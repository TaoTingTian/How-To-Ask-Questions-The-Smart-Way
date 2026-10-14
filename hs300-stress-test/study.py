"""中枢漂移专项研究：各指标中枢各走各的。

第一层  18 个具名经济情景 × 24 个随机种子（与基准情景配对，噪声、危机、假回归完全相同，只有中枢不同）
第二层  4 因子 × 3 水平全组合（PE 中枢 / ROE / 分红率 / 国债），风险溢价作为差额吸收项；
        风险溢价变化超过 ±3 个百分点的组合视为经济上不自洽，剔除。每个组合 8 个种子。
输出 results/drift_study.json。
"""
import itertools
import json
import multiprocessing as mp
import os
import time

import numpy as np
import pandas as pd

import engine as En
import gen2
import indicators as I
from engine import START, YEAR

HERE = os.path.dirname(os.path.abspath(__file__))
VERS = ["1.6", "1.7", "1.8", "1.9"]
N1, N2 = 24, 8
SEED0 = 5000

SCEN = [
    # key, 名称, 分组, 说明, 驱动终值, 速度
    ("S0", "基准：各中枢不动", "基准", "四个驱动都不变", {}, {}),
    ("S1", "利率缓慢下行", "单因素", "10 年国债 12 年内 −1.5pp", dict(y=-0.015), {}),
    ("S2", "利率缓慢上行", "单因素", "10 年国债 12 年内 +1.5pp", dict(y=0.015), {}),
    ("S3", "风险溢价缓慢上升", "单因素", "要求的风险溢价 +1.5pp（风险偏好下降）", dict(rp=0.015), {}),
    ("S4", "风险溢价缓慢下降", "单因素", "要求的风险溢价 −1.5pp（风险偏好修复）", dict(rp=-0.015), {}),
    ("S5", "ROE 下台阶", "单因素", "ROE 12% → 8.5%", dict(roe=-0.035), {}),
    ("S6", "ROE 上台阶", "单因素", "ROE 12% → 15.5%", dict(roe=0.035), {}),
    ("S7", "分红率提升", "单因素", "分红率 33% → 50%", dict(p=0.17), {}),
    ("C1", "降息被盈利下滑对冲（沪深300 2015–2026 型）", "组合", "国债 −1.2pp、ROE 12%→8.5%、分红率 33%→39%", dict(y=-0.012, roe=-0.035, p=0.06), {}),
    ("C2", "降息牛（流动性推动）", "组合", "国债 −1.5pp、风险溢价 −0.5pp", dict(y=-0.015, rp=-0.005), {}),
    ("C3", "滞胀加息熊", "组合", "国债 +1.5pp、风险溢价 +1pp、ROE −1.5pp", dict(y=0.015, rp=0.01, roe=-0.015), {}),
    ("C4", "日本化（低利率、低增长、高风险溢价）", "组合", "国债 −2pp、风险溢价 +2pp、ROE 12%→7%、分红率→45%", dict(y=-0.02, rp=0.02, roe=-0.05, p=0.12), {}),
    ("C5", "结构升级（高 ROE + 高分红）", "组合", "ROE 12%→16%、分红率→45%、国债 −1pp", dict(roe=0.04, p=0.12, y=-0.01), {}),
    ("C6", "风险偏好修复 + 盈利改善", "组合", "风险溢价 −1pp、ROE +2pp", dict(rp=-0.01, roe=0.02), {}),
    ("F1", "利率急降", "快速", "国债 2 个月内 −1.5pp", dict(y=-0.015), dict(y="fast")),
    ("F2", "风险溢价急升（冲击事件）", "快速", "风险溢价 2 个月内 +1.5pp", dict(rp=0.015), dict(rp="fast")),
    ("F3", "政策急转（降息 + 风险偏好修复）", "快速", "国债 −1pp、风险溢价 −1pp，2 个月内完成", dict(y=-0.01, rp=-0.01), dict(y="fast", rp="fast")),
    ("F4", "降息先行、盈利后滑", "快速", "国债 2 个月内 −1.2pp；ROE、分红率同 C1 缓慢变化", dict(y=-0.012, roe=-0.035, p=0.06), dict(y="fast")),
]

LEVELS = dict(pe=[-0.18, 0.0, 0.18], roe=[-0.03, 0.0, 0.03], p=[-0.08, 0.0, 0.12], y=[-0.015, 0.0, 0.015])


def comp_pcts(df):
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe5 = pd.Series(pb / pe).rolling(5 * YEAR).mean().shift(1).values
    ey = roe5 / pb
    inds = dict(ey=ey, bp=1 / pb, dy=dy, erp=ey - y)
    pct = {k: (I.pct_score(v, 10) + I.pct_score(v, 5)) / 2 for k, v in inds.items()}
    V = (pct["ey"] + pct["bp"] + pct["dy"] + pct["erp"]) / 4
    Vn = (pct["ey"] + pct["dy"] + pct["erp"]) / 3
    return pct, dict(orig=V, nopb=Vn, ey=pct["ey"]), roe5


