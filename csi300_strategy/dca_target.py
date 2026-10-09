"""
目标仓位引导的每日定投（第二个、也是最后一个检验的设计；不再继续调整）

由来：smart_dca.py（只买不卖的估值加权定投）预先登记的方案没有跑赢普通定投。
原因是 ERP-Merton 的价值主要来自"高估时卖出"，只买不卖拿不到。
因此直接沿用已验证的 ERP-Merton 目标仓位 w*（γ=2，公式不变），只把资金流改成每日定投：

  每天流入 1 份资金：
    若 当前股票占比 < w*：这 1 份全部买沪深300
    否则：这 1 份放入债券/货币（备用金）
  每月最后一个交易日复核（下一交易日执行）：
    A 只买不卖版：若股票占比 < w* − 10pp，用备用金买到 w*
    B 带止盈版：  另外若股票占比 > w* + 10pp，卖出降到 w*
  价值陷阱修正：两种 ERP 都跑（原始 1/PE；修正版同 smart_dca.py）
  备用金收益：10年国债票息（与 ERP-Merton 一致）和 0 两种都报
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
import erp_merton as em
import smart_dca as sd

COST = 0.0005


def target(df, trap):
    _, erp_adj = sd.signals(df, trap=trap)
    vol = df["ret"].expanding(min_periods=250).std() * np.sqrt(252)
    return (erp_adj / (2 * vol ** 2)).clip(0, 1)


def run(df, w_t, start, end=None, sell=True, carry=True, plain=False):
    d = df[start:end]
    w = w_t.shift(1).reindex(d.index).values  # 昨日收盘信号
    px, dy = d["close"].values, (d["dy"] / 100 / 252).values
    rf = (d["y10"] / 100 / 252).values if carry else np.zeros(len(d))
    m = d.index.to_period("M")
    month_first = np.r_[True, m[1:] != m[:-1]]  # 月末信号 -> 下月首个交易日执行
    eq = cash = 0.0
    wealth = np.empty(len(d))
    for i in range(len(d)):
        eq *= (px[i] / px[i - 1] if i else 1) * (1 + dy[i])
        cash *= 1 + rf[i]
        if plain:
            eq += 1 - COST
        else:
            tot = eq + cash + 1
            if eq / tot < w[i]:
                eq += 1 - COST
            else:
                cash += 1
            if month_first[i] and i:
                tot = eq + cash
                gap = w[i] * tot - eq
                if gap > 0.10 * tot or (sell and gap < -0.10 * tot):
                    eq += gap - COST * abs(gap)
                    cash -= gap
        wealth[i] = eq + cash
    return pd.Series(wealth, d.index)


def stats(wealth, d):
    inv = np.arange(1, len(wealth) + 1)
    ratio = wealth.values / inv
    dd = (ratio / np.maximum.accumulate(ratio) - 1).min()
    return dict(终值=wealth.iloc[-1], 收益率=wealth.iloc[-1] / len(wealth) - 1,
                XIRR=sd.xirr(len(wealth), wealth.iloc[-1], d.index), 最大回撤=dd)


def main():
    em.DATA = sys.argv[1] if len(sys.argv) > 1 else "."
    df = em.load()
    out = []
    P = lambda *a: (print(*a), out.append(" ".join(map(str, a))))
    wt_raw, wt_trap = target(df, False), target(df, True)
    start = wt_trap.dropna().index[1]
    d = df[start:]
    base = run(df, wt_raw, start, plain=True)
    res = {"普通每日定投": base}
    for trap, wt in [("原始ERP", wt_raw), ("陷阱修正ERP", wt_trap)]:
        for sell in [False, True]:
            for carry in [True, False]:
                res[f"{'B带止盈' if sell else 'A只买'}·{trap}·备用金{'计息' if carry else '不计息'}"] = \
                    run(df, wt, start, sell=sell, carry=carry)
    tab = pd.DataFrame({k: stats(v, d) for k, v in res.items()}).T
    P(f"区间 {start.date()} ~ {df.index[-1].date()}，每日投入 1 份，共 {len(d)} 份")
    P(tab.to_string(float_format=lambda x: f"{x:.3f}"))

    P("\n滚动起点（每季度一个起点）：主推方案 B带止盈·原始ERP·计息 vs 普通定投")
    for name, wt in [("原始ERP", wt_raw), ("陷阱修正ERP", wt_trap)]:
        for yrs in [3, 5]:
            diffs, dds = [], []
            for s0 in pd.date_range(start, df.index[-1] - pd.DateOffset(years=yrs), freq="QS"):
                s0 = df.index[df.index >= s0][0]
                e0 = df.index[df.index <= s0 + pd.DateOffset(years=yrs)][-1]
                a, b = run(df, wt, s0, e0), run(df, wt, s0, e0, plain=True)
                diffs.append(a.iloc[-1] / b.iloc[-1] - 1)
                dds.append(stats(a, df[s0:e0])["最大回撤"] - stats(b, df[s0:e0])["最大回撤"])
            diffs = np.array(diffs)
            P(f"  {name} {yrs}年: {len(diffs)}个起点, 终值更高 {(diffs > 0).mean():.0%}, 中位数 {np.median(diffs):+.1%}, "
              f"最差 {diffs.min():+.1%}; 回撤更小 {(np.array(dds) > 0).mean():.0%}")

    for a, b, lab in [("2015-01-01", "2016-12-31", "2015-16 泡沫+股灾"), ("2021-01-01", "2024-09-23", "2021-24 泡沫+陷阱期")]:
        x = {k: run(df, wt, a, b, sell=True) for k, wt in [("原始", wt_raw), ("修正", wt_trap)]}
        x["普通"] = run(df, wt_raw, a, b, plain=True)
        P(f"  {lab}: 期末资产/投入 " + ", ".join(f"{k} {v.iloc[-1]/len(v):.3f}" for k, v in x.items()) +
          "；最大回撤 " + ", ".join(f"{k} {stats(v, df[a:b])['最大回撤']:.1%}" for k, v in x.items()))

    rng = np.random.default_rng(0)
    v = wt_raw.dropna()
    real = res["B带止盈·原始ERP·备用金计息"].iloc[-1] / base.iloc[-1] - 1
    sims = []
    for _ in range(200):
        k = rng.integers(250, len(v) - 250)
        sims.append(run(df, pd.Series(np.roll(v.values, k), v.index).reindex(df.index), start).iloc[-1] / base.iloc[-1] - 1)
    P(f"\n安慰剂(目标仓位序列随机平移200次)：真实 {real:+.1%}，随机中位数 {np.median(sims):+.1%}，"
      f"p={np.mean(np.array(sims) >= real):.3f}")
    P(f"\n最新目标仓位 w*: 原始 {wt_raw.iloc[-1]:.0%}，陷阱修正 {wt_trap.iloc[-1]:.0%}")
    open("dca_target_results.txt", "w").write("\n".join(out))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    inv = np.arange(1, len(d) + 1)
    fig, ax = plt.subplots(figsize=(11, 5))
    for k, c, ls in [("普通每日定投", "#7f8c8d", "-"), ("B带止盈·原始ERP·备用金计息", "#c0392b", "-"),
                     ("B带止盈·陷阱修正ERP·备用金计息", "#8e44ad", "--"), ("A只买·原始ERP·备用金计息", "#e67e22", ":")]:
        lab = {"普通每日定投": "Plain daily DCA", "B带止盈·原始ERP·备用金计息": "DCA + target weight + take-profit",
               "B带止盈·陷阱修正ERP·备用金计息": "same, trap-filtered ERP",
               "A只买·原始ERP·备用金计息": "DCA + target weight, buy-only"}[k]
        ax.plot(d.index, res[k].values / inv, color=c, ls=ls, label=lab)
    ax.axhline(1, color="k", lw=.5); ax.set_ylabel("Wealth / cash contributed"); ax.legend(); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig("dca_target_nav.png", dpi=110)


if __name__ == "__main__":
    main()
