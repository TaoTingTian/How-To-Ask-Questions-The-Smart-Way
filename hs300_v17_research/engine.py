"""V1.6 规则引擎 + 可插拔的指标"插槽"。

时点：用第 i−1 行（T−1 收盘）的 V、U、指标和 p 决策，按第 i 行（T 日）净值成交。

插槽（全部默认关闭 = 原版 V1.6）：
  sell_sig / sell_wait  止盈执行过滤：触发止盈后，需 T−1 日 sell_sig 为真才卖；
                        连续触发 sell_wait 个交易日仍未确认则强制执行（安全阀）。
  buy_sig  / buy_wait   回投执行过滤：同上，作用于回投。
  dca_sig  / dca_wait   定投择时：定投额先挂账，T−1 日 dca_sig 为真或挂账满 dca_wait 日才买入（资金总量不变）。
  U                     替换趋势分 U（取 0~1，≥2/3 视为向上，≤1/3 视为向下）。
  buy_aggr              为真时回投改用企稳线（更积极），如恐慌期（高波动分位）。
  sell_aggr             为真时止盈改用趋势向下的卖出线（更积极），如亢奋期。
  buy_tranche / sell_tranche  (步长, 份数)：动态百分比网格分批执行。
"""
import numpy as np
import pandas as pd

FEE_BUY = 0.001
ER_DRAG = 0.005          # 基金管理+托管费近似（年化）
SETTLE = 2               # 赎回款 T+2 个交易日到账


def redeem_fee(days):
    if days < 7:
        return 0.015
    if days < 30:
        return 0.005
    if days < 180:
        return 0.0025
    return 0.0


def clip01(x):
    return min(max(x, 0.0), 1.0)


def B_s(x):
    return 0.2 + 0.8 * clip01((80 - x) / 10)


def sell_target(V, Vmax, U):
    if U <= 1 / 3 + 1e-9:
        return B_s(Vmax)
    if V > 70:
        return (1 + B_s(V)) / 2 - 0.4 * clip01((V - 80) / 10)
    return None


def buy_target(V, U, aggressive=False):
    if aggressive or U >= 2 / 3 - 1e-9:
        return 0.2 + 0.8 * clip01((50 - V) / 20)
    return 0.2 + 0.8 * clip01((40 - V) / 20)


def nav_series(df, start):
    d = df.loc[start:]
    r = d.ret.fillna(0) + d.dy.shift().bfill() / 100 / 244 - ER_DRAG / 244
    nav = (1 + r).cumprod()
    nav.iloc[0] = 1.0
    return nav


def _arr(x, idx, default):
    if x is None:
        return np.full(len(idx), default)
    return pd.Series(x).reindex(idx).fillna(default).values