def job(arg):
    layer, key, seed, dr, speeds, full = arg
    df, meta, cen = gen2.make_drift_path(seed, dr, speeds)
    n = len(df)
    pct, Vs, roe5 = comp_pcts(df)
    ind = I.compute(df, val=(Vs["orig"], roe5))
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    d = df.dev.values
    w = slice(START, n)
    post = slice(21 * YEAR, n)
    out = dict(layer=layer, key=key, seed=seed,
               pct={k: float(np.nanmean(v[w])) for k, v in pct.items()},
               pct_post={k: float(np.nanmean(v[post])) for k, v in pct.items()},
               V={k: float(np.nanmean(v[w])) for k, v in Vs.items()},
               V_post={k: float(np.nanmean(v[post])) for k, v in Vs.items()},
               corr={k: float(pd.Series(v[w]).corr(pd.Series(d[w]))) for k, v in Vs.items()},
               runs={})
    variants = ["orig", "nopb", "ey"] if full else ["orig"]
    for vk in variants:
        ind["V"] = Vs[vk]
        D = En.Data(df, ind, None, fail)
        for v in VERS:
            combos = [("rev", "old")] if v == "1.6" else [("rev", "old")]
            if full and vk == "orig" and v != "1.6":
                combos += [("rev", "new"), ("norev", "old")]
            for rv, rule in combos:
                r = En.run(D, v, cost=True, review=(rv == "rev" and v != "1.6"), review_rule=rule)
                bh = En.bench(D, r["inflow"], True, "bh")
                tw = r["twr"][START - 1:]
                dec = [(bool(x[1]), bool(cen["dlpe"][x[0]] - cen["dlpe"][x[3]] >= 0.08)) for x in r["decisions"] if x[3] is not None]
                out["runs"][f"{vk}|{v}|{rv}|{rule}"] = dict(
                    xirr=En.xirr(r["inflow"], r["final"]), bh=En.xirr(bh["inflow"], bh["final"]),
                    mdd=float(np.max(1 - tw / np.maximum.accumulate(tw))),
                    idle=float(np.mean(r["cash"][START:] / np.maximum(r["total"][START:], 1) > 0.05)),
                    n_sell=r["n_sell"], n_rebuy=r["n_rebuy"], dec=dec)
    if full and seed == SEED0:
        step = 20
        idx = np.arange(0, n, step)
        sm = lambda a: pd.Series(a).rolling(120, min_periods=1).mean().values[idx]
        out["series"] = dict(
            date=[str(x)[:4] for x in df.date.values[idx]],
            pe_c=np.round(cen["pe"][idx], 3).tolist(), pb_c=np.round(cen["pb"][idx], 4).tolist(),
            dy_c=np.round(cen["dy"][idx] * 100, 3).tolist(), y_c=np.round(cen["y"][idx] * 100, 3).tolist(),
            erp_c=np.round(cen["erp"][idx] * 100, 3).tolist(),
            pe=np.round(df.pe.values[idx], 2).tolist(),
            **{"V_" + k: [None if np.isnan(x) else round(float(x), 1) for x in sm(v)] for k, v in Vs.items()},
        )
    return out


def build_jobs():
    jobs = []
    for key, *_rest in SCEN:
        dr, sp = _rest[3], _rest[4]
        for k in range(N1):
            jobs.append(("L1", key, SEED0 + k, dr, sp, True))
    combos = []
    for lv in itertools.product(*[LEVELS[f] for f in ("pe", "roe", "p", "y")]):
        dr = dict(roe=lv[1], p=lv[2], y=lv[3])
        rp = gen2.solve_rp(dr, lv[0])
        dr["rp"] = rp
        kept = abs(rp) <= 0.03 + 1e-12
        ck = "|".join(f"{x:g}" for x in lv)
        combos.append(dict(key=ck, pe=lv[0], roe=lv[1], p=lv[2], y=lv[3], rp=rp, kept=kept))
        if kept:
            for k in range(N2):
                jobs.append(("L2", ck, SEED0 + k, dr, {}, False))
    return jobs, combos


