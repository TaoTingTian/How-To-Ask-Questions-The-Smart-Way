"""
沪深300 "风险溢价定仓" 策略（ERP-Merton）—— 均值回归思想，零拟合参数

=== 预先登记的设计（写于运行回测之前，运行后不再修改主方案） ===
思想：
  不问"现在的估值在历史上排第几"，而问"现在买股票，比买国债每年多赚多少，
  这份超额补偿值得承担多大的波动"。价格下跌 -> 盈利收益率 E/P 上升 ->
  超额补偿变大 -> 仓位自动上升；泡沫时相反。这就是均值回归，但锚是
  "债券收益 + 风险补偿"这个经济量，而不是一段历史分布。

公式（Merton 最优仓位）：
  w_t = clip( ERP_t / (gamma * sigma_t^2), 0, 1 )
  ERP_t   = 1/PE_TTM_t - 10年国债收益率_t          （当天已知数据）
  sigma_t = 截至 t 的扩展窗口日收益年化波动率（只用过去数据，至少 250 天）
  gamma   = 2   （教科书中"中等风险厌恶"，不从本数据估计）

执行：
  每月最后一个交易日计算信号，下一个交易日收盘成交（滞后 1 天，杜绝前视）
  仅当 |目标仓位 - 当前实际仓位| > 0.10 才调仓；单边成本 0.1%
  股票腿收益 = 指数涨跌 + 股息率/252（近似全收益）
  现金腿收益 = 10年国债收益率/252（持有到期票息近似，忽略久期损益）

检验（主方案不因检验结果而改动）：
  1) 同平均仓位的静态股债组合 —— 区分"择时价值"和"只是仓位低"
  2) 参数网格 gamma × sigma × 调仓带宽 × 执行滞后，看分布而不是最大值
  3) 子区间 & 滚动 3 年窗口胜率
  4) 安慰剂：把仓位序列循环平移（打乱与价格的时间对应），看真实结果在
     随机分布中的位置
"""
import sys
import numpy as np
import pandas as pd

DATA = sys.argv[1] if len(sys.argv) > 1 else "."
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
COST = 0.001


def load():
    import glob
    f = lambda pat: glob.glob(f"{DATA}/*{pat}*")[0]
    px = pd.read_csv(glob.glob(f"{DATA}/*20110930-20260930*")[0], encoding="utf-8-sig")
    px = px.rename(columns={px.columns[0]: "date", px.columns[1]: "close"})[["date", "close"]]
    df = px.set_index(pd.to_datetime(px["date"]))[["close"]]
    for name, pat in [("pe", "PE_TTM"), ("pb", "PB"), ("dy", "Dividend"), ("y10", "10Y")]:
        s = pd.read_csv(f(pat))
        df[name] = s.set_index(pd.to_datetime(s["date"]))["value"]
    df = df.ffill().dropna()
    df["ret"] = df["close"].pct_change().fillna(0.0)
    df["erp"] = 1 / df["pe"] - df["y10"] / 100
    return df


def target_weight(df, gamma=2.0, sigma="expanding"):
    if sigma == "expanding":
        vol = df["ret"].expanding(min_periods=250).std() * np.sqrt(252)
    else:
        vol = pd.Series(float(sigma), index=df.index)
        vol[: df.index[250]] = np.nan  # 与扩展窗口同一起点，便于比较
    return (df["erp"] / (gamma * vol ** 2)).clip(0, 1)


def backtest(df, w_target, band=0.10, lag=1, monthly=True, start=None):
    """返回每日净值、每日实际股票仓位。w_target 在信号日已知，lag 天后成交。"""
    eq_r = (df["ret"] + df["dy"] / 100 / 252).values
    cash_r = (df["y10"] / 100 / 252).values
    tgt = w_target.values
    is_sig = np.zeros(len(df), bool)
    if monthly:
        m = df.index.to_period("M")
        is_sig[:-1] = m[:-1] != m[1:]
    else:
        is_sig[:] = True
    exec_at = {}
    for i in np.where(is_sig)[0]:
        if not np.isnan(tgt[i]) and i + lag < len(df):
            exec_at[i + lag] = tgt[i]
    if start is not None:  # 基准：在指定日期以该日目标仓位建仓
        i0 = df.index.get_loc(start)
        exec_at = {k: v for k, v in exec_at.items() if k > i0}
        exec_at[i0] = tgt[i0]
    nav, w = 1.0, 0.0
    started = False
    backtest.trades = 0
    navs, ws = np.full(len(df), np.nan), np.full(len(df), np.nan)
    for i in range(len(df)):
        if started:  # 当日收益按昨日收盘后的仓位结算
            g = w * (1 + eq_r[i]) + (1 - w) * (1 + cash_r[i])
            w = w * (1 + eq_r[i]) / g
            nav *= g
        if i in exec_at:
            new = exec_at[i]
            if not started or abs(new - w) > band:
                nav *= 1 - COST * abs(new - w)
                w = new
                backtest.trades += 1
            started = True
        if started:
            navs[i], ws[i] = nav, w
    return pd.Series(navs, df.index), pd.Series(ws, df.index)


