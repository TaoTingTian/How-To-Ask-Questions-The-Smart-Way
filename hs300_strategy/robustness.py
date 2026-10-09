"""
TCVB 策略的反过拟合 / 稳健性检验。所有检验只"看"，不回头改 strategy.py 中的参数。

  1. 主回测 + 公平基准（买入持有 / 等暴露静态组合）
  2. 消融：只用趋势 / 只用波动 / 两者结合
  3. 参数邻域：108 组相邻参数，看分布与"高原"，而不是挑最大值
  4. 安慰剂（零假设）检验：块自助法打乱时间顺序，摧毁中长期趋势后策略还剩多少优势
  5. 分段 / 逐年 / 不同起点
  6. 交易成本、执行延迟敏感性
  7. 跨市场：原封不动用于中证500

python robustness.py   ->  results/ 下的图表与 robustness_report.md
"""
from __future__ import annotations

import itertools
import os

import logging
import matplotlib
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from strategy import (HERE, PARAMS, backtest, decision_days, load_csv, metrics,
                      replace, run, signals, static_mix)

OUT = os.path.join(HERE, "results")
os.makedirs(OUT, exist_ok=True)
plt.rcParams.update({"font.family": ["WenQuanYi Zen Hei", "DejaVu Sans"],
                     "axes.unicode_minus": False, "figure.dpi": 130,
                     "axes.facecolor": "#fcfcfb", "figure.facecolor": "#fcfcfb",
                     "axes.edgecolor": "#c9c8c2", "axes.grid": True,
                     "grid.color": "#e6e5e0", "grid.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False})
C_STRAT, C_BH, C_MIX, C_INK = "#2a78d6", "#eb6834", "#1baf7a", "#52514e"

df = load_csv(os.path.join(HERE, "data", "hs300.csv"))
report: list[str] = []


def fmt(table: pd.DataFrame) -> str:
    pct = {"年化收益", "年化波动", "最大回撤", "平均仓位", "超额收益"}
    t = table.copy().astype(object)
    for idx in t.index:
        for col in t.columns:
            v = table.loc[idx, col]
            if pd.isna(v):
                t.loc[idx, col] = "–"
            elif idx in pct or col in pct:
                t.loc[idx, col] = f"{v:.1%}"
            elif isinstance(v, (int, np.integer)) or float(v).is_integer() and abs(v) > 50:
                t.loc[idx, col] = f"{v:.0f}"
            else:
                t.loc[idx, col] = f"{v:.2f}"
    return t.to_markdown()


def section(title: str, body: str):
    print(f"\n## {title}\n{body}")
    report.append(f"\n## {title}\n\n{body}\n")


def summary(res: pd.DataFrame) -> dict:
    s = metrics(res["nav"], res["weight"], res["turnover"])
    b = metrics(res["bh"])
    m = metrics(static_mix(res["bh"], res["weight"].mean()))
    return {"strat": s, "bh": b, "mix": m}


# ---------------------------------------------------------------------------
# 1. 主回测
# ---------------------------------------------------------------------------
base = run(df)
S = summary(base)
avg_w = base["weight"].mean()
section("1. 主回测（预先设定参数，只跑一次）",
        f"区间 {base.index[0].date()} ~ {base.index[-1].date()}，沪深300价格指数，"
        f"单边成本 0.10%，周频决策、次日开盘执行，现金收益按 0 计。\n\n"
        + fmt(pd.DataFrame({"TCVB策略": S["strat"], "买入持有": S["bh"],
                            f"等暴露静态组合({avg_w:.0%}仓位)": S["mix"]})))

# 资金曲线 + 回撤 + 仓位
fig, ax = plt.subplots(3, 1, figsize=(10, 8.4), sharex=True,
                       gridspec_kw={"height_ratios": [3, 1.3, 1.1]})
mix_nav = static_mix(base["bh"], avg_w)
for s, c, lab in [(base["nav"], C_STRAT, "TCVB 策略"), (base["bh"], C_BH, "买入持有"),
                  (mix_nav, C_MIX, f"等暴露静态 ({avg_w:.0%})")]:
    ax[0].plot(s.index, s, color=c, lw=1.6, label=lab)
    ax[1].plot(s.index, s / s.cummax() - 1, color=c, lw=1.2)
ax[0].set_yscale("log"); ax[0].set_ylabel("净值（对数）")
ax[0].yaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter("%.1f"))
ax[0].yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter()); ax[0].legend(frameon=False, loc="upper left")
ax[0].set_title("沪深300 · 趋势共识 × 波动预算（TCVB）", loc="left", fontsize=13)
ax[1].set_ylabel("回撤")
ax[1].yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
ax[2].fill_between(base.index, base["weight"], step="post", color=C_STRAT, alpha=0.35, lw=0)
ax[2].set_ylabel("仓位"); ax[2].set_ylim(0, 1.02)
ax[2].yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
fig.tight_layout(); fig.savefig(os.path.join(OUT, "1_equity_drawdown_position.png")); plt.close(fig)

