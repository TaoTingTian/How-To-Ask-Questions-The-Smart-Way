// 计算 V2.0（及对照 C1 用于口径校验）在 90 条路径上的全部 RES 字段
const HS=require('./engine_instr.js');const {R,pathList,cfgOf}=require('./base.js');
const KEYS=(process.argv[2]||'C1,V2,V2s,V2e').split(',');
const Y=252,warmFix=null;
const nmJ=j=>({y:'Y',pe:'PE',roe:'ROE',pay:'PAY',vol:'VOL'}[j.ind])+(j.pct>0?'↑':'↓');
const catD=(e,slow)=>(slow?'缓慢':'跳变')+'·'+(((e.ind==='pe'||e.ind==='roe'||e.ind==='y')&&(slow?e.ratePct:e.pct)>0)?'中枢变贵':'中枢变便宜');
const per={};for(const k of KEYS)per[k]=[];
const sig={},env={},drift={},trap={},cris={},jump={},vol={};
for(const k of KEYS){sig[k]={};env[k]=[0,1,2,3].map(()=>[0,0]);drift[k]={};trap[k]={up:[],down:[]};cris[k]={big:[],med:[]};jump[k]={};vol[k]={tot:0,hi:0,erH:[],erO:[]};}
const tot={up:0,down:0};let first=true;
for(const P of pathList()){
 const p=HS.genPath(HS.scenarioSpec(P.type,P.seed));const ind=HS.computeInd(p);const t0=p.warm,N=p.N;
 const rb=HS.runBench(p,ind,{},'bh'),rm=HS.runBench(p,ind,{},'monthly');const mb=HS.metrics(rb,2e5),mm=HS.metrics(rm,2e5);
 const V0=HS.getV(ind);
 // env 标签：危机 = 危机段 + 结束后 63 日
 const L=Uint8Array.from(p.lab,x=>x===4?1:x);for(const c of p.crises)for(let t=c.end;t<Math.min(N,c.end+63)&&(p.lab[t]===4||p.lab[t]===2);t++)L[t]=3;
 const v=Array.from(ind.atrPct.slice(t0)).sort((a,b)=>a-b);const athr=v[Math.floor(0.9*v.length)];
 for(const k of KEYS){
  const r=HS.runStrategy(p,ind,cfgOf(k));const g=HS.runStrategy(p,ind,Object.assign({},cfgOf(k),{costMode:'gross',record:false}));
  const m=HS.metrics(r,2e5),mg=HS.metrics(g,2e5);
  Object.assign(m,{xirrG:mg.xirr,cagrG:mg.cagr,exBH:m.xirr-mb.xirr,exMO:m.xirr-mm.xirr,nDec:r.nDec,decAmt:r.decAmt});
  per[k].push({P,m});
  // env
  for(let i=1;i<r.twr.length;i++){const e=L[t0+i];env[k][e][0]+=Math.log(r.twr[i]/r.twr[i-1]);env[k][e][1]++;}
  // signal
  const S=(sig[k][P.type]=sig[k][P.type]||{s:0,ns:0,b:0,nb:0});
  for(const tr of r.trades){const t=tr.t,c=p.close;
   if(tr.k==='sell'){if(t+252>=N)continue;S.ns++;if(c[t+252]/c[t]-1>0.15)S.s++;}
   else{if(t+126>=N)continue;let mn=1e18;for(let u=t+1;u<=t+126;u++)mn=Math.min(mn,c[u]);S.nb++;if(mn/c[t]-1<-0.15)S.b++;}}
  // drift events
  for(const [Ls,slow] of [[p.drifts,true],[p.jumps,false]])for(const e of Ls){if(e.ind==='vol')continue;if(e.start+e.dur<t0)continue;if(!slow&&e.start<t0)continue;
   const c=catD(e,slow),s=Math.max(t0,e.start),en=Math.min(N-1,e.start+e.dur+504),n=en-s;
   const x=Math.pow(r.twr[en-t0]/r.twr[s-t0],252/n)-Math.pow(rb.twr[en-t0]/rb.twr[s-t0],252/n);(drift[k][c]=drift[k][c]||[]).push(x);}
  // traps：窗口 [touchStart−10, end+10]，损失至趋势延续极值 contT
  for(const tp of p.traps){if(!tp.valid||tp.start<t0)continue;if(k===KEYS[0])tot[tp.dir]++;
   const ts=r.trades.filter(x=>x.t>=tp.touchStart-10&&x.t<=tp.end+10);const want=tp.dir==='up'?'sell':'buy';
   const o={n:ts.length,h:[]};
   for(const x of ts){const same=want==='sell'?x.k==='sell':x.k!=='sell';if(!same||x.t>tp.contT)continue;let ext=x.k==='sell'?-1:1e18;for(let u=x.t;u<=tp.contT;u++)ext=x.k==='sell'?Math.max(ext,p.close[u]):Math.min(ext,p.close[u]);
    const Ls=x.k==='sell'?(x.px/ext-1):(ext/x.px-1);if(Ls<0)o.h.push({l:Ls,a:Ls*x.amt/r.W[x.t-t0]});}
   trap[k][tp.dir].push(o);}
  // crisis
  for(const c of p.crises){if(c.start<t0||c.peak<t0||c.trough+60>=N)continue;const pk=c.peak,tr=c.trough,tw=r.twr,pre=tw[pk-t0];
   let mn=Infinity;for(let u=pk;u<=Math.min(N-1,tr+20);u++)mn=Math.min(mn,tw[u-t0]);let rec=null;for(let u=tr;u<N;u++)if(tw[u-t0]>=pre){rec=u-tr;break;}
   const lowP=p.close[tr];const bot=r.trades.some(x=>x.k!=='sell'&&x.t>=tr-20&&x.t<=tr+60&&x.px<=1.15*lowP);
   cris[k][c.big?'big':'med'].push({pp:r.p[pk-t0],bot,dd:mn/pre-1,rec});}
  // jumps
  for(const j of p.jumps){if(j.start<t0)continue;const c=nmJ(j);if(c.startsWith('VOL'))continue;const s=j.start,e3=Math.min(N-1,s+756);
   const rel=(r.twr[e3-t0]/r.twr[s-t0])/(rb.twr[e3-t0]/rb.twr[s-t0])-1;let idle=0;for(let u=s;u<Math.min(N,s+5*252);u++){if(r.cash[u-t0]/r.W[u-t0]>0.3&&V0[u-1]>=50)idle++;}
   (jump[k][c]=jump[k][c]||[]).push({rel,idle});}
  // vol
  for(let t=t0;t<N;t++){vol[k].tot+=r.impD[t];if(ind.atrPct[t]>=athr)vol[k].hi+=r.impD[t];}
  ((P.type===6||P.type===10)?vol[k].erH:vol[k].erO).push(mg.xirr-m.xirr);
 }
}
const mean=a=>a.reduce((x,y)=>x+y,0)/a.length,med=a=>{a=a.slice().sort((x,y)=>x-y);const n=a.length;return n%2?a[(n-1)/2]:(a[n/2-1]+a[n/2])/2},sd=a=>{const m=mean(a);return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/(a.length-1))},sdp=a=>{const m=mean(a);return Math.sqrt(a.reduce((s,x)=>s+(x-m)**2,0)/a.length)};
const r4=x=>x==null||isNaN(x)?x:Math.round(x*1e4)/1e4;
const OUT={};
for(const k of KEYS){const o=OUT[k]={};const rows=per[k];
 const aggOf=L=>{const a={};for(const f of Object.keys(L[0].m)){const xs=L.map(x=>x.m[f]).filter(x=>x!=null&&!isNaN(x));if(!xs.length)continue;a[f]={mean:r4(mean(xs)),median:r4(med(xs)),std:r4(sd(xs)),stdp:r4(sdp(xs))};}return a;};
 o.main={};rows.filter(x=>x.P.main).forEach(x=>{const mm={};for(const f in x.m)mm[f]=r4(x.m[f]);o.main[x.P.id]=mm;});
 o.aggMain=aggOf(rows.filter(x=>x.P.main));o.aggMC=aggOf(rows.filter(x=>!x.P.main));o.aggAll=aggOf(rows);
 o.aggSplit={};for(const sp of ['train','test','review']){o.aggSplit[sp]={main:aggOf(rows.filter(x=>x.P.main&&HS.SPLIT[x.P.type]===sp)),mc:aggOf(rows.filter(x=>!x.P.main&&HS.SPLIT[x.P.type]===sp))};}
 o.byType={};for(let t=1;t<=10;t++){const L2=rows.filter(x=>x.P.type===t).map(x=>x.m);o.byType[t]={xirr:r4(mean(L2.map(x=>x.xirr))),mdd:r4(mean(L2.map(x=>x.mdd))),sharpe:r4(mean(L2.map(x=>x.sharpe))),calmar:r4(mean(L2.map(x=>x.calmar))),exBH:r4(mean(L2.map(x=>x.exBH))),xirrSd:r4(sd(L2.map(x=>x.xirr))),xirrSdp:r4(sdp(L2.map(x=>x.xirr)))};}
 o.decay={};for(let t=1;t<=10;t++)o.decay[t]=r4(o.byType[t].exBH-o.byType[1].exBH);
 o.env=env[k].map(([s,n])=>r4(Math.exp(s/n*252)-1));
 o.signal={};for(let t=1;t<=10;t++){const S=sig[k][t];o.signal[t]={sell:r4(S.s/S.ns),buy:r4(S.b/S.nb),all:r4((S.s+S.b)/(S.ns+S.nb)),n:S.ns+S.nb};}
 o.driftEv={};for(const c in drift[k])o.driftEv[c]={n:drift[k][c].length,v:r4(mean(drift[k][c]))};
 o.traps={};for(const d of ['up','down']){const L2=trap[k][d];const H=L2.flatMap(x=>x.h);o.traps[d]={pTrig:r4(L2.filter(x=>x.n>0).length/L2.length),pHarm:r4(L2.filter(x=>x.h.length).length/L2.length),nTrades:L2.reduce((a,x)=>a+x.n,0),nHarm:H.length,avgLoss:r4(mean(H.map(x=>x.l))),maxLoss:r4(Math.min(...H.map(x=>x.l))),avgAcctLoss:r4(mean(H.map(x=>x.a))),maxAcctLoss:r4(Math.min(...H.map(x=>x.a)))};}
 o.trapTotal=tot;
 o.trapPer={};for(const d of ['up','down']){const L2=trap[k][d];o.trapPer[d]={acct:r4(mean(L2.map(x=>x.h.reduce((a,y)=>a+y.a,0)))),worst:r4(Math.min(...L2.map(x=>x.h.reduce((a,y)=>a+y.a,0)))),nSame:r4(mean(L2.map(x=>x.h.length)))};}
 o.crisis={};for(const b of ['big','med']){const L2=cris[k][b];const recs=L2.filter(x=>x.rec!=null).map(x=>x.rec);o.crisis[b]={n:L2.length,escape:r4(mean(L2.map(x=>x.pp<=0.6?1:0))),pPeak:r4(mean(L2.map(x=>x.pp))),bottom:r4(mean(L2.map(x=>x.bot?1:0))),recMed:Math.round(med(recs)),recMean:Math.round(mean(recs)),dd:r4(mean(L2.map(x=>x.dd)))};}
 o.jump={};for(const c in jump[k]){const L2=jump[k][c];o.jump[c]={n:L2.length,rel3y:r4(mean(L2.map(x=>x.rel))),idleDays:Math.round(mean(L2.map(x=>x.idle)))};}
 o.vol={impHiShare:r4(vol[k].hi/vol[k].tot),erosionHiVol:r4(mean(vol[k].erH)),erosionOther:r4(mean(vol[k].erO))};
 // bootstrap：路径重抽样 4000 次，均值的 2.5/50/97.5 分位
 o.bootCi={};let seed=12345;const rnd=()=>{seed=(seed*1103515245+12345)%2147483648;return seed/2147483648;};
 for(const f of ['xirr','sharpe','calmar','mdd'])for(const set of ['main','all']){const xs=rows.filter(x=>set==='all'||x.P.main).map(x=>x.m[f]);const bs=[];for(let b=0;b<4000;b++){let s=0;for(let i=0;i<xs.length;i++)s+=xs[Math.floor(rnd()*xs.length)];bs.push(s/xs.length);}bs.sort((a,b)=>a-b);
  ((o.bootCi[f]=o.bootCi[f]||{})[set])=[r4(bs[100]),r4(bs[2000]),r4(bs[3899])];}
}
require('fs').writeFileSync('out_'+KEYS.join('_')+'.json',JSON.stringify(OUT));
console.log('done');
