"""阶段三：防过拟合评估。
1) 默认参数相对基线的增量；2) 3×3 参数邻域中优于基线的比例（参数高原）；
3) 样本内/样本外方向一致性；4) 循环平移安慰剂分位；5) CSCV 回测过拟合概率 PBO；6) 紧缩夏普 DSR。"""
import itertools, math
import numpy as np, pandas as pd

R = pd.read_pickle("out/stage2.pkl")
rets = pd.read_pickle("out/stage2_rets.pkl")
base = R[R.槽位 == "基线"].iloc[0]
for c in ["IRR", "TWR年化", "Sharpe", "最大回撤", "Calmar", "IS_Sharpe", "OOS_Sharpe", "IS_TWR", "OOS_TWR"]:
    R["Δ" + c] = R[c] - base[c]

real = R[~R.槽位.str.startswith("P_") & ~R.槽位.isin(["基线"])]
plc = R[R.槽位.str.startswith("P_")]
pmap = {"A回投过滤": "P_A", "B止盈-超买确认": "P_B", "B'止盈-超买回落": "P_B'", "C定投择时": "P_C"}

rows = []
for (slot, name), g in real.groupby(["槽位", "指标"], sort=False):
    d = g[g.默认 == True]
    d = d.iloc[0] if len(d) else g.iloc[len(g) // 2]
    row = dict(槽位=slot, 指标=name, 参数=d.参数, ΔIRR=d.ΔIRR, ΔSharpe=d.ΔSharpe, Δ回撤=d.Δ最大回撤,
               ΔCalmar=d.ΔCalmar, ΔIS_Sharpe=d.ΔIS_Sharpe, ΔOOS_Sharpe=d.ΔOOS_Sharpe,
               网格优于基线比例=(g.ΔCalmar > 0).mean() if len(g) > 1 else np.nan,
               网格ΔCalmar中位=g.ΔCalmar.median(), 网格ΔIRR中位=g.ΔIRR.median(),
               IS_OOS同向=np.sign(d.ΔIS_Sharpe) == np.sign(d.ΔOOS_Sharpe))
    if slot in pmap:
        pg = plc[(plc.槽位 == pmap[slot]) & (plc.指标 == name)]
        row["安慰剂分位"] = (pg.Calmar < d.Calmar).mean()
        row["安慰剂ΔCalmar中位"] = (pg.Calmar - base.Calmar).median()
    rows.append(row)
T = pd.DataFrame(rows)
pd.set_option("display.width", 260); pd.set_option("display.max_rows", 300); pd.set_option("display.max_columns", 30)
print("基线:", base[["IRR", "TWR年化", "Sharpe", "最大回撤", "Calmar", "IS_Sharpe", "OOS_Sharpe"]].to_dict())
print(T.round(3).to_string())
T.to_pickle("out/stage3_table.pkl")


# ---------- CSCV / PBO（Bailey, Borwein, López de Prado & Zhu 2017） ----------
def pbo(M, S=16):
    """M: T×N 日收益矩阵。按时间切 S 块，所有 C(S,S/2) 组合中，样本内最优策略在样本外的相对排名 ≤ 中位的比例。"""
    T_, N = M.shape
    blocks = np.array_split(np.arange(T_), S)
    lam = []
    for comb in itertools.combinations(range(S), S // 2):
        is_idx = np.concatenate([blocks[k] for k in comb])
        oos_idx = np.concatenate([blocks[k] for k in range(S) if k not in comb])
        sr = lambda x: x.mean(0) / (x.std(0) + 1e-12)
        best = np.argmax(sr(M[is_idx]))
        o = sr(M[oos_idx])
        w = (o < o[best]).sum() / N + 0.5 / N
        lam.append(math.log(w / (1 - w)))
    lam = np.array(lam)
    return (lam <= 0).mean(), lam


keys = [k for k in rets if not k[0].startswith("P_")]
M = np.column_stack([rets[k] for k in keys])
start = np.argmax(np.abs(M).sum(1) > 0) + 5
M = M[start:]
p_all, _ = pbo(M)
print(f"\nPBO（全部 {M.shape[1]} 个真实变体）= {p_all:.2f}")
res_pbo = {"全部": p_all}
for slot in real.槽位.unique():
    ks = [i for i, k in enumerate(keys) if k[0] in (slot, "基线")]
    if len(ks) > 3:
        res_pbo[slot] = pbo(M[:, ks])[0]
print(pd.Series(res_pbo).round(2))
pd.to_pickle(res_pbo, "out/pbo.pkl")


# ---------- 紧缩夏普（Bailey & López de Prado 2014） ----------
from statistics import NormalDist
N_ = NormalDist()


def dsr(r, n_trials, sr_var):
    r = r[r != 0]
    T_ = len(r); sr = r.mean() / r.std()
    g3 = ((r - r.mean()) ** 3).mean() / r.std() ** 3; g4 = ((r - r.mean()) ** 4).mean() / r.std() ** 4
    emc = 0.5772156649
    sr0 = math.sqrt(sr_var) * ((1 - emc) * N_.inv_cdf(1 - 1 / n_trials) + emc * N_.inv_cdf(1 - 1 / (n_trials * math.e)))
    z = (sr - sr0) * math.sqrt(T_ - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)
    return N_.cdf(z), sr * math.sqrt(244), sr0 * math.sqrt(244)


srs = M.mean(0) / M.std(0)
best = int(np.argmax(srs))
bi = keys.index(("基线", "V1.6", "-", "-"))
d_best = dsr(M[:, best], M.shape[1], srs.var())
print("\n夏普最高变体:", keys[best], "DSR=%.2f 年化SR=%.2f 多重检验门槛SR=%.2f" % d_best)
d_base = dsr(M[:, bi], M.shape[1], srs.var())
print("基线 V1.6:", "DSR=%.2f 年化SR=%.2f 门槛=%.2f" % d_base)
pd.to_pickle({"best": (keys[best], d_best), "base": d_base, "n": M.shape[1]}, "out/dsr.pkl")
