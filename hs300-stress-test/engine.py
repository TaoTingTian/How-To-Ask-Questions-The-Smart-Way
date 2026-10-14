"""V1.6 / V1.7 / V1.8 / V1.9 逐日回测引擎（规则严格对应各版本文档，另加全口径成本、第十节复核、多周期预警应对）。"""
import numpy as np

YEAR = 252
START = 8 * YEAR + 1          # 前 8 年预热；V 首个可算日为第 2016 日，信号用 T−1，故从 2017 起交易
INIT_CAPITAL = 100_000.0

BASE = dict(SL=70.0, RB=50.0, TH=0.05, FL=0.20)


def clip01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def redemption_rate(age):
    if age < 7:
        return 0.015
    if age < 30:
        return 0.005
    if age < 180:
        return 0.0025
    return 0.0


class Data:
    """一条路径的全部输入数组（numpy），供多次回测复用。"""

    def __init__(self, df, ind, mc, fail):
        self.n = len(df)
        self.nav = df.tr.values / df.tr.values[0]
        self.tr = df.tr.values
        self.close = df.close.values
        self.y = df.y.values
        self.V = ind["V"]
        self.V3 = ind["V3"]
        self.U = ind["U"]
        self.S = ind["S"]
        self.B = ind["B"]
        self.atr_rel = np.nan_to_num(ind["atr_rel"], nan=0.015)
        self.ma160 = ind["ma160"]
        self.roe5 = ind["roe5"]
        self.fail = fail
        self.up_count = mc["up_count"] if mc is not None else np.zeros(self.n, int)
        self.down_count = mc["down_count"] if mc is not None else np.zeros(self.n, int)
        z = np.zeros(self.n, bool)
        self.up_ml = mc["up_ml"] if mc is not None else z
        self.down_ml = mc["down_ml"] if mc is not None else z
        # 修订版复核所需：PE 滚动 5 年中位数（观测中枢）、股债利差 1 年均值
        import pandas as pd
        self.pe_med5 = pd.Series(df.pe.values).rolling(5 * YEAR, min_periods=3 * YEAR).median().values
        self.erp_sm = pd.Series(self.roe5 / df.pb.values - df.y.values).rolling(YEAR, min_periods=20).mean().values


