"""沪深300 合成行情生成器（30 年日度，含中枢漂移、危机、波动率聚集、假回归陷阱）。

模型：
  log PE_t = c_t + d_t
    c_t : 估值中枢（缓慢漂移 / 快速跳变 / 固定）
    d_t : 相对中枢的偏离，均值回归过程 d += k_t (m_t - d) dt + s_t dW
          m_t / k_t 由事件脚本控制（危机、回调、泡沫、假回归、周期），平时 m=0、k=基础值
  log E_t : 每股收益，年化增长 g + 周期 + 危机冲击
  P_t = PE_t * E_t            价格指数
  ROE_t = ROE0 * 周期 * 危机 * exp(0.3 * (c_t - c_0))   中枢漂移伴随 ROE 永久偏移
  PB_t = PE_t * ROE_t         （ROE = PB / PE）
  DY_t = payout_t / PE_t
  y_t  = 10 年国债：OU + 危机宽松 / 过热收紧 − 0.04 * (c_t − c_0)
  TR_t = 全收益指数 = 价格 + 每日按 DY/252 再投资
"""
import numpy as np
import pandas as pd

YEAR = 252
N_YEARS = 30
SIGMA_DEV = 0.20          # 设计口径的偏离标准差（假回归判定用）


class Script:
    """分段线性目标脚本：在 [t0, t1] 内 m_t 线性插值，k_t 取 kappa。"""

    def __init__(self):
        self.m = None
        self.k = None


def _business_days(rng, n_years):
    days = pd.bdate_range("1996-01-01", periods=int(n_years * 261) + 20)
    # 随机剔除约 9 天 / 年的节假日，得到约 252 天 / 年
    keep = np.ones(len(days), bool)
    keep[rng.choice(len(days), size=int(len(days) * 9 / 261), replace=False)] = False
    days = days[keep][: n_years * YEAR]
    return days


