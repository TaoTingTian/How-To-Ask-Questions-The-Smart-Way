"""Plan D（修改版）——规则在运行回测前预先写定，取整数参数，不按回测结果再调。

与 Plan C 的差异（全部出于降低过拟合，而非提高历史收益）：
1. 趋势：MA 20/40/60/80/120/160/200/250 八条均线的集成 U8，替代 40/80/160 三条
   （单均线扫描显示 XIRR 对窗口锯齿状敏感，集成=对窗口取平均，不押注任一窗口）
2. 卖出：S<25 时，目标卖出比例 = floor((1-U8)*4)/4，即 0/25/50/75/100% 五档、只减不加
   （把一次全有全无的决策拆成多次小决策，单次判断错误的代价减小）
3. 回补：S>50 起，资金池分 120 个交易日（约半年）等额回补，替代 S>58 一次性回补
   （58 是回测中最敏感的参数；分批回补把对单一阈值/单一日期的依赖摊平）
4. 定投不因"等待"而停：只要公式额度>0 就照常买（去掉一个状态，规则更少）
5. 估值分 S、定投公式（s0=30、指数2.5、上限250）保持不变——它们的邻域本来就平滑
"""
import itertools
import math
import numpy as np
import pandas as pd
from engine import load_data, add_signals, set_ma, run, fmt

ENS8 = (20, 40, 60, 80, 120, 160, 200, 250)


def make_sell_fn(zone=25, steps=4):
    def f(s, u):
        if s >= zone:
            return 0.0
        return math.floor((1 - u) * steps + 1e-9) / steps
    return f


PLAN_D = dict(sell_fn=make_sell_fn(25, 4), resume_thr=50, reentry="tranche", tranche_days=120,
              dca_while_waiting=True)

