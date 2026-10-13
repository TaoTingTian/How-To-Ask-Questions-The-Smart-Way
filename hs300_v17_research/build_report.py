"""把各阶段结果拼成 report.html（数据全部来自 out/ 下的回测结果）。"""
import json
import pandas as pd

cur = json.load(open("out/curves.json"))
for k in ("V1.6", "V1.7", "纯定投"):          # 春节等无交易周的 NaN 用前值填充
    for f in ("twr", "pos"):
        cur[k][f] = pd.Series(cur[k][f], dtype=float).ffill().fillna(0).round(4).tolist()
cur["V"] = pd.Series(cur["V"], dtype=float).ffill().round(1).tolist()
rd = json.load(open("out/report_data.json"))
T = pd.DataFrame(rd["T"])
S4 = pd.read_pickle("out/stage4.pkl")
pbo = pd.read_pickle("out/pbo.pkl")
m16, m17, m0 = cur["V1.6"]["m"], cur["V1.7"]["m"], cur["纯定投"]["m"]


def pp(x, d=2, sign=True):
    return (f"{x*100:+.{d}f}" if sign else f"{x*100:.{d}f}")


def cls(x, tol=0.0005):
    return "pos" if x > tol else ("neg" if x < -tol else "flat")


# ---------- 信号层表 ----------
s1 = {r[0]: r for r in rd["s1buy"]}
s1s = {r[0]: r for r in rd["s1sell"]}
names = ["布林带", "RSI", "KDJ", "BIAS", "W%R", "ATR通道", "凯尔特纳", "VWAP偏离", "波动率分位"]
img_no = {"布林带": "01", "RSI": "02", "KDJ": "03", "BIAS": "04", "VWAP偏离": "05", "ATR通道": "08", "W%R": "09",
          "凯尔特纳": "新增", "波动率分位": "新增*"}
rows1 = ""
for n in names:
    b, s = s1[n], s1s[n]
    # 超买信号：超额收益字段已取反（正=之后下跌），这里还原为"之后 20 日收益"
    rows1 += (f"<tr><td>{n}<span class='tag'>{img_no[n]}</span></td>"
              f"<td class='num {cls(b[1])}'>{pp(b[1])}</td><td class='num'>{b[2]:+.2f}</td><td class='num'>{b[3]}</td>"
              f"<td class='num {cls(-s[1])}'>{pp(-s[1])}</td><td class='num'>{-s[2]:+.2f}</td><td class='num'>{s[3]}</td></tr>")

# ---------- 策略层矩阵 ----------
slots = [("A回投过滤", "回投前等超卖"), ("B止盈-超买确认", "止盈前等超买"), ("B'止盈-超买回落", "止盈等超买回落"), ("C定投择时", "定投挂账等超卖")]
head2 = "".join(f"<th>{lab}</th>" for _, lab in slots)
rows2 = ""
for n in names:
    cells = ""
    for s, _ in slots:
        r = T[(T.槽位 == s) & (T.指标 == n)].iloc[0]
        p = r["安慰剂分位"]
        mark = "pass" if (p >= 0.9 and r["网格优于基线比例"] >= 0.75 and r["IS_OOS同向"] and r["ΔIRR"] > 0) else ""
        cells += (f"<td class='cell {mark}'><b class='{cls(r['ΔIRR'])}'>{pp(r['ΔIRR'])}</b>"
                  f"<small>邻域 {r['网格优于基线比例']*100:.0f}% · 安慰剂 {p*100:.0f}分位</small></td>")
    rows2 += f"<tr><th scope='row'>{n}</th>{cells}</tr>"


def one(slot, ind):
    r = T[(T.槽位 == slot) & (T.指标 == ind)].iloc[0]
    return r


struct_rows = ""
for slot, ind, lab, logic in [
    ("对照", "回投延迟20日", "对照：回投一律延迟 20 日", "不看任何指标，只延迟"),
    ("对照", "止盈延迟20日", "对照：止盈一律延迟 20 日", "不看任何指标，只延迟"),
    ("对照", "定投按月(20日)", "对照：定投改为每 20 日买一次", "不看任何指标"),
    ("D趋势替换", "凯尔特纳", "趋势层：凯尔特纳通道突破替换 U", "EMA20 ± 1.5·ATR10，滞回"),
    ("D趋势合成", "凯尔特纳", "趋势层：U 三条均线 + 凯尔特纳第 4 票", "4 票平均"),
    ("D趋势替换", "ATR通道", "趋势层：ATR 通道突破替换 U", "MA20 ± 1.5·ATR14，滞回"),
    ("E恐慌加速回投", "波动率分位", "风险层：高波动时回投改用企稳线", "RV20 分位 > 80"),
    ("E平静加速止盈", "波动率分位", "风险层：低波动时止盈改用下跌线", "RV20 分位 < 20"),
    ("F网格分批回投", "百分比网格", "资金层：回投按 5% 网格分 3 批", "图 07"),
    ("F网格分批止盈", "百分比网格", "资金层：止盈按 5% 网格分 3 批", "图 07"),
]:
    r = one(slot, ind)
    grid = "—" if pd.isna(r["网格优于基线比例"]) else f"{r['网格优于基线比例']*100:.0f}%"
    struct_rows += (f"<tr><td>{lab}<small>{logic}</small></td><td class='num {cls(r['ΔIRR'])}'>{pp(r['ΔIRR'])}</td>"
                    f"<td class='num {cls(r['Δ回撤'])}'>{pp(r['Δ回撤'],1)}</td><td class='num {cls(r['ΔCalmar'],0.002)}'>{r['ΔCalmar']:+.3f}</td>"
                    f"<td class='num'>{grid}</td><td class='num'>{'同向' if r['IS_OOS同向'] else '反向'}</td></tr>")
