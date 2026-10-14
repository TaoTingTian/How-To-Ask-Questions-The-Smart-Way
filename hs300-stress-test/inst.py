"""国际主流机构处理“估值中枢漂移”的方法，在模拟数据上的移植检验。

  orig      原版 V（4 项分位，5/10 年）
  ecy       Shiller 等（2020）超额 CAPE 收益率思路：只用 盈利收益率 − 国债 的分位
  fvpe      Vanguard 公允价值 CAPE 思路：过去 10 年 log PE 对国债收益率回归（模拟中无通胀项），残差取分位
  ddm       Damodaran 隐含风险溢价：r = 股息率 × (1 + g) + g，g = 0.5 × ROE5 × (1 − 分红率)，ERP = r − 国债，取分位
  ddm_k1    同上但增长假设偏误：g = ROE5 × (1 − 分红率) − 4%（检验对增长假设的敏感性）
  v_ddm     原版 4 项中，用隐含风险溢价替换股债利差
  lvn       Lettau & Van Nieuwerburgh（2008）稳态均值调整的实时近似：过去 10 年内检测 log PE 均值的单次断点
            （两段均值差 ≥ 0.25、每段 ≥ 3 年），偏离 = log PE − 当前区制均值，再取分位
  ra_half   Research Affiliates / GMO 的“部分回归”思路：只预期回归一半 → V 向 50 收缩一半
  oracle    理想 V（真实偏离分位），仅作上限
测试集与 vtrack.py 相同（336 条：18 个漂移情景 × 12 + 10 类压力市场 × 12）。
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
import vtrack
from engine import START, YEAR

HERE = os.path.dirname(os.path.abspath(__file__))
VERS = ["1.6", "1.7", "1.8", "1.9"]
METHODS = ["orig", "ecy", "fvpe", "ddm", "ddm_k1", "v_ddm", "lvn", "ra_half", "oracle"]
pct2 = vtrack.pct2


def reg_resid(yv, X, W=10 * YEAR, minp=3 * YEAR, step=21):
    res = np.full(len(yv), np.nan)
    beta = None
    for t in range(len(yv)):
        if np.isnan(X[t]).any():
            continue
        if beta is None or t % step == 0:
            lo = max(0, t - W)
            Xi, yi = X[lo:t], yv[lo:t]
            m = ~np.isnan(Xi).any(1)
            if m.sum() >= minp:
                beta = np.linalg.lstsq(Xi[m], yi[m], rcond=None)[0]
        if beta is not None:
            res[t] = yv[t] - X[t] @ beta
    return res


def regime_dev(lx, W=10 * YEAR, seg=3 * YEAR, thr=0.25, step=21):
    """实时单断点检测：每 21 天在过去 10 年里找使两段均值差最大的断点；差 ≥ thr 时以断点后的均值为区制均值，否则用整窗均值。"""
    n = len(lx)
    dev = np.full(n, np.nan)
    mu = np.nan
    for t in range(seg * 2, n):
        if t % step == 0 or np.isnan(mu):
            lo = max(0, t - W)
            x = lx[lo:t]
            x = x[~np.isnan(x)]
            if len(x) < 2 * seg + 21:
                mu = np.mean(x) if len(x) >= seg else np.nan
            else:
                cs = np.cumsum(x)
                ks = np.arange(seg, len(x) - seg, 21)
                m1 = cs[ks - 1] / ks
                m2 = (cs[-1] - cs[ks - 1]) / (len(x) - ks)
                j = int(np.argmax(np.abs(m2 - m1)))
                mu = m2[j] if abs(m2[j] - m1[j]) >= thr else np.mean(x)
        if not np.isnan(mu):
            dev[t] = lx[t] - mu
    return dev


def methods(df, d_true):
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe5 = pd.Series(pb / pe).rolling(5 * YEAR).mean().shift(1).values
    ey = roe5 / pb
    payout = dy * pe
    inds = dict(ey=ey, bp=1 / pb, dy=dy, erp=ey - y)
    P = {k: pct2(v) for k, v in inds.items()}
    V = {}
    V["orig"] = (P["ey"] + P["bp"] + P["dy"] + P["erp"]) / 4
    V["ecy"] = P["erp"]
    X = np.column_stack([np.ones(len(df)), y])
    V["fvpe"] = pct2(-reg_resid(np.log(pe), X))
    g = 0.5 * roe5 * (1 - payout)
    erp_ddm = dy * (1 + g) + g - y
    V["ddm"] = pct2(erp_ddm)
    g1 = roe5 * (1 - payout) - 0.04
    V["ddm_k1"] = pct2(dy * (1 + g1) + g1 - y)
    V["v_ddm"] = (P["ey"] + P["bp"] + P["dy"] + pct2(erp_ddm)) / 4
    V["lvn"] = pct2(-regime_dev(np.log(pe)))
    V["ra_half"] = 50 + 0.5 * (V["orig"] - 50)
    V["oracle"] = pct2(-d_true)
    return V, roe5


def job(arg):
    setname, key, seed, spec = arg
    if setname == "A":
        df, meta, cen = gen2.make_drift_path(seed, spec["dr"], spec["sp"])
    else:
        df, meta = gen.make_valid_path(key, seed, spec or None)
    n = len(df)
    d_true = np.log(df.pe.values) - np.log(df.center.values)
    V, roe5 = methods(df, d_true)
    ind = I.compute(df, val=(V["orig"], roe5))
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    w = slice(START, n)
    o = V["oracle"][w]
    common = np.all([~np.isnan(V[mk][w]) for mk in METHODS], axis=0)
    out = dict(set=setname, key=key, seed=seed, m={})
    for mk in METHODS:
        v = V[mk][w]
        ok = common
        rec = dict(corr=float(np.corrcoef(v[ok], o[ok])[0, 1]), rmse=float(np.sqrt(np.mean((v[ok] - o[ok]) ** 2))),
                   bias=float(np.mean(v[ok] - o[ok])), cover=float(np.mean(~np.isnan(v))))
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
            m = {k: float(np.mean([r["m"][mk][k] for r in rs])) for k in ("corr", "rmse", "bias", "cover")}
            for ver in VERS + ["avg"]:
                vv = VERS if ver == "avg" else [ver]
                dx = [np.mean([r["m"][mk][u]["x"] - r["m"]["orig"][u]["x"] for u in vv]) for r in rs]
                dm = [np.mean([r["m"][mk][u]["mdd"] - r["m"]["orig"][u]["mdd"] for u in vv]) for r in rs]
                m[ver] = dict(dx=float(np.mean(dx)), dx_se=se(dx), dmdd=float(np.mean(dm)))
            agg[g][mk] = m
    json.dump(dict(agg=agg, methods=METHODS, n=len(res)), open(os.path.join(HERE, "results", "inst.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
