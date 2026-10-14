"""多行业模拟 · 加入行业重估：成分迁移与行业自身估值中枢变化同时存在时，各种 V 口径能挽回多少。

与 sector.py 的区别：
  1. 每个行业的估值中枢可以变化（行业重估，视为基本面导致的中枢移动，理想 V 不把它当贵贱），
     ROE 中枢也可以变化；
  2. 市值权重对重估有反应：权重 ∝ 目标权重 × 重估倍数（行业变贵，市值占比自然上升）；
  3. 增加“固定权重 + 隐含风险溢价”的组合口径。

V 口径：orig / ierp / cw / neutral / cw_ierp / oracle（含义见 sector.py；cw_ierp = 固定权重口径中用隐含风险溢价替换股债利差）
"""
import json
import multiprocessing as mp
import os
import time

import numpy as np
import pandas as pd

import engine as En
import gen
import indicators as I
import sector as S1
from engine import START, YEAR

HERE = os.path.dirname(os.path.abspath(__file__))
VERS = ["1.6", "1.7", "1.8", "1.9"]
METHODS = ["orig", "ierp", "cw", "neutral", "cw_ierp", "oracle"]
ONE = np.ones(5)
UP = np.array([1, 1, 1.3, 1.3, 1.6])

SCEN = [
    dict(key="B0", name="基准：无迁移、无重估", desc="权重与各行业中枢都不变"),
    dict(key="P1", name="纯成分迁移（温和）", desc="权重向高 PE 行业迁移，各行业中枢不变（对照）", w=S1.W_MILD),
    dict(key="R1", name="成长行业上修", desc="消费、医药中枢 +30%，科技 +60%；无外生调样（市值占比随之上升）", rr=UP),
    dict(key="R2", name="价值行业下杀", desc="银行、周期地产中枢 −30%；无外生调样", rr=np.array([0.7, 0.7, 1, 1, 1])),
    dict(key="R3", name="迁移 + 同向上修（成长牛）", desc="温和迁移，同时成长行业上修（同 R1）", w=S1.W_MILD, rr=UP),
    dict(key="R4", name="迁移 + 迁入行业被下杀", desc="强迁移，但消费、医药中枢 −20%、科技 −35%", w=S1.W_STRONG, rr=np.array([1, 1, 0.8, 0.8, 0.65])),
    dict(key="R5", name="沪深300 型", desc="温和迁移 + 各行业中枢下修（银行 −25%、周期 −30%、其余 −15%~−25%）+ ROE 下滑（银行 −28%）",
         w=S1.W_MILD, rr=np.array([0.75, 0.7, 0.85, 0.85, 0.75]), roe=np.array([0.72, 0.8, 0.9, 0.9, 0.9])),
    dict(key="R6", name="科技快速重估", desc="科技中枢 3 个月内 +60%（第 12 年），无外生调样", rr=np.array([1, 1, 1, 1, 1.6]), rr_speed="fast"),
    dict(key="R7", name="自然迁移 + 成长上修", desc="科技盈利每年快 5%、银行慢 3%，同时成长行业上修（同 R1）", natural=True, rr=UP),
]


