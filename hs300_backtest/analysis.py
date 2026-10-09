"""过拟合诊断：基准对照、事件归因、参数邻域、子区间、窗口敏感性"""
import itertools
import numpy as np
import pandas as pd
from engine import load_data, add_signals, set_ma, run, fmt, xirr

pd.set_option("display.width", 200)
base = add_signals(load_data())
OUT = []


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    OUT.append(s)


def row(name, r):
    return dict(方案=name, 本金=round(r["inflow"]), 期末=round(r["final"]), XIRR=round(r["xirr"] * 100, 2),
                TWR=round(r["twr"] * 100, 2), MDD=round(r["mdd"] * 100, 1), Calmar=round(r["calmar"], 2),
                卖出次数=r["n_exit"])


# ------------------------------------------------ 1. 基准
p("## 1. 基准对照（价格指数口径 / 近似全收益净值口径）")
for nav in ["close", "nav_tr"]:
    rows = [row("Plan C", run(base, nav=nav)),
            row("同公式估值定投·永不清仓", run(base, nav=nav, tiers=()))]
    # 等额日定投：与 Plan C 同起点，日额使总本金相同
    pc = run(base, nav=nav)
    n = base.loc[base["S"].first_valid_index():].shape[0] - 1
    flat = base.copy(); flat["S"] = 100.0; flat.loc[flat.index < base["S"].first_valid_index(), "S"] = np.nan
    rows.append(row("等额日定投（同总本金）", run(flat, nav=nav, tiers=(), s0=0, power=1, cap=pc["inflow"] / n)))
    p(f"\n口径={nav}\n" + pd.DataFrame(rows).to_string(index=False))

# ------------------------------------------------ 2. 事件归因
p("\n## 2. 单次清仓事件归因（只允许某一年份区间触发清仓）")
rows = []
none = run(base, tiers=())
for name, yrs in [("仅2015", {2015}), ("仅2017-18", {2017, 2018}), ("仅2020-21", {2020, 2021}), ("全部", None)]:
    r = run(base, exit_years=yrs)
    rows.append(dict(事件=name, XIRR=round(r["xirr"] * 100, 2), 相对永不清仓pp=round((r["xirr"] - none["xirr"]) * 100, 2),
                     MDD=round(r["mdd"] * 100, 1)))
p(pd.DataFrame(rows).to_string(index=False))

# ------------------------------------------------ 3. 参数邻域
def grid(xs, ys, fx, fy, metric="xirr", **fixed):
    tab = pd.DataFrame(index=ys, columns=xs, dtype=float)
    for x, y in itertools.product(xs, ys):
        kw = {**fixed, **fx(x), **fy(y)}
        df = kw.pop("_df", base)
        r = run(df, **kw)
        tab.loc[y, x] = round(r[metric] * (100 if metric in ("xirr", "mdd", "twr") else 1), 2)
    return tab


p("\n## 3a. 卖出阈值 × 恢复阈值（XIRR %）")
sells = [15, 20, 25, 30, 35]
resumes = [45, 50, 55, 58, 60, 65, 70]
g = grid(sells, resumes, lambda x: dict(tiers=((x, 1.0),)), lambda y: dict(resume_thr=y))
p(g.to_string())
p("\n## 3b. 同上（最大回撤 %）")
p(grid(sells, resumes, lambda x: dict(tiers=((x, 1.0),)), lambda y: dict(resume_thr=y), metric="mdd").to_string())

p("\n## 3c. 均线窗口组 × U阈值（XIRR %），复核规则书第二节")
ma_sets = {"40/80/160": (40, 80, 160), "60/120/240": (60, 120, 240), "80/160/320": (80, 160, 320),
           "30/60/120": (30, 60, 120), "50/100/200": (50, 100, 200)}
ma_df = {k: set_ma(base, v) for k, v in ma_sets.items()}
tab = pd.DataFrame(index=list(ma_sets), columns=["U≤0", "U≤1/3", "U≤2/3"], dtype=float)
for k in ma_sets:
    for c, ut in zip(tab.columns, [0, 1 / 3, 2 / 3]):
        tab.loc[k, c] = round(run(ma_df[k], u_thr=ut)["xirr"] * 100, 2)
p(tab.to_string())
p("\n单均线 MA(k) 扫描（U≤0 即跌破该均线）XIRR%：")
single = {k: round(run(set_ma(base, (k,)), u_thr=0)["xirr"] * 100, 2) for k in [20, 30, 40, 50, 60, 70, 80, 100, 120, 160, 200, 250]}
p(single)
p("无趋势过滤（只看 S<25）:", fmt(run(base, u_thr=1.0)))

p("\n## 3d. 定投曲线 s0 × 指数（XIRR % / 本金）")
g = grid([1, 1.5, 2, 2.5, 3, 4], [20, 25, 30, 35, 40], lambda x: dict(power=x), lambda y: dict(s0=y))
p(g.to_string())

# ------------------------------------------------ 4. 子区间
p("\n## 4. 子区间（各自独立起投）")
rows = []
for a, b in [("2013-11-07", "2019-12-31"), ("2020-01-01", "2026-09-30"), ("2016-01-01", "2026-09-30"), ("2018-07-01", "2026-09-30")]:
    for name, kw in [("Plan C", {}), ("永不清仓", dict(tiers=()))]:
        r = run(base, start=a, end=b, **kw)
        rows.append(dict(区间=f"{a}~{b}", 方案=name, XIRR=round(r["xirr"] * 100, 2), MDD=round(r["mdd"] * 100, 1), 卖出=r["n_exit"]))
p(pd.DataFrame(rows).to_string(index=False))

# ------------------------------------------------ 5. 百分位窗口
p("\n## 5. 百分位窗口/最少样本敏感性（数据始于2011-09，15年窗口实为扩张窗口）")
rows = []
for yrs, mn in [(15, 504), (15, 252), (15, 756), (10, 504), (5, 504), (3, 504)]:
    d = add_signals(load_data(), years=yrs, min_n=mn)
    r = run(d, start="2013-11-07")
    rows.append(dict(窗口年=yrs, 最少样本=mn, XIRR=round(r["xirr"] * 100, 2), MDD=round(r["mdd"] * 100, 1), 卖出=r["n_exit"],
                     卖出日=",".join(str(e[0].date()) for e in r["events"] if e[1].startswith("卖出"))))
p(pd.DataFrame(rows).to_string(index=False))

# ------------------------------------------------ 6. 补全口径
p("\n## 6. 补全口径敏感性")
for name, kw in [("价格指数, 资金池0%", {}), ("近似全收益净值, 资金池0%", dict(nav="nav_tr")),
                 ("近似全收益净值, 资金池2%", dict(nav="nav_tr", pool_rate=0.02))]:
    p(f"{name:<24}", fmt(run(base, **kw)))

open("results_diagnostics.txt", "w").write("\n".join(OUT))
