import json, re, sys
SP='/tmp/claude-0/-home-user-How-To-Ask-Questions-The-Smart-Way/1895c3b0-1d47-5ea6-859e-d11849cbb7b7/scratchpad/lab'
R=json.load(open(SP+'/work/RES.json'))
O=json.load(open('/tmp/lab2/out_C1_C2_C3_C4_C5_C6_O1_O2_O3_O4_V2_V2s_V2e.json'))
V=O['V2']
def agg(a): return {f:{'mean':x['mean'],'median':x['median'],'std':x['stdp']} for f,x in a.items()}
# ---- 1 strats
cfg={'mode':'v20','name':'V2.0','vKeys':['EY','BP','DY','IRP2'],'floor':0.2,'zoneB':50,'rB0':50,'rB1':20,'rMax':0.04,'rPow':2,'sS0':65,'sS1':85,'sMax':0.04,'sPow':2,'decisive':True,'dS0':65,'dS1':85,'dThr':0.05,'minAmt':10,'review':'proxy','ma':[40,80,160],'vWin':[10,5],'vW':[1,1,1,1]}
assert not any(s['key']=='V2' for s in R['strats'])
R['strats'].append({'key':'V2','name':'V2.0 每日净额','short':'V2.0','cfg':cfg})
# ---- 2 metrics
keep=list(R['main']['M1']['C1'].keys())+['nDec']
for mid,m in V['main'].items(): R['main'][mid]['V2']={f:m[f] for f in keep if f in m}
for s in ['aggMain','aggMC','aggAll']: R[s]['V2']=agg(V[s])
for sp in ['train','test','review']:
    for part in ['main','mc']: R['aggSplit'][sp][part]['V2']=agg(V['aggSplit'][sp][part])
for t in R['byType']: b=V['byType'][t]; R['byType'][t]['V2']={k:b[k] for k in ['xirr','mdd','sharpe','calmar','exBH']}|{'xirrSd':b['xirrSdp']}
R['env']['V2']=V['env']
for t in R['signal']: R['signal'][t]['V2']=V['signal'][t]
R['decay']['V2']=V['decay']
for c in R['driftEv']: assert V['driftEv'][c]['n']==R['driftEv'][c]['n']; R['driftEv'][c]['V2']=V['driftEv'][c]['v']
assert V['trapTotal']==R['traps']['total']
R['traps']['V2']=V['traps']
R['stress']['crisis']['V2']=V['crisis']; assert V['crisis']['big']['n']==R['stress']['crisis']['C1']['big']['n']
for c in R['stress']['jump']: assert V['jump'][c]['n']==R['stress']['jump'][c]['n']; R['stress']['jump'][c]['V2']={'rel3y':V['jump'][c]['rel3y'],'idleDays':V['jump'][c]['idleDays']}
R['stress']['vol']['V2']=V['vol']
for f in R['boot']:
    for st in ['main','all']: R['boot'][f][st]['ci']['V2']=V['bootCi'][f][st]
# ---- 3 score（11 套重新归一化，公式与原报告相同）
K=['C1','C2','C3','C4','C5','C6','O1','O2','O3','O4','V2']
g=lambda k,m:R['aggAll'][k][m]['mean']
tp=lambda k:(R['traps'][k]['up']['pHarm']+R['traps'][k]['down']['pHarm'])/2
def norm(v,hi=True):
    lo,mx=min(v.values()),max(v.values());return {k:((x-lo)/(mx-lo) if hi else (mx-x)/(mx-lo))*100 for k,x in v.items()}
