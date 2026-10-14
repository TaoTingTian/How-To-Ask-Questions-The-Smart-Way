"""稳健性：V 中用隐含风险溢价替换股债利差时，对增长假设设错的敏感度。
  v_ddm      g = 0.5 × ROE5 × (1 − 分红率)          （与模拟的真实传导一致）
  v_ddm_k1   g = ROE5 × (1 − 分红率) − 4%           （传导系数设成 1，增长变化被放大一倍）
  v_ddm_k25  g = 0.25 × ROE5 × (1 − 分红率) + 2%    （传导系数设成 0.25，增长变化被低估一半）
  v_ddm_g0   g = 固定 4%                              （完全不估增长：隐含溢价 ≈ 股息率 − 国债 + 常数）
  v_ddm_g10  g = 过去 10 年每股收益的实际年化增速    （纯历史外推，不用 ROE 模型）
"""
import json, os, time, multiprocessing as mp
import numpy as np, pandas as pd
import engine as En, gen, gen2, indicators as I, study, inst
from engine import START, YEAR
HERE = os.path.dirname(os.path.abspath(__file__))
VERS = ["1.6", "1.7", "1.8", "1.9"]
M = ["orig", "v_ddm", "v_ddm_k1", "v_ddm_k25", "v_ddm_g0", "v_ddm_g10", "oracle"]
pct2 = inst.pct2


def job(arg):
    setname, key, seed, spec = arg
    if setname == "A":
        df, meta, cen = gen2.make_drift_path(seed, spec["dr"], spec["sp"])
    else:
        df, meta = gen.make_valid_path(key, seed, spec or None)
    n = len(df)
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe5 = pd.Series(pb / pe).rolling(5 * YEAR).mean().shift(1).values
    ey = roe5 / pb
    payout = dy * pe
    P = {k: pct2(v) for k, v in dict(ey=ey, bp=1 / pb, dy=dy).items()}
    base3 = P["ey"] + P["bp"] + P["dy"]
    eps = df.close.values / pe
    g10 = np.r_[np.full(10 * YEAR, np.nan), (eps[10 * YEAR:] / eps[:-10 * YEAR]) ** 0.1 - 1]
    gs = dict(v_ddm=0.5 * roe5 * (1 - payout), v_ddm_k1=roe5 * (1 - payout) - 0.04,
              v_ddm_k25=0.25 * roe5 * (1 - payout) + 0.02, v_ddm_g0=np.full(n, 0.04),
              v_ddm_g10=np.where(np.isnan(g10), 0.04, g10))
    V = {"orig": (base3 + pct2(ey - y)) / 4}
    for k, g in gs.items():
        V[k] = (base3 + pct2(dy * (1 + g) + g - y)) / 4
    d_true = np.log(pe) - np.log(df.center.values)
    V["oracle"] = pct2(-d_true)
    ind = I.compute(df, val=(V["orig"], roe5))
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    w = slice(START, n)
    common = np.all([~np.isnan(V[m][w]) for m in M], axis=0)
    out = dict(set=setname, key=key, m={})
    for mk in M:
        v = V[mk][w]
        rec = dict(corr=float(np.corrcoef(v[common], V["oracle"][w][common])[0, 1]),
                   rmse=float(np.sqrt(np.mean((v[common] - V["oracle"][w][common]) ** 2))))
        Vm = np.where(np.isnan(V[mk]), V["orig"], V[mk])
        ind["V"] = Vm; ind["V3"] = Vm
        D = En.Data(df, ind, None, fail)
        for ver in VERS:
            r = En.run(D, ver, cost=True, review=(ver != "1.6"))
            tw = r["twr"][START - 1:]
            rec[ver] = dict(x=En.xirr(r["inflow"], r["final"]), mdd=float(np.max(1 - tw / np.maximum.accumulate(tw))))
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
    with mp.Pool(4) as pool:
        res = list(pool.imap_unordered(job, jobs, chunksize=2))
    agg = {}
    groups = {"全部": res, "A·漂移情景": [r for r in res if r["set"] == "A"], "B·压力市场": [r for r in res if r["set"] == "B"]}
    for kind in ["slow_up", "jump_up", "cycle", "bubble", "fake_reversion", "slow_down"]:
        groups["B·" + kind] = [r for r in res if r["key"] == kind]
    for g, rs in groups.items():
        agg[g] = {}
        for mk in M:
            dx = [np.mean([r["m"][mk][u]["x"] - r["m"]["orig"][u]["x"] for u in VERS]) for r in rs]
            dm = [np.mean([r["m"][mk][u]["mdd"] - r["m"]["orig"][u]["mdd"] for u in VERS]) for r in rs]
            agg[g][mk] = dict(corr=float(np.mean([r["m"][mk]["corr"] for r in rs])), rmse=float(np.mean([r["m"][mk]["rmse"] for r in rs])),
                              dx=float(np.mean(dx)), dx_se=float(np.std(dx, ddof=1) / np.sqrt(len(dx))), dmdd=float(np.mean(dm)),
                              win=float(np.mean([d > 0 for d in dx])))
    json.dump(dict(agg=agg, methods=M), open(os.path.join(HERE, "results", "inst_robust.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
