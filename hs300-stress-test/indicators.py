"""策略文档附录 C/D 的指标计算 + 多周期中枢漂移预警指标。所有数组按日对齐，值为当日收盘后可得。"""
import numpy as np
import pandas as pd

YEAR = 252


def pct_score(x, W_years, min_years=3):
    """Pct_W(x) = 窗口 [t−W 年, t−1] 内指标值 ≥ x_t 的样本占比 ×100；窗口不足用全部样本；样本 < 3 年不计算。"""
    n = len(x)
    W = W_years * YEAR
    out = np.full(n, np.nan)
    valid = ~np.isnan(x)
    first = np.argmax(valid)
    for t in range(n):
        if not valid[t]:
            continue
        lo = max(first, t - W)
        if t - lo < min_years * YEAR:
            continue
        s = x[lo:t]
        out[t] = (s >= x[t]).sum() * 100.0 / len(s)
    return out


def valuation_score(df, windows=(10, 5)):
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe = pb / pe
    roe5 = pd.Series(roe).rolling(5 * YEAR).mean().shift(1).values   # [t−5年, t−1]
    ey = roe5 / pb
    bp = 1 / pb
    erp = ey - y
    pcts = []
    for ind in (ey, bp, dy, erp):
        ps = [pct_score(ind, w) for w in windows]
        pcts.append(np.mean(ps, axis=0))
    V = np.mean(pcts, axis=0)
    return V, roe5


def rsi(c, n=14):
    out = np.full(len(c), np.nan)
    d = np.diff(c)
    g = np.maximum(d, 0)
    l = np.maximum(-d, 0)
    if len(d) < n:
        return out
    ag, ad = g[:n].mean(), l[:n].mean()
    out[n] = 100 if ad == 0 else 100 - 100 / (1 + ag / ad)
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + g[i]) / n
        ad = (ad * (n - 1) + l[i]) / n
        out[i + 1] = 100 if ad == 0 else 100 - 100 / (1 + ag / ad)
    return out


def ema(c, n=20):
    out = np.empty(len(c))
    out[0] = c[0]
    a = 2 / (n + 1)
    for i in range(1, len(c)):
        out[i] = out[i - 1] + a * (c[i] - out[i - 1])
    return out


def atr(h, l, c, n=10):
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    tr[1:] = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
    out = np.full(len(c), np.nan)
    if len(c) < n:
        return out
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def compute(df, val=None):
    """val: 可传入预先算好的 (V, roe5)，此时跳过估值分计算，V3 取 V。"""
    n = len(df)
    c, h, l = df.close.values, df.high.values, df.low.values
    ind = {}
    if val is None:
        V, roe5 = valuation_score(df)
        V3, _ = valuation_score(df, windows=(3,))
    else:
        V, roe5 = val
        V3 = V
    ind["V"], ind["V3"], ind["roe5"] = V, V3, roe5
    ma = {k: pd.Series(c).rolling(k).mean().values for k in (20, 40, 80, 160)}
    U = ((c > ma[40]).astype(float) + (c > ma[80]) + (c > ma[160])) / 3.0
    U[np.isnan(ma[160])] = np.nan
    ind["U"] = U
    ind["ma160"] = ma[160]
    # 日线
    rd = rsi(c)
    kc_mid = ema(c)
    a10 = atr(h, l, c)
    ind["B"] = ((rd <= 30) | (c < kc_mid - 2 * a10)).astype(np.int8)
    ind["atr_rel"] = a10 / c
    ind["rsi_d"] = rd
    # 周线（自然周）
    wk = pd.Series(df.date.values).dt.to_period("W").values
    last_of_week = np.r_[wk[1:] != wk[:-1], True]
    widx = np.where(last_of_week)[0]
    wc = c[widx]
    grp = np.cumsum(np.r_[True, wk[1:] != wk[:-1]]) - 1
    wh = pd.Series(h).groupby(grp).max().values
    wl = pd.Series(l).groupby(grp).min().values
    rw = rsi(wc)
    kw = ema(wc)
    aw = atr(wh, wl, wc)
    hot = (rw >= 70) | (wc > kw + 2 * aw)
    hot = np.where(np.isnan(rw) | np.isnan(aw), False, hot)
    Sw = np.zeros(len(widx), np.int8)
    for w in range(4, len(widx)):
        Sw[w] = int((not hot[w]) and hot[w - 4:w].any())
    # 日度化：第 t 日收盘时“最近一个已完成的周”= 最后一个 widx ≤ t
    S = np.zeros(n, np.int8)
    pos = np.searchsorted(widx, np.arange(n), side="right") - 1
    ok = pos >= 0
    S[ok] = Sw[pos[ok]]
    ind["S"] = S
    ind["week_hot"] = np.zeros(n, np.int8)
    ind["week_hot"][ok] = hot[pos[ok]].astype(np.int8)
    return ind


