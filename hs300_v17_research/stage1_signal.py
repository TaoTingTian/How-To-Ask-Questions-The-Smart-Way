"""阶段一：信号层检验（与策略路径无关的大样本检验）。
问题：在估值分 V 已知的前提下，指标的超卖/超买信号是否还能预测未来 20/60 日收益？
方法：在同一估值区间内，比较信号日与全部日的前瞻收益；Newey-West(HAC, lag=h) t 值；统计独立事件数。"""
import numpy as np, pandas as pd
from signals import raw, NAMES, DEFAULT, grid, PX

df = pd.read_pickle("out/panel.pkl")
lc = np.log(PX.close)
fwd = {h: (lc.shift(-h) - lc) for h in (20, 60)}

def nw_t(y, x, lag):
    """y = a + b·x 的 b 的 HAC t 值。"""
    X = np.c_[np.ones(len(x)), x]; b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b; Xe = X * e[:, None]
    S = Xe.T @ Xe
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1); G = Xe[L:].T @ Xe[:-L]; S += w * (G + G.T)
    XtXi = np.linalg.inv(X.T @ X); cov = XtXi @ S @ XtXi
    return b[1], b[1] / np.sqrt(cov[1, 1])

def episodes(sig, gap=20):
    d = np.flatnonzero(sig.values)
    return 0 if len(d) == 0 else 1 + int((np.diff(d) > gap).sum())

rows = []
regimes = {"buy": {"全部": df.V.notna(), "V<50": df.V < 50},
           "sell": {"全部": df.V.notna(), "V≥50": df.V >= 50}}
for name in NAMES:
    for params in grid(name):
        b, s = raw(name, *params)
        for side, sig in (("buy", b), ("sell", s)):
            for rg, mask in regimes[side].items():
                for h, f in fwd.items():
                    m = mask.reindex(lc.index).fillna(False) & f.notna()
                    y = f[m].values; x = sig[m].fillna(False).astype(float).values
                    if x.sum() < 5: continue
                    coef, t = nw_t(y, x, h)
                    rows.append(dict(指标=name, 参数=params, 默认=params == DEFAULT[name], 方向=side, 区间=rg, h=h,
                                     信号天数=int(x.sum()), 独立事件=episodes(sig[m].fillna(False)),
                                     超额收益=coef * (1 if side == "buy" else -1), t值=t * (1 if side == "buy" else -1)))
R = pd.DataFrame(rows)
R.to_pickle("out/stage1.pkl")
# 汇总：默认参数 + 网格稳健性
def summ(g):
    d = g[g.默认]
    return pd.Series({"默认超额%": d.超额收益.iloc[0] * 100 if len(d) else np.nan, "默认t": d.t值.iloc[0] if len(d) else np.nan,
                      "默认事件数": d.独立事件.iloc[0] if len(d) else np.nan,
                      "网格中位超额%": g.超额收益.median() * 100, "网格同号比例": (np.sign(g.超额收益) > 0).mean(),
                      "网格t>2比例": (g.t值 > 2).mean()})
S = R.groupby(["方向", "区间", "h", "指标"]).apply(summ, include_groups=False).round(2)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
print(S)
S.to_csv("out/stage1_summary.csv", encoding="utf-8-sig")
