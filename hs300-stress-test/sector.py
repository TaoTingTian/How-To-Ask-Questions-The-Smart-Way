"""多行业 + 权重迁移模拟器，检验“成分结构漂移”与行业中性 V。

市场：5 个行业，各自估值中枢固定（除非情景另行设定），共享同一条市场偏离路径（含危机、假回归、波动率聚集，
来自 gen.py 的基准路径），按行业弹性 β 放大或缩小，另加行业自身的均值回归噪声。
指数：按市值权重汇总——指数 PE = 1 / Σ(w / PE_i)，PB = 1 / Σ(w / PB_i)，股息率 = Σ w × DY_i；
指数日收益 = Σ w_{t−1} × 行业收益。权重由情景外生给定（相当于指数调样），或随行业市值自然变化。

“真实偏离” = log(指数 PE) − log(当前权重下各行业中枢汇总的指数中枢)，只来自各行业自身的贵贱，不含成分变化。

V 的构造：
  orig     原版：指数层面 4 项分位（盈利收益率、1/PB、股息率、股债利差），5/10 年平均
  ierp     原版 4 项中用隐含风险溢价替换股债利差（上一轮推荐的结构）
  cw       固定权重口径：每 5 个交易日用“当前权重”重算历史指数估值，再取分位
  neutral  行业中性：各行业用自身历史算 4 项分位，再按当前市值权重加总
  oracle   理想 V（真实偏离的分位），仅作上限
"""
import json
import multiprocessing as mp
import os
import time

import numpy as np
import pandas as pd

import engine as En
import gen
import indicators as I
from engine import START, YEAR

HERE = os.path.dirname(os.path.abspath(__file__))
VERS = ["1.6", "1.7", "1.8", "1.9"]
METHODS = ["orig", "ierp", "cw", "neutral", "oracle"]

SECT = ["银行", "周期地产", "消费", "医药", "科技新能源"]
PE0 = np.array([6.5, 10.0, 28.0, 32.0, 38.0])
ROE0 = np.array([0.14, 0.11, 0.18, 0.13, 0.10])
PAY0 = np.array([0.30, 0.35, 0.45, 0.30, 0.15])
BETA = np.array([0.8, 1.1, 1.0, 1.0, 1.3])
W_START = np.array([0.35, 0.30, 0.15, 0.08, 0.12])
W_MILD = np.array([0.22, 0.25, 0.20, 0.12, 0.21])
W_STRONG = np.array([0.15, 0.20, 0.22, 0.15, 0.28])
W_VALUE = np.array([0.45, 0.30, 0.10, 0.05, 0.10])

SCEN = [
    # key, 名称, 说明, 目标权重, 速度, 行业中枢变化（终值相对倍数）, 自然迁移
    ("N0", "基准：权重不变", "各行业权重固定", W_START, "slow", None, False),
    ("N1", "温和迁移", "12 年内银行 35%→22%、科技 12%→21% 等，指数 PE 中枢约 +27%", W_MILD, "slow", None, False),
    ("N2", "强迁移", "12 年内银行 35%→15%、科技 12%→28% 等，指数 PE 中枢约 +50%", W_STRONG, "slow", None, False),
    ("N3", "反向迁移（价值化）", "12 年内银行 35%→45%、消费医药科技下降，指数 PE 中枢约 −11%", W_VALUE, "slow", None, False),
    ("N4", "快速调样", "强迁移在 3 个月内完成（第 12 年）", W_STRONG, "fast", None, False),
    ("N5", "迁移 + 行业真实重估", "温和迁移，同时科技行业自身中枢 +30%、银行 −20%", W_MILD, "slow", np.array([0.8, 1.0, 1.0, 1.0, 1.3]), False),
    ("N6", "自然迁移（增长差异）", "无外生调样；科技每股收益每年快 5%、银行慢 3%，权重随市值自然变化", None, "slow", None, True),
]
GROWTH_N6 = np.array([-0.03, -0.01, 0.01, 0.02, 0.05])


