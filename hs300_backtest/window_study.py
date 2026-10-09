"""百分位口径对照：扩张窗口（5年预热） vs 滚动窗口 N=3/5/7 年（预热 = N 年，保证窗口满长度）

每种口径分别跑 Plan C / Plan D / 永不清仓（同公式估值定投），
并在共同起点（最晚的预热结束日）上再比一次，消除起点不同的影响。
"""
import numpy as np, pandas as pd
from engine import load_data, add_signals, set_ma, run, fmt
from plan_d import PLAN_D, ENS8

OUT = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); OUT.append(s)

raw = load_data()
MODES = {
    "扩张窗口(预热5年)": dict(years=100, min_n=1, warmup_years=5),
    "滚动3年": dict(years=3, min_n=1, warmup_years=3),
    "滚动5年": dict(years=5, min_n=1, warmup_years=5),
    "滚动7年": dict(years=7, min_n=1, warmup_years=7),
    "原规则(15年,≥504样本)": dict(years=15, min_n=504),
}
sig = {k: add_signals(raw, **v) for k, v in MODES.items()}
common = max(d["S"].first_valid_index() for d in sig.values())

p("## 1. S 的分布与信号状态（各口径自身有效期内）")
rows = []
for k, d in sig.items():
    S = d["S"].dropna()
    rows.append(dict(口径=k, 首个有效日=S.index[0].date(), 均值=round(S.mean(), 1), 标准差=round(S.std(), 1),
                     日均波动=round(S.diff().abs().mean(), 2),
                     **{"S<25占比": f"{(S < 25).mean():.0%}", "S>58占比": f"{(S > 58).mean():.0%}", "S≤30停投占比": f"{(S <= 30).mean():.0%}"}))
p(pd.DataFrame(rows).to_string(index=False))

p("\n共同区间内各口径 S 的相关系数：")
C = pd.DataFrame({k: d["S"] for k, d in sig.items()}).loc[common:].corr().round(2)
p(C.to_string())

def block(start_label, start):
    p(f"\n## {start_label}")
    rows = []
    for k, d in sig.items():
        st = start or d["S"].first_valid_index()
        for name, r in [("Plan C", run(d, start=st)),
                        ("Plan D", run(set_ma(d, ENS8), start=st, **PLAN_D)),
                        ("永不清仓", run(d, start=st, tiers=()))]:
            rows.append(dict(口径=k, 起点=st.date(), 方案=name, 本金=round(r["inflow"]), XIRR=round(r["xirr"] * 100, 2),
                             MDD=round(r["mdd"] * 100, 1), Calmar=round(r["calmar"], 2), 卖出=r["n_exit"]))
    p(pd.DataFrame(rows).to_string(index=False))

block("2. 各口径从自身最早有效日起回测", None)
block(f"3. 共同起点 {common.date()} 起回测（口径间可直接比较）", common)

p("\n## 4. Plan C 各口径的清仓/回补事件")
for k, d in sig.items():
    ev = run(d)["events"]
    p(f"{k}: " + ("；".join(f"{e[0].date()} {'清仓' if e[1].startswith('卖出') else '回补'}(S={e[2]:.0f})" for e in ev) or "无"))

p("\n## 5. 低估期买入力度：S>30 时的平均日定投额（元），以及2018-10~2019-03、2022-04~2024-09 两段低估期的累计投入")
for k, d in sig.items():
    S = d["S"].shift(1)
    amt = 250 * ((S - 30) / 70).clip(0, 1) ** 2.5
    seg = lambda a, b: round(amt.loc[a:b].sum())
    p(f"{k:<22} 2018-10~2019-03: {seg('2018-10-01','2019-03-31'):>6}  2022-04~2024-09: {seg('2022-04-01','2024-09-30'):>6}  2025-01~2026-09: {seg('2025-01-01','2026-09-30'):>6}")

open("results_window_study.txt", "w").write("\n".join(OUT))