def make_path(kind, seed, params=None):
    params = params or {}
    rng = np.random.default_rng(seed)
    n = N_YEARS * YEAR
    dates = _business_days(rng, N_YEARS)
    dt = 1.0 / YEAR
    t = np.arange(n)

    # ---------------- 中枢 c_t ----------------
    c0 = np.log(13.0)
    c = np.full(n, c0)
    drift_info = []
    slow_rate = params.get("slow_rate", 0.05)
    jump_size = params.get("jump_size", 0.20)

    def add_slow(start_y, end_y, rate):
        s, e = int(start_y * YEAR), min(n, int(end_y * YEAR))
        r = np.log(1 + rate) if rate > 0 else -np.log(1 + abs(rate))
        inc = np.zeros(n)
        inc[s:e] = r / YEAR
        drift_info.append(dict(type="slow", dir=int(np.sign(rate)), start=s, end=e, rate=rate))
        return np.cumsum(inc)

    def add_jump(at_y, size, dur_days):
        s = int(at_y * YEAR)
        e = s + dur_days
        r = np.log(1 + size) if size > 0 else -np.log(1 + abs(size))
        prof = np.zeros(n)
        x = np.clip((t - s) / dur_days, 0, 1)
        prof = r * (0.5 - 0.5 * np.cos(np.pi * x))
        drift_info.append(dict(type="jump", dir=int(np.sign(size)), start=s, end=e, size=size))
        return prof

    if kind == "slow_up":
        c += add_slow(7, 30, slow_rate)
    elif kind == "slow_down":
        c += add_slow(7, 30, -slow_rate)
    elif kind == "jump_up":
        y1 = rng.uniform(11, 13)
        c += add_jump(y1, jump_size, int(rng.integers(21, 64)))
        c += add_jump(y1 + rng.uniform(6, 8), jump_size, int(rng.integers(21, 64)))
    elif kind == "jump_down":
        y1 = rng.uniform(11, 13)
        c += add_jump(y1, -jump_size, int(rng.integers(21, 64)))
        c += add_jump(y1 + rng.uniform(6, 8), -jump_size, int(rng.integers(21, 64)))
    elif kind == "stagnation":
        c += add_slow(14, 30, -0.03)
    elif kind == "mixed":
        c += add_slow(7, 15, 0.05)
        c += add_jump(rng.uniform(17, 18), -0.25, int(rng.integers(21, 64)))
        c += add_jump(rng.uniform(23.5, 24.5), 0.20, int(rng.integers(21, 64)))

    # ---------------- 事件脚本 ----------------
    m = np.zeros(n)          # 偏离目标
    k = np.full(n, 1.0)      # 回归强度（年化）
    volmult = np.ones(n)
    y_shock = np.zeros(n)    # 国债收益率政策冲击（百分点）
    e_shock = np.zeros(n)    # 盈利冲击（log）
    roe_shock = np.zeros(n)
    events = []
    scripted = np.zeros(n, bool)

    def place(knots, kappa, vm=1.0):
        """knots: [(day, target), ...] 绝对日序；在区间内设置 m、k。"""
        for (d0, v0), (d1, v1) in zip(knots[:-1], knots[1:]):
            d0, d1 = int(d0), int(d1)
            if d0 >= n:
                return
            d1c = min(d1, n)
            seg = np.arange(d0, d1c)
            if d1 > d0:
                m[seg] = v0 + (v1 - v0) * (seg - d0) / (d1 - d0)
            k[seg] = kappa
            scripted[seg] = True
            volmult[seg] = np.maximum(volmult[seg], vm)

    def vol_bump(s, peak_mult, ramp=60, decay=180):
        idx = np.arange(n)
        up = np.clip(1 - (s - idx) / ramp, 0, 1) * (idx < s)
        down = np.exp(-(idx - s) / decay) * (idx >= s)
        volmult[:] = np.maximum(volmult, 1 + (peak_mult - 1) * np.maximum(up, down))

    def y_bump(s, size, ramp, decay):
        idx = np.arange(n)
        x = np.where(idx < s, 0.0, np.where(idx < s + ramp, (idx - s) / ramp, np.exp(-(idx - s - ramp) / decay)))
        y_shock[:] += size * x

    def crisis(at, drop, with_traps=True):
        """at: 崩盘起点。前置过热（含假回落），崩盘 + 假反弹（二次探底）。"""
        sd = SIGMA_DEV
        run = int(rng.integers(220, 300))
        s0 = at - run
        hi1 = rng.uniform(1.55, 1.8) * sd
        peak = max(hi1 + rng.uniform(-0.3, 0.4) * sd, 1.2 * sd)
        crash_len = int(rng.integers(70, 160))
        trough = min(peak + np.log(1 - drop), -1.55 * sd) if with_traps else peak + np.log(1 - drop)
        knots = [(s0, 0.0)]
        if with_traps:
            # 上升趋势：冲到 +1.7σ → 假回落到中枢附近（停留 ≤10 天）→ 再创新高
            a = s0 + int(run * 0.45)
            fall = int(rng.integers(20, 30))
            hold = int(rng.integers(1, 4))
            q = a + fall + hold
            knots += [(a, hi1), (a + fall, 0.0), (q, 0.0), (q + int(rng.integers(20, 30)), 1.2 * sd), (max(at, q + 60), peak)]
        else:
            knots += [(at, peak)]
        place(knots, 100.0)
        y_bump(s0, 0.6, run, 250)                     # 过热收紧
        # 崩盘
        if with_traps:
            low1 = trough
            mid = at + crash_len
            reb = int(rng.integers(20, 30))
            hold = int(rng.integers(1, 4))
            low2 = -rng.uniform(1.3, 1.6) * sd
            q = mid + reb + hold
            k2 = [(at, peak), (mid, low1), (mid + reb, 0.0), (q, 0.0),
                  (q + int(rng.integers(20, 30)), -1.2 * sd), (q + int(rng.integers(60, 100)), low2)]
            end = k2[-1][0]
            tday = mid
        else:
            k2 = [(at, peak), (at + crash_len, trough)]
            end = at + crash_len
            tday = end
        place(k2, 100.0, vm=2.5)
        vol_bump(at, rng.uniform(2.2, 3.0), ramp=40, decay=200)
        y_bump(at, -rng.uniform(0.8, 1.3), crash_len, 500)  # 危机后宽松
        idx = np.arange(n)
        sh = np.where(idx < at, 0, np.where(idx < end, (idx - at) / max(1, end - at), np.exp(-(idx - end) / 400)))
        e_shock[:] += -0.12 * sh
        roe_shock[:] += -0.10 * sh
        events.append(dict(type="crisis", start=s0, peak=at, trough=tday, end=end, drop=drop))

    def correction(at, drop):
        dur = int(rng.integers(40, 80))
        # 以当前目标为基准下挫（相对值在模拟时解析）
        rel_corr.append((at, dur, np.log(1 - drop)))
        vol_bump(at, 1.6, ramp=20, decay=90)
        events.append(dict(type="correction", start=at, peak=at, trough=at + dur, drop=drop))

    def trap(at, direction):
        """独立假回归：先偏离到 ±1.7σ，再假回归到中枢、停留 ≤10 天，随后沿原趋势偏离 ≥1σ。"""
        sd = SIGMA_DEV
        go = int(rng.integers(180, 260))
        ext = direction * rng.uniform(1.6, 1.9) * sd
        back = int(rng.integers(20, 30))
        hold = int(rng.integers(1, 4))
        again = direction * rng.uniform(1.7, 2.1) * sd
        cont = int(rng.integers(60, 110))
        s = at
        q = s + go + back + hold
        place([(s, 0.0), (s + go, ext), (s + go + back, 0.0), (q, 0.0),
               (q + int(rng.integers(20, 30)), direction * 1.2 * sd), (q + cont, again)],
              100.0, vm=1.0 if direction > 0 else 1.4)
        events.append(dict(type="trap_script", start=s, dir=direction))

    def bubble(at):
        run = int(rng.integers(320, 420))
        peak = rng.uniform(3.2, 3.8) * SIGMA_DEV
        a = at - run + int(run * 0.4)
        q = a + int(rng.integers(20, 30)) + int(rng.integers(1, 4))
        place([(at - run, 0.0), (a, 1.65 * SIGMA_DEV), (q - 2, 0.0), (q, 0.0),
               (q + int(rng.integers(20, 30)), 1.2 * SIGMA_DEV), (at, peak),
               (at + 62, peak + np.log(rng.uniform(0.40, 0.48)))], 100.0, vm=2.8)
        vol_bump(at, 3.0, ramp=30, decay=220)
        y_bump(at - run, 0.9, run, 300)
        idx = np.arange(n)
        sh = np.where(idx < at, 0, np.where(idx < at + 62, (idx - at) / 62, np.exp(-(idx - at - 62) / 400)))
        e_shock[:] += -0.10 * sh
        events.append(dict(type="bubble", start=at - run, peak=at, trough=at + 62, drop=0.55))

    rel_corr = []

    # 危机：每 7–10 年一次；中型回调：每 3–4 年一次
    def schedule_crises(first_y=(3.5, 6.0), traps=True, skip=()):
        y = rng.uniform(*first_y)
        out = []
        while y < N_YEARS - 1.0:
            out.append(y)
            y += rng.uniform(7, 10)
        for y in out:
            if any(lo <= y <= hi for lo, hi in skip):
                continue
            crisis(int(y * YEAR), rng.uniform(0.35, 0.55), with_traps=traps)
        return out

    def schedule_corrections(crisis_years, skip=()):
        y = rng.uniform(1.5, 3.0)
        while y < N_YEARS - 0.5:
            if all(abs(y - cy) > 1.5 for cy in crisis_years) and not any(lo <= y <= hi for lo, hi in skip):
                correction(int(y * YEAR), rng.uniform(0.15, 0.25))
            y += rng.uniform(3, 4)

    base_kappa = 1.0
    if kind == "cycle":
        # 强周期：带动量的牛熊大周期，估值振幅 ±40%
        per = rng.uniform(5.5, 7.0) * YEAR
        amp = np.log(1.4)
        phase = rng.uniform(0, 2 * np.pi)
        m[:] = amp * np.sin(2 * np.pi * t / per + phase)
        k[:] = 4.0
        cy = schedule_crises(traps=True)
        schedule_corrections(cy)
    elif kind == "bubble":
        b_at = int(rng.uniform(22.5, 24.0) * YEAR)
        cy = schedule_crises(traps=True, skip=[(b_at / YEAR - 3.5, b_at / YEAR + 3.0)])
        bubble(b_at)
        schedule_corrections(cy + [b_at / YEAR], skip=[(b_at / YEAR - 2, b_at / YEAR + 1)])
    elif kind == "stagnation":
        cy = schedule_crises(traps=True, skip=[(16, 30)])
        # 长停滞：16–22 年估值低位震荡（目标 −1.2σ），无有效反弹
        s, e = 16 * YEAR, 22 * YEAR
        m[s:e] = -1.2 * SIGMA_DEV
        k[s:e] = 3.0
        scripted[s:e] = True
        events.append(dict(type="stagnation", start=s, peak=s, trough=e, drop=0.0))
        cy2 = [24.5]
        crisis(int(rng.uniform(24.5, 26) * YEAR), rng.uniform(0.35, 0.45), with_traps=True)
        schedule_corrections(cy + cy2, skip=[(16, 22)])
    elif kind == "fake_reversion":
        cy = schedule_crises(first_y=(5.0, 6.0), traps=True)
        # 额外独立陷阱：上/下交替，确保全程 ≥ 6 次
        y = 2.0
        d = 1
        while y < N_YEARS - 2:
            if all(abs(y - c_) > 2.2 and abs(y + 1.2 - c_) > 2.2 for c_ in cy):
                trap(int(y * YEAR), d)
                d = -d
                y += rng.uniform(2.4, 3.0)
            else:
                y += 0.5
    elif kind == "mixed":
        cy = schedule_crises(traps=True)
        y = 2.5
        d = -1
        for _ in range(3):
            while any(abs(y - c_) < 2.3 or abs(y + 1.2 - c_) < 2.3 for c_ in cy) and y < N_YEARS - 2:
                y += 0.4
            if y < N_YEARS - 2:
                trap(int(y * YEAR), d)
                d = -d
            y += rng.uniform(4, 6)
        schedule_corrections(cy)
    else:
        cy = schedule_crises(traps=True)
        schedule_corrections(cy)

    # ---------------- 模拟偏离 d_t ----------------
    sig0 = params.get("sigma", 0.17)
    eps = rng.standard_normal(n)
    # 波动率聚集：对数波动率 OU
    lv = np.zeros(n)
    z = rng.standard_normal(n)
    for i in range(1, n):
        lv[i] = lv[i - 1] * (1 - 3.0 * dt) + 0.5 * np.sqrt(dt) * z[i]
    sig = sig0 * volmult * np.exp(lv - 0.5 * 0.5 ** 2 / (2 * 3.0))
    corr_map = {}
    for at, dur, dl in rel_corr:
        corr_map[at] = (dur, dl)
    d = np.zeros(n)
    d[0] = rng.normal(0, 0.1)
    corr_active = None
    for i in range(1, n):
        mi, ki = m[i], k[i]
        if i in corr_map and not scripted[i]:
            dur, dl = corr_map[i]
            corr_active = (i, i + dur, d[i - 1], d[i - 1] + dl)
        if corr_active is not None:
            s_, e_, v0, v1 = corr_active
            if i < e_ and not scripted[i]:
                mi = v0 + (v1 - v0) * (i - s_) / (e_ - s_)
                ki = 25.0
            else:
                corr_active = None
        noise_scale = 1.0
        d[i] = d[i - 1] + ki * (mi - d[i - 1]) * dt + sig[i] * noise_scale * np.sqrt(dt) * eps[i]

    logpe = c + d
    pe = np.exp(logpe)

    # ---------------- 盈利、ROE、股息、利率 ----------------
    g0 = params.get("g", 0.06 if kind != "stagnation" else 0.03)
    gcyc = np.zeros(n)
    zz = rng.standard_normal(n)
    for i in range(1, n):
        gcyc[i] = gcyc[i - 1] * (1 - 0.5 * dt) + 0.05 * np.sqrt(dt) * zz[i]
    loge = np.cumsum(np.full(n, g0 * dt) + gcyc * dt + 0.004 * rng.standard_normal(n)) + e_shock
    if kind == "stagnation":
        loge[16 * YEAR:22 * YEAR] -= np.linspace(0, 0.05, 6 * YEAR)
        loge[22 * YEAR:] -= 0.05
    price = 1000.0 * np.exp(logpe - logpe[0] + loge - loge[0])

    roe_cyc = np.zeros(n)
    zr = rng.standard_normal(n)
    for i in range(1, n):
        roe_cyc[i] = roe_cyc[i - 1] * (1 - 0.4 * dt) + 0.06 * np.sqrt(dt) * zr[i]
    roe = 0.12 * np.exp(roe_cyc + roe_shock + 0.30 * (c - c0))
    pb = pe * roe
    payout = 0.33 * np.exp(0.05 * np.sin(2 * np.pi * t / (YEAR * 4.3)) + np.cumsum(0.002 * rng.standard_normal(n)) * 0.2)
    dy = payout / pe

    y = np.zeros(n)
    zy = rng.standard_normal(n)
    yb = 0.0
    for i in range(1, n):
        yb = yb * (1 - 0.6 * dt) + 0.55 * np.sqrt(dt) * zy[i]
        y[i] = yb
    y = 3.4 + y + y_shock - 4.0 * (c - c0)
    y = np.maximum(y, 1.0) / 100.0

    # ---------------- OHLC、全收益 ----------------
    r = np.diff(np.log(price), prepend=np.log(price[0]))
    dsig = np.maximum(np.abs(r), sig / np.sqrt(YEAR) * 0.6)
    close = price
    openp = np.empty(n)
    openp[0] = close[0]
    openp[1:] = close[:-1] * np.exp(0.25 * r[1:] + 0.002 * rng.standard_normal(n - 1))
    hi = np.maximum(openp, close) * np.exp(np.abs(rng.normal(0, 0.45, n)) * dsig)
    lo = np.minimum(openp, close) * np.exp(-np.abs(rng.normal(0, 0.45, n)) * dsig)
    tr = np.empty(n)
    tr[0] = 1000.0
    tr[1:] = tr[0] * np.cumprod(close[1:] / close[:-1] * (1 + dy[:-1] / YEAR))

    df = pd.DataFrame(dict(date=dates, open=openp, high=hi, low=lo, close=close, tr=tr,
                           pe=pe, pb=pb, dy=dy, y=y, roe=roe, center=np.exp(c), dev=d))
    meta = dict(kind=kind, seed=seed, events=events, drift=drift_info, params=params)
    return df, meta


