(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("data").textContent);
  var NS = "http://www.w3.org/2000/svg";
  var tip = document.getElementById("tip");
  var VERS = ["1.6", "1.7", "1.8", "1.9"];
  var VC = { "1.6": "var(--v16)", "1.7": "var(--v17)", "1.8": "var(--v18)", "1.9": "var(--v19)" };
  var BT0 = 2016, STEP = 10;

  function S(tag, a, p) {
    var e = document.createElementNS(NS, tag);
    for (var k in a) e.setAttribute(k, a[k]);
    if (p) p.appendChild(e);
    return e;
  }
  function pct(v, d) { return v == null ? "—" : (v * 100).toFixed(d == null ? 2 : d) + "%"; }
  function pp(v) { return v == null ? "—" : (v >= 0 ? "+" : "") + (v * 100).toFixed(2); }
  function niceTicks(a, b, n) {
    var span = b - a || 1, step = Math.pow(10, Math.floor(Math.log10(span / n))), err = span / n / step;
    if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    var t = [];
    for (var v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) t.push(+v.toFixed(10));
    return t;
  }
  function showTip(html, x, y) {
    tip.innerHTML = html; tip.hidden = false;
    var r = tip.getBoundingClientRect(), L = x + 14, T = y + 14;
    if (L + r.width > innerWidth - 8) L = x - r.width - 14;
    if (T + r.height > innerHeight - 8) T = y - r.height - 14;
    tip.style.left = Math.max(4, L) + "px"; tip.style.top = Math.max(4, T) + "px";
  }
  function hideTip() { tip.hidden = true; }
  function legend(host, series, sq) {
    if (series.length < 2) return 0;
    var l = document.createElement("div"); l.className = "lgd";
    series.forEach(function (s) {
      var sp = document.createElement("span"), i = document.createElement("i");
      if (sq) i.className = "sq";
      i.style.setProperty("--c", s.color);
      if (s.dash) i.style.background = "repeating-linear-gradient(90deg,var(--c) 0 5px,transparent 5px 8px)";
      sp.appendChild(i); sp.appendChild(document.createTextNode(s.name)); l.appendChild(sp);
    });
    host.appendChild(l);
    return l.offsetHeight + 6;
  }
  function rowsTip(head, items) {
    return '<div class="th">' + head + "</div>" + items.map(function (it) {
      return '<div class="tr"><span><i style="--c:' + it.c + '"></i>' + it.n + "</span><b>" + it.v + "</b></div>";
    }).join("");
  }

  // ---------------- 折线图 ----------------
  function line(host, cfg) {
    host.innerHTML = "";
    var lh = legend(host, cfg.series);
    var W = host.clientWidth, H = host.clientHeight - lh;
    if (W < 50 || H < 50) return;
    var m = { l: cfg.ml || 46, r: 12, t: 8, b: 22 };
    var svg = S("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, "class": "svg", role: "img", "aria-label": cfg.aria || "" }, host);
    var n = cfg.x.length, ys = [];
    cfg.series.forEach(function (s) { s.data.forEach(function (v) { if (v != null && isFinite(v)) ys.push(v); }); });
    var lo = cfg.yMin != null ? cfg.yMin : Math.min.apply(null, ys), hi = cfg.yMax != null ? cfg.yMax : Math.max.apply(null, ys);
    var tf = cfg.log ? function (v) { return Math.log10(v); } : function (v) { return v; };
    var a = tf(lo), b = tf(hi), pad = (b - a) * 0.06 || 1;
    if (cfg.yMin == null) a -= pad;
    if (cfg.yMax == null) b += pad;
    var X = function (i) { return m.l + (W - m.l - m.r) * (n === 1 ? 0.5 : i / (n - 1)); };
    var Y = function (v) { return m.t + (H - m.t - m.b) * (1 - (tf(v) - a) / (b - a)); };
    var tv;
    if (cfg.log) {
      tv = [];
      for (var e = Math.floor(a); e <= Math.ceil(b); e++) [1, 2, 5].forEach(function (k) { var v = k * Math.pow(10, e); if (tf(v) >= a && tf(v) <= b) tv.push(v); });
    } else tv = niceTicks(a, b, cfg.ticks || 4);
    var fmt = cfg.yfmt || function (v) { return v; };
    tv.forEach(function (v) {
      var y = Y(v);
      S("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, "class": "gl" }, svg);
      S("text", { x: m.l - 6, y: y + 3.5, "text-anchor": "end" }, svg).textContent = fmt(v);
    });
    (cfg.shade || []).forEach(function (s) {
      S("rect", { x: X(s.i0), y: m.t, width: Math.max(0, X(s.i1) - X(s.i0)), height: H - m.t - m.b, fill: "var(--rule2)" }, svg);
      if (s.label) S("text", { x: X(s.i0) + 4, y: m.t + 11 }, svg).textContent = s.label;
    });
    // x 轴刻度
    var xt = [];
    if (cfg.xcat) xt = cfg.x.map(function (_, i) { return i; });
    else {
      var yrs = [], last = null;
      cfg.x.forEach(function (d, i) { var y = d.slice(0, 4); if (y !== last) { yrs.push(i); last = y; } });
      var every = Math.ceil(yrs.length / Math.max(2, Math.floor((W - m.l) / 62)));
      xt = yrs.filter(function (_, k) { return k % every === 0; });
    }
    S("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, "class": "ax" }, svg);
    xt.forEach(function (i) {
      S("text", { x: X(i), y: H - m.b + 15, "text-anchor": cfg.xcat ? "middle" : "start" }, svg).textContent = cfg.xcat ? cfg.x[i] : cfg.x[i].slice(0, 4);
    });
    (cfg.refs || []).forEach(function (r) {
      var y = Y(r.y);
      S("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: "var(--muted)", "stroke-dasharray": "3 3", "stroke-width": 1 }, svg);
      if (r.label) S("text", { x: m.l + 4, y: y - 4, "text-anchor": "start" }, svg).textContent = r.label;
    });
    (cfg.vlines || []).forEach(function (v) {
      var x = X(v.i);
      S("line", { x1: x, x2: x, y1: m.t, y2: H - m.b, stroke: "var(--muted)", "stroke-width": 1, opacity: 0.55 }, svg);
      if (v.label) S("text", { x: x + 3, y: m.t + 10 }, svg).textContent = v.label;
    });
    cfg.series.forEach(function (s) {
      var d = "", pen = false;
      s.data.forEach(function (v, i) {
        if (v == null || !isFinite(v)) { pen = false; return; }
        d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true;
      });
      S("path", { d: d, fill: "none", stroke: s.color, "stroke-width": s.width || 2, "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": s.dash || "" }, svg);
      if (cfg.xcat) s.data.forEach(function (v, i) { if (v != null) S("circle", { cx: X(i), cy: Y(v), r: 3.5, fill: s.color, stroke: "var(--surface)", "stroke-width": 1.5 }, svg); });
    });
    (cfg.points || []).forEach(function (p) {
      if (p.y == null) return;
      S("circle", { cx: X(p.i), cy: Y(p.y), r: 4, fill: p.color, stroke: "var(--surface)", "stroke-width": 1.5 }, svg);
    });
    // 悬停：十字线 + 提示
    var cross = S("line", { y1: m.t, y2: H - m.b, stroke: "var(--ink2)", "stroke-width": 1, opacity: 0 }, svg);
    var dots = cfg.series.map(function (s) { return S("circle", { r: 4, fill: s.color, stroke: "var(--surface)", "stroke-width": 2, opacity: 0 }, svg); });
    var hit = S("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
    function move(ev) {
      var r = svg.getBoundingClientRect(), px = ev.clientX - r.left;
      var i = Math.round((px - m.l) / (W - m.l - m.r) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      var x = X(i);
      cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("opacity", 0.5);
      var items = [];
      cfg.series.forEach(function (s, k) {
        var v = s.data[i];
        if (v == null || !isFinite(v)) { dots[k].setAttribute("opacity", 0); return; }
        dots[k].setAttribute("cx", x); dots[k].setAttribute("cy", Y(v)); dots[k].setAttribute("opacity", 1);
        items.push({ n: s.name, c: s.color, v: (cfg.tfmt || fmt)(v) });
      });
      var extra = cfg.tipExtra ? cfg.tipExtra(i) : "";
      showTip(rowsTip(cfg.xcat ? cfg.x[i] : cfg.x[i], items) + extra, ev.clientX, ev.clientY);
    }
    function leave() { cross.setAttribute("opacity", 0); dots.forEach(function (d) { d.setAttribute("opacity", 0); }); hideTip(); }
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", leave);
  }

  // ---------------- 分组柱状图 ----------------
  function bars(host, cfg) {
    host.innerHTML = "";
    var lh = legend(host, cfg.series, true);
    var W = host.clientWidth, H = host.clientHeight - lh;
    if (W < 50 || H < 50) return;
    var m = { l: 46, r: 8, t: 14, b: 34 };
    var svg = S("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, "class": "svg", role: "img", "aria-label": cfg.aria || "" }, host);
    var vals = [];
    cfg.series.forEach(function (s) { s.data.forEach(function (v) { if (v != null) vals.push(v); }); });
    var lo = Math.min(0, Math.min.apply(null, vals)), hi = Math.max(0, Math.max.apply(null, vals));
    var pad = (hi - lo) * 0.1; if (lo < 0) lo -= pad; hi += pad;
    var Y = function (v) { return m.t + (H - m.t - m.b) * (1 - (v - lo) / (hi - lo)); };
    var fmt = cfg.yfmt || function (v) { return v; };
    niceTicks(lo, hi, 4).forEach(function (v) {
      var y = Y(v);
      S("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, "class": "gl" }, svg);
      S("text", { x: m.l - 6, y: y + 3.5, "text-anchor": "end" }, svg).textContent = fmt(v);
    });
    var nc = cfg.cats.length, ns = cfg.series.length, cw = (W - m.l - m.r) / nc;
    var gw = Math.min(cw * 0.78, ns * 34), bw = (gw - (ns - 1) * 2) / ns;
    var y0 = Y(0);
    S("line", { x1: m.l, x2: W - m.r, y1: y0, y2: y0, stroke: "var(--muted)", "stroke-width": 1 }, svg);
    var showLab = nc * ns <= 14 && bw >= 24;
    cfg.cats.forEach(function (c, ci) {
      var gx = m.l + cw * ci + (cw - gw) / 2;
      var words = String(c);
      var tx = S("text", { x: m.l + cw * ci + cw / 2, y: H - m.b + 15, "text-anchor": "middle" }, svg);
      tx.textContent = words.length * 11 > cw && words.indexOf("·") > 0 ? words.split("·")[0] : words;
      if (words.length * 11 > cw && words.indexOf("·") > 0) S("text", { x: m.l + cw * ci + cw / 2, y: H - m.b + 28, "text-anchor": "middle" }, svg).textContent = words.split("·")[1];
      cfg.series.forEach(function (s, si) {
        var v = s.data[ci]; if (v == null) return;
        var x = gx + si * (bw + 2), y1 = Y(v), r = Math.min(3, bw / 2, Math.abs(y1 - y0));
        var up = v >= 0, top = up ? y1 : y0, bot = up ? y0 : y1, d;
        if (up) d = "M" + x + " " + bot + "V" + (top + r) + "Q" + x + " " + top + " " + (x + r) + " " + top + "H" + (x + bw - r) + "Q" + (x + bw) + " " + top + " " + (x + bw) + " " + (top + r) + "V" + bot + "Z";
        else d = "M" + x + " " + top + "V" + (bot - r) + "Q" + x + " " + bot + " " + (x + r) + " " + bot + "H" + (x + bw - r) + "Q" + (x + bw) + " " + bot + " " + (x + bw) + " " + (bot - r) + "V" + top + "Z";
        var p = S("path", { d: d, fill: s.color }, svg);
        if (showLab) S("text", { x: x + bw / 2, y: up ? y1 - 4 : y1 + 12, "text-anchor": "middle", style: "fill:var(--ink2)" }, svg).textContent = (cfg.lfmt || fmt)(v);
        var hitr = S("rect", { x: x - 1, y: m.t, width: bw + 2, height: H - m.t - m.b, fill: "transparent" }, svg);
        var on = function (ev) { p.setAttribute("opacity", 0.8); showTip(rowsTip(c, cfg.series.map(function (ss) { return { n: ss.name, c: ss.color, v: (cfg.tfmt || fmt)(ss.data[ci]) }; })), ev.clientX, ev.clientY); };
        hitr.addEventListener("pointermove", on);
        hitr.addEventListener("pointerdown", on);
        hitr.addEventListener("pointerleave", function () { p.setAttribute("opacity", 1); hideTip(); });
      });
    });
  }

  // ---------------- 各图配置 ----------------
  var renders = [];
  function reg(id, fn) { var el = document.getElementById(id); if (!el) return; renders.push([el, fn]); fn(el); }

  var cur = 10;
  function explorer() {
    var s = D.series[cur], ov = D.ov.filter(function (o) { return o.no === cur; })[0];
    var vl = ov.events.map(function (e) { return { i: Math.round(e.peak / STEP), label: e.type === "bubble" ? "泡沫" : "危机" }; });
    var pts = ov.traps.map(function (t) {
      var i = Math.round(t.ts / STEP);
      return { i: i, y: s.pe[i], color: t.dir > 0 ? "var(--pos)" : "var(--neg)" };
    });
    var pre = [{ i0: 0, i1: Math.round(BT0 / STEP), label: "预热期" }];
    var n = s.date.length;
    var tipDate = function (i) { return ""; };
    function draw() {
      line(document.getElementById("c_pe"), {
        x: s.date, series: [{ name: "PE(TTM)", color: "var(--accent)", data: s.pe, width: 1.6 }, { name: "估值中枢", color: "var(--muted)", data: s.center, dash: "5 4", width: 1.6 }],
        vlines: vl, points: pts, shade: pre, yfmt: function (v) { return v.toFixed(0); }, tfmt: function (v) { return v.toFixed(1); }, aria: "PE 与估值中枢"
      });
      line(document.getElementById("c_v"), {
        x: s.date, series: [{ name: "V", color: "var(--accent)", data: s.V, width: 1.4 }], yMin: 0, yMax: 100, shade: pre,
        refs: [{ y: 70, label: "70 止盈区" }, { y: 50, label: "50 回投区" }], yfmt: function (v) { return v.toFixed(0); }, aria: "估值分 V"
      });
      var bvl = vl.map(function (v) { return { i: v.i - Math.round(BT0 / STEP), label: v.label }; }).filter(function (v) { return v.i >= 0; });
      line(document.getElementById("c_nav"), {
        x: s.bt_date, log: true,
        series: VERS.map(function (v) { return { name: "V" + v, color: VC[v], data: s["twr_" + v] }; }).concat([{ name: "买入持有", color: "var(--bh)", data: s.nav, dash: "5 4" }]),
        vlines: bvl, yfmt: function (v) { return v >= 1 ? v.toFixed(0) + "×" : v.toFixed(1) + "×"; }, tfmt: function (v) { return v.toFixed(2) + "×"; }, aria: "净值"
      });
      line(document.getElementById("c_p"), {
        x: s.bt_date, yMin: 0, yMax: 1,
        series: VERS.map(function (v) { return { name: "V" + v, color: VC[v], data: s["p_" + v], width: 1.4 }; }),
        yfmt: function (v) { return (v * 100).toFixed(0) + "%"; }, aria: "持仓占比"
      });
    }
    draw();
  }
  var sel = document.getElementById("pathsel");
  D.ov.forEach(function (o) {
    var b = document.createElement("button");
    b.type = "button"; b.id = "path-" + o.no; b.textContent = o.no + " " + o.name.replace("（样本外）", "");
    b.setAttribute("aria-pressed", o.no === cur ? "true" : "false");
    b.addEventListener("click", function () {
      cur = o.no;
      sel.querySelectorAll("button").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      explorer();
    });
    sel.appendChild(b);
  });
  explorer();
  ["c_pe", "c_v", "c_nav", "c_p"].forEach(function (id) { renders.push([document.getElementById(id), function () { explorer(); }]); });

  var pfmt = function (v) { return (v * 100).toFixed(0) + "%"; };
  var pfmt1 = function (v) { return (v * 100).toFixed(1) + "%"; };
  var pfmt2 = function (v) { return (v * 100).toFixed(2) + "%"; };
  var ppf = function (v) { return pp(v); };

  reg("c_xirr", function (el) {
    var b = D.bars_overall;
    bars(el, { cats: b.cats, series: [{ name: "毛（不计成本）", color: "var(--m3)", data: b.gross }, { name: "净（全口径成本）", color: "var(--m1)", data: b.net }],
      yfmt: pfmt, lfmt: function (v) { return (v * 100).toFixed(1); }, tfmt: pfmt2, aria: "毛与净 XIRR" });
  });
  reg("c_mdd", function (el) {
    var b = D.mdd;
    bars(el, { cats: b.cats, series: [{ name: "10 条主路径", color: "var(--m1)", data: b.main }, { name: "300 条蒙特卡洛", color: "var(--m3)", data: b.mc }],
      yfmt: pfmt, lfmt: pfmt, tfmt: pfmt1, aria: "最大回撤" });
  });
  reg("c_quad", function (el) {
    var q = D.quad;
    bars(el, { cats: q.cats, series: VERS.map(function (v) { return { name: "V" + v, color: VC[v], data: q[v] }; }),
      yfmt: function (v) { return (v >= 0 ? "+" : "") + (v * 100).toFixed(0); }, tfmt: function (v) { return pp(v) + " pp"; }, aria: "四象限超额" });
  });
  reg("c_trap", function (el) {
    var t = D.trap;
    bars(el, { cats: t.cats, series: VERS.map(function (v) { return { name: "V" + v, color: VC[v], data: t[v] }; }), yfmt: pfmt, lfmt: pfmt, tfmt: pfmt1, aria: "陷阱触发概率" });
  });
  reg("c_oat", function (el) {
    el.innerHTML = "";
    var g = document.createElement("div"); g.className = "oatg"; el.appendChild(g);
    var names = { SL: "止盈估值线", RB: "回投估值线", TH: "交易阈值", FL: "底仓比例" };
    var all = [];
    ["SL", "RB", "TH", "FL"].forEach(function (k) { VERS.forEach(function (v) { all = all.concat(D.oat[k][v]); }); });
    var lo = Math.min.apply(null, all) - 0.001, hi = Math.max.apply(null, all) + 0.001;
    ["SL", "FL", "RB", "TH"].forEach(function (k, idx) {
      var box = document.createElement("div");
      var t = document.createElement("div"); t.className = "oatt"; t.textContent = names[k];
      var c = document.createElement("div"); c.style.height = "calc(100% - 22px)"; c.style.position = "relative";
      box.appendChild(t); box.appendChild(c); g.appendChild(box);
      var o = D.oat[k];
      var labs = o.levels.map(function (x) { return (k === "TH" || k === "FL") ? (x * 100).toFixed(0) + "%" : String(x); });
      line(c, { x: labs, xcat: true, yMin: lo, yMax: hi, ml: idx === 0 || (el.clientWidth < 700 && idx === 2) ? 46 : 14,
        series: VERS.map(function (v) { return { name: "V" + v, color: VC[v], data: o[v] }; }).map(function (s) { return s; }),
        yfmt: function (v) { return idx === 0 || (el.clientWidth < 700 && idx === 2) ? (v * 100).toFixed(1) + "%" : ""; }, tfmt: pfmt2, ticks: 4, aria: names[k] });
      var lg = c.querySelector(".lgd"); if (lg && idx !== 0) { lg.style.visibility = "hidden"; }
    });
  });
  reg("c_mcw", function (el) {
    var w = D.mcw;
    bars(el, { cats: w.cats, series: [{ name: "准确率", color: "var(--m1)", data: w.prec }, { name: "假阳性率", color: "var(--m2)", data: w.fpr }, { name: "漏警率", color: "var(--m3)", data: w.miss }],
      yfmt: pfmt, tfmt: pfmt1, aria: "预警准确率对比" });
  });
  reg("c_resp", function (el) {
    var r = D.resp;
    bars(el, { cats: r.cats, series: [{ name: "全部场景", color: "var(--m1)", data: r.all }, { name: "仅缓慢上移场景", color: "var(--m2)", data: r.slow }],
      yfmt: function (v) { return (v >= 0 ? "+" : "") + (v * 100).toFixed(1); }, lfmt: function (v) { return pp(v); }, tfmt: function (v) { return pp(v) + " pp"; }, aria: "预警应对效果" });
  });

  // ---------------- 第 10 节：中枢漂移专项 ----------------
  var DD = D.drift, curS = "C1";
  function scenDraw() {
    var sc = DD.scen.filter(function (x) { return x.key === curS; })[0], s = sc.series;
    if (!s) return;
    var r = function (a) { var b = a[0]; return a.map(function (v) { return v / b; }); };
    var shade = [{ i0: 0, i1: Math.round(2016 / 20), label: "预热期" }];
    line(document.getElementById("c_dc1"), {
      x: s.date, shade: shade,
      series: [{ name: "PE 中枢", color: "var(--m1)", data: r(s.pe_c) }, { name: "PB 中枢", color: "var(--m2)", data: r(s.pb_c) }, { name: "股息率中枢", color: "var(--neg)", data: r(s.dy_c), dash: "5 4" }],
      yfmt: function (v) { return v.toFixed(2); }, aria: "估值指标中枢"
    });
    line(document.getElementById("c_dc2"), {
      x: s.date, shade: shade,
      series: [{ name: "10 年国债", color: "var(--m3)", data: s.y_c }, { name: "股债利差", color: "var(--m1)", data: s.erp_c }],
      yfmt: function (v) { return v.toFixed(1) + "%"; }, tfmt: function (v) { return v.toFixed(2) + "%"; }, aria: "利率与股债利差"
    });
    line(document.getElementById("c_dc3"), {
      x: s.date, yMin: 0, yMax: 100, shade: shade, refs: [{ y: 70, label: "70" }, { y: 50, label: "50" }],
      series: [{ name: "原版 V（4 项）", color: "var(--m1)", data: s.V_orig }, { name: "去掉 PB", color: "var(--m2)", data: s.V_nopb, width: 1.6 }, { name: "只用盈利收益率", color: "var(--m3)", data: s.V_ey, width: 1.6, dash: "5 4" }],
      yfmt: function (v) { return v.toFixed(0); }, tfmt: function (v) { return v.toFixed(1); }, aria: "估值分 V"
    });
  }
  var ssel = document.getElementById("scensel");
  if (ssel) {
    DD.scen.forEach(function (x) {
      var b = document.createElement("button");
      b.type = "button"; b.id = "scen-" + x.key; b.textContent = x.key + " " + x.name.replace(/（.*?）/g, "");
      b.setAttribute("aria-pressed", x.key === curS ? "true" : "false");
      b.addEventListener("click", function () {
        curS = x.key;
        ssel.querySelectorAll("button").forEach(function (y) { y.setAttribute("aria-pressed", y === b ? "true" : "false"); });
        scenDraw();
      });
      ssel.appendChild(b);
    });
    scenDraw();
    ["c_dc1", "c_dc2", "c_dc3"].forEach(function (id) { renders.push([document.getElementById(id), function () { scenDraw(); }]); });
  }
  reg("c_me", function (el) {
    el.innerHTML = "";
    var g = document.createElement("div"); g.className = "oatg"; el.appendChild(g);
    var names = { pe: "PE 中枢（%）", roe: "ROE（pp）", p: "分红率（pp）", y: "10 年国债（pp）" };
    var labs = { pe: ["−18", "0", "+18"], roe: ["−3", "0", "+3"], p: ["−8", "0", "+12"], y: ["−1.5", "0", "+1.5"] };
    var all = [];
    ["pe", "roe", "p", "y"].forEach(function (k) { VERS.forEach(function (v) { all = all.concat(DD.me[k][v]); }); });
    var lo = Math.min.apply(null, all) - 0.001, hi = Math.max.apply(null, all) + 0.001;
    ["pe", "roe", "p", "y"].forEach(function (k, idx) {
      var box = document.createElement("div");
      var t = document.createElement("div"); t.className = "oatt"; t.textContent = names[k];
      var c = document.createElement("div"); c.style.height = "calc(100% - 22px)"; c.style.position = "relative";
      box.appendChild(t); box.appendChild(c); g.appendChild(box);
      var showY = idx === 0 || (el.clientWidth < 700 && idx === 2);
      line(c, { x: labs[k], xcat: true, yMin: lo, yMax: hi, ml: showY ? 46 : 14,
        series: VERS.map(function (v) { return { name: "V" + v, color: VC[v], data: DD.me[k][v] }; }),
        yfmt: function (v) { return showY ? (v >= 0 ? "+" : "") + (v * 100).toFixed(1) : ""; }, tfmt: function (v) { return pp(v) + " pp"; }, ticks: 4, aria: names[k] });
      var lg = c.querySelector(".lgd"); if (lg && idx !== 0) lg.style.visibility = "hidden";
    });
  });

  var tmr = null;
  if (window.ResizeObserver) {
    var lastW = document.body.clientWidth;
    new ResizeObserver(function () {
      if (Math.abs(document.body.clientWidth - lastW) < 2) return;
      lastW = document.body.clientWidth;
      clearTimeout(tmr);
      tmr = setTimeout(function () { var done = {}; renders.forEach(function (r) { if (r[0].id.indexOf("c_") === 0 && ["c_pe", "c_v", "c_nav", "c_p"].indexOf(r[0].id) >= 0) { if (done.ex) return; done.ex = 1; } r[1](r[0]); }); }, 120);
    }).observe(document.body);
  }
})();
