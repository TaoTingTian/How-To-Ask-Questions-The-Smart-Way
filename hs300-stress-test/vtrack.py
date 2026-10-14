"""让估值分 V 识别并跟随中枢漂移：候选方法对比（纯模拟数据）。

衡量标准：模拟里真实中枢已知，构造“理想 V”= 真实偏离（log PE − log 真实中枢）在 5/10 年窗口里的分位数，
它就是“完全知道中枢在哪”时的估值分。各方法与理想 V 比较：相关系数、均方根误差、平均偏差；
再把各方法的 V 代入四版策略，比较净收益与最大回撤。

方法：
  orig    原版：4 项指标，5 年 / 10 年分位平均
  win3    短窗口：4 项指标，3 年分位
  ewma    EWMA 去中枢：各指标（对数）减去半衰期 3 年的指数均值，再取 5/10 年分位
  trend   趋势去中枢：各指标（对数）减去过去 10 年线性趋势外推值，再取 5/10 年分位
  fund    基本面回归中枢：过去 10 年 log PE 对 [国债, log ROE5, log 分红率] 回归（每月重估），残差取 5/10 年分位
  blend   orig 与 fund 的平均
  mix     orig 与 ewma 的平均
  ewma_gate  门控：长周期基本面（ROE5、国债、观测中枢速率三取二）确认上移或下移时用 ewma，否则用 orig
  oracle  理想 V（只作上限参照）
测试集：中枢漂移 18 情景 × 12 条（种子 6000 起）+ 压力测试 10 类 × 12 条（种子 700000 起），与 optim.py 相同。
"""
import json
import multiprocessing as mp
import os
import time

import numpy as np
import pandas as pd

import engine as En
import gen
import gen2
import indicators as I
import study
from engine import START, YEAR

HERE = os.path.dirname(os.path.abspath(__file__))
VERS = ["1.6", "1.7", "1.8", "1.9"]
METHODS = ["orig", "win3", "ewma", "trend", "fund", "blend", "mix", "ewma_gate", "oracle"]


def pct2(x, wins=(10, 5)):
    """x 为“越大越便宜”的序列；返回 0–100 的估值分（越大越贵）。"""
    return np.mean([I.pct_score(x, w) for w in wins], axis=0)


def rolling_trend_pred(lx, W=10 * YEAR, minp=3 * YEAR):
    """用 [t−W, t−1] 的线性趋势外推到 t。"""
    n = len(lx)
    s = np.arange(n, dtype=float)
    ok = ~np.isnan(lx)
    y = np.where(ok, lx, 0.0)
    c = ok.astype(float)

    def rs(a):
        return pd.Series(a).rolling(W, min_periods=1).sum().shift(1).values
    N, Sx, Sy, Sxy, Sxx = rs(c), rs(s * c), rs(y), rs(s * y), rs(s * s * c)
    den = N * Sxx - Sx ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        b = (N * Sxy - Sx * Sy) / den
        a = (Sy - b * Sx) / N
    pred = a + b * s
    pred[N < minp] = np.nan
    return pred


def fund_resid(df, roe5, W=10 * YEAR, minp=3 * YEAR, step=21):
    lpe = np.log(df.pe.values)
    payout = df.dy.values * df.pe.values
    X = np.column_stack([np.ones(len(df)), df.y.values, np.log(roe5), np.log(payout)])
    res = np.full(len(df), np.nan)
    beta = None
    for t in range(len(df)):
        if np.isnan(X[t]).any():
            continue
        if beta is None or t % step == 0:
            lo = max(0, t - W)
            Xi, yi = X[lo:t], lpe[lo:t]
            m = ~np.isnan(Xi).any(1)
            if m.sum() >= minp:
                beta = np.linalg.lstsq(Xi[m], yi[m], rcond=None)[0]
        if beta is not None:
            res[t] = lpe[t] - X[t] @ beta
    return res


def all_methods(df, d_true):
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe5 = pd.Series(pb / pe).rolling(5 * YEAR).mean().shift(1).values
    ey = roe5 / pb
    inds = dict(ey=ey, bp=1 / pb, dy=dy, erp=ey - y)
    V = {}
    V["orig"] = np.mean([pct2(x) for x in inds.values()], axis=0)
    V["win3"] = np.mean([pct2(x, (3,)) for x in inds.values()], axis=0)
    ew, tr = [], []
    for k, x in inds.items():
        lx = x if k == "erp" else np.log(x)
        e = pd.Series(lx).ewm(halflife=3 * YEAR, min_periods=3 * YEAR).mean().shift(1).values
        ew.append(pct2(lx - e))
        tr.append(pct2(lx - rolling_trend_pred(lx)))
    V["ewma"] = np.mean(ew, axis=0)
    V["trend"] = np.mean(tr, axis=0)
    V["fund"] = pct2(-fund_resid(df, roe5))
    V["blend"] = (V["orig"] + V["fund"]) / 2
    V["mix"] = (V["orig"] + V["ewma"]) / 2
    V["oracle"] = pct2(-d_true)
    for k in V:                       # 预热期内无法计算的统一置空，保证各方法起点一致
        V[k][:START - 1] = np.where(np.isnan(V[k][:START - 1]), np.nan, V[k][:START - 1])
    return V, roe5


