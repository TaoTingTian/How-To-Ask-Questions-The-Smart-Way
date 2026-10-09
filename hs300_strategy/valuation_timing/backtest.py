#!/usr/bin/env python3
"""
沪深300 估值择时：多滚动窗口集成百分位回测 + 过拟合检查
=========================================================

运行：
    pip install pandas numpy scipy matplotlib
    python backtest.py            # 读取 ./data，输出到 ./output

所有“事先固定”的参数都集中在下方 CONFIG 区块；本脚本不做任何参数寻优，
阈值 / 窗口 / 聚合方式的变化只用于敏感性分析，并全部计入试验次数。

时序约定（无未来函数）：
  * 百分位：rolling(window).rank(pct=True)，窗口只含 t 日及以前数据；
    min_periods = window（窗口填满才出值）。
  * 信号在 t 日收盘计算 -> t+1 日收盘按收盘价调仓 -> 新仓位从 t+2 日起承担收益。
  * 缺失值只允许 ffill（本数据集实际无缺失，代码仍保留 ffill 以符合规则）。
"""
from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "output"
FIG = OUT / "figures"

# ============================== CONFIG（事先固定） ==============================
DAYS_PER_YEAR_WINDOW = 250          # 窗口年数 -> 交易日 的换算（按需求）
COST = 0.001                        # 单边交易成本 0.1%
CASH_ANNUAL = 0.0                   # 空仓收益：主口径 0（未提供货币基金数据）
CASH_ANNUAL_ALT = 0.02              # 敏感性：假设货基年化 2%（常数近似）
MAIN_TH = (0.20, 0.80)              # 主阈值（事先指定，非优化所得）
THRESHOLDS = [(0.15, 0.85), (0.20, 0.80), (0.25, 0.75), (0.30, 0.70)]
POS_STEP = 0.10                     # 仓位离散为 10% 一档，避免每天微调
EXPANDING_MIN_YEARS = 3             # 扩展窗口最少 3 年才出值
MIN_WINDOWS = 2                     # 集成：至少 2 个窗口有值才输出

INDICATORS = {  # 名称: (文件, 方向)  方向 +1: 值越高越贵；-1: 值越高越便宜
    "ERP": ("CSI300_ERP.csv", -1),
    "PE": ("CSI300_PE_TTM.csv", +1),
    "PB": ("CSI300_PB.csv", +1),
    "DY": ("CSI300_Dividend_Yield.csv", -1),
}
COMPOSITE = "综合"  # 四指标“贵度分位”等权平均（额外构建，计入试验次数）
IND_ALL = list(INDICATORS) + [COMPOSITE]

SPECS = {  # 规格名: (类型, 窗口年数, 聚合)
    "A_均值": ("ens", (3, 5, 7, 10), "mean"),
    "A_中位数": ("ens", (3, 5, 7, 10), "median"),
    "B_均值": ("ens", (2, 4, 6, 8), "mean"),
    "B_中位数": ("ens", (2, 4, 6, 8), "median"),
    "C_均值": ("ens", (5, 7, 10, 12), "mean"),
    "C_中位数": ("ens", (5, 7, 10, 12), "median"),
    "单窗3年": ("single", (3,), None),
    "单窗5年": ("single", (5,), None),
    "单窗10年": ("single", (10,), None),
    "扩展窗口": ("expanding", (), None),
}
ENSEMBLE_SPECS = [s for s, v in SPECS.items() if v[0] == "ens"]

MAIN_WIN = ("2019-01-02", "2026-09-30")  # 主比较区间：A/B/C 全部有信号（C 自 2018-12）
LATE_WIN = ("2022-01-17", "2026-09-30")  # 含单窗10年在内全部策略都有信号的区间
HALVES = [("2019-01-02", "2022-10-31"), ("2022-11-01", "2026-09-30")]
SUBPERIODS = {
    "2015泡沫(2014-11~2016-02)": ("2014-11-13", "2016-02-29"),
    "2018熊市(2018-01-24~2019-01-04)": ("2018-01-24", "2019-01-04"),
    "2021高点前后(2020-07~2022-10)": ("2020-07-01", "2022-10-31"),
    "2024年以来(2024-01~2026-09)": ("2024-01-02", "2026-09-30"),
}
KEY_POINTS = {  # 由收盘价序列确认的局部极值
    "2015-06-08 高点": "2015-06-08",
    "2016-01-28 低点": "2016-01-28",
    "2018-01-24 高点": "2018-01-24",
    "2019-01-03 低点": "2019-01-03",
    "2021-02-10 高点": "2021-02-10",
    "2022-10-31 低点": "2022-10-31",
    "2024-02-02 低点": "2024-02-02",
    "2024-09-13 低点": "2024-09-13",
    "2026-06-22 近期高点": "2026-06-22",
}

