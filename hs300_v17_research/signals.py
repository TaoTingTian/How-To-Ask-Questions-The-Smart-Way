"""图中指标 + 凯尔特纳 + 波动率分位 的"超卖(buy)/超买(sell)"信号。
每个指标：预先登记的教科书默认参数（DEFAULT）+ 3×3 邻域网格（GRID）用于稳健性检验，不做寻优。"""
import itertools
import numpy as np
import pandas as pd
from data import load_raw

PX, _ = load_raw()


def _wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def _atr(n):
    c, h, l = PX.close, PX.high, PX.low
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return _wilder(tr, n)


def raw(name, n, k):
    """返回 (buy_state, sell_state) 两个布尔序列。"""
    c, h, l, v = PX.close, PX.high, PX.low, PX.volume
    if name == "布林带":
        m, s = c.rolling(n).mean(), c.rolling(n).std(ddof=0)
        return c < m - k * s, c > m + k * s
    if name == "RSI":
        d = c.diff()
        r = 100 - 100 / (1 + _wilder(d.clip(lower=0), n) / _wilder(-d.clip(upper=0), n))
        return r < k, r > 100 - k
    if name == "KDJ":
        rsv = (c - l.rolling(n).min()) / (h.rolling(n).max() - l.rolling(n).min()) * 100
        K = rsv.ewm(alpha=1 / 3, adjust=False).mean()
        D = K.ewm(alpha=1 / 3, adjust=False).mean()
        up = (K > D) & (K.shift() <= D.shift())
        dn = (K < D) & (K.shift() >= D.shift())
        return up & (K.shift() < k), dn & (K.shift() > 100 - k)
    if name == "BIAS":
        b = c / c.rolling(n).mean() - 1
        return b < -k / 100, b > k / 100
    if name == "W%R":
        hh, ll = h.rolling(n).max(), l.rolling(n).min()
        w = (hh - c) / (hh - ll) * -100
        return (w > -100 + k) & (w.shift() <= -100 + k), (w < -k) & (w.shift() >= -k)
    if name == "ATR通道":
        m = c.rolling(n).mean()
        a = _atr(14)
        return c < m - k * a, c > m + k * a
    if name == "凯尔特纳":
        m = c.ewm(span=n, adjust=False).mean()
        a = _atr(10)
        return c < m - k * a, c > m + k * a
    if name == "VWAP偏离":
        tp = (h + l + c) / 3
        vw = (tp * v).rolling(n).sum() / v.rolling(n).sum()
        dv = c / vw - 1
        return dv < -k / 100, dv > k / 100
    if name == "波动率分位":
        rv = np.log(c).diff().rolling(n).std()
        pct = rv.rolling(750, min_periods=244).rank(pct=True) * 100
        return pct > k, pct < 100 - k          # 恐慌=买；平静=卖
    raise KeyError(name)


DEFAULT = {"布林带": (20, 2.0), "RSI": (14, 30), "KDJ": (9, 20), "BIAS": (20, 5.0), "W%R": (14, 20),
           "ATR通道": (20, 2.0), "凯尔特纳": (20, 2.0), "VWAP偏离": (20, 5.0), "波动率分位": (20, 80)}
GRID = {"布林带": ((15, 20, 30), (1.5, 2.0, 2.5)), "RSI": ((10, 14, 20), (25, 30, 35)),
        "KDJ": ((7, 9, 12), (15, 20, 25)), "BIAS": ((10, 20, 30), (4.0, 5.0, 6.0)),
        "W%R": ((10, 14, 20), (15, 20, 25)), "ATR通道": ((15, 20, 30), (1.5, 2.0, 2.5)),
        "凯尔特纳": ((15, 20, 30), (1.5, 2.0, 2.5)), "VWAP偏离": ((10, 20, 30), (4.0, 5.0, 6.0)),
        "波动率分位": ((10, 20, 40), (75, 80, 85))}
NAMES = list(DEFAULT)


def grid(name):
    return list(itertools.product(*GRID[name]))


def channel_trend(n=20, k=2.0, kind="凯尔特纳"):
    """通道突破型趋势状态（结构性替代 U）：收盘上破上轨=1，下破下轨=0，其余沿用前值（滞回）。"""
    c = PX.close
    if kind == "凯尔特纳":
        m, a = c.ewm(span=n, adjust=False).mean(), _atr(10)
    else:
        m, a = c.rolling(n).mean(), _atr(14)
    st = pd.Series(np.nan, c.index)
    st[c > m + k * a] = 1.0
    st[c < m - k * a] = 0.0
    return st.ffill()