def make_path(seed, sc):
    base, meta = gen.make_valid_path("base", seed, dict(g=0.05))
    n = len(base)
    rng = np.random.default_rng(seed + 991)
    K = 5
    dt = 1 / YEAR
    s_w = S1.ramp(n, "slow")
    s_r = S1.ramp(n, sc.get("rr_speed", "slow"))
    rr = sc.get("rr", ONE)
    rr_t = np.exp(np.outer(s_r, np.log(rr)))                     # 重估倍数路径
    pe_c = S1.PE0 * rr_t
    roe_t = 1 + np.outer(s_w, sc.get("roe", ONE) - 1)
    dm = base.dev.values
    e = np.zeros((n, K))
    z = rng.standard_normal((n, K))
    for i in range(1, n):
        e[i] = e[i - 1] * (1 - 2.0 * dt) + 0.09 * np.sqrt(dt) * z[i]
    pe_i = pe_c * np.exp(S1.BETA * dm[:, None] + e)
    eps_m = base.close.values / base.pe.values
    gdiff = S1.GROWTH_N6 if sc.get("natural") else np.zeros(K)
    eps_i = eps_m[:, None] * np.exp(np.outer(np.arange(n) * dt, gdiff) + np.cumsum(0.003 * rng.standard_normal((n, K)), 0) * 0.3)
    roe_i = S1.ROE0 * roe_t * (base.roe.values / 0.12)[:, None]
    pb_i = pe_i * roe_i
    dy_i = S1.PAY0 * (1 + 0.05 * np.sin(np.arange(n)[:, None] / YEAR * 2 * np.pi / 4.3 + np.arange(K))) / pe_i
    p_i = pe_i * eps_i
    r_i = np.vstack([np.zeros(K), p_i[1:] / p_i[:-1] - 1])
    if sc.get("natural"):
        cap = S1.W_START * p_i / p_i[0]
        w = cap / cap.sum(1, keepdims=True)
    else:
        wt = sc.get("w", S1.W_START)
        w = (S1.W_START + np.outer(s_w, wt - S1.W_START)) * rr_t
        w = w / w.sum(1, keepdims=True)
    wl = np.vstack([w[0], w[:-1]])
    r_idx = (wl * r_i).sum(1)
    div_idx = (wl * dy_i).sum(1) / YEAR
    close = 1000 * np.cumprod(1 + r_idx)
    tr = 1000 * np.cumprod(1 + r_idx + np.r_[0, div_idx[:-1]])
    ratio = close / base.close.values
    pe = 1 / (w / pe_i).sum(1)
    pb = 1 / (w / pb_i).sum(1)
    dy = (w * dy_i).sum(1)
    center = 1 / (w / pe_c).sum(1)
    cen_fixed_w = 1 / (S1.W_START / pe_c).sum(1)                 # 只有重估、权重不变时的中枢
    cen_fixed_r = 1 / (w / S1.PE0).sum(1)                         # 只有迁移、中枢不变时的中枢
    df = pd.DataFrame(dict(date=base.date.values, open=base.open.values * np.r_[ratio[0], ratio[:-1]],
                           high=base.high.values * ratio, low=base.low.values * ratio, close=close, tr=tr,
                           pe=pe, pb=pb, dy=dy, y=base.y.values, roe=pb / pe, center=center, dev=np.log(pe) - np.log(center)))
    df["high"] = np.maximum(df.high, np.maximum(df.open, df.close))
    df["low"] = np.minimum(df.low, np.minimum(df.open, df.close))
    sec = dict(w=w, pe=pe_i, pb=pb_i, dy=dy_i)
    decomp = dict(total=float(center[-1] / center[0] - 1), mix=float(cen_fixed_r[-1] / cen_fixed_r[0] - 1),
                  rerate=float(cen_fixed_w[-1] / cen_fixed_w[0] - 1))
    return df, meta, sec, decomp


def v_constweight(sec, y, ierp=False, step=5):
    n, K = sec["w"].shape
    roe5_i = np.column_stack([S1.roe5_of(sec["pb"][:, k], sec["pe"][:, k]) for k in range(K)])
    ey_i = roe5_i / sec["pb"]
    bp_i = 1 / sec["pb"]
    dy_i = sec["dy"]
    out = np.full(n, np.nan)
    W10, W5 = 10 * YEAR, 5 * YEAR
    for t in range(START - 1 - step * 2, n, step):
        w = sec["w"][t]
        lo = max(0, t - W10)
        seg = slice(lo, t + 1)
        ey = ey_i[seg] @ w
        bp = bp_i[seg] @ w
        dy = dy_i[seg] @ w
        if ierp:
            roe5 = ey / bp                                         # 汇总后的 ROE5 ≈ EY × PB
            payout = dy / ey
            g = np.clip(0.5 * roe5 * (1 - payout), 0, 0.08)
            last = dy * (1 + g) + g - y[seg]
        else:
            last = ey - y[seg]
        vals = []
        for x in (ey, bp, dy, last):
            cur, hist = x[-1], x[:-1]
            hist = hist[~np.isnan(hist)]
            if np.isnan(cur) or len(hist) < 3 * YEAR:
                vals = None
                break
            vals.append((np.mean(hist >= cur) * 100 + np.mean(hist[-W5:] >= cur) * 100) / 2)
        if vals is not None:
            out[t:t + step] = np.mean(vals)
    return out