# ---------------------------------------------------------------------------
# 2. 消融
# ---------------------------------------------------------------------------
rows = {}
for name, p in [("只用趋势", replace(PARAMS, use_vol=False)),
                ("只用波动", replace(PARAMS, use_trend=False)),
                ("趋势×波动(TCVB)", PARAMS)]:
    r = run(df, p, start=base.index[0])
    m = metrics(r["nav"], r["weight"], r["turnover"])
    mm = metrics(static_mix(r["bh"], r["weight"].mean()))
    rows[name] = {**{k: m[k] for k in ["年化收益", "夏普(无风险=0)", "最大回撤", "卡玛", "平均仓位"]},
                  "等暴露静态夏普": mm["夏普(无风险=0)"], "等暴露静态卡玛": mm["卡玛"]}
section("2. 消融：每个部件各自贡献多少", fmt(pd.DataFrame(rows).T))

# ---------------------------------------------------------------------------
# 3. 参数邻域
# ---------------------------------------------------------------------------
LB = {"短(0.5-6月)": (10, 21, 42, 63, 126), "基准(1-12月)": PARAMS.lookbacks,
      "长(2-24月)": (42, 63, 126, 252, 504)}
VW = {"快(10,42)": (10, 42), "基准(21,63)": PARAMS.vol_windows, "慢(42,126)": (42, 126)}
BANDS = [0.0, 0.05, 0.10, 0.20]
FREQS = {"日": "D", "周": "W", "月": "M"}
grid = []
start = pd.Timestamp("2007-01-01")  # 统一起点，保证最长回看(504日)也已预热
for (lk, lb), (vk, vw), band, (fk, fq) in itertools.product(LB.items(), VW.items(), BANDS, FREQS.items()):
    p = replace(PARAMS, lookbacks=lb, vol_windows=vw, band=band, freq=fq)
    r = run(df, p, start=start)
    m = metrics(r["nav"], r["weight"], r["turnover"])
    mm = metrics(static_mix(r["bh"], r["weight"].mean()))
    grid.append({"回看": lk, "波动窗口": vk, "带宽": band, "频率": fk,
                 "年化收益": m["年化收益"], "夏普": m["夏普(无风险=0)"], "最大回撤": m["最大回撤"],
                 "卡玛": m["卡玛"], "年换手": m["年换手(单边)"],
                 "静态夏普": mm["夏普(无风险=0)"], "静态卡玛": mm["卡玛"]})
G = pd.DataFrame(grid)
G.to_csv(os.path.join(OUT, "param_grid.csv"), index=False)
bh_g = metrics(run(df, start=start)["bh"])
desc = G[["年化收益", "夏普", "最大回撤", "卡玛", "年换手"]].describe(percentiles=[.1, .5, .9]).T
desc = desc[["min", "10%", "50%", "90%", "max"]]
desc.columns = ["最差", "10分位", "中位数", "90分位", "最好"]
body = (f"共 {len(G)} 组相邻参数（3 种回看族 × 3 种波动窗口 × 4 种带宽 × 3 种频率），"
        f"统一从 {start.date()} 开始。同期买入持有：夏普 {bh_g['夏普(无风险=0)']:.2f}，"
        f"卡玛 {bh_g['卡玛']:.2f}，最大回撤 {bh_g['最大回撤']:.1%}。\n\n"
        + desc.to_markdown(floatfmt=".3f")
        + f"\n\n- 夏普高于买入持有的组合占比：**{(G['夏普'] > bh_g['夏普(无风险=0)']).mean():.0%}**"
        + f"\n- 夏普高于自身等暴露静态组合的占比：**{(G['夏普'] > G['静态夏普']).mean():.0%}**"
        + f"\n- 卡玛高于自身等暴露静态组合的占比：**{(G['卡玛'] > G['静态卡玛']).mean():.0%}**"
        + f"\n- 最大回撤小于买入持有的占比：**{(G['最大回撤'] > bh_g['最大回撤']).mean():.0%}**")
