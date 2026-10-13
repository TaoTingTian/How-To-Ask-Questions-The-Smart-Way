"""数据层：读入原始数据，按 V1.6 附录计算 V、U，并计算各技术/波动率指标。
所有指标都在 T 日收盘后可得；策略在 T+1 日使用（引擎负责错位）。"""
import numpy as np
import pandas as pd
from pathlib import Path

D = Path(__file__).parent / "data"


def _series(name):
    s = pd.read_csv(D / f"{name}.csv", parse_dates=["date"]).set_index("date")["value"]
    return s[~s.index.duplicated()].sort_index()


def load_raw():
    px = pd.read_csv(D / "hs300_ohlcv.csv", index_col=0, parse_dates=True)
    px.index.name = "date"
    px = px[["open", "high", "low", "close", "volume", "money"]].astype(float)
    val = pd.DataFrame({k: _series(k) for k in ["pe", "pb", "dy", "y10"]}).dropna()
    return px, val


# ---------------- 估值分 V（附录 A–C） ----------------
def _pct_window(x: pd.Series, years: int, min_years: float = 3.0):
    """Pct_W(x)：窗口 [t−W年, t−1] 内 ≥ x_t 的样本占比 ×100；有效样本不足 3 年返回 NaN。"""
    idx = x.index
    vals = x.values
    out = np.full(len(x), np.nan)
    start0 = idx[0]
    for i in range(1, len(x)):
        t = idx[i]
        if np.isnan(vals[i]):
            continue
        lo = t - pd.DateOffset(years=years)
        j0 = idx.searchsorted(lo, side="left")
        w = vals[j0:i]
        w = w[~np.isnan(w)]
        if len(w) == 0:
            continue
        # 有效样本跨度不足 3 年则不计算
        first_valid = idx[j0:i][~np.isnan(vals[j0:i])][0]
        if (t - first_valid).days < 365.25 * min_years:
            continue
        out[i] = (w >= vals[i]).sum() / len(w) * 100
    return pd.Series(out, idx)


def valuation_score(val: pd.DataFrame):
    pe, pb, dy, y = val.pe, val.pb, val.dy / 100, val.y10 / 100
    roe = pb / pe
    idx = val.index
    roe_n = np.full(len(idx), np.nan)
    rv = roe.values
    for i in range(1, len(idx)):
        t = idx[i]
        if (t - idx[0]).days < 365.25 * 5:
            continue
        j0 = idx.searchsorted(t - pd.DateOffset(years=5), side="left")
        roe_n[i] = rv[j0:i].mean()
    roe_n = pd.Series(roe_n, idx)
    ind = pd.DataFrame({"EY": roe_n / pb, "BP": 1 / pb, "DY": dy})
    ind["ERP"] = ind.EY - y
    pct = {}
    for k in ind:
        pct[k] = (_pct_window(ind[k], 10) + _pct_window(ind[k], 5)) / 2
    pct = pd.DataFrame(pct)
    V = pct.mean(axis=1, skipna=False)
    return V, pct, ind


# ---------------- 技术指标 ----------------
def _wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def indicators(px: pd.DataFrame):
    c, h, l, v = px.close, px.high, px.low, px.volume
    o = pd.DataFrame(index=px.index)
    o["close"] = c
    for k in (40, 80, 160):
        o[f"ma{k}"] = c.rolling(k).mean()
    o["U"] = ((c > o.ma40).astype(int) + (c > o.ma80) + (c > o.ma160)) / 3
    o.loc[o.ma160.isna(), "U"] = np.nan
    # 布林带 20,2
    ma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std(ddof=0)
    o["bb_pctb"] = (c - (ma20 - 2 * sd20)) / (4 * sd20)
    # RSI 14
    d = c.diff()
    o["rsi"] = 100 - 100 / (1 + _wilder(d.clip(lower=0), 14) / _wilder(-d.clip(upper=0), 14))
    # KDJ 9,3,3
    llv, hhv = l.rolling(9).min(), h.rolling(9).max()
    rsv = (c - llv) / (hhv - llv) * 100
    o["kdj_k"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    o["kdj_d"] = o.kdj_k.ewm(alpha=1 / 3, adjust=False).mean()
    # BIAS 20
    o["bias"] = c / ma20 - 1
    # W%R 14
    h14, l14 = h.rolling(14).max(), l.rolling(14).min()
    o["wr"] = (h14 - c) / (h14 - l14) * -100
    # ATR
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14, atr10 = _wilder(tr, 14), _wilder(tr, 10)
    o["atrch_z"] = (c - ma20) / atr14          # ATR 通道：MA20 ± k·ATR14
    ema20 = c.ewm(span=20, adjust=False).mean()
    o["kc_z"] = (c - ema20) / atr10            # 凯尔特纳：EMA20 ± k·ATR10
    # 20 日成交量加权均价（日线近似 VWAP）
    tp = (h + l + c) / 3
    o["vwap_dev"] = c / ((tp * v).rolling(20).sum() / v.rolling(20).sum()) - 1
    # 已实现波动率分位（期权 IV 缺数据时的替代检验）
    rv = np.log(c).diff().rolling(20).std() * np.sqrt(244)
    o["rv20"] = rv
    o["rv_pct"] = rv.rolling(750, min_periods=244).rank(pct=True) * 100
    return o


def build():
    px, val = load_raw()
    V, pct, ind = valuation_score(val)
    tech = indicators(px)
    df = tech.join(pd.DataFrame({"V": V, "dy": val.dy}), how="inner")
    df["ret"] = df.close.pct_change()
    return df, pct, ind


if __name__ == "__main__":
    df, pct, ind = build()
    df.to_pickle(Path(__file__).parent / "out" / "panel.pkl")
    pct.to_pickle(Path(__file__).parent / "out" / "pct.pkl")
    print(df.dropna(subset=["V"]).iloc[[0, -1]].T)
    print(df.V.describe())
