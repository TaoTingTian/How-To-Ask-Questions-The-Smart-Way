"""执行全部回测实验，输出 results/results.json（报告数据源）。

  python analysis.py            # 10 条主路径 + 300 条蒙特卡洛复核路径
用法见 README.md。"""
import json
import os
import sys
import time
import itertools
import multiprocessing as mp

import numpy as np

import gen
import indicators as I
import engine as En
from engine import START, YEAR, INIT_CAPITAL

VERS = ["1.6", "1.7", "1.8", "1.9"]
WARN_SCHEMES = ["L1", "L2", "L3", "graded", "L1ML", "L1L3"]
GRID = dict(SL=[65.0, 70.0, 75.0], RB=[45.0, 50.0, 55.0], TH=[0.03, 0.05, 0.07], FL=[0.10, 0.20, 0.30])
MC_SEEDS = 30
MC_GRID_SEEDS = 10
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


# ---------------------------------------------------------------- 指标
def perf(D, r, cost):
    n = D.n
    tw = r["twr"][START - 1:]
    ret = np.diff(np.log(tw))
    years = (n - START) / YEAR
    cagr = tw[-1] ** (1 / years) - 1
    peak = np.maximum.accumulate(tw)
    dd = 1 - tw / peak
    mdd = dd.max()
    # 最长水下时长（回撤修复时长）
    under = dd > 1e-9
    longest = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    down = np.sqrt(np.mean(np.minimum(ret, 0) ** 2)) * np.sqrt(YEAR)
    sharpe = ret.mean() / ret.std() * np.sqrt(YEAR)
    x = En.xirr(r["inflow"], r["final"])
    bh = En.bench(D, r["inflow"], cost, "bh")
    dca = En.bench(D, r["inflow"], cost, "dca")
    xb = En.xirr(bh["inflow"], bh["final"])
    xd = En.xirr(dca["inflow"], dca["final"])
    cost_total = r["cost_sub"] + r["cost_red"] + r["cost_comm"] + r["cost_imp"]
    avg_assets = r["total"][START:].mean()
    pool_idle = np.mean(r["cash"][START:] / np.maximum(r["total"][START:], 1) > 0.05)
    inflow_total = r["inflow"][START:].sum()
    return dict(
        final=r["final"], inflow=inflow_total, xirr=x, xirr_bh=xb, xirr_dca=xd,
        ex_bh=x - xb, ex_dca=x - xd, final_bh=bh["final"], final_dca=dca["final"],
        cagr_twr=cagr, mdd=mdd, uw_days=longest, down_vol=down, sortino=cagr / down if down else np.nan,
        sharpe=sharpe, calmar=cagr / mdd if mdd else np.nan,
        cost_total=cost_total, cost_ratio=cost_total / r["final"],
        cost_fee=r["cost_sub"] + r["cost_red"], cost_comm=r["cost_comm"], cost_imp=r["cost_imp"],
        cost_kind=r["cost_by_kind"], turnover=r["turnover_amt"] / avg_assets / years,
        n_sell=r["n_sell"], n_rebuy=r["n_rebuy"], n_special=r["n_special"],
        spread=(r["avg_sell_px"] / r["avg_buy_px"] - 1) if r["avg_buy_px"] == r["avg_buy_px"] else np.nan,
        pool_idle=pool_idle, mdd_bh=float(np.max(1 - D.nav[START - 1:] / np.maximum.accumulate(D.nav[START - 1:]))),
    )


# ---------------------------------------------------------------- 预警评估
def eval_warning(events, active, truth_state, eps, d, n, refr_hold=126):
    """events: 预警日列表；active: 日度预警状态；truth_state: 真实漂移方向数组；d: 方向。"""
    tp = fp = 0
    for t in events:
        lo, hi = max(0, t - 126), min(n, t + 504)
        if np.any(truth_state[lo:hi] == d):
            tp += 1
        else:
            fp += 1
    leads = []
    missed = 0
    n_ep = 0
    for e in eps:
        if e["dir"] != d or e["end"] < START:
            continue
        n_ep += 1
        onset = max(e["onset"], START)
        lo, hi = max(START, onset - 504), min(n, onset + 252, e["end"] + 1)
        on = np.where(active[lo:hi])[0]
        if len(on):
            leads.append(onset - (lo + on[0]))
        else:
            missed += 1
    # 日度假阳性：无漂移日中预警处于激活状态的比例
    is_d = (truth_state == d).astype(int)
    cs = np.r_[0, np.cumsum(is_d)]
    idx = np.arange(START, n)
    lo = np.maximum(idx - 126, 0)
    hi = np.minimum(idx + 504, n)
    near = (cs[hi] - cs[lo]) > 0
    nd = ~near
    fp_days = int(np.sum(active[START:][nd]))
    nd_days = int(np.sum(nd))
    drift_days = int(np.sum(near))
    tp_days = int(np.sum(active[START:][near]))
    return dict(tp=tp, fp=fp, leads=leads, missed=missed, n_ep=n_ep,
                fp_days=fp_days, nd_days=nd_days, tp_days=tp_days, drift_days=drift_days)


