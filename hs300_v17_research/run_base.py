import pandas as pd, numpy as np, time
from engine import simulate, metrics
df = pd.read_pickle("out/panel.pkl")
t=time.time(); r = simulate(df); print("sec",time.time()-t)
m = metrics(r); print(pd.Series(m))
print(r["trades"].assign(month=lambda x:x.date.dt.to_period("M")).groupby(["month","side"]).agg(n=("amount","size"),amt=("amount","sum"),V=("V","mean"),px=("close","mean")))
# 纯定投（永不卖）对照
big = df.copy(); 
r0 = simulate(df, sell_sig=pd.Series(False,index=df.index), sell_wait=0)
print(pd.Series(metrics(r0)))
