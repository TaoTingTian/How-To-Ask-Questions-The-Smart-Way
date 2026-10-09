"""时序 / 未来函数自检：python test_no_lookahead.py"""
import numpy as np

import backtest as bt


def main():
    df, px = bt.load_data()
    ret = px.pct_change().fillna(0.0)
    bt.ANN = 242.8
    win = ("2019-01-02", "2026-09-30")

    def sharpe(target):
        return bt.perf(bt.run(target, ret, *win, cost=0.0))["夏普"]

    # t 日目标仓位 = t+2 日收益是否为正：若“t 算信号 → t+1 收盘成交 → t+2 起承担收益”实现正确，这等于完美预知
    assert sharpe((ret.shift(-2) > 0).astype(float)) > 5
    # t 日目标仓位 = t+1 日收益是否为正：成交时 t+1 已过去，不应带来显著优势
    assert abs(sharpe((ret.shift(-1) > 0).astype(float))) < 0.5
    # 百分位只用 t 日及以前：截断未来数据不改变历史信号
    for col, d in [("PB", 1), ("ERP", -1)]:
        full = bt.expensiveness(df[col], d, 750)
        cut = bt.expensiveness(df[col].loc[:"2020-06-30"], d, 750)
        assert np.allclose(full.loc[:"2020-06-30"].dropna(), cut.dropna())
    print("OK: 无未来函数")


if __name__ == "__main__":
    main()