section("3. 参数邻域：是高原还是孤峰？", body)

fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
for a, fk in zip(axes, FREQS):
    piv = G[(G["频率"] == fk) & (G["带宽"] == 0.10)].pivot(index="回看", columns="波动窗口", values="夏普")
    piv = piv.loc[list(LB), list(VW)]
    im = a.imshow(piv.values, cmap="Blues", vmin=0.3, vmax=0.8)
    a.set_xticks(range(3), piv.columns, fontsize=8); a.set_yticks(range(3), piv.index, fontsize=8)
    a.tick_params(axis="y", labelleft=a is axes[0])
    a.grid(False); a.set_title(f"{fk}频，带宽10%：夏普", fontsize=10)
    for (i, j), v in np.ndenumerate(piv.values):
        a.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=9,
               color="white" if v > 0.62 else "#0b0b0b")
fig.colorbar(im, ax=axes, shrink=0.8, label=f"夏普（买入持有 = {bh_g['夏普(无风险=0)']:.2f}）")
fig.savefig(os.path.join(OUT, "3_param_heatmap.png"), bbox_inches="tight"); plt.close(fig)

fig, ax = plt.subplots(figsize=(8, 3.6))
ax.hist(G["夏普"], bins=20, color=C_STRAT, alpha=0.8, edgecolor="#fcfcfb")
ax.axvline(bh_g["夏普(无风险=0)"], color=C_BH, lw=2, label="买入持有")
ax.axvline(G["静态夏普"].median(), color=C_MIX, lw=2, ls="--", label="等暴露静态（中位）")
ax.set_title(f"{len(G)} 组相邻参数的夏普分布", loc="left"); ax.legend(frameon=False)
fig.tight_layout(); fig.savefig(os.path.join(OUT, "3_param_distribution.png")); plt.close(fig)

# ---------------------------------------------------------------------------
# 4. 安慰剂检验：平稳块自助法（平均块长 5 日）打乱时间顺序
#    保留日收益分布与短期波动聚集，摧毁 1~12 个月的趋势结构。
# ---------------------------------------------------------------------------
rng = np.random.default_rng(20240101)  # 固定种子，结果可复现
N_PATH, MEAN_BLOCK = 500, 5
gap = (df["open"] / df["close"].shift(1)).to_numpy()[1:]
intr = (df["close"] / df["open"]).to_numpy()[1:]
T = len(gap)


def stationary_bootstrap_idx(T, n, mean_block, rng):
    idx = np.empty((T, n), dtype=int)
    idx[0] = rng.integers(0, T, n)
    for t in range(1, T):
        jump = rng.random(n) < 1 / mean_block
        idx[t] = np.where(jump, rng.integers(0, T, n), (idx[t - 1] + 1) % T)
    return idx


