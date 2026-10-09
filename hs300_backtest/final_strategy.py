"""检验"多口径共识确认卖出"（Plan E = Plan D + 滚动7年确认）。结论：不采用（XIRR 与回撤均不如 Plan D），见 FINAL_STRATEGY.md

规则（预先写定）：
- 主 S：扩张窗口·日度更新，预热 5 年 —— 用于定投额度与回补
- 共识 S_exit = max(S_扩张, S_滚动7年)：两者都 < 25 才进入减仓区（滚动7年尚不可用时只看扩张）
- 减仓：S_exit<25 时目标卖出比例 = floor((1−U8)×4)/4，只减不加
- 回补：主 S > 50 起，资金池 120 交易日等额回补；定投不停
"""
import itertools
import numpy as np, pandas as pd
from engine import load_data, add_signals, set_ma, run, fmt
from plan_d import PLAN_D, ENS8, make_sell_fn

OUT = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); OUT.append(s)

raw = load_data()
exp = add_signals(raw, years=100, min_n=1, warmup_years=5)
roll = {n: add_signals(raw, years=n, min_n=1, warmup_years=n)["S"] for n in (5, 7, 10)}


def build(confirm=7):
    d = set_ma(exp, ENS8)
    if confirm:
        d["S_exit"] = np.fmax(d["S"], roll[confirm])   # 滚动不可用(NaN)时 fmax 取扩张
    else:
        d["S_exit"] = d["S"]
    return d


E = build(7)
PLAN_E = dict(PLAN_D, exit_col="S_exit")
base_c = exp                                   # Plan C 用扩张口径
starts = {"2016-09-30（扩张预热满5年）": "2016-09-30", "2018-10-08（滚动7年可用起）": "2018-10-08"}

for lab, st in starts.items():
    p(f"\n## 起点 {lab}")
    rows = []
    for name, r in [("Plan C（扩张口径）", run(base_c, start=st)),
                    ("Plan D（扩张口径）", run(set_ma(exp, ENS8), start=st, **PLAN_D)),
                    ("Plan E 最终方案", run(E, start=st, **PLAN_E)),
                    ("Plan E·全收益净值", run(E, start=st, nav="nav_tr", **PLAN_E)),
                    ("永不清仓", run(exp, start=st, tiers=())),
                    ("永不清仓·全收益净值", run(exp, start=st, tiers=(), nav="nav_tr"))]:
        rows.append(dict(方案=name, 本金=round(r["inflow"]), 期末=round(r["final"]), 盈利=round(r["profit"]),
                         XIRR=round(r["xirr"]*100, 2), TWR=round(r["twr"]*100, 2), MDD=round(r["mdd"]*100, 1),
                         Calmar=round(r["calmar"], 2), 卖出=r["n_exit"]))
    p(pd.DataFrame(rows).to_string(index=False))

p("\n## Plan E 交易事件（2016-09 起）")
for e in run(E, start="2016-09-30", **PLAN_E)["events"]:
    p(f"  {e[0].date()} {e[1]:<8} 主S={e[2]:5.1f}  指数={e[3]:.0f}")

p("\n## Plan E 邻域（确认窗口 无/5/7/10 × 减仓区 20/25/30 × 恢复 40/50/60 × 回补 60/120/250 天），2016-09 起")
res = []
for cf, z, rs, td in itertools.product([0, 5, 7, 10], [20, 25, 30], [40, 50, 60], [60, 120, 250]):
    r = run(build(cf), start="2016-09-30", sell_fn=make_sell_fn(z, 4), resume_thr=rs, reentry="tranche",
            tranche_days=td, dca_while_waiting=True, exit_col="S_exit")
    res.append((cf, r["xirr"]*100, r["mdd"]*100))
a = pd.DataFrame(res, columns=["确认", "XIRR", "MDD"])
p(a.groupby("确认").agg(XIRR最小=("XIRR", "min"), XIRR中位=("XIRR", "median"), XIRR最大=("XIRR", "max"),
                         MDD最差=("MDD", "min"), MDD中位=("MDD", "median")).round(2).to_string())
q = np.percentile(a.XIRR, [0, 10, 50, 90, 100]).round(2)
p(f"全部108组: XIRR 最小/P10/中位/P90/最大 = {q}；MDD 最差 {a.MDD.min():.1f}%")

last = E.iloc[-1]
p(f"\n## 截至 {E.index[-1].date()}：主S={last.S:.1f}  滚动7年S={roll[7].iloc[-1]:.1f}  S_exit={last.S_exit:.1f}  U8={last.U:.3f}")
x = min(max((last.S - 30) / 70, 0), 1); p(f"次日定投额度 = 250×{x:.3f}^2.5 = {250*x**2.5:.1f} 元")
open("results_final.txt", "w").write("\n".join(OUT))