brk = S4[(S4.类 == "高波动暂停回投") & (S4.名 == "(20, 80, 20)")].iloc[0]
b6 = S4[(S4.类 == "组合") & (S4.名 == "V1.6基线")].iloc[0]
pl = S4[S4.类 == "安慰剂"]
struct_rows += (f"<tr><td>风险层：高波动时暂停回投（刹车）<small>RV20 分位 > 80，满 20 日放行</small></td>"
                f"<td class='num {cls(brk.IRR-b6.IRR)}'>{pp(brk.IRR-b6.IRR)}</td><td class='num {cls(brk.最大回撤-b6.最大回撤)}'>{pp(brk.最大回撤-b6.最大回撤,1)}</td>"
                f"<td class='num flat'>{brk.Calmar-b6.Calmar:+.3f}</td><td class='num'>安慰剂 {(pl.Calmar<brk.Calmar).mean()*100:.0f}分位</td><td class='num'>反向</td></tr>")

# ---------- 组合消融 ----------
comb = S4[S4.类 == "组合"].copy()
crow = ""
for _, r in comb.iterrows():
    crow += (f"<tr><td>{r.名}</td><td class='num'>{pp(r.IRR,2,False)}%</td><td class='num {cls(r.IRR-b6.IRR)}'>{pp(r.IRR-b6.IRR)}</td>"
             f"<td class='num'>{pp(r.最大回撤,1,False)}%</td><td class='num'>{r.Calmar:.3f}</td><td class='num'>{r.IS_Sharpe:.2f}</td><td class='num'>{r.OOS_Sharpe:.2f}</td></tr>")

st5 = pd.read_pickle("out/stage5.pkl")
pos_share = (st5.ΔIRR > 0).mean()
med5 = st5.ΔIRR.median()

data_js = json.dumps({"c": {k: cur[k] for k in ("V1.6", "V1.7", "纯定投")}, "V": cur["V"], "plc": rd["plc"], "real": rd["real"]},
                     ensure_ascii=False)

html = open("report_template.html", encoding="utf-8").read()
for k, v in {
    "%%ROWS1%%": rows1, "%%HEAD2%%": head2, "%%ROWS2%%": rows2, "%%STRUCT%%": struct_rows, "%%COMB%%": crow,
    "%%DATA%%": data_js, "%%PBO%%": f"{pbo['全部']:.2f}", "%%NVAR%%": "418",
    "%%IRR16%%": pp(m16["IRR"], 1, False), "%%IRR17%%": pp(m17["IRR"], 1, False), "%%IRR0%%": pp(m0["IRR"], 1, False),
    "%%MDD16%%": pp(-m16["最大回撤"], 1, False), "%%MDD17%%": pp(-m17["最大回撤"], 1, False), "%%MDD0%%": pp(-m0["最大回撤"], 1, False),
    "%%SH16%%": f"{m16['Sharpe']:.2f}", "%%SH17%%": f"{m17['Sharpe']:.2f}", "%%SH0%%": f"{m0['Sharpe']:.2f}",
    "%%CAL16%%": f"{m16['Calmar']:.2f}", "%%CAL17%%": f"{m17['Calmar']:.2f}", "%%CAL0%%": f"{m0['Calmar']:.2f}",
    "%%MUL16%%": f"{m16['倍数']:.2f}", "%%MUL17%%": f"{m17['倍数']:.2f}", "%%MUL0%%": f"{m0['倍数']:.2f}",
    "%%INV%%": f"{m16['投入']/1e4:.1f}", "%%POS5%%": f"{pos_share*100:.0f}%", "%%MED5%%": pp(med5),
}.items():
    html = html.replace(k, v)
open("report.html", "w", encoding="utf-8").write(html)
print("ok", len(html))
