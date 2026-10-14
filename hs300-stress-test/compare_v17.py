"""V1.7：原版 V 与“隐含风险溢价替换股债利差”的新版 V 对比回测（纯模拟数据，逐路径配对）。

  原版 V = 平均分位（盈利收益率、1/PB、股息率、盈利收益率 − 国债）
  新版 V = 平均分位（盈利收益率、1/PB、股息率、隐含风险溢价）
           隐含风险溢价 = 股息率 × (1 + g) + g − 国债，g = clip(0.5 × ROE5 × (1 − 分红率), 0, 8%)，分红率 = 股息率 × PE
  其余规则（止盈 S 信号、回投 B 信号、定投、阈值、底仓、第十节复核、全口径成本）完全相同。

路径集：
  主路径   10 条（与主报告相同的种子）
  蒙特卡洛 300 条（与主报告相同的种子与参数）
  漂移情景 18 个 × 24 条（与中枢漂移专项相同的种子）
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
pct2 = lambda x: (I.pct_score(x, 10) + I.pct_score(x, 5)) / 2


def two_v(df):
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe5 = pd.Series(pb / pe).rolling(5 * YEAR).mean().shift(1).values
    ey = roe5 / pb
    payout = dy * pe
    g = np.clip(0.5 * roe5 * (1 - payout), 0, 0.08)
    p_ey, p_bp, p_dy = pct2(ey), pct2(1 / pb), pct2(dy)
    p_erp, p_ierp = pct2(ey - y), pct2(dy * (1 + g) + g - y)
    return dict(orig=(p_ey + p_bp + p_dy + p_erp) / 4, new=(p_ey + p_bp + p_dy + p_ierp) / 4), roe5


def crises(D, r, events, n):
    out = []
    for e in events:
        if e["type"] not in ("crisis", "bubble") or e["peak"] < START + 60 or e["trough"] >= n - 10:
            continue
        pk, th = e["peak"], e["trough"]
        lowp = D.close[pk:th + 1].min()
        buys = [x for x in r["trades"] if x[1] != "sell" and pk <= x[0] <= th + 126 and x[3] <= 1.15 * lowp]
        pre = r["twr"][pk - 60:pk + 1].max()
        k0 = pk + int(np.argmin(r["twr"][pk:min(n, th + 126)]))
        rep = next((u - k0 for u in range(k0, n) if r["twr"][u] >= pre), None)
        out.append(dict(type=e["type"], escape=bool(r["p"][pk - 1] <= 0.6), p_peak=float(r["p"][pk - 1]),
                        bottom=bool(buys), repair=rep, dd=float(1 - r["twr"][k0] / pre)))
    return out


def job(arg):
    setname, key, seed, spec = arg
    if setname == "drift":
        df, meta, cen = gen2.make_drift_path(seed, spec["dr"], spec["sp"])
    else:
        df, meta = gen.make_valid_path(key, seed, spec or None)
    n = len(df)
    Vs, roe5 = two_v(df)
    ind = I.compute(df, val=(Vs["orig"], roe5))
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    d_true = np.log(df.pe.values) - np.log(df.center.values)
    oracle = pct2(-d_true)
    w = slice(START, n)
    out = dict(set=setname, key=key, seed=seed, v={})
    for vk, V in Vs.items():
        ind["V"] = V
        ind["V3"] = V
        D = En.Data(df, ind, None, fail)
        rec = {}
        for cost in (True, False):
            r = En.run(D, "1.7", cost=cost, review=True, record=cost)
            m = AN.perf(D, r, cost)
            m.pop("cost_kind", None)
            rec["net" if cost else "gross"] = m
            if cost:
                rec["crises"] = crises(D, r, meta["events"], n)
                rec["triggers"] = len(r["triggers"])
                rec["decisions_up"] = sum(1 for x in r["decisions"] if x[1])
        vv = V[w]
        ok = ~np.isnan(vv) & ~np.isnan(oracle[w])
        rec["vstat"] = dict(mean=float(np.nanmean(vv)), hi=float(np.nanmean(vv > 70)), lo=float(np.nanmean(vv < 50)),
                            corr=float(np.corrcoef(vv[ok], oracle[w][ok])[0, 1]),
                            rmse=float(np.sqrt(np.mean((vv[ok] - oracle[w][ok]) ** 2))),
                            bias=float(np.mean(vv[ok] - oracle[w][ok])))
        out["v"][vk] = rec
    return out


def build_jobs():
    jobs = []
    for no, kind, name, ds, seed in gen.PATH_SPECS:
        jobs.append(("main", kind, seed, None))
    rng = np.random.default_rng(20261014)          # 与 analysis.py 完全相同的参数抽样顺序
    for no, kind, name, ds, seed in gen.PATH_SPECS:
        for j in range(AN.MC_SEEDS):
            prm = {}
            if kind in ("slow_up", "slow_down"):
                prm["slow_rate"] = float(rng.uniform(0.03, 0.08))
            if kind in ("jump_up", "jump_down"):
                prm["jump_size"] = float(rng.uniform(0.15, 0.30))
            jobs.append(("mc", kind, 100000 + no * 1000 + j, prm or None))
    for key, name, grp, desc, dr, sp in study.SCEN:
        for k in range(study.N1):
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
    json.dump(AN.to_jsonable(res), open(os.path.join(HERE, "results", "compare_v17_raw.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