def job(arg):
    key, seed = arg
    sc = [s for s in SCEN if s["key"] == key][0]
    df, meta, sec, decomp = make_path(seed, sc)
    n = len(df)
    y = df.y.values
    V = {}
    V["orig"], roe5 = S1.v_index(df)
    V["ierp"], _ = S1.v_index(df, ierp=True)
    V["cw"] = v_constweight(sec, y)
    V["neutral"] = S1.v_neutral(sec, y)
    V["cw_ierp"] = v_constweight(sec, y, ierp=True)
    V["oracle"] = S1.pct2(-df.dev.values)
    ind = I.compute(df, val=(V["orig"], roe5))
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    w = slice(START, n)
    common = np.all([~np.isnan(V[m][w]) for m in METHODS], axis=0)
    out = dict(key=key, seed=seed, decomp=decomp, m={},
               pe=[float(df.pe.values[START:START + YEAR].mean()), float(df.pe.values[-YEAR:].mean())],
               pb=[float(df.pb.values[START:START + YEAR].mean()), float(df.pb.values[-YEAR:].mean())],
               dy=[float(df.dy.values[START:START + YEAR].mean()), float(df.dy.values[-YEAR:].mean())],
               roe=[float(df.roe.values[START:START + YEAR].mean()), float(df.roe.values[-YEAR:].mean())],
               w_end=sec["w"][-1].tolist())
    for mk in METHODS:
        v = V[mk][w]
        o = V["oracle"][w]
        rec = dict(corr=float(np.corrcoef(v[common], o[common])[0, 1]), rmse=float(np.sqrt(np.mean((v[common] - o[common]) ** 2))),
                   bias=float(np.mean(v[common] - o[common])), hi=float(np.nanmean(v > 70)))
        Vm = np.where(np.isnan(V[mk]), V["orig"], V[mk])
        ind["V"] = Vm
        ind["V3"] = Vm
        D = En.Data(df, ind, None, fail)
        for ver in VERS:
            r = En.run(D, ver, cost=True, review=(ver != "1.6"))
            bh = En.bench(D, r["inflow"], True, "bh")
            tw = r["twr"][START - 1:]
            rec[ver] = dict(x=En.xirr(r["inflow"], r["final"]), bh=En.xirr(bh["inflow"], bh["final"]),
                            mdd=float(np.max(1 - tw / np.maximum.accumulate(tw))))
        out["m"][mk] = rec
    return out


def main():
    N = 24
    jobs = [(s["key"], 8000 + k) for s in SCEN for k in range(N)]
    t0 = time.time()
    with mp.Pool(4) as pool:
        res = []
        for k, r in enumerate(pool.imap_unordered(job, jobs, chunksize=1)):
            res.append(r)
            if k % 36 == 0:
                print(f"{k + 1}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    by = {}
    for r in res:
        by.setdefault(r["key"], {})[r["seed"]] = r

    def se(a):
        a = np.asarray(a, float)
        return float(a.std(ddof=1) / np.sqrt(len(a)))

    agg = {}
    for sc in SCEN:
        rs = by[sc["key"]]
        seeds = sorted(rs)
        mean = lambda f: float(np.mean([f(rs[s]) for s in seeds]))
        rec = dict(name=sc["name"], desc=sc["desc"], n=len(seeds),
                   decomp={k: mean(lambda r: r["decomp"][k]) for k in ("total", "mix", "rerate")},
                   pe=[mean(lambda r: r["pe"][i]) for i in (0, 1)], pb=[mean(lambda r: r["pb"][i]) for i in (0, 1)],
                   dy=[mean(lambda r: r["dy"][i]) for i in (0, 1)], roe=[mean(lambda r: r["roe"][i]) for i in (0, 1)],
                   w_end=np.mean([rs[s]["w_end"] for s in seeds], 0).tolist())
        for mk in METHODS:
            m = {k: mean(lambda r: r["m"][mk][k]) for k in ("corr", "rmse", "bias", "hi")}
            for ver in VERS + ["avg"]:
                vv = VERS if ver == "avg" else [ver]
                dx = [np.mean([rs[s]["m"][mk][u]["x"] - rs[s]["m"]["orig"][u]["x"] for u in vv]) for s in seeds]
                dm = [np.mean([rs[s]["m"][mk][u]["mdd"] - rs[s]["m"]["orig"][u]["mdd"] for u in vv]) for s in seeds]
                ex = [np.mean([rs[s]["m"][mk][u]["x"] - rs[s]["m"][mk][u]["bh"] for u in vv]) for s in seeds]
                m[ver] = dict(dx=float(np.mean(dx)), dx_se=se(dx), dmdd=float(np.mean(dm)), ex=float(np.mean(ex)))
            rec[mk] = m
        agg[sc["key"]] = rec
    json.dump(dict(agg=agg, methods=METHODS, sectors=S1.SECT), open(os.path.join(HERE, "results", "sector2.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
