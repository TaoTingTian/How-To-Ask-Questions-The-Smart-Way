"""V2.0 回测：与 V1.6–V1.10 对比（路径集、陷阱 / 危机 / 假回落统计与 v110.py 相同）。

  2.0   按文档：V = 平均分位（EY、BP、DY、IRP），IRP = DY + g − y，g = ROE_n × (1 − clip(DY×PE, 0, 1))
  2.0s  去掉果断卖出（只有平缓曲线，文档附录 E 的对照）
  2.0e  V2.0 的买卖规则 + 原版股债利差 V（拆出“规则”与“估值分”各自的作用）
"""
import json, os, time, multiprocessing as mp
import numpy as np, pandas as pd
import analysis as AN, engine as En, gen, gen2, indicators as I, v110
from engine import START, YEAR

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANTS = ["1.6", "1.7", "1.8", "1.9", "1.10", "2.0", "2.0s", "2.0e"]


def v_v2(df):
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe5 = pd.Series(pb / pe).rolling(5 * YEAR).mean().shift(1).values
    g = roe5 * (1 - np.clip(dy * pe, 0, 1))
    pct2 = lambda x: (I.pct_score(x, 10) + I.pct_score(x, 5)) / 2
    return (pct2(roe5 / pb) + pct2(1 / pb) + pct2(dy) + pct2(dy + g - y)) / 4


def job(arg):
    setname, key, seed, spec = arg
    if setname == "drift":
        df, meta, _ = gen2.make_drift_path(seed, spec["dr"], spec["sp"])
    else:
        df, meta = gen.make_valid_path(key, seed, spec or None)
    n = len(df)
    ind = I.compute(df)
    W = v110.weekly(df)
    S_new = v110.s_hysteresis(W, n)
    V110, V20 = v110.v_irp(df), v_v2(df)
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    traps = [tp for tp in meta.get("traps", gen.detect_traps(df.dev.values)) if tp[2] >= START + 20]
    base_V, base_S = ind["V"].copy(), ind["S"].copy()
    out = dict(set=setname, key=key, seed=seed, v={})
    for var in VARIANTS:
        ind["V"] = {"1.10": V110, "2.0": V20, "2.0s": V20}.get(var, base_V)
        ind["V3"] = ind["V"]
        ind["S"] = S_new if var == "1.10" else base_S
        D = En.Data(df, ind, None, fail)
        if var.startswith("2.0"):
            r = En.run_v2(D, cost=True, review=True, decisive=(var != "2.0s"), record=True)
        else:
            r = En.run(D, "1.7" if var == "1.10" else var, cost=True, review=(var != "1.6"), record=True)
        m = AN.perf(D, r, True)
        m.pop("cost_kind", None)
        m["n_decisive"] = r.get("n_decisive", 0)
        m["traps"] = v110.trap_stats(D, r, traps, n)
        m["crises"] = v110.crisis_stats(D, r, meta["events"], n)
        m["fdrop"] = v110.false_drop(r, W, n)
        m["p_mean"] = float(r["p"][START:].mean())
        out["v"][var] = m
    return out


def main():
    jobs = v110.build_jobs()
    t0 = time.time()
    with mp.Pool(4) as pool:
        res = []
        for k, r in enumerate(pool.imap_unordered(job, jobs, chunksize=2)):
            res.append(r)
            if k % 100 == 0:
                print(f"{k + 1}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    json.dump(AN.to_jsonable(res), open(os.path.join(HERE, "results", "v20_raw.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
