"""
沪深300 估值加权每日定投 + 价值陷阱修正（Smart-DCA）

=== 预先登记的设计（写于运行回测之前；主方案不因结果修改） ===
资金：每个交易日固定流入 1 份资金（工资），先进入「备用金」。
每日买入额 = min(备用金, 1 × 倍数_t)，只买不卖。备用金在主方案中不计利息（保守）。

倍数_t = clip( 2 × ERP调整_t / (γ σ_t²), 0, 3 )，γ = 2
  —— 即上一版的 Merton 仓位 k 乘以 2：k = 50%（中性）时每天投 1 份，
     越便宜投得越多（上限 3 份），越贵投得越少（可降到 0，钱留在备用金）。

价值陷阱修正（两条，均无可调参数）：
  E_ttm  = 指数点位 / PE_TTM               （隐含每股盈利）
  g      = E_ttm 相对一年前的增速
  ① 盈利下滑外推：若 g < 0，假设下滑再持续一年：E_fwd = E_ttm × (1 + g)
  ② 周期高点修正：E_cons = min(E_fwd, 过去 3 年 E_ttm 的平均值)
  ERP调整 = E_cons / 点位 − 10年国债收益率
  ——"看起来便宜"必须经得起"盈利再跌一年"和"不用景气高点的盈利"两道检验。

执行：t 日收盘后的数据决定 t+1 日的买入额，t+1 日收盘价成交，成本 0.05%。
股息：持有份额按股息率/252 每日再投资（近似全收益）。

基准：普通每日定投（每天投 1 份，同样的资金流）。
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
import erp_merton as em

COST = 0.0005


def signals(df, gamma=2.0, trap=True, m_max=3.0):
    E = df["close"] / df["pe"]
    vol = df["ret"].expanding(min_periods=250).std() * np.sqrt(252)
    if trap:
        g = E / E.shift(250) - 1
        e_fwd = E * (1 + g.clip(upper=0).fillna(0))
        e_avg = E.rolling(756, min_periods=250).mean()
        e_cons = np.minimum(e_fwd, e_avg)
    else:
        e_cons = E
    erp_adj = e_cons / df["close"] - df["y10"] / 100
    mult = (2 * erp_adj / (gamma * vol ** 2)).clip(0, m_max)
    return mult, erp_adj


def run(df, mult, start, end=None, lag=1, carry=False, plain=False):
    d = df[start:end]
    m = mult.shift(lag).reindex(d.index).values
    px = d["close"].values
    dy = (d["dy"] / 100 / 252).values
    rf = (d["y10"] / 100 / 252).values if carry else np.zeros(len(d))
    shares = cash = spent = 0.0
    wealth = np.empty(len(d))
    for i in range(len(d)):
        shares *= 1 + dy[i]
        cash = cash * (1 + rf[i]) + 1.0
        amt = 1.0 if plain else (0.0 if np.isnan(m[i]) else min(cash, m[i]))
        if amt > 0:
            shares += amt * (1 - COST) / px[i]
            cash -= amt
            spent += amt
        wealth[i] = shares * px[i] + cash
    return dict(wealth=pd.Series(wealth, d.index), final=wealth[-1], cash=cash, spent=spent,
                avg_cost=spent / shares if shares else np.nan, n=len(d), shares=shares)


def xirr(n_days, final, dates):
    t = np.array([(x - dates[0]).days / 365.25 for x in dates])
    T = t[-1]
    f = lambda r: np.sum((1 + r) ** (T - t)) - final
    lo, hi = -0.5, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return mid


def summarize(res, df_slice):
    w = res["wealth"]
    inv = np.arange(1, len(w) + 1)
    dd = ((w / inv) / (w / inv).cummax() - 1).min()  # 以"资产/累计投入"衡量回撤
    return dict(终值=res["final"], 累计投入=res["n"], 收益率=res["final"] / res["n"] - 1,
                XIRR=xirr(res["n"], res["final"], df_slice.index), 平均成本=res["avg_cost"],
                期末备用金占比=res["cash"] / res["final"], 最大回撤=dd)


def main():
    em.DATA = sys.argv[1] if len(sys.argv) > 1 else "."
    df = em.load()
    out = []
    P = lambda *a: (print(*a), out.append(" ".join(map(str, a))))

    mult, erp_adj = signals(df)
    mult_raw, _ = signals(df, trap=False)
    start = mult.dropna().index[1]
    sl = df[start:]
    base = run(df, mult, start, plain=True)
    smart = run(df, mult, start)
    raw = run(df, mult_raw, start)
    tab = pd.DataFrame({"普通每日定投": summarize(base, sl), "估值定投+陷阱修正(主)": summarize(smart, sl),
                        "估值定投(无陷阱修正)": summarize(raw, sl),
                        "主方案+备用金计息": summarize(run(df, mult, start, carry=True), sl)}).T
    P(f"区间 {start.date()} ~ {df.index[-1].date()}，每日投入 1 份，共 {len(sl)} 份")
    P(tab.to_string(float_format=lambda x: f"{x:.3f}"))

    # 价值陷阱诊断：原始 ERP 看起来便宜（倍数≥1.2）时，盈利下滑 vs 增长，未来 1 年收益
    E = df.close / df.pe
    g = E / E.shift(250) - 1
    fwd = df.close.shift(-250) / df.close - 1
    cheap = mult_raw >= 1.2
    P("\n诊断：原始估值看起来便宜(倍数≥1.2)时的未来1年指数涨幅")
    for lab, mask in [("盈利同比下滑", cheap & (g < 0)), ("盈利同比增长", cheap & (g >= 0))]:
        x = fwd[mask].dropna()
        P(f"  {lab}: 天数 {len(x)}, 未来1年涨幅中位数 {x.median():.3f}, 下跌概率 {(x < 0).mean():.0%}")

    # 2022-2024 陷阱期
    a, b = "2022-01-01", "2024-09-23"
    for lab, mm in [("有修正", mult), ("无修正", mult_raw)]:
        r = run(df, mm, a, b)
        P(f"  2022-01~2024-09 陷阱期 {lab}: 投入 {r['spent']:.0f}/{r['n']} 份，平均成本 {r['avg_cost']:.0f}，"
          f"期末资产/投入 {r['final']/r['n']:.3f}")
    rb = run(df, mult, a, b, plain=True)
    P(f"  同期普通定投: 平均成本 {rb['avg_cost']:.0f}，期末资产/投入 {rb['final']/rb['n']:.3f}")

    # 滚动起点：每季度一个起点，持有 3 年 / 5 年
    P("\n滚动起点（每季度一个起点）：估值定投 vs 普通定投")
    for yrs in [3, 5]:
        wins, diffs = [], []
        for s0 in pd.date_range(start, df.index[-1] - pd.DateOffset(years=yrs), freq="QS"):
            s0 = df.index[df.index >= s0][0]
            e0 = df.index[df.index <= s0 + pd.DateOffset(years=yrs)][-1]
            r1, r0 = run(df, mult, s0, e0), run(df, mult, s0, e0, plain=True)
            diffs.append(r1["final"] / r0["final"] - 1)
        diffs = np.array(diffs)
        P(f"  {yrs}年: {len(diffs)} 个起点, 终值更高的比例 {(diffs > 0).mean():.0%}, "
          f"终值差中位数 {np.median(diffs):+.1%}, 最差 {diffs.min():+.1%}, 最好 {diffs.max():+.1%}")

    # 参数网格
    rows = []
    for gamma in [1, 1.5, 2, 3, 4]:
        for m_max in [2, 3, 5]:
            for trap in [True, False]:
                mm, _ = signals(df, gamma, trap, m_max)
                for lag in [1, 5, 21]:
                    for carry in [False, True]:
                        r = run(df, mm, start, lag=lag, carry=carry)
                        rows.append(dict(gamma=gamma, m_max=m_max, trap=trap, lag=lag, carry=carry,
                                         excess=r["final"] / base["final"] - 1,
                                         cost_gap=r["avg_cost"] / base["avg_cost"] - 1))
    gdf = pd.DataFrame(rows)
    gdf.to_csv("dca_grid.csv", index=False)
    P(f"\n参数网格 {len(gdf)} 组：终值高于普通定投 {(gdf.excess > 0).mean():.0%}，"
      f"中位数 {gdf.excess.median():+.1%}；平均成本更低 {(gdf.cost_gap < 0).mean():.0%}，中位数 {gdf.cost_gap.median():+.1%}")
    P("  陷阱修正 开/关 的终值超额中位数：" +
      ", ".join(f"{'开' if k else '关'} {v:+.1%}" for k, v in gdf.groupby("trap").excess.median().items()))
    paired = gdf.pivot_table(index=["gamma", "m_max", "lag", "carry"], columns="trap", values="excess")
    P(f"  同参数下 开修正 优于 关修正 的比例 {(paired[True] > paired[False]).mean():.0%}")

    # 安慰剂
    rng = np.random.default_rng(0)
    v = mult.dropna()
    sims = []
    for _ in range(300):
        k = rng.integers(250, len(v) - 250)
        sh = pd.Series(np.roll(v.values, k), v.index).reindex(df.index)
        sims.append(run(df, sh, start)["final"] / base["final"] - 1)
    real = smart["final"] / base["final"] - 1
    P(f"\n安慰剂(倍数序列随机平移300次)：真实终值超额 {real:+.1%}，随机中位数 {np.median(sims):+.1%}，"
      f"p={np.mean(np.array(sims) >= real):.3f}")

    # 当前信号
    last = df.index[-1]
    P(f"\n最新 {last.date()}: E_ttm 同比 {g.iloc[-1]:+.1%}，调整后ERP {erp_adj.iloc[-1]:.2%}"
      f"（原始 {df.erp.iloc[-1]:.2%}），下一交易日定投倍数 {mult.iloc[-1]:.2f}")

    open("dca_results.txt", "w").write("\n".join(out))
    pd.DataFrame({"mult": mult, "mult_raw": mult_raw, "erp_adj": erp_adj, "erp_raw": df.erp,
                  "eps_yoy": g}).to_csv("dca_signal.csv")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    inv = np.arange(1, len(sl) + 1)
    fig, ax = plt.subplots(3, 1, figsize=(11, 10), sharex=True, gridspec_kw=dict(height_ratios=[3, 1.6, 1.6]))
    ax[0].plot(sl.index, base["wealth"] / inv, label="Plain daily DCA", color="#7f8c8d")
    ax[0].plot(sl.index, smart["wealth"] / inv, label="Valuation DCA + trap filter", color="#c0392b")
    ax[0].plot(sl.index, raw["wealth"] / inv, label="Valuation DCA, no trap filter", color="#e67e22", ls="--", lw=1)
    ax[0].axhline(1, color="k", lw=.5); ax[0].set_ylabel("Wealth / cash contributed"); ax[0].legend(); ax[0].grid(alpha=.3)
    ax[1].plot(mult[start:], color="#c0392b", lw=.8, label="multiplier (filtered)")
    ax[1].plot(mult_raw[start:], color="#e67e22", lw=.6, alpha=.7, label="multiplier (raw)")
    ax[1].axhline(1, color="k", lw=.5); ax[1].set_ylabel("Daily buy x"); ax[1].legend(); ax[1].grid(alpha=.3)
    ax[2].plot(g[start:] * 100, color="#2980b9", lw=.8); ax[2].axhline(0, color="k", lw=.5)
    ax[2].fill_between(g[start:].index, g[start:] * 100, 0, where=g[start:] < 0, color="#c0392b", alpha=.25)
    ax[2].set_ylabel("EPS YoY %"); ax[2].grid(alpha=.3)
    fig.tight_layout(); fig.savefig("dca_nav.png", dpi=110)


if __name__ == "__main__":
    main()