ix = stationary_bootstrap_idx(T, N_PATH, MEAN_BLOCK, rng)
g_s, i_s = gap[ix], intr[ix]
cls = np.vstack([np.ones((1, N_PATH)), np.cumprod(g_s * i_s, axis=0)])
opn = np.vstack([np.ones((1, N_PATH)), cls[:-1] * g_s])
dates = df.index
close_df = pd.DataFrame(cls, index=dates)
sig = signals(close_df)
tgt = sig["target"]
first = tgt.notna().all(axis=1).idxmax()
k0 = dates.get_loc(first)
nav, w, _ = backtest(opn[k0:], cls[k0:], tgt.to_numpy()[k0:], decision_days(dates, "W")[k0:])
r_s = np.diff(np.log(nav), axis=0)
r_b = np.diff(np.log(cls[k0:]), axis=0)
ppy = 244
sh_s = r_s.mean(0) / r_s.std(0) * np.sqrt(ppy)
sh_b = r_b.mean(0) / r_b.std(0) * np.sqrt(ppy)
real_s = np.diff(np.log(base["nav"].to_numpy())); real_b = np.diff(np.log(base["bh"].to_numpy()))
real_diff = real_s.mean() / real_s.std() * np.sqrt(ppy) - real_b.mean() / real_b.std() * np.sqrt(ppy)
null_diff = sh_s - sh_b
pval = (np.sum(null_diff >= real_diff) + 1) / (N_PATH + 1)
dd_null = (nav / np.maximum.accumulate(nav, axis=0) - 1).min(0)
section("4. 安慰剂检验：打乱时间顺序后优势还在吗？",
        f"用平稳块自助法（平均块长 {MEAN_BLOCK} 日）生成 {N_PATH} 条与沪深300日收益分布相同、"
        f"但中长期趋势被摧毁的假行情，原封不动运行策略。\n\n"
        f"| | 真实沪深300 | 假行情中位数 | 假行情 95 分位 |\n|---|---|---|---|\n"
        f"| 策略夏普 − 买入持有夏普 | **{real_diff:+.2f}** | {np.median(null_diff):+.2f} | "
        f"{np.quantile(null_diff, .95):+.2f} |\n"
        f"| 策略最大回撤 | {S['strat']['最大回撤']:.1%} | {np.median(dd_null):.1%} | – |\n\n"
        f"单侧 p 值 ≈ **{pval:.3f}**（假行情中夏普优势不低于真实值的比例）。"
        f"\n\n解读：假行情保留了收益分布和短期波动聚集，只摧毁了中长期趋势。"
        f"如果策略的优势只是『少持仓、少波动』带来的机械效果，它在假行情里也应同样出现；"
        f"真实值落在假行情分布右尾之外的部分，才可归因于真实存在的趋势结构。")

fig, ax = plt.subplots(figsize=(8, 3.6))
ax.hist(null_diff, bins=30, color="#9a9890", edgecolor="#fcfcfb", label="打乱时间顺序的假行情")
ax.axvline(real_diff, color=C_STRAT, lw=2.4, label=f"真实沪深300（p≈{pval:.3f}）")
ax.set_xlabel("策略夏普 − 买入持有夏普"); ax.legend(frameon=False)
ax.set_title("安慰剂检验", loc="left")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "4_placebo.png")); plt.close(fig)

# ---------------------------------------------------------------------------
# 5. 分段 / 逐年 / 不同起点
# ---------------------------------------------------------------------------
seg_rows = {}
for a, b in [("2006", "2010"), ("2011", "2015"), ("2016", "2020"), ("2021", "2026")]:
    sub = base.loc[a:b]
    s = metrics(sub["nav"] / sub["nav"].iloc[0]); bh = metrics(sub["bh"] / sub["bh"].iloc[0])
    seg_rows[f"{a}-{b}"] = {"策略年化": s["年化收益"], "买持年化": bh["年化收益"],
                            "策略回撤": s["最大回撤"], "买持回撤": bh["最大回撤"],
                            "策略夏普": s["夏普(无风险=0)"], "买持夏普": bh["夏普(无风险=0)"]}
seg = pd.DataFrame(seg_rows).T
seg_fmt = seg.copy().astype(object)
for c in seg.columns:
    seg_fmt[c] = seg[c].map(lambda v: f"{v:.2f}" if "夏普" in c else f"{v:.1%}")

yr = base[["nav", "bh"]].resample("YE").last()
yr = pd.concat([base[["nav", "bh"]].iloc[[0]], yr]).pct_change().dropna()
yr.index = yr.index.year
yr.columns = ["策略", "买入持有"]
win = (yr["策略"] > yr["买入持有"]).mean()
down_years = yr[yr["买入持有"] < 0]
starts = {}
for y in range(2007, 2021):
    sub = base.loc[f"{y}":]
    s = metrics(sub["nav"] / sub["nav"].iloc[0]); bh = metrics(sub["bh"] / sub["bh"].iloc[0])
    starts[y] = {"策略年化": s["年化收益"], "买持年化": bh["年化收益"],
                 "策略回撤": s["最大回撤"], "买持回撤": bh["最大回撤"]}