# 图表配色（dataviz 参考色板，固定顺序）
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
DIVERGING = LinearSegmentedColormap.from_list("rb", ["#c0392b", "#e34948", "#f0efec", "#2a78d6", "#184f95"])
plt.rcParams.update({
    "font.sans-serif": ["WenQuanYi Zen Hei", "Noto Sans CJK SC", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False, "axes.edgecolor": INK2, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 110, "savefig.bbox": "tight", "lines.linewidth": 1.4,
})


# ============================== 数据 ==============================
def load_data() -> tuple[pd.DataFrame, pd.Series]:
    px = pd.read_csv(DATA / "CSI300_close_20110930-20260930.csv", encoding="utf-8-sig",
                     parse_dates=["日期"]).set_index("日期")["收盘点位"].rename("close")
    raw = {k: pd.read_csv(DATA / f, parse_dates=["date"]).set_index("date")["value"]
           for k, (f, _) in INDICATORS.items()}
    raw["Y10"] = pd.read_csv(DATA / "China_10Y_Gov_Bond_Yield.csv",
                             parse_dates=["date"]).set_index("date")["value"]
    df = pd.DataFrame(raw).reindex(px.index).ffill()      # 只允许向前填充
    # ERP 按定义重算：1/PE-TTM − 10年国债收益率（百分比口径），并与文件核对
    erp = 100.0 / df["PE"] - df["Y10"]
    diff = (erp - df["ERP"]).abs().max()
    assert diff < 1e-8, f"ERP 文件与定义不一致: {diff}"
    df["ERP"] = erp
    return df, px


# ============================== 百分位与信号 ==============================
def expensiveness(x: pd.Series, direction: int, window_days: int | None) -> pd.Series:
    """统一转换为“贵度分位”：值越高越贵。方向为 -1 的指标先取负再排名。"""
    y = direction * x
    if window_days is None:
        return y.expanding(min_periods=EXPANDING_MIN_YEARS * DAYS_PER_YEAR_WINDOW).rank(pct=True)
    return y.rolling(window_days, min_periods=window_days).rank(pct=True)


def build_percentiles(df: pd.DataFrame) -> dict[str, dict]:
    """返回 {指标: {'win': {年数: Series}, 'exp': Series}}"""
    years = sorted({w for v in SPECS.values() for w in v[1]})
    out = {}
    for ind, (_, d) in INDICATORS.items():
        out[ind] = {"win": {w: expensiveness(df[ind], d, w * DAYS_PER_YEAR_WINDOW) for w in years},
                    "exp": expensiveness(df[ind], d, None)}
    return out


def spec_signal(pct: dict, spec: str) -> pd.Series:
    kind, wins, agg = SPECS[spec]
    if kind == "expanding":
        return pct["exp"]
    if kind == "single":
        return pct["win"][wins[0]]
    m = pd.concat([pct["win"][w] for w in wins], axis=1)
    val = m.mean(axis=1) if agg == "mean" else m.median(axis=1)
    return val.where(m.notna().sum(axis=1) >= MIN_WINDOWS)


def build_signals(pcts: dict) -> dict[tuple[str, str], pd.Series]:
    sig = {}
    for spec in SPECS:
        cols = []
        for ind in INDICATORS:
            sig[(ind, spec)] = spec_signal(pcts[ind], spec)
            cols.append(sig[(ind, spec)])
        m = pd.concat(cols, axis=1)
        sig[(COMPOSITE, spec)] = m.mean(axis=1).where(m.notna().all(axis=1))
    return sig


def position_linear(v: pd.Series, lo: float, hi: float) -> pd.Series:
    """主映射：贵度 ≤ lo 满仓，≥ hi 空仓，中间线性；按 10% 一档取整。"""
    p = ((hi - v) / (hi - lo)).clip(0, 1)
    return (np.round(p / POS_STEP) * POS_STEP).where(v.notna())


def position_tier3(v: pd.Series, lo: float, hi: float) -> pd.Series:
    """替代映射（仅作稳健性对照）：≤lo 满仓 / ≥hi 空仓 / 中间 50%。"""
    p = pd.Series(0.5, index=v.index)
    p[v <= lo] = 1.0
    p[v >= hi] = 0.0
    return p.where(v.notna())


# ============================== 回测与指标 ==============================
def run(target: pd.Series, ret: pd.Series, start, end, cash_annual=CASH_ANNUAL, cost=COST):
    """target: t 日收盘算出的目标仓位。t+1 收盘成交，t+2 起承担收益。
    区间首日前视为空仓（首日收盘建仓并计成本）。信号不全覆盖区间时返回 None。"""
    held = target.shift(1).loc[start:end]  # 第 d 日收盘后持有的仓位
    if len(held) < 20 or held.isna().any():
        return None
    r = ret.loc[start:end]
    cash = (1 + cash_annual) ** (1 / ANN) - 1
    prev = held.shift(1).fillna(0.0)
    trade = (held - prev).abs()
    daily = prev * r + (1 - prev) * cash - cost * trade
    return {"daily": daily, "pos": held, "trade": trade, "cash": cash}


def perf(res, rf_daily=None) -> dict:
    d, pos, trade = res["daily"], res["pos"], res["trade"]
    rf = res["cash"] if rf_daily is None else rf_daily
    n = len(d)
    yrs = n / ANN
    nav = (1 + d).cumprod()
    peak = np.maximum.accumulate(np.r_[1.0, nav.values])[1:]
    mdd = float((nav.values / peak - 1).min())
    cagr = nav.iloc[-1] ** (1 / yrs) - 1
    vol = d.std(ddof=1) * math.sqrt(ANN)
    sharpe = (d - rf).mean() / d.std(ddof=1) * math.sqrt(ANN) if d.std() > 0 else np.nan
    return {
        "年化收益": cagr, "年化波动": vol, "夏普": sharpe, "最大回撤": mdd,
        "卡玛": cagr / abs(mdd) if mdd < 0 else np.nan,
        "年换手率": trade.iloc[1:].sum() / yrs, "平均仓位": pos.mean(),
        "交易次数": int((trade.iloc[1:] > 1e-9).sum()),
        "起始日": d.index[0].date(), "结束日": d.index[-1].date(), "年数": yrs,
    }


def static_mix_mdd(ret, w, start, end):
    """同平均仓位、每日再平衡、无成本的静态组合的最大回撤（衡量“降仓位本身”带来的回撤改善）。"""
    nav = (1 + w * ret.loc[start:end]).cumprod()
    peak = np.maximum.accumulate(np.r_[1.0, nav.values])[1:]
    return float((nav.values / peak - 1).min())


# ============================== 过拟合工具 ==============================
EULER = 0.5772156649015329


def expected_max_sr(var_sr: float, n: float) -> float:
    """N 次独立试验下最大夏普的期望（Bailey & López de Prado 2014），per-period 单位。"""
    if n <= 1:
        return 0.0
    return math.sqrt(var_sr) * ((1 - EULER) * stats.norm.ppf(1 - 1 / n)
                                + EULER * stats.norm.ppf(1 - 1 / (n * math.e)))


def psr(x: pd.Series, sr0: float) -> float:
    """Probabilistic Sharpe Ratio：P(真实 SR > sr0)，per-period 单位，考虑偏度与峰度。"""
    sr = x.mean() / x.std(ddof=1)
    g3, g4 = stats.skew(x), stats.kurtosis(x, fisher=False)
    z = (sr - sr0) * math.sqrt(len(x) - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)
    return float(stats.norm.cdf(z))


def effective_n(R: pd.DataFrame) -> tuple[float, float, float]:
    c = R.corr().values
    n = c.shape[0]
    rho = (c.sum() - n) / (n * (n - 1))
    ev = np.clip(np.linalg.eigvalsh(c), 0, None)
    return rho, rho + (1 - rho) * n, ev.sum() ** 2 / (ev ** 2).sum()


def cscv_pbo(R: pd.DataFrame, s: int = 10) -> tuple[float, np.ndarray, float]:
    """Combinatorially Symmetric Cross-Validation（Bailey et al. 2017）。
    R: T×N 日收益矩阵。返回 PBO、logit 序列、IS→OOS 夏普回归斜率。"""
    blocks = np.array_split(np.arange(len(R)), s)
    X = R.values
    lam, is_best, oos_best = [], [], []
    for comb in itertools.combinations(range(s), s // 2):
        is_idx = np.concatenate([blocks[i] for i in comb])
        oos_idx = np.concatenate([blocks[i] for i in range(s) if i not in comb])
        sr_is = X[is_idx].mean(0) / X[is_idx].std(0, ddof=1)
        sr_oos = X[oos_idx].mean(0) / X[oos_idx].std(0, ddof=1)
        k = int(np.nanargmax(sr_is))
        rank = stats.rankdata(sr_oos)[k]
        w = rank / (len(sr_oos) + 1)
        lam.append(math.log(w / (1 - w)))
        is_best.append(sr_is[k])
        oos_best.append(sr_oos[k])
    lam = np.array(lam)
    slope = np.polyfit(is_best, oos_best, 1)[0]
    return float((lam <= 0).mean()), lam, float(slope)


# ============================== 输出辅助 ==============================
def fmt_table(df: pd.DataFrame, pct_cols=(), f2_cols=(), f0_cols=()) -> str:
    d = df.copy()
    for c in d.columns:
        if c in pct_cols:
            d[c] = d[c].map(lambda v: "—" if pd.isna(v) else f"{v * 100:.1f}%")
        elif c in f2_cols:
            d[c] = d[c].map(lambda v: "—" if pd.isna(v) else f"{v:.2f}")
        elif c in f0_cols:
            d[c] = d[c].map(lambda v: "—" if pd.isna(v) else f"{int(v)}")
    if isinstance(d.index, pd.MultiIndex) or d.index.name:
        return d.reset_index().to_markdown(index=False)
    return d.to_markdown()


PCT = ("年化收益", "年化波动", "最大回撤", "平均仓位", "同仓位静态MDD", "超额年化")
F2 = ("夏普", "卡玛", "年换手率", "夏普差", "年数")
F0 = ("交易次数",)


def savefig(fig, name):
    fig.savefig(FIG / name)
    plt.close(fig)


# ============================== 主流程 ==============================
def main():
    global ANN
    OUT.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    df, px = load_data()
    ret = px.pct_change().fillna(0.0)
    ANN = len(px) / ((px.index[-1] - px.index[0]).days / 365.25)  # 样本实际年均交易日 ≈ 243
    md = []  # 汇总 markdown

    pcts = build_percentiles(df)
    sigs = build_signals(pcts)
    bench_target = pd.Series(1.0, index=px.index)

    # ---------- 所有试验：指标 × 规格 × 阈值 ----------
    trials = {}
    for (ind, spec), v in sigs.items():
        for lo, hi in THRESHOLDS:
            trials[(ind, spec, f"{int(lo * 100)}/{int(hi * 100)}")] = position_linear(v, lo, hi)
    main_th = f"{int(MAIN_TH[0] * 100)}/{int(MAIN_TH[1] * 100)}"
    n_trials = len(trials)

    def table_for(start, end, keys, cash=CASH_ANNUAL):
        rows = {}
        b = run(bench_target, ret, start, end, cash)
        bp = perf(b)
        for k in keys:
            r = run(trials[k] if isinstance(k, tuple) else k, ret, start, end, cash)
            if r is None:
                rows[k] = {"信号不足": True}
                continue
            p = perf(r)
            p["夏普差"] = p["夏普"] - bp["夏普"]
            p["超额年化"] = p["年化收益"] - bp["年化收益"]
            p["同仓位静态MDD"] = static_mix_mdd(ret, p["平均仓位"], start, end)
            rows[k] = p
        return pd.DataFrame(rows).T, bp

    main_keys = [(i, s, main_th) for i in IND_ALL for s in SPECS]
    cols = ["年化收益", "年化波动", "夏普", "最大回撤", "卡玛", "年换手率", "平均仓位", "交易次数",
            "夏普差", "超额年化", "同仓位静态MDD"]

    # ---------- 1) 主区间总表 ----------
    T_main, b_main = table_for(*MAIN_WIN, main_keys)
    T_main.index = pd.MultiIndex.from_tuples(T_main.index, names=["指标", "规格", "阈值"])
    T_main.to_csv(OUT / "table_main_window.csv", encoding="utf-8-sig")
    bench_row = pd.DataFrame([{**b_main, "夏普差": 0.0, "超额年化": 0.0, "同仓位静态MDD": b_main["最大回撤"]}],
                             index=pd.MultiIndex.from_tuples([("基准", "沪深300买入持有", "—")], names=["指标", "规格", "阈值"]))
    md.append(f"## 表1 主比较区间 {MAIN_WIN[0]} ~ {MAIN_WIN[1]}（阈值 {main_th}，空仓收益 0）\n")
    md.append(fmt_table(pd.concat([bench_row[cols], T_main[cols]]), PCT, F2, F0))

    # 按指标分组展示：每个指标一张小表
    md.append("\n## 表1b 按指标分组（同上，主区间）\n")
    for ind in IND_ALL:
        sub = T_main.xs(ind, level="指标")[["年化收益", "夏普", "最大回撤", "卡玛", "年换手率", "平均仓位", "交易次数", "夏普差"]]
        md.append(f"\n### {ind}\n")
        md.append(fmt_table(sub, PCT, F2, F0))
    # 按指标汇总的分组统计
    grp = T_main.dropna(subset=["夏普"]).groupby(level="指标")[["夏普", "夏普差", "最大回撤", "平均仓位", "年换手率"]].agg(["mean", "min", "max"])
    md.append("\n## 表1c 按指标分组统计（主区间，各规格的均值/最小/最大）\n")
    md.append(grp.round(3).to_markdown())
    grp2 = T_main.dropna(subset=["夏普"]).groupby(level="规格")[["夏普", "夏普差", "最大回撤", "平均仓位", "年换手率"]].mean()
    md.append("\n## 表1d 按规格分组统计（主区间，5 个指标的均值）\n")
    md.append(grp2.round(3).to_markdown())

    # ---------- 2) 各自全可用区间 ----------
    rows = {}
    for k in main_keys:
        held = trials[k].shift(1)
        start = held.first_valid_index()
        t, bp = table_for(start, MAIN_WIN[1], [k])
        r = t.iloc[0].to_dict()
        r["基准夏普"] = bp["夏普"]
        r["基准年化"] = bp["年化收益"]
        r["基准MDD"] = bp["最大回撤"]
        rows[k] = r
    T_full = pd.DataFrame(rows).T
    T_full.index = pd.MultiIndex.from_tuples(T_full.index, names=["指标", "规格", "阈值"])
    T_full.to_csv(OUT / "table_full_available.csv", encoding="utf-8-sig")
    md.append("\n## 表2 各策略自身全部可用区间（起点 = 首个可执行信号日，终点 2026-09-30）\n")
    md.append(fmt_table(T_full[["起始日", "年数", "年化收益", "夏普", "最大回撤", "卡玛", "平均仓位", "交易次数",
                                "基准年化", "基准夏普", "基准MDD", "夏普差"]],
                        PCT + ("基准年化", "基准MDD"), F2 + ("基准夏普",), F0))

    # ---------- 2b) 晚区间（含单窗10年） ----------
    T_late, b_late = table_for(*LATE_WIN, main_keys)
    T_late.index = pd.MultiIndex.from_tuples(T_late.index, names=["指标", "规格", "阈值"])
    T_late.to_csv(OUT / "table_late_window.csv", encoding="utf-8-sig")
    pv = T_late["夏普差"].astype(float).unstack("规格").droplevel("阈值")[list(SPECS)]
    md.append(f"\n## 表2b 全部 50 个主阈值策略都有信号的区间 {LATE_WIN[0]} ~ {LATE_WIN[1]}：夏普差（策略−基准，基准夏普 {b_late['夏普']:.2f}）\n")
    md.append(pv.round(2).to_markdown())

    # ---------- 3) 阈值稳健性 ----------
    all_keys = list(trials)
    T_all, _ = table_for(*MAIN_WIN, all_keys)
    T_all.index = pd.MultiIndex.from_tuples(T_all.index, names=["指标", "规格", "阈值"])
    T_all.to_csv(OUT / "table_all_trials_main_window.csv", encoding="utf-8-sig")
    th_labels = [f"{int(a * 100)}/{int(b * 100)}" for a, b in THRESHOLDS]
    for metric, fname, title in [("夏普差", "fig_threshold_heatmap_sharpe.png", "夏普差（策略 − 基准）"),
                                 ("最大回撤", "fig_threshold_heatmap_mdd.png", "最大回撤")]:
        fig, axes = plt.subplots(1, 5, figsize=(19, 5.6), sharey=True)
        vals = T_all[metric].astype(float)
        if metric == "夏普差":
            vmax = np.nanmax(np.abs(vals.values))
            vmin, cmap = -vmax, DIVERGING
        else:
            vmin, vmax, cmap = np.nanmin(vals.values), 0, plt.get_cmap("Blues")
        for ax, ind in zip(axes, IND_ALL):
            M = vals.xs(ind, level="指标").unstack("阈值").reindex(index=list(SPECS), columns=th_labels)
            im = ax.imshow(M.values, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
            for (i, j), v in np.ndenumerate(M.values):
                ax.text(j, i, "—" if np.isnan(v) else (f"{v:+.2f}" if metric == "夏普差" else f"{v * 100:.0f}%"),
                        ha="center", va="center", fontsize=8.5, color=INK)
            ax.set_xticks(range(4), th_labels)
            ax.set_yticks(range(len(SPECS)), list(SPECS))
            ax.set_title(ind, color=INK)
            ax.grid(False)
        fig.colorbar(im, ax=axes, shrink=0.8, label=title)
        fig.suptitle(f"阈值 × 规格 热力图：{title}（主区间 {MAIN_WIN[0]}~{MAIN_WIN[1]}；单窗10年在主区间内信号不足）", color=INK)
        savefig(fig, fname)

    # 平滑度量化：每个 (指标,规格) 在 4 个阈值上的夏普差
    sm_rows = {}
    for (ind, spec), g in T_all["夏普差"].astype(float).groupby(level=["指标", "规格"]):
        v = g.droplevel([0, 1]).reindex(th_labels).values
        if np.isnan(v).all():
            continue
        jumps = np.abs(np.diff(v))
        best = int(np.nanargmax(v))
        nb = [v[j] for j in (best - 1, best + 1) if 0 <= j < 4]
        sm_rows[(ind, spec)] = {
            "主阈值夏普差": v[1], "4阈值最小": np.nanmin(v), "4阈值最大": np.nanmax(v),
            "跑赢基准阈值数": int((v > 0).sum()), "相邻最大跳变": jumps.max(),
            "最优阈值": th_labels[best], "最优-相邻均值": v[best] - np.mean(nb),
        }
    SM = pd.DataFrame(sm_rows).T
    SM.index.names = ["指标", "规格"]
    SM.to_csv(OUT / "table_threshold_smoothness.csv", encoding="utf-8-sig")
    md.append("\n## 表3 阈值稳健性（主区间；夏普差在 4 组阈值上的变化）\n")
    md.append(fmt_table(SM, (), ("主阈值夏普差", "4阈值最小", "4阈值最大", "相邻最大跳变", "最优-相邻均值"), ("跑赢基准阈值数",)))

    # ---------- 4) 试验次数与 DSR ----------
    valid = T_all.dropna(subset=["夏普"])
    R = pd.DataFrame({k: run(trials[k], ret, *MAIN_WIN)["daily"] for k in valid.index})
    bd = run(bench_target, ret, *MAIN_WIN)["daily"]
    A = R.sub(bd, axis=0)  # 相对基准的主动收益
    sr_pp = R.mean() / R.std(ddof=1)
    ir_pp = A.mean() / A.std(ddof=1)
    rho, n_eff_rho, n_eff_eig = effective_n(R)
    rho_a, n_eff_rho_a, n_eff_eig_a = effective_n(A)
    best = sr_pp.idxmax()
    best_ir = ir_pp.idxmax()
    dsr_rows = []
    for label, n in [("全部试验 N", n_trials), ("主区间可评估 N", len(valid)),
                     ("仅主阈值 N", len(main_keys)),
                     ("有效 N（平均相关）", n_eff_rho), ("有效 N（特征值参与比）", n_eff_eig)]:
        sr0 = expected_max_sr(sr_pp.var(ddof=1), n)
        dsr_rows.append({"口径": label, "N": n, "SR0(年化)": sr0 * math.sqrt(ANN),
                         "最优夏普(年化)": sr_pp[best] * math.sqrt(ANN),
                         "DSR=P(SR>SR0)": psr(R[best], sr0)})
    for label, n in [("全部试验 N", n_trials), ("有效 N（平均相关，主动收益）", n_eff_rho_a),
                     ("有效 N（特征值参与比，主动收益）", n_eff_eig_a)]:
        sr0 = expected_max_sr(ir_pp.var(ddof=1), n)
        dsr_rows.append({"口径": "[相对基准 IR] " + label, "N": n, "SR0(年化)": sr0 * math.sqrt(ANN),
                         "最优夏普(年化)": ir_pp[best_ir] * math.sqrt(ANN),
                         "DSR=P(SR>SR0)": psr(A[best_ir], sr0)})
    DSR = pd.DataFrame(dsr_rows).set_index("口径")
    DSR.to_csv(OUT / "table_dsr.csv", encoding="utf-8-sig")
    psr_bench = psr(R[best], 0.0)
    psr_vs_bench = psr(A[best], 0.0)
    md.append("\n## 表4 试验次数与 Deflated Sharpe Ratio（主区间）\n")
    md.append(f"- 试验总数：{len(IND_ALL)} 指标 × {len(SPECS)} 规格 × {len(THRESHOLDS)} 阈值 = **{n_trials}**"
              f"（其中单窗10年的 {len(IND_ALL) * len(THRESHOLDS)} 个在主区间内信号不足，主区间可评估 {len(valid)} 个）")
    md.append(f"- 稳健性附加试验（未参与选优，但同样被运行）：3 档仓位映射 × 主阈值 × 50、空仓 2% 口径 × 50 → 共 100 个")
    md.append(f"- 按夏普选出的最优：**{best}**，年化夏普 {sr_pp[best] * math.sqrt(ANN):.3f}；基准 {b_main['夏普']:.3f}")
    md.append(f"- 按相对基准 IR 选出的最优：**{best_ir}**，年化 IR {ir_pp[best_ir] * math.sqrt(ANN):.3f}")
    md.append(f"- 试验间日收益平均相关 {rho:.3f}（主动收益 {rho_a:.3f}）；跨试验夏普的标准差（年化）{sr_pp.std() * math.sqrt(ANN):.3f}")
    md.append(f"- 未做多重检验校正的 PSR：P(最优 SR>0) = {psr_bench:.3f}；P(最优策略主动收益 SR>0) = {psr_vs_bench:.3f}\n")
    md.append(DSR.round(3).to_markdown())

    # 夏普分布图
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.hist(sr_pp * math.sqrt(ANN), bins=30, color=SERIES[0], edgecolor="white", linewidth=1)
    ax.axvline(b_main["夏普"], color=SERIES[1], lw=2, label=f"基准夏普 {b_main['夏普']:.2f}")
    sr0_all = expected_max_sr(sr_pp.var(ddof=1), n_trials) * math.sqrt(ANN)
    ax.axvline(sr0_all, color=INK2, ls="--", lw=1.5, label=f"N={n_trials} 次纯噪声试验的期望最大夏普 {sr0_all:.2f}")
    ax.set_xlabel("年化夏普（主区间）")
    ax.set_ylabel("试验数")
    ax.set_title(f"{len(valid)} 个可评估试验的夏普分布", color=INK)
    ax.legend(frameon=False)
    savefig(fig, "fig_sharpe_distribution.png")

    # ---------- 4a) 循环平移安慰剂：保留仓位序列分布与自相关，打乱与行情的对齐 ----------
    rng = np.random.default_rng(20261009)
    perm_rows = {}
    b_sr = perf(run(bench_target, ret, *MAIN_WIN))["夏普"]
    for k in [best, (COMPOSITE, "A_均值", main_th), ("PE", "A_均值", main_th), ("ERP", "A_均值", main_th),
              ("DY", "A_均值", main_th)]:
        res = run(trials[k], ret, *MAIN_WIN)
        pos, r = res["pos"].values, ret.loc[MAIN_WIN[0]:MAIN_WIN[1]].values
        n = len(pos)
        actual = perf(res)["夏普"] - b_sr
        null = []
        for off in rng.integers(120, n - 120, size=1000):
            p_ = np.roll(pos, off)
            prev = np.r_[0.0, p_[:-1]]
            d = prev * r - COST * np.abs(p_ - prev)
            null.append(d.mean() / d.std(ddof=1) * math.sqrt(ANN) - b_sr)
        null = np.array(null)
        perm_rows[k] = {"实际夏普差": actual, "安慰剂夏普差中位": np.median(null),
                        "安慰剂95%分位": np.quantile(null, 0.95), "p值(安慰剂≥实际)": (null >= actual).mean()}
    PERM = pd.DataFrame(perm_rows).T
    PERM.to_csv(OUT / "table_placebo_circular_shift.csv", encoding="utf-8-sig")
    md.append("\n## 表4b 安慰剂检验：仓位序列在主区间内随机循环平移 1000 次（≥120 日）\n")
    md.append("同样的仓位分布与持续性、但与估值无关的择时，能否同样跑赢？p 值小说明择时与行情的对齐不是偶然。\n")
    md.append(PERM.round(3).to_markdown())

    # ---------- 4b) CSCV / PBO 与前后半段 ----------
    pbo, lam, slope = cscv_pbo(R, 10)
    pbo_a, lam_a, slope_a = cscv_pbo(A, 10)
    h_rows = {}
    for k in valid.index:
        a = run(trials[k], ret, *HALVES[0])
        b = run(trials[k], ret, *HALVES[1])
        if a is None or b is None:
            continue
        h_rows[k] = {"H1夏普差": perf(a)["夏普"] - perf(run(bench_target, ret, *HALVES[0]))["夏普"],
                     "H2夏普差": perf(b)["夏普"] - perf(run(bench_target, ret, *HALVES[1]))["夏普"]}
    H = pd.DataFrame(h_rows).T
    H.index = pd.MultiIndex.from_tuples(H.index, names=["指标", "规格", "阈值"])
    H.to_csv(OUT / "table_halves.csv", encoding="utf-8-sig")
    rho_h = stats.spearmanr(H["H1夏普差"], H["H2夏普差"]).statistic
    top = H["H1夏普差"].idxmax()
    md.append("\n## 表5 CSCV / PBO 与前后半段样本外检验（主区间，180 个可评估试验）\n")
    md.append(f"- CSCV（S=10，252 种切分）按夏普选优：**PBO = {pbo:.2f}**，IS→OOS 夏普回归斜率 {slope:.2f}")
    md.append(f"- CSCV 按相对基准 IR 选优：**PBO = {pbo_a:.2f}**，斜率 {slope_a:.2f}")
    md.append(f"- 前半段 {HALVES[0][0]}~{HALVES[0][1]} vs 后半段 {HALVES[1][0]}~{HALVES[1][1]}：试验夏普差的 Spearman 秩相关 = **{rho_h:.2f}**")
    md.append(f"- 前半段最优 {top}：H1 夏普差 {H.loc[top, 'H1夏普差']:+.2f} → H2 夏普差 {H.loc[top, 'H2夏普差']:+.2f}"
              f"（H2 排名 {int(H['H2夏普差'].rank(ascending=False)[top])}/{len(H)}）")
    md.append(f"- 两半段都跑赢基准（夏普差>0）的试验：{int(((H['H1夏普差'] > 0) & (H['H2夏普差'] > 0)).sum())}/{len(H)}；"
              f"H1 跑赢 {int((H['H1夏普差'] > 0).sum())}，H2 跑赢 {int((H['H2夏普差'] > 0).sum())}")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    axes[0].hist(lam, bins=25, color=SERIES[0], edgecolor="white")
    axes[0].axvline(0, color=INK2, ls="--")
    axes[0].set_title(f"CSCV logit 分布（按夏普选优）PBO={pbo:.2f}", color=INK)
    axes[0].set_xlabel("λ = logit(OOS 相对排名)，≤0 表示样本内最优在样本外低于中位")
    axes[1].scatter(H["H1夏普差"], H["H2夏普差"], s=16, color=SERIES[0], alpha=0.75, edgecolor="white", linewidth=0.5)
    axes[1].axhline(0, color=INK2, lw=0.8)
    axes[1].axvline(0, color=INK2, lw=0.8)
    axes[1].set_xlabel("前半段夏普差")
    axes[1].set_ylabel("后半段夏普差")
    axes[1].set_title(f"前后半段夏普差（Spearman ρ={rho_h:.2f}）", color=INK)
    savefig(fig, "fig_cscv_halves.png")

    # ---------- 5) 起点敏感性 ----------
    q_starts = pd.date_range("2010-01-01", "2023-12-31", freq="QS")
    starts = [px.index[px.index.searchsorted(d)] for d in q_starts if d >= px.index[0]]
    srows = []
    for st in starts:
        bp = perf(run(bench_target, ret, st, MAIN_WIN[1]))
        for k in main_keys:
            r = run(trials[k], ret, st, MAIN_WIN[1])
            if r is None:
                continue
            p = perf(r)
            srows.append({"起点": st.date(), "指标": k[0], "规格": k[1], "夏普": p["夏普"], "最大回撤": p["最大回撤"],
                          "夏普差": p["夏普"] - bp["夏普"], "基准夏普": bp["夏普"], "基准MDD": bp["最大回撤"],
                          "MDD改善": p["最大回撤"] - bp["最大回撤"]})
    S = pd.DataFrame(srows)
    S.to_csv(OUT / "table_start_sensitivity.csv", encoding="utf-8-sig", index=False)
    S["起点"] = pd.to_datetime(S["起点"])
    req = S[S["起点"] <= "2016-12-31"]
    feas = req.drop_duplicates(["规格", "起点"]).groupby("规格")["起点"].agg(["count", "min"]).reindex(list(SPECS))
    feas["count"] = feas["count"].fillna(0).astype(int)
    feas["min"] = feas["min"].dt.date
    n_req = sum(1 for d in q_starts if d <= pd.Timestamp("2016-12-31"))
    md.append(f"\n## 表6 起点敏感性\n\n需求区间 2010Q1~2016Q4 共 {n_req} 个季度起点；数据始于 2011-09-30，"
              f"其中各规格可执行的起点数（同一规格 5 个指标相同）：\n")
    md.append(feas.rename(columns={"count": "可行起点数", "min": "最早可行起点"}).to_markdown())
    common = S[(S["起点"] >= "2019-01-01") & (S["规格"] != "单窗10年")]
    n_common = common["起点"].nunique()
    st_sum = common.groupby(["指标", "规格"]).agg(
        夏普中位=("夏普", "median"), 夏普最小=("夏普", "min"), 夏普最大=("夏普", "max"),
        夏普差中位=("夏普差", "median"), 跑赢比例=("夏普差", lambda x: (x > 0).mean()),
        MDD中位=("最大回撤", "median"), MDD最差=("最大回撤", "min"),
        MDD改善中位=("MDD改善", "median"))
    st_sum.to_csv(OUT / "table_start_summary_common.csv", encoding="utf-8-sig")
    md.append(f"\n### 表6b 公共可行起点 2019Q1~2023Q4（{n_common} 个季度起点，终点均为 2026-09-30）\n")
    md.append(fmt_table(st_sum, ("跑赢比例", "MDD中位", "MDD最差", "MDD改善中位"),
                        ("夏普中位", "夏普最小", "夏普最大", "夏普差中位")))
    if len(req):
        rq = req.groupby(["指标", "规格"]).agg(起点数=("夏普", "size"), 夏普差中位=("夏普差", "median"),
                                             跑赢比例=("夏普差", lambda x: (x > 0).mean()),
                                             MDD中位=("最大回撤", "median"), 基准MDD中位=("基准MDD", "median"))
        md.append("\n### 表6c 需求区间内（≤2016Q4）实际可行起点上的结果\n")
        md.append(fmt_table(rq, ("跑赢比例", "MDD中位", "基准MDD中位"), ("夏普差中位",), ("起点数",)))

    bcommon = S[(S["起点"] >= "2019-01-01")].drop_duplicates("起点")
    fig, axes = plt.subplots(2, 1, figsize=(15, 9.5), sharex=True)
    order = [(i, s) for i in IND_ALL for s in SPECS if s != "单窗10年"]
    for ax, metric, bcol, lab in [(axes[0], "夏普", "基准夏普", "年化夏普"), (axes[1], "最大回撤", "基准MDD", "最大回撤")]:
        data = [common[(common["指标"] == i) & (common["规格"] == s)][metric].values for i, s in order]
        bp_ = ax.boxplot([bcommon[bcol].values] + data, patch_artist=True, widths=0.6,
                         medianprops={"color": INK}, flierprops={"markersize": 3})
        for j, patch in enumerate(bp_["boxes"]):
            patch.set_facecolor("#c3c2b7" if j == 0 else SERIES[IND_ALL.index(order[j - 1][0])])
            patch.set_alpha(0.85)
            patch.set_edgecolor("white")
        ax.axhline(np.median(bcommon[bcol]), color=INK2, ls="--", lw=1)
        ax.set_ylabel(lab)
    axes[1].set_xticks(range(1, len(order) + 2), ["基准"] + [f"{i}·{s}" for i, s in order], rotation=90, fontsize=8)
    handles = [plt.Rectangle((0, 0), 1, 1, color=SERIES[k]) for k in range(5)] + [plt.Rectangle((0, 0), 1, 1, color="#c3c2b7")]
    axes[0].legend(handles, IND_ALL + ["基准"], ncol=6, frameon=False, loc="upper left")
    axes[0].set_title(f"起点敏感性：{n_common} 个季度起点（2019Q1~2023Q4）→ 2026-09-30，主阈值", color=INK)
    savefig(fig, "fig_start_sensitivity.png")

    # ---------- 6) 子区间 ----------
    sub_rows = []
    for name, (a, b) in SUBPERIODS.items():
        bp = perf(run(bench_target, ret, a, b))
        sub_rows.append({"子区间": name, "指标": "基准", "规格": "买入持有", "区间收益": (1 + run(bench_target, ret, a, b)["daily"]).prod() - 1,
                         "最大回撤": bp["最大回撤"], "夏普": bp["夏普"], "平均仓位": 1.0})
        for k in main_keys:
            r = run(trials[k], ret, a, b)
            if r is None:
                sub_rows.append({"子区间": name, "指标": k[0], "规格": k[1]})
                continue
            p = perf(r)
            sub_rows.append({"子区间": name, "指标": k[0], "规格": k[1], "区间收益": (1 + r["daily"]).prod() - 1,
                             "最大回撤": p["最大回撤"], "夏普": p["夏普"], "平均仓位": p["平均仓位"]})
    SUB = pd.DataFrame(sub_rows)
    SUB.to_csv(OUT / "table_subperiods.csv", encoding="utf-8-sig", index=False)
    md.append("\n## 表7 子区间表现（主阈值；“—”= 该规格在此区间信号不足）\n")
    for name in SUBPERIODS:
        t = SUB[SUB["子区间"] == name].set_index(["指标", "规格"]).drop(columns="子区间")
        ret_pv = t["区间收益"].drop(("基准", "买入持有")).unstack("规格").reindex(index=IND_ALL, columns=list(SPECS))
        mdd_pv = t["最大回撤"].drop(("基准", "买入持有")).unstack("规格").reindex(index=IND_ALL, columns=list(SPECS))
        bt = t.loc[("基准", "买入持有")]
        md.append(f"\n### {name}：基准区间收益 {bt['区间收益'] * 100:.1f}%，最大回撤 {bt['最大回撤'] * 100:.1f}%\n")
        md.append("区间收益：\n")
        md.append(ret_pv.map(lambda v: "—" if pd.isna(v) else f"{v * 100:.1f}%").to_markdown())
        md.append("\n最大回撤：\n")
        md.append(mdd_pv.map(lambda v: "—" if pd.isna(v) else f"{v * 100:.1f}%").to_markdown())

    # ---------- 7) 指标一致性 ----------
    md.append("\n## 表8 指标一致性\n")
    corr_specs = ["A_均值", "B_均值", "C_均值", "单窗3年", "扩展窗口"]
    fig, axes = plt.subplots(1, len(corr_specs), figsize=(20, 4.4))
    for ax, spec in zip(axes, corr_specs):
        m = pd.concat({i: sigs[(i, spec)] for i in INDICATORS}, axis=1).dropna()
        c = m.corr()
        md.append(f"\n**{spec}**（贵度分位相关，{m.index[0].date()}~{m.index[-1].date()}，{len(m)} 日）\n")
        md.append(c.round(2).to_markdown())
        im = ax.imshow(c.values, cmap=DIVERGING, vmin=-1, vmax=1)
        for (i, j), v in np.ndenumerate(c.values):
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=9, color=INK)
        ax.set_xticks(range(4), list(INDICATORS))
        ax.set_yticks(range(4), list(INDICATORS))
        ax.set_title(f"{spec}\n{m.index[0].date()}~", color=INK, fontsize=10)
        ax.grid(False)
    fig.colorbar(im, ax=axes, shrink=0.8, label="相关系数")
    savefig(fig, "fig_indicator_corr.png")

    kp_rows = []
    for lab, d in KEY_POINTS.items():
        d = pd.Timestamp(d)
        for spec in ["A_均值", "B_均值", "C_均值", "单窗3年", "单窗5年", "扩展窗口"]:
            row = {"关键点": lab, "规格": spec}
            for ind in IND_ALL:
                v = sigs[(ind, spec)].get(d, np.nan)
                row[ind] = "—" if pd.isna(v) else f"{v * 100:.0f}" + ("贵" if v >= 0.8 else "廉" if v <= 0.2 else "")
            kp_rows.append(row)
    KP = pd.DataFrame(kp_rows).set_index(["关键点", "规格"])
    KP.to_csv(OUT / "table_key_points.csv", encoding="utf-8-sig")
    md.append("\n### 表8b 关键高低点的贵度分位（0~100；≥80 标“贵”，≤20 标“廉”；高点应偏贵、低点应偏廉）\n")
    md.append(KP.to_markdown())

    # 方向一致性统计：主区间内四指标同时 ≥0.8 或 ≤0.2 的天数占比、两两仓位方向分歧
    agree = {}
    for spec in ["A_均值", "B_均值", "C_均值", "单窗3年", "扩展窗口"]:
        m = pd.concat({i: sigs[(i, spec)] for i in INDICATORS}, axis=1).dropna()
        zone = np.sign((m <= 0.2).astype(int) - (m >= 0.8).astype(int))  # +1 廉, -1 贵, 0 中性
        agree[spec] = {"区间起点": m.index[0].date(), "四指标同区(全廉/全贵/全中性)": (zone.nunique(axis=1) == 1).mean(),
                       "存在一廉一贵的直接矛盾": ((zone == 1).any(axis=1) & (zone == -1).any(axis=1)).mean()}
    md.append("\n### 表8c 方向一致性（按日统计占比）\n")
    md.append(pd.DataFrame(agree).T.to_markdown())

    # ---------- 8) 窗口组合 / 聚合方式差异 ----------
    md.append("\n## 表9 窗口组合与聚合方式差异\n")
    div_rows = {}
    st, en = MAIN_WIN
    for ind in IND_ALL:
        s = {k: sigs[(ind, k)].loc[st:en] for k in ENSEMBLE_SPECS}
        p = {k: trials[(ind, k, main_th)].loc[st:en] for k in ENSEMBLE_SPECS}
        div_rows[ind] = {
            "|A−B|均值": (s["A_均值"] - s["B_均值"]).abs().mean(),
            "|A−C|均值": (s["A_均值"] - s["C_均值"]).abs().mean(),
            "|B−C|均值": (s["B_均值"] - s["C_均值"]).abs().mean(),
            "|均值−中位|A": (s["A_均值"] - s["A_中位数"]).abs().mean(),
            "|均值−中位|B": (s["B_均值"] - s["B_中位数"]).abs().mean(),
            "|均值−中位|C": (s["C_均值"] - s["C_中位数"]).abs().mean(),
            "A/C仓位差≥50%天数占比": ((p["A_均值"] - p["C_均值"]).abs() >= 0.5).mean(),
            "B/C仓位差≥50%天数占比": ((p["B_均值"] - p["C_均值"]).abs() >= 0.5).mean(),
        }
    md.append(pd.DataFrame(div_rows).T.round(3).to_markdown())

    # 留一法：从组合中去掉某个窗口后夏普与仓位的变化（诊断用，不参与选优）
    loo = []
    for ind in INDICATORS:
        for combo in ("A", "B", "C"):
            wins = SPECS[f"{combo}_均值"][1]
            base_sig = sigs[(ind, f"{combo}_均值")]
            base = perf(run(position_linear(base_sig, *MAIN_TH), ret, *MAIN_WIN))
            for w in wins:
                rest = [x for x in wins if x != w]
                m = pd.concat([pcts[ind]["win"][x] for x in rest], axis=1)
                sig = m.mean(axis=1).where(m.notna().sum(axis=1) >= MIN_WINDOWS)
                r = run(position_linear(sig, *MAIN_TH), ret, *MAIN_WIN)
                row = {"指标": ind, "组合": combo, "去掉窗口": f"{w}年", "完整组合夏普": base["夏普"]}
                if r is None:
                    row.update({"去掉后夏普": np.nan, "夏普变化": np.nan, "平均|仓位变化|": np.nan})
                else:
                    pp = perf(r)
                    row.update({"去掉后夏普": pp["夏普"], "夏普变化": pp["夏普"] - base["夏普"],
                                "平均|仓位变化|": (r["pos"] - run(position_linear(base_sig, *MAIN_TH), ret, *MAIN_WIN)["pos"]).abs().mean()})
                loo.append(row)
    LOO = pd.DataFrame(loo).set_index(["指标", "组合", "去掉窗口"])
    LOO.to_csv(OUT / "table_leave_one_window_out.csv", encoding="utf-8-sig")
    md.append("\n### 表9b 留一窗口诊断（均值聚合、主阈值、主区间；诊断用，不计入候选）\n")
    md.append(LOO.round(3).to_markdown())

    # 各单窗口贵度分位（主区间均值）——看长短窗口的结构性偏差
    lvl = {}
    for ind in INDICATORS:
        lvl[ind] = {f"{w}年": pcts[ind]["win"][w].loc[st:en].mean() for w in sorted(pcts[ind]["win"])}
        lvl[ind]["扩展"] = pcts[ind]["exp"].loc[st:en].mean()
    md.append("\n### 表9c 各单窗口贵度分位在主区间的平均值（>0.5 偏贵，<0.5 偏廉；12年窗口仅 2024-02 起有值）\n")
    md.append(pd.DataFrame(lvl).T.round(3).to_markdown())

    fig, axes = plt.subplots(5, 1, figsize=(14, 17), sharex=True)
    wins_plot = [2, 3, 5, 7, 10, 12]
    for ax, ind in zip(axes[:4], INDICATORS):
        for j, w in enumerate(wins_plot):
            ax.plot(pcts[ind]["win"][w].loc["2013":], color=SERIES[j], lw=1.1, label=f"{w}年")
        ax.plot(pcts[ind]["exp"].loc["2013":], color=SERIES[6], lw=1.1, ls="--", label="扩展")
        ax.axhspan(0.8, 1.0, color="#e34948", alpha=0.06)
        ax.axhspan(0.0, 0.2, color="#2a78d6", alpha=0.06)
        ax.set_ylabel(f"{ind} 贵度分位")
        ax.set_ylim(0, 1)
    axes[0].legend(ncol=7, frameon=False, loc="upper left", fontsize=9)
    axes[0].set_title("各窗口贵度分位（越高越贵；阴影 = 主阈值 20/80 区）", color=INK)
    axes[4].plot(px.loc["2013":], color=INK, lw=1.1)
    axes[4].set_ylabel("沪深300 收盘")
    for lab, d in KEY_POINTS.items():
        for ax in axes:
            ax.axvline(pd.Timestamp(d), color=INK2, lw=0.6, ls=":")
    savefig(fig, "fig_window_percentiles.png")

    # ---------- 9) 净值图 ----------
    fig, axes = plt.subplots(5, 1, figsize=(13, 18), sharex=True)
    show = ["A_均值", "B_均值", "C_均值", "单窗3年", "单窗5年", "扩展窗口"]
    bnav = (1 + run(bench_target, ret, *MAIN_WIN)["daily"]).cumprod()
    for ax, ind in zip(axes, IND_ALL):
        ax.plot(bnav, color=INK, lw=1.6, label="基准")
        for j, s in enumerate(show):
            r = run(trials[(ind, s, main_th)], ret, *MAIN_WIN)
            ax.plot((1 + r["daily"]).cumprod(), color=SERIES[j], lw=1.2, label=s)
        ax.set_title(f"{ind}（阈值 {main_th}）", color=INK, loc="left")
        ax.set_ylabel("净值")
    axes[0].legend(ncol=7, frameon=False, fontsize=9)
    savefig(fig, "fig_nav_main.png")

    # ---------- 10) 稳健性：仓位映射 & 空仓收益 ----------
    rob = {}
    for k in main_keys:
        ind, spec, _ = k
        b0 = perf(run(bench_target, ret, *MAIN_WIN))
        r1 = run(position_tier3(sigs[(ind, spec)], *MAIN_TH), ret, *MAIN_WIN)
        r2 = run(trials[k], ret, *MAIN_WIN, cash_annual=CASH_ANNUAL_ALT)
        if r1 is None:
            continue
        b2 = perf(run(bench_target, ret, *MAIN_WIN, cash_annual=CASH_ANNUAL_ALT))
        rob[(ind, spec)] = {"线性映射夏普差": T_main.loc[k, "夏普差"],
                            "三档映射夏普差": perf(r1)["夏普"] - b0["夏普"],
                            "三档映射交易次数": perf(r1)["交易次数"],
                            "空仓2%：年化": perf(r2)["年化收益"], "空仓2%：夏普差(超额rf)": perf(r2)["夏普"] - b2["夏普"]}
    ROB = pd.DataFrame(rob).T
    ROB.index.names = ["指标", "规格"]
    ROB.to_csv(OUT / "table_robustness_mapping_cash.csv", encoding="utf-8-sig")
    md.append("\n## 表10 稳健性：仓位映射（线性10%档 vs 三档100/50/0）与空仓收益（0 vs 年化2%）\n")
    md.append(f"空仓 2% 口径下，夏普按超额无风险（2%）计算；基准年化 {perf(run(bench_target, ret, *MAIN_WIN, cash_annual=CASH_ANNUAL_ALT))['年化收益'] * 100:.2f}%\n")
    md.append(fmt_table(ROB, ("空仓2%：年化",), ("线性映射夏普差", "三档映射夏普差", "空仓2%：夏普差(超额rf)"), ("三档映射交易次数",)))

    # ---------- 11) 分类（规则在看结果前写定） ----------
    cls = {}
    for ind in IND_ALL:
        for spec in SPECS:
            k = (ind, spec, main_th)
            row = T_main.loc[k]
            if pd.isna(row.get("夏普")):
                cls[(ind, spec)] = {"类别": "无法评估（主区间信号不足）"}
                continue
            sd = float(row["夏普差"])
            n_th = int(SM.loc[(ind, spec), "跑赢基准阈值数"])
            win_start = float(st_sum.loc[(ind, spec), "跑赢比例"])
            h = H.loc[k]
            both_halves = bool(h["H1夏普差"] > 0 and h["H2夏普差"] > 0)
            subs = SUB[(SUB["指标"] == ind) & (SUB["规格"] == spec)].dropna(subset=["夏普"])
            bsubs = SUB[(SUB["指标"] == "基准")].set_index("子区间")["夏普"]
            sub_win = np.mean([r["夏普"] > bsubs[r["子区间"]] for _, r in subs.iterrows()]) if len(subs) else np.nan
            checks = {"阈值≥3/4跑赢": n_th >= 3, "起点≥75%跑赢": win_start >= 0.75,
                      "前后半段均跑赢": both_halves, "子区间≥半数跑赢": (sub_win >= 0.5) if not np.isnan(sub_win) else False}
            if sd <= 0:
                c = "无效"
            elif all(checks.values()):
                c = "稳健有效（样本内）"
            else:
                c = "可能过拟合"
            act = run(trials[k], ret, *MAIN_WIN)["daily"] - bd
            cls[(ind, spec)] = {"类别": c, "主区间夏普差": sd,
                                "主动IR(年化)": act.mean() / act.std() * math.sqrt(ANN), "主动PSR(未校正)": psr(act, 0.0), "跑赢阈值数": n_th, "起点跑赢比例": win_start,
                                "H1夏普差": h["H1夏普差"], "H2夏普差": h["H2夏普差"], "子区间跑赢比例": sub_win,
                                "未通过": "、".join(n for n, ok in checks.items() if not ok) if sd > 0 else "主区间夏普不高于基准"}
    CLS = pd.DataFrame(cls).T
    CLS.index.names = ["指标", "规格"]
    CLS.to_csv(OUT / "table_classification.csv", encoding="utf-8-sig")
    md.append("\n## 表11 分类结果（判定规则见报告；主阈值）\n")
    md.append(fmt_table(CLS, ("起点跑赢比例", "子区间跑赢比例", "主动PSR(未校正)"),
                        ("主区间夏普差", "主动IR(年化)", "H1夏普差", "H2夏普差"), ("跑赢阈值数",)))
    md.append("\n分类计数：\n")
    md.append(CLS["类别"].value_counts().to_markdown())

    # ---------- 12) 最新读数 ----------
    last = px.index[-1]
    cur = pd.DataFrame({ind: {spec: sigs[(ind, spec)].iloc[-1] for spec in SPECS} for ind in IND_ALL})
    md.append(f"\n## 表12 最新贵度分位（{last.date()}，0~1，越高越贵）与主阈值目标仓位\n")
    md.append(cur.round(3).to_markdown())
    curpos = pd.DataFrame({ind: {spec: trials[(ind, spec, main_th)].iloc[-1] for spec in SPECS} for ind in IND_ALL})
    md.append("\n")
    md.append(curpos.map(lambda v: "—" if pd.isna(v) else f"{v * 100:.0f}%").to_markdown())

    header = (f"# 自动生成的结果表（backtest.py）\n\n样本 {px.index[0].date()} ~ {px.index[-1].date()}，"
              f"{len(px)} 个交易日；年化因子 {ANN:.1f}（样本实际年均交易日）；单边成本 {COST * 100:.1f}%；"
              f"主口径空仓收益 {CASH_ANNUAL * 100:.0f}%。\n")
    (OUT / "results_tables.md").write_text(header + "\n".join(md), encoding="utf-8")
    print(f"done. trials={n_trials}, outputs in {OUT}")


ANN = 243.0
if __name__ == "__main__":
    main()