def run(D, ver, cost=True, review=True, params=None, warn=None, block=None, record=False, review_rule="old"):
    P = dict(BASE)
    if params:
        P.update(params)
    SL, RB, TH, FL = P["SL"], P["RB"], P["TH"], P["FL"]
    two_stage = ver in ("1.8", "1.9")
    uses_U_sell = ver in ("1.6", "1.8", "1.9")
    uses_S = ver in ("1.7", "1.8", "1.9")
    rebuy_B = ver in ("1.7", "1.9")
    rebuy_U = ver in ("1.6", "1.8")
    has_review = review and ver != "1.6"
    log_review = ver != "1.6"

    n = D.n
    nav, close, tr = D.nav, D.close, D.tr
    Varr, V3arr, Uarr, Sarr, Barr = D.V, D.V3, D.U, D.S, D.B
    atr_rel = D.atr_rel

    c_sub = 0.001 if cost else 0.0
    c_comm = 0.001 if cost else 0.0
    c_imp_k = 0.5 if cost else 0.0

    # 状态
    lots_day = [START - 1000]
    lots_sh = [INIT_CAPITAL / nav[START - 1]]
    head = 0
    shares = lots_sh[0]
    cash = 0.0
    transit = []          # [到账日, 金额]
    transit_sum = 0.0
    pending = 0.0
    E = 0.0
    Vmax = None
    a = b = 1.0
    Vc = Uc = None
    # 第十节
    t0 = None
    sold_sh = 0.0
    sold_trsh = 0.0
    no_more_stop = False
    in_review = False
    review_end = -1
    review_conds = ()
    sup = {"A": -1, "B": -1}
    # 预警
    v3_until = -1
    last_pool_l2 = -10 ** 9
    last_pool_l3 = -10 ** 9
    prev_up = 0
    prev_ml = False

    inflow = np.zeros(n)
    total = np.zeros(n)
    pser = np.zeros(n)
    cashser = np.zeros(n)
    impday = np.zeros(n)
    costday = np.zeros(n)
    units = INIT_CAPITAL / 1.0
    twr = np.ones(n)
    cost_sub = cost_red = cost_comm = cost_imp = 0.0
    cost_by_kind = {"sell": 0.0, "rebuy": 0.0, "dca": 0.0, "special": 0.0}
    n_sell = n_rebuy = n_special = 0
    sell_amt = sell_px = 0.0
    buy_amt = buy_px = 0.0
    turnover_amt = 0.0
    trades = [] if record else None
    triggers = []
    decisions = []
    stop_days = 0

    total[START - 1] = INIT_CAPITAL
    twr[:START] = 1.0

    def buy(t, amount, kind):
        nonlocal shares, cost_sub, cost_comm, cost_imp, buy_amt, buy_px
        comm = amount * c_comm
        imp = amount * c_imp_k * atr_rel[t]
        net = amount - comm - imp
        sh = net / (1 + c_sub) / nav[t]
        sub = net - net / (1 + c_sub)
        cost_sub += sub
        cost_comm += comm
        cost_imp += imp
        cost_by_kind[kind] += sub + comm + imp
        impday[t] += imp
        costday[t] += sub + comm + imp
        lots_day.append(t)
        lots_sh.append(sh)
        shares += sh
        if kind != "dca":
            buy_amt += amount
            buy_px += amount * close[t]
        return sh

    for t in range(START, n):
        i = t - 1
        valid = not D.fail[i]
        # ---------- 预警状态（用 T−1 数据） ----------
        upc = int(D.up_count[i]) if warn else 0
        dnc = int(D.down_count[i]) if warn else 0
        l1_up = l1_dn = pause_stop_w = pause_rebuy_w = False
        use_v3 = False
        pool_frac = 0.0
        if warn:
            if warn in ("L1", "graded", "L1ML", "L1L3"):
                l1_up = upc >= 1
                l1_dn = dnc >= 1
            if warn == "L1ML":
                # 优化方案：一级照常；二级只认“中周期 + 长周期”共振
                upml = bool(D.up_ml[i])
                pause_stop_w = upml
                pause_rebuy_w = bool(D.down_ml[i])
                if upml and not prev_ml and t - last_pool_l2 >= YEAR:
                    pool_frac = 0.5
                    last_pool_l2 = t
                prev_ml = upml
            if warn in ("L2", "graded"):
                pause_stop_w = upc >= 2
                pause_rebuy_w = dnc >= 2
                if upc >= 2 and prev_up < 2 and t - last_pool_l2 >= YEAR:
                    pool_frac = 0.5
                    last_pool_l2 = t
            if warn in ("L3", "graded", "L1L3"):
                if upc == 3 or dnc == 3:
                    v3_until = t + YEAR
                if upc == 3 and prev_up < 3 and t - last_pool_l3 >= YEAR:
                    pool_frac = 1.0
                    last_pool_l3 = t
                if warn in ("graded", "L1L3") and upc == 3:
                    pause_stop_w = True
            use_v3 = t <= v3_until
            prev_up = upc
        SLe = SL + 5 if l1_up else SL
        RBe = RB - 5 if (l1_up or l1_dn) else RB
        reb_mult = 0.5 if (l1_up or l1_dn) else 1.0

        # ---------- 读指标 ----------
        if valid or Vc is None:
            Vc = (V3arr[i] if use_v3 else Varr[i])
            Uc = Uarr[i]
            Sc, Bc = int(Sarr[i]), int(Barr[i])
        else:
            Sc = Bc = 0
        # 在途款到账（T+3）
        while transit and transit[0][0] <= t:
            amt = transit.pop(0)[1]
            cash += amt
            transit_sum -= amt
        if Vmax is None or Vc < RB:
            Vmax = Vc
        else:
            Vmax = max(Vmax, Vc)
        if Vc >= 50:
            E = 0.0
        if Vc < RB:
            a = b = 1.0
        if Vc < 50 and t0 is not None:          # 第十节：本轮清空
            t0 = None
            sold_sh = sold_trsh = 0.0
            no_more_stop = False
            in_review = False
        H = shares * nav[i]
        C = cash + transit_sum
        p = H / (H + C)
        blocked = block is not None and block[t]

        # ---------- 预警：资金池回补 ----------
        if pool_frac > 0 and cash >= 10 and not blocked:
            amt = cash * pool_frac
            cash -= amt
            buy(t, amt, "special")
            n_special += 1
            turnover_amt += amt
            if record:
                trades.append((t, "warn_buy", amt, close[t], p))
            if two_stage:
                Hn = shares * nav[t]
                a = b = max(FL, Hn / (Hn + cash + transit_sum))
            if pool_frac >= 1.0:          # 三级预警：确认中枢偏移，本轮不再止盈
                no_more_stop = True

        # ---------- 第十节复核结论（第 20 个交易日） ----------
        if has_review and in_review and t == review_end:
            in_review = False
            j0 = max(t0 - 1, 0) if t0 is not None else i
            dy_ = D.y[i] - D.y[j0]
            lo = D.y[max(j0, i - YEAR + 1): i + 1]
            cond_y = dy_ <= -0.005 and (i - j0) >= YEAR and np.all(lo <= D.y[j0] - 0.005)
            cond_r = (not np.isnan(D.roe5[j0])) and D.roe5[i] / D.roe5[j0] - 1 >= 0.05
            if review_rule == "new":
                # 修订版：以 PE 观测中枢 / ROE 的变化为主证据；利率下行只有在股债利差没有同步抬升时才算数
                cond_pe = (not np.isnan(D.pe_med5[j0])) and D.pe_med5[i] / D.pe_med5[j0] - 1 >= 0.10
                erp_up = (not np.isnan(D.erp_sm[j0])) and D.erp_sm[i] - D.erp_sm[j0] >= 0.005
                up = bool(cond_pe or cond_r or (cond_y and not erp_up))
            else:
                up = bool(cond_y or cond_r)
            decisions.append((t, up, review_conds, t0))
            if up and t0 is not None:
                if cash >= 10:
                    amt = cash * 0.5
                    cash -= amt
                    buy(t, amt, "special")
                    n_special += 1
                    turnover_amt += amt
                    if record:
                        trades.append((t, "review_buy", amt, close[t], p))
                if two_stage:
                    Hn = shares * nav[t]
                    a = b = max(FL, Hn / (Hn + cash + transit_sum))
                no_more_stop = True
            else:
                for cnd in review_conds:
                    sup[cnd] = t + YEAR

        # ---------- 止盈 ----------
        stop_day = False
        if valid and not blocked and not in_review and not no_more_stop and not pause_stop_w:
            target = None
            trig = ""

            def Bs(x):
                return FL + (1 - FL) * clip01((SLe + 10 - x) / 10)

            if ver == "1.6" or two_stage:
                ta = None
                if Vmax > SLe and Vc >= RB:
                    if Uc <= 1 / 3 + 1e-9:
                        ta = Bs(Vmax)
                    elif Vc > SLe:
                        ta = (1 + Bs(Vc)) / 2 - (1 - FL) / 2 * clip01((Vc - SLe - 10) / 10)
                if ver == "1.6":
                    target = ta
                    trig = "U"
                elif ta is not None:
                    a = min(a, max(FL, ta))
                    trig += "前"
            if ver == "1.7" or two_stage:
                tb = Bs(Vc) if (Vc > SLe and Sc == 1) else None
                if ver == "1.7":
                    target = tb
                    trig = "S"
                elif tb is not None:
                    b = min(b, tb)
                    trig += "后"
            if two_stage and trig:
                target = max(FL, (a + b) / 2)
            if target is not None and p > target + TH:
                val = (p - target) * (H + C)
                q = val / nav[i]
                # 先进先出，持有 < 30 天的不卖
                got = 0.0
                gross = 0.0
                red = 0.0
                k = head
                while q > 1e-12 and k < len(lots_sh) and lots_day[k] <= t - 30:
                    take = min(q, lots_sh[k])
                    v = take * nav[t]
                    rr = redemption_rate(t - lots_day[k]) if cost else 0.0
                    red += v * rr
                    gross += v
                    lots_sh[k] -= take
                    q -= take
                    got += take
                    if lots_sh[k] <= 1e-12:
                        k += 1
                head = k
                if got > 0:
                    comm = gross * c_comm
                    imp = gross * c_imp_k * atr_rel[t]
                    proceeds = gross - red - comm - imp
                    cost_red += red
                    cost_comm += comm
                    cost_imp += imp
                    cost_by_kind["sell"] += red + comm + imp
                    impday[t] += imp
                    costday[t] += red + comm + imp
                    shares -= got
                    transit.append([t + 3, proceeds])
                    transit_sum += proceeds
                    stop_day = True
                    stop_days += 1
                    n_sell += 1
                    sell_amt += gross
                    sell_px += gross * close[t]
                    turnover_amt += gross
                    if t0 is None:
                        t0 = t
                    sold_sh += got
                    sold_trsh += got * tr[t]
                    if record:
                        trades.append((t, "sell", gross, close[t], p, trig))

        # ---------- 回投 ----------
        if valid and not blocked and not stop_day and not pause_rebuy_w and Vc < RBe and cash >= 10:
            if rebuy_B:
                Tb = FL + (1 - FL) * clip01((RBe - Vc) / 20) if Bc == 1 else None
            else:
                if Uc >= 2 / 3 - 1e-9:
                    Tb = FL + (1 - FL) * clip01((RBe - Vc) / 20)
                else:
                    Tb = FL + (1 - FL) * clip01((RBe - 10 - Vc) / 20)
            if Tb is not None and p < Tb - TH:
                amt = min((Tb - p) * (H + C), cash) * reb_mult
                if amt >= 10:
                    cash -= amt
                    buy(t, amt, "rebuy")
                    n_rebuy += 1
                    turnover_amt += amt
                    if record:
                        trades.append((t, "rebuy", amt, close[t], p))

        # ---------- 定投 ----------
        if not stop_day:
            x = clip01((70 - Vc) / 70)
            xb = x ** 2.5
            base = 300 * xb
            extra = 700 * clip01((15 - Vc) / 15) * xb
            extra = min(extra, 50000 - E)
            amt = base + extra
            E += extra
            inflow[t] = amt
            pending += amt
            if pending >= 10:
                buy(t, pending, "dca")
                pending = 0.0

        # ---------- 第十节触发检查 ----------
        if log_review and valid and t0 is not None and not in_review and not no_more_stop:
            conds = []
            if t - t0 >= 3 * YEAR and t > sup["A"]:
                conds.append("A")
            pbar = sold_trsh / sold_sh if sold_sh > 0 else np.inf
            if tr[i] >= 1.3 * pbar and close[i] > D.ma160[i] and t > sup["B"]:
                conds.append("B")
            if conds:
                triggers.append((t, tuple(conds), t0))
                if has_review:
                    in_review = True
                    review_end = t + 20
                    review_conds = tuple(conds)
                else:
                    for cnd in conds:
                        sup[cnd] = t + YEAR

        # ---------- 收盘记账 ----------
        tot = shares * nav[t] + cash + transit_sum + pending
        total[t] = tot
        f = inflow[t]
        u = (tot - f) / units
        units += f / u
        twr[t] = u
        pser[t] = shares * nav[t] / max(shares * nav[t] + cash + transit_sum, 1e-9)
        cashser[t] = cash + transit_sum

    twr = twr / twr[START - 1]
    return dict(
        ver=ver, total=total, twr=twr, p=pser, cash=cashser, inflow=inflow, impday=impday, costday=costday,
        final=total[-1], cost_sub=cost_sub, cost_red=cost_red, cost_comm=cost_comm, cost_imp=cost_imp,
        cost_by_kind=cost_by_kind, n_sell=n_sell, n_rebuy=n_rebuy, n_special=n_special, stop_days=stop_days,
        avg_sell_px=sell_px / sell_amt if sell_amt else np.nan,
        avg_buy_px=buy_px / buy_amt if buy_amt else np.nan,
        turnover_amt=turnover_amt, trades=trades, triggers=triggers, decisions=decisions,
    )