def job(arg):
    setname, key, seed, spec = arg
    if setname == "A":
        df, meta, cen = gen2.make_drift_path(seed, spec["dr"], spec["sp"])
    else:
        df, meta = gen.make_valid_path(key, seed, spec or None)
    n = len(df)
    d_true = np.log(df.pe.values) - np.log(df.center.values)
    V, roe5 = all_methods(df, d_true)
    ind = I.compute(df, val=(V["orig"], roe5))
    mc = I.multi_cycle(df, ind)
    gate = pd.Series((mc["up_long"] | mc["down_long"]).astype(float)).rolling(60, min_periods=1).max().values > 0
    V["ewma_gate"] = np.where(gate & ~np.isnan(V["ewma"]), V["ewma"], V["orig"])
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    w = slice(START, n)
    o = V["oracle"][w]
    common = np.all([~np.isnan(V[mk][w]) for mk in METHODS], axis=0)   # 所有方法都可算的共同区间
    out = dict(set=setname, key=key, seed=seed, m={})
    for mk in METHODS:
        v = V[mk][w].copy()
        ok = common
        rec = dict(corr=float(np.corrcoef(v[ok], o[ok])[0, 1]), rmse=float(np.sqrt(np.mean((v[ok] - o[ok]) ** 2))),
                   bias=float(np.mean(v[ok] - o[ok])), cover=float(ok.mean()),
                   hi=float(np.mean(v[ok] > 70)), lo=float(np.mean(v[ok] < 50)), cover_own=float(np.mean(~np.isnan(v))))
        Vm = np.where(np.isnan(V[mk]), V["orig"], V[mk])      # 个别方法起算稍晚时用原版补齐
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
    jobs = []
    for key, name, grp, desc, dr, sp in study.SCEN:
        for k in range(12):
            jobs.append(("A", key, 6000 + k, dict(dr=dr, sp=sp)))
    rng = np.random.default_rng(777)
    for no, kind, name, ds, seed in gen.PATH_SPECS:
        for k in range(12):
            prm = {}
            if kind in ("slow_up", "slow_down"):
                prm["slow_rate"] = float(rng.uniform(0.03, 0.08))
            if kind in ("jump_up", "jump_down"):
                prm["jump_size"] = float(rng.uniform(0.15, 0.30))
            jobs.append(("B", kind, 700000 + no * 1000 + k, prm))
    t0 = time.time()
    res = []
    with mp.Pool(4) as pool:
        for k, r in enumerate(pool.imap_unordered(job, jobs, chunksize=2)):
            res.append(r)
            if k % 60 == 0:
                print(f"{k + 1}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)

    def grp(r):
        if r["set"] == "A":
            a = gen2.analytic(dict(study.SCEN[[s[0] for s in study.SCEN].index(r["key"])][4]))["pe"]
            return "A·基准" if r["key"] == "S0" else ("A·PE中枢上移" if a > 0.05 else ("A·PE中枢下移" if a < -0.05 else "A·成分漂移"))
        return "B·" + r["key"]

    def se(a):
        a = np.asarray(a, float)
        return float(a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 1 else 0.0

    groups = {}
    for r in res:
        for g in (grp(r), r["set"] + "·全部", "全部"):
            groups.setdefault(g, []).append(r)
    agg = {}
    for g, rs in groups.items():
        agg[g] = {"n": len(rs)}
        for mk in METHODS:
            m = dict(corr=float(np.mean([r["m"][mk]["corr"] for r in rs])), rmse=float(np.mean([r["m"][mk]["rmse"] for r in rs])),
                     bias=float(np.mean([r["m"][mk]["bias"] for r in rs])), hi=float(np.mean([r["m"][mk]["hi"] for r in rs])))
            for ver in VERS + ["avg"]:
                vv = VERS if ver == "avg" else [ver]
                dx = [np.mean([r["m"][mk][u]["x"] - r["m"]["orig"][u]["x"] for u in vv]) for r in rs]
                dm = [np.mean([r["m"][mk][u]["mdd"] - r["m"]["orig"][u]["mdd"] for u in vv]) for r in rs]
                ex = [np.mean([r["m"][mk][u]["x"] - r["m"][mk][u]["bh"] for u in vv]) for r in rs]
                m[ver] = dict(dx=float(np.mean(dx)), dx_se=se(dx), dmdd=float(np.mean(dm)), ex=float(np.mean(ex)))
            agg[g][mk] = m
    json.dump(dict(agg=agg, methods=METHODS, n=len(res)), open(os.path.join(HERE, "results", "vtrack.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
