"""收益-回撤平衡：唯一调节杆 = 最多卖出比例 m（保留 1−m 底仓）
- Plan D 族：卖出比例 = min(⌊(1−U8)×4⌋/4, m)
- Plan C 族：S<25 且 U≤1/3 时一次卖出 m
平衡指标（事先定义）：Calmar = XIRR / |MDD|（资金加权），同时给 TWR/|MDD|
每个 m 同时给出参数邻域（减仓区20/25/30 × 回补40/50/60 × 回补期60/120/250）的中位数
"""
import itertools, numpy as np, pandas as pd
from engine import load_data, add_signals, set_ma, run
from plan_d import ENS8, make_sell_fn

OUT = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); OUT.append(s)

raw = load_data()
cases = {"扩张口径·2016-09起(主)": (add_signals(raw, years=100, min_n=1, warmup_years=5), "2016-09-30"),
         "原规则口径·2013-11起(含2015,偏乐观)": (add_signals(raw), "2013-11-07")}

def capped(z, m):
    f = make_sell_fn(z, 4)
    return lambda s, u: min(f(s, u), m)

for lab, (sig, st) in cases.items():
    dD = set_ma(sig, ENS8)
    p(f"\n## {lab}")
    rows = []
    for m in [0, 0.25, 0.5, 0.75, 1.0]:
        rd = run(dD, start=st, sell_fn=capped(25, m), resume_thr=50, reentry="tranche", tranche_days=120, dca_while_waiting=True)
        nb = []
        for z, rs, td in itertools.product([20, 25, 30], [40, 50, 60], [60, 120, 250]):
            r = run(dD, start=st, sell_fn=capped(z, m), resume_thr=rs, reentry="tranche", tranche_days=td, dca_while_waiting=True)
            nb.append((r["xirr"], r["mdd"], r["xirr"] / abs(r["mdd"])))
        nb = np.array(nb)
        rc = run(sig, start=st, tiers=((25, m),) if m > 0 else ())
        rows.append({"最多卖出": f"{m:.0%}",
                     "D·XIRR": round(rd["xirr"]*100, 2), "D·MDD": round(rd["mdd"]*100, 1),
                     "D·Calmar": round(rd["xirr"]/abs(rd["mdd"]), 3), "D·TWR/MDD": round(rd["twr"]/abs(rd["mdd"]), 3),
                     "D邻域XIRR中位": round(np.median(nb[:, 0])*100, 2), "D邻域MDD中位": round(np.median(nb[:, 1])*100, 1),
                     "D邻域Calmar中位": round(np.median(nb[:, 2]), 3), "D邻域Calmar最差": round(nb[:, 2].min(), 3),
                     "C·XIRR": round(rc["xirr"]*100, 2), "C·MDD": round(rc["mdd"]*100, 1), "C·Calmar": round(rc["xirr"]/abs(rc["mdd"]), 3)})
    p(pd.DataFrame(rows).to_string(index=False))
open("results_balance.txt", "w").write("\n".join(OUT))
