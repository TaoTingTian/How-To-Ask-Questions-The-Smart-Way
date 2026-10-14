"""V1.10 回测：与 V1.6–V1.9 对比，并拆解两项修改的各自作用。

V1.10 = V1.7 的单段式结构（周线冲高回落止盈 + 日线超卖回投 + 企稳线）+ 两项修改：
  1. 周线过热带滞回：进入条件不变（RSI_w ≥ 70 或 周收盘 > KC_w 上轨）；退出须同时满足
     RSI_w < 60、周收盘 < KC_w 上轨、周收盘 ≤ M − 1 × ATR_w（M = 过热期最高周收盘）。
     S = 1：最近完成周不在过热，且最近退出周是该周或之前 3 周之一。
  2. V 的第四项：股债利差 → 隐含风险溢价 IRP = DY × (1 + g) + g − y，
     g = ROE_n × (1 − clip(PR_n, 0, 1))，PR = DY × PE，ROE_n、PR_n 为 [t−5 年, t−1] 均值。

对照：V1.10a（只改 S）、V1.10b（只改 V）用于拆解。
假回落卖出率（V1.10 文档附录 F 的定义，统一用于所有版本）：卖出后 26 周内出现周线过热、
且周收盘超过卖出前过热期最高周收盘的卖出占比。“卖出前过热期最高周收盘”取卖出前最近一段
连续过热周（原始过热条件）起点至卖出周的最高周收盘。
"""
import json
import multiprocessing as mp
import os
import time

import numpy as np
import pandas as pd

import analysis as AN
import engine as En
import gen
import gen2
import indicators as I
import study
from engine import START, YEAR

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = ["1.6", "1.7", "1.8", "1.9", "1.10", "1.10a", "1.10b"]


def weekly(df):
    c, h, l = df.close.values, df.high.values, df.low.values
    wk = pd.Series(df.date.values).dt.to_period("W").values
    last = np.r_[wk[1:] != wk[:-1], True]
    widx = np.where(last)[0]
    grp = np.cumsum(np.r_[True, wk[1:] != wk[:-1]]) - 1
    wc = c[widx]
    wh = pd.Series(h).groupby(grp).max().values
    wl = pd.Series(l).groupby(grp).min().values
    rw = I.rsi(wc)
    kw = I.ema(wc)
    aw = I.atr(wh, wl, wc)
    up = kw + 2 * aw
    hot = (rw >= 70) | (wc > up)
    hot = np.where(np.isnan(rw) | np.isnan(aw), False, hot)
    return dict(widx=widx, wc=wc, rw=rw, up=up, aw=aw, hot=hot)


def s_hysteresis(W, n):
    nw = len(W["wc"])
    O = np.zeros(nw, bool)
    S = np.zeros(nw, np.int8)
    M = np.nan
    e = -10 ** 9
    for w in range(nw):
        prev = O[w - 1] if w > 0 else False
        if not prev:
            if W["hot"][w]:
                O[w] = True
                M = W["wc"][w]
        else:
            M = max(M, W["wc"][w])
            ok = (not np.isnan(W["rw"][w])) and W["rw"][w] < 60 and W["wc"][w] < W["up"][w] and W["wc"][w] <= M - W["aw"][w]
            if ok:
                O[w] = False
                e = w
            else:
                O[w] = True
        S[w] = int((not O[w]) and (w - e) <= 3)
    pos = np.searchsorted(W["widx"], np.arange(n), side="right") - 1
    Sd = np.zeros(n, np.int8)
    ok = pos >= 0
    Sd[ok] = S[pos[ok]]
    return Sd


def v_irp(df):
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe5 = pd.Series(pb / pe).rolling(5 * YEAR).mean().shift(1).values
    pr5 = pd.Series(dy * pe).rolling(5 * YEAR).mean().shift(1).values
    g = roe5 * (1 - np.clip(pr5, 0, 1))
    ey = roe5 / pb
    pct2 = lambda x: (I.pct_score(x, 10) + I.pct_score(x, 5)) / 2
    return (pct2(ey) + pct2(1 / pb) + pct2(dy) + pct2(dy * (1 + g) + g - y)) / 4


def false_drop(r, W, n):
    """每笔卖出：卖出后 26 周内出现过热且周收盘超过卖出前过热期最高周收盘 → 假回落卖出。"""
    widx, wc, hot = W["widx"], W["wc"], W["hot"]
    pos = np.searchsorted(widx, np.arange(n), side="right") - 1
    out = []
    for x in r["trades"]:
        if x[1] != "sell":
            continue
        t = x[0]
        w = pos[t - 1]                       # 卖出时最近完成的周
        if w < 0:
            continue
        k = w
        while k >= 0 and not hot[k]:         # 回溯到最近一段过热
            k -= 1
        if k < 0:
            continue
        j = k
        while j > 0 and hot[j - 1]:
            j -= 1
        m_pre = wc[j:w + 1].max()
        fut = slice(w + 1, min(len(wc), w + 27))
        fd = bool(np.any(hot[fut] & (wc[fut] > m_pre)))
        later = wc[fut]
        out.append(dict(fd=fd, amt=x[2], ret26=float(later.max() / x[3] - 1) if len(later) else np.nan,
                        dd26=float(later.min() / x[3] - 1) if len(later) else np.nan))
    return out