def detect_traps(dev, sd=SIGMA_DEV, start=0):
    """按定义识别假回归：|偏离| ≥ 1.5σ 的极端状态 → 回到中枢 ±0.2σ 内、停留 ≤ 10 天
    → 之后（120 天内）沿原方向偏离 ≥ 1σ。返回 [(dir, extreme_day, touch_start, touch_end, resume_day)]。
    dir=+1：上升趋势中的假回落；dir=-1：下降趋势中的假反弹。"""
    n = len(dev)
    out = []
    i = start
    last_ext_day, last_ext_dir = None, 0
    while i < n:
        x = dev[i]
        if abs(x) >= 1.5 * sd:
            last_ext_day, last_ext_dir = i, int(np.sign(x))
            i += 1
            continue
        if last_ext_day is not None and abs(x) <= 0.2 * sd and i - last_ext_day <= 120:
            j = i
            while j < n and abs(dev[j]) <= 0.2 * sd:
                j += 1
            stay = j - i
            if stay <= 10:
                # 向后寻找沿原方向的 ≥1σ 偏离，期间不得出现反方向 ≥1σ
                k = j
                ok = None
                while k < min(n, j + 160):
                    if last_ext_dir * dev[k] >= 1.0 * sd:
                        ok = k
                        break
                    if -last_ext_dir * dev[k] >= 1.0 * sd:
                        break
                    k += 1
                if ok is not None:
                    out.append((last_ext_dir, last_ext_day, i, j - 1, ok))
                    last_ext_day = None
                    i = ok
                    continue
            last_ext_day = None
            i = j
            continue
        i += 1
    return out


