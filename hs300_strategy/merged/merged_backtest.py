"""
合并版（Plan C 估值定投 + 分批趋势卖出）回测与稳健性检验。

同时实现两个版本，用完全相同的引擎、费用和资金流口径比较：
  - planc   : Plan C v1.0 原版——S<25 且 U≤阈值 时一次性清仓
  - graded  : 合并版 v2.0——S<25 时持仓按 U 分档"只减不加"（棘轮），S>58 回补
  - nosell  : 只定投、从不卖出（衡量卖出规则本身的价值）

输入 CSV（二选一）：
  A. date, close, S                    —— 直接使用你算好的估值分 S
  B. date, close, pe, pb, dy, y10      —— 由原始数据计算 S（可额外检验百分位窗口）
  可选列 signal_close：计算均线用的价格序列（缺省用 close）。close 应为实际成交价格（场外基金净值或全收益指数）。

用法:
  python merged_backtest.py --csv 你的数据.csv            # 复现检查 + 对比 + 稳健性检验
  python merged_backtest.py --demo                        # 用价格构造的假 S 测试代码能否跑通（结果无意义）
"""
from __future__ import annotations

import argparse
import itertools
import os
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 1. 参数（默认值 = Plan C v1.0 冻结参数）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Params:
    mode: str = "planc"            # planc / graded / nosell
    sell_thr: float = 25.0         # S < sell_thr 进入卖出区
    resume_thr: float = 58.0       # S > resume_thr 资金池回补
    ma_windows: tuple = (40, 80, 160)
    u_thr: float = 1 / 3           # 仅 planc 使用：U ≤ u_thr 清仓
    stop_s: float = 30.0           # S ≤ 30 不买
    power: float = 2.5             # 买入曲线指数
    daily_cap: float = 250.0       # 每日额度
    min_order: float = 10.0        # 挂账满 10 元成交
    buy_fee: float = 0.0012
    sell_fee: float = 0.005
    pct_years: int = 15            # 仅在由原始数据计算 S 时使用
    pct_min: int = 504


P0 = Params()


# ---------------------------------------------------------------------------
# 2. 指标
# ---------------------------------------------------------------------------
def compute_s(df: pd.DataFrame, years: int = 15, min_n: int = 504) -> pd.Series:
    """S = [(100 − PB百分位) + 股息率百分位 + ERP百分位] / 3，过去 years 个日历年滚动百分位。"""
    win = f"{int(round(years * 365.25))}D"
    pct = lambda x: x.rolling(win, min_periods=min_n).rank(pct=True) * 100
    erp = 100 / df["pe"] - df["y10"]
    return ((100 - pct(df["pb"])) + pct(df["dy"]) + pct(erp)) / 3


def compute_u(price: pd.Series, windows: tuple) -> pd.Series:
    """U = 站上各均线的比例；等于均线不算站上；均线未形成时为 NaN。"""
    votes = [(price > price.rolling(k).mean()).astype(float).where(price.rolling(k).mean().notna())
             for k in windows]
    return sum(votes) / len(votes)


# ---------------------------------------------------------------------------
# 3. 引擎（逐日；T-1 日信号，T 日收盘成交）
# ---------------------------------------------------------------------------
def simulate(close: pd.Series, S: pd.Series, U: pd.Series, p: Params = P0, log=False):
    dates = close.index
    px = close.to_numpy(float)
    s_prev = S.shift(1).to_numpy(float)
    u_prev = U.shift(1).to_numpy(float)

    shares = pool = pending = 0.0
    waiting = False
    ratchet = 1.0                      # graded：卖出区内已到达的最低 U
    deposit = np.zeros(len(px)); value = np.zeros(len(px))
    events = []

    def sell(frac, i, tag):
        nonlocal shares, pool
        q = shares * frac
        if q <= 0:
            return
        pool += q * px[i] * (1 - p.sell_fee)
        shares -= q
        events.append((dates[i], tag, s_prev[i], u_prev[i], px[i], frac))

    for i in range(len(px)):
        s, u = s_prev[i], u_prev[i]
        if np.isnan(s) or np.isnan(u):
            value[i] = shares * px[i] + pool + pending
            continue
        skip_buy = False

        # —— 回补 ——
        if s > p.resume_thr and (waiting or ratchet < 1 or pool > 0):
            if pool > 0:
                shares += pool * (1 - p.buy_fee) / px[i]
                events.append((dates[i], "回补", s, u, px[i], pool))
                pool = 0.0
            waiting, ratchet = False, 1.0

        # —— 卖出 ——
        if not waiting and p.mode != "nosell" and s < p.sell_thr:
            if p.mode == "planc" and u <= p.u_thr + 1e-9:
                sell(1.0, i, "清仓")
                waiting, skip_buy = True, True
            elif p.mode == "graded" and u < ratchet - 1e-9:
                sell(1 - u / ratchet, i, f"减至U={u:.2f}")
                ratchet = u
                if u <= 1e-9:
                    waiting, skip_buy = True, True
            if waiting:                 # 清仓日：挂账转入资金池
                pool += pending; pending = 0.0

        # —— 定投 ——
        if not waiting and not skip_buy:
            x = min(max((s - p.stop_s) / (100 - p.stop_s), 0.0), 1.0)
            amt = p.daily_cap * x ** p.power
            if amt > 0:
                deposit[i] = amt
                pending += amt
                if pending >= p.min_order:
                    shares += pending * (1 - p.buy_fee) / px[i]
                    pending = 0.0
        value[i] = shares * px[i] + pool + pending

    res = pd.DataFrame({"deposit": deposit, "value": value}, index=dates)
    return (res, events) if log else res


