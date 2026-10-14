"""汇总 v110_raw.json → v110.json，并打印对比表。"""
import json, os
import numpy as np
import gen2, study
HERE = os.path.dirname(os.path.abspath(__file__))
res = json.load(open(os.path.join(HERE, "results", "v110_raw.json")))
V = ["1.6", "1.7", "1.8", "1.9", "1.10", "1.10a", "1.10b"]
KCN = {"base": "基准震荡", "slow_up": "缓慢上移", "slow_down": "缓慢下移", "jump_up": "快速跳升", "jump_down": "快速跳降",
       "cycle": "强周期", "bubble": "泡沫崩盘", "stagnation": "长停滞", "fake_reversion": "高频假回归", "mixed": "混合极端"}


def pe_grp(key):
    a = gen2.analytic(dict([s for s in study.SCEN if s[0] == key][0][4]))["pe"]
    return "基准" if key == "S0" else ("PE中枢上移" if a > 0.05 else ("PE中枢下移" if a < -0.05 else "成分漂移"))


def se(a):
    a = np.asarray(a, float); a = a[~np.isnan(a)]
    return float(a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 1 else 0.0


def summ(rs):
    o = {"n": len(rs)}
    for v in V:
        g = lambda k: [np.nan if r["v"][v][k] is None else r["v"][v][k] for r in rs]
        d = {k: float(np.nanmean(g(k))) for k in ("xirr", "ex_bh", "mdd", "calmar", "sharpe", "cost_ratio", "turnover", "n_sell", "n_rebuy", "spread", "pool_idle", "uw_days")}
        for ref in ("1.7", "1.9"):
            dx = np.array(g("xirr")) - np.array([r["v"][ref]["xirr"] for r in rs])
            dm = np.array(g("mdd")) - np.array([r["v"][ref]["mdd"] for r in rs])
            d[f"vs{ref}"] = dict(dx=float(dx.mean()), se=se(dx), win=float(np.mean(dx > 0)), dmdd=float(dm.mean()), dmdd_se=se(dm))
        tr = [t for r in rs for t in r["v"][v]["traps"]]
        up = [t for t in tr if t["dir"] > 0]
        dn = [t for t in tr if t["dir"] < 0]
        ups = [t for t in up if t["ns"] > 0]
        d["trap"] = dict(n_up=len(up), n_dn=len(dn),
                         up_trig=float(np.mean([t["n"] > 0 for t in up])), up_sell_trig=float(np.mean([t["ns"] > 0 for t in up])),
                         up_sells_per=float(np.mean([t["ns"] for t in up])),
                         up_sell_loss_rate=float(np.mean([t["g_sell"] < 0 for t in ups])) if ups else None,
                         up_sell_pnl=float(np.mean([t["g_sell"] for t in up])), up_buy_pnl=float(np.mean([t["g_buy"] for t in up])),
                         up_sell_loss_mean=float(np.mean([-t["g_sell"] for t in ups if t["g_sell"] < 0])) if any(t["g_sell"] < 0 for t in ups) else 0.0,
                         dn_trig=float(np.mean([t["n"] > 0 for t in dn])), dn_pnl=float(np.mean([t["g_sell"] + t["g_buy"] for t in dn])))
        fd = [x for r in rs for x in r["v"][v]["fdrop"]]
        d["fdrop"] = dict(n=len(fd), rate=float(np.mean([x["fd"] for x in fd])) if fd else None,
                          rate_amt=float(sum(x["amt"] for x in fd if x["fd"]) / sum(x["amt"] for x in fd)) if fd else None,
                          ret26=float(np.nanmean([np.nan if x["ret26"] is None else x["ret26"] for x in fd])) if fd else None,
                          dd26=float(np.nanmean([np.nan if x["dd26"] is None else x["dd26"] for x in fd])) if fd else None)
        for typ in ("crisis", "bubble"):
            cs = [c for r in rs for c in r["v"][v]["crises"] if c["type"] == typ]
            if cs:
                d[typ] = dict(n=len(cs), escape=float(np.mean([c["escape"] for c in cs])), bottom=float(np.mean([c["bottom"] for c in cs])),
                              dd=float(np.mean([c["dd"] for c in cs])), p_peak=float(np.mean([c["p_peak"] for c in cs])),
                              repair=float(np.median([c["repair"] for c in cs if c["repair"] is not None])) if any(c["repair"] is not None for c in cs) else None,
                              sell_vs_peak=float(np.nanmean([np.nan if c["sell_vs_peak"] is None else c["sell_vs_peak"] for c in cs])))
        o[v] = d
    o["s_days"] = dict(old=float(np.mean([r["s_days"]["old"] for r in rs])), new=float(np.mean([r["s_days"]["new"] for r in rs])))
    return o


G = {"主路径 10 条": [r for r in res if r["set"] == "main"], "蒙特卡洛 300 条": [r for r in res if r["set"] == "mc"],
     "漂移情景 216 条": [r for r in res if r["set"] == "drift"], "全部 526 条": res}
for k, nm in KCN.items():
    G["MC·" + nm] = [r for r in res if r["set"] == "mc" and r["key"] == k]
for g in ("基准", "PE中枢上移", "PE中枢下移", "成分漂移"):
    G["漂移·" + g] = [r for r in res if r["set"] == "drift" and pe_grp(r["key"]) == g]
S = {g: summ(rs) for g, rs in G.items()}
json.dump(S, open(os.path.join(HERE, "results", "v110.json"), "w"), ensure_ascii=False)
f = lambda x: "—" if x is None else f"{x*100:+.2f}"
for g in ["主路径 10 条", "蒙特卡洛 300 条", "漂移情景 216 条", "全部 526 条"]:
    o = S[g]; print(f"\n######## {g} (n={o['n']})  S=1 天数占比 旧 {o['s_days']['old']:.3f} 新 {o['s_days']['new']:.3f}")
    for v in V:
        d = o[v]
        print(f" {v:6s} xirr {d['xirr']*100:6.2f} ex {d['ex_bh']*100:+.2f} mdd {d['mdd']*100:5.1f} calmar {d['calmar']:.3f} cost {d['cost_ratio']*100:.2f} sells {d['n_sell']:5.1f} rebuy {d['n_rebuy']:5.1f} spread {d['spread']*100:5.1f} idle {d['pool_idle']*100:4.1f} | vs1.7 {f(d['vs1.7']['dx'])}±{d['vs1.7']['se']*100:.2f} win {d['vs1.7']['win']:.0%} dmdd {f(d['vs1.7']['dmdd'])} | vs1.9 {f(d['vs1.9']['dx'])}±{d['vs1.9']['se']*100:.2f} dmdd {f(d['vs1.9']['dmdd'])}")
    for v in V:
        t = o[v]["trap"]; fd = o[v]["fdrop"]
        print(f"   trap {v:6s} up n{t['n_up']} 触发 {t['up_trig']:.0%} 卖出触发 {t['up_sell_trig']:.1%} 卖出次数/陷阱 {t['up_sells_per']:.2f} 卖出亏损率 {t['up_sell_loss_rate'] if t['up_sell_loss_rate'] is None else round(t['up_sell_loss_rate']*100)}% 卖出盈亏/陷阱 {f(t['up_sell_pnl'])}% 亏损时均亏 {t['up_sell_loss_mean']*100:.2f}% 买入盈亏 {f(t['up_buy_pnl'])}% | down 触发 {t['dn_trig']:.0%} 盈亏 {f(t['dn_pnl'])}% || 假回落卖出率 {fd['rate']:.1%} 金额 {fd['rate_amt']:.1%} 卖后26周最高 {f(fd['ret26'])}% 最低 {f(fd['dd26'])}% (n={fd['n']})")
    for typ in ("crisis", "bubble"):
        for v in V:
            if typ in o[v]:
                c = o[v][typ]; print(f"   {typ} {v:6s} n{c['n']} 逃顶 {c['escape']:.0%} 高点持仓 {c['p_peak']:.0%} 抄底 {c['bottom']:.0%} 回撤 {c['dd']:.1%} 修复 {c['repair']} 卖价/高点 {c['sell_vs_peak']:.3f}")
print("\n######## 分市场：V1.10 / 1.10a / 1.10b 相对 V1.7 的年化差（±se）与回撤差")
for g, o in S.items():
    if g.startswith("MC·") or g.startswith("漂移·"):
        print(f" {g:12s} n{o['n']:3d} " + " | ".join(f"{v}: {f(o[v]['vs1.7']['dx'])}±{o[v]['vs1.7']['se']*100:.2f} mdd {f(o[v]['vs1.7']['dmdd'])}" for v in ("1.10", "1.10a", "1.10b")) + f" | 1.10 vs1.9 {f(o['1.10']['vs1.9']['dx'])}")