def se(x):
    x = np.asarray(x, float)
    return float(x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else 0.0


def aggregate(res, combos):
    L1 = [r for r in res if r["layer"] == "L1"]
    by = {}
    for r in L1:
        by.setdefault(r["key"], {})[r["seed"]] = r
    base = by["S0"]
    out = dict(scen=[], combos=combos)
    for key, name, grp, desc, dr, sp in SCEN:
        rs = by[key]
        seeds = sorted(rs)
        rec = dict(key=key, name=name, group=grp, desc=desc, drivers=dr, speeds=sp, analytic=gen2.analytic(dr), n=len(seeds))
        rec["dV"] = {vk: float(np.mean([rs[s]["V"][vk] - base[s]["V"][vk] for s in seeds])) for vk in ("orig", "nopb", "ey")}
        rec["dV_post"] = {vk: float(np.mean([rs[s]["V_post"][vk] - base[s]["V_post"][vk] for s in seeds])) for vk in ("orig", "nopb", "ey")}
        rec["dpct"] = {c: float(np.mean([rs[s]["pct"][c] - base[s]["pct"][c] for s in seeds])) for c in ("ey", "bp", "dy", "erp")}
        rec["dpct_post"] = {c: float(np.mean([rs[s]["pct_post"][c] - base[s]["pct_post"][c] for s in seeds])) for c in ("ey", "bp", "dy", "erp")}
        rec["corr"] = {vk: float(np.mean([rs[s]["corr"][vk] for s in seeds])) for vk in ("orig", "nopb", "ey")}
        perf = {}
        for vk in ("orig", "nopb", "ey"):
            for v in VERS:
                k = f"{vk}|{v}|rev|old"
                ex = [rs[s]["runs"][k]["xirr"] - rs[s]["runs"][k]["bh"] for s in seeds]
                dex = [ex[i] - (base[s]["runs"][f"orig|{v}|rev|old"]["xirr"] - base[s]["runs"][f"orig|{v}|rev|old"]["bh"]) for i, s in enumerate(seeds)]
                dvar = [rs[s]["runs"][k]["xirr"] - rs[s]["runs"][f"orig|{v}|rev|old"]["xirr"] for s in seeds]
                perf[f"{vk}|{v}"] = dict(
                    xirr=float(np.mean([rs[s]["runs"][k]["xirr"] for s in seeds])),
                    bh=float(np.mean([rs[s]["runs"][k]["bh"] for s in seeds])),
                    ex=float(np.mean(ex)), dex=float(np.mean(dex)), dex_se=se(dex),
                    dvar=float(np.mean(dvar)), dvar_se=se(dvar),
                    mdd=float(np.mean([rs[s]["runs"][k]["mdd"] for s in seeds])),
                    dmdd=float(np.mean([rs[s]["runs"][k]["mdd"] - base[s]["runs"][f"orig|{v}|rev|old"]["mdd"] for s in seeds])),
                    idle=float(np.mean([rs[s]["runs"][k]["idle"] for s in seeds])),
                    didle=float(np.mean([rs[s]["runs"][k]["idle"] - base[s]["runs"][f"orig|{v}|rev|old"]["idle"] for s in seeds])),
                    sells=float(np.mean([rs[s]["runs"][k]["n_sell"] for s in seeds])),
                    rebuys=float(np.mean([rs[s]["runs"][k]["n_rebuy"] for s in seeds])))
        rec["perf"] = perf
        rv = {}
        for v in ["1.7", "1.8", "1.9"]:
            dold = [x for s in seeds for x in rs[s]["runs"][f"orig|{v}|rev|old"]["dec"]]
            dnew = [x for s in seeds for x in rs[s]["runs"][f"orig|{v}|rev|new"]["dec"]]
            gain_old = [rs[s]["runs"][f"orig|{v}|rev|old"]["xirr"] - rs[s]["runs"][f"orig|{v}|norev|old"]["xirr"] for s in seeds]
            gain_new = [rs[s]["runs"][f"orig|{v}|rev|new"]["xirr"] - rs[s]["runs"][f"orig|{v}|norev|old"]["xirr"] for s in seeds]
            rv[v] = dict(n_old=len(dold), up_old=sum(a for a, _ in dold), acc_old=float(np.mean([a == b for a, b in dold])) if dold else None,
                         false_up_old=sum(1 for a, b in dold if a and not b), true_up=sum(1 for _, b in dold if b),
                         n_new=len(dnew), up_new=sum(a for a, _ in dnew), acc_new=float(np.mean([a == b for a, b in dnew])) if dnew else None,
                         false_up_new=sum(1 for a, b in dnew if a and not b), miss_new=sum(1 for a, b in dnew if b and not a),
                         miss_old=sum(1 for a, b in dold if b and not a),
                         gain_old=float(np.mean(gain_old)), gain_new=float(np.mean(gain_new)), gain_se=se(np.array(gain_new) - np.array(gain_old)))
        rec["review"] = rv
        if "series" in rs[SEED0]:
            rec["series"] = rs[SEED0]["series"]
        out["scen"].append(rec)

    # 第二层
    L2 = [r for r in res if r["layer"] == "L2"]
    b2 = {}
    for r in L2:
        b2.setdefault(r["key"], {})[r["seed"]] = r
    ck0 = "0|0|0|0"
    cres = {}
    for c in combos:
        if not c["kept"]:
            continue
        rs = b2[c["key"]]
        seeds = sorted(rs)
        rec = dict(dV=float(np.mean([rs[s]["V"]["orig"] - b2[ck0][s]["V"]["orig"] for s in seeds])),
                   dV_post=float(np.mean([rs[s]["V_post"]["orig"] - b2[ck0][s]["V_post"]["orig"] for s in seeds])),
                   dpct={k: float(np.mean([rs[s]["pct"][k] - b2[ck0][s]["pct"][k] for s in seeds])) for k in ("ey", "bp", "dy", "erp")},
                   corr=float(np.mean([rs[s]["corr"]["orig"] for s in seeds])))
        for v in VERS:
            k = f"orig|{v}|rev|old"
            rec[v] = float(np.mean([(rs[s]["runs"][k]["xirr"] - rs[s]["runs"][k]["bh"]) - (b2[ck0][s]["runs"][k]["xirr"] - b2[ck0][s]["runs"][k]["bh"]) for s in seeds]))
            rec[v + "_mdd"] = float(np.mean([rs[s]["runs"][k]["mdd"] - b2[ck0][s]["runs"][k]["mdd"] for s in seeds]))
            rec[v + "_ex"] = float(np.mean([rs[s]["runs"][k]["xirr"] - rs[s]["runs"][k]["bh"] for s in seeds]))
        rec["avg"] = float(np.mean([rec[v] for v in VERS]))
        cres[c["key"]] = rec
    out["combo_res"] = cres
    kept = [c for c in combos if c["kept"]]
    # 主效应
    me = {}
    for f in ("pe", "roe", "p", "y", "rp_sign"):
        me[f] = {}
        if f == "rp_sign":
            groups = {"−": [c for c in kept if c["rp"] < -0.004], "0": [c for c in kept if abs(c["rp"]) <= 0.004], "+": [c for c in kept if c["rp"] > 0.004]}
        else:
            groups = {f"{lv:g}": [c for c in kept if abs(c[f] - lv) < 1e-12] for lv in LEVELS[f]}
        for g, cs in groups.items():
            me[f][g] = dict(n=len(cs), dV=float(np.mean([cres[c["key"]]["dV"] for c in cs])) if cs else None,
                            avg=float(np.mean([cres[c["key"]]["avg"] for c in cs])) if cs else None,
                            **{v: float(np.mean([cres[c["key"]][v] for c in cs])) if cs else None for v in VERS},
                            **{"pct_" + k: float(np.mean([cres[c["key"]]["dpct"][k] for c in cs])) if cs else None for k in ("ey", "bp", "dy", "erp")})
    out["main_effects"] = me
    # 线性回归：Δ超额 / ΔV 对编码后的因子（−1/0/+1）
    X = np.array([[np.sign(c["pe"]), np.sign(c["roe"]), np.sign(c["p"]), np.sign(c["y"]), 1.0] for c in kept])
    reg = {}
    for tgt in ["dV", "avg"] + VERS:
        yv = np.array([cres[c["key"]][tgt] for c in kept])
        beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
        resid = yv - X @ beta
        r2 = 1 - resid.var() / yv.var() if yv.var() > 0 else 0
        reg[tgt] = dict(pe=float(beta[0]), roe=float(beta[1]), p=float(beta[2]), y=float(beta[3]), c=float(beta[4]), r2=float(r2))
    out["reg"] = reg
    out["n_kept"] = len(kept)
    out["n_combos"] = len(combos)
    out["params"] = dict(D=gen2.D_EQ, kappa=gen2.KAPPA, lam=gen2.LAMBDA, roe0=gen2.ROE0, p0=gen2.P0, y0=gen2.Y0, g0=gen2.G0, N1=N1, N2=N2)
    return out


def main():
    jobs, combos = build_jobs()
    print("jobs", len(jobs), "kept combos", sum(c["kept"] for c in combos), flush=True)
    t0 = time.time()
    res = []
    with mp.Pool(4) as pool:
        for k, r in enumerate(pool.imap_unordered(job, jobs, chunksize=2)):
            res.append(r)
            if k % 100 == 0:
                print(f"{k + 1}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    out = aggregate(res, combos)

    def clean(o):
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating, float)):
            f = float(o)
            return None if f != f else round(f, 6)
        if isinstance(o, (np.integer, np.bool_)):
            return o.item()
        return o
    json.dump(clean(out), open(os.path.join(HERE, "results", "drift_study.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
