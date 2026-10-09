"""
沪深300「趋势共识 × 波动预算」择时策略 (Trend Consensus × Volatility Budget, TCVB)

核心思想（两条跨市场、跨百年都被反复验证过的规律，而不是在沪深300上挖出来的规律）：
  1. 趋势共识：价格在 1/2/3/6/12 个月几个尺度上"有几个在涨"，就持有几成仓位。
     不挑"最好的周期"，而是让 5 个周期等权投票——参数风险被分散，而不是被优化。
  2. 波动预算：市场波动率高于"历史常态"时按比例降仓；常态由扩展窗口中位数给出，
     只用当时之前的数据，没有任何人为设定的目标波动率。

  目标仓位 = 趋势得分(0~1) × min(1, 常态波动 / 当前波动)     ∈ [0, 1]，不加杠杆、不做空

所有参数都在下方 PARAMS 中一次写死，取值理由见 策略说明.md；回测与稳健性检验只做"检验"，
绝不回头用结果去改这些参数。

用法:
  python strategy.py                         # 用 data/hs300.csv 回测并输出图表到 results/
  python strategy.py --signal                # 只打印最新交易日的目标仓位（实盘用）
  python strategy.py --csv my.csv --signal   # 用自己的数据（需含 date, open, close 三列）
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 1. 参数：一次性写死（事前设定，不做任何优化）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Params:
    lookbacks: tuple = (21, 42, 63, 126, 252)  # 1/2/3/6/12 个月，时间序列动量的标准族
    vol_windows: tuple = (21, 63)              # 1 个月 + 3 个月已实现波动，取平均
    vol_warmup: int = 252                      # 至少 1 年数据才开始估计"常态波动"
    freq: str = "W"                            # 每周最后一个交易日收盘后决策
    band: float = 0.10                         # 目标仓位与当前仓位相差 ≥10% 才调仓
    cost: float = 0.0010                       # 单边交易成本 0.10%（佣金+滑点+ETF 折溢价）
    exec_at: str = "open"                      # 决策后下一交易日开盘执行
    extra_delay: int = 0                       # 额外延迟天数（只用于稳健性检验）
    use_trend: bool = True                     # 消融实验开关
    use_vol: bool = True
    cash_yield: float = 0.0                    # 空仓部分年化收益（默认 0，保守）
    div_yield: float = 0.0                     # 持仓部分年化股息（价格指数不含股息）


PARAMS = Params()


# ---------------------------------------------------------------------------
# 2. 数据
# ---------------------------------------------------------------------------
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    df = df[["open", "close"]].astype(float).dropna()
    return df[~df.index.duplicated()]


def load_akshare() -> pd.DataFrame:
    """可选：本地联网时用 akshare 拉取沪深300日线（pip install akshare）。"""
    import akshare as ak
    raw = ak.stock_zh_index_daily(symbol="sh000300")
    raw["date"] = pd.to_datetime(raw["date"])
    return raw.set_index("date")[["open", "close"]].astype(float).sort_index()


# ---------------------------------------------------------------------------
# 3. 信号（全部因果：t 日的值只用到 t 日收盘及以前的数据）
# ---------------------------------------------------------------------------
def signals(close: pd.DataFrame | pd.Series, p: Params = PARAMS) -> dict:
    close = close.to_frame() if isinstance(close, pd.Series) else close
    logp = np.log(close)
    ret = logp.diff()

    # 趋势共识：各尺度收益为正的比例，取值 0, 0.2, ..., 1
    votes = [(logp - logp.shift(L) > 0).astype(float).where(logp.shift(L).notna())
             for L in p.lookbacks]
    trend = sum(votes) / len(votes)

    # 当前波动：多窗口已实现波动的平均（年化）
    vol = sum(ret.rolling(w).std() for w in p.vol_windows) / len(p.vol_windows) * np.sqrt(252)
    # 常态波动：截至当日的全部历史中位数（扩展窗口）
    normal_vol = vol.expanding(min_periods=p.vol_warmup).median()
    vol_scale = (normal_vol / vol).clip(upper=1.0)

    t = trend if p.use_trend else trend * 0 + 1
    v = vol_scale if p.use_vol else vol_scale * 0 + 1
    target = (t * v).where(trend.notna() & vol_scale.notna())
    return {"trend": trend, "vol": vol, "normal_vol": normal_vol,
            "vol_scale": vol_scale, "target": target}


def decision_days(index: pd.DatetimeIndex, freq: str) -> np.ndarray:
    """每个周期的最后一个交易日为决策日（最后一行也视为决策日，便于实盘）。"""
    if freq == "D":
        return np.ones(len(index), dtype=bool)
    period = index.to_period(freq)
    last = np.r_[period[1:] != period[:-1], True]
    return np.asarray(last)


# ---------------------------------------------------------------------------
# 4. 回测引擎（逐日模拟，持仓权重随价格漂移；支持多条路径并行）
# ---------------------------------------------------------------------------
def backtest(opn: np.ndarray, cls: np.ndarray, target: np.ndarray,
             is_decision: np.ndarray, p: Params = PARAMS):
    """opn/cls/target 形状均为 (T, N)。返回 (净值, 收盘持仓权重, 换手) 三个 (T, N) 数组。"""
    T, N = cls.shape
    gap = np.vstack([np.zeros((1, N)), opn[1:] / cls[:-1] - 1])   # 隔夜
    intr = cls / opn - 1                                           # 日内
    carry_cash, carry_div = p.cash_yield / 252, p.div_yield / 252

    tgt = np.where(is_decision[:, None], target, np.nan)
    if p.extra_delay:
        tgt = np.vstack([np.full((p.extra_delay, N), np.nan), tgt[:-p.extra_delay]])

    nav = np.ones(N); w = np.zeros(N); pending = np.full(N, np.nan)
    nav_out = np.empty((T, N)); w_out = np.empty((T, N)); turn_out = np.zeros((T, N))

    def trade(nav, w, pending, i):
        go = ~np.isnan(pending) & (np.abs(pending - w) >= p.band)
        dw = np.where(go, np.abs(pending - w), 0.0)
        turn_out[i] += dw
        return nav * (1 - p.cost * dw), np.where(go, pending, w)

    for i in range(T):
        # 隔夜段
        g = gap[i]
        nav = nav * (1 + w * g)
        w = w * (1 + g) / np.maximum(1 + w * g, 1e-12)
        if p.exec_at == "open":
            nav, w = trade(nav, w, pending, i)
            pending = np.full(N, np.nan)
        # 日内段 + 现金/股息收益
        r = intr[i]
        nav = nav * (1 + w * r + (1 - w) * carry_cash + w * carry_div)
        w = w * (1 + r) / np.maximum(1 + w * r, 1e-12)
        if p.exec_at == "close":
            nav, w = trade(nav, w, pending, i)
            pending = np.full(N, np.nan)
        # 收盘后决策，下一交易日执行
        new = tgt[i]
        pending = np.where(np.isnan(new), pending, np.nan_to_num(new))
        nav_out[i], w_out[i] = nav, w
    return nav_out, w_out, turn_out


def run(df: pd.DataFrame, p: Params = PARAMS, start=None) -> pd.DataFrame:
    """单条价格序列的完整回测。start 之前只做预热，不交易。"""
    sig = signals(df["close"], p)
    target = sig["target"].iloc[:, 0]
    first = target.first_valid_index()
    start = max(pd.Timestamp(start), first) if start is not None else first
    d = df.loc[start:]
    tg = target.loc[start:].to_numpy()[:, None]
    dec = decision_days(df.index, p.freq)[df.index.get_indexer(d.index)]
    nav, w, turn = backtest(d["open"].to_numpy()[:, None], d["close"].to_numpy()[:, None],
                            tg, dec, p)
    out = pd.DataFrame({"nav": nav[:, 0], "weight": w[:, 0], "turnover": turn[:, 0],
                        "target": target.loc[start:].values,
                        "trend": sig["trend"].iloc[:, 0].loc[start:].values,
                        "vol_scale": sig["vol_scale"].iloc[:, 0].loc[start:].values,
                        "bh": d["close"].values / d["close"].iloc[0]}, index=d.index)
    if p.div_yield:  # 买入持有同样计入股息，保证公平
        out["bh"] *= (1 + p.div_yield / 252) ** np.arange(len(out))
    return out


# ---------------------------------------------------------------------------
# 5. 绩效指标
# ---------------------------------------------------------------------------
def metrics(nav: pd.Series, weight: pd.Series | None = None,
            turnover: pd.Series | None = None) -> dict:
    nav = nav.dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    ppy = len(nav) / years
    r = nav.pct_change().dropna()
    dd = nav / nav.cummax() - 1
    cagr = nav.iloc[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(ppy)
    m = {"年化收益": cagr, "年化波动": vol,
         "夏普(无风险=0)": r.mean() / r.std() * np.sqrt(ppy),
         "最大回撤": dd.min(), "卡玛": cagr / abs(dd.min()),
         "最长水下期(交易日)": int(_longest_underwater(nav))}
    if weight is not None:
        m["平均仓位"] = weight.mean()
    if turnover is not None:
        m["年换手(单边)"] = turnover.sum() / years
        m["年调仓次数"] = (turnover > 0).sum() / years
    return m


def _longest_underwater(nav: pd.Series) -> int:
    under = (nav < nav.cummax()).to_numpy()
    best = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        best = max(best, cur)
    return best


def static_mix(bh: pd.Series, exposure: float, cash_yield: float = 0.0) -> pd.Series:
    """等暴露静态组合：始终持有 exposure 比例指数（每日再平衡），用于公平比较。"""
    r = bh.pct_change().fillna(0)
    return (1 + exposure * r + (1 - exposure) * cash_yield / 252).cumprod()


# ---------------------------------------------------------------------------
# 6. 入口
# ---------------------------------------------------------------------------
def print_signal(df: pd.DataFrame, p: Params = PARAMS):
    sig = signals(df["close"], p)
    last = df.index[-1]
    trend = sig["trend"].iloc[-1, 0]
    print(f"数据截至 {last.date()}  收盘 {df['close'].iloc[-1]:.2f}")
    for L in p.lookbacks:
        up = df["close"].iloc[-1] > df["close"].iloc[-1 - L]
        print(f"  {L:>3} 日趋势: {'上涨 ✓' if up else '下跌 ✗'}")
    print(f"趋势得分      = {trend:.2f}")
    print(f"当前波动      = {sig['vol'].iloc[-1, 0]:.1%}   常态波动 = {sig['normal_vol'].iloc[-1, 0]:.1%}")
    print(f"波动缩放      = {sig['vol_scale'].iloc[-1, 0]:.2f}")
    print(f"==> 目标仓位  = {sig['target'].iloc[-1, 0]:.0%}")
    print(f"执行规则：每周最后一个交易日收盘后计算，下一交易日开盘执行，"
          f"与当前仓位相差 ≥{p.band:.0%} 才调仓。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(HERE, "data", "hs300.csv"))
    ap.add_argument("--akshare", action="store_true", help="联网用 akshare 获取数据")
    ap.add_argument("--signal", action="store_true", help="只输出最新目标仓位")
    a = ap.parse_args()
    df = load_akshare() if a.akshare else load_csv(a.csv)

    if a.signal:
        print_signal(df)
        return

    res = run(df)
    s = metrics(res["nav"], res["weight"], res["turnover"])
    b = metrics(res["bh"])
    mix = metrics(static_mix(res["bh"], res["weight"].mean()))
    table = pd.DataFrame({"TCVB策略": s, "买入持有": b,
                          f"等暴露静态({res['weight'].mean():.0%})": mix})
    print(f"回测区间 {res.index[0].date()} ~ {res.index[-1].date()}")
    print(table.to_string(float_format=lambda x: f"{x:.3f}"))
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    res.to_csv(os.path.join(HERE, "results", "backtest_daily.csv"))


if __name__ == "__main__":
    main()