def stats(nav):
    nav = nav.dropna()
    r = nav.pct_change().dropna()
    yrs = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(252)
    mdd = (nav / nav.cummax() - 1).min()
    return dict(CAGR=cagr, Vol=vol, Sharpe=cagr / vol if vol else np.nan,
                MaxDD=mdd, Calmar=cagr / -mdd if mdd else np.nan)


def static_mix(df, w, start):
    """固定仓位 w 的股债组合，每月再平衡，从同一天开始。"""
    nav, _ = backtest(df, pd.Series(w, df.index), band=0.0, lag=0, start=start)
    return nav


def main():
    df = load()
    lines = []
    P = lambda *a: (print(*a), lines.append(" ".join(str(x) for x in a)))

    # ---------- 主方案 ----------
    tw = target_weight(df)
    nav, w = backtest(df, tw)
    turns = backtest.trades - 1  # 不计首次建仓
    start = nav.dropna().index[0]
    avg_w = w.dropna().mean()
    bh, _ = backtest(df, pd.Series(1.0, df.index), band=0, lag=0, start=start)
    mix = static_mix(df, avg_w, start)

    P(f"回测区间 {start.date()} ~ {df.index[-1].date()}，平均股票仓位 {avg_w:.2f}，调仓 {turns} 次")
    tab = pd.DataFrame({"ERP-Merton(主方案)": stats(nav), "买入持有(全收益)": stats(bh),
                        f"静态{avg_w:.0%}股+债": stats(mix)}).T
    P(tab.to_string(float_format=lambda x: f"{x:.3f}"))

    # ---------- 子区间 ----------
    P("\n子区间（CAGR：策略 / 静态同仓位 / 买入持有）")
    for a, b in [("2012-10", "2016-12"), ("2017-01", "2020-12"), ("2021-01", "2026-09")]:
        sl = lambda s: s[a:b]
        P(f"  {a}~{b}: {stats(sl(nav))['CAGR']:.3f} / {stats(sl(mix))['CAGR']:.3f} / {stats(sl(bh))['CAGR']:.3f}"
          f"   回撤 {stats(sl(nav))['MaxDD']:.3f} / {stats(sl(mix))['MaxDD']:.3f} / {stats(sl(bh))['MaxDD']:.3f}")

    # 滚动 3 年：策略 vs 同仓位静态组合
    def roll_win(n1, n2, days=756):
        a, b = n1.dropna(), n2.reindex(n1.dropna().index)
        r1 = a.shift(-days) / a - 1
        r2 = b.shift(-days) / b - 1
        d = (r1 - r2).dropna()
        return (d > 0).mean(), d.median()
    wr, md = roll_win(nav, mix)
    P(f"\n滚动3年窗口：跑赢同仓位静态组合的比例 {wr:.0%}，超额中位数 {md:.3f}")
    wr, md = roll_win(nav, bh)
    P(f"滚动3年窗口：跑赢买入持有的比例 {wr:.0%}，超额中位数 {md:.3f}")

    # ---------- 参数网格 ----------
    rows = []
    for gamma in [1, 1.5, 2, 3, 4]:
        for sig in ["expanding", 0.20, 0.25, 0.30]:
            t = target_weight(df, gamma, sig)
            for band in [0.0, 0.05, 0.10, 0.20]:
                for lag in [1, 5, 21]:
                    n, ww = backtest(df, t, band, lag)
                    s0 = n.dropna().index[0]
                    aw = ww.dropna().mean()
                    m = static_mix(df, aw, s0)
                    s, sm = stats(n), stats(m)
                    rows.append(dict(gamma=gamma, sigma=sig, band=band, lag=lag, avg_w=aw,
                                     CAGR=s["CAGR"], Sharpe=s["Sharpe"], MaxDD=s["MaxDD"],
                                     alpha=s["CAGR"] - sm["CAGR"], dSharpe=s["Sharpe"] - sm["Sharpe"],
                                     dMDD=s["MaxDD"] - sm["MaxDD"]))
    grid = pd.DataFrame(rows)
    grid.to_csv(f"{OUT}/grid.csv", index=False)
    P(f"\n参数网格 {len(grid)} 组：")
    P(f"  择时超额(CAGR-同仓位静态) >0 的比例 {(grid.alpha > 0).mean():.0%}，中位数 {grid.alpha.median():.3f}，"
      f"10%分位 {grid.alpha.quantile(.1):.3f}，90%分位 {grid.alpha.quantile(.9):.3f}")
    P(f"  夏普提升 >0 的比例 {(grid.dSharpe > 0).mean():.0%}，回撤改善 >0 的比例 {(grid.dMDD > 0).mean():.0%}")
    P("  按 gamma 分组的超额中位数：" + ", ".join(f"γ={k}:{v:.3f}" for k, v in grid.groupby('gamma').alpha.median().items()))
    P("  按 滞后 分组的超额中位数：" + ", ".join(f"{k}天:{v:.3f}" for k, v in grid.groupby('lag').alpha.median().items()))

    # ---------- 安慰剂：循环平移仓位序列 ----------
    rng = np.random.default_rng(0)
    wt = tw.copy()
    valid = wt.dropna()
    real = stats(nav)["CAGR"] - stats(mix)["CAGR"]
    sims = []
    for _ in range(300):
        k = rng.integers(250, len(valid) - 250)
        sh = pd.Series(np.roll(valid.values, k), valid.index).reindex(df.index)
        n, ww = backtest(df, sh)
        m = static_mix(df, ww.dropna().mean(), n.dropna().index[0])
        sims.append(stats(n)["CAGR"] - stats(m)["CAGR"])
    sims = np.array(sims)
    P(f"\n安慰剂(300次循环平移)：真实择时超额 {real:.3f}，随机中位数 {np.median(sims):.3f}，"
      f"随机结果≥真实的比例 p={np.mean(sims >= real):.3f}")

    # ---------- 当前信号 ----------
    last = df.iloc[-1]
    P(f"\n最新({df.index[-1].date()}): PE={last.pe:.2f}  E/P={1/last.pe:.2%}  10Y={last.y10:.2f}%  "
      f"ERP={last.erp:.2%}  年化波动={(df.ret.std()*np.sqrt(252)):.1%}  -> 目标仓位 {tw.iloc[-1]:.0%}")

    open(f"{OUT}/results.txt", "w").write("\n".join(lines))

    # ---------- 图 ----------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(3, 1, figsize=(11, 10), sharex=True,
                           gridspec_kw=dict(height_ratios=[3, 1.5, 1.5]))
    for s, lab, c in [(nav, "ERP-Merton", "#c0392b"), (bh, "Buy & Hold (TR)", "#7f8c8d"),
                      (mix, f"Static {avg_w:.0%} equity", "#2980b9")]:
        ax[0].plot(s / s.dropna().iloc[0], label=lab, color=c, lw=1.4)
    ax[0].set_yscale("log"); ax[0].legend(); ax[0].set_title("NAV (log)"); ax[0].grid(alpha=.3)
    ax[1].plot(df["erp"] * 100, color="#8e44ad", lw=1); ax[1].set_ylabel("ERP %"); ax[1].grid(alpha=.3)
    ax[2].fill_between(w.index, w.fillna(0), color="#c0392b", alpha=.4, step="post")
    ax[2].set_ylabel("Equity weight"); ax[2].set_ylim(0, 1.05); ax[2].grid(alpha=.3)
    fig.tight_layout(); fig.savefig(f"{OUT}/nav.png", dpi=110)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(grid.alpha * 100, bins=30, color="#c0392b", alpha=.6, label=f"Param grid ({len(grid)})")
    ax.hist(sims * 100, bins=30, color="#7f8c8d", alpha=.5, label="Placebo (shifted signal)")
    ax.axvline(real * 100, color="k", ls="--", label="Main spec")
    ax.axvline(0, color="k", lw=.5)
    ax.set_xlabel("Timing alpha vs same-exposure static mix (CAGR, %)"); ax.legend()
    fig.tight_layout(); fig.savefig(f"{OUT}/robustness.png", dpi=110)


if __name__ == "__main__":
    main()
