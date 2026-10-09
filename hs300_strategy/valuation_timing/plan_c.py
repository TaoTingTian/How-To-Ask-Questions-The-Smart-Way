#!/usr/bin/env python3
"""
Plan C 规则书（v1.0 冻结）回测引擎 + 百分位方法测试
====================================================

交易规则逐条按《沪深300估值百分位动态仓位策略 · Plan C 完整规则书》实现（见 PLAN_C_REPORT.md 第 1 节）；
本脚本的研究目的：**规则其余部分全部冻结，只替换"百分位"的计算方式**，检验结论对百分位方法的依赖。

运行：python plan_c.py   （依赖与 backtest.py 相同）
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import optimize, stats

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import backtest as bt  # 复用数据读取、百分位函数、配色、DSR/CSCV 工具

OUT = bt.HERE / "output_planc"
FIG = OUT / "figures"


# ============================== 规则书参数（冻结） ==============================
@dataclass(frozen=True)
class Rules:
    sell_thr: float = 25.0        # S < 25
    resume_thr: float = 58.0      # S > 58
    u_max: float = 1 / 3          # U ≤ 1/3
    ma: tuple = (40, 80, 160)
    zero_line: float = 30.0       # x = clip((S-30)/70, 0, 1)
    span: float = 70.0
    power: float = 2.5
    daily_cap: float = 250.0
    min_order: float = 10.0       # 挂账满 10 元成交
    fee_buy: float = 0.0012
    fee_sell: float = 0.005


RULES = Rules()
SELL_GRID = [15, 20, 25, 30]          # 对应原需求 15/85…30/70 中的"贵"侧阈值（S<25 ⇔ 贵度>75）
RESUME_GRID = [50, 58, 66, 75]
PCT_15Y_DAYS = "5479D"                # 15 个日历年
PCT_MIN_OBS = 504


# ============================== 百分位 → S ==============================
def pct_rulebook(x: pd.Series) -> pd.Series:
    """规则书口径：过去 15 个日历年滚动窗口、至少 504 个样本的排名百分位（0~100，越高值越大）。"""
    return x.rolling(PCT_15Y_DAYS, min_periods=PCT_MIN_OBS).rank(pct=True) * 100


def raw_percentiles(df: pd.DataFrame) -> dict:
    """不取负的原始百分位（值越大分位越高），与规则书公式一致：PB 用 100−分位，DY/ERP 直接用分位。"""
    years = sorted({w for v in bt.SPECS.values() for w in v[1]})
    return {ind: {"win": {w: bt.expensiveness(df[ind], +1, w * bt.DAYS_PER_YEAR_WINDOW) for w in years},
                  "exp": bt.expensiveness(df[ind], +1, None)} for ind in bt.INDICATORS}


def cheapness_by_spec(df: pd.DataFrame, raw: dict, ind: str, spec: str) -> pd.Series:
    """"便宜度"(0~100，越高越便宜)。PE/PB：100 − 分位；ERP/DY：分位。spec='规则书15年' 为规则书口径。"""
    p = pct_rulebook(df[ind]) if spec == "规则书15年" else 100 * bt.spec_signal(raw[ind], spec)
    return 100 - p if bt.INDICATORS[ind][1] > 0 else p


SPECS = ["规则书15年"] + list(bt.SPECS)
S_DEFS = {  # S 的构成：规则书为 PB、DY、ERP 三者等权；另测单指标 S（四指标分别计算）
    "S(规则书:PB+DY+ERP)": ["PB", "DY", "ERP"],
    "S=ERP": ["ERP"], "S=PE": ["PE"], "S=PB": ["PB"], "S=DY": ["DY"],
}
MAIN_S = "S(规则书:PB+DY+ERP)"


def build_S(df, pcts) -> dict[tuple[str, str], pd.Series]:
    out = {}
    for spec in SPECS:
        ch = {i: cheapness_by_spec(df, pcts, i, spec) for i in bt.INDICATORS}
        for sname, comps in S_DEFS.items():
            m = pd.concat([ch[c] for c in comps], axis=1)
            out[(sname, spec)] = m.mean(axis=1).where(m.notna().all(axis=1))
    return out


def trend_U(px: pd.Series, mas=(40, 80, 160)) -> pd.Series:
    u = sum((px > px.rolling(k, min_periods=k).mean()).astype(float) for k in mas) / len(mas)
    return u.where(px.rolling(max(mas), min_periods=max(mas)).mean().notna())


# ============================== 引擎 ==============================
def simulate(S: pd.Series, U: pd.Series, px: pd.Series, start, end, r: Rules = RULES):
    """T-1 收盘的 S、U 决策，T 日收盘价成交。返回逐日账本与事件列表。start 当天为首个决策日。"""
    idx = px.loc[start:end].index
    Sx, Ux = S.shift(1).reindex(idx), U.shift(1).reindex(idx)
    if Sx.isna().any() or Ux.isna().any():
        return None
    P = px.reindex(idx).values
    s_arr, u_arr = Sx.values, Ux.values
    units = pool = pending = 0.0
    waiting = False
    n = len(idx)
    dep = np.zeros(n); val = np.zeros(n); hold = np.zeros(n)
    sold = np.zeros(n); rebuy = np.zeros(n); bought = np.zeros(n)
    events = []
    for t in range(n):
        s, u, p = s_arr[t], u_arr[t], P[t]
        if waiting:
            if s > r.resume_thr:
                units += pool * (1 - r.fee_buy) / p
                rebuy[t] = pool
                events.append((idx[t], "恢复回补", s, p, pool))
                pool, waiting = 0.0, False
        elif s < r.sell_thr and u <= r.u_max + 1e-12:
            if units > 0:
                proceeds = units * p * (1 - r.fee_sell)
                sold[t] = units * p
                pool += proceeds
                units = 0.0
            events.append((idx[t], "清仓", s, p, sold[t]))
            waiting = True
        if not waiting and rebuy[t] == 0:          # 正常定投（回补当日不再另行定投）
            x = min(max((s - r.zero_line) / r.span, 0.0), 1.0)
            a = r.daily_cap * x ** r.power
            if a > 0:
                dep[t] = a
                pending += a
                if pending >= r.min_order:
                    units += pending * (1 - r.fee_buy) / p
                    bought[t] = pending
                    pending = 0.0
        hold[t] = units * p
        val[t] = hold[t] + pool + pending
    led = pd.DataFrame({"deposit": dep, "value": val, "holding": hold, "sold": sold, "rebuy": rebuy,
                        "bought": bought}, index=idx)
    return led, events


def xirr(dates, flows) -> float:
    t = np.array([(d - dates[0]).days / 365.25 for d in dates])
    f = np.array(flows)
    if not (f < 0).any() or not (f > 0).any():
        return np.nan
    g = lambda rate: np.sum(f / (1 + rate) ** t)  # noqa: E731
    try:
        return optimize.brentq(g, -0.99, 10)
    except ValueError:
        return np.nan


TWR_MIN_BASE = 1000.0  # 账户规模过小时（新入金的申购费相对基数过大）不计 TWR


def twr_series(led: pd.DataFrame) -> pd.Series:
    """投资账户时间加权收益：r_t = (V_t − 当日入金) / V_{t-1} − 1；从 V_{t-1} ≥ 1000 元起计。"""
    v, d = led["value"].values, led["deposit"].values
    r = np.full(len(v), np.nan)
    for t in range(1, len(v)):
        if v[t - 1] >= TWR_MIN_BASE:
            r[t] = (v[t] - d[t]) / v[t - 1] - 1
    return pd.Series(r, index=led.index).dropna()


def evaluate(led: pd.DataFrame, events) -> dict:
    tw = twr_series(led)
    nav = (1 + tw).cumprod()
    peak = np.maximum.accumulate(np.r_[1.0, nav.values])[1:]
    mdd = float((nav.values / peak - 1).min())
    yrs = len(tw) / bt.ANN
    twr = nav.iloc[-1] ** (1 / yrs) - 1
    dep = led["deposit"]
    flows_d = list(led.index[dep > 0]) + [led.index[-1]]
    flows = list(-dep[dep > 0].values) + [led["value"].iloc[-1]]
    avg_v = led["value"].replace(0, np.nan).mean()
    w = (led["holding"] / led["value"].replace(0, np.nan)).dropna()
    return {
        "累计本金": dep.sum(), "期末价值": led["value"].iloc[-1],
        "总盈利率": led["value"].iloc[-1] / dep.sum() - 1 if dep.sum() > 0 else np.nan,
        "XIRR": xirr(flows_d, flows), "XIRR连续复利": math.log1p(xirr(flows_d, flows)), "TWR年化": twr, "年化波动": tw.std() * math.sqrt(bt.ANN),
        "夏普": tw.mean() / tw.std() * math.sqrt(bt.ANN), "最大回撤": mdd,
        "卡玛": twr / abs(mdd) if mdd < 0 else np.nan,
        "年换手率": (led["sold"].sum() + led["rebuy"].sum()) / 2 / avg_v / (len(led) / bt.ANN),
        "平均仓位": w.mean(),
        "清仓次数": sum(e[1] == "清仓" for e in events), "回补次数": sum(e[1] == "恢复回补" for e in events),
        "定投成交次数": int((led["bought"] > 0).sum()),
        "交易次数": int((led["bought"] > 0).sum() + (led["sold"] > 0).sum() + (led["rebuy"] > 0).sum()),
        "起始日": led.index[0].date(),
    }


def bench_same_flows(led: pd.DataFrame, px: pd.Series, r: Rules = RULES) -> pd.DataFrame:
    """对照1：同样的每日入金，挂账满10元买入，永不卖出（只去掉清仓/回补，保留估值加权定投）。"""
    P = px.reindex(led.index).values
    units = pending = 0.0
    val = np.zeros(len(led)); hold = np.zeros(len(led)); bought = np.zeros(len(led))
    for t, a in enumerate(led["deposit"].values):
        pending += a
        if pending >= r.min_order:
            units += pending * (1 - r.fee_buy) / P[t]
            bought[t] = pending
            pending = 0.0
        hold[t] = units * P[t]
        val[t] = hold[t] + pending
    return pd.DataFrame({"deposit": led["deposit"].values, "value": val, "holding": hold, "sold": 0.0,
                         "rebuy": 0.0, "bought": bought}, index=led.index)


def bench_fixed_dca(led: pd.DataFrame, px: pd.Series, r: Rules = RULES) -> pd.DataFrame:
    """对照2：总本金相同的每日等额定投（不看估值）。"""
    fake = led.copy()
    fake["deposit"] = led["deposit"].sum() / len(led)
    return bench_same_flows(fake, px, r)


# ============================== 主流程 ==============================
def main():
    OUT.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    df, px = bt.load_data()
    bt.ANN = len(px) / ((px.index[-1] - px.index[0]).days / 365.25)
    ret = px.pct_change().fillna(0.0)
    pcts = raw_percentiles(df)
    Smap = build_S(df, pcts)
    U = trend_U(px, RULES.ma)
    END = "2026-09-30"
    md = []

    # ---------- 0) 复现规则书原始结果 ----------
    S0 = Smap[(MAIN_S, "规则书15年")]
    first = S0.first_valid_index()
    led0, ev0 = simulate(S0, U, px, px.index[px.index.get_loc(first) + 1], END)
    m0 = evaluate(led0, ev0)
    book = {"累计本金": 161694, "期末价值": 362788, "XIRR连续复利": 0.1159, "XIRR": np.nan, "TWR年化": 0.1257, "最大回撤": -0.318,
            "卡玛": 0.40, "清仓次数": 3}
    rep = pd.DataFrame({"规则书": book, "本脚本复现": {k: m0[k] for k in book}})
    md.append(f"## 表0 复现规则书原始结果（规则书15年百分位，S 首个有效日 {first.date()}，首个决策日 {led0.index[0].date()}）\n")
    md.append(rep.to_markdown(floatfmt=".4f"))
    md.append("\n事件：\n")
    md.append(pd.DataFrame(ev0, columns=["日期", "事件", "T-1日S", "成交价", "金额"]).assign(
        日期=lambda d: d["日期"].dt.date).round(2).to_markdown(index=False))

    # ---------- 1) 试验集合 ----------
    MAIN_WIN = (bt.MAIN_WIN[0], END)
    FULL_START = led0.index[0]

    def run_cfg(sname, spec, start, end=END, rules=RULES):
        res = simulate(Smap[(sname, spec)], U, px, start, end, rules)
        return None if res is None else res

    trials = {}
    for sname in S_DEFS:
        for spec in SPECS:
            for st in SELL_GRID:
                trials[(sname, spec, st, RULES.resume_thr)] = Rules(sell_thr=st)
    for spec in SPECS:  # 阈值热力图的第二维（仅规则书 S）
        for st, rs in itertools.product(SELL_GRID, RESUME_GRID):
            trials.setdefault((MAIN_S, spec, st, rs), Rules(sell_thr=st, resume_thr=rs))
    n_trials = len(trials)

    def table(start, keys):
        rows, ledgers = {}, {}
        for k in keys:
            res = run_cfg(k[0], k[1], start, rules=trials[k])
            if res is None:
                rows[k] = {}
                continue
            led, ev = res
            m = evaluate(led, ev)
            b1 = evaluate(bench_same_flows(led, px), [])
            b2 = evaluate(bench_fixed_dca(led, px), [])
            m.update({"对照1_同入金不卖XIRR": b1["XIRR"], "对照1_MDD": b1["最大回撤"], "对照1_夏普": b1["夏普"],
                      "对照2_等额定投XIRR": b2["XIRR"], "XIRR−对照1": m["XIRR"] - b1["XIRR"],
                      "夏普−对照1": m["夏普"] - b1["夏普"]})
            rows[k] = m
            ledgers[k] = led
        T = pd.DataFrame(rows).T
        T.index = pd.MultiIndex.from_tuples(T.index, names=["S构成", "百分位方法", "清仓阈值", "回补阈值"])
        return T, ledgers

    base_keys = [(MAIN_S, spec, RULES.sell_thr, RULES.resume_thr) for spec in SPECS]
    b_main = bt.perf(bt.run(pd.Series(1.0, index=px.index), ret, *MAIN_WIN, cost=0.0))
    cols = ["累计本金", "期末价值", "XIRR", "XIRR连续复利", "TWR年化", "年化波动", "夏普", "最大回撤", "卡玛", "年换手率",
            "平均仓位", "交易次数", "清仓次数", "对照1_同入金不卖XIRR", "对照1_MDD", "对照2_等额定投XIRR", "XIRR−对照1", "夏普−对照1"]
    PCT = ("XIRR", "XIRR连续复利", "TWR年化", "年化波动", "最大回撤", "平均仓位", "对照1_同入金不卖XIRR", "对照1_MDD",
           "对照2_等额定投XIRR", "XIRR−对照1")
    F2 = ("夏普", "卡玛", "年换手率", "夏普−对照1")
    F0 = ("累计本金", "期末价值", "交易次数", "清仓次数")

    # 规则书全区间（各百分位方法若在 2013-11-08 无信号则记为不可评估）
    T_full, _ = table(FULL_START, base_keys)
    T_full.to_csv(OUT / "table_rulebook_window.csv", encoding="utf-8-sig")
    md.append(f"\n## 表1 规则书全区间 {FULL_START.date()} ~ {END}（规则书 S，阈值 25/58；空行=该百分位方法在起点无信号）\n")
    md.append(bt.fmt_table(T_full[cols], PCT, F2, F0))

    # 各方法自身首个有效日起
    own_rows = {}
    for k in base_keys:
        s = Smap[(k[0], k[1])]
        st = px.index[px.index.get_loc(s.first_valid_index()) + 1]
        led, ev = simulate(s, U, px, st, END)
        m = evaluate(led, ev)
        b1 = evaluate(bench_same_flows(led, px), [])
        m.update({"对照1_同入金不卖XIRR": b1["XIRR"], "对照1_MDD": b1["最大回撤"], "XIRR−对照1": m["XIRR"] - b1["XIRR"],
                  "夏普−对照1": m["夏普"] - b1["夏普"],
                  "事件": "；".join(f"{e[1]}{e[0].date()}" for e in ev)})
        own_rows[k[1]] = m
    T_own = pd.DataFrame(own_rows).T
    T_own.index.name = "百分位方法"
    T_own.to_csv(OUT / "table_own_start.csv", encoding="utf-8-sig")
    md.append("\n## 表2 各百分位方法自身首个有效日起（规则书 S，阈值 25/58）与清仓/回补事件\n")
    md.append(bt.fmt_table(T_own[["起始日", "XIRR", "TWR年化", "夏普", "最大回撤", "卡玛", "清仓次数",
                                  "对照1_同入金不卖XIRR", "对照1_MDD", "XIRR−对照1", "事件"]],
                           PCT, F2, F0))

    # 主比较区间（所有方法同一起点，除单窗10年）
    T_main, led_main = table(MAIN_WIN[0], base_keys)
    T_main.to_csv(OUT / "table_main_window.csv", encoding="utf-8-sig")
    md.append(f"\n## 表3 主比较区间 {MAIN_WIN[0]} ~ {END}（同一天开始定投；规则书 S，阈值 25/58）\n")
    md.append(f"参考：沪深300 一次性买入持有 年化 {b_main['年化收益'] * 100:.1f}%、夏普 {b_main['夏普']:.2f}、最大回撤 {b_main['最大回撤'] * 100:.1f}%\n")
    md.append(bt.fmt_table(T_main[cols], PCT, F2, F0))

    # 四指标单独 S（同一主区间、阈值 25/58）
    ind_keys = [(s, spec, RULES.sell_thr, RULES.resume_thr) for s in S_DEFS if s != MAIN_S for spec in SPECS]
    T_ind, _ = table(MAIN_WIN[0], ind_keys)
    T_ind.to_csv(OUT / "table_single_indicator_S.csv", encoding="utf-8-sig")
    md.append("\n## 表4 四个指标分别作为 S（主区间，阈值 25/58；PE 不在规则书 S 内，此处单独测试）\n")
    md.append(bt.fmt_table(T_ind[["XIRR", "TWR年化", "夏普", "最大回撤", "卡玛", "清仓次数", "平均仓位",
                                  "对照1_同入金不卖XIRR", "XIRR−对照1", "夏普−对照1"]], PCT, F2, F0))
    grp = pd.concat([T_main, T_ind]).dropna(subset=["XIRR"]).groupby(level="S构成")[["XIRR", "夏普", "最大回撤", "XIRR−对照1", "清仓次数"]].agg(["min", "max"])
    md.append("\n### 表4b 按 S 构成分组（各百分位方法的最小/最大）\n")
    md.append(grp.astype(float).round(3).to_markdown())

    # ---------- 2) 全部试验在主区间 ----------
    T_all, led_all = table(MAIN_WIN[0], list(trials))
    T_all.to_csv(OUT / "table_all_trials_main_window.csv", encoding="utf-8-sig")
    valid = T_all.dropna(subset=["XIRR"])

    # 阈值热力图：清仓阈值 × 回补阈值，每个百分位方法一格（XIRR 与 MDD）
    for metric, fname, fmt in [("XIRR", "fig_heatmap_xirr.png", lambda v: f"{v * 100:.1f}"),
                               ("最大回撤", "fig_heatmap_mdd.png", lambda v: f"{v * 100:.0f}")]:
        specs_plot = [s for s in SPECS if s != "单窗10年"]
        fig, axes = plt.subplots(2, 5, figsize=(20, 8.2), sharex=True, sharey=True)
        vals = T_all.xs(MAIN_S, level="S构成")[metric].astype(float)
        vmin, vmax = np.nanmin(vals), np.nanmax(vals)
        cmap = plt.get_cmap("Blues" if metric == "XIRR" else "Blues_r")
        for ax, spec in zip(axes.flat, specs_plot):
            M = vals.xs(spec, level="百分位方法").unstack("回补阈值").reindex(index=SELL_GRID, columns=RESUME_GRID)
            im = ax.imshow(M.values, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
            for (i, j), v in np.ndenumerate(M.values):
                ax.text(j, i, "—" if np.isnan(v) else fmt(v), ha="center", va="center", fontsize=9,
                        color="white" if (v - vmin) / (vmax - vmin + 1e-12) > (0.6 if metric == "XIRR" else 2) or
                        (metric != "XIRR" and (v - vmin) / (vmax - vmin + 1e-12) < 0.35) else bt.INK)
            ax.add_patch(plt.Rectangle((RESUME_GRID.index(58) - .5, SELL_GRID.index(25) - .5), 1, 1, fill=False,
                                       ec=bt.SERIES[1], lw=2))
            ax.set_title(spec, color=bt.INK, fontsize=11)
            ax.set_xticks(range(4), RESUME_GRID)
            ax.set_yticks(range(4), SELL_GRID)
            ax.grid(False)
        for ax in axes[1]:
            ax.set_xlabel("回补阈值 S>")
        for ax in axes[:, 0]:
            ax.set_ylabel("清仓阈值 S<")
        fig.colorbar(im, ax=axes, shrink=0.8, label=metric)
        fig.suptitle(f"Plan C 阈值热力图：{metric}（%；主区间 {MAIN_WIN[0]}~{END}；橙框=规则书 25/58）", color=bt.INK)
        bt.savefig_dir = None
        fig.savefig(FIG / fname, bbox_inches="tight")
        plt.close(fig)
    hm = T_all.xs(MAIN_S, level="S构成")[["XIRR", "最大回撤", "清仓次数"]].astype(float)
    hm_x = hm["XIRR"].unstack(["清仓阈值", "回补阈值"])
    md.append("\n## 表5 阈值稳健性：规则书 S，各百分位方法在 4×4 阈值网格上的 XIRR（主区间）\n")
    stat = pd.DataFrame({"25/58 XIRR": hm["XIRR"].xs((25, 58), level=["清仓阈值", "回补阈值"]),
                         "网格最小": hm_x.min(axis=1), "网格最大": hm_x.max(axis=1),
                         "网格中位": hm_x.median(axis=1),
                         "25/58 在网格内排名": hm_x.rank(axis=1, ascending=False)[(25, 58)],
                         "清仓次数范围": hm["清仓次数"].unstack(["清仓阈值", "回补阈值"]).apply(
                             lambda r: f"{int(r.min())}~{int(r.max())}" if r.notna().any() else "—", axis=1)})
    md.append(bt.fmt_table(stat, ("25/58 XIRR", "网格最小", "网格最大", "网格中位"), (), ("25/58 在网格内排名",)))
    # 原需求的 4 档阈值（清仓阈值 15/20/25/30，回补固定 58），5 种 S 全部方法
    md.append("\n### 表5b 清仓阈值 15/20/25/30（回补固定 58）下的 XIRR，全部 S 构成\n")
    sub = T_all.xs(58, level="回补阈值")["XIRR"].astype(float).unstack("清仓阈值")
    md.append(sub.map(lambda v: "—" if pd.isna(v) else f"{v * 100:.2f}%").reset_index().to_markdown(index=False))

    # ---------- 3) 试验次数、DSR、PBO ----------
    R = pd.DataFrame({k: twr_series(led_all[k]) for k in valid.index}).dropna()
    rho, n_eff_rho, n_eff_eig = bt.effective_n(R)
    sr_pp = R.mean() / R.std(ddof=1)
    best = sr_pp.idxmax()
    best_x = valid["XIRR"].astype(float).idxmax()
    # 相对对照1（同入金不卖）的主动 TWR 收益
    A = pd.DataFrame({k: twr_series(led_all[k]) - twr_series(bench_same_flows(led_all[k], px)) for k in valid.index}).dropna()
    ir_pp = A.mean() / A.std(ddof=1)
    best_ir = ir_pp.idxmax()
    rows = []
    for lab, n in [("全部试验 N", n_trials), ("主区间可评估 N", len(valid)), ("有效 N（平均相关）", n_eff_rho),
                   ("有效 N（特征值）", n_eff_eig)]:
        sr0 = bt.expected_max_sr(sr_pp.var(ddof=1), n)
        rows.append({"检验": "TWR 夏普 > SR0", "N 口径": lab, "N": n, "SR0(年化)": sr0 * math.sqrt(bt.ANN),
                     "最优(年化)": sr_pp[best] * math.sqrt(bt.ANN), "DSR": bt.psr(R[best], sr0)})
        sr0a = bt.expected_max_sr(ir_pp.var(ddof=1), n)
        rows.append({"检验": "相对对照1 的 IR > SR0", "N 口径": lab, "N": n, "SR0(年化)": sr0a * math.sqrt(bt.ANN),
                     "最优(年化)": ir_pp[best_ir] * math.sqrt(bt.ANN), "DSR": bt.psr(A[best_ir], sr0a)})
    DSR = pd.DataFrame(rows)
    DSR.to_csv(OUT / "table_dsr.csv", encoding="utf-8-sig", index=False)
    pbo, lam, slope = bt.cscv_pbo(R, 10)
    pbo_a, _, slope_a = bt.cscv_pbo(A, 10)
    md.append("\n## 表6 试验次数、DSR 与 PBO（主区间）\n")
    md.append(f"- 试验总数 **{n_trials}** = 5 种 S × 11 种百分位方法 × 4 个清仓阈值（回补 58）"
              f" + 规则书 S × 11 × 其余 12 个阈值格；主区间可评估 {len(valid)} 个（单窗10年无信号）")
    nm = lambda k: f"{k[0]}·{k[1]}·清仓<{int(k[2])}·回补>{int(k[3])}"  # noqa: E731
    md.append(f"- 按 TWR 夏普最优：{nm(best)}；按 XIRR 最优：{nm(best_x)}（XIRR {valid.loc[best_x, 'XIRR'] * 100:.2f}%）")
    md.append(f"- 按相对对照1 的 IR 最优：{nm(best_ir)}（年化 IR {ir_pp[best_ir] * math.sqrt(bt.ANN):.2f}）")
    md.append(f"- 试验间 TWR 日收益平均相关 {rho:.3f}；有效 N：{n_eff_rho:.1f}（平均相关）/ {n_eff_eig:.1f}（特征值）")
    md.append(f"- CSCV（S=10）按夏普选优 PBO = **{pbo:.2f}**（斜率 {slope:.2f}）；按相对对照1 IR 选优 PBO = **{pbo_a:.2f}**（斜率 {slope_a:.2f}）\n")
    md.append(DSR.round(3).to_markdown(index=False))

    # ---------- 4) 起点敏感性 ----------
    q = pd.date_range("2010-01-01", "2023-12-31", freq="QS")
    starts = [px.index[px.index.searchsorted(d)] for d in q if d >= px.index[0]]
    srow = []
    for st in starts:
        for spec in SPECS:
            res = simulate(Smap[(MAIN_S, spec)], U, px, st, END)
            if res is None:
                continue
            led, ev = res
            m = evaluate(led, ev)
            b1 = evaluate(bench_same_flows(led, px), [])
            srow.append({"起点": st, "百分位方法": spec, "XIRR": m["XIRR"], "夏普": m["夏普"], "最大回撤": m["最大回撤"],
                         "清仓次数": m["清仓次数"], "对照1XIRR": b1["XIRR"], "对照1MDD": b1["最大回撤"],
                         "XIRR−对照1": m["XIRR"] - b1["XIRR"], "MDD改善": m["最大回撤"] - b1["最大回撤"]})
    S_ = pd.DataFrame(srow)
    S_.to_csv(OUT / "table_start_sensitivity.csv", encoding="utf-8-sig", index=False)
    req = S_[S_["起点"] <= "2016-12-31"]
    feas = req.groupby("百分位方法")["起点"].agg(["count", "min"]).reindex(SPECS)
    feas["count"] = feas["count"].fillna(0).astype(int)
    md.append(f"\n## 表7 起点敏感性（规则书 S，阈值 25/58）\n\n需求区间 2010Q1~2016Q4 共 {sum(d <= pd.Timestamp('2016-12-31') for d in q)} 个季度起点，各百分位方法可行起点数：\n")
    md.append(feas.assign(min=feas["min"].dt.date).rename(columns={"count": "可行起点数", "min": "最早"}).to_markdown())
    agg = lambda g: pd.Series({  # noqa: E731
        "起点数": len(g), "XIRR中位": g["XIRR"].median(), "XIRR最小": g["XIRR"].min(), "XIRR最大": g["XIRR"].max(),
        "XIRR−对照1 中位": g["XIRR−对照1"].median(), "XIRR跑赢对照1比例": (g["XIRR−对照1"] > 0).mean(),
        "MDD中位": g["最大回撤"].median(), "MDD改善中位": g["MDD改善"].median(), "清仓次数中位": g["清仓次数"].median()})
    md.append("\n### 表7b 需求区间内可行起点（≤2016Q4）\n")
    md.append(bt.fmt_table(req.groupby("百分位方法").apply(agg).reindex([s for s in SPECS if s in req["百分位方法"].unique()]),
                           ("XIRR中位", "XIRR最小", "XIRR最大", "XIRR−对照1 中位", "XIRR跑赢对照1比例", "MDD中位", "MDD改善中位"),
                           ("清仓次数中位",), ("起点数",)))
    com = S_[(S_["起点"] >= "2019-01-01") & (S_["百分位方法"] != "单窗10年")]
    md.append(f"\n### 表7c 公共可行起点 2019Q1~2023Q4（{com['起点'].nunique()} 个）\n")
    md.append(bt.fmt_table(com.groupby("百分位方法").apply(agg).reindex([s for s in SPECS if s != "单窗10年"]),
                           ("XIRR中位", "XIRR最小", "XIRR最大", "XIRR−对照1 中位", "XIRR跑赢对照1比例", "MDD中位", "MDD改善中位"),
                           ("清仓次数中位",), ("起点数",)))
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))
    order = [s for s in SPECS if s != "单窗10年"]
    for ax, met, lab in [(axes[0], "XIRR−对照1", "XIRR − 对照1（同入金不卖）"), (axes[1], "MDD改善", "最大回撤改善（策略 − 对照1）")]:
        data = [com[com["百分位方法"] == s][met].values * 100 for s in order]
        bp_ = ax.boxplot(data, patch_artist=True, widths=0.6, medianprops={"color": bt.INK})
        for j, p_ in enumerate(bp_["boxes"]):
            p_.set_facecolor(bt.SERIES[1] if j == 0 else bt.SERIES[0])
            p_.set_edgecolor("white")
        ax.axhline(0, color=bt.INK2, lw=1)
        ax.set_xticks(range(1, len(order) + 1), order, rotation=60)
        ax.set_ylabel(lab + "（百分点）")
    fig.suptitle(f"起点敏感性：{com['起点'].nunique()} 个季度起点 2019Q1~2023Q4 → {END}（橙色=规则书15年百分位）", color=bt.INK)
    fig.savefig(FIG / "fig_start_sensitivity.png", bbox_inches="tight")
    plt.close(fig)

    # ---------- 5) 子区间（从各方法自身首个有效日起连续运行，再截取子区间的 TWR） ----------
    subrows = []
    full_runs = {}
    for spec in SPECS:
        s = Smap[(MAIN_S, spec)]
        st = px.index[px.index.get_loc(s.first_valid_index()) + 1]
        led, ev = simulate(s, U, px, st, END)
        full_runs[spec] = (led, ev)
        tw = twr_series(led)
        for name, (a, b) in bt.SUBPERIODS.items():
            if pd.Timestamp(a) < led.index[0]:
                subrows.append({"子区间": name, "百分位方法": spec})
                continue
            x = tw.loc[a:b]
            nav = (1 + x).cumprod()
            pk = np.maximum.accumulate(np.r_[1.0, nav.values])[1:]
            w = (led["holding"] / led["value"].replace(0, np.nan)).loc[a:b]
            subrows.append({"子区间": name, "百分位方法": spec + ("（账户自" + str(led.index[0].date()) + "建立）" if (pd.Timestamp(a) - led.index[0]).days < 90 else ""),
                            "TWR区间收益": nav.iloc[-1] - 1,
                            "最大回撤": (nav.values / pk - 1).min(), "平均仓位": w.mean(),
                            "区间内事件": "；".join(f"{e[1]}{e[0].date()}" for e in ev if a <= str(e[0].date()) <= b)})
    for name, (a, b) in bt.SUBPERIODS.items():
        x = ret.loc[a:b]
        nav = (1 + x).cumprod()
        pk = np.maximum.accumulate(np.r_[1.0, nav.values])[1:]
        subrows.append({"子区间": name, "百分位方法": "沪深300买入持有", "TWR区间收益": nav.iloc[-1] - 1,
                        "最大回撤": (nav.values / pk - 1).min(), "平均仓位": 1.0})
    SUB = pd.DataFrame(subrows)
    SUB.to_csv(OUT / "table_subperiods.csv", encoding="utf-8-sig", index=False)
    md.append("\n## 表8 子区间（各方法从自身首个有效日起连续运行后截取；“—”=该方法当时无信号）\n")
    for name in bt.SUBPERIODS:
        t = SUB[SUB["子区间"] == name].drop(columns="子区间").set_index("百分位方法")
        md.append(f"\n### {name}\n")
        md.append(bt.fmt_table(t, ("TWR区间收益", "最大回撤", "平均仓位")))

    # ---------- 6) 指标一致性：S 构成分量 & 关键点 ----------
    md.append("\n## 表9 指标一致性\n")
    for spec in ["规则书15年", "A_均值", "C_均值", "单窗3年"]:
        ch = pd.concat({i: cheapness_by_spec(df, pcts, i, spec) for i in bt.INDICATORS}, axis=1).dropna()
        md.append(f"\n**{spec}** 便宜度分位相关（{ch.index[0].date()}~）\n")
        md.append(ch.corr().round(2).to_markdown())
    kp = []
    for lab, d in bt.KEY_POINTS.items():
        row = {"关键点": lab}
        for spec in SPECS:
            v = Smap[(MAIN_S, spec)].get(pd.Timestamp(d), np.nan)
            row[spec] = "—" if pd.isna(v) else f"{v:.0f}"
        kp.append(row)
    md.append("\n### 表9b 关键高低点的规则书 S（0~100，越高越便宜；<25 为清仓估值条件，>58 为回补条件）\n")
    md.append(pd.DataFrame(kp).set_index("关键点").to_markdown())
    kp2 = []
    for lab, d in bt.KEY_POINTS.items():
        row = {"关键点": lab}
        for i in bt.INDICATORS:
            v = cheapness_by_spec(df, pcts, i, "规则书15年").get(pd.Timestamp(d), np.nan)
            row[i] = "—" if pd.isna(v) else f"{v:.0f}"
        row["U"] = f"{U.get(pd.Timestamp(d)):.2f}"
        kp2.append(row)
    md.append("\n### 表9c 关键点上各指标的便宜度分位（规则书15年口径）与趋势分 U\n")
    md.append(pd.DataFrame(kp2).set_index("关键点").to_markdown())

    # ---------- 7) 事件对比 & S 曲线图 ----------
    ev_rows = []
    for spec, (led, ev) in full_runs.items():
        for e in ev:
            ev_rows.append({"百分位方法": spec, "日期": e[0].date(), "事件": e[1], "T-1日S": round(e[2], 1), "成交价": e[3]})
    EV = pd.DataFrame(ev_rows)
    EV.to_csv(OUT / "table_events.csv", encoding="utf-8-sig", index=False)
    md.append("\n## 表10 各百分位方法的清仓/回补事件（规则书 S，阈值 25/58，自身首个有效日起）\n")
    md.append(EV.to_markdown(index=False))

    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True, gridspec_kw={"height_ratios": [3, 1.2, 2]})
    show = ["规则书15年", "A_均值", "B_均值", "C_均值", "单窗3年", "单窗5年", "扩展窗口"]
    for j, spec in enumerate(show):
        axes[0].plot(Smap[(MAIN_S, spec)].loc["2013":], color=bt.SERIES[j], lw=1.3 if j == 0 else 1.0,
                     label=spec, zorder=3 if j == 0 else 2)
    axes[0].axhline(25, color=bt.SERIES[7], ls="--", lw=1)
    axes[0].axhline(58, color=bt.SERIES[2], ls="--", lw=1)
    axes[0].set_ylabel("规则书 S（越高越便宜）")
    axes[0].legend(ncol=7, frameon=False, fontsize=9, loc="upper left")
    axes[0].set_ylim(0, 100)
    axes[1].plot(U.loc["2013":], color=bt.INK2, lw=0.8, drawstyle="steps-post")
    axes[1].axhline(1 / 3, color=bt.SERIES[7], ls="--", lw=1)
    axes[1].set_ylabel("趋势分 U")
    axes[2].plot(px.loc["2013":], color=bt.INK, lw=1)
    ylo = px.loc["2013":].min()
    for j, spec in enumerate(show):
        for e in full_runs[spec][1]:
            axes[2].scatter(e[0], ylo * (0.93 - 0.035 * j), marker="v" if e[1] == "清仓" else "^",
                            color=bt.SERIES[j], s=36, zorder=3, edgecolor="white", linewidth=0.5)
    axes[2].set_ylabel("沪深300 收盘；▼清仓 ▲回补")
    axes[0].set_title("规则书 S 在不同百分位方法下的走势与 Plan C 事件（虚线：S<25 清仓、S>58 回补）", color=bt.INK)
    fig.savefig(FIG / "fig_S_and_events.png", bbox_inches="tight")
    plt.close(fig)

    # 净值（主区间 TWR）
    fig, ax = plt.subplots(figsize=(13, 5.5))
    for j, spec in enumerate(show):
        k = (MAIN_S, spec, RULES.sell_thr, RULES.resume_thr)
        if k in led_main:
            ax.plot((1 + twr_series(led_main[k])).cumprod(), color=bt.SERIES[j], lw=1.3 if j == 0 else 1.0, label=spec)
    k0 = (MAIN_S, "规则书15年", RULES.sell_thr, RULES.resume_thr)
    ax.plot((1 + twr_series(bench_same_flows(led_main[k0], px))).cumprod(), color=bt.INK, lw=1.6, ls="--",
            label="对照1：同入金不卖（规则书15年 S 的入金）")
    ax.set_ylabel("投资账户 TWR 净值")
    ax.legend(ncol=3, frameon=False, fontsize=9)
    ax.set_title(f"主区间 {MAIN_WIN[0]}~{END} 投资账户 TWR 净值", color=bt.INK)
    fig.savefig(FIG / "fig_twr_main.png", bbox_inches="tight")
    plt.close(fig)

    # ---------- 8) 窗口/聚合差异：S 差异与 U 的作用 ----------
    st_, en_ = MAIN_WIN
    base = Smap[(MAIN_S, "规则书15年")].loc[st_:en_]
    dif = {}
    for spec in SPECS[1:]:
        s = Smap[(MAIN_S, spec)].loc[st_:en_]
        dif[spec] = {"与规则书S平均|差|": (s - base).abs().mean(), "平均S": s.mean(), "S<25 天数占比": (s < 25).mean(),
                     "S>58 天数占比": (s > 58).mean(), "S<25且U≤1/3 天数": int(((s < 25) & (U.loc[st_:en_] <= 1 / 3 + 1e-12)).sum())}
    dif["规则书15年"] = {"与规则书S平均|差|": 0.0, "平均S": base.mean(), "S<25 天数占比": (base < 25).mean(),
                     "S>58 天数占比": (base > 58).mean(), "S<25且U≤1/3 天数": int(((base < 25) & (U.loc[st_:en_] <= 1 / 3 + 1e-12)).sum())}
    md.append("\n## 表11 百分位方法对 S 的影响（主区间）\n")
    md.append(pd.DataFrame(dif).T.reindex(SPECS).round(3).to_markdown())

    header = (f"# Plan C 回测结果表（plan_c.py 自动生成）\n\n样本 {px.index[0].date()} ~ {END}；年化因子 {bt.ANN:.1f}；"
              f"规则参数冻结（S<25 且 U≤1/3 清仓、S>58 回补、250×x^2.5 定投、申购 0.12%、赎回 0.5%）。\n")
    (OUT / "results_tables.md").write_text(header + "\n".join(md), encoding="utf-8")
    print(rep.to_string())
    print(f"done. trials={n_trials}")


if __name__ == "__main__":
    main()