def ramp(n, kind, start_y=9.0, dur_y=12.0, jump_y=12.0, jump_days=63):
    t = np.arange(n)
    if kind == "fast":
        s = int(jump_y * YEAR)
        return np.clip((t - s) / jump_days, 0, 1)
    s, e = int(start_y * YEAR), int((start_y + dur_y) * YEAR)
    return np.clip((t - s) / (e - s), 0, 1)


def make_sector_path(seed, scen):
    key, name, desc, wt, speed, rerate, natural = scen
    base, meta = gen.make_valid_path("base", seed, dict(g=0.05))
    n = len(base)
    rng = np.random.default_rng(seed + 991)
    K = len(SECT)
    dt = 1 / YEAR
    s = ramp(n, speed)
    # 行业中枢
    pe_c = np.tile(PE0, (n, 1))
    if rerate is not None:
        pe_c = PE0 * np.exp(np.outer(s, np.log(rerate)))
    roe_c = np.tile(ROE0, (n, 1))
    # 行业偏离 = β × 市场偏离 + 行业噪声（OU）
    dm = base.dev.values
    e = np.zeros((n, K))
    z = rng.standard_normal((n, K))
    for i in range(1, n):
        e[i] = e[i - 1] * (1 - 2.0 * dt) + 0.09 * np.sqrt(dt) * z[i]
    dev_i = BETA * dm[:, None] + e
    pe_i = pe_c * np.exp(dev_i)
    # 行业盈利：共享市场盈利 + 行业增长差 + 小噪声；ROE 围绕各自中枢波动（含市场盈利周期）
    eps_m = base.close.values / base.pe.values
    gdiff = GROWTH_N6 if natural else np.zeros(K)
    eps_i = eps_m[:, None] * np.exp(np.outer(np.arange(n) * dt, gdiff) + np.cumsum(0.003 * rng.standard_normal((n, K)), 0) * 0.3)
    roe_cyc = base.roe.values / 0.12
    roe_i = roe_c * roe_cyc[:, None]
    pb_i = pe_i * roe_i
    dy_i = PAY0 * (1 + 0.05 * np.sin(np.arange(n)[:, None] / YEAR * 2 * np.pi / 4.3 + np.arange(K))) / pe_i
    p_i = pe_i * eps_i
    r_i = np.vstack([np.zeros(K), p_i[1:] / p_i[:-1] - 1])
    # 权重
    if natural:
        cap = W_START * p_i / p_i[0]
        w = cap / cap.sum(1, keepdims=True)
    else:
        w = W_START + np.outer(s, wt - W_START)
        w = w / w.sum(1, keepdims=True)
    wl = np.vstack([w[0], w[:-1]])
    r_idx = (wl * r_i).sum(1)
    div_idx = (wl * dy_i).sum(1) / YEAR
    close = 1000 * np.cumprod(1 + r_idx)
    tr = 1000 * np.cumprod(1 + r_idx + np.r_[0, div_idx[:-1]])
    ratio = close / base.close.values
    pe = 1 / (w / pe_i).sum(1)
    pb = 1 / (w / pb_i).sum(1)
    dy = (w * dy_i).sum(1)
    center = 1 / (w / pe_c).sum(1)
    df = pd.DataFrame(dict(date=base.date.values, open=base.open.values * np.r_[ratio[0], ratio[:-1]],
                           high=base.high.values * ratio, low=base.low.values * ratio, close=close, tr=tr,
                           pe=pe, pb=pb, dy=dy, y=base.y.values, roe=pb / pe, center=center, dev=np.log(pe) - np.log(center)))
    df["high"] = np.maximum(df.high, np.maximum(df.open, df.close))
    df["low"] = np.minimum(df.low, np.minimum(df.open, df.close))
    sec = dict(w=w, pe=pe_i, pb=pb_i, dy=dy_i)
    return df, meta, sec


def pct2(x):
    return (I.pct_score(x, 10) + I.pct_score(x, 5)) / 2


def roe5_of(pb, pe):
    return pd.Series(pb / pe).rolling(5 * YEAR).mean().shift(1).values