if __name__ == "__main__":
    OUT = []

    def p(*a):
        s = " ".join(str(x) for x in a); print(s); OUT.append(s)

    base = add_signals(load_data())
    dD = set_ma(base, ENS8)

    p("## Plan D 主结果")
    for nav in ["close", "nav_tr"]:
        rc, rd = run(base, nav=nav), run(dD, nav=nav, **PLAN_D)
        p(f"[{nav}] Plan C:", fmt(rc)); p(f"[{nav}] Plan D:", fmt(rd))
    rd = run(dD, **PLAN_D)
    p("\nPlan D 交易事件：")
    for e in rd["events"]:
        p(f"  {e[0].date()} {e[1]:<8} S={e[2]:5.1f} 指数={e[3]:.0f}")

    # ---------------- 邻域分布
    p("\n## 参数邻域分布对比（每个方案在其参数邻域内全部组合的 XIRR / MDD 分布）")
    ma_sets = [(40, 80, 160), (60, 120, 240), (80, 160, 320), (30, 60, 120), (50, 100, 200)]
    ma_cache = {m: set_ma(base, m) for m in ma_sets}
    rc_list = []
    for sell, res, m, ut in itertools.product([20, 25, 30], [50, 55, 58, 60, 65], ma_sets, [0, 1 / 3, 2 / 3]):
        r = run(ma_cache[m], tiers=((sell, 1.0),), resume_thr=res, u_thr=ut)
        rc_list.append((r["xirr"], r["mdd"]))
    ens = {"8条(20..250)": ENS8, "6条(60..250)": (60, 80, 120, 160, 200, 250), "6条(20..160)": (20, 40, 60, 80, 120, 160)}
    ens_cache = {k: set_ma(base, v) for k, v in ens.items()}
    rd_list = []
    for zone, res, td, ek, st in itertools.product([20, 25, 30], [40, 45, 50, 55, 60], [60, 120, 250], ens, [2, 4]):
        r = run(ens_cache[ek], sell_fn=make_sell_fn(zone, st), resume_thr=res, reentry="tranche",
                tranche_days=td, dca_while_waiting=True)
        rd_list.append((r["xirr"], r["mdd"]))
    rn = run(base, tiers=())
    for name, L in [("Plan C 邻域(225组)", rc_list), ("Plan D 邻域(270组)", rd_list)]:
        a = np.array(L) * 100
        q = lambda c: np.percentile(a[:, c], [0, 10, 50, 90, 100]).round(2)
        p(f"{name}: XIRR 最小/P10/中位/P90/最大 = {q(0)}  ;  MDD = {q(1)}  ;  "
          f"XIRR<永不清仓({rn['xirr']*100:.2f})的比例 {np.mean(a[:,0] < rn['xirr']*100):.0%}")

    # ---------------- 敏感性单维
    p("\n## Plan D 单参数扰动（其余保持 Plan D）XIRR% / MDD%")
    for name, grid in [("zone", [15, 20, 25, 30, 35]), ("resume_thr", [40, 45, 50, 55, 60, 65]),
                       ("tranche_days", [20, 60, 120, 250, 500])]:
        cells = []
        for v in grid:
            kw = dict(PLAN_D)
            if name == "zone":
                kw["sell_fn"] = make_sell_fn(v, 4)
            else:
                kw[name] = v
            r = run(dD, **kw)
            cells.append(f"{v}:{r['xirr']*100:.2f}/{r['mdd']*100:.1f}")
        p(f"{name:<13}", "  ".join(cells))

    # ---------------- 事件归因与子区间
    p("\n## 事件归因（相对永不清仓 XIRR pp）")
    for name, yrs in [("仅2015", {2015}), ("仅2017-18", {2017, 2018}), ("仅2020-21", {2020, 2021})]:
        c = run(base, exit_years=yrs)["xirr"] - rn["xirr"]
        d = run(dD, exit_years=yrs, **PLAN_D)["xirr"] - rn["xirr"]
        p(f"{name:<9} Plan C {c*100:+.2f}  Plan D {d*100:+.2f}")
    p("\n## 子区间")
    for a, b in [("2013-11-07", "2019-12-31"), ("2020-01-01", "2026-09-30")]:
        p(f"{a}~{b}  C: {fmt(run(base, start=a, end=b))}")
        p(f"{'':23}  D: {fmt(run(dD, start=a, end=b, **PLAN_D))}")
        p(f"{'':23}  N: {fmt(run(base, start=a, end=b, tiers=()))}")

    # ---------------- 2005-2011 缺失数据压力测试（解析式，不编造日数据）
    p("\n## 缺失 2005-04~2011-09 历史对 S 的影响（解析压力测试）")
    p("假设补入 N 个更早交易日，其中比卖出日'更贵'的比例为 f（三项指标同取 f），重算卖出日 S：")
    exits = [e[0] for e in run(base)["events"] if e[1].startswith("卖出")]
    for dt in exits:
        i = base.index.get_loc(dt) - 1          # T-1 信号日
        row = base.iloc[i]
        n_old = int(((base.index > base.index[i] - pd.DateOffset(years=15)) & (base.index <= base.index[i])).sum())
        lo = base.index[i] - pd.DateOffset(years=15)
        N = int(np.busday_count(max(lo, pd.Timestamp("2005-04-08")).date(), pd.Timestamp("2011-09-30").date()) * 0.95)
        cells = []
        for f in [0.3, 0.5, 0.7]:
            pb = (row.pb_pct * n_old + (1 - f) * N * 100) / (n_old + N)
            dy = (row.dy_pct * n_old + f * N * 100) / (n_old + N)
            ep = (row.erp_pct * n_old + f * N * 100) / (n_old + N)
            cells.append(f"f={f}: S={((100 - pb) + dy + ep) / 3:.1f}")
        p(f"  {base.index[i].date()} 原S={row.S:.1f}（窗口{n_old}样本, 补入≈{N}）  " + "  ".join(cells))

    open("results_plan_d.txt", "w").write("\n".join(OUT))
