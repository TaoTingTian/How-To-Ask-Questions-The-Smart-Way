const HS=require('./engine.js');
const R=require('/tmp/claude-0/-home-user-How-To-Ask-Questions-The-Smart-Way/1895c3b0-1d47-5ea6-859e-d11849cbb7b7/scratchpad/lab/work/RES.json');
const V2CFG={mode:'v20',name:'V2.0'};
function pathList(){const L=[];for(let t=1;t<=10;t++)L.push({id:'M'+t,type:t,seed:20261014+97*t,main:true});
 for(let t=1;t<=10;t++)for(let k=0;k<8;k++)L.push({id:`MC${t}_${900000+1000*t+k}`,type:t,seed:900000+1000*t+k,main:false});return L;}
function cfgOf(k){if(k==='V2')return V2CFG;if(k==='V2s')return Object.assign({},V2CFG,{decisive:false});if(k==='V2e')return Object.assign({},V2CFG,{vKeys:['EY','BP','DY','ERP']});return R.strats.find(s=>s.key===k).cfg;}
function run(p,ind,k,extra){if(k==='BH'||k==='MO')return HS.runBench(p,ind,Object.assign({},extra||{}),k==='BH'?'bh':'monthly');return HS.runStrategy(p,ind,Object.assign({},cfgOf(k),extra||{}));}
module.exports={HS,R,pathList,cfgOf,run};
