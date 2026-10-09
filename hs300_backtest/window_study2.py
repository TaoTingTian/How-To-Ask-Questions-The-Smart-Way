"""百分位口径对照（第二轮）：
- 扩张窗口·年度更新：预热 5 年；之后参照集 = [数据起点, 最近一个"起点+k年"周年日)，每满 1 年才把这一年并入参照集；
  当日值对参照集排名（参照集在一年内冻结）
- 扩张窗口·日度更新（对照）：参照集 = 起点 ~ 当日，预热 5 年
- 滚动窗口 N = 5 / 7 / 10 年：参照集 = [t−N年, t]，预热 N 年（窗口满长度才交易）
每种口径跑 Plan C / Plan D / 永不清仓；另在共同起点上比较。
"""
import numpy as np, pandas as pd
from engine import load_data, add_signals, set_ma, run
from plan_d import PLAN_D, ENS8

OUT = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); OUT.append(s)


def annual_expanding_pct(s, warmup=5, step=1):
    idx = s.index; v = s.values; out = np.full(len(v), np.nan)
    t0 = idx[0]
    for i in range(len(v)):
        k = 0
        while t0 + pd.DateOffset(years=k + step) <= idx[i]:
            k += step
        if k < warmup:
            continue
        ref = v[idx < t0 + pd.DateOffset(years=k)]
        out[i] = ((ref < v[i]).sum() + 0.5 * (ref == v[i]).sum()) / len(ref) * 100
    return pd.Series(out, index=idx)


def annual_signals(raw):
    df = raw.copy()
    df["pb_pct"] = annual_expanding_pct(df["pb"])
    df["dy_pct"] = annual_expanding_pct(df["dividend_yield"])
    df["erp_pct"] = annual_expanding_pct(df["erp"])
    df["S"] = ((100 - df["pb_pct"]) + df["dy_pct"] + df["erp_pct"]) / 3
    return set_ma(df, (40, 80, 160))


if __name__ == "__main__":
    raw = load_data()
    sig = {
        "扩张·年度更新(预热5年)": annual_signals(raw),
        "扩张·日度更新(预热5年)": add_signals(raw, years=100, min_n=1, warmup_years=5),
        "滚动5年": add_signals(raw, years=5, min_n=1, warmup_years=5),
        "滚动7年": add_signals(raw, years=7, min_n=1, warmup_years=7),
        "滚动10年": add_signals(raw, years=10, min_n=1, warmup_years=10),
    }
    starts = {k: d["S"].first_valid_index() for k, d in sig.items()}

    p("## 1. S 的分布（各口径自身有效期内）")
    rows = []
    for k, d in sig.items():
        S = d["S"].dropna()
        rows.append(dict(口径=k, 首个有效日=S.index[0].date(), 均值=round(S.mean(), 1), 标准差=round(S.std(), 1),
                         日均波动=round(S.diff().abs().mean(), 2), **{"S<25": f"{(S<25).mean():.0%}",
                         "S>58": f"{(S>58).mean():.0%}", "S≤30停投": f"{(S<=30).mean():.0%}"}))
    p(pd.DataFrame(rows).to_string(index=False))

    def table(title, start_of):
        p(f"\n## {title}")
        rows = []
        for k, d in sig.items():
            st = start_of(k)
            for name, r in [("Plan C", run(d, start=st)), ("Plan D", run(set_ma(d, ENS8), start=st, **PLAN_D)),
                            ("永不清仓", run(d, start=st, tiers=()))]:
                rows.append(dict(口径=k, 起点=st.date(), 方案=name, 本金=round(r["inflow"]), 期末=round(r["final"]),
                                 XIRR=round(r["xirr"]*100, 2), MDD=round(r["mdd"]*100, 1), Calmar=round(r["calmar"], 2), 卖出=r["n_exit"]))
        p(pd.DataFrame(rows).to_string(index=False))

    c1 = max(starts[k] for k in sig if k != "滚动10年")
    c2 = starts["滚动10年"]
    table("2. 各口径自身最早有效日起", lambda k: starts[k])
    table(f"3. 共同起点 A：{c1.date()}（滚动7年可用起，不含滚动10年的比较需看此表）", lambda k: max(c1, starts[k]))
    table(f"4. 共同起点 B：{c2.date()}（全部5种口径可比，但只有5年）", lambda k: c2)

    p("\n## 5. Plan C 清仓/回补事件")
    for k, d in sig.items():
        ev = run(d)["events"]
        p(f"{k}: " + ("；".join(f"{e[0].date()} {'清仓' if e[1].startswith('卖出') else '回补'}(S={e[2]:.0f})" for e in ev) or "无"))

    p("\n## 6. 分段累计定投额（元，按公式额度）")
    for k, d in sig.items():
        a = 250 * ((d["S"].shift(1) - 30) / 70).clip(0, 1) ** 2.5
        seg = lambda x, y: f"{round(a.loc[x:y].sum()):>7}"
        p(f"{k:<16} 2016-10~2017-12:{seg('2016-10-01','2017-12-31')}  2018-10~2019-03:{seg('2018-10-01','2019-03-31')}  "
          f"2022-04~2024-09:{seg('2022-04-01','2024-09-30')}  2025-01~2026-09:{seg('2025-01-01','2026-09-30')}")

    p("\n## 7. 截至 2026-09-30 的信号与状态")
    for k, d in sig.items():
        last = d.iloc[-1]; ev = run(d)["events"]; evd = run(set_ma(d, ENS8), **PLAN_D)["events"]
        p(f"{k:<16} S={last.S:5.1f}  PB分位={last.pb_pct:5.1f} 股息分位={last.dy_pct:5.1f} ERP分位={last.erp_pct:5.1f}  "
          f"PlanC末次:{ev[-1][0].date() if ev else '-'} {ev[-1][1] if ev else ''}  PlanD末次:{evd[-1][0].date() if evd else '-'} {evd[-1][1] if evd else ''}")

    open("results_window_study2.txt", "w").write("\n".join(OUT))
