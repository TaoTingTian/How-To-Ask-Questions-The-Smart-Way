"""补充检查：Plan C 在自身邻域中的分位；要求≥5年百分位历史（min_n=1260）后的表现"""
import itertools, numpy as np, pandas as pd
from engine import load_data, add_signals, set_ma, run, fmt
from plan_d import PLAN_D, ENS8
OUT=[]
def p(*a):
    s=" ".join(str(x) for x in a); print(s); OUT.append(s)
base=add_signals(load_data())
ma_sets=[(40,80,160),(60,120,240),(80,160,320),(30,60,120),(50,100,200)]
cache={m:set_ma(base,m) for m in ma_sets}
xs=[run(cache[m],tiers=((s,1.0),),resume_thr=r,u_thr=u)["xirr"] for s,r,m,u in itertools.product([20,25,30],[50,55,58,60,65],ma_sets,[0,1/3,2/3])]
pc=run(base)["xirr"]
p(f"Plan C 点估计 XIRR {pc*100:.2f}% 在其225组邻域中的分位：{np.mean(np.array(xs)<pc):.0%}；邻域中位 {np.median(xs)*100:.2f}%")
p("\n要求百分位至少5年历史（min_n=1260，S 首个有效日≈2016-10），2016-10 起回测：")
b5=add_signals(load_data(),min_n=1260)
st=b5.S.first_valid_index(); p("S首个有效日",st.date())
p("Plan C   ",fmt(run(b5)))
for e in run(b5)["events"]: p("    ",e[0].date(),e[1],round(e[2],1))
p("Plan D   ",fmt(run(set_ma(b5,ENS8),**PLAN_D)))
p("永不清仓 ",fmt(run(b5,tiers=())))
open("results_extra.txt","w").write("\n".join(OUT))