st = pd.DataFrame(starts).T
section("5. 分段、逐年与不同起点",
        "**四个五年段**\n\n" + seg_fmt.to_markdown()
        + f"\n\n**逐年**：策略跑赢买入持有的年份占 {win:.0%}；"
        f"在买入持有下跌的 {len(down_years)} 个年份里，策略平均 {down_years['策略'].mean():.1%}，"
        f"买入持有平均 {down_years['买入持有'].mean():.1%}；"
        f"在买入持有上涨的年份里，策略平均 {yr[yr['买入持有'] >= 0]['策略'].mean():.1%}，"
        f"买入持有平均 {yr[yr['买入持有'] >= 0]['买入持有'].mean():.1%}。\n\n"
        + yr.T.map(lambda v: f"{v:.0%}").to_markdown()
        + f"\n\n**不同起点持有至今**：策略年化跑赢的起点占 "
        f"{(st['策略年化'] > st['买持年化']).mean():.0%}，回撤更小的起点占 "
        f"{(st['策略回撤'] > st['买持回撤']).mean():.0%}。\n\n"
        + st.map(lambda v: f"{v:.1%}").to_markdown())

fig, ax = plt.subplots(figsize=(10, 3.8))
x = np.arange(len(yr))
ax.bar(x - 0.2, yr["策略"], 0.38, color=C_STRAT, label="TCVB 策略")
ax.bar(x + 0.2, yr["买入持有"], 0.38, color=C_BH, label="买入持有")
ax.set_xticks(x, yr.index, rotation=45, fontsize=8); ax.axhline(0, color=C_INK, lw=0.8)
ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
ax.legend(frameon=False); ax.set_title("逐年收益", loc="left")
fig.tight_layout(); fig.savefig(os.path.join(OUT, "5_yearly.png")); plt.close(fig)

# ---------------------------------------------------------------------------
# 6. 成本、执行时点、现金/股息假设
# ---------------------------------------------------------------------------
rows = {}
for c in [0.0, 0.0005, 0.001, 0.002, 0.003, 0.005]:
    m = metrics(run(df, replace(PARAMS, cost=c))["nav"])
    rows[f"单边成本 {c:.2%}"] = {k: m[k] for k in ["年化收益", "夏普(无风险=0)", "最大回撤"]}
for lab, p in [("次日开盘执行（基准）", PARAMS), ("次日收盘执行", replace(PARAMS, exec_at="close")),
               ("再延迟 1 日", replace(PARAMS, extra_delay=1)),
               ("再延迟 3 日", replace(PARAMS, extra_delay=3))]:
    m = metrics(run(df, p)["nav"])
    rows[lab] = {k: m[k] for k in ["年化收益", "夏普(无风险=0)", "最大回撤"]}
r_tr = run(df, replace(PARAMS, cash_yield=0.02, div_yield=0.02))
m, mb = metrics(r_tr["nav"]), metrics(r_tr["bh"])
rows["股息2%+现金2%（策略）"] = {k: m[k] for k in ["年化收益", "夏普(无风险=0)", "最大回撤"]}
rows["股息2%（买入持有）"] = {k: mb[k] for k in ["年化收益", "夏普(无风险=0)", "最大回撤"]}
section("6. 成本、执行时点与收益口径敏感性", fmt(pd.DataFrame(rows).T))

# ---------------------------------------------------------------------------
# 7. 跨市场：原封不动用于中证500
# ---------------------------------------------------------------------------
d5 = load_csv(os.path.join(HERE, "data", "csi500.csv"))
r5 = run(d5)
S5 = summary(r5)
section("7. 跨市场：参数不改，直接用于中证500",
        fmt(pd.DataFrame({"TCVB策略": S5["strat"], "买入持有": S5["bh"],
                          f"等暴露静态({r5['weight'].mean():.0%})": S5["mix"]})))

with open(os.path.join(OUT, "robustness_report.md"), "w") as f:
    f.write("# TCVB 稳健性检验报告（由 robustness.py 自动生成）\n" + "".join(report))
print("\n已写出 results/robustness_report.md 及图表")
