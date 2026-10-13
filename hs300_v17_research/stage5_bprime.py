"""阶段五：止盈"超买回落"机制的分段归因与结构参数敏感性。"""
import numpy as np, pandas as pd, itertools
from engine import simulate, metrics, twr_returns
from signals import raw, NAMES, DEFAULT
df = pd.read_pickle("out/panel.pkl")
def fade(s, L):
    was = s.fillna(False).astype(int).rolling(L, min_periods=1).max().shift(1).fillna(0).astype(bool)
    return was & ~s.fillna(False)
b0 = simulate(df); r0 = twr_returns(b0)
_, s = raw("BIAS", 20, 5.0)
r1 = twr_returns(simulate(df, sell_sig=fade(s, 5), sell_wait=20))
eps = {"2014-15牛市": ("2014-07", "2015-12"), "2016-18慢牛": ("2016-01", "2018-12"), "2019-21核心资产": ("2019-01", "2021-12"), "2022-26": ("2022-01", "2026-12")}
rows = []
for k, (a, b) in eps.items():
    x0 = (1 + r0[a:b]).prod() - 1; x1 = (1 + r1[a:b]).prod() - 1
    rows.append(dict(阶段=k, V16=x0, BIAS回落=x1, 差=x1 - x0))
print(pd.DataFrame(rows).round(4))
rows = []
for L, W in itertools.product((3, 5, 10), (10, 20, 40)):
    for nm in NAMES:
        _, s = raw(nm, *DEFAULT[nm])
        m = metrics(simulate(df, sell_sig=fade(s, L), sell_wait=W))
        rows.append(dict(回看=L, 安全阀=W, 指标=nm, IRR=m["IRR"], Calmar=m["Calmar"]))
T = pd.DataFrame(rows); base = metrics(b0)
T["ΔIRR"] = T.IRR - base["IRR"]
print(T.pivot_table(index=["回看", "安全阀"], columns="指标", values="ΔIRR").round(4))
print("全部 81 个结构组合中 ΔIRR>0 的比例:", (T.ΔIRR > 0).mean().round(3), " 中位 ΔIRR:", T.ΔIRR.median().round(4))
T.to_pickle("out/stage5.pkl"); pd.DataFrame(rows).to_csv("out/stage5.csv", index=False, encoding="utf-8-sig")
