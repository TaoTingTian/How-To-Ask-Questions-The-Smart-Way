"""各指标中枢“各走各的”：由四个经济驱动因素推导出每个估值指标的中枢路径。

驱动因素（均为中枢，即长期水平；短期波动、危机、假回归仍来自 gen.py 的基准路径，保证配对比较）：
  y    10 年国债收益率
  rp   投资者要求的股权风险溢价（情绪 / 风险偏好）
  ROE  净资产收益率
  p    分红率

经济关系（恒等式 + 估值规律）：
  可持续增长    g_pot = ROE × (1 − p)；盈利增速变化 Δg = κ · Δg_pot                (κ = 0.5，扣除摊薄与再投资效率)
  PE 中枢       Δln PE* = D · (−Δy − Δrp + Δg) + λ · ln(p / p0)                   (D = 12，股票久期)
                λ = D·κ·ROE0·p0，使分红率变化在基准 ROE 下对估值中性（MM 定理）
  PB 中枢       PB* = PE* × ROE                                                   (恒等式)
  股息率中枢    DY* = p / PE*                                                      (恒等式)
  盈利收益率    EY ≈ ROE5 / PB ≈ 1 / PE                                           (恒等式)
  股债利差      ERP = EY − y                                                       (定义)
  每股收益      ln EPS 额外累加 Δg（盈利能力变化影响价格中枢的增长速度）
"""
import numpy as np
import pandas as pd

import gen

YEAR = 252
C0 = np.log(13.0)
ROE0, P0, Y0 = 0.12, 0.33, 0.034
D_EQ, KAPPA = 12.0, 0.5
LAMBDA = D_EQ * KAPPA * ROE0 * P0
G0 = 0.04            # 基准每股收益增速（贴近沪深300 实际的 3%–4%）


def ramp(n, kind, start_y=9.0, dur_y=12.0, jump_y=12.0, jump_days=42):
    t = np.arange(n)
    if kind == "fast":
        s = int(jump_y * YEAR)
        x = np.clip((t - s) / jump_days, 0, 1)
        return 0.5 - 0.5 * np.cos(np.pi * x)
    s, e = int(start_y * YEAR), int((start_y + dur_y) * YEAR)
    return np.clip((t - s) / (e - s), 0, 1)


def analytic(dr):
    """终点的理论中枢变化（不含噪声）。dr: dict(y, rp, roe, p) 的终值变化。"""
    dy, drp, droe, dp = dr.get("y", 0.0), dr.get("rp", 0.0), dr.get("roe", 0.0), dr.get("p", 0.0)
    roe, p = ROE0 + droe, P0 + dp
    dg = KAPPA * (roe * (1 - p) - ROE0 * (1 - P0))
    dlpe = D_EQ * (-dy - drp + dg) + LAMBDA * np.log(p / P0)
    pe = np.exp(dlpe)
    return dict(pe=pe - 1, pb=pe * roe / ROE0 - 1, dy=(p / P0) / pe - 1, ey=1 / pe - 1,
                erp=(1 / (13 * pe) - (Y0 + dy)) - (1 / 13 - Y0), g=dg, y=dy, rp=drp, roe=droe, p=dp)


def solve_rp(dr, target_dlpe):
    """给定其他驱动与 PE 中枢目标，求风险溢价的变化（风险溢价吸收剩余差额）。"""
    dy, droe, dp = dr.get("y", 0.0), dr.get("roe", 0.0), dr.get("p", 0.0)
    roe, p = ROE0 + droe, P0 + dp
    dg = KAPPA * (roe * (1 - p) - ROE0 * (1 - P0))
    return -dy + dg + (LAMBDA * np.log(p / P0) - target_dlpe) / D_EQ


def make_drift_path(seed, dr, speeds=None, base=None):
    """dr: 终值变化 dict(y, rp, roe, p)；speeds: 每个驱动 'slow' 或 'fast'（ROE、分红率只能慢）。
    base: 可传入已生成的基准 (df, meta) 以复用。返回 (df, meta, centers)。"""
    speeds = speeds or {}
    if base is None:
        df_b, meta = gen.make_valid_path("base", seed, dict(g=G0))
    else:
        df_b, meta = base
    n = len(df_b)
    sp = {k: ramp(n, speeds.get(k, "slow")) for k in ("y", "rp", "roe", "p")}
    dy = dr.get("y", 0.0) * sp["y"]
    drp = dr.get("rp", 0.0) * sp["rp"]
    roe_c = ROE0 + dr.get("roe", 0.0) * sp["roe"]
    p_c = P0 + dr.get("p", 0.0) * sp["p"]
    dg = KAPPA * (roe_c * (1 - p_c) - ROE0 * (1 - P0))
    dlpe = D_EQ * (-dy - drp + dg) + LAMBDA * np.log(p_c / P0)

    d = df_b.dev.values
    pe = np.exp(C0 + dlpe + d)
    roe = df_b.roe.values * roe_c / ROE0
    payout = df_b.dy.values * df_b.pe.values * p_c / P0
    y = np.maximum(df_b.y.values + dy, 0.005)
    eps_b = df_b.close.values / df_b.pe.values
    eps = eps_b * np.exp(np.cumsum(dg) / YEAR)
    close = pe * eps
    ratio = close / df_b.close.values
    df = df_b.copy()
    df["close"] = close
    df["open"] = df_b.open.values * np.r_[ratio[0], ratio[:-1]]
    df["high"] = np.maximum(df_b.high.values * ratio, np.maximum(df["open"].values, close))
    df["low"] = np.minimum(df_b.low.values * ratio, np.minimum(df["open"].values, close))
    df["pe"] = pe
    df["roe"] = roe
    df["pb"] = pe * roe
    df["dy"] = payout / pe
    df["y"] = y
    df["center"] = np.exp(C0 + dlpe)
    tr = np.empty(n)
    tr[0] = 1000.0
    tr[1:] = tr[0] * np.cumprod(close[1:] / close[:-1] * (1 + df["dy"].values[:-1] / YEAR))
    df["tr"] = tr
    pe_c = np.exp(C0 + dlpe)
    centers = dict(pe=pe_c, pb=pe_c * roe_c, dy=p_c / pe_c, y=Y0 + dy, erp=1 / pe_c - (Y0 + dy),
                   roe=roe_c, p=p_c, g=G0 + dg, price=eps * pe_c, dlpe=dlpe)
    return df, meta, centers
