"""把 results/raw.json 汇总为 results/summary.json（报告直接引用的全部统计量）。"""
import json
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
VERS = ["1.6", "1.7", "1.8", "1.9"]
KIND_CN = {"base": "基准震荡", "slow_up": "缓慢上移", "slow_down": "缓慢下移", "jump_up": "快速跳升",
           "jump_down": "快速跳降", "cycle": "强周期", "bubble": "泡沫崩盘", "stagnation": "长停滞",
           "fake_reversion": "高频假回归", "mixed": "混合极端"}
KINDS = list(KIND_CN)


def nz(x):
    return [v for v in x if v is not None and v == v]


def stats(x):
    x = np.array(nz(x), float)
    if len(x) == 0:
        return dict(mean=None, median=None, std=None, n=0)
    return dict(mean=float(x.mean()), median=float(np.median(x)), std=float(x.std(ddof=1)) if len(x) > 1 else 0.0,
                se=float(x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else 0.0, n=int(len(x)),
                min=float(x.min()), max=float(x.max()))


def r6(o):
    if isinstance(o, dict):
        return {k: r6(v) for k, v in o.items()}
    if isinstance(o, list):
        return [r6(v) for v in o]
    if isinstance(o, float):
        return round(o, 6)
    return o


def main():
    raw = json.load(open(os.path.join(OUT, "raw.json")))
    mainp = sorted([r for r in raw if not r["label"]["mc"]], key=lambda r: r["label"]["no"])
    mcp = [r for r in raw if r["label"]["mc"] and r["label"]["set"] != "留出验证"]
    hold = [r for r in raw if r["label"]["set"] == "留出验证"]
    allp = mainp + mcp
    S = {}

    # ---------------- 1. 数据概览 ----------------
    ov = []
    for r in mainp:
        ev = r["events"]
        ov.append(dict(no=r["label"]["no"], name=r["label"]["name"], set=r["label"]["set"], kind=r["kind"],
                       seed=r["seed"], stats=r["path_stats"],
                       n_crisis=sum(1 for e in ev if e["type"] == "crisis" and e["peak"] >= 2017),
                       n_crisis_all=sum(1 for e in ev if e["type"] == "crisis"),
                       n_corr=sum(1 for e in ev if e["type"] == "correction"),
                       n_bubble=sum(1 for e in ev if e["type"] == "bubble"),
                       traps_up=sum(1 for t in r["trap_list"] if t["dir"] > 0),
                       traps_down=sum(1 for t in r["trap_list"] if t["dir"] < 0),
                       drift=r["drift_meta"], events=ev, trap_list=r["trap_list"]))
    S["overview"] = ov
    S["series"] = {r["label"]["no"]: r["series"] for r in mainp}

    # ---------------- 2. 全周期总览 ----------------
    metrics = ["final", "xirr", "xirr_bh", "xirr_dca", "ex_bh", "ex_dca", "mdd", "uw_days", "down_vol", "sortino",
               "sharpe", "calmar", "cost_ratio", "turnover", "n_sell", "n_rebuy", "spread", "pool_idle", "cagr_twr",
               "mdd_bh", "inflow", "cost_total", "cost_fee", "cost_comm", "cost_imp"]

    def table(paths):
        out = {}
        for v in VERS:
            for c in ("net", "gross"):
                key = f"{v}|{c}|{'rev' if v != '1.6' else 'norev'}"
                out[f"{v}|{c}"] = {m: stats([p["main"][key][m] for p in paths]) for m in metrics}
        return out

    S["overall_main"] = table(mainp)
    S["overall_mc"] = table(mcp)
    # 成本结构
    cs = {}
    for v in VERS:
        key = f"{v}|net|{'rev' if v != '1.6' else 'norev'}"
        tot = sum(p["main"][key]["cost_total"] for p in mainp)
        cs[v] = dict(fee=sum(p["main"][key]["cost_fee"] for p in mainp) / tot,
                     comm=sum(p["main"][key]["cost_comm"] for p in mainp) / tot,
                     imp=sum(p["main"][key]["cost_imp"] for p in mainp) / tot,
                     kind={k: sum(p["main"][key]["cost_kind"][k] for p in mainp) / tot for k in ("sell", "rebuy", "dca", "special")},
                     loss_xirr=float(np.mean([p["main"][f"{v}|gross|{'rev' if v != '1.6' else 'norev'}"]["xirr"] - p["main"][key]["xirr"] for p in mainp])),
                     loss_xirr_mc=float(np.mean([p["main"][f"{v}|gross|{'rev' if v != '1.6' else 'norev'}"]["xirr"] - p["main"][key]["xirr"] for p in mcp])))
    S["cost_struct"] = cs
    # 换手率与成本相关性（主路径 40 个净值回测 + MC）
    to, cr = [], []
    for p in allp:
        for v in VERS:
            m = p["main"][f"{v}|net|{'rev' if v != '1.6' else 'norev'}"]
            to.append(m["turnover"])
            cr.append(m["cost_ratio"])
    S["turnover_cost_corr"] = float(np.corrcoef(to, cr)[0, 1])
    # 逐路径
    S["per_path"] = [dict(no=p["label"]["no"], name=p["label"]["name"], set=p["label"]["set"],
                          **{v: dict(net=p["main"][f"{v}|net|{'rev' if v != '1.6' else 'norev'}"]["xirr"],
                                     gross=p["main"][f"{v}|gross|{'rev' if v != '1.6' else 'norev'}"]["xirr"],
                                     mdd=p["main"][f"{v}|net|{'rev' if v != '1.6' else 'norev'}"]["mdd"],
                                     final=p["main"][f"{v}|net|{'rev' if v != '1.6' else 'norev'}"]["final"])
                             for v in VERS},
                          bh=p["main"]["1.6|net|norev"]["xirr_bh"], bh_gross=p["main"]["1.6|gross|norev"]["xirr_bh"],
                          dca=p["main"]["1.6|net|norev"]["xirr_dca"], mdd_bh=p["main"]["1.6|net|norev"]["mdd_bh"])
                     for p in mainp]
    # 数据集
    sets = {}
    for sname in ("训练集", "测试集", "复核集"):
        ps = [p for p in mainp if p["label"]["set"] == sname]
        sets[sname] = {v: dict(net=float(np.mean([p["main"][f"{v}|net|{'rev' if v != '1.6' else 'norev'}"]["xirr"] for p in ps])),
                               ex=float(np.mean([p["main"][f"{v}|net|{'rev' if v != '1.6' else 'norev'}"]["ex_bh"] for p in ps])))
                       for v in VERS}
        sets[sname]["n"] = len(ps)
    S["sets"] = sets
    # MC 按类型 × 版本
    bytype = {}
    for k in KINDS:
        ps = [p for p in mcp if p["kind"] == k]
        bytype[k] = {v: dict(xirr=stats([p["main"][f"{v}|net|{'rev' if v != '1.6' else 'norev'}"]["xirr"] for p in ps]),
                             ex=stats([p["main"][f"{v}|net|{'rev' if v != '1.6' else 'norev'}"]["ex_bh"] for p in ps]),
                             mdd=stats([p["main"][f"{v}|net|{'rev' if v != '1.6' else 'norev'}"]["mdd"] for p in ps]),
                             gross=stats([p["main"][f"{v}|gross|{'rev' if v != '1.6' else 'norev'}"]["xirr"] for p in ps]))
                     for v in VERS}
        bytype[k]["bh"] = stats([p["main"]["1.6|net|norev"]["xirr_bh"] for p in ps])
        bytype[k]["bh_mdd"] = stats([p["main"]["1.6|net|norev"]["mdd_bh"] for p in ps])
    S["mc_bytype"] = bytype
    # 胜率（MC，按路径两两比较净 XIRR）
    win = {}
    for a in VERS:
        for b in VERS:
            if a == b:
                continue
            ka = f"{a}|net|{'rev' if a != '1.6' else 'norev'}"
            kb = f"{b}|net|{'rev' if b != '1.6' else 'norev'}"
            win[f"{a}>{b}"] = float(np.mean([p["main"][ka]["xirr"] > p["main"][kb]["xirr"] for p in mcp]))
    S["winrate"] = win
    # 复核增益
    rg = {}
    for v in ["1.7", "1.8", "1.9"]:
        d_main = [p["main"][f"{v}|net|rev"]["xirr"] - p["main"][f"{v}|net|norev"]["xirr"] for p in mainp]
        d_mc = {k: stats([p["main"][f"{v}|net|rev"]["xirr"] - p["main"][f"{v}|net|norev"]["xirr"] for p in mcp if p["kind"] == k]) for k in KINDS}
        rg[v] = dict(main=stats(d_main), per_path=d_main, mc_all=stats([p["main"][f"{v}|net|rev"]["xirr"] - p["main"][f"{v}|net|norev"]["xirr"] for p in mcp]),
                     mc_type=d_mc,
                     mdd=stats([p["main"][f"{v}|net|rev"]["mdd"] - p["main"][f"{v}|net|norev"]["mdd"] for p in mcp]))
    S["review_gain"] = rg

    # ---------------- 3. 中枢漂移速度 ----------------
    quad = {}
    for k in ("base", "slow_up", "slow_down", "jump_up", "jump_down"):
        ps = [p for p in allp if p["kind"] == k]
        quad[k] = {}
        for v in VERS + ["bh"]:
            if v == "bh":
                quad[k][v] = dict(xirr=stats([p["main"]["1.6|net|norev"]["xirr_bh"] for p in ps])["mean"],
                                  mdd=stats([p["main"]["1.6|net|norev"]["mdd_bh"] for p in ps])["mean"])
                continue
            key = f"{v}|net|{'rev' if v != '1.6' else 'norev'}"
            quad[k][v] = dict(xirr=stats([p["main"][key]["xirr"] for p in ps])["mean"],
                              ex=stats([p["main"][key]["ex_bh"] for p in ps])["mean"],
                              ex_se=stats([p["main"][key]["ex_bh"] for p in ps])["se"],
                              mdd=stats([p["main"][key]["mdd"] for p in ps])["mean"],
                              n=len(ps))
    S["quad"] = quad
    drift = {}
    for typ in ("slow", "jump"):
        for dr in (1, -1):
            recs = [(p, d) for p in allp for d in p["drifts"] if d["type"] == typ and d["dir"] == dr]
            key = f"{typ}_{'up' if dr > 0 else 'down'}"
            vb = [d["v_back"] if d["v_back"] is not None else None for _, d in recs]
            cens = sum(1 for _, d in recs if d["v_left"] is not None and d["v_back"] is None)
            out = dict(n=len(recs), v_left=stats([d["v_left"] for _, d in recs]), v_back=stats(vb),
                       v_back_censored=cens / max(1, len(recs)),
                       never_left=sum(1 for _, d in recs if d["v_left"] is None) / max(1, len(recs)))
            for v in VERS:
                out[v] = dict(slope=stats([d[v]["slope"] for _, d in recs]), loss3=stats([d[v]["loss3"] for _, d in recs]),
                              first_sell=stats([d[v]["first_sell"] for _, d in recs]),
                              first_buy=stats([d[v]["first_buy"] for _, d in recs]),
                              stuck=stats([d[v]["stuck"] for _, d in recs]),
                              stuck_rate=float(np.mean([d[v]["stuck"] is not None for _, d in recs])) if recs else None,
                              exhausted=stats([d[v]["exhausted"] for _, d in recs]),
                              exhausted_rate=float(np.mean([d[v]["exhausted"] is not None for _, d in recs])) if recs else None,
                              first_trigger=stats([d[v]["first_trigger"] for _, d in recs]),
                              trigger_rate=float(np.mean([d[v]["first_trigger"] is not None for _, d in recs])) if recs and v != "1.6" else None)
            drift[key] = out
    S["drift"] = drift

    # ---------------- 4. 假回归 ----------------
    def trap_agg(paths):
        out = {}
        for v in VERS:
            for side in ("all", "up", "down"):
                per = [x for p in paths for x in p["traps"][v]["per"] if side == "all" or (x["dir"] > 0) == (side == "up")]
                trig = [x for x in per if x["n_trades"] > 0]
                losses = [x["loss"] for x in trig]
                pbs = [pb for x in trig for pb in x["paybacks"]]
                out[f"{v}|{side}"] = dict(
                    n=len(per), n_trig=len(trig), prob=len(trig) / max(1, len(per)),
                    trades=float(np.mean([x["n_trades"] for x in per])) if per else 0,
                    sells=float(np.mean([x["n_sell"] for x in per])) if per else 0,
                    buys=float(np.mean([x["n_buy"] for x in per])) if per else 0,
                    loss_mean=float(np.mean(losses)) if losses else 0, loss_max=float(np.max(losses)) if losses else 0,
                    loss_median=float(np.median(losses)) if losses else 0,
                    loss_pos_rate=float(np.mean([l > 0 for l in losses])) if losses else 0,
                    loss_given_loss=float(np.mean([l for l in losses if l > 0])) if any(l > 0 for l in losses) else 0,
                    g_sell=float(np.mean([x["g_sell"] for x in trig])) if trig else 0,
                    g_buy=float(np.mean([x["g_buy"] for x in trig])) if trig else 0,
                    sell_loss_rate=float(np.mean([x["g_sell"] < 0 for x in trig if x["n_sell"] > 0])) if any(x["n_sell"] > 0 for x in trig) else 0,
                    buy_loss_rate=float(np.mean([x["g_buy"] < 0 for x in trig if x["n_buy"] > 0])) if any(x["n_buy"] > 0 for x in trig) else 0,
                    payback=stats([pb for pb in pbs if pb is not None]),
                    payback_censored=float(np.mean([pb is None for pb in pbs])) if pbs else 0)
            imp = [p["traps"][v]["impact"] for p in paths]
            out[f"{v}|impact"] = stats(imp)
            out[f"{v}|impact_pos"] = float(np.mean([x > 0 for x in nz(imp)])) if nz(imp) else None
        return out
    S["traps_main"] = trap_agg(mainp)
    S["traps_all"] = trap_agg(allp)
    S["traps_fr"] = trap_agg([p for p in allp if p["kind"] == "fake_reversion"])

    # ---------------- 5. 极端事件 ----------------
    def crisis_agg(paths, typ):
        recs = [c for p in paths for c in p["crises"] if c["type"] == typ]
        out = dict(n=len(recs), drop=stats([c["drop"] for c in recs]))
        for v in VERS + ["bh"]:
            if v == "bh":
                out[v] = dict(repair=stats([c["bh"]["repair"] for c in recs]),
                              repair_cens=float(np.mean([c["bh"]["repair"] is None for c in recs])) if recs else None,
                              dd=stats([c["bh"]["dd"] for c in recs]))
                continue
            out[v] = dict(escape=float(np.mean([c[v]["escape"] for c in recs])) if recs else None,
                          bottom=float(np.mean([c[v]["bottom"] for c in recs])) if recs else None,
                          p_peak=stats([c[v]["p_peak"] for c in recs]),
                          repair=stats([c[v]["repair"] for c in recs]),
                          repair_cens=float(np.mean([c[v]["repair"] is None for c in recs])) if recs else None,
                          dd=stats([c[v]["dd"] for c in recs]))
        return out
    S["crisis"] = crisis_agg(allp, "crisis")
    S["bubble"] = crisis_agg(allp, "bubble")
    hv = {}
    for v in VERS:
        key = f"{v}|net|{'rev' if v != '1.6' else 'norev'}"
        hv[v] = dict(imp_share_hv=float(np.mean([p["highvol"][v]["imp_share_hv"] for p in allp])),
                     imp_rate_hv=float(np.mean([p["highvol"][v]["imp_rate_hv"] for p in allp])),
                     imp_rate_lv=float(np.mean([p["highvol"][v]["imp_rate_lv"] for p in allp])))
    # 高波动路径（ATR 前 1/3）vs 低波动路径的净毛差
    atrs = np.array([p["atr_mean"] for p in allp])
    hi = atrs >= np.quantile(atrs, 2 / 3)
    lo = atrs <= np.quantile(atrs, 1 / 3)
    for v in VERS:
        kn = f"{v}|net|{'rev' if v != '1.6' else 'norev'}"
        kg = f"{v}|gross|{'rev' if v != '1.6' else 'norev'}"
        gap = np.array([p["main"][kg]["xirr"] - p["main"][kn]["xirr"] for p in allp])
        ex = np.array([p["main"][kn]["ex_bh"] for p in allp])
        exg = np.array([p["main"][kg]["ex_bh"] for p in allp])
        tov = np.array([p["main"][kn]["turnover"] for p in allp])
        hv[v].update(gap_hi=float(gap[hi].mean()), gap_lo=float(gap[lo].mean()),
                     ex_hi=float(ex[hi].mean()), ex_lo=float(ex[lo].mean()),
                     exg_hi=float(exg[hi].mean()), exg_lo=float(exg[lo].mean()),
                     corr_turn_ex=float(np.corrcoef(tov, ex)[0, 1]), corr_turn_gap=float(np.corrcoef(tov, gap)[0, 1]),
                     turnover=float(tov.mean()))
    hv["atr_hi"] = float(atrs[hi].mean())
    hv["atr_lo"] = float(atrs[lo].mean())
    S["highvol"] = hv

    # ---------------- 6. 参数鲁棒性 ----------------
    gp = [p for p in allp if "grid" in p]
    keys = ["SL", "RB", "TH", "FL"]
    levels = dict(SL=[65, 70, 75], RB=[45, 50, 55], TH=[0.03, 0.05, 0.07], FL=[0.1, 0.2, 0.3])
    base = dict(SL=70, RB=50, TH=0.05, FL=0.2)

    def ck(d):
        return "|".join(f"{float(d[k]):g}" for k in keys)
    combos = sorted({k.split("|", 1)[1] for k in gp[0]["grid"]})
    gres = {}
    for v in VERS:
        mean_all = {c: float(np.mean([p["grid"][f"{v}|{c}"] for p in gp])) for c in combos}
        base_val = mean_all[ck(base)]
        oat = {}
        for k in keys:
            vals = []
            for lv in levels[k]:
                d = dict(base)
                d[k] = lv
                vals.append(mean_all[ck(d)])
            oat[k] = dict(levels=levels[k], vals=vals, range=max(vals) - min(vals))
        best = max(mean_all, key=mean_all.get)
        plateau = [c for c in combos if mean_all[c] >= mean_all[best] - 0.0025]
        heat = {}
        for sl in levels["SL"]:
            for rb in levels["RB"]:
                heat[f"{sl}|{rb}"] = mean_all[ck(dict(SL=sl, RB=rb, TH=0.05, FL=0.2))]
        # 过拟合：在训练集（主路径 1/2/4/6）选最优，拿到测试 + 复核主路径和 MC 上检验
        tr = [p for p in mainp if p["label"]["set"] == "训练集"]
        te = [p for p in mainp if p["label"]["set"] != "训练集"]
        mcg = [p for p in mcp if "grid" in p]
        tr_mean = {c: float(np.mean([p["grid"][f"{v}|{c}"] for p in tr])) for c in combos}
        te_mean = {c: float(np.mean([p["grid"][f"{v}|{c}"] for p in te])) for c in combos}
        mc_mean = {c: float(np.mean([p["grid"][f"{v}|{c}"] for p in mcg])) for c in combos}
        bt = max(tr_mean, key=tr_mean.get)
        rank_te = sorted(combos, key=lambda c: -te_mean[c]).index(bt) + 1
        rank_mc = sorted(combos, key=lambda c: -mc_mean[c]).index(bt) + 1
        # 每个参数单独的 plateau 判定：平均 XIRR 对每档的标准差（跨路径）
        disp = {k: float(np.std([mean_all[ck({**base, k: lv})] for lv in levels[k]])) for k in keys}
        gres[v] = dict(base=base_val, oat=oat, best=best, best_val=mean_all[best], plateau=plateau,
                       plateau_n=len(plateau), heat=heat, rank=sorted(keys, key=lambda k: -oat[k]["range"]),
                       overfit=dict(best_train=bt, train_gain=tr_mean[bt] - tr_mean[ck(base)],
                                    test_gain=te_mean[bt] - te_mean[ck(base)], mc_gain=mc_mean[bt] - mc_mean[ck(base)],
                                    rank_test=rank_te, rank_mc=rank_mc, n=len(combos)),
                       worst=min(mean_all.values()), spread_all=max(mean_all.values()) - min(mean_all.values()),
                       disp=disp, all=mean_all)
    S["grid"] = gres
    S["grid_n_paths"] = len(gp)

    # ---------------- 7. 预警 ----------------
    def wagg(lst):
        tp = sum(x["tp"] for x in lst)
        fp = sum(x["fp"] for x in lst)
        tpd = sum(x["tp_days"] for x in lst)
        fpd = sum(x["fp_days"] for x in lst)
        ndd = sum(x["nd_days"] for x in lst)
        ne = sum(x["n_ep"] for x in lst)
        mi = sum(x["missed"] for x in lst)
        leads = [l for x in lst for l in x["leads"]]
        return dict(events=tp + fp, prec_ev=tp / (tp + fp) if tp + fp else None,
                    prec_day=tpd / (tpd + fpd) if tpd + fpd else None, fpr=fpd / ndd if ndd else None,
                    miss=mi / ne if ne else None, n_ep=ne, lead=stats(leads))
    sec = {}
    groups = dict(全部=allp, 缓慢漂移=[p for p in allp if p["kind"] in ("slow_up",)],
                  快速跳升=[p for p in allp if p["kind"] in ("jump_up",)],
                  无漂移=[p for p in allp if p["kind"] in ("base", "cycle", "bubble", "fake_reversion")],
                  混合=[p for p in allp if p["kind"] == "mixed"])
    for v in ["1.7", "1.8", "1.9"]:
        for cnd in ("all", "A", "B"):
            for gname, ps in groups.items():
                sec[f"{v}|{cnd}|{gname}"] = wagg([p["sec10"][v][cnd] for p in ps])
    S["sec10"] = sec
    mcw = {}
    var_names = list(allp[0]["multicycle"]["up"].keys())
    for d in ("up", "down", "both"):
        for vn in var_names:
            for gname, ps in dict(全部=allp, 缓慢=[p for p in allp if p["kind"] in ("slow_up", "slow_down", "stagnation")],
                                  快速=[p for p in allp if p["kind"] in ("jump_up", "jump_down")],
                                  无漂移=[p for p in allp if p["kind"] in ("base", "cycle", "bubble", "fake_reversion")]).items():
                lst = [p["multicycle"][dd][vn] for p in ps for dd in (("up", "down") if d == "both" else (d,))]
                mcw[f"{d}|{vn}|{gname}"] = wagg(lst)
    S["multicycle"] = mcw
    S["multicycle_variants"] = var_names
    # 分级应对
    schemes = ["无预警无复核", "第十节复核", "L1", "L2", "L3", "graded", "L1ML", "L1L3"]
    wr = {}
    for v in VERS:
        for sc in schemes:
            if sc not in allp[0]["warn"][v]:
                continue
            wr[f"{v}|{sc}|全部"] = dict(xirr=stats([p["warn"][v][sc]["xirr"] for p in allp]),
                                       mdd=stats([p["warn"][v][sc]["mdd"] for p in allp]),
                                       d=stats([p["warn"][v][sc]["xirr"] - p["warn"][v]["无预警无复核"]["xirr"] for p in allp]))
            for k in KINDS:
                ps = [p for p in allp if p["kind"] == k]
                wr[f"{v}|{sc}|{k}"] = dict(xirr=stats([p["warn"][v][sc]["xirr"] for p in ps]),
                                           mdd=stats([p["warn"][v][sc]["mdd"] for p in ps]),
                                           d=stats([p["warn"][v][sc]["xirr"] - p["warn"][v]["无预警无复核"]["xirr"] for p in ps]))
    S["warn_resp"] = wr
    # 留出验证集（独立种子，方案确定后才生成）
    wh = {}
    for v in VERS:
        for sc in schemes:
            if sc not in hold[0]["warn"][v]:
                continue
            wh[f"{v}|{sc}|全部"] = dict(d=stats([p["warn"][v][sc]["xirr"] - p["warn"][v]["无预警无复核"]["xirr"] for p in hold]),
                                       mdd=stats([p["warn"][v][sc]["mdd"] - p["warn"][v]["无预警无复核"]["mdd"] for p in hold]))
            for k in KINDS:
                ps = [p for p in hold if p["kind"] == k]
                wh[f"{v}|{sc}|{k}"] = dict(d=stats([p["warn"][v][sc]["xirr"] - p["warn"][v]["无预警无复核"]["xirr"] for p in ps]))
    S["warn_hold"] = wh
    S["n_hold"] = len(hold)
    S["n_paths"] = dict(main=len(mainp), mc=len(mcp), all=len(allp))
    S["n_traps_total"] = sum(p["n_traps"] for p in allp)
    S["n_crises_total"] = S["crisis"]["n"]
    json.dump(r6(S), open(os.path.join(OUT, "summary.json"), "w"), ensure_ascii=False)
    print("summary written")


if __name__ == "__main__":
    main()