def edges(state, refractory=YEAR):
    ev = []
    last = -10 ** 9
    prev = False
    for t in range(START, len(state)):
        s = bool(state[t])
        if s and not prev and t - last >= refractory:
            ev.append(t)
            last = t
        prev = s
    return ev


def hold(x, k=20):
    import pandas as pd
    return pd.Series(x.astype(float)).rolling(k, min_periods=1).max().values > 0


# ---------------------------------------------------------------- 单路径任务
def path_job(job):
    kind, seed, params, detail, do_grid, label = job
    df, meta = gen.make_valid_path(kind, seed, params)
    ind = I.compute(df)
    mc = I.multi_cycle(df, ind)
    n = len(df)
    fail = np.random.default_rng(meta["seed_used"] + 17).random(n) < 0.003
    D = En.Data(df, ind, mc, fail)
    truth, eps = I.truth_drift(df)
    traps = [tp for tp in meta["traps"] if tp[2] >= START + 20]
    res = dict(kind=kind, seed=meta["seed_used"], label=label, n_traps=len(traps))

    # ---------- 1. 主回测：四版 × 毛/净 × 复核开/关 ----------
    main = {}
    runs_net = {}
    runs_norev = {}
    for v in VERS:
        for cost in (True, False):
            for rev in ([False] if v == "1.6" else [True, False]):
                r = En.run(D, v, cost=cost, review=rev, record=cost)
                key = f"{v}|{'net' if cost else 'gross'}|{'rev' if rev else 'norev'}"
                m = perf(D, r, cost)
                main[key] = m
                if cost and (rev or v == "1.6"):
                    runs_net[v] = r
                if cost and not rev:
                    runs_norev[v] = r
    res["main"] = main

    # ---------- 2. 高波动：冲击成本侵蚀 ----------
    ar = D.atr_rel[START:]
    hv = ar >= np.quantile(ar, 0.8)
    hvres = {}
    for v in VERS:
        r = runs_net[v]
        imp = r["impday"][START:]
        tot = imp.sum()
        hvres[v] = dict(imp_share_hv=float(imp[hv].sum() / tot) if tot else 0.0,
                        imp_rate_hv=float(np.mean(ar[hv]) * 0.5), imp_rate_lv=float(np.mean(ar[~hv]) * 0.5))
    res["highvol"] = hvres
    res["atr_mean"] = float(np.mean(ar))

    # ---------- 3. 假回归陷阱 ----------
    block = np.zeros(n, bool)
    wins = []
    for (dr, ext, ts, te, rr) in traps:
        lo, hi = ts - 20, te + 20
        block[lo:hi + 1] = True
        wins.append((dr, lo, hi, rr))
    trap_res = {}
    for v in VERS:
        r = runs_net[v]
        per = []
        for (dr, lo, hi, rr) in wins:
            tds = [x for x in r["trades"] if lo <= x[0] <= hi]
            losses = []
            paybacks = []
            g_sell = g_buy = 0.0
            for x in tds:
                t, kindt, val = x[0], x[1], x[2]
                h = max(rr, t + 20)
                if h >= n:
                    continue
                chg = D.nav[h] / D.nav[t] - 1
                gain = val * chg if kindt != "sell" else -val * chg
                losses.append(-gain / r["total"][t])
                if kindt == "sell":
                    g_sell += gain / r["total"][t]
                else:
                    g_buy += gain / r["total"][t]
                if gain < 0:
                    pb = None
                    for u in range(h, n):
                        if (kindt != "sell" and D.nav[u] >= D.nav[t]) or (kindt == "sell" and D.nav[u] <= D.nav[t]):
                            pb = u - t
                            break
                    paybacks.append(pb)
            per.append(dict(dir=dr, n_trades=len(tds), n_sell=sum(1 for x in tds if x[1] == "sell"),
                            n_buy=sum(1 for x in tds if x[1] != "sell"), loss=float(np.sum(losses)) if losses else 0.0,
                            g_sell=g_sell, g_buy=g_buy,
                            paybacks=paybacks))
        rb = En.run(D, v, cost=True, review=(v != "1.6"), block=block)
        prof_b = rb["final"] - INIT_CAPITAL - rb["inflow"][START:].sum()
        trap_res[v] = dict(per=per, final=r["final"], final_block=rb["final"],
                           impact=(rb["final"] - r["final"]) / prof_b if prof_b > 0 else np.nan,
                           xirr_block=En.xirr(rb["inflow"], rb["final"]))
    res["traps"] = trap_res

    # ---------- 4. 危机 / 泡沫崩盘 ----------
    crises = []
    for e in meta["events"]:
        if e["type"] not in ("crisis", "bubble") or e["peak"] < START + 60 or e["trough"] >= n - 10:
            continue
        pk, th = e["peak"], e["trough"]
        lowp = D.close[pk:th + 1].min()
        rec = dict(type=e["type"], peak=pk, trough=th, drop=float(1 - lowp / D.close[pk - 5:pk + 5].max()))
        for v in VERS:
            r = runs_net[v]
            p_pk = r["p"][pk - 1]
            esc = bool(p_pk <= 0.6)
            buys = [x for x in r["trades"] if x[1] != "sell" and pk <= x[0] <= th + 126 and x[3] <= 1.15 * lowp]
            pre = r["twr"][pk - 60:pk + 1].max()
            k0 = pk + int(np.argmin(r["twr"][pk:min(n, th + 126)]))
            rep = None
            for u in range(k0, n):
                if r["twr"][u] >= pre:
                    rep = u - k0
                    break
            rec[v] = dict(p_peak=float(p_pk), escape=esc, bottom=bool(buys), repair=rep,
                          dd=float(1 - r["twr"][k0] / pre))
        pre = D.nav[pk - 60:pk + 1].max()
        k0 = pk + int(np.argmin(D.nav[pk:min(n, th + 126)]))
        rep = next((u - k0 for u in range(k0, n) if D.nav[u] >= pre), None)
        rec["bh"] = dict(repair=rep, dd=float(1 - D.nav[k0] / pre))
        crises.append(rec)
    res["crises"] = crises

    # ---------- 5. 中枢漂移：感知滞后、收益衰减、跳变失灵顺序 ----------
    Vrm = __import__("pandas").Series(D.V).rolling(120, min_periods=20).mean().values
    drifts = []
    for di in meta["drift"]:
        s = di["start"]
        if s >= n - YEAR:
            continue
        dr = di["dir"]
        s_eff = max(s, START)
        # V 偏离正常带（35–65）后回到正常带的时间
        left = None
        back = None
        for u in range(s_eff, n):
            out = Vrm[u] > 65 if dr > 0 else Vrm[u] < 35
            if left is None and out:
                left = u
            elif left is not None and not out:
                back = u
                break
        e_end = min(n - 1, (di["end"] if di["type"] == "slow" else s + 3 * YEAR))
        rec = dict(type=di["type"], dir=dr, start=s, end=e_end,
                   v_left=None if left is None else left - s_eff,
                   v_back=None if back is None else back - s_eff, censor=n - s_eff)
        for v in VERS:
            r = runs_net[v]
            seg = np.arange(s_eff, e_end + 1)
            rel = np.log(r["twr"][seg] / D.nav[seg]) - np.log(r["twr"][s_eff] / D.nav[s_eff])
            tt = (seg - s_eff) / YEAR
            slope = float(np.polyfit(tt, rel, 1)[0]) if len(seg) > 30 else np.nan
            loss3 = float(rel[min(len(rel) - 1, 3 * YEAR)])
            trs = [x for x in r["trades"] if x[0] >= s_eff]
            first_sell = next((x[0] - s_eff for x in trs if x[1] == "sell"), None)
            first_buy = next((x[0] - s_eff for x in trs if x[1] != "sell"), None)
            cashr = r["cash"] / np.maximum(r["total"], 1)
            stuck = None
            exhausted = None
            for u in range(s_eff, n - YEAR):
                if stuck is None and cashr[u] > 0.05 and np.all(D.V[u:u + YEAR] >= 50):
                    stuck = u - s_eff
                if exhausted is None and cashr[u] < 0.01 and u > s_eff + 5:
                    exhausted = u - s_eff
                if stuck is not None and exhausted is not None:
                    break
            trig = next((tg[0] - s_eff for tg in runs_norev.get(v, {"triggers": []})["triggers"] if tg[0] >= s_eff), None) \
                if v != "1.6" else None
            rec[v] = dict(slope=slope, loss3=loss3, first_sell=first_sell, first_buy=first_buy,
                          stuck=stuck, exhausted=exhausted, first_trigger=trig)
        drifts.append(rec)
    res["drifts"] = drifts

    # ---------- 6. 第十节触发条件 ----------
    sec10 = {}
    for v in ["1.7", "1.8", "1.9"]:
        trg = runs_norev[v]["triggers"]
        out = {}
        for cname, sel in (("all", lambda c: True), ("A", lambda c: "A" in c), ("B", lambda c: "B" in c)):
            evs = [tg[0] for tg in trg if sel(tg[1])]
            act = np.zeros(n, bool)
            for t in evs:
                act[t:t + 126] = True
            out[cname] = eval_warning(evs, act, truth, eps, 1, n)
        sec10[v] = out
    res["sec10"] = sec10

    # ---------- 7. 多周期共振预警 ----------
    mcres = {}
    for d in ("up", "down"):
        dd = 1 if d == "up" else -1
        sh, md, lg = mc[d + "_short"], mc[d + "_mid"], mc[d + "_long"]
        variants = {
            "单周期(任一)": mc[d + "_count"] >= 1,
            "双周期(任两)": mc[d + "_count"] >= 2,
            "三周期共振": mc[d + "_count"] >= 3,
            "短+中": hold(sh & md), "中+长": hold(md & lg), "短+长": hold(sh & lg),
            "仅短周期": hold(sh), "仅中周期": hold(md), "仅长周期": hold(lg),
        }
        mcres[d] = {k: eval_warning(edges(st), st, truth, eps, dd, n) for k, st in variants.items()}
    res["multicycle"] = mcres
    res["truth_eps"] = [e for e in eps if e["end"] >= START]

    # ---------- 8. 预警分级应对 ----------
    wres = {}
    for v in VERS:
        wres[v] = {"无预警无复核": dict(xirr=main[f"{v}|net|{'norev' if v != '1.6' else 'norev'}"]["xirr"],
                                    mdd=main[f"{v}|net|norev"]["mdd"])}
        if v != "1.6":
            wres[v]["第十节复核"] = dict(xirr=main[f"{v}|net|rev"]["xirr"], mdd=main[f"{v}|net|rev"]["mdd"])
        for w in WARN_SCHEMES:
            r = En.run(D, v, cost=True, review=False, warn=w)
            tw = r["twr"][START - 1:]
            wres[v][w] = dict(xirr=En.xirr(r["inflow"], r["final"]),
                              mdd=float(np.max(1 - tw / np.maximum.accumulate(tw))))
    res["warn"] = wres

    # ---------- 9. 参数网格 ----------
    if do_grid:
        grid = {}
        keys = list(GRID)
        for combo in itertools.product(*[GRID[k] for k in keys]):
            pr = dict(zip(keys, combo))
            ck = "|".join(f"{c:g}" for c in combo)
            for v in VERS:
                r = En.run(D, v, cost=True, review=(v != "1.6"), params=pr)
                grid[f"{v}|{ck}"] = En.xirr(r["inflow"], r["final"])
        res["grid"] = grid

    # ---------- 10. 图表序列（主路径） ----------
    if detail:
        step = 5
        idx = np.arange(0, n, step)
        ser = dict(
            date=[str(d)[:10] for d in df.date.values[idx]],
            close=np.round(df.close.values[idx], 1).tolist(),
            pe=np.round(df.pe.values[idx], 2).tolist(),
            center=np.round(df.center.values[idx], 2).tolist(),
            V=[None if np.isnan(x) else round(float(x), 1) for x in D.V[idx]],
            y=np.round(df.y.values[idx] * 100, 2).tolist(),
            up_count=mc["up_count"][idx].tolist(), down_count=mc["down_count"][idx].tolist(),
            truth=truth[idx].tolist(),
        )
        bi = np.arange(START - 1, n, step)
        ser["bt_date"] = [str(d)[:10] for d in df.date.values[bi]]
        ser["nav"] = np.round(D.nav[bi] / D.nav[START - 1], 4).tolist()
        for v in VERS:
            ser["twr_" + v] = np.round(runs_net[v]["twr"][bi], 4).tolist()
            ser["p_" + v] = np.round(runs_net[v]["p"][bi], 3).tolist()
        res["series"] = ser
        res["events"] = [dict(type=e["type"], peak=e.get("peak", e["start"]), trough=e.get("trough"), dir=e.get("dir"),
                              date=str(df.date.values[min(e.get("peak", e["start"]), n - 1)])[:10]) for e in meta["events"]]
        res["trap_list"] = [dict(dir=int(t[0]), touch=str(df.date.values[t[2]])[:10], ts=int(t[2]),
                                 te=int(t[3]), resume=int(t[4])) for t in traps]
        res["drift_meta"] = [dict(di, start_date=str(df.date.values[min(di["start"], n - 1)])[:10]) for di in meta["drift"]]
        res["path_stats"] = dict(
            ann_price=float(np.log(df.close.values[-1] / df.close.values[0]) / 30),
            ann_tr_bt=float((D.nav[-1] / D.nav[START - 1]) ** (YEAR / (n - START)) - 1),
            vol=float(np.std(np.diff(np.log(df.close.values))) * np.sqrt(YEAR)),
            mdd=float(np.max(1 - df.close.values / np.maximum.accumulate(df.close.values))),
            pe_min=float(df.pe.min()), pe_max=float(df.pe.max()),
            center_chg=float(df.center.values[-1] / df.center.values[0] - 1),
            V_mean=float(np.nanmean(D.V[START:])), V_hi=float(np.nanmean(D.V[START:] > 70)),
            V_lo=float(np.nanmean(D.V[START:] < 30)),
            y_min=float(df.y.min()), y_max=float(df.y.max()), n_days=n,
            start_date=str(df.date.values[0])[:10], bt_start=str(df.date.values[START])[:10],
            end_date=str(df.date.values[-1])[:10], fail_days=int(fail[START:].sum()),
        )
    return res


