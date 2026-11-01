/* 沪深300 六组策略 · 合成行情 + 回测引擎（Node 与浏览器共用）
 * 交易日口径：1 年 = 252 个交易日；1 周 = 5 个交易日；
 * 日历天换算：7 天 → 5 个交易日，30 天 → 21，180 天 → 124。
 */
(function (root) {
'use strict';
const Y = 252;
const clip = (x, a, b) => (x < a ? a : x > b ? b : x);
const ss = u => u * u * (3 - 2 * u);            // smoothstep
const lin = u => u;

// ---------------------------------------------------------------- RNG
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function makeRng(seed) {
  const u = mulberry32((seed * 2654435761) >>> 0);
  for (let i = 0; i < 10; i++) u();
  let spare = null;
  return {
    u,
    n() {
      if (spare !== null) { const s = spare; spare = null; return s; }
      let a, b, s;
      do { a = u() * 2 - 1; b = u() * 2 - 1; s = a * a + b * b; } while (s >= 1 || s === 0);
      const m = Math.sqrt(-2 * Math.log(s) / s); spare = b * m; return a * m;
    },
    r(lo, hi) { return lo + (hi - lo) * u(); },
    i(lo, hi) { return lo + Math.floor((hi - lo + 1) * u()); },
    pick(arr) { return arr[Math.floor(u() * arr.length)]; },
    chance(p) { return u() < p; },
  };
}

// ---------------------------------------------------------------- 场景定义
const SCENARIOS = [
  { id: 1, key: 'base', name: '基准震荡型', short: '基准震荡' },
  { id: 2, key: 'peUpRoeDn', name: 'PE慢上+ROE慢下型', short: 'PE↑ROE↓' },
  { id: 3, key: 'pbDn', name: 'PE震荡+PB慢下型', short: 'PB慢下' },
  { id: 4, key: 'rateJump', name: '利率单独跳变型', short: '利率跳变' },
  { id: 5, key: 'asyncJump', name: '多指标异步跳变型', short: '异步跳变' },
  { id: 6, key: 'cycle', name: '强周期波动型', short: '强周期' },
  { id: 7, key: 'bubble', name: '泡沫崩盘型', short: '泡沫崩盘' },
  { id: 8, key: 'stagnation', name: '长期停滞型', short: '长期停滞' },
  { id: 9, key: 'falseRev', name: '高频假回归型', short: '高频假回归' },
  { id: 10, key: 'composite', name: '复合极端型', short: '复合极端' },
];
// 数据集划分：训练 4 / 测试 3（含样本外极端 10）/ 复核 3
const SPLIT = { 1: 'train', 2: 'train', 6: 'train', 9: 'train', 3: 'test', 5: 'test', 10: 'test', 4: 'review', 7: 'review', 8: 'review' };

const BASE = { pe: 13, roe: 0.115, pay: 0.32, y: 0.032, vol: 0.0112, sigX: 0.24, dil: 0.015 };

// 生成场景规格（事件时点与幅度随种子抖动）
function scenarioSpec(type, seed, over) {
  const rng = makeRng(seed * 7 + 13);
  const years = 42, N = years * Y, warm = 10 * Y;
  const sp = {
    type, seed, N, warm, years, sigX: BASE.sigX,
    base: Object.assign({}, BASE),
    ev: { pe: [], roe: [], pay: [], y: [], vol: [] },
    w: { bull: 0.36, bear: 0.30, range: 0.34 },
    amp: 1.0, rangeAmp: 1.0, momentum: 0, betaMode: 'stable', betaLag: 63, gammaRoe: 0,
    trapsPerTrend: 1, minTraps: 0, bigGap: [7, 10], medGap: [3, 4], bigDD: [0.35, 0.55], medDD: [0.15, 0.25],
    volCrisis: [2, 3], bubbleAt: null, bubbleDD: [0.52, 0.6], extraBig: 0,
  };
  const slow = (k, startYr, yrs, ratePct) => sp.ev[k].push({ kind: 'slow', start: Math.round(startYr * Y), dur: Math.round(yrs * Y), mult: Math.pow(1 + ratePct / 100, yrs) });
  const jump = (k, atYr, pct) => sp.ev[k].push({ kind: 'jump', start: Math.round(atYr * Y), dur: rng.i(21, 63), mult: 1 + pct / 100 });
  const sgn = () => (rng.chance(0.5) ? 1 : -1);
  switch (type) {
    case 1: break;
    case 2:
      slow('pe', rng.r(11, 14), rng.r(10, 13), rng.r(3.5, 6));
      slow('roe', rng.r(12, 16), rng.r(9, 12), -rng.r(3, 5));
      sp.betaMode = 'weak'; break;
    case 3:
      slow('roe', rng.r(11, 14), rng.r(12, 15), -rng.r(3.5, 5.5));
      sp.w = { bull: 0.28, bear: 0.24, range: 0.48 }; sp.betaMode = 'weak'; break;
    case 4: {
      const j1 = rng.r(16, 20); jump('y', j1, rng.r(20, 30));
      jump('y', j1 + rng.r(5, 8), -rng.r(15, 22));
      sp.betaMode = 'lagged'; sp.betaLag = 252; break;
    }
    case 5: {
      const t1 = rng.r(12, 15); jump('pe', t1, rng.r(15, 25));
      jump('roe', rng.r(17, 21), -rng.r(15, 25));
      jump('pay', rng.r(22, 26), rng.r(18, 28));
      jump('pe', Math.max(t1 + 4, rng.r(30, 34)), -rng.r(15, 22));
      sp.betaMode = 'cyclical'; break;
    }
    case 6:
      sp.amp = 1.35; sp.momentum = 0.08; sp.w = { bull: 0.42, bear: 0.40, range: 0.18 }; sp.betaMode = 'cyclical';
      slow('vol', rng.r(12, 16), rng.r(6, 8), rng.r(3, 5)); slow('vol', rng.r(26, 30), rng.r(6, 8), -rng.r(3, 5)); break;
    case 7:
      sp.bubbleAt = rng.r(19, 23); sp.betaMode = 'cyclical'; break;
    case 8:
      sp.base.roe = 0.095; slow('roe', rng.r(9, 12), rng.r(22, 26), -rng.r(2, 3.5));
      sp.w = { bull: 0.2, bear: 0.2, range: 0.6 }; sp.amp = 0.75; sp.rangeAmp = 0.8; sp.betaMode = 'weak'; break;
    case 9:
      sp.trapsPerTrend = 2; sp.minTraps = 6; sp.w = { bull: 0.42, bear: 0.40, range: 0.18 };
      slow('roe', rng.r(11, 13), rng.r(6, 7), rng.r(3, 5)); slow('roe', rng.r(24, 26), rng.r(6, 8), -rng.r(3, 4.5));
      slow('pay', rng.r(14, 17), rng.r(6, 8), rng.r(3, 5)); slow('y', rng.r(13, 16), rng.r(7, 9), -rng.r(3, 5));
      sp.betaMode = 'cyclical'; break;
    case 10:
      slow('pe', rng.r(11, 13), rng.r(7, 9), rng.r(4, 6)); slow('roe', rng.r(13, 15), rng.r(8, 10), -rng.r(3.5, 5));
      jump('y', rng.r(19, 21), rng.r(20, 30)); jump('pay', rng.r(26, 28), rng.r(18, 26)); jump('pe', rng.r(33, 35), -rng.r(16, 24));
      jump('vol', rng.r(29, 31), rng.r(20, 30));
      sp.trapsPerTrend = 2; sp.minTraps = 6; sp.amp = 1.2; sp.betaMode = 'cyclical'; sp.bigGap = [7, 8]; sp.bubbleAt = rng.r(23, 26);
      break;
  }
  if (over) Object.assign(sp, over);
  return sp;
}

// 自定义压力测试场景
function customSpec(o, seed) {
  const sp = scenarioSpec(1, seed);
  const rng = makeRng(seed * 31 + 7);
  sp.type = 0;
  sp.bigDD = [o.crisisDD * 0.9, Math.min(0.75, o.crisisDD * 1.1)];
  sp.bigGap = [o.crisisGap, o.crisisGap + 1.5];
  sp.base.vol = BASE.vol * o.volMult;
  sp.volCrisis = [o.volCrisis * 0.9, o.volCrisis * 1.1];
  sp.trapsPerTrend = o.trapsPerTrend; sp.minTraps = 0;
  sp.amp = o.amp;
  const addDrift = (k, rate, start, yrs) => { if (Math.abs(rate) > 1e-9) sp.ev[k].push({ kind: 'slow', start: Math.round(start * Y), dur: Math.round(yrs * Y), mult: Math.pow(1 + rate / 100, yrs) }); };
  addDrift('pe', o.peDrift, 11, 12); addDrift('roe', o.roeDrift, 12, 14); addDrift('pay', o.payDrift, 13, 12); addDrift('y', o.yDrift, 12, 12);
  if (o.peJump) sp.ev.pe.push({ kind: 'jump', start: Math.round(o.peJumpAt * Y), dur: 42, mult: 1 + o.peJump / 100 });
  if (o.yJump) sp.ev.y.push({ kind: 'jump', start: Math.round(o.yJumpAt * Y), dur: 42, mult: 1 + o.yJump / 100 });
  if (o.bubble) sp.bubbleAt = 22;
  sp.betaMode = o.betaMode || 'stable';
  return sp;
}

// ---------------------------------------------------------------- 路径生成
function buildCenter(base, events, N) {
  const out = new Float64Array(N), d = new Float64Array(N);
  for (const ev of events) {
    const s = Math.max(0, ev.start), dur = Math.max(1, ev.dur), tot = Math.log(ev.mult);
    for (let i = 0; i < dur; i++) {
      const t = s + i; if (t >= N) break;
      d[t] += ev.kind === 'jump' ? tot * (ss((i + 1) / dur) - ss(i / dur)) : tot / dur;
    }
  }
  let c = Math.log(base);
  for (let t = 0; t < N; t++) { c += d[t]; out[t] = Math.exp(c); }
  return out;
}

function crisisSchedule(sp, rng) {
  const N = sp.N, list = [];
  let b = rng.r(2, 6) * Y;
  const bigs = [];
  while (b < N - 60) { bigs.push(b); b += rng.r(sp.bigGap[0], sp.bigGap[1]) * Y; }
  for (let k = 0; k < bigs.length; k++) {
    list.push({ start: Math.round(bigs[k]), big: true });
    const next = k + 1 < bigs.length ? bigs[k + 1] : N;
    let m = bigs[k] + rng.r(sp.medGap[0], sp.medGap[1]) * Y;
    while (m <= next - 2.5 * Y && m < N - 60) { list.push({ start: Math.round(m), big: false }); m += rng.r(sp.medGap[0], sp.medGap[1]) * Y; }
  }
  // 中型回调也补在第一场大型危机之前
  let m0 = bigs[0] - rng.r(sp.medGap[0], sp.medGap[1]) * Y;
  if (m0 > 0.8 * Y) list.push({ start: Math.round(m0), big: false });
  if (sp.bubbleAt) { // 泡沫崩盘替换最近的一次大型危机
    const bt = Math.round(sp.bubbleAt * Y);
    let bi = -1, bd = 1e9;
    list.forEach((c, i) => { if (c.big && Math.abs(c.start - bt) < bd) { bd = Math.abs(c.start - bt); bi = i; } });
    if (bi >= 0 && bd < 3 * Y) list.splice(bi, 1);
    for (let i = list.length - 1; i >= 0; i--) if (Math.abs(list[i].start - bt) < 2.2 * Y) list.splice(i, 1);
    list.push({ start: bt, big: true, bubble: true });
  }
  list.sort((a, b2) => a.start - b2.start);
  for (const c of list) {
    c.dd = c.bubble ? rng.r(sp.bubbleDD[0], sp.bubbleDD[1]) : c.big ? rng.r(sp.bigDD[0], sp.bigDD[1]) : rng.r(sp.medDD[0], sp.medDD[1]);
    c.len = c.bubble ? rng.i(50, 63) : c.big ? rng.i(45, 63) : rng.i(25, 50);
    c.volK = c.big ? rng.r(sp.volCrisis[0], sp.volCrisis[1]) : rng.r(1.5, 2.1);
    c.roeHit = c.big ? rng.r(0.12, 0.28) : rng.r(0.04, 0.10);
    c.roeRec = rng.r(0.7, 2.2) * Y;     // 盈利恢复速度独立
    c.ease = c.big ? rng.r(0.005, 0.012) : rng.r(0.002, 0.005);
    c.easeLag = rng.i(21, 63);
  }
  return list;
}

// 估值偏离规划路径（单位：σ）
function buildPlan(sp, rng, crises) {
  const N = sp.N, plan = new Float64Array(N), lab = new Uint8Array(N); // 0 震荡 1 牛 2 熊 3 危机 4 修复
  const traps = [];
  let t = 0, lvl = rng.r(-0.3, 0.3), ci = 0, prev = 'range';
  const amp = sp.amp;
  const shapeUp = sp.momentum > 0 ? (u => Math.pow(u, 1.7)) : ss;
  // 沿路标填充；遇到 limit 截断。返回 [到达时间, 到达水平, 是否完整]
  function run(points, limit, label) {
    // points: [{d: 天数, to: 水平, shape, label}]
    for (const p of points) {
      const from = lvl, d = Math.max(1, Math.round(p.d));
      for (let i = 0; i < d; i++) {
        if (t >= limit || t >= N) { if (t > 0) lvl = plan[t - 1]; return false; }
        const u = (i + 1) / d; plan[t] = from + (p.to - from) * (p.shape || ss)(u); lab[t] = p.label != null ? p.label : label; t++;
      }
      lvl = p.to;
    }
    return true;
  }
  function trend(dir, limit) {
    const isBull = dir > 0;
    let target = isBull ? Math.max(lvl + 0.6, rng.r(1.2, 2.2) * amp) : Math.min(lvl - 0.6, -rng.r(1.0, 2.0) * amp);
    const dur = (isBull ? rng.r(1.0, 2.8) : rng.r(0.9, 2.2)) * Y;
    const s = dir, label = isBull ? 1 : 2;
    const pts = [];
    const nTr = sp.trapsPerTrend;
    let canTrap = s * lvl < 0.5;
    const plannedTraps = [];
    if (canTrap && nTr > 0) {
      let Lk = s * rng.r(0.6, 0.9) * Math.max(1, amp * 0.9);
      if (s * target < Math.max(1.2, s * Lk + 0.3)) target = s * Math.max(1.2, s * Lk + 0.35);
      plannedTraps.push(Lk);
      if (nTr >= 2 && dur > 1.4 * Y) {
        const Lk2 = Lk + s * rng.r(0.35, 0.6);
        if (s * target < s * Lk2 + 0.3) target = Lk2 + s * 0.35;
        plannedTraps.push(Lk2);
      }
    }
    const total = Math.abs(target - lvl);
    let lastLvl = lvl;
    for (const Lk of plannedTraps) {
      const dd = Math.max(40, dur * Math.abs(Lk - lastLvl) / total);
      pts.push({ d: dd, to: Lk, shape: lin, trapPre: true });
      const dip = rng.i(8, 15), hold = rng.i(3, 8), ret = rng.i(12, 25), touch = s * rng.r(0, 0.1);
      pts.push({ d: dip, to: touch, shape: ss, trap: { dir: s, Lk, dip, hold, ret } });
      pts.push({ d: hold, to: touch + s * 0.02, shape: lin });
      pts.push({ d: ret, to: Lk, shape: ss });
      lastLvl = Lk;
    }
    pts.push({ d: Math.max(60, dur * Math.abs(target - lastLvl) / total), to: target, shape: isBull ? shapeUp : ss });
    // 逐段执行并记录陷阱
    for (let k = 0; k < pts.length; k++) {
      const p = pts[k];
      if (p.trap) {
        const st = t;
        const ok = run([p, pts[k + 1], pts[k + 2]], limit, label);
        if (!ok) return;
        traps.push({ start: st, touchStart: st + p.trap.dip - 2, touchEnd: st + p.trap.dip + p.trap.hold, end: t, dir: s > 0 ? 'up' : 'down', Lk: p.trap.Lk, target, segEndPlan: null });
        k += 2; continue;
      }
      if (!run([p], limit, label)) { traps.forEach(tr => { if (tr.segEndPlan === null) tr.segEndPlan = t; }); return; }
    }
    traps.forEach(tr => { if (tr.segEndPlan === null) tr.segEndPlan = t; });
  }
  function range(limit) {
    const dur = rng.r(0.8, 2.2) * Y, end = t + dur;
    while (t < end && t < limit) {
      const tgt = rng.r(-0.55, 0.55) * sp.rangeAmp;
      if (!run([{ d: rng.r(0.25, 0.6) * Y, to: tgt, shape: ss }], Math.min(limit, end + 0.3 * Y), 0)) return;
    }
  }
  function crisis(c) {
    const limitNext = ci + 1 < crises.length ? crises[ci + 1].start : N;
    const drop = (c.bubble ? 1.0 : 0.8) * Math.log(1 - c.dd) / sp.sigX;
    const accel = u => 1 - Math.pow(1 - u, 1.6);
    run([{ d: c.len, to: lvl + drop, shape: u => u < 0.5 ? 0.3 * accel(u * 2) : 0.3 + 0.7 * ss((u - 0.5) * 2), label: 3 }], N, 3);
    c.end = t;
    if (rng.chance(c.big ? 0.25 : 0.12)) run([{ d: rng.r(0.35, 0.8) * Y, to: lvl - rng.r(0.25, 0.6), shape: ss }], limitNext, 2);
    run([{ d: (c.big ? rng.r(1.2, 2.5) : rng.r(0.5, 1.0)) * Y, to: rng.r(-0.4, 0.4), shape: ss }], limitNext, 4);
  }
  while (t < N) {
    const nc = ci < crises.length ? crises[ci] : null;
    const limit = nc ? nc.start : N;
    if (nc && nc.bubble) {
      const bDur = Math.round(rng.r(1.0, 1.5) * Y);
      if (limit - t <= bDur + 40) {
        if (limit - t > 0) {
          const target = Math.max(lvl + 2.0, rng.r(3.0, 3.4));
          run([{ d: limit - t, to: target, shape: u => Math.pow(u, 2.0) }], limit, 1);
        }
        t = limit; crisis(nc); ci++; prev = 'crisis'; continue;
      }
    }
    if (nc && limit - t < 45) {
      if (limit - t > 0) run([{ d: limit - t, to: lvl + rng.r(-0.1, 0.15), shape: ss }], limit, prev === 'bull' ? 1 : 0);
      t = limit; crisis(nc); ci++; prev = 'crisis'; continue;
    }
    const w = Object.assign({}, sp.w);
    if (lvl > 0.9) w.bull *= 0.12; if (lvl < -0.9) w.bear *= 0.12;
    if (prev === 'bull') w.bull *= 0.4; if (prev === 'bear') w.bear *= 0.4;
    if (nc && nc.big && limit - t < 3 * Y) w.bull *= 2;
    const tot = w.bull + w.bear + w.range, r = rng.u() * tot;
    const kind = r < w.bull ? 'bull' : r < w.bull + w.bear ? 'bear' : 'range';
    if (kind === 'range') range(limit); else trend(kind === 'bull' ? 1 : -1, limit);
    prev = kind;
  }
  return { plan, lab, traps };
}

function genPath(sp) {
  if (!sp.minTraps) return genPath1(sp);
  let best = null;
  for (let k = 0; k < 40; k++) {
    const p = genPath1(Object.assign({}, sp, { seed: sp.seed + 7919 * k }));
    const nv = p.traps.filter(t => t.start >= p.warm && t.valid).length;
    if (!best || nv > best.nv) best = { p, nv };
    if (nv >= sp.minTraps) return p;
  }
  return best.p;
}
function genPath1(sp) {
  const rng = makeRng(sp.seed);
  const N = sp.N, b = sp.base;
  const crises = crisisSchedule(sp, rng);
  const { plan, lab, traps } = buildPlan(sp, rng, crises);
  const cPE = buildCenter(b.pe, sp.ev.pe, N), cROE = buildCenter(b.roe, sp.ev.roe, N), cPay = buildCenter(b.pay, sp.ev.pay, N);
  const cY = buildCenter(b.y, sp.ev.y, N), cVol = buildCenter(b.vol, sp.ev.vol, N);
  // beta(t) 估值对利率偏离的敏感度，可升降、反转
  const betaRaw = new Float64Array(N);
  { let t = 0; let cur = 1;
    while (t < N) {
      const d = Math.round(rng.r(2, 5) * Y);
      if (sp.betaMode === 'stable') cur = 1; else if (sp.betaMode === 'weak') cur = rng.pick([0.6, 0.3, 0.8]);
      else if (sp.betaMode === 'lagged') cur = rng.pick([0.2, 0.5, 0.0]); else cur = rng.pick([1.3, 0.6, 0, -0.6]);
      for (let i = 0; i < d && t < N; i++, t++) betaRaw[t] = cur;
    } }
  const beta = new Float64Array(N); { let s = betaRaw[0]; for (let t = 0; t < N; t++) { s += (betaRaw[t] - s) / 63; beta[t] = s; } }
  // 利率：中枢 + OU + 政策 + 危机宽松
  const pol = new Float64Array(N);
  const polEv = []; { let t = Math.round(rng.r(0.5, 1.5) * Y), dir = rng.chance(0.5) ? 1 : -1;
    while (t < N) { polEv.push({ start: t, mag: dir * rng.r(0.0025, 0.0075), dur: rng.i(63, 126) }); if (rng.chance(0.65)) dir = -dir; t += Math.round(rng.r(1.0, 2.2) * Y); } }
  for (const c of crises) polEv.push({ start: c.start + c.easeLag, mag: -c.ease, dur: 126, crisis: true });
  const polInc = new Float64Array(N);
  for (const e of polEv) for (let i = 0; i < e.dur; i++) { const t = e.start + i; if (t < N) polInc[t] += e.mag / e.dur; }
  const yld = new Float64Array(N);
  { let ou = 0, p = 0; const k = Math.LN2 / Y, kp = Math.LN2 / (1.5 * Y), sd = 0.004 * Math.sqrt(2 * k);
    for (let t = 0; t < N; t++) { ou += -k * ou + sd * rng.n(); p += polInc[t] - kp * p; pol[t] = p; yld[t] = Math.max(0.008, cY[t] + ou + p); } }
  // 波动率：中枢 × 聚集 × 危机放大
  const crisisMult = new Float64Array(N).fill(1);
  for (const c of crises) {
    for (let t = Math.max(0, c.start - 20); t < Math.min(N, c.start + c.len + 250); t++) {
      let w;
      if (t < c.start) w = (t - (c.start - 20)) / 20; else if (t < c.start + c.len) w = 1; else w = Math.exp(-(t - c.start - c.len) / 45);
      crisisMult[t] = Math.max(crisisMult[t], 1 + (c.volK - 1) * w);
    }
  }
  const sig = new Float64Array(N);
  { let h = 0; for (let t = 0; t < N; t++) { h += -h / 40 + 0.055 * rng.n(); sig[t] = cVol[t] * Math.exp(h) * crisisMult[t]; } }
  // ROE 周期 + 危机冲击（滞后、独立恢复）
  const roeS = new Float64Array(N);
  { let r = 0; const k = Math.LN2 / (1.5 * Y), sd = 0.06 * Math.sqrt(2 * k);
    const hit = new Float64Array(N);
    for (const c of crises) {
      const s0 = c.start + 63;
      for (let t = s0; t < N; t++) {
        const i = t - s0; let w = i < 126 ? ss(i / 126) : Math.exp(-(i - 126) * Math.LN2 / c.roeRec);
        if (w < 0.002) break; hit[t] += -c.roeHit * w;
      }
    }
    const g = sp.gammaRoe;
    for (let t = 0; t < N; t++) { r += -k * r + sd * rng.n(); const pe = t >= 252 ? -pol[t - 252] : 0; roeS[t] = cROE[t] * Math.exp(r + hit[t] + g * pe); } }
  const payS = new Float64Array(N);
  { let q = 0; const k = Math.LN2 / Y, sd = 0.05 * Math.sqrt(2 * k); for (let t = 0; t < N; t++) { q += -k * q + sd * rng.n(); payS[t] = clip(cPay[t] * Math.exp(q), 0.05, 0.9); } }
  // 价格
  const close = new Float64Array(N), high = new Float64Array(N), low = new Float64Array(N);
  const pe = new Float64Array(N), pb = new Float64Array(N), roe = new Float64Array(N), dy = new Float64Array(N), nav = new Float64Array(N);
  let Bs = 1, e = 0, ePrev = 0, Erep = 0, Brep = 0, Prep = 0;
  const sigX = sp.sigX, kap = 1 / 30, phi = sp.momentum;
  for (let t = 0; t < N; t++) {
    Bs *= Math.exp((roeS[t] * (1 - payS[t]) - b.dil) / Y);
    const Es = roeS[t] * Bs;
    const eNew = e - kap * e + phi * (e - ePrev) + sig[t] * rng.n(); ePrev = e; e = eNew;
    const lag = sp.betaLag, ul = t >= lag ? (yld[t - lag] - cY[t - lag]) : 0;
    const xr = -beta[t] * 6 * ul;
    const logPE = Math.log(cPE[t]) + sigX * plan[t] + e + xr;
    const P = Math.exp(logPE) * Es * 1000 / (b.pe * b.roe);
    if (t % 63 === 0) { Erep = Es * 1000 / (b.pe * b.roe); Brep = Bs * 1000 / (b.pe * b.roe); Prep = payS[t]; }
    close[t] = P;
    pe[t] = P / Erep; pb[t] = P / Brep; roe[t] = Erep / Brep; dy[t] = Prep * Erep / P;
  }
  // 价格从 1000 点附近起步
  for (let t = 0; t < N; t++) {
    const pc = t > 0 ? close[t - 1] : close[0];
    const hi = Math.max(pc, close[t]), lo = Math.min(pc, close[t]);
    high[t] = hi * Math.exp(Math.abs(rng.n()) * 0.45 * sig[t]);
    low[t] = lo * Math.exp(-Math.abs(rng.n()) * 0.45 * sig[t]);
    nav[t] = t === 0 ? 1 : nav[t - 1] * (close[t] / close[t - 1] + dy[t - 1] / Y);
  }
  // 危机实际回撤
  for (const c of crises) {
    let pk = close[c.start], tr = pk, ti = c.start;
    for (let t = Math.max(0, c.start - 20); t <= c.start; t++) if (close[t] > pk) pk = close[t];
    for (let t = c.start; t < Math.min(N, c.start + c.len + 40); t++) if (close[t] < tr) { tr = close[t]; ti = t; }
    c.trough = ti; c.ddReal = 1 - tr / pk;
    let pi = c.start; for (let t = Math.max(0, c.start - 60); t <= c.start + 5 && t < N; t++) if (close[t] >= close[pi]) pi = t;
    c.peak = pi;
  }
  // 陷阱实测校验：触碰期内估值偏离是否落在中枢 ±0.2σ 内、之后是否继续偏离 ≥1σ
  const dev = new Float64Array(N);
  for (let t = 0; t < N; t++) dev[t] = Math.log(pe[t] / cPE[t]) / sigX; // PE 相对中枢的偏离（σ）
  for (const tr of traps) {
    let touched = 0; for (let t = tr.touchStart; t <= tr.touchEnd && t < N; t++) if (Math.abs(dev[t]) <= 0.2) touched++;
    tr.touchDays = touched;
    const s = tr.dir === 'up' ? 1 : -1; let ext = 0, extT = tr.end;
    for (let t = tr.end; t < Math.min(N, (tr.segEndPlan || tr.end) + 10); t++) if (s * dev[t] > ext) { ext = s * dev[t]; extT = t; }
    tr.contDev = ext; tr.contT = extT; tr.valid = touched > 0 && ext >= 1.0;
  }
  // 中枢跳变事件
  const jumps = [];
  for (const k of ['pe', 'roe', 'pay', 'y', 'vol']) for (const ev of sp.ev[k]) if (ev.kind === 'jump') jumps.push({ ind: k, start: ev.start, dur: ev.dur, pct: (ev.mult - 1) * 100 });
  const drifts = [];
  for (const k of ['pe', 'roe', 'pay', 'y', 'vol']) for (const ev of sp.ev[k]) if (ev.kind === 'slow') drifts.push({ ind: k, start: ev.start, dur: ev.dur, ratePct: (Math.pow(ev.mult, Y / ev.dur) - 1) * 100 });
  return { spec: sp, N, warm: sp.warm, close, high, low, nav, pe, pb, roe, dy, y: yld, cPE, cROE, cPay, cY, cVol, sig, beta, plan, lab, crises, traps, jumps, drifts, dev };
}

// ---------------------------------------------------------------- 指标
function sma(a, n) { const N = a.length, o = new Float64Array(N).fill(NaN); let s = 0; for (let i = 0; i < N; i++) { s += a[i]; if (i >= n) s -= a[i - n]; if (i >= n - 1) o[i] = s / n; } return o; }
function rsiWilder(c, n) {
  const N = c.length, o = new Float64Array(N).fill(NaN); let ag = 0, ad = 0;
  for (let i = 1; i < N; i++) {
    const g = Math.max(c[i] - c[i - 1], 0), d = Math.max(c[i - 1] - c[i], 0);
    if (i <= n) { ag += g / n; ad += d / n; if (i < n) continue; }
    else { ag = (ag * (n - 1) + g) / n; ad = (ad * (n - 1) + d) / n; }
    o[i] = ad === 0 ? 100 : 100 - 100 / (1 + ag / ad);
  }
  return o;
}
function ema(c, n) { const N = c.length, o = new Float64Array(N), k = 2 / (n + 1); o[0] = c[0]; for (let i = 1; i < N; i++) o[i] = o[i - 1] + k * (c[i] - o[i - 1]); return o; }
function atr(h, l, c, n) {
  const N = c.length, o = new Float64Array(N).fill(NaN); let s = 0;
  for (let i = 1; i < N; i++) {
    const tr = Math.max(h[i], c[i - 1]) - Math.min(l[i], c[i - 1]);
    if (i <= n) { s += tr / n; if (i === n) o[i] = s; continue; }
    o[i] = (o[i - 1] * (n - 1) + tr) / n;
  }
  return o;
}
// 滚动分位：Pct = 窗口 [t−W, t−1] 内 ≥ x_t 的样本占比 ×100；样本不足 3 年不计算
function rollingPct(x, W, startIdx) {
  const N = x.length, out = new Float64Array(N).fill(NaN);
  const buf = new Float64Array(W + 1); let len = 0;
  const lb = v => { let lo = 0, hi = len; while (lo < hi) { const m = (lo + hi) >> 1; if (buf[m] < v) lo = m + 1; else hi = m; } return lo; };
  for (let t = startIdx; t < N; t++) {
    if (len >= 3 * Y) out[t] = 100 * (len - lb(x[t])) / len;
    // 加入 x_t
    const pos = lb(x[t]); buf.copyWithin(pos + 1, pos, len); buf[pos] = x[t]; len++;
    // 移出 x_{t−W+1}... 下一步窗口为 [t+1−W, t]
    const oi = t + 1 - W - 1;
    if (oi >= startIdx) { const v = x[oi]; let p = lb(v); buf.copyWithin(p, p + 1, len); len--; }
  }
  return out;
}

const VWIN = [10, 5];
function computeInd(path) {
  const N = path.N, c = path.close;
  const ind = { N, path };
  // ROE_n：过去 5 年日均 ROE（[t−5y, t−1]）
  const roeN = new Float64Array(N).fill(NaN); { let s = 0; const W = 5 * Y; for (let t = 0; t < N; t++) { if (t >= W) roeN[t] = s / W; s += path.roe[t]; if (t >= W) s -= path.roe[t - W]; } }
  ind.roeN = roeN;
  const EY = new Float64Array(N), BP = new Float64Array(N), DY = new Float64Array(N), ERP = new Float64Array(N), IRP = new Float64Array(N), IRP2 = new Float64Array(N), G = new Float64Array(N);
  for (let t = 0; t < N; t++) {
    EY[t] = roeN[t] / path.pb[t]; BP[t] = 1 / path.pb[t]; DY[t] = path.dy[t]; ERP[t] = EY[t] - path.y[t];
    // 隐含风险溢价（戈登增长模型）：IRP = DY×(1+g) + g − y，g = ROE_n × (1 − 分红率)，分红率 = DY × PE
    const pay = clip(path.dy[t] * path.pe[t], 0, 1), g = clip(roeN[t] * (1 - pay), -0.05, 0.25);
    G[t] = g; IRP[t] = path.dy[t] * (1 + g) + g - path.y[t];
    IRP2[t] = path.dy[t] + g - path.y[t]; // V2.0 附录 B：IRP = DY + g − y
  }
  ind.raw = { EY, BP, DY, ERP, IRP, IRP2 };
  ind.growth = G;
  ind.start = { EY: 5 * Y, BP: 0, DY: 0, ERP: 5 * Y, IRP: 5 * Y, IRP2: 5 * Y };
  ind._pct = {};
  ind.ma = {};
  ind.atrD = atr(path.high, path.low, c, 10);
  ind.atrPct = new Float64Array(N); for (let t = 0; t < N; t++) ind.atrPct[t] = isNaN(ind.atrD[t]) ? 0.015 : ind.atrD[t] / c[t];
  // 周线
  const NW = Math.floor(N / 5);
  const wc = new Float64Array(NW), wh = new Float64Array(NW), wl = new Float64Array(NW);
  for (let w = 0; w < NW; w++) { let h = -Infinity, l = Infinity; for (let i = 5 * w; i < 5 * w + 5; i++) { if (path.high[i] > h) h = path.high[i]; if (path.low[i] < l) l = path.low[i]; } wc[w] = c[5 * w + 4]; wh[w] = h; wl[w] = l; }
  ind.week = { wc, wh, wl, NW };
  ind._cache = {};
  return ind;
}
function getPct(ind, k, W) {
  const key = k + W; if (!ind._pct[key]) ind._pct[key] = rollingPct(ind.raw[k], Math.round(W * Y), ind.start[k]); return ind._pct[key];
}
const VKEYS = ['EY', 'BP', 'DY', 'ERP'];
function getV(ind, wins, wts, keys) {
  wins = wins || VWIN; wts = wts || [1, 1, 1, 1]; keys = keys || VKEYS;
  const key = 'V' + wins.join(',') + '|' + wts.join(',') + '|' + keys.join(',');
  if (ind._cache[key]) return ind._cache[key];
  const N = ind.N, out = new Float64Array(N).fill(NaN), ks = keys;
  const arrs = ks.map(k => wins.map(W => getPct(ind, k, W)));
  const sw = wts.reduce((a, b) => a + b, 0);
  for (let t = 0; t < N; t++) {
    let v = 0, ok = true;
    for (let j = 0; j < 4; j++) { if (!wts[j]) continue; let s = 0; for (const a of arrs[j]) { if (isNaN(a[t])) { ok = false; break; } s += a[t]; } if (!ok) break; v += wts[j] * s / arrs[j].length; }
    out[t] = ok ? v / sw : NaN;
  }
  ind._cache[key] = out; return out;
}
function getMA(ind, n) { if (!ind.ma[n]) ind.ma[n] = sma(ind.path.close, n); return ind.ma[n]; }
function getU(ind, mas) {
  const key = 'U' + mas.join(','); if (ind._cache[key]) return ind._cache[key];
  const c = ind.path.close, N = ind.N, o = new Float64Array(N).fill(NaN), m = mas.map(n => getMA(ind, n));
  for (let t = 0; t < N; t++) { let s = 0, ok = true; for (const a of m) { if (isNaN(a[t])) { ok = false; break; } if (c[t] > a[t]) s++; } o[t] = ok ? s / mas.length : NaN; }
  ind._cache[key] = o; return o;
}
// 日线超卖 B
function getB(ind, n, os, kcm, emaN, atrN) {
  const key = ['B', n, os, kcm, emaN, atrN].join(','); if (ind._cache[key]) return ind._cache[key];
  const p = ind.path, c = p.close, r = rsiWilder(c, n), e = ema(c, emaN), a = atr(p.high, p.low, c, atrN);
  const o = new Uint8Array(ind.N); for (let t = 0; t < ind.N; t++) o[t] = (r[t] <= os || c[t] < e[t] - kcm * a[t]) ? 1 : 0;
  ind._cache[key] = o; ind._cache['RSId' + n] = r; return o;
}
// 周线冲高回落 S（按日展开：S[i] 为第 i 日收盘时已完成周口径）
function getS(ind, n, ob, kcm, win, emaN, atrN) {
  const key = ['S', n, ob, kcm, win, emaN, atrN].join(','); if (ind._cache[key]) return ind._cache[key];
  const { wc, wh, wl, NW } = ind.week;
  const r = rsiWilder(wc, n), e = ema(wc, emaN), a = atr(wh, wl, wc, atrN);
  const hot = new Uint8Array(NW); for (let w = 0; w < NW; w++) hot[w] = (r[w] >= ob || wc[w] > e[w] + kcm * a[w]) ? 1 : 0;
  const Sw = new Uint8Array(NW);
  for (let w = win; w < NW; w++) { if (hot[w]) continue; let any = 0; for (let j = w - win; j < w; j++) if (hot[j]) { any = 1; break; } Sw[w] = any; }
  const o = new Uint8Array(ind.N);
  for (let i = 0; i < ind.N; i++) { const w = (i % 5 === 4) ? Math.floor(i / 5) : Math.floor(i / 5) - 1; o[i] = w >= 0 ? Sw[w] : 0; }
  ind._cache[key] = o; ind._cache['HOT' + key] = hot; return o;
}
function getRSId(ind, n) { const k = 'RSId' + n; if (!ind._cache[k]) ind._cache[k] = rsiWilder(ind.path.close, n); return ind._cache[k]; }
function getROE5(ind) { return ind.roeN; }

// ---------------------------------------------------------------- 多周期预警（中枢上移）
const WARN_DEF = {
  sV: 70, sRsi: 55, mDays: 126, mVmean: 62, lRoe: 0.0, lY: -0.005, lPE: 0.12,
};
function getWarn(ind, Vser, wd) {
  wd = Object.assign({}, WARN_DEF, wd || {});
  const key = 'W' + JSON.stringify(wd); if (ind._cache[key]) return ind._cache[key];
  const N = ind.N, p = ind.path, c = p.close;
  const V = Vser, rsi = getRSId(ind, 14), ma20 = getMA(ind, 20), ma160 = getMA(ind, 160);
  const short = new Uint8Array(N), mid = new Uint8Array(N), long = new Uint8Array(N), lvl = new Uint8Array(N);
  const sub = { s1: new Float32Array(N), s2: new Float32Array(N), s3: new Float32Array(N), m1: new Float32Array(N), m2: new Float32Array(N), m3: new Float32Array(N), l1: new Float32Array(N), l2: new Float32Array(N), l3: new Float32Array(N) };
  // 63 日 RSI 均值、252 日 V≥70 天数、252 日 V 均值
  let rs = 0, rn = 0, vc = 0, vs = 0, vn = 0;
  const logpe = new Float64Array(N); for (let t = 0; t < N; t++) logpe[t] = Math.log(p.pe[t]);
  // 3 年滚动中位 PE 的近似：756 日均值
  const pe3 = sma(logpe, 756);
  for (let t = 0; t < N; t++) {
    if (!isNaN(rsi[t])) { rs += rsi[t]; rn++; } if (t >= 63 && !isNaN(rsi[t - 63])) { rs -= rsi[t - 63]; rn--; }
    const v = V[t], vok = !isNaN(v);
    if (vok) { vs += v; vn++; if (v >= wd.sV) vc++; }
    if (t >= 252 && !isNaN(V[t - 252])) { vs -= V[t - 252]; vn--; if (V[t - 252] >= wd.sV) vc--; }
    if (!vok || t < 800) continue;
    const s1 = v >= wd.sV ? 1 : 0, s2 = rn > 0 && rs / rn >= wd.sRsi ? 1 : 0, s3 = ma20[t] > ma20[t - 63] ? 1 : 0;
    const m1 = vc >= wd.mDays ? 1 : 0, m2 = ma160[t] > ma160[t - 63] ? 1 : 0, m3 = vn > 0 && vs / vn >= wd.mVmean ? 1 : 0;
    const dRoe = (ind.roeN[t] / ind.roeN[t - 756] - 1), dY = p.y[t] - p.y[t - 756], dPE = pe3[t] - pe3[t - 756];
    const l1 = dRoe >= wd.lRoe ? 1 : 0, l2 = dY <= wd.lY ? 1 : 0, l3 = dPE >= wd.lPE ? 1 : 0;
    sub.s1[t] = v; sub.s2[t] = rn > 0 ? rs / rn : 50; sub.s3[t] = (ma20[t] / ma20[t - 63] - 1);
    sub.m1[t] = vc; sub.m2[t] = (ma160[t] / ma160[t - 63] - 1); sub.m3[t] = vn > 0 ? vs / vn : 50;
    sub.l1[t] = isNaN(dRoe) ? 0 : dRoe; sub.l2[t] = dY; sub.l3[t] = isNaN(dPE) ? 0 : dPE;
    short[t] = (s1 + s2 + s3) >= 2 ? 1 : 0; mid[t] = (m1 + m2 + m3) >= 2 ? 1 : 0; long[t] = (l1 + l2 + l3) >= 2 ? 1 : 0;
    lvl[t] = short[t] + mid[t] + long[t];
  }
  const res = { short, mid, long, lvl, sub, def: wd };
  ind._cache[key] = res; return res;
}

// 中枢漂移真值：中枢相对过去 7.5 年均值向“贵”的方向移动的幅度（σ 单位）
function driftTruth(path) {
  const N = path.N, sx = path.spec.sigX, W = Math.round(7.5 * Y);
  const roeC5 = new Float64Array(N); { let s = 0; for (let t = 0; t < N; t++) { s += path.cROE[t]; if (t >= 5 * Y) s -= path.cROE[t - 5 * Y]; roeC5[t] = s / Math.min(t + 1, 5 * Y); } }
  const k4 = [new Float64Array(N), new Float64Array(N), new Float64Array(N), new Float64Array(N)];
  for (let t = 0; t < N; t++) {
    const pe = path.cPE[t], r = path.cROE[t], ey = roeC5[t] / (pe * r);
    k4[0][t] = Math.log(ey); k4[1][t] = Math.log(1 / (pe * r)); k4[2][t] = Math.log(path.cPay[t] / pe); k4[3][t] = (ey - path.cY[t]) / ey; // ERP 以 EY 归一
  }
  const means = k4.map(a => sma(a, W));
  const D = new Float64Array(N).fill(0);
  for (let t = W; t < N; t++) { let s = 0; for (let j = 0; j < 4; j++) s += (k4[j][t] - means[j][t]) / (j === 3 ? sx * 1.0 : sx); D[t] = -s / 4; }
  return D;
}
function driftEpisodes(D, thr, from, minLen) {
  const eps = []; let s = -1;
  for (let t = from; t < D.length; t++) {
    if (D[t] >= thr) { if (s < 0) s = t; }
    else if (s >= 0) { if (t - s >= minLen) eps.push({ start: s, end: t - 1 }); s = -1; }
  }
  if (s >= 0 && D.length - s >= minLen) eps.push({ start: s, end: D.length - 1 });
  // 合并间隔 < 63 日
  const m = []; for (const e of eps) { if (m.length && e.start - m[m.length - 1].end < 63) m[m.length - 1].end = e.end; else m.push(e); }
  return m;
}

// ---------------------------------------------------------------- 策略
const DEF = {
  name: '', sell: 'v16', buy: 'v16', review: 'none',
  floor: 0.2, thr: 0.05,
  sS0: 70, sS1: 80, upFloorV: 90, zoneB: 50,
  bSt0: 50, bSt1: 30, bDn0: 40, bDn1: 20,
  wA: 0.5, wC: 0, trailDD: 0.10,
  buyW: 0.5,
  ma: [40, 80, 160],
  rsiD: 14, rsiOS: 30, kcD: 2, emaD: 20, atrDn: 10,
  rsiW: 14, rsiOB: 70, kcW: 2, sWin: 4, emaW: 20, atrWn: 10,
  vWin: [10, 5], vW: [1, 1, 1, 1], vKeys: ['EY', 'BP', 'DY', 'ERP'],
  dcaBase: 300, dcaBoost: 700, dcaCap: 50000, dcaPow: 2.5, dcaV0: 70, dcaVb: 15,
  initCap: 200000, costMode: 'net',
  sub: 0.001, comm: 0.001, impK: 0.5,
  revA: 756, revB: 1.3, revPause: 20, revDays: 20, revCool: 252, revDeploy: 0.5, revJudge: 'proxy',
  warn: false, warnMax: 3, warnDef: null, w1Shift: 5, w1BuyHalf: true, w2Deploy: 0.5, w3Deploy: 1.0, w3Win: [5, 3], w2Pause: true,
  cashYield: 0, settle: 3, minHold: 21,
  start: null, end: null, record: true,
};
const COMBOS = [
  { id: 1, name: '组合1 V1.6', buy: 'v16', sell: 'v16', review: 'none', ver: 'V1.6原版' },
  { id: 2, name: '组合2 V1.7.1', buy: 'v16', sell: 'v17', review: 'proxy', ver: 'V1.7.1新组合' },
  { id: 3, name: '组合3 V1.8', buy: 'v16', sell: 'v18', review: 'proxy', ver: 'V1.8原版' },
  { id: 4, name: '组合4 V1.6.1', buy: 'v17', sell: 'v16', review: 'none', ver: 'V1.6.1新组合' },
  { id: 5, name: '组合5 V1.7', buy: 'v17', sell: 'v17', review: 'proxy', ver: 'V1.7原版' },
  { id: 6, name: '组合6 V1.9', buy: 'v17', sell: 'v18', review: 'proxy', ver: 'V1.9原版' },
];
function comboCfg(id, extra) { const c = COMBOS.find(x => x.id === id); return Object.assign({}, DEF, { name: c.name, buy: c.buy, sell: c.sell, review: c.review }, extra || {}); }

function redFee(age) { return age < 5 ? 0.015 : age < 21 ? 0.005 : age < 124 ? 0.0025 : 0; }

function runStrategy(path, ind, cfg) {
  if (cfg && cfg.mode === 'v20') return runV20(path, ind, cfg);
  const P = Object.assign({}, DEF, cfg);
  const N = path.N, nav = path.nav, close = path.close;
  const t0 = P.start != null ? P.start : path.warm, tEnd = P.end != null ? P.end : N;
  const Vn = getV(ind, P.vWin, P.vW, P.vKeys);
  const U = getU(ind, P.ma);
  const needB = P.buy !== 'v16', needS = P.sell !== 'v16';
  const Bs = needB ? getB(ind, P.rsiD, P.rsiOS, P.kcD, P.emaD, P.atrDn) : null;
  const Ss = needS ? getS(ind, P.rsiW, P.rsiOB, P.kcW, P.sWin, P.emaW, P.atrWn) : null;
  const ma160 = getMA(ind, 160);
  const roe5 = ind.roeN;
  const W = P.warn ? getWarn(ind, Vn, P.warnDef) : null;
  const Valt = P.warn ? getV(ind, P.w3Win, P.vW, P.vKeys) : null;
  const cm = P.costMode;
  const sub = cm === 'gross' ? 0 : P.sub, comm = cm === 'net' ? P.comm : 0, impK = cm === 'net' ? P.impK : 0, useRed = cm !== 'gross';
  const atrp = ind.atrPct;
  const f = P.floor;
  const BsF = (x, s0, s1) => f + (1 - f) * clip((s1 - x) / (s1 - s0), 0, 1);
  const tUp = (V, s0, s1, vf) => (1 + BsF(V, s0, s1)) / 2 - ((1 - f) / 2) * clip((V - s1) / (vf - s1), 0, 1);
  const Tb = (V, b0, b1) => f + (1 - f) * clip((b0 - V) / (b0 - b1), 0, 1);

  // 账户
  const lotU = [], lotD = []; let head = 0, units = 0;
  let cav = 0; const trA = [], trD = []; let trHead = 0, transit = 0;
  let pend = 0, E = 0, Vmax = NaN, a = 1, b = 1, cst = 1, ab = 0, bb = 0; // ab/bb：两段式回投累计目标
  let trailPk = 0;
  const cost = { sub: 0, comm: 0, imp: 0, red: 0 };
  // 初始持仓 100%
  { const u0 = P.initCap / nav[t0 - 1]; lotU.push(u0); lotD.push(t0 - 400); units = u0; }
  let inflow = P.initCap;
  const rec = P.record;
  const len = tEnd - t0;
  const Wt = new Float64Array(len), pS = new Float32Array(len), twr = new Float64Array(len), flowArr = new Float64Array(len), cashS = new Float32Array(len);
  const trades = [];
  let nSell = 0, nBuy = 0, nRev = 0, sellAmt = 0, buyAmt = 0, dcaAmt = 0, dcaN = 0, tpDays = 0;
  let idleDays = 0, sumP = 0;
  // 复核状态
  let roundOn = false, rT0 = -1, rSU = 0, rSV = 0, noTP = false, pauseTo = -1, judgeAt = -1, judgeTrig = '', coolA = -1, coolB = -1, yLowCnt = 0, revLog = [];
  let wPrevLvl = 0, w3On = false;
  let prevW = P.initCap, tw = 1;
  const yld = path.y;

  function buy(t, amt, kind, tag) {
    if (amt <= 0) return 0;
    const imp = impK * atrp[t], k = sub + comm + imp;
    const u = amt / (1 + k) / nav[t];
    const tc = amt - amt / (1 + k);
    if (k > 0) { cost.sub += tc * sub / k; cost.comm += tc * comm / k; cost.imp += tc * imp / k; }
    lotU.push(u); lotD.push(t); units += u;
    if (kind !== 'dca' && rec) trades.push({ t, k: kind, amt, px: close[t], nav: nav[t], tag });
    return u;
  }
  function sell(t, value, tag) {
    // 卖出份额 = 卖出市值 ÷ T−1 净值；FIFO；持有 < 30 天不卖
    let want = value / nav[t - 1], sold = 0, proceeds = 0;
    const imp = impK * atrp[t];
    while (want > 1e-9 && head < lotU.length) {
      const age = t - lotD[head];
      if (age < P.minHold) break;
      const q = Math.min(want, lotU[head]);
      const g = q * nav[t];
      const rf = useRed ? redFee(age) : 0;
      const fee = g * (rf + comm + imp);
      cost.red += g * rf; cost.comm += g * comm; cost.imp += g * imp;
      proceeds += g - fee; sold += q; want -= q; lotU[head] -= q;
      if (lotU[head] <= 1e-9) head++;
    }
    if (sold > 0) {
      units -= sold;
      trA.push(proceeds); trD.push(t + P.settle); transit += proceeds;
      if (rec) trades.push({ t, k: 'sell', amt: proceeds, px: close[t], nav: nav[t], tag });
    }
    return sold;
  }

  for (let t = t0; t < tEnd; t++) {
    const i = t - t0;
    // 在途款到账
    while (trHead < trA.length && trD[trHead] <= t) { cav += trA[trHead]; transit -= trA[trHead]; trHead++; }
    if (P.cashYield > 0) cav *= 1 + Math.max(0.005, yld[t - 1] - P.cashYield) / Y;
    const wl = W ? Math.min(W.lvl[t - 1], P.warnMax) : 0;
    if (W && wl >= 3) w3On = true; else if (W && wl === 0) w3On = false;
    const V = (W && w3On) ? Valt[t - 1] : Vn[t - 1];
    const u = U[t - 1];
    const up = u >= 2 / 3 - 1e-9, dn = u <= 1 / 3 + 1e-9;
    if (V < P.zoneB) { Vmax = V; a = 1; b = 1; cst = 1; if (roundOn) { roundOn = false; noTP = false; rSU = 0; rSV = 0; } }
    else { Vmax = isNaN(Vmax) ? V : Math.max(Vmax, V); E = 0; }
    if (V >= P.zoneB) { ab = 0; bb = 0; }
    const H = units * nav[t - 1], C = cav + transit, Wp = H + C, p = Wp > 0 ? H / Wp : 1;
    // 预警响应参数
    const sh = (W && wl >= 1) ? P.w1Shift : 0;
    const sS0 = P.sS0 + sh, sS1 = P.sS1 + sh, upV = P.upFloorV + sh;
    const bSt0 = P.bSt0 - sh, bSt1 = P.bSt1 - sh, bDn0 = P.bDn0 - sh, bDn1 = P.bDn1 - sh;
    const buyMul = (W && wl >= 1 && P.w1BuyHalf) ? 0.5 : 1;
    // 预警回补（一次性，在等级上升时）
    if (W && wl >= 2 && wPrevLvl < 2 && cav >= 10) { const amt = cav * (wl >= 3 ? P.w3Deploy : P.w2Deploy); cav -= amt; buy(t, amt, 'buy', 'W' + wl); nBuy++; buyAmt += amt; }
    else if (W && wl >= 3 && wPrevLvl === 2 && cav >= 10) { const amt = cav * P.w3Deploy; cav -= amt; buy(t, amt, 'buy', 'W3'); nBuy++; buyAmt += amt; }
    if (W) wPrevLvl = wl;
    // 复核结论
    if (judgeAt === t) {
      let shift = false;
      if (P.revJudge === 'proxy') {
        const s1 = (yld[t - 1] - yld[rT0] <= -0.005) && yLowCnt >= 252;
        const s3 = roe5[t - 1] >= roe5[rT0] * 1.05;
        shift = s1 || s3;
      }
      if (shift && roundOn) {
        const amt = cav * P.revDeploy; if (amt >= 10) { cav -= amt; buy(t, amt, 'buy', 'REV'); nBuy++; buyAmt += amt; }
        noTP = true; const H2 = units * nav[t - 1], p2 = H2 / (H2 + cav + transit); a = b = cst = p2;
      } else { if (judgeTrig === 'A') coolA = t + P.revCool; else coolB = t + P.revCool; }
      revLog.push({ t, trig: judgeTrig, shift }); judgeAt = -1;
    }
    let tp = false;
    const paused = (P.review !== 'none' && t <= pauseTo) || noTP || (W && wl >= 2 && P.w2Pause);
    // ---------------- 止盈
    if (!paused && Vmax > sS0 && V >= P.zoneB) {
      let T = NaN, trig = false, tag = '';
      const S = Ss ? Ss[t - 1] : 0;
      if (P.sell === 'v16') {
        if (dn) { T = BsF(Vmax, sS0, sS1); trig = true; tag = 'U↓'; }
        else if (up && V > sS0) { T = tUp(V, sS0, sS1, upV); trig = true; tag = 'U↑'; }
      } else if (P.sell === 'v17') {
        if (V > sS0 && S) { T = BsF(V, sS0, sS1); trig = true; tag = 'S'; }
      } else { // v18 / multi
        let tA = false, tB = false, tC = false;
        if (dn) { a = Math.min(a, BsF(Vmax, sS0, sS1)); tA = true; }
        else if (up && V > sS0) { a = Math.min(a, tUp(V, sS0, sS1, upV)); tA = true; }
        if (V > sS0 && S) { b = Math.min(b, BsF(V, sS0, sS1)); tB = true; }
        if (P.wC > 0) {
          trailPk = Math.max(trailPk, close[t - 1]);
          if (V > sS0 && close[t - 1] <= trailPk * (1 - P.trailDD)) { cst = Math.min(cst, BsF(Vmax, sS0, sS1)); tC = true; }
        }
        a = Math.max(a, f); b = Math.max(b, f); cst = Math.max(cst, f);
        if (tA || tB || tC) { const wB = 1 - P.wA - P.wC; T = P.wA * a + wB * b + P.wC * cst; trig = true; tag = (tA ? 'A' : '') + (tB ? 'B' : '') + (tC ? 'C' : ''); }
      }
      if (trig) { T = Math.max(T, f); if (p > T + P.thr) { const sold = sell(t, (p - T) * Wp, tag); if (sold > 0) { tp = true; nSell++; sellAmt += sold * nav[t]; if (!roundOn) { roundOn = true; rT0 = t; } rSU += sold; rSV += sold * nav[t]; } } }
    }
    if (V < P.zoneB) trailPk = 0;
    if (tp) tpDays++;
    // ---------------- 回投
    if (!tp && V < P.zoneB && cav >= 10) {
      let T = NaN, ok = false;
      const Bv = Bs ? Bs[t - 1] : 0;
      if (P.buy === 'v16') { T = up ? Tb(V, bSt0, bSt1) : Tb(V, bDn0, bDn1); ok = true; }
      else if (P.buy === 'v17') { if (Bv) { T = Tb(V, bSt0, bSt1); ok = true; } }
      else if (P.buy === 'hybrid') { if (Bv) { T = up ? Tb(V, bSt0, bSt1) : Tb(V, bDn0, bDn1); ok = true; } }
      else if (P.buy === 'split') { // 两段式回投：A 段按 V1.6、B 段按 V1.7，目标只升不降
        ab = Math.max(ab, up ? Tb(V, bSt0, bSt1) : Tb(V, bDn0, bDn1));
        if (Bv) bb = Math.max(bb, Tb(V, bSt0, bSt1));
        T = (1 - P.buyW) * ab + P.buyW * bb; ok = true;
      }
      if (ok && p < T - P.thr) {
        const amt = Math.min((T - p) * Wp * buyMul, cav);
        if (amt >= 10) { cav -= amt; buy(t, amt, 'buy', P.buy); nBuy++; buyAmt += amt; }
      }
    }
    // ---------------- 定投
    let flow = 0;
    if (!tp) {
      const x = clip((P.dcaV0 - V) / P.dcaV0, 0, 1), xp = Math.pow(x, P.dcaPow);
      const base = P.dcaBase * xp;
      let boost = P.dcaBoost * clip((P.dcaVb - V) / P.dcaVb, 0, 1) * xp;
      boost = Math.max(0, Math.min(boost, P.dcaCap - E)); E += boost;
      flow = base + boost; pend += flow;
      if (pend >= 10) { buy(t, pend, 'dca'); dcaAmt += pend; dcaN++; pend = 0; }
    }
    inflow += flow;
    // ---------------- 复核触发检查
    if (P.review !== 'none') {
      if (roundOn && yld[t - 1] <= yld[rT0] - 0.005) yLowCnt++; else yLowCnt = 0;
      if (roundOn && !noTP && judgeAt < 0 && t > pauseTo) {
        const Pbar = rSU > 0 ? rSV / rSU : Infinity;
        const A = t - rT0 >= P.revA && t > coolA;
        const Bt = nav[t - 1] >= P.revB * Pbar && close[t - 1] > ma160[t - 1] && t > coolB;
        if (A || Bt) { nRev++; pauseTo = t + P.revPause; judgeAt = t + (P.revJudge === 'proxy' ? P.revDays : P.revPause); judgeTrig = A ? 'A' : 'B'; revLog.push({ t, trig: judgeTrig, start: true }); }
      }
    }
    // ---------------- 收盘记账
    const Hc = units * nav[t], Wc = Hc + cav + transit + pend;
    const r = (Wc - flow) / prevW - 1; tw *= 1 + r; prevW = Wc;
    Wt[i] = Wc; pS[i] = Hc / (Hc + cav + transit); twr[i] = tw; flowArr[i] = flow; cashS[i] = cav + transit;
    sumP += pS[i]; if ((cav + transit) / Wc > 0.05) idleDays++;
  }
  return {
    cfg: P, t0, tEnd, W: Wt, p: pS, twr, flow: flowArr, cash: cashS, trades, cost, inflow,
    nSell, nBuy, nRev, sellAmt, buyAmt, dcaAmt, dcaN, tpDays, idle: idleDays / len, util: sumP / len, revLog,
  };
}


// ---------------------------------------------------------------- V2.0：每日净额 = 定投 + 平缓回投 − 平缓/果断卖出
const V20_DEF = {
  mode: 'v20', name: 'V2.0', vKeys: ['EY', 'BP', 'DY', 'IRP2'],
  floor: 0.2, zoneB: 50,
  rB0: 50, rB1: 20, rMax: 0.04, rPow: 2,        // 平缓回投：V 50→20，每天可用资金池 0→4%
  sS0: 65, sS1: 85, sMax: 0.04, sPow: 2,        // 平缓卖出：V 65→85，每天持仓 0→4%
  decisive: true, dS0: 65, dS1: 85, dThr: 0.05, // 果断卖出：U ≤ 1/3 且 V ≥ 50，目标 T_s = 1 − 0.8 × clip((V_max − 65)/20)
  minAmt: 10, review: 'proxy',
};
function runV20(path, ind, cfg) {
  const P = Object.assign({}, DEF, V20_DEF, cfg);
  const N = path.N, nav = path.nav, close = path.close;
  const t0 = P.start != null ? P.start : path.warm, tEnd = P.end != null ? P.end : N;
  const Vn = getV(ind, P.vWin, P.vW, P.vKeys);
  const U = getU(ind, P.ma);
  const ma160 = getMA(ind, 160);
  const roe5 = ind.roeN;
  const cm = P.costMode;
  const sub = cm === 'gross' ? 0 : P.sub, comm = cm === 'net' ? P.comm : 0, impK = cm === 'net' ? P.impK : 0, useRed = cm !== 'gross';
  const atrp = ind.atrPct, f = P.floor;
  const lotU = [], lotD = []; let head = 0, units = 0;
  let cav = 0; const trA = [], trD = []; let trHead = 0, transit = 0;
  let E = 0, Vmax = NaN;
  const cost = { sub: 0, comm: 0, imp: 0, red: 0 }, impD = new Float64Array(N);
  { const u0 = P.initCap / nav[t0 - 1]; lotU.push(u0); lotD.push(t0 - 400); units = u0; }
  let inflow = P.initCap;
  const rec = P.record, len = tEnd - t0;
  const Wt = new Float64Array(len), pS = new Float32Array(len), twr = new Float64Array(len), flowArr = new Float64Array(len), cashS = new Float32Array(len);
  const trades = [];
  let nSell = 0, nBuy = 0, nRev = 0, sellAmt = 0, buyAmt = 0, dcaAmt = 0, dcaN = 0, tpDays = 0, nDec = 0, decAmt = 0;
  let idleDays = 0, sumP = 0;
  let roundOn = false, rT0 = -1, rSU = 0, rSV = 0, noTP = false, pauseTo = -1, judgeAt = -1, judgeTrig = '', coolA = -1, coolB = -1, yLowCnt = 0;
  const revLog = [];
  let prevW = P.initCap, tw = 1;
  const yld = path.y;
  function buy(t, amt, kind, tag) {
    if (amt <= 0) return 0;
    const imp = impK * atrp[t], k = sub + comm + imp;
    const u = amt / (1 + k) / nav[t], tc = amt - amt / (1 + k);
    if (k > 0) { cost.sub += tc * sub / k; cost.comm += tc * comm / k; cost.imp += tc * imp / k; impD[t] += tc * imp / k; }
    lotU.push(u); lotD.push(t); units += u;
    if (rec && kind !== 'dca') trades.push({ t, k: kind, amt, px: close[t], nav: nav[t], tag });
    return u;
  }
  function sell(t, value, tag) {
    let want = value / nav[t - 1], sold = 0, proceeds = 0;
    const imp = impK * atrp[t];
    while (want > 1e-9 && head < lotU.length) {
      const age = t - lotD[head];
      if (age < P.minHold) break;
      const q = Math.min(want, lotU[head]), g = q * nav[t], rf = useRed ? redFee(age) : 0;
      cost.red += g * rf; cost.comm += g * comm; cost.imp += g * imp; impD[t] += g * imp;
      proceeds += g - g * (rf + comm + imp); sold += q; want -= q; lotU[head] -= q;
      if (lotU[head] <= 1e-9) head++;
    }
    if (sold > 0) {
      units -= sold; trA.push(proceeds); trD.push(t + P.settle); transit += proceeds;
      if (rec) trades.push({ t, k: 'sell', amt: proceeds, px: close[t], nav: nav[t], tag });
    }
    return sold;
  }
  for (let t = t0; t < tEnd; t++) {
    const i = t - t0;
    while (trHead < trA.length && trD[trHead] <= t) { cav += trA[trHead]; transit -= trA[trHead]; trHead++; }
    const V = Vn[t - 1], u = U[t - 1];
    if (V < P.zoneB) { Vmax = V; if (roundOn) { roundOn = false; noTP = false; rSU = 0; rSV = 0; } }
    else { Vmax = isNaN(Vmax) ? V : Math.max(Vmax, V); E = 0; }
    const H = units * nav[t - 1], C = cav + transit, Wp = H + C, p = Wp > 0 ? H / Wp : 1;
    // 复核结论（与 V1.7/V1.8 相同的代理判断）
    if (judgeAt === t) {
      let shift = false;
      if (P.revJudge === 'proxy') {
        const s1 = (yld[t - 1] - yld[rT0] <= -0.005) && yLowCnt >= 252, s3 = roe5[t - 1] >= roe5[rT0] * 1.05;
        shift = s1 || s3;
      }
      if (shift && roundOn) { const amt = cav * P.revDeploy; if (amt >= P.minAmt) { cav -= amt; buy(t, amt, 'buy', 'REV'); nBuy++; buyAmt += amt; } noTP = true; }
      else { if (judgeTrig === 'A') coolA = t + P.revCool; else coolB = t + P.revCool; }
      revLog.push({ t, trig: judgeTrig, shift }); judgeAt = -1;
    }
    const paused = (P.review !== 'none' && t <= pauseTo) || noTP;
    // 1. 定投 D
    const x = clip((P.dcaV0 - V) / P.dcaV0, 0, 1), xp = Math.pow(x, P.dcaPow);
    let boost = P.dcaBoost * clip((P.dcaVb - V) / P.dcaVb, 0, 1) * xp;
    boost = Math.max(0, Math.min(boost, P.dcaCap - E)); E += boost;
    const D = P.dcaBase * xp + boost;
    inflow += D;
    // 2. 平缓回投 R（只用已到账资金池）
    const R = cav * P.rMax * Math.pow(clip((P.rB0 - V) / (P.rB0 - P.rB1), 0, 1), P.rPow);
    // 3. 平缓卖出 S
    let S = paused ? 0 : H * P.sMax * Math.pow(clip((V - P.sS0) / (P.sS1 - P.sS0), 0, 1), P.sPow);
    // 4. 果断卖出
    let dec = false;
    if (!paused && P.decisive && u <= 1 / 3 + 1e-9 && V >= P.zoneB) {
      const Ts = 1 - (1 - f) * clip((Vmax - P.dS0) / (P.dS1 - P.dS0), 0, 1);
      if (p > Ts + P.dThr) { const Sd = (p - Ts) * Wp; if (Sd > S) { S = Sd; dec = true; } }
    }
    // 底仓：卖出后持仓占比不低于 20%
    S = Math.max(0, Math.min(S, H - f * (H + C + D)));
    const Nn = D + R - S;
    let tp = false;
    cav += D; // 当日定投款先进入可用资金
    if (Nn >= P.minAmt) {
      const amt = Math.min(Nn, cav); cav -= amt; buy(t, amt, R > 0 ? 'buy' : 'dca', R > 0 ? 'R' : 'D');
      dcaAmt += Math.min(D, amt); dcaN++; if (R > 0) { nBuy++; buyAmt += amt - Math.min(D, amt); }
    } else if (Nn <= -P.minAmt) {
      const sold = sell(t, -Nn, dec ? 'X' : 'S');
      if (sold > 0) {
        tp = true; nSell++; sellAmt += sold * nav[t]; if (dec) { nDec++; decAmt += sold * nav[t]; }
        if (!roundOn) { roundOn = true; rT0 = t; } rSU += sold; rSV += sold * nav[t];
      }
    }
    if (tp) tpDays++;
    // 复核触发检查
    if (P.review !== 'none') {
      if (roundOn && yld[t - 1] <= yld[rT0] - 0.005) yLowCnt++; else yLowCnt = 0;
      if (roundOn && !noTP && judgeAt < 0 && t > pauseTo) {
        const Pbar = rSU > 0 ? rSV / rSU : Infinity;
        const A = t - rT0 >= P.revA && t > coolA;
        const Bt = nav[t - 1] >= P.revB * Pbar && close[t - 1] > ma160[t - 1] && t > coolB;
        if (A || Bt) { nRev++; pauseTo = t + P.revPause; judgeAt = t + (P.revJudge === 'proxy' ? P.revDays : P.revPause); judgeTrig = A ? 'A' : 'B'; revLog.push({ t, trig: judgeTrig, start: true }); }
      }
    }
    const Hc = units * nav[t], Wc = Hc + cav + transit;
    const r = (Wc - D) / prevW - 1; tw *= 1 + r; prevW = Wc;
    Wt[i] = Wc; pS[i] = Hc / Wc; twr[i] = tw; flowArr[i] = D; cashS[i] = cav + transit;
    sumP += pS[i]; if ((cav + transit) / Wc > 0.05) idleDays++;
  }
  return {
    cfg: P, t0, tEnd, W: Wt, p: pS, twr, flow: flowArr, cash: cashS, trades, cost, inflow,
    nSell, nBuy, nRev, sellAmt, buyAmt, dcaAmt, dcaN, tpDays, idle: idleDays / len, util: sumP / len, revLog, nDec, decAmt, impD,
  };
}

// 基准：同现金流买入持有（初始全仓 + 公式定投每日买入，不卖出）；每月定额定投
function runBench(path, ind, cfg, kind) {
  const P = Object.assign({}, DEF, cfg);
  const N = path.N, nav = path.nav, t0 = P.start != null ? P.start : path.warm, tEnd = P.end != null ? P.end : N;
  const V = getV(ind, P.vWin, P.vW, P.vKeys);
  const cm = P.costMode, sub = cm === 'gross' ? 0 : P.sub, comm = cm === 'net' ? P.comm : 0, impK = cm === 'net' ? P.impK : 0;
  const len = tEnd - t0;
  // 先算公式定投总额（不跳过止盈日）
  const flows = new Float64Array(len); let E = 0, tot = 0;
  for (let t = t0; t < tEnd; t++) {
    const v = V[t - 1]; if (v >= 50) E = 0;
    const x = clip((P.dcaV0 - v) / P.dcaV0, 0, 1), xp = Math.pow(x, P.dcaPow);
    let boost = P.dcaBoost * clip((P.dcaVb - v) / P.dcaVb, 0, 1) * xp; boost = Math.max(0, Math.min(boost, P.dcaCap - E)); E += boost;
    flows[t - t0] = P.dcaBase * xp + boost; tot += flows[t - t0];
  }
  if (kind === 'monthly') { const m = tot / (len / 21); flows.fill(0); for (let i = 0; i < len; i += 21) flows[i] = m; }
  let units = P.initCap / nav[t0 - 1], prevW = P.initCap, tw = 1, inflow = P.initCap;
  const Wt = new Float64Array(len), twr = new Float64Array(len); let costT = 0;
  for (let t = t0; t < tEnd; t++) {
    const i = t - t0, fl = flows[i];
    if (fl > 0) { const k = sub + comm + impK * ind.atrPct[t]; units += fl / (1 + k) / nav[t]; costT += fl - fl / (1 + k); inflow += fl; }
    const Wc = units * nav[t]; tw *= 1 + (Wc - fl) / prevW - 1; prevW = Wc; Wt[i] = Wc; twr[i] = tw;
  }
  return { t0, tEnd, W: Wt, twr, flow: flows, inflow, cost: { total: costT }, p: null };
}

// ---------------------------------------------------------------- 绩效
function xirr(initCap, flows, finalW) {
  // 日度现金流：t=0 投入 initCap，第 i 日投入 flows[i]（视为当日），末日取回 finalW
  const n = flows.length;
  const f = r => { const d = Math.log(1 + r) / Y; let s = -initCap; for (let i = 0; i < n; i++) if (flows[i]) s -= flows[i] * Math.exp(-d * (i + 1)); s += finalW * Math.exp(-d * n); return s; };
  let lo = -0.5, hi = 1.0, flo = f(lo), fhi = f(hi);
  if (flo * fhi > 0) return NaN;
  for (let k = 0; k < 60; k++) { const m = (lo + hi) / 2, fm = f(m); if (fm * flo > 0) { lo = m; flo = fm; } else hi = m; if (hi - lo < 1e-7) break; }
  return (lo + hi) / 2;
}
function metrics(res, initCap) {
  const tw = res.twr, n = tw.length, yrs = n / Y;
  const fin = res.W[n - 1];
  const x = xirr(initCap, res.flow, fin);
  let pk = 1, mdd = 0, pkI = 0, ddStart = 0, ddTrough = 0, uw = 0, maxUw = 0;
  for (let i = 0; i < n; i++) {
    if (tw[i] >= pk) { pk = tw[i]; pkI = i; uw = 0; } else { uw++; if (uw > maxUw) maxUw = uw; }
    const dd = tw[i] / pk - 1; if (dd < mdd) { mdd = dd; ddStart = pkI; ddTrough = i; }
  }
  let rec = -1; for (let i = ddTrough; i < n; i++) if (tw[i] >= tw[ddStart]) { rec = i - ddTrough; break; }
  let s = 0, s2 = 0, dsum = 0; const rets = new Float64Array(n);
  for (let i = 0; i < n; i++) { const r = i === 0 ? tw[0] - 1 : tw[i] / tw[i - 1] - 1; rets[i] = r; s += r; s2 += r * r; if (r < 0) dsum += r * r; }
  const mu = s / n, sd = Math.sqrt(Math.max(0, s2 / n - mu * mu)), dsd = Math.sqrt(dsum / n);
  const cagr = Math.pow(tw[n - 1], 1 / yrs) - 1;
  const out = {
    final: fin, inflow: res.inflow, xirr: x, cagr, mdd, recDays: rec, maxUw,
    vol: sd * Math.sqrt(Y), dvol: dsd * Math.sqrt(Y),
    sharpe: sd > 0 ? (mu * Y) / (sd * Math.sqrt(Y)) : 0, sortino: dsd > 0 ? (mu * Y) / (dsd * Math.sqrt(Y)) : 0,
    calmar: mdd < 0 ? cagr / -mdd : 0,
  };
  if (res.cost && res.cost.sub !== undefined) {
    const c = res.cost, tot = c.sub + c.comm + c.imp + c.red;
    let avgW = 0; for (let i = 0; i < n; i++) avgW += res.W[i]; avgW /= n;
    Object.assign(out, {
      costTot: tot, costPct: tot / fin, costBpY: tot / avgW / yrs * 1e4, costSub: c.sub, costComm: c.comm, costImp: c.imp, costRed: c.red,
      turnover: (res.sellAmt + res.buyAmt) / avgW / yrs, nSell: res.nSell, nBuy: res.nBuy, nRev: res.nRev, tpDays: res.tpDays,
      idle: res.idle, util: res.util, dcaAmt: res.dcaAmt,
    });
  } else if (res.cost) { out.costTot = res.cost.total; }
  return out;
}
function monthlyRets(tw) { const o = []; for (let i = 21; i < tw.length; i += 21) o.push(tw[i] / tw[i - 21] - 1); return o; }

const API = { Y, clip, makeRng, SCENARIOS, SPLIT, BASE, scenarioSpec, customSpec, genPath, computeInd, getV, getU, getB, getS, getMA, getRSId, getWarn, WARN_DEF, driftTruth, driftEpisodes, DEF, COMBOS, comboCfg, runStrategy, runV20, V20_DEF, runBench, metrics, xirr, monthlyRets, rsiWilder, ema, atr, sma };
if (typeof module !== 'undefined' && module.exports) module.exports = API; else root.HS = API;
})(typeof self !== 'undefined' ? self : this);