# ---------------------------------------------------------------------------
# 4. 绩效：XIRR、TWR、投资账户最大回撤
# ---------------------------------------------------------------------------
def xirr(dates: pd.DatetimeIndex, flows: np.ndarray) -> float:
    t = (dates - dates[0]).days / 365.25
    f = lambda r: np.sum(flows / (1 + r) ** t)
    lo, hi = -0.99, 10.0
    if f(lo) * f(hi) > 0:
        return np.nan
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def perf(res: pd.DataFrame) -> dict:
    r = res[res["value"] > 0]
    flows = -r["deposit"].to_numpy().copy()
    flows[-1] += r["value"].iloc[-1]
    v, d = r["value"].to_numpy(), r["deposit"].to_numpy()
    ret = (v[1:] - d[1:]) / v[:-1] - 1
    twr = np.cumprod(1 + ret)
    years = (r.index[-1] - r.index[0]).days / 365.25
    dd = (twr / np.maximum.accumulate(twr) - 1).min()
    twr_cagr = twr[-1] ** (1 / years) - 1
    return {"累计本金": r["deposit"].sum(), "期末价值": v[-1], "XIRR": xirr(r.index, flows),
            "TWR年化": twr_cagr, "最大回撤": dd, "Calmar": twr_cagr / abs(dd)}


# ---------------------------------------------------------------------------
# 5. 检验
# ---------------------------------------------------------------------------
def run_one(df, p: Params, S=None):
    S = df["S"] if S is None else S
    sig = df["signal_close"] if "signal_close" in df else df["close"]
    return simulate(df["close"], S, compute_u(sig, p.ma_windows), p, log=True)


def replication_check(df) -> str:
    res, ev = run_one(df, P0)
    m = perf(res)
    sells = [str(e[0].date()) for e in ev if e[1] == "清仓"]
    expect = ["2015-06-29", "2018-02-08", "2021-03-09"]
    return (f"原版本金 {m['累计本金']:,.0f} 元（规则书：161,694）；"
            f"XIRR {m['XIRR']:.2%}（规则书：11.59%）\n"
            f"原版清仓日 {sells}（规则书：{expect}）\n"
            "→ 两者一致（允许 ±1 个交易日、本金差 <0.5%）才说明脚本与你的原回测口径相同，之后的对比才有意义。")


def grid(df, has_raw: bool) -> pd.DataFrame:
    MA = {"短40/80/160": (40, 80, 160), "中60/120/240": (60, 120, 240), "长80/160/320": (80, 160, 320)}
    rows = []
    s_windows = (10, 15, 20) if has_raw else (None,)
    for yrs in s_windows:
        S = compute_s(df, yrs) if yrs else df["S"]
        for sell_thr, resume_thr, (mk, ma) in itertools.product((20, 25, 30), (53, 58, 63), MA.items()):
            base = replace(P0, sell_thr=sell_thr, resume_thr=resume_thr, ma_windows=ma)
            variants = [("graded", "—", replace(base, mode="graded"))]
            variants += [("planc", f"{u:.2f}", replace(base, mode="planc", u_thr=u)) for u in (0, 1 / 3, 2 / 3)]
            for mode, ut, p in variants:
                m = perf(run_one(df, p, S)[0])
                rows.append({"版本": mode, "U阈值": ut, "估值窗口": yrs or "给定S", "卖出线": sell_thr,
                             "回补线": resume_thr, "均线组": mk, **m})
    return pd.DataFrame(rows)


def placebo(df, p: Params, n=200, seed=7) -> np.ndarray:
    """把 U 序列整体循环平移随机天数：保留 U 的统计特征，破坏它与估值和行情的时间对齐。"""
    rng = np.random.default_rng(seed)
    sig = df["signal_close"] if "signal_close" in df else df["close"]
    U = compute_u(sig, p.ma_windows)
    valid = U.dropna()
    out = []
    for _ in range(n):
        k = int(rng.integers(250, len(valid) - 250))
        Us = pd.Series(np.roll(valid.to_numpy(), k), index=valid.index).reindex(U.index)
        out.append(perf(simulate(df["close"], df["S"], Us, p))["XIRR"])
    return np.array(out)


def summarize(G: pd.DataFrame) -> pd.DataFrame:
    def stats(g):
        q = g["XIRR"].quantile([.25, .5, .75])
        return pd.Series({"格数": len(g), "XIRR中位": q[.5], "XIRR四分位距": q[.75] - q[.25],
                          "XIRR极差": g["XIRR"].max() - g["XIRR"].min(),
                          "最大回撤中位": g["最大回撤"].median(), "Calmar中位": g["Calmar"].median()})
    out = {"合并版 graded": stats(G[G["版本"] == "graded"]),
           "原版 U≤1/3": stats(G[(G["版本"] == "planc") & (G["U阈值"] == "0.33")]),
           "原版 全部U阈值": stats(G[G["版本"] == "planc"])}
    return pd.DataFrame(out).T