def bench(D, inflow, cost=True, mode="bh"):
    """买入持有（初始 10 万 + 与策略相同的外部入金，当日全部买入）/ 定额定投（总入金相同、每日等额）。"""
    n = D.n
    nav = D.nav
    if mode == "dca":
        tot_in = inflow[START:].sum()
        flows = np.zeros(n)
        flows[START:] = tot_in / (n - START)
    else:
        flows = inflow.copy()
    if cost:
        rate = (1 - 0.001 - 0.5 * D.atr_rel) / 1.001
    else:
        rate = np.ones(n)
    sh = INIT_CAPITAL / nav[START - 1] + np.cumsum(np.where(np.arange(n) >= START, flows * rate / nav, 0))
    total = sh * nav
    total[:START] = INIT_CAPITAL
    return dict(total=total, inflow=flows, final=total[-1])


def xirr(inflow, final, start=START):
    """日度现金流 IRR（年化，252 交易日 / 年）。"""
    n = len(inflow)
    tt = (np.arange(start - 1, n) - (start - 1)) / YEAR
    cf = -np.r_[INIT_CAPITAL, inflow[start:]]
    cf = cf.astype(float)
    cf[-1] += final

    def npv(r):
        return np.sum(cf / (1 + r) ** tt)

    lo, hi = -0.9, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2