n=[norm({k:g(k,'xirr') for k in K}),norm({k:g(k,'sharpe') for k in K}),norm({k:g(k,'calmar') for k in K}),norm({k:g(k,'mdd') for k in K}),norm({k:tp(k) for k in K},False),norm({k:g(k,'costBpY') for k in K},False)]
w=[.25,.2,.2,.15,.1,.1]
old=dict(R['score'])
R['score']={k:round(sum(wi*ni[k] for wi,ni in zip(w,n))) for k in K}
print('score',R['score'])
# ---- 4 V2.0 专页数据
R['v20']={'variants':{k:agg(O[k]['aggAll']) for k in ['V2s','V2e']},
 'byType':{k:{t:{'exBH':O[k]['byType'][t]['exBH']} for t in O[k]['byType']} for k in ['V2s','V2e']},
 'crisis':{k:O[k]['crisis'] for k in ['V2s','V2e']},
 'trapPer':{k:O[k]['trapPer'] for k in K},
 'nDec':V['aggAll']['nDec']['mean'],'scoreOld':old,'generated':'2026-11-01'}
R['meta']['v20Added']='2026-11-01'
# ---- 5 app.js 修改
app=open(SP+'/work/app.js').read()
def rep(a,b,cnt=1):
    global app
    c=app.count(a); assert c==cnt,(a[:80],c); app=app.replace(a,b)
rep("C6: '--s6', O1: '--s7', O2: '--s7', O3: '--s7', O4: '--s7', BH: '--bench'","C6: '--s6', O1: '--s7', O2: '--s7', O3: '--s7', O4: '--s7', V2: '--s8', BH: '--bench'")
rep("lineStyle: { width: key[0] === 'O' ? 2.4 : 1.6","lineStyle: { width: key[0] === 'O' || key === 'V2' ? 2.4 : 1.6")
rep("const ovState = { type: 1, sel: ['C1', 'C5', 'O1', 'O2', 'O3', 'O4', 'BH'], focus: 'O4' };","const ovState = { type: 1, sel: ['C1', 'C5', 'O1', 'O2', 'O3', 'O4', 'V2', 'BH'], focus: 'V2' };")
rep("<select id=\"tu-base\">${SKEY.map(","<select id=\"tu-base\">${SKEY.filter(k => k !== 'V2').map(")
rep("['C1', 'C3', 'C5', 'C6', 'O1', 'O2', 'O3', 'O4', 'BH'].includes(k)","['C1', 'C3', 'C5', 'C6', 'O1', 'O2', 'O3', 'O4', 'V2', 'BH'].includes(k)")
rep("ALLK = ORIG.concat(OPTK);","ALLK = ORIG.concat(OPTK, ['V2']);")
n_hl=app.count("k[0] === 'O' ? ' class=\"hl\"'")
app=app.replace("k[0] === 'O' ? ' class=\"hl\"'","(k[0] === 'O' || k === 'V2') ? ' class=\"hl\"'"); print('hl',n_hl)
rep("symbol: k[0] === 'O' ? 'diamond' :","symbol: k === 'V2' ? 'triangle' : k[0] === 'O' ? 'diamond' :")
# 摘要：新增 V2.0 结论
rep("    <li><b>用隐含风险溢价替换股债利差：不提高收益，略降风险。</b>",
"    <li><b>新增 V2.0（每日净额）：风险调整后最好，综合分第一。</b>夏普 ${fN(M('V2').sharpe.mean, 3)}、卡玛 ${fN(M('V2').calmar.mean, 3)} 为全部方案最高，年化 ${fP(M('V2').xirr.mean, 2)} 高于全部原方案、与稳健型持平，最大回撤 ${fP(M('V2').mdd.mean, 1)}；大型危机期间回撤 ${fP(RES.stress.crisis.V2.big.dd, 1)}，为全部方案最浅。果断卖出不提高收益（去掉后年化 ${fP(RES.v20.variants.V2s.xirr.mean, 2)}）。详见“V2.0 回测”页。</li>\n    <li><b>用隐含风险溢价替换股债利差：不提高收益，略降风险。</b>")
# 结论页
rep("平衡型 IRP 版综合分最高（${RES.score.O4}），回撤最浅（${fP(M('O4').mdd.mean, 1)}）、夏普最高（${fN(M('O4').sharpe.mean, 3)}），",
"平衡型 IRP 版在三套优化方案中综合分最高（${RES.score.O4}），回撤为全部方案最浅（${fP(M('O4').mdd.mean, 1)}）、夏普 ${fN(M('O4').sharpe.mean, 3)}，")
rep("    <li><b>如果只做一处改动：</b>",
"    <li><b>V2.0（每日净额）：</b>综合分 ${RES.score.V2}，为全部 ${ALLK.length} 套最高；夏普、卡玛第一，年化与稳健型持平，危机中回撤最浅、修复最快。代价是几乎每天都有小额交易（适合用程序自动生成指令），IRP 版 V 偏高使累计定投少约 ${fP(1 - M('V2').inflow.mean / M('C1').inflow.mean, 0)}。果断卖出可以去掉：收益略升、回撤略深，差异在噪声范围内。</li>\n    <li><b>如果只做一处改动：</b>")
rep("账户影响 = 单笔损失 × 交易金额 / 当日总资产。</p></div>","账户影响 = 单笔损失 × 交易金额 / 当日总资产。V2.0 在陷阱窗口内几乎每天小额交易，按笔数统计的触发与误触概率天然偏高；按每次陷阱合计账户影响的公平比较见“V2.0 回测”页。V2.0 一行按重建口径计算（组合 1 复算误差 &lt; 1 个百分点）。</p></div>")
# 插入 V2.0 页
page=open('/tmp/lab2/build/v20page.js').read()
parts=app.split('/*=====SPLIT=====*/')
assert len(parts)==2
p2=parts[1]
anchor="// ================================================================ 6 中枢漂移预警体系"
if anchor not in p2:
    anchor=[l for l in p2.split('\n') if "A.register('warnsys'" in l][0]
    i=p2.index(anchor); i=p2.rfind('\n// ====',0,i)