def trap_stats(D, r, traps, n):
    res = []
    for (dr, ext, ts, te, rr) in traps:
        lo, hi = ts - 20, te + 20
        tds = [x for x in r["trades"] if lo <= x[0] <= hi]
        g_sell = g_buy = 0.0
        ns = nb = 0
        for x in tds:
            t, kind, val = x[0], x[1], x[2]
            h = max(rr, t + 20)
            if h >= n:
                continue
            chg = D.nav[h] / D.nav[t] - 1
            if kind == "sell":
                g_sell += -val * chg / r["total"][t]
                ns += 1
            else:
                g_buy += val * chg / r["total"][t]
                nb += 1
        res.append(dict(dir=int(dr), n=len(tds), ns=ns, nb=nb, g_sell=g_sell, g_buy=g_buy))
    return res


def crisis_stats(D, r, events, n):
    out = []
    for e in events:
        if e["type"] not in ("crisis", "bubble") or e["peak"] < START + 60 or e["trough"] >= n - 10:
            continue
        pk, th = e["peak"], e["trough"]
        lowp = D.close[pk:th + 1].min()
        buys = [x for x in r["trades"] if x[1] != "sell" and pk <= x[0] <= th + 126 and x[3] <= 1.15 * lowp]
        sells = [x for x in r["trades"] if x[1] == "sell" and pk - 252 <= x[0] <= pk + 21]
        pre = r["twr"][pk - 60:pk + 1].max()
        k0 = pk + int(np.argmin(r["twr"][pk:min(n, th + 126)]))
        rep = next((u - k0 for u in range(k0, n) if r["twr"][u] >= pre), None)
        sp = sum(x[2] * x[3] for x in sells) / sum(x[2] for x in sells) / D.close[pk] if sells else np.nan
        out.append(dict(type=e["type"], escape=bool(r["p"][pk - 1] <= 0.6), p_peak=float(r["p"][pk - 1]), bottom=bool(buys),
                        repair=rep, dd=float(1 - r["twr"][k0] / pre), sell_vs_peak=float(sp)))
    return out


def job(arg):
    setname, key, seed, spec = arg
    if setname == "drift":
        df, meta, _ = gen2.make_drift_path(seed, spec["dr"], spec["sp"])
    else:
        df, meta = gen.make_valid_path(key, seed, spec or None)
    n = len(df)
    ind = I.compute(df)
    W = weekly(df)
    S_new = s_hysteresis(W, n)
    V_new = v_irp(df)
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    traps = [tp for tp in meta.get("traps", gen.detect_traps(df.dev.values)) if tp[2] >= START + 20]
    base_V, base_S = ind["V"].copy(), ind["S"].copy()
    out = dict(set=setname, key=key, seed=seed, v={}, n_traps=len(traps),
               s_days=dict(old=float(base_S[START:].mean()), new=float(S_new[START:].mean())))
    for var in VARIANTS:
        ver = var if var in ("1.6", "1.7", "1.8", "1.9") else "1.7"
        ind["V"] = V_new if var in ("1.10", "1.10b") else base_V
        ind["V3"] = ind["V"]
        ind["S"] = S_new if var in ("1.10", "1.10a") else base_S
        D = En.Data(df, ind, None, fail)
        r = En.run(D, ver, cost=True, review=(ver != "1.6"), record=True)
        m = AN.perf(D, r, True)
        m.pop("cost_kind", None)
        m["traps"] = trap_stats(D, r, traps, n)
        m["crises"] = crisis_stats(D, r, meta["events"], n)
        m["fdrop"] = false_drop(r, W, n)
        out["v"][var] = m
    return out


def build_jobs():
    jobs = [("main", kind, seed, None) for no, kind, name, ds, seed in gen.PATH_SPECS]
    rng = np.random.default_rng(20261014)
    for no, kind, name, ds, seed in gen.PATH_SPECS:
        for j in range(AN.MC_SEEDS):
            prm = {}
            if kind in ("slow_up", "slow_down"):
                prm["slow_rate"] = float(rng.uniform(0.03, 0.08))
            if kind in ("jump_up", "jump_down"):
                prm["jump_size"] = float(rng.uniform(0.15, 0.30))
            jobs.append(("mc", kind, 100000 + no * 1000 + j, prm or None))
    for key, name, grp, desc, dr, sp in study.SCEN:
        for k in range(12):
            jobs.append(("drift", key, study.SEED0 + k, dict(dr=dr, sp=sp)))
    return jobs


def main():
    jobs = build_jobs()
    t0 = time.time()
    with mp.Pool(4) as pool:
        res = []
        for k, r in enumerate(pool.imap_unordered(job, jobs, chunksize=2)):
            res.append(r)
            if k % 100 == 0:
                print(f"{k + 1}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    json.dump(AN.to_jsonable(res), open(os.path.join(HERE, "results", "v110_raw.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