# ---------------- 多周期中枢漂移预警 ----------------
def multi_cycle(df, ind):
    """返回 up/down 两个方向上短/中/长三个周期的触发布尔数组（每个周期 3 项指标中 ≥2 项成立即触发）。"""
    n = len(df)
    c = df.close.values
    lpe = np.log(df.pe.values)
    V = ind["V"]
    s = pd.Series(lpe)
    mean5 = s.rolling(5 * YEAR, min_periods=3 * YEAR).mean().values
    sd5 = s.rolling(5 * YEAR, min_periods=3 * YEAR).std().values
    dev = (lpe - mean5) / sd5
    # 短周期（60 日）
    dev60 = pd.Series(dev).rolling(60).mean().values
    rsi60 = pd.Series(ind["rsi_d"]).rolling(60).mean().values
    ma20 = pd.Series(c).rolling(20).mean().values
    ma20_slope = ma20 / np.r_[np.full(60, np.nan), ma20[:-60]] - 1
    # 中周期（252 日）
    hi_days = pd.Series((V > 70).astype(float)).rolling(YEAR).sum().values
    lo_days = pd.Series((V < 30).astype(float)).rolling(YEAR).sum().values
    ma160 = ind["ma160"]
    ma160_slope = ma160 / np.r_[np.full(YEAR, np.nan), ma160[:-YEAR]] - 1
    vbias = pd.Series(V).rolling(YEAR).mean().values - 50
    # 长周期（756 日）
    L = 3 * YEAR
    roe5 = ind["roe5"]
    roe_chg = roe5 / np.r_[np.full(L, np.nan), roe5[:-L]] - 1
    ysm = pd.Series(df.y.values).rolling(YEAR).mean().values
    y_chg = ysm - np.r_[np.full(L, np.nan), ysm[:-L]]
    center_rate = (mean5 - np.r_[np.full(L, np.nan), mean5[:-L]]) / 3.0

    def two_of_three(a, b, c_):
        return (np.nan_to_num(a.astype(float)) + np.nan_to_num(b.astype(float)) + np.nan_to_num(c_.astype(float))) >= 2

    with np.errstate(invalid="ignore"):
        out = {}
        out["up_short"] = two_of_three(dev60 >= 1.0, (rsi60 >= 50) & (rsi60 <= 70), ma20_slope > 0)
        out["up_mid"] = two_of_three(hi_days >= 150, ma160_slope > 0, vbias >= 20)
        out["up_long"] = two_of_three(roe_chg >= 0.05, y_chg <= -0.005, center_rate >= 0.03)
        out["down_short"] = two_of_three(dev60 <= -1.0, (rsi60 >= 30) & (rsi60 <= 50), ma20_slope < 0)
        out["down_mid"] = two_of_three(lo_days >= 150, ma160_slope < 0, vbias <= -20)
        out["down_long"] = two_of_three(roe_chg <= -0.05, y_chg >= 0.005, center_rate <= -0.03)
    for kk in list(out):
        out[kk][np.isnan(V)] = False
    # 共振计数（20 日内保持，防止闪烁）
    for d in ("up", "down"):
        cnt = out[d + "_short"].astype(int) + out[d + "_mid"].astype(int) + out[d + "_long"].astype(int)
        out[d + "_count"] = pd.Series(cnt).rolling(20, min_periods=1).max().values.astype(int)
    for d in ("up", "down"):
        out[d + "_ml"] = pd.Series((out[d + "_mid"] & out[d + "_long"]).astype(float)).rolling(20, min_periods=1).max().values > 0
    out["dev_obs"] = dev
    return out


def truth_drift(df, thr=0.12, L=3 * YEAR, merge_gap=63):
    """真实中枢漂移状态：过去 3 年中枢 log 变动 ≥ +0.12（上移）或 ≤ −0.12（下移）。返回 state 数组与事件列表。"""
    c = np.log(df.center.values)
    n = len(c)
    chg = np.full(n, 0.0)
    chg[L:] = c[L:] - c[:-L]
    state = np.where(chg >= thr, 1, np.where(chg <= -thr, -1, 0))
    eps = []
    for d in (1, -1):
        on = state == d
        i = 0
        runs = []
        while i < n:
            if on[i]:
                j = i
                while j < n and on[j]:
                    j += 1
                runs.append([i, j - 1])
                i = j
            else:
                i += 1
        merged = []
        for r in runs:
            if merged and r[0] - merged[-1][1] <= merge_gap:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        for a, b in merged:
            # 漂移起点：回溯到中枢开始移动的日子（日变动非零的连续段起点）
            k = a
            while k > 0 and d * (c[k] - c[k - 1]) > 1e-9:
                k -= 1
            eps.append(dict(dir=d, onset=a, move_start=k, end=b))
    return state, eps