def trap_ok(df, meta):
    """校验：每个脚本化的单边趋势（危机前过热 / 崩盘、泡沫拉升、独立陷阱）都识别到至少 1 次同向假回归。"""
    tr = detect_traps(df.dev.values)
    def has(d, lo, hi):
        return any(x[0] == d and lo <= x[2] <= hi for x in tr)
    for e in meta["events"]:
        if e["type"] == "crisis":
            if not has(1, e["start"], e["peak"]) or not has(-1, e["peak"], e["end"] + 30):
                return False
        elif e["type"] == "bubble":
            if not has(1, e["start"], e["peak"]):
                return False
        elif e["type"] == "trap_script":
            if not has(e["dir"], e["start"], e["start"] + 500):
                return False
    if meta["kind"] == "fake_reversion" and len([x for x in tr if x[2] >= 8 * YEAR]) < 6:
        return False
    return True


def make_valid_path(kind, seed, params=None, max_try=200):
    for k in range(max_try):
        df, meta = make_path(kind, seed + 7919 * k, params)
        if trap_ok(df, meta):
            meta["seed_used"] = seed + 7919 * k
            meta["traps"] = detect_traps(df.dev.values)
            return df, meta
    raise RuntimeError("no valid path for %s" % kind)


PATH_SPECS = [
    # (编号, kind, 中文名, 数据集, 种子)
    (1, "base", "基准震荡型", "训练集", 1101),
    (2, "slow_up", "缓慢漂移上移型", "训练集", 1202),
    (3, "slow_down", "缓慢漂移下移型", "测试集", 1303),
    (4, "jump_up", "快速跳升上移型", "训练集", 1404),
    (5, "jump_down", "快速跳降下移型", "测试集", 1505),
    (6, "cycle", "强周期波动型", "训练集", 1606),
    (7, "bubble", "泡沫崩盘型（样本外）", "测试集", 1707),
    (8, "stagnation", "长停滞型", "复核集", 2808),
    (9, "fake_reversion", "高频假回归型", "复核集", 2909),
    (10, "mixed", "混合极端型", "复核集", 3010),
]
