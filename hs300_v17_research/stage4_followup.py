"""阶段四：逻辑驱动的追加检验 + 预先指定的 V1.7 候选组合 + 消融 + 起点敏感性。"""
import numpy as np, pandas as pd, itertools
from multiprocessing import Pool
from engine import simulate, metrics
from signals import raw, channel_trend, grid, PX
from stage2_strategy import ob_fade, IS, OOS

df = pd.read_pickle("out/panel.pkl")
def M(kw, start="2014-01-07"):
    r = simulate(df, start=start, **kw); m = metrics(r)
    m["IS_Sharpe"] = metrics(r, IS)["Sharpe"]; m["OOS_Sharpe"] = metrics(r, OOS)["Sharpe"]
    return m

# 1) 波动率"刹车"：高波动时暂停回投（等波动回落或满 W 日）
def brake(args):
    n, k, w = args
    b, _ = raw("波动率分位", n, k)
    return ("高波动暂停回投", (n, k, w)), M(dict(buy_sig=~b, buy_wait=w))
# 安慰剂：平移
def brake_plc(sh):
    b, _ = raw("波动率分位", 20, 80)
    rb = pd.Series(np.roll(b.fillna(False).values, sh), PX.index)
    return ("安慰剂", sh), M(dict(buy_sig=~rb, buy_wait=20))

# 2) 组合
KC = channel_trend(20, 1.5, "凯尔特纳")
U2 = (df.U * 3 + KC.reindex(df.index)) / 4
_, sB = raw("BIAS", 20, 5.0)
bV, _ = raw("波动率分位", 20, 80)
mods = {"趋势合成(U+凯尔特纳)": dict(U=U2), "止盈:BIAS超买回落": dict(sell_sig=ob_fade(sB), sell_wait=20),
        "回投:高波动刹车": dict(buy_sig=~bV, buy_wait=20)}
def combo(names):
    kw = {}
    for nm in names: kw.update(mods[nm])
    return ("组合", " + ".join(names) or "V1.6基线"), M(kw)
def start_sens(args):
    nm, st = args
    kw = {}
    if nm == "V1.7候选":
        for v in mods.values(): kw.update(v)
    return ("起点", (nm, st)), M(kw, st)

if __name__ == "__main__":
    jobs = []
    with Pool(4) as p:
        A = p.map(brake, list(itertools.product((10, 20, 40), (75, 80, 85), (20, 40))))
        rng = np.random.default_rng(11)
        B = p.map(brake_plc, list(rng.integers(120, len(PX) - 120, 40)))
        subsets = [c for r in range(0, 4) for c in itertools.combinations(mods, r)]
        C = p.map(combo, subsets)
        starts = [s.strftime("%Y-%m-%d") for s in pd.date_range("2014-01-07", "2019-01-07", freq="6MS")]
        D = p.map(start_sens, [(nm, s) for nm in ("V1.6", "V1.7候选") for s in starts])
    out = pd.DataFrame([dict(类=k[0], 名=str(k[1])) | m for k, m in A + B + C + D])
    out.to_pickle("out/stage4.pkl")
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    cols = ["类", "名", "IRR", "TWR年化", "Sharpe", "最大回撤", "Calmar", "IS_Sharpe", "OOS_Sharpe", "止盈次数", "回投次数"]
    base = out[(out.类 == "组合") & (out.名 == "V1.6基线")].iloc[0]
    print(out[out.类.isin(["高波动暂停回投", "组合"])][cols].round(4).to_string())
    pl = out[out.类 == "安慰剂"]
    dflt = out[(out.类 == "高波动暂停回投") & (out.名 == "(20, 80, 20)")].iloc[0]
    print("刹车默认 Calmar 在安慰剂中的分位:", (pl.Calmar < dflt.Calmar).mean(), "安慰剂中位Calmar", pl.Calmar.median(), "基线", base.Calmar)
    s = out[out.类 == "起点"].copy(); s["版本"] = s.名.str.extract(r"'(V1\.\d\S*)'"); s["起点"] = s.名.str.extract(r"(\d{4}-\d\d-\d\d)")
    piv = s.pivot(index="起点", columns="版本", values=["IRR", "Calmar"])
    print(piv.round(4)); print("V1.7 IRR 胜出比例", (piv["IRR"]["V1.7候选"] > piv["IRR"]["V1.6"]).mean(),
                              "Calmar 胜出比例", (piv["Calmar"]["V1.7候选"] > piv["Calmar"]["V1.6"]).mean())
