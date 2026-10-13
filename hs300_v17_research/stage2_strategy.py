"""阶段二：策略层检验。每个指标放入不同插槽，默认参数 + 3×3 邻域网格 + 循环平移安慰剂。
IS = 2014–2019（样本内），OOS = 2020–2026（样本外）。"""
import numpy as np, pandas as pd, itertools
from multiprocessing import Pool
from engine import simulate, metrics, twr_returns
from signals import raw, NAMES, DEFAULT, grid, channel_trend, PX

df = pd.read_pickle("out/panel.pkl")
IS, OOS = ("2014-01-07", "2019-12-31"), ("2020-01-01", "2026-12-31")
WAIT = 20


def run(spec):
    key, kw = spec
    r = simulate(df, **kw)
    m = metrics(r)
    mi, mo = metrics(r, IS), metrics(r, OOS)
    m.update({"IS_TWR": mi["TWR年化"], "IS_Sharpe": mi["Sharpe"], "IS_MDD": mi["最大回撤"],
              "OOS_TWR": mo["TWR年化"], "OOS_Sharpe": mo["Sharpe"], "OOS_MDD": mo["最大回撤"]})
    return key, m, twr_returns(r).values


def ob_fade(s):
    """超买后回落：过去 5 日内出现过超买、T 日已不再超买（W%R"拐头"思路的推广）。"""
    was = s.fillna(False).astype(int).rolling(5, min_periods=1).max().shift(1).fillna(0).astype(bool)
    return was & ~s.fillna(False)


def specs(placebo_n=40):
    S = [(("基线", "V1.6", "-", "-"), {})]
    # 对照：纯延迟（无信号，只靠安全阀）
    F = pd.Series(False, PX.index)
    S += [(("对照", "回投延迟20日", "-", "-"), dict(buy_sig=F, buy_wait=WAIT)),
          (("对照", "止盈延迟20日", "-", "-"), dict(sell_sig=F, sell_wait=WAIT)),
          (("对照", "定投按月(20日)", "-", "-"), dict(dca_sig=F, dca_wait=WAIT))]
    rng = np.random.default_rng(7)
    for name in NAMES:
        for p in grid(name):
            b, s = raw(name, *p)
            dflt = p == DEFAULT[name]
            S.append((("A回投过滤", name, p, dflt), dict(buy_sig=b, buy_wait=WAIT)))
            S.append((("B止盈-超买确认", name, p, dflt), dict(sell_sig=s, sell_wait=WAIT)))
            S.append((("B'止盈-超买回落", name, p, dflt), dict(sell_sig=ob_fade(s), sell_wait=WAIT)))
            S.append((("C定投择时", name, p, dflt), dict(dca_sig=b, dca_wait=WAIT)))
        # 安慰剂：把默认参数信号整体循环平移（保留频率与聚集结构，破坏与行情的对应关系）
        b, s = raw(name, *DEFAULT[name])
        for j, sh in enumerate(rng.integers(120, len(PX) - 120, placebo_n)):
            rb = pd.Series(np.roll(b.fillna(False).values, sh), PX.index)
            rs = pd.Series(np.roll(s.fillna(False).values, sh), PX.index)
            S.append((("P_A", name, j, False), dict(buy_sig=rb, buy_wait=WAIT)))
            S.append((("P_B", name, j, False), dict(sell_sig=rs, sell_wait=WAIT)))
            S.append((("P_B'", name, j, False), dict(sell_sig=ob_fade(rs), sell_wait=WAIT)))
            S.append((("P_C", name, j, False), dict(dca_sig=rb, dca_wait=WAIT)))
    # D 趋势层替换：通道突破型趋势（滞回）
    for kind in ("凯尔特纳", "ATR通道"):
        for n, k in itertools.product((15, 20, 30), (1.0, 1.5, 2.0)):
            st = channel_trend(n, k, kind)
            dflt = (n, k) == (20, 1.5)
            S.append((("D趋势替换", kind, (n, k), dflt), dict(U=st)))
            u2 = (df.U * 3 + st.reindex(df.index)) / 4          # U 与通道趋势合成：4 票
            S.append((("D趋势合成", kind, (n, k), dflt), dict(U=u2)))
    # E 波动率情绪层：高波动(恐慌)→回投用企稳线；低波动(亢奋)→止盈用下跌线
    for n, k in grid("波动率分位"):
        b, s = raw("波动率分位", n, k)
        dflt = (n, k) == DEFAULT["波动率分位"]
        S.append((("E恐慌加速回投", "波动率分位", (n, k), dflt), dict(buy_aggr=b)))
        S.append((("E平静加速止盈", "波动率分位", (n, k), dflt), dict(sell_aggr=s)))
        S.append((("E双向", "波动率分位", (n, k), dflt), dict(buy_aggr=b, sell_aggr=s)))
    # F 动态百分比网格（图 07）分批执行
    for st, nn in itertools.product((0.03, 0.05, 0.08), (2, 3, 4)):
        dflt = (st, nn) == (0.05, 3)
        S.append((("F网格分批回投", "百分比网格", (st, nn), dflt), dict(buy_tranche=(st, nn))))
        S.append((("F网格分批止盈", "百分比网格", (st, nn), dflt), dict(sell_tranche=(st, nn))))
        S.append((("F网格双向", "百分比网格", (st, nn), dflt), dict(buy_tranche=(st, nn), sell_tranche=(st, nn))))
    return S


if __name__ == "__main__":
    sp = specs()
    print("runs:", len(sp))
    with Pool(4) as pool:
        out = pool.map(run, sp, chunksize=8)
    rows, rets = [], {}
    for key, m, r in out:
        rows.append(dict(zip(["槽位", "指标", "参数", "默认"], key)) | m)
        rets[key] = r
    R = pd.DataFrame(rows)
    R.to_pickle("out/stage2.pkl")
    pd.to_pickle(rets, "out/stage2_rets.pkl")
    print(R[R.槽位 == "基线"].T)