def v_index(df, ierp=False):
    pe, pb, dy, y = df.pe.values, df.pb.values, df.dy.values, df.y.values
    roe5 = roe5_of(pb, pe)
    ey = roe5 / pb
    if ierp:
        g = np.clip(0.5 * roe5 * (1 - dy * pe), 0, 0.08)
        last = pct2(dy * (1 + g) + g - y)
    else:
        last = pct2(ey - y)
    return (pct2(ey) + pct2(1 / pb) + pct2(dy) + last) / 4, roe5


def v_neutral(sec, y):
    n, K = sec["w"].shape
    Vs = np.zeros((n, K))
    for k in range(K):
        pe, pb, dy = sec["pe"][:, k], sec["pb"][:, k], sec["dy"][:, k]
        ey = roe5_of(pb, pe) / pb
        Vs[:, k] = (pct2(ey) + pct2(1 / pb) + pct2(dy) + pct2(ey - y)) / 4
    return (sec["w"] * Vs).sum(1)


def v_constweight(sec, y, step=5):
    """每 step 天：用当日权重把过去 10 年的行业数据重新汇总成指数估值，再取当日分位。"""
    n, K = sec["w"].shape
    ey_i = np.column_stack([roe5_of(sec["pb"][:, k], sec["pe"][:, k]) / sec["pb"][:, k] for k in range(K)])
    bp_i = 1 / sec["pb"]
    dy_i = sec["dy"]
    out = np.full(n, np.nan)
    W10, W5 = 10 * YEAR, 5 * YEAR
    for t in range(START - 1 - step * 2, n, step):
        w = sec["w"][t]
        lo = max(0, t - W10)
        seg = slice(lo, t + 1)
        ey = ey_i[seg] @ w
        bp = bp_i[seg] @ w                      # 指数 1/PB = Σ w / PB_i
        dy = dy_i[seg] @ w
        erp = ey - y[seg]
        vals = []
        for x in (ey, bp, dy, erp):
            cur, hist = x[-1], x[:-1]
            hist = hist[~np.isnan(hist)]
            if np.isnan(cur) or len(hist) < 3 * YEAR:
                vals = None
                break
            p10 = np.mean(hist >= cur) * 100
            h5 = hist[-W5:]
            p5 = np.mean(h5 >= cur) * 100
            vals.append((p10 + p5) / 2)
        if vals is not None:
            out[t:t + step] = np.mean(vals)
    return out


def job(arg):
    key, seed = arg
    scen = [s for s in SCEN if s[0] == key][0]
    df, meta, sec = make_sector_path(seed, scen)
    n = len(df)
    y = df.y.values
    V = {}
    V["orig"], roe5 = v_index(df)
    V["ierp"], _ = v_index(df, ierp=True)
    V["cw"] = v_constweight(sec, y)
    V["neutral"] = v_neutral(sec, y)
    V["oracle"] = pct2(-df.dev.values)
    ind = I.compute(df, val=(V["orig"], roe5))
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    w = slice(START, n)
    common = np.all([~np.isnan(V[m][w]) for m in METHODS], axis=0)
    out = dict(key=key, seed=seed, m={},
               pe_center=[float(df.center.values[i]) for i in (START, n - 1)],
               pb=[float(df.pb.values[START:START + YEAR].mean()), float(df.pb.values[-YEAR:].mean())],
               dy=[float(df.dy.values[START:START + YEAR].mean()), float(df.dy.values[-YEAR:].mean())],
               roe=[float(df.roe.values[START:START + YEAR].mean()), float(df.roe.values[-YEAR:].mean())],
               w_end=sec["w"][-1].tolist())
    for mk in METHODS:
        v = V[mk][w]
        o = V["oracle"][w]
        rec = dict(corr=float(np.corrcoef(v[common], o[common])[0, 1]), rmse=float(np.sqrt(np.mean((v[common] - o[common]) ** 2))),
                   bias=float(np.mean(v[common] - o[common])), hi=float(np.nanmean(v > 70)))
        Vm = np.where(np.isnan(V[mk]), V["orig"], V[mk])
        ind["V"] = Vm
        ind["V3"] = Vm
        D = En.Data(df, ind, None, fail)
        for ver in VERS:
            r = En.run(D, ver, cost=True, review=(ver != "1.6"))
            bh = En.bench(D, r["inflow"], True, "bh")
            tw = r["twr"][START - 1:]
            rec[ver] = dict(x=En.xirr(r["inflow"], r["final"]), bh=En.xirr(bh["inflow"], bh["final"]),
                            mdd=float(np.max(1 - tw / np.maximum.accumulate(tw))),
                            idle=float(np.mean(r["cash"][START:] / np.maximum(r["total"][START:], 1) > 0.05)))
        out["m"][mk] = rec
    if seed == 8000:
        idx = np.arange(0, n, 20)
        sm = lambda a: pd.Series(a).rolling(120, min_periods=1).mean().values[idx]
        out["series"] = dict(date=[str(d)[:4] for d in df.date.values[idx]],
                             center=np.round(df.center.values[idx], 2).tolist(), pe=np.round(df.pe.values[idx], 2).tolist(),
                             w=np.round(sec["w"][idx], 3).tolist(),
                             **{"V_" + m: [None if np.isnan(x) else round(float(x), 1) for x in sm(V[m])] for m in METHODS})
    return out


