"""补充统计：版本两两配对差（含标准误）、止盈线 65/70/75 对最大回撤的影响。输出 results/extra.json。"""
import json
import os
import numpy as np
import gen
import indicators as I
import engine as En
from engine import START

HERE = os.path.dirname(os.path.abspath(__file__))
VERS = ["1.6", "1.7", "1.8", "1.9"]


def key(v):
    return f"{v}|net|{'rev' if v != '1.6' else 'norev'}"


def main():
    raw = json.load(open(os.path.join(HERE, "results", "raw.json")))
    mc = [r for r in raw if r["label"]["mc"] and r["label"]["set"] != "留出验证"]
    out = {"paired": {}}
    for a, b in [("1.7", "1.6"), ("1.8", "1.7"), ("1.9", "1.8"), ("1.8", "1.6"), ("1.9", "1.6"), ("1.9", "1.7")]:
        d = np.array([r["main"][key(a)]["xirr"] - r["main"][key(b)]["xirr"] for r in mc])
        m = np.array([r["main"][key(a)]["mdd"] - r["main"][key(b)]["mdd"] for r in mc])
        out["paired"][f"{a}-{b}"] = dict(mean=float(d.mean()), se=float(d.std(ddof=1) / np.sqrt(len(d))),
                                         mdd=float(m.mean()), mdd_se=float(m.std(ddof=1) / np.sqrt(len(m))))
    # 止盈线对回撤：10 条主路径 + 每类 3 条 MC
    res = {v: {sl: dict(x=[], m=[]) for sl in (65, 70, 75)} for v in VERS}
    specs = [(k, s, None) for _, k, _, _, s in gen.PATH_SPECS]
    for no, k, _, _, s in gen.PATH_SPECS:
        for j in range(3):
            specs.append((k, 100000 + no * 1000 + j, None))
    for k, s, p in specs:
        df, meta = gen.make_valid_path(k, s, p)
        ind = I.compute(df)
        D = En.Data(df, ind, None, np.zeros(len(df), bool))
        for v in VERS:
            for sl in (65, 70, 75):
                r = En.run(D, v, cost=True, review=(v != "1.6"), params=dict(SL=float(sl)))
                tw = r["twr"][START - 1:]
                res[v][sl]["x"].append(En.xirr(r["inflow"], r["final"]))
                res[v][sl]["m"].append(float(np.max(1 - tw / np.maximum.accumulate(tw))))
    out["sl_mdd"] = {v: {str(sl): dict(xirr=float(np.mean(d["x"])), mdd=float(np.mean(d["m"]))) for sl, d in res[v].items()} for v in VERS}
    out["sl_mdd_n"] = len(specs)
    json.dump(out, open(os.path.join(HERE, "results", "extra.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
