"""针对中枢漂移的结构性优化检验。

候选结构（engine.run 的 opt 开关）：
  cash_yield  资金池放货币基金（年化 = 国债 − 1pp，最低 1%），降低资金池闲置的机会成本
  timeout     超时分批回补：资金池闲置满 2 年、且不在止盈区（V < 70）时，每月回补剩余资金的 1/12
  dyn_floor   动态底仓：长周期上移预警（ROE、国债、观测中枢速率三取二）成立时底仓 20% → 40%
  gap         分项偏差调线：盈利收益率分位比其余三项分位均值高 5 点以上时，回投线下调 gap/2（最多 5 点）
  adapt_win   自适应窗口：V 的一年均值 > 65 时，改用 3 年窗口计算的 V
  package     预先指定的组合：cash_yield + timeout + dyn_floor
  all         全部五项

测试集（与此前所有路径不同的新种子）：
  A  中枢漂移专项的 18 个情景 × 12 条（种子 6000 起，配对）
  B  压力测试的 10 类市场 × 12 条（种子 700000 起，漂移速度 / 跳变幅度随机）
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
OPTS = {"base": (), "cash_yield": ("cash_yield",), "timeout": ("timeout",), "dyn_floor": ("dyn_floor",),
        "gap": ("gap",), "adapt_win": ("adapt_win",), "package": ("cash_yield", "timeout", "dyn_floor"),
        "all": ("cash_yield", "timeout", "dyn_floor", "gap", "adapt_win")}
NA, NB = 12, 12


def job(arg):
    setname, key, seed, spec = arg
    if setname == "A":
        df, meta, cen = gen2.make_drift_path(seed, spec["dr"], spec["sp"])
    else:
        df, meta = gen.make_valid_path(key, seed, spec or None)
    n = len(df)
    ind = I.compute(df)
    mc = I.multi_cycle(df, ind)
    pct, Vs, _ = study.comp_pcts(df)
    gap = pct["ey"] - (pct["bp"] + pct["dy"] + pct["erp"]) / 3
    ind["gap"] = pd.Series(gap).rolling(YEAR, min_periods=60).mean().values
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    D = En.Data(df, ind, mc, fail)
    out = dict(set=setname, key=key, seed=seed, runs={})
    for v in VERS:
        for ok, o in OPTS.items():
            r = En.run(D, v, cost=True, review=(v != "1.6"), opt=o)
            bh = En.bench(D, r["inflow"], True, "bh")
            tw = r["twr"][START - 1:]
            out["runs"][f"{v}|{ok}"] = dict(x=En.xirr(r["inflow"], r["final"]), bh=En.xirr(bh["inflow"], bh["final"]),
                                            mdd=float(np.max(1 - tw / np.maximum.accumulate(tw))),
                                            idle=float(np.mean(r["cash"][START:] / np.maximum(r["total"][START:], 1) > 0.05)))
    return out


def main():
    jobs = []
    for key, name, grp, desc, dr, sp in study.SCEN:
        for k in range(NA):
            jobs.append(("A", key, 6000 + k, dict(dr=dr, sp=sp)))
    rng = np.random.default_rng(777)
    for no, kind, name, ds, seed in gen.PATH_SPECS:
        for k in range(NB):
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

    def se(a):
        a = np.asarray(a, float)
        return float(a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 1 else 0.0

    groups = {}
    for r in res:
        if r["set"] == "A":
            a = gen2.analytic(dict(study.SCEN[[s[0] for s in study.SCEN].index(r["key"])][4]))["pe"]
            g = "A·基准" if r["key"] == "S0" else ("A·PE中枢上移" if a > 0.05 else ("A·PE中枢下移" if a < -0.05 else "A·成分漂移"))
        else:
            g = "B·" + r["key"]
        for gg in (g, r["set"] + "·全部", "全部"):
            groups.setdefault(gg, []).append(r)
    agg = {}
    for g, rs in groups.items():
        agg[g] = {"n": len(rs)}
        for v in VERS + ["avg"]:
            for ok in OPTS:
                vv = VERS if v == "avg" else [v]
                dx = [np.mean([r["runs"][f"{u}|{ok}"]["x"] - r["runs"][f"{u}|base"]["x"] for u in vv]) for r in rs]
                dm = [np.mean([r["runs"][f"{u}|{ok}"]["mdd"] - r["runs"][f"{u}|base"]["mdd"] for u in vv]) for r in rs]
                ex = [np.mean([r["runs"][f"{u}|{ok}"]["x"] - r["runs"][f"{u}|{ok}"]["bh"] for u in vv]) for r in rs]
                win = [np.mean([r["runs"][f"{u}|{ok}"]["x"] > r["runs"][f"{u}|base"]["x"] for u in vv]) for r in rs]
                agg[g][f"{v}|{ok}"] = dict(dx=float(np.mean(dx)), dx_se=se(dx), dmdd=float(np.mean(dm)), dmdd_se=se(dm),
                                           ex=float(np.mean(ex)), win=float(np.mean(win)))
    json.dump(dict(agg=agg, opts=list(OPTS), n=len(res)), open(os.path.join(HERE, "results", "optim.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
