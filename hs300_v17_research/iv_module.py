"""沪深300 期权隐含波动率分位模块（可插拔）。

本环境网络无法访问期权数据源，所以未内置数据。在本地联网环境执行一次：
    pip install akshare
    python iv_module.py fetch          # 生成 data/iv300.csv（300ETF 期权 QVIX，2019-12 起）
然后：
    python iv_module.py test           # 用真实 IV 分位替换"波动率分位"跑 E 槽位 + 信号层检验

口径：IV_pct = IV 在过去 750 个交易日（不足时至少 244 日）中的分位；>80 视为恐慌，<20 视为平静。
样本仅 2020 年起，≈1.5 个完整估值周期，结论只能作参考，不能单独作为调参依据。"""
import sys
from pathlib import Path
import numpy as np, pandas as pd

F = Path(__file__).parent / "data" / "iv300.csv"


def fetch():
    import akshare as ak
    d = ak.index_option_300etf_qvix()          # 列：date, open, high, low, close
    d = d.rename(columns=str.lower)[["date", "close"]].rename(columns={"close": "iv"})
    d.to_csv(F, index=False)
    print("saved", F, len(d))


def iv_pct():
    d = pd.read_csv(F, parse_dates=["date"]).set_index("date").iv.astype(float)
    return d.rolling(750, min_periods=244).rank(pct=True) * 100


def test():
    from engine import simulate, metrics
    df = pd.read_pickle(Path(__file__).parent / "out" / "panel.pkl")
    p = iv_pct().reindex(df.index)
    start = p.first_valid_index()
    rows = {}
    for k in (75, 80, 85):
        b, s = p > k, p < 100 - k
        for lab, kw in {"基线": {}, f"恐慌加速回投@{k}": dict(buy_aggr=b), f"平静加速止盈@{k}": dict(sell_aggr=s),
                        f"双向@{k}": dict(buy_aggr=b, sell_aggr=s)}.items():
            rows[lab] = metrics(simulate(df, **kw), (start, None))
    print(pd.DataFrame(rows).T.round(3))
    rv = df.rv_pct.reindex(p.index)
    print("IV 分位与 20 日已实现波动率分位相关系数：", round(p.corr(rv), 3))


if __name__ == "__main__":
    {"fetch": fetch, "test": test}[sys.argv[1]]()