def verdict(T: pd.DataFrame, tol: float) -> str:
    g, c = T.loc["合并版 graded"], T.loc["原版 U≤1/3"]
    checks = [("跨参数四分位距更小", g["XIRR四分位距"] < c["XIRR四分位距"]),
              (f"XIRR中位数下降 ≤ {tol * 100:.1f}pp", g["XIRR中位"] >= c["XIRR中位"] - tol),
              ("最大回撤中位数恶化 ≤ 2pp", g["最大回撤中位"] >= c["最大回撤中位"] - 0.02)]
    lines = [f"- {'✓' if ok else '✗'} {name}" for name, ok in checks]
    adopt = all(ok for _, ok in checks)
    return "\n".join(lines) + f"\n\n**事前判定：{'采纳合并版 v2.0' if adopt else '保留 Plan C v1.0'}**"


# ---------------------------------------------------------------------------
# 6. 入口
# ---------------------------------------------------------------------------
def demo_data() -> pd.DataFrame:
    """仅用于测试代码：用价格在过去 15 年中的百分位倒数伪造一个 S。不代表任何估值信息。"""
    px = pd.read_csv(os.path.join(HERE, "..", "data", "hs300.csv"), parse_dates=["date"]).set_index("date")["close"]
    fake_s = 100 - px.rolling("5479D", min_periods=504).rank(pct=True) * 100
    return pd.DataFrame({"close": px, "S": fake_s}).loc["2013-11-07":]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--placebo", type=int, default=200)
    ap.add_argument("--tolerance", type=float, default=0.005,
                    help="可接受的 XIRR 中位数下降幅度，必须在运行前决定（默认 0.005 即 0.5pp）")
    a = ap.parse_args()
    if a.demo:
        df = demo_data()
        print("【演示模式】S 是用价格伪造的，以下数字只用于确认代码能跑通，不代表策略表现。\n")
    else:
        df = pd.read_csv(a.csv, parse_dates=["date"]).set_index("date").sort_index()
    has_raw = {"pe", "pb", "dy", "y10"} <= set(df.columns)
    if "S" not in df:
        df["S"] = compute_s(df)
    df = df.loc[df["S"].first_valid_index():]

    out = os.path.join(HERE, "results_demo" if a.demo else "results")
    os.makedirs(out, exist_ok=True)
    rep = ["# 合并版 vs Plan C 检验报告\n"]

    rep.append("## 1. 复现检查\n\n" + replication_check(df) + "\n")

    rows, logs = {}, []
    for name, p in [("Plan C 原版", P0), ("合并版 v2.0", replace(P0, mode="graded")),
                    ("只定投不卖出", replace(P0, mode="nosell"))]:
        res, ev = run_one(df, p)
        rows[name] = perf(res)
        logs += [f"| {name} | {e[0].date()} | {e[1]} | {e[2]:.1f} | {e[3]:.2f} | {e[4]:.2f} |" for e in ev]
    T = pd.DataFrame(rows).T
    rep.append("## 2. 默认参数对比\n\n" + T.to_markdown(floatfmt=",.4f") + "\n")
    rep.append("### 交易事件\n\n| 版本 | 日期 | 动作 | S(T-1) | U(T-1) | 成交价 |\n|---|---|---|---|---|---|\n"
               + "\n".join(logs) + "\n")

    G = grid(df, has_raw)
    G.to_csv(os.path.join(out, "grid.csv"), index=False)
    ST = summarize(G)
    rep.append("## 3. 参数邻域（卖出线 20/25/30 × 回补线 53/58/63 × 三组均线"
               + (" × 估值窗口 10/15/20 年" if has_raw else "") + "）\n\n"
               + ST.to_markdown(floatfmt=".4f") + "\n\n### 事前设定的采纳标准\n\n" + verdict(ST, a.tolerance) + "\n")

    if a.placebo:
        rep_lines = []
        for name, p in [("Plan C 原版", P0), ("合并版 v2.0", replace(P0, mode="graded"))]:
            null = placebo(df, p, a.placebo)
            real = rows[name]["XIRR"]
            rep_lines.append(f"| {name} | {real:.2%} | {np.median(null):.2%} | {np.mean(null >= real):.0%} |")
        rep.append("## 4. 安慰剂：趋势信号错位后还剩多少\n\n| 版本 | 真实 XIRR | 错位 U 的 XIRR 中位 | 错位后不差于真实的比例 |\n"
                   "|---|---|---|---|\n" + "\n".join(rep_lines)
                   + "\n\n比例越低，说明趋势信号的『时机』确实贡献了收益；接近 50% 说明卖出规则的价值主要来自估值条件本身。\n")

    text = "\n".join(rep)
    with open(os.path.join(out, "report.md"), "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
