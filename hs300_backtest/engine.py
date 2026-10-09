"""沪深300估值百分位动态仓位策略 回测引擎（Plan C 及其变体）

口径（与规则书一致）：
- 信号用 T-1 收盘后的 S、U，T 日收盘净值成交
- 真实资金流：每日外部入金 = 当日公式买入额；资金池只来自卖出回收款
- 申购费 0.12%，赎回费 0.5%；挂账满 10 元才成交
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA = Path(__file__).parent / "data"


# ---------------------------------------------------------------- data
def load_data():
    p = pd.read_csv(DATA / "price.csv", encoding="utf-8-sig")
    p = p.iloc[:, :2]
    p.columns = ["date", "close"]
    df = p.set_index(pd.to_datetime(p["date"]))[["close"]]
    for k in ["pe_ttm", "pb", "dividend_yield", "cn10y"]:
        s = pd.read_csv(DATA / f"{k}.csv")
        df[k] = pd.Series(s["value"].values, index=pd.to_datetime(s["date"]))
    df = df.sort_index()
    df["erp"] = 100.0 / df["pe_ttm"] - df["cn10y"]
    # 近似场外指数基金净值（补全项）：价格指数 + 股息日度再投资 − 0.5%/年管理托管费
    r = df["close"].pct_change().fillna(0) + df["dividend_yield"].shift(1).fillna(0) / 100 / 252 - 0.005 / 252
    df["nav_tr"] = df["close"].iloc[0] * (1 + r).cumprod()
    return df


def rolling_pct(s: pd.Series, years=15, min_n=504):
    """当日值在过去 years 个日历年（含当日）中的百分位，0~100；样本不足返回 NaN"""
    v = s.values
    idx = s.index
    out = np.full(len(v), np.nan)
    start = 0
    for i in range(len(v)):
        lo = idx[i] - pd.DateOffset(years=years)
        while idx[start] <= lo:
            start += 1
        w = v[start:i + 1]
        w = w[~np.isnan(w)]
        if len(w) < min_n or np.isnan(v[i]):
            continue
        out[i] = ((w < v[i]).sum() + 0.5 * ((w == v[i]).sum() - 1)) / (len(w) - 1) * 100 if len(w) > 1 else 50
    return pd.Series(out, index=idx)


def add_signals(df, years=15, min_n=504, ma=(40, 80, 160), warmup_years=0):
    """years: 回看窗口（日历年；取很大值即为扩张窗口）
    warmup_years: 预热期——数据起点后满这么多日历年才输出百分位"""
    df = df.copy()
    df["pb_pct"] = rolling_pct(df["pb"], years, min_n)
    df["dy_pct"] = rolling_pct(df["dividend_yield"], years, min_n)
    df["erp_pct"] = rolling_pct(df["erp"], years, min_n)
    if warmup_years:
        cut = df.index[0] + pd.DateOffset(years=warmup_years)
        df.loc[df.index < cut, ["pb_pct", "dy_pct", "erp_pct"]] = np.nan
    df["S"] = ((100 - df["pb_pct"]) + df["dy_pct"] + df["erp_pct"]) / 3
    df = set_ma(df, ma)
    return df


def set_ma(df, ma):
    df = df.copy()
    ups = []
    for k in ma:
        m = df["close"].rolling(k).mean()
        ups.append((df["close"] > m).astype(float).where(m.notna()))
    df["U"] = sum(ups) / len(ups)
    return df


# ---------------------------------------------------------------- xirr
def xirr(dates, flows):
    t = np.array([(d - dates[0]).days / 365.25 for d in dates])
    f = np.array(flows, dtype=float)

    def npv(r):
        return (f / (1 + r) ** t).sum()

    lo, hi = -0.99, 5.0
    if npv(lo) * npv(hi) > 0:
        return np.nan
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- strategy
DEFAULT = dict(
    tiers=((25, 1.0),),        # 清仓分档：((S阈值, 累计卖出比例), ...)；Plan C = 一档 S<25 全卖
    u_thr=1 / 3, resume_thr=58,
    s0=30, power=2.5, cap=250, min_order=10,
    fee_buy=0.0012, fee_sell=0.005,
    dca_while_waiting=False,  # Plan C：等待期停止定投
    reentry="lump",           # lump: S>resume 一次回补 | tranche: 分 tranche_days 个交易日等额回补
    tranche_days=60,
    pool_rate=0.0,            # 资金池年化收益（规则书为 0）
    nav="close",              # close: 价格指数 | nav_tr: 近似全收益基金净值
    sell_fn=None,             # 可选：f(S, U) -> 目标累计卖出比例（覆盖 tiers/u_thr）
    exit_col=None,            # 可选：卖出判断改用这一列的 S（如多口径共识 S），定投与回补仍用 S
    exit_years=None,          # 仅允许这些年份触发卖出（事件归因用）
    start=None, end=None,
)


def run(df, **kw):
    P = {**DEFAULT, **kw}
    d = df
    if P["start"]:
        d = d[d.index >= P["start"]]
    if P["end"]:
        d = d[d.index <= P["end"]]
    nav = d[P["nav"]].values
    S = d["S"].shift(1).values   # T-1 信号
    SX = d[P["exit_col"]].shift(1).values if P["exit_col"] else S
    U = d["U"].shift(1).values
    close = d["close"].values
    dates = d.index
    tiers = sorted(P["tiers"], key=lambda t: -t[0])
    shares = pool = pending = 0.0
    level = 0.0                  # 当前累计卖出比例
    waiting = False
    tranche_left, tranche_amt = 0, 0.0
    flows_d, flows_v = [], []
    inflow = 0.0
    events = []
    acct = np.zeros(len(d))
    ret = np.zeros(len(d))
    started = False
    prev_val = 0.0
    daily_pool_r = (1 + P["pool_rate"]) ** (1 / 252) - 1
    for i in range(len(d)):
        px = nav[i]
        pool *= 1 + daily_pool_r
        if started and prev_val > 0:
            ret[i] = (shares * px + pool) / prev_val - 1
        s, u = S[i], U[i]
        new_in = 0.0
        sold_today = False
        if not np.isnan(s) and not np.isnan(u):
            # 1) 卖出（最高优先级）
            ok_year = P["exit_years"] is None or dates[i].year in P["exit_years"]
            if shares > 0 and ok_year:
                if P["sell_fn"] is not None:
                    tgt = P["sell_fn"](SX[i], u)
                elif u <= P["u_thr"] + 1e-9:
                    tgt = max([f for th, f in tiers if SX[i] < th], default=0.0)
                else:
                    tgt = 0.0
                if tgt > level + 1e-9:
                    frac = (tgt - level) / (1 - level)
                    pool += shares * frac * px * (1 - P["fee_sell"])
                    shares *= 1 - frac
                    level = tgt
                    waiting = True
                    pending = 0.0
                    tranche_left = 0
                    sold_today = True
                    events.append((dates[i], f"卖出至{1-tgt:.0%}仓", s, close[i]))
            # 2) 恢复
            if waiting and not sold_today and s > P["resume_thr"]:
                waiting = False
                level = 0.0
                events.append((dates[i], "恢复", s, close[i]))
                if P["reentry"] == "lump":
                    shares += pool * (1 - P["fee_buy"]) / px
                    pool = 0.0
                else:
                    tranche_left = P["tranche_days"]
                    tranche_amt = pool / tranche_left
            # 3) 定投
            if not sold_today and (not waiting or P["dca_while_waiting"]):
                x = min(max((s - P["s0"]) / (100 - P["s0"]), 0), 1)
                pending += P["cap"] * x ** P["power"]
                if pending >= P["min_order"]:
                    new_in = pending
                    shares += pending * (1 - P["fee_buy"]) / px
                    pending = 0.0
        if not waiting and tranche_left > 0:
            amt = pool if tranche_left == 1 else min(tranche_amt, pool)
            shares += amt * (1 - P["fee_buy"]) / px
            pool -= amt
            tranche_left -= 1
        if new_in > 0:
            inflow += new_in
            flows_d.append(dates[i]); flows_v.append(-new_in)
            started = True
        acct[i] = shares * px + pool
        prev_val = acct[i]
    final = acct[-1]
    res = dict(inflow=inflow, final=final, profit=final - inflow, events=events,
               n_exit=sum(1 for e in events if e[1].startswith("卖出")))
    if inflow > 0:
        res["xirr"] = xirr(flows_d + [dates[-1]], flows_v + [final])
        first = int(np.argmax(acct > 0))
        r = ret[first + 1:]
        curve = np.cumprod(1 + r)
        yrs = (dates[-1] - dates[first]).days / 365.25
        res["twr"] = curve[-1] ** (1 / yrs) - 1
        peak = np.maximum.accumulate(curve)
        res["mdd"] = (curve / peak - 1).min()
        res["calmar"] = res["twr"] / abs(res["mdd"]) if res["mdd"] < 0 else np.nan
        res["curve"] = pd.Series(np.r_[1, curve], index=dates[first:])
    res["acct"] = pd.Series(acct, index=dates)
    return res


def fmt(r):
    return (f"本金{r['inflow']:>9,.0f} 期末{r['final']:>9,.0f} XIRR{r['xirr']*100:6.2f}% "
            f"TWR{r['twr']*100:6.2f}% MDD{r['mdd']*100:6.1f}% Calmar{r['calmar']:5.2f} 清仓{r['n_exit']}次")