def main():
    N = 24
    jobs = [(s[0], 8000 + k) for s in SCEN for k in range(N)]
    t0 = time.time()
    with mp.Pool(4) as pool:
        res = []
        for k, r in enumerate(pool.imap_unordered(job, jobs, chunksize=1)):
            res.append(r)
            if k % 24 == 0:
                print(f"{k + 1}/{len(jobs)} {time.time() - t0:.0f}s", flush=True)
    by = {}
    for r in res:
        by.setdefault(r["key"], {})[r["seed"]] = r
    base = by["N0"]

    def se(a):
        a = np.asarray(a, float)
        return float(a.std(ddof=1) / np.sqrt(len(a)))

    agg = {}
    for key, name, desc, *_ in SCEN:
        rs = by[key]
        seeds = sorted(rs)
        rec = dict(name=name, desc=desc, n=len(seeds),
                   pe_center=[float(np.mean([rs[s]["pe_center"][i] for s in seeds])) for i in (0, 1)],
                   pb=[float(np.mean([rs[s]["pb"][i] for s in seeds])) for i in (0, 1)],
                   dy=[float(np.mean([rs[s]["dy"][i] for s in seeds])) for i in (0, 1)],
                   roe=[float(np.mean([rs[s]["roe"][i] for s in seeds])) for i in (0, 1)],
                   w_end=np.mean([rs[s]["w_end"] for s in seeds], 0).tolist())
        for mk in METHODS:
            m = {k: float(np.mean([rs[s]["m"][mk][k] for s in seeds])) for k in ("corr", "rmse", "bias", "hi")}
            for ver in VERS + ["avg"]:
                vv = VERS if ver == "avg" else [ver]
                ex = lambda r_, m_: np.mean([r_["m"][m_][u]["x"] - r_["m"][m_][u]["bh"] for u in vv])
                dx = [np.mean([rs[s]["m"][mk][u]["x"] - rs[s]["m"]["orig"][u]["x"] for u in vv]) for s in seeds]
                dmg = [ex(rs[s], "orig") - ex(base[s], "orig") for s in seeds]          # 原版因成分漂移损失的超额
                exm = [ex(rs[s], mk) for s in seeds]
                m[ver] = dict(dx=float(np.mean(dx)), dx_se=se(dx), ex=float(np.mean(exm)),
                              dmdd=float(np.mean([np.mean([rs[s]["m"][mk][u]["mdd"] - rs[s]["m"]["orig"][u]["mdd"] for u in vv]) for s in seeds])),
                              didle=float(np.mean([np.mean([rs[s]["m"][mk][u]["idle"] - rs[s]["m"]["orig"][u]["idle"] for u in vv]) for s in seeds])),
                              damage=float(np.mean(dmg)))
            rec[mk] = m
        if "series" in rs.get(8000, {}):
            rec["series"] = rs[8000]["series"]
        agg[key] = rec
    json.dump(dict(agg=agg, sectors=SECT, methods=METHODS), open(os.path.join(HERE, "results", "sector.json"), "w"), ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