def simulate(df, start="2014-01-07", end=None, record=False, **kw):
    d = df.loc[start:end]
    idx = d.index
    nav = nav_series(df, start).loc[idx].values
    V = d.V.values
    U = _arr(kw.get("U"), idx, np.nan) if kw.get("U") is not None else d.U.values
    sell_sig = _arr(kw.get("sell_sig"), idx, True).astype(bool)
    buy_sig = _arr(kw.get("buy_sig"), idx, True).astype(bool)
    dca_sig = _arr(kw.get("dca_sig"), idx, True).astype(bool)
    buy_aggr = _arr(kw.get("buy_aggr"), idx, False).astype(bool)
    sell_aggr = _arr(kw.get("sell_aggr"), idx, False).astype(bool)
    sell_wait = kw.get("sell_wait", 0)
    buy_wait = kw.get("buy_wait", 0)
    dca_wait = kw.get("dca_wait", 0)
    btr = kw.get("buy_tranche")      # (step, n)
    stran = kw.get("sell_tranche")
    dca_scale = kw.get("dca_scale", 1.0)

    lots = []            # [date_idx, shares]
    cash = 0.0           # 已到账资金池
    transit = []         # [arrive_idx, amount]
    pending = 0.0
    pend_age = 0
    E = 0.0
    Vmax = np.nan
    s_cnt = b_cnt = 0
    last_buy_px = last_sell_px = None
    n = len(idx)
    AV = np.zeros(n)
    inflow = np.zeros(n)
    pos = np.zeros(n)
    trades = []
    dates = idx

    for i in range(n):
        # 到账
        if transit:
            arrived = [a for a in transit if a[0] <= i]
            if arrived:
                cash += sum(a[1] for a in arrived)
                transit = [a for a in transit if a[0] > i]
        if i == 0 or np.isnan(V[i - 1]):
            AV[i] = sum(l[1] for l in lots) * nav[i] + cash + sum(a[1] for a in transit)
            continue
        v, u = V[i - 1], U[i - 1]
        # V_max / E（基于 T−1 的 V）
        if v < 50:
            Vmax = v
        else:
            Vmax = v if np.isnan(Vmax) else max(Vmax, v)
            E = 0.0
        sh = sum(l[1] for l in lots)
        H = sh * nav[i - 1]
        C = cash + sum(a[1] for a in transit)
        tot = H + C
        p = H / tot if tot > 0 else np.nan
        sold = False

        # ---------- 止盈 ----------
        trig_s = False
        if tot > 0 and Vmax > 70 and v >= 50:
            ts = sell_target(v, Vmax, 0.0 if sell_aggr[i - 1] else u)
            if ts is not None and p > ts + 0.05:
                trig_s = True
                s_cnt += 1
                ok = sell_sig[i - 1] or (sell_wait and s_cnt >= sell_wait)
                if ok and stran is not None and last_sell_px is not None:
                    ok = d.close.values[i - 1] >= last_sell_px * (1 + stran[0])
                if ok:
                    amt = (p - ts) * tot
                    if stran is not None:          # 网格分批：每批至多 80%/n 的账户
                        amt = min(amt, 0.8 * tot / stran[1])
                    sh_to_sell = amt / nav[i - 1]
                    proceeds = 0.0
                    sold_sh = 0.0
                    for l in lots:
                        if sh_to_sell <= 1e-12:
                            break
                        days = (dates[i] - dates[l[0]]).days
                        if days < 30:
                            break
                        q = min(l[1], sh_to_sell)
                        proceeds += q * nav[i] * (1 - redeem_fee(days))
                        l[1] -= q
                        sh_to_sell -= q
                        sold_sh += q
                    lots = [l for l in lots if l[1] > 1e-12]
                    if sold_sh > 0:
                        sold = True
                        transit.append([i + SETTLE, proceeds])
                        trades.append((dates[i], "sell", proceeds, nav[i], v, d.close.values[i]))
                        last_sell_px = d.close.values[i - 1]
        if not trig_s:
            s_cnt = 0
            if v < 50:
                last_sell_px = None

        # ---------- 回投 ----------
        trig_b = False
        if tot > 0 and v < 50 and cash >= 10:
            tb = buy_target(v, u, buy_aggr[i - 1])
            if p < tb - 0.05:
                trig_b = True
                b_cnt += 1
                ok = buy_sig[i - 1] or (buy_wait and b_cnt >= buy_wait)
                if ok and btr is not None and last_buy_px is not None:
                    ok = d.close.values[i - 1] <= last_buy_px * (1 - btr[0])
                if ok:
                    amt = min((tb - p) * tot, cash)
                    if btr is not None:
                        amt = min(amt, 0.8 * tot / btr[1])
                    cash -= amt
                    lots.append([i, amt / (1 + FEE_BUY) / nav[i]])
                    trades.append((dates[i], "buy", amt, nav[i], v, d.close.values[i]))
                    last_buy_px = d.close.values[i - 1]
        if not trig_b:
            b_cnt = 0
            if v >= 50:
                last_buy_px = None

        # ---------- 定投 ----------
        if not sold:
            x = clip01((70 - v) / 70)
            base = 300 * x ** 2.5
            extra = 700 * clip01((15 - v) / 15) * x ** 2.5
            extra = min(extra, 50000 - E)
            E += extra
            amt = (base + extra) * dca_scale
            if amt > 0:
                pending += amt
                pend_age += 1
        if pending >= 10 and (dca_sig[i - 1] or (dca_wait and pend_age >= dca_wait) or dca_wait == 0):
            lots.append([i, pending / (1 + FEE_BUY) / nav[i]])
            inflow[i] = pending
            pending = 0.0
            pend_age = 0

        sh = sum(l[1] for l in lots)
        AV[i] = sh * nav[i] + cash + sum(a[1] for a in transit)
        pos[i] = sh * nav[i] / AV[i] if AV[i] > 0 else np.nan

    res = dict(dates=idx, AV=AV, inflow=inflow, pos=pos, pending_end=pending,
               trades=pd.DataFrame(trades, columns=["date", "side", "amount", "nav", "V", "close"]))
    return res


# ---------------- 绩效 ----------------
def xirr(dates, flows):
    t = np.array([(x - dates[0]).days / 365.25 for x in dates])
    f = np.array(flows)
    lo, hi = -0.99, 1.0
    npv = lambda r: (f / (1 + r) ** t).sum()
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def twr_returns(res):
    AV, inflow = res["AV"], res["inflow"]
    prev = np.r_[np.nan, AV[:-1]]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (AV - inflow) / prev - 1
    r[~np.isfinite(r)] = 0.0
    return pd.Series(r, res["dates"])


def metrics(res, sub=None):
    r = twr_returns(res)
    dates, inflow, AV = res["dates"], res["inflow"], res["AV"]
    m = {}
    flows = list(-inflow)
    flows[-1] += AV[-1] + res["pending_end"]
    nz = [k for k, f in enumerate(flows) if f != 0]
    m["IRR"] = xirr([dates[k] for k in nz], [flows[k] for k in nz])
    m["投入"] = inflow.sum()
    m["期末"] = AV[-1] + res["pending_end"]
    m["倍数"] = m["期末"] / m["投入"]
    rr = r if sub is None else r.loc[sub[0]:sub[1]]
    rr = rr[rr.index >= r.index[np.argmax(AV > 1000)]]
    nav = (1 + rr).cumprod()
    yrs = len(rr) / 244
    m["TWR年化"] = nav.iloc[-1] ** (1 / yrs) - 1
    m["波动"] = rr.std() * np.sqrt(244)
    m["Sharpe"] = rr.mean() / rr.std() * np.sqrt(244) if rr.std() > 0 else np.nan
    m["最大回撤"] = (nav / nav.cummax() - 1).min()
    m["Calmar"] = m["TWR年化"] / -m["最大回撤"] if m["最大回撤"] < 0 else np.nan
    m["平均仓位"] = np.nanmean(res["pos"][AV > 1000])
    t = res["trades"]
    m["止盈次数"] = (t.side == "sell").sum() if len(t) else 0
    m["回投次数"] = (t.side == "buy").sum() if len(t) else 0
    return m
