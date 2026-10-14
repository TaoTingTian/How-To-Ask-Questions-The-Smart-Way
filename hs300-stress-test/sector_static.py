"""只有成分（行业）权重、没有行业估值历史时的近似修正：静态估值快照法。

思路：固定权重口径需要行业估值历史，只是为了算出“权重变化本身让指数估值移动了多少”。
若只有一张“当前各行业典型估值”的快照（PE、PB、股息率），可近似：
    成分因子 mix_X(s) = 按 s 日权重、快照估值汇总的指数指标（盈利收益率 Σw/PE_i，1/PB Σw/PB_i，股息率 Σw×DY_i）
    把历史指数指标换算到今天的成分：X_adj(s) = X(s) × mix_X(t) / mix_X(s)，再取分位
只需要：指数自身的估值历史（附录 E 已有）+ 行业权重历史 + 一张行业估值快照。

检验（沿用 sector2 的 9 个情景 × 24 条路径）：
  orig        原版
  cw          精确固定权重（需要完整行业估值历史）
  snap        今天（路径末期）的行业中枢做快照
  snap_err    快照有误差：每个行业乘以 exp(N(0, 0.3))（约 ±30%）
  snap_start  用期初（重估前）的行业中枢做快照
  oracle      理想 V
"""
import json
import multiprocessing as mp
import os
import time

import numpy as np

import engine as En
import indicators as I
import sector as S1
import sector2 as S2
from engine import START, YEAR

HERE = os.path.dirname(os.path.abspath(__file__))
VERS = ["1.6", "1.7", "1.8", "1.9"]
METHODS = ["orig", "cw", "snap", "snap_err", "snap_start", "oracle"]


def v_snapshot(df, w, pe_s, pb_s, dy_s, step=5):
    n = len(df)
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe5 = S1.roe5_of(pb, pe)
    ey, bp = roe5 / pb, 1 / pb
    m_ey, m_bp, m_dy = w @ (1 / pe_s), w @ (1 / pb_s), w @ dy_s
    out = np.full(n, np.nan)
    W10, W5 = 10 * YEAR, 5 * YEAR
    for t in range(START - 1 - step * 2, n, step):
        seg = slice(max(0, t - W10), t + 1)
        e = ey[seg] * m_ey[t] / m_ey[seg]
        b = bp[seg] * m_bp[t] / m_bp[seg]
        d = dy[seg] * m_dy[t] / m_dy[seg]
        vals = []
        for x in (e, b, d, e - y[seg]):
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
    sc = [s for s in S2.SCEN if s["key"] == key][0]
    df, meta, sec, decomp = S2.make_path(seed, sc)
    n = len(df)
    y = df.y.values
    rr = sc.get("rr", S2.ONE)
    roe_m = sc.get("roe", S2.ONE)
    pe_end, pb_end = S1.PE0 * rr, S1.PE0 * rr * S1.ROE0 * roe_m
    dy_end = S1.PAY0 / pe_end
    f = np.exp(np.random.default_rng(seed + 5).normal(0, 0.3, 5))
    V = {}
    V["orig"], roe5 = S1.v_index(df)
    V["cw"] = S2.v_constweight(sec, y)
    V["snap"] = v_snapshot(df, sec["w"], pe_end, pb_end, dy_end)
    V["snap_err"] = v_snapshot(df, sec["w"], pe_end * f, pb_end * f, dy_end / f)
    V["snap_start"] = v_snapshot(df, sec["w"], S1.PE0, S1.PE0 * S1.ROE0, S1.PAY0 / S1.PE0)
    V["oracle"] = S1.pct2(-df.dev.values)
    ind = I.compute(df, val=(V["orig"], roe5))
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    w = slice(START, n)
    common = np.all([~np.isnan(V[m][w]) for m in METHODS], axis=0)
    out = dict(key=key, seed=seed, m={})
    for mk in METHODS:
        v, o = V[mk][w], V["oracle"][w]
        rec = dict(corr=float(np.corrcoef(v[common], o[common])[0, 1]), rmse=float(np.sqrt(np.mean((v[common] - o[common]) ** 2))),
                   bias=float(np.mean(v[common] - o[common])))
        Vm = np.where(np.isnan(V[mk]), V["orig"], V[mk])
        ind["V"] = Vm
        ind["V3"] = Vm
        D = En.Data(df, ind, None, fail)
        for ver in VERS:
            r = En.run(D, ver, cost=True, review=(ver != "1.6"))
            tw = r["twr"][START - 1:]
            rec[ver] = dict(x=En.xirr(r["inflow"], r["final"]), mdd=float(np.max(1 - tw / np.maximum.accumulate(tw))))
        out["m"][mk] = rec
    return out


def main():
    jobs = [(s["key"], 8000 + k) for s in S2.SCEN for k in range(24)]
    t0 = time.time()
    with mp.Pool(4) as pool:
        res = list(pool.imap_unordered(job, jobs, chunksize=1))
    agg = {}
    for sc in S2.SCEN:
        rs = [r for r in res if r["key"] == sc["key"]]
        agg[sc["key"]] = dict(name=sc["name"])
        for mk in METHODS:
            dx = [np.mean([r["m"][mk][u]["x"] - r["m"]["orig"][u]["x"] for u in VERS]) for r in rs]
            dm = [np.mean([r["m"][mk][u]["mdd"] - r["m"]["orig"][u]["mdd"] for u in VERS]) for r in rs]
            dx7 = [r["m"][mk]["1.7"]["x"] - r["m"]["orig"]["1.7"]["x"] for r in rs]
            agg[sc["key"]][mk] = dict(corr=float(np.mean([r["m"][mk]["corr"] for r in rs])), rmse=float(np.mean([r["m"][mk]["rmse"] for r in rs])),
                                      bias=float(np.mean([r["m"][mk]["bias"] for r in rs])), dx=float(np.mean(dx)),
                                      dx_se=float(np.std(dx, ddof=1) / np.sqrt(len(dx))), dmdd=float(np.mean(dm)), dx17=float(np.mean(dx7)))
    json.dump(dict(agg=agg, methods=METHODS), open(os.path.join(HERE, "results", "sector_static.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
