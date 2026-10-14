"""汇总 compare_v17_raw.json → compare_v17.json，并打印对比表。"""
import json, os
import numpy as np
import gen, gen2, study
HERE = os.path.dirname(os.path.abspath(__file__))
res = json.load(open(os.path.join(HERE, "results", "compare_v17_raw.json")))
KCN = {"base": "基准震荡", "slow_up": "缓慢上移", "slow_down": "缓慢下移", "jump_up": "快速跳升", "jump_down": "快速跳降",
       "cycle": "强周期", "bubble": "泡沫崩盘", "stagnation": "长停滞", "fake_reversion": "高频假回归", "mixed": "混合极端"}
MET = [("xirr", "net"), ("xirr", "gross"), ("ex_bh", "net"), ("mdd", "net"), ("uw_days", "net"), ("sharpe", "net"), ("sortino", "net"),
       ("calmar", "net"), ("cost_ratio", "net"), ("turnover", "net"), ("n_sell", "net"), ("n_rebuy", "net"), ("spread", "net"), ("pool_idle", "net")]


def pe_grp(key):
    a = gen2.analytic(dict([s for s in study.SCEN if s[0] == key][0][4]))["pe"]
    return "基准" if key == "S0" else ("PE中枢上移" if a > 0.05 else ("PE中枢下移" if a < -0.05 else "成分漂移"))


def summ(rs):
    o = {"n": len(rs)}
    for m, c in MET:
        a = np.array([r["v"]["orig"][c][m] for r in rs], float)
        b = np.array([r["v"]["new"][c][m] for r in rs], float)
        ok = ~np.isnan(a) & ~np.isnan(b)
        d = b[ok] - a[ok]
        o[f"{m}|{c}"] = dict(orig=float(a[ok].mean()), new=float(b[ok].mean()), d=float(d.mean()),
                             se=float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0,
                             win=float(np.mean(d > 0)) if m not in ("mdd", "uw_days", "cost_ratio", "turnover", "pool_idle") else float(np.mean(d < 0)))
    for k in ("mean", "hi", "lo", "corr", "rmse", "bias"):
        o["v_" + k] = dict(orig=float(np.mean([r["v"]["orig"]["vstat"][k] for r in rs])), new=float(np.mean([r["v"]["new"]["vstat"][k] for r in rs])))
    for typ in ("crisis", "bubble"):
        co = [c for r in rs for c in r["v"]["orig"]["crises"] if c["type"] == typ]
        cn = [c for r in rs for c in r["v"]["new"]["crises"] if c["type"] == typ]
        if co:
            o[typ] = {vk: dict(n=len(cs), escape=float(np.mean([c["escape"] for c in cs])), bottom=float(np.mean([c["bottom"] for c in cs])),
                               dd=float(np.mean([c["dd"] for c in cs])), p_peak=float(np.mean([c["p_peak"] for c in cs])),
                               repair=float(np.median([c["repair"] for c in cs if c["repair"] is not None])) if any(c["repair"] is not None for c in cs) else None)
                      for vk, cs in (("orig", co), ("new", cn))}
    o["triggers"] = dict(orig=float(np.mean([r["v"]["orig"]["triggers"] for r in rs])), new=float(np.mean([r["v"]["new"]["triggers"] for r in rs])))
    return o


G = {}
G["主路径 10 条"] = [r for r in res if r["set"] == "main"]
G["蒙特卡洛 300 条"] = [r for r in res if r["set"] == "mc"]
G["漂移情景 432 条"] = [r for r in res if r["set"] == "drift"]
G["全部 742 条"] = res
for k in KCN:
    G["MC·" + KCN[k]] = [r for r in res if r["set"] == "mc" and r["key"] == k]
for g in ("基准", "PE中枢上移", "PE中枢下移", "成分漂移"):
    G["漂移·" + g] = [r for r in res if r["set"] == "drift" and pe_grp(r["key"]) == g]
S = {g: summ(rs) for g, rs in G.items()}
_order = {sd: no for no, k, nm, ds, sd in gen.PATH_SPECS}
S["_main_paths"] = [dict(no=_order[r["seed"]], key=r["key"], orig=r["v"]["orig"]["net"]["xirr"], new=r["v"]["new"]["net"]["xirr"],
                         orig_mdd=r["v"]["orig"]["net"]["mdd"], new_mdd=r["v"]["new"]["net"]["mdd"], bh=r["v"]["orig"]["net"]["xirr_bh"])
                    for r in sorted(G["主路径 10 条"], key=lambda r: _order[r["seed"]])]
json.dump(S, open(os.path.join(HERE, "results", "compare_v17.json"), "w"), ensure_ascii=False)

f = lambda x: f"{x*100:+.2f}"
for p in S["_main_paths"]:
    print("path", p["no"], p["key"], f"orig {p['orig']*100:.2f} new {p['new']*100:.2f} d {(p['new']-p['orig'])*100:+.2f} mdd {p['orig_mdd']*100:.1f}->{p['new_mdd']*100:.1f} bh {p['bh']*100:.2f}")
for g, o in S.items():
    if g.startswith("_"):
        continue
    print(f"== {g} (n={o['n']})")
    for m, c in MET:
        x = o[f"{m}|{c}"]
        sc = 100 if m in ("xirr", "ex_bh", "mdd", "cost_ratio", "spread", "pool_idle") else 1
        print(f"   {m}|{c:5s} 原 {x['orig']*sc:8.2f} 新 {x['new']*sc:8.2f} 差 {x['d']*sc:+7.2f} ± {x['se']*sc:.2f}  更优占比 {x['win']:.0%}")
    print("   V: " + " ".join(f"{k} {o['v_'+k]['orig']:.3f}→{o['v_'+k]['new']:.3f}" for k in ("mean", "hi", "lo", "corr", "rmse", "bias")))
    for typ in ("crisis", "bubble"):
        if typ in o:
            print(f"   {typ}: " + " | ".join(f"{vk} n{d['n']} 逃顶{d['escape']:.0%} 抄底{d['bottom']:.0%} 回撤{d['dd']:.1%} 修复{d['repair']}" for vk, d in o[typ].items()))