else: i=p2.index(anchor)
p2=p2[:i]+page+'\n'+p2[i:]
parts[1]=p2
# ---- 6 引擎
eng=open('/tmp/lab2/engine.js').read()
# ---- 7 HTML
h=open(SP+'/src/index.html').read()
scripts=list(re.finditer(r'<script(?:\s[^>]*)?>(.*?)</script>', h, re.S))
assert 'function runStrategy' in scripts[1].group(1) and scripts[2].group(1).startswith('window.RES=')
new=[None,eng,'window.RES='+json.dumps(R,ensure_ascii=False,separators=(',',':'))+';',parts[0],parts[1]]
out=[];last=0
for i,m in enumerate(scripts):
    out.append(h[last:m.start(1)]); out.append(m.group(1) if new[i] is None else new[i]); last=m.end(1)
out.append(h[last:]); h2=''.join(out)
def hrep(a,b):
    global h2
    assert h2.count(a)==1,a[:60]; h2=h2.replace(a,b)
hrep('<button type="button" data-p="irp" aria-selected="false">IRP 检验</button>','<button type="button" data-p="irp" aria-selected="false">IRP 检验</button><button type="button" data-p="v20" aria-selected="false">V2.0 回测</button>')
hrep('<section class="page" id="p-warnsys" hidden>','<section class="page" id="p-v20" hidden><h2>5c · V2.0 每日净额策略回测</h2><div class="body"></div></section>\n<section class="page" id="p-warnsys" hidden>')
hrep('<h1>沪深300 六组策略 · 回测与结构优化</h1>','<h1>沪深300 六组策略 + V2.0 · 回测与结构优化</h1>')
hrep('对 V1.6 / V1.7 / V1.8 买卖法的六种组合执行全规则回测、横向对比、防过拟合优化与中枢漂移预警检验。','对 V1.6 / V1.7 / V1.8 买卖法的六种组合执行全规则回测、横向对比、防过拟合优化与中枢漂移预警检验；2026-11-01 加入 V2.0（每日净额：定投 + 平缓回投 − 平缓/果断卖出），在同一批路径上回测。')
hrep('<span>生成 2026-10-14</span>','<span>生成 2026-10-14 · V2.0 加入 2026-11-01</span>')
open('/tmp/lab2/build/index.html','w').write(h2)
print('size',len(h2))