def to_jsonable(o):
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [to_jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if (f != f or f in (float("inf"), float("-inf"))) else round(f, 6)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return to_jsonable(o.tolist())
    return o


def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = []
    for no, kind, name, ds, seed in gen.PATH_SPECS:
        jobs.append((kind, seed, None, True, True, dict(no=no, name=name, set=ds, mc=False)))
    rng = np.random.default_rng(20261014)
    for no, kind, name, ds, seed in gen.PATH_SPECS:
        for j in range(MC_SEEDS):
            prm = {}
            if kind in ("slow_up", "slow_down"):
                prm["slow_rate"] = float(rng.uniform(0.03, 0.08))
            if kind in ("jump_up", "jump_down"):
                prm["jump_size"] = float(rng.uniform(0.15, 0.30))
            jobs.append((kind, 100000 + no * 1000 + j, prm or None, False, j < MC_GRID_SEEDS,
                         dict(no=no, name=name, set="蒙特卡洛", mc=True, rep=j, params=prm)))
    for no, kind, name, ds, seed in gen.PATH_SPECS:
        for j in range(10):
            prm = {}
            if kind in ("slow_up", "slow_down"):
                prm["slow_rate"] = float(rng.uniform(0.03, 0.08))
            if kind in ("jump_up", "jump_down"):
                prm["jump_size"] = float(rng.uniform(0.15, 0.30))
            jobs.append((kind, 900000 + no * 1000 + j, prm or None, False, False,
                         dict(no=no, name=name, set="留出验证", mc=True, rep=j, params=prm)))
    t0 = time.time()
    with mp.Pool(min(4, os.cpu_count() or 1)) as pool:
        out = []
        for k, r in enumerate(pool.imap(path_job, jobs, chunksize=1)):
            out.append(r)
            if k % 20 == 0:
                print(f"{k + 1}/{len(jobs)}  {time.time() - t0:.0f}s", flush=True)
    with open(os.path.join(OUT, "raw.json"), "w") as f:
        json.dump(to_jsonable(out), f, ensure_ascii=False)
    print("done", time.time() - t0)


if __name__ == "__main__":
    main()
