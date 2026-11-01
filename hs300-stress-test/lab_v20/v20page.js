
// ================================================================ 5c V2.0 每日净额策略
A.register('v20', function () {
  const X = RES.v20, Vv = X.variants, G2 = k => (Vv[k] || RES.aggAll[k]);
  const rank = ALLK.slice().sort((a, b) => RES.score[b] - RES.score[a]);
  const topOther = rank.filter(k => k !== 'V2')[0];
  const others = ALLK.filter(k => k !== 'V2');
  const bestOf = (q, dir) => others.reduce((a, b) => dir * (G[b][q].mean - G[a][q].mean) > 0 ? b : a);
  const bx = bestOf('xirr', 1), bs = bestOf('sharpe', 1), bc = bestOf('calmar', 1), bm = bestOf('mdd', 1);
  const v = G2('V2'), vs = G2('V2s'), ve = G2('V2e');
  const types = HS.SCENARIOS.map(s => s.id);
  const wins = types.filter(t => others.every(k => RES.byType[t].V2.exBH >= RES.byType[t][k].exBH)).length;
  const beatOrig = types.filter(t => ORIG.every(k => RES.byType[t].V2.exBH > RES.byType[t][k].exBH)).length;
  const C = RES.stress.crisis, TP = X.trapPer;
  const envRk = e => ALLK.slice().sort((a, b) => RES.env[b][e] - RES.env[a][e]).indexOf('V2') + 1;
  if (once('#p-v20 .body', `
  <div class="callout"><b>V2.0 是什么：</b>不再按目标仓位一次买卖到位，而是每天把“定投 D + 平缓回投 R − 平缓卖出 S”相加，只按净额成交；三条均线中至少两条跌破时，按本轮最高估值 V<sub>max</sub> 一次卖到目标仓位（果断卖出）。只用估值分 V 和 MA40/80/160，不再使用周线 RSI、KC 通道和日线超卖信号。V 的第四项用隐含风险溢价 IRP = DY + g − y 替代股债利差。</div>
  <div class="kpis">
    <div class="kpi"><div class="l">年化 XIRR（净，90 条路径均值）</div><div class="v">${fP(v.xirr.mean, 2)}</div><div class="d">其他 10 套最高 ${shortOf(bx)} ${fP(G[bx].xirr.mean, 2)}</div></div>
    <div class="kpi"><div class="l">相对同现金流买入持有</div><div class="v">${pp(v.exBH.mean)}</div><div class="d">原 6 组 ${fS(Math.min(...ORIG.map(k => G[k].exBH.mean)))}～${fS(Math.max(...ORIG.map(k => G[k].exBH.mean)))}</div></div>
    <div class="kpi"><div class="l">最大回撤（均值）</div><div class="v">${fP(v.mdd.mean, 1)}</div><div class="d">最浅 ${shortOf(bm)} ${fP(G[bm].mdd.mean, 1)} · 买入持有 ${fP(G.BH.mdd.mean, 1)}</div></div>
    <div class="kpi"><div class="l">夏普 / 卡玛</div><div class="v">${fN(v.sharpe.mean, 3)} / ${fN(v.calmar.mean, 3)}</div><div class="d">其他最高 ${fN(G[bs].sharpe.mean, 3)}（${shortOf(bs)}）/ ${fN(G[bc].calmar.mean, 3)}（${shortOf(bc)}）</div></div>
    <div class="kpi"><div class="l">综合分</div><div class="v">${RES.score.V2}</div><div class="d">第 ${rank.indexOf('V2') + 1} / ${ALLK.length} · 次高 ${shortOf(topOther)} ${RES.score[topOther]}</div></div>
  </div>
  <div class="card"><h3>核心结论</h3><ol class="findings">
    <li><b>风险调整后收益是全部 11 套方案中最好的。</b>夏普 ${fN(v.sharpe.mean, 3)}、卡玛 ${fN(v.calmar.mean, 3)} 均排第一；年化 ${fP(v.xirr.mean, 2)}，高于全部 6 组原方案（${fP(Math.min(...ORIG.map(k => G[k].xirr.mean)), 2)}～${fP(Math.max(...ORIG.map(k => G[k].xirr.mean)), 2)}），与稳健型持平，低于进取型；最大回撤 ${fP(v.mdd.mean, 1)}，浅于全部原方案，深于平衡型与平衡型 IRP 版。按原报告的综合分公式排名第一。</li>
    <li><b>优势来自危机：</b>大型危机期间回撤 ${fP(C.V2.big.dd, 1)}（组合 1 ${fP(C.C1.big.dd, 1)}，买入持有 ${fP(C.BH.big.dd, 1)}），修复中位数 ${C.V2.big.recMed} 日（组合 1 ${C.C1.big.recMed} 日）。V &gt; 65 起就每天小额卖出，危机前平均仓位 ${fP(C.V2.big.pPeak, 0)}；谷底附近几乎每次都在分批回投（抄底成功 ${fP(C.V2.big.bottom, 0)}，其他方案 ${fP(Math.min(...others.map(k => C[k].big.bottom)), 0)}～${fP(Math.max(...others.map(k => C[k].big.bottom)), 0)}）。危机市年化 ${fP(RES.env.V2[3], 1)}（${ALLK.length} 套中第 ${envRk(3)}），代价是震荡市年化 ${fP(RES.env.V2[0], 1)}（第 ${envRk(0)}）。</li>
    <li><b>上升趋势假回落中，每次陷阱的账户损失最小。</b>V2.0 在陷阱窗口里几乎天天交易，所以按“笔数”算的误触概率很高（见“六组对比”页，那是计数口径带来的）；按每次陷阱合计的账户影响比较才公平：上升趋势假回落 ${fP(TP.V2.up.acct, 2)}（其他 10 套 ${fP(Math.min(...others.map(k => TP[k].up.acct)), 2)}～${fP(Math.max(...others.map(k => TP[k].up.acct)), 2)}，最好），下降趋势假反弹 ${fP(TP.V2.down.acct, 2)}（${ALLK.length} 套中第 ${ALLK.slice().sort((a, b) => TP[b].down.acct - TP[a].down.acct).indexOf('V2') + 1}）。</li>
    <li><b>果断卖出没有带来收益。</b>去掉它（只留平缓曲线）年化 ${fP(vs.xirr.mean, 2)}（${pp(vs.xirr.mean - v.xirr.mean)}），夏普 ${fN(vs.sharpe.mean, 3)}、卡玛 ${fN(vs.calmar.mean, 3)} 基本不变，最大回撤 ${fP(vs.mdd.mean, 1)}（深 ${fN((v.mdd.mean - vs.mdd.mean) * 100, 1)} 个百分点）。每条路径 32 年平均触发 ${fN(X.nDec, 1)} 天。它主要提高大型危机前的逃顶成功率（${fP(X.crisis.V2s.big.escape, 0)} → ${fP(C.V2.big.escape, 0)}），这与文档真实回测“全期年化略低 0.16 个百分点”的结论方向一致。</li>
    <li><b>IRP 替换股债利差：风险调整略好，收益持平。</b>改回股债利差版 V，年化 ${fP(ve.xirr.mean, 2)}、夏普 ${fN(ve.sharpe.mean, 3)}、回撤 ${fP(ve.mdd.mean, 1)}。IRP 版 V 平均更高，定投更少：累计外部入金 ${fW(v.inflow.mean)}，股债利差版 ${fW(ve.inflow.mean)}（文档真实数据中也是 IRP 版定投更少）。</li>
    <li><b>分场景：</b>相对买入持有的超额在 ${wins} 个场景中是 11 套方案里最高的，在 ${beatOrig} 个场景中高于全部 6 组原方案。最弱的是基准震荡型（${pp(RES.byType[1].V2.exBH)}）和强周期型（${pp(RES.byType[6].V2.exBH)}）：没有大的估值极端时，平缓曲线卖得早、买得慢。</li>
  </ol></div>
  <div class="card"><h3>V2.0 与各方案对比（90 条路径均值，净口径）</h3><div class="tbl-wrap" id="v2-tbl"></div><p class="note">“V2.0 无果断卖出”与“V2.0 股债利差版”是本页的消融对照，不进入其他页面的排名。交易笔数：V2.0 每天按净额成交，“回投”为当日净买入且含平缓回投的天数，纯定投日不计。</p></div>
  <div class="grid2"><div class="card"><h3>分场景：相对买入持有的净年化超额（pp）</h3><div class="tbl-wrap" id="v2-type"></div></div>
  <div class="card"><h3>极端事件：大型危机 / 中型回调</h3><div class="tbl-wrap" id="v2-cr"></div><p class="note">口径与“六组对比”页相同。</p></div></div>
  <div class="card"><h3>假回归陷阱：每次陷阱的账户总影响</h3><div class="chart" id="v2-trap"></div><p class="note">对每个有效陷阱，把窗口内全部同向交易（上升趋势假回落中的卖出、下降趋势假反弹中的回投）的“单笔损失 × 交易金额 / 当日总资产”相加，再对 ${RES.traps.total.up} + ${RES.traps.total.down} 个陷阱取平均。数值越接近 0 越好。</p></div>
  <div class="card"><div class="controls">${A.pathSelect('v2-path', 2)}</div>
    <h3 style="margin-top:10px">单条路径：时间加权净值（对数坐标）</h3><div class="chart" id="v2-nav"></div>
    <h3>V2.0 持仓占比与估值分 V</h3><div class="chart" id="v2-pos"></div><p class="note">在浏览器中用同一引擎实时重算。V2.0 的仓位随 V 连续变化：V &gt; 65 逐日减仓，V &lt; 50 逐日回投；对照为组合 1 的持仓占比。</p></div>
  <div class="card"><h3>本页的实现与口径</h3><ul class="tight">
    <li>与其他方案使用同一引擎、同样的 90 条路径和同样的成本：申购 0.1%，赎回按持有期 1.5% / 0.5% / 0.25% / 0，佣金滑点 0.1%，冲击成本 0.5 × ATR / 收盘价；持有不足 30 天不卖、先进先出、赎回款 T+3 到账、初始满仓 20 万元。</li>
    <li>每日顺序：用 T−1 日的 V、U 计算定投 D、平缓回投 R = 可用资金池 × 4% × clip((50 − V)/30)<sup>2</sup>、平缓卖出 S = 持仓 × 4% × clip((V − 65)/20)<sup>2</sup>；U ≤ 1/3 且 V ≥ 50 且 p 高于 T<sub>s</sub> = 1 − 0.8 × clip((V<sub>max</sub> − 65)/20) 超过 5 个百分点时，S* = max(S, (p − T<sub>s</sub>) × (H + C))；S* 受 20% 底仓限制；|N| &lt; 10 元不交易。</li>
    <li>IRP = DY + g − y，g = ROE<sub>n</sub> × (1 − clip(DY × PE, 0, 1))，与“IRP 检验”页的 IRP（DY × (1 + g) + g − y）略有不同，按 V2.0 文档附录 B 实现。</li>
    <li>第九节中枢漂移复核：触发后暂停平缓卖出和果断卖出 20 个交易日，复核结论用与组合 2、3、5、6 相同的规则化代理判定。数据双重验证失败不模拟（与其他方案相同）。</li>
    <li>加入 V2.0 后，综合分在 11 套方案内重新归一化，其他方案的分数相应变化 −4～+5 分（原表见下方注），前四名的先后顺序不变。假回归陷阱表和高波动表中 V2.0 一行按原口径重建计算，用同一重建口径重算组合 1 时，与原表的差异在 1 个百分点以内。</li>
    <li>加入前的综合分：${Object.entries(X.scoreOld).map(([k, x]) => `${esc(shortOf(k))} ${x}`).join('，')}。</li>
    <li>V2.0 文档的卖出区间 65→85、指数 2、最大速度 4% 是在真实数据上选定的，本页没有针对合成行情重新调参。</li>
  </ul></div>`)) {
    $('#v2-path').onchange = e => { v2State.type = +e.target.value; A.rerender(); };
  }
  // 对比表
  const rows = [['V2', v], ['V2s', vs], ['V2e', ve]].concat(['C1', 'C5', 'O1', 'O3', 'O4', 'BH'].map(k => [k, G[k]]));
  const nm = k => k === 'V2s' ? 'V2.0 无果断卖出' : k === 'V2e' ? 'V2.0 股债利差版' : nameOf(k);
  const cols = [['xirr', 'XIRR 净', x => fP(x, 2)], ['xirrG', 'XIRR 毛', x => fP(x, 2)], ['exBH', '超额 vs 持有', x => fS(x)], ['mdd', '最大回撤', x => fP(x, 1)], ['recDays', '修复日', x => fN(x, 0)], ['sharpe', '夏普', x => fN(x, 3)], ['calmar', '卡玛', x => fN(x, 3)], ['costBpY', '成本 bp/年', x => fN(x, 0)], ['nSell', '卖出笔数', x => fN(x, 0)], ['nBuy', '回投笔数', x => fN(x, 0)], ['idle', '资金池闲置', x => fP(x, 0)], ['util', '利用率', x => fP(x, 0)], ['inflow', '累计入金', fW], ['final', '期末财富', fW]];
  $('#v2-tbl').innerHTML = `<table><thead><tr><th>方案</th>${cols.map(c => `<th class="n">${c[1]}</th>`).join('')}</tr></thead><tbody>${rows.map(([k, m]) => `<tr${k === 'V2' ? ' class="hl"' : k === 'BH' ? ' class="sub"' : ''}><td>${sw(k[0] === 'V' ? 'V2' : k)}${esc(nm(k))}</td>${cols.map(c => `<td class="n">${m[c[0]] ? c[2](m[c[0]].mean) : '—'}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  // 分场景
  $('#v2-type').innerHTML = `<table><thead><tr><th>场景</th><th class="n">V2.0</th><th class="n">无果断卖出</th><th class="n">原 6 组最好</th><th class="n">其他 10 套最好</th><th class="n">名次</th></tr></thead><tbody>${types.map(t => { const bt = RES.byType[t], bo = ORIG.reduce((a, b) => bt[b].exBH > bt[a].exBH ? b : a), ba = others.reduce((a, b) => bt[b].exBH > bt[a].exBH ? b : a); const r = ALLK.slice().sort((a, b) => bt[b].exBH - bt[a].exBH).indexOf('V2') + 1; return `<tr><td>${esc(HS.SCENARIOS[t - 1].name)}</td><td class="n"><b class="${sgnCls(bt.V2.exBH)}">${fS(bt.V2.exBH)}</b></td><td class="n">${fS(X.byType.V2s[t].exBH)}</td><td class="n">${fS(bt[bo].exBH)} <span class="note">${esc(shortOf(bo))}</span></td><td class="n">${fS(bt[ba].exBH)} <span class="note">${esc(shortOf(ba))}</span></td><td class="n"><span class="chip${r === 1 ? ' ok' : ''}">${r}/${ALLK.length}</span></td></tr>`; }).join('')}</tbody></table>`;
  // 危机
  const ck = ['V2', 'V2s', 'C1', 'C5', 'O1', 'O4', 'BH'];
  const cOf = k => k === 'V2s' ? X.crisis.V2s : C[k];
  $('#v2-cr').innerHTML = `<table><thead><tr><th>方案</th><th class="n">高点仓位</th><th class="n">逃顶</th><th class="n">抄底</th><th class="n">期间回撤</th><th class="n">修复日</th><th class="n">中型·回撤</th><th class="n">中型·修复</th></tr></thead><tbody>${ck.map(k => { const b = cOf(k).big, m = cOf(k).med; return `<tr${k === 'V2' ? ' class="hl"' : k === 'BH' ? ' class="sub"' : ''}><td>${sw(k[0] === 'V' ? 'V2' : k)}${esc(nm(k))}</td><td class="n">${fP(b.pPeak, 0)}</td><td class="n">${fP(b.escape, 0)}</td><td class="n">${b.bottom == null ? '—' : fP(b.bottom, 0)}</td><td class="n">${fP(b.dd, 1)}</td><td class="n">${b.recMed}</td><td class="n">${fP(m.dd, 1)}</td><td class="n">${m.recMed}</td></tr>`; }).join('')}</tbody></table>`;
  // 陷阱柱图
  const tk = ALLK.slice().sort((a, b) => TP[b].up.acct - TP[a].up.acct);
  chart('#v2-trap').setOption(merge(baseOpt(), {
    legend: { top: 0, textStyle: { color: cssv('--ink2') } }, grid: { top: 34, bottom: 56 },
    xAxis: { type: 'category', data: tk.map(shortOf), axisLabel: { interval: 0, rotate: 30 } },
    yAxis: { type: 'value', axisLabel: { formatter: x => (x * 100).toFixed(1) + '%' } }, tooltip: { valueFormatter: x => fP(x, 2) },
    color: [cssv('--s1'), cssv('--bench')],
    series: [{ name: '上升趋势假回落（卖出）', type: 'bar', data: tk.map(k => ({ value: TP[k].up.acct, itemStyle: { color: k === 'V2' ? cssv('--s8') : cssv('--s1') } })) },
      { name: '下降趋势假反弹（回投）', type: 'bar', data: tk.map(k => ({ value: TP[k].down.acct, itemStyle: { color: k === 'V2' ? cssv('--s8') : cssv('--bench'), opacity: 0.55 } })) }],
  }), true);
  // 单路径
  const t = v2State.type, keys = ['V2', 'C1', 'O4', 'BH'];
  const runs = Object.fromEntries(keys.map(k => [k, A.runS(t, k)]));
  chart('#v2-nav').setOption(merge(baseOpt(), {
    legend: { top: 0, textStyle: { color: cssv('--ink2') } }, grid: { top: 34 },
    xAxis: { type: 'value', min: 0, max: 32, axisLabel: { formatter: x => x + '年' } }, yAxis: { type: 'log', logBase: 2 }, tooltip: { valueFormatter: x => x.toFixed(3) },
    series: keys.map(k => A.lineSeries(k, A.downsample(runs[k].res.twr, 5))),
  }), true);
  const po = A.pathObj(t), cfg = Object.assign({}, HS.V20_DEF), Vs = HS.getV(po.ind, cfg.vWin || [10, 5], [1, 1, 1, 1], cfg.vKeys), t0 = runs.V2.res.t0;
  chart('#v2-pos').setOption(merge(baseOpt(), {
    legend: { top: 0, textStyle: { color: cssv('--ink2') } }, grid: { top: 34, right: 46 },
    xAxis: { type: 'value', min: 0, max: 32, axisLabel: { formatter: x => x + '年' } },
    yAxis: [{ type: 'value', min: 0, max: 1, axisLabel: { formatter: x => (x * 100).toFixed(0) + '%' } }, { type: 'value', min: 0, max: 100, splitLine: { show: false }, axisLabel: { color: cssv('--muted') } }],
    tooltip: { valueFormatter: x => x <= 1 ? fP(x, 0) : x.toFixed(0) },
    series: [A.lineSeries('V2', A.downsample(runs.V2.res.p, 3), { name: 'V2.0 持仓占比' }), A.lineSeries('C1', A.downsample(runs.C1.res.p, 3), { name: '组合1 持仓占比' }),
      { name: '估值分 V（右轴）', type: 'line', yAxisIndex: 1, showSymbol: false, data: A.downsample(Array.from(Vs.subarray(t0)), 3), lineStyle: { width: 1, color: cssv('--muted'), type: [4, 3] }, itemStyle: { color: cssv('--muted') } }],
  }), true);
});
const v2State = { type: 2 };
