"""生成《沪深300 风险溢价定仓策略 操作手册》PDF。依赖 trades.csv / results.txt / nav.png / robustness.png。"""
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

pdfmetrics.registerFont(TTFont("CN", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", subfontIndex=0))
F = "CN"
INK, MUTED, ACCENT, SOFT, LINE = (colors.HexColor(c) for c in
                                  ["#1f2328", "#59636e", "#b03a2e", "#f6f1ef", "#d0d7de"])
BUY, SELL = colors.HexColor("#1a7f37"), colors.HexColor("#b03a2e")

S = dict(
    title=ParagraphStyle("t", fontName=F, fontSize=22, leading=30, textColor=INK, alignment=TA_CENTER),
    sub=ParagraphStyle("s", fontName=F, fontSize=11, leading=16, textColor=MUTED, alignment=TA_CENTER),
    h1=ParagraphStyle("h1", fontName=F, fontSize=15, leading=22, textColor=ACCENT, spaceBefore=10, spaceAfter=6),
    h2=ParagraphStyle("h2", fontName=F, fontSize=12, leading=18, textColor=INK, spaceBefore=6, spaceAfter=3),
    body=ParagraphStyle("b", fontName=F, fontSize=10, leading=16, textColor=INK, wordWrap="CJK"),
    small=ParagraphStyle("sm", fontName=F, fontSize=8.5, leading=13, textColor=MUTED, wordWrap="CJK"),
    cell=ParagraphStyle("c", fontName=F, fontSize=9, leading=13, textColor=INK, wordWrap="CJK"),
    formula=ParagraphStyle("f", fontName=F, fontSize=12, leading=20, textColor=INK, alignment=TA_CENTER),
)
P = lambda t, s="body": Paragraph(t, S[s])


def box(flow, bg=SOFT, border=ACCENT):
    t = Table([[flow]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.8, border),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def grid(data, widths, header=True, size=9, align="CENTER"):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("FONTNAME", (0, 0), (-1, -1), F), ("FONTSIZE", (0, 0), (-1, -1), size),
          ("TEXTCOLOR", (0, 0), (-1, -1), INK), ("ALIGN", (0, 0), (-1, -1), align),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    t.setStyle(TableStyle(st))
    return t


def footer(c, doc):
    c.saveState()
    c.setFont(F, 8)
    c.setFillColor(MUTED)
    c.drawString(20 * mm, 10 * mm, "沪深300 风险溢价定仓策略 · 操作手册 · 仅供研究，不构成投资建议")
    c.drawRightString(190 * mm, 10 * mm, f"第 {doc.page} 页")
    c.restoreState()


SIGMA = 0.215  # 速查表用的波动率，接近当前扩展窗口估计值 21.3%
GAMMA = 2.0
w_of = lambda pe, y: max(0.0, min(1.0, (1 / pe - y / 100) / (GAMMA * SIGMA ** 2)))

story = []

# ---------------- 封面 + 一页纸 ----------------
story += [Spacer(1, 18 * mm), P("沪深300 风险溢价定仓策略", "title"),
          P("ERP-Merton · 均值回归 · 零拟合参数 · 操作手册", "sub"),
          P("数据截至 2026-09-30", "sub"), Spacer(1, 10 * mm)]

story.append(P("一、策略一句话", "h1"))
story.append(P("股票越便宜（相对国债多赚得越多），就持有越多；越贵，就持有越少。"
               "仓位不是「买 / 不买」二选一，而是一个 0%~100% 之间连续变化的数。"
               "<b>买入</b>就是把仓位往上调到目标，<b>卖出</b>就是往下调到目标。"))
story.append(Spacer(1, 4 * mm))
story.append(box([P("目标股票仓位 = ( 1/PE<sub>TTM</sub> - 10年国债收益率 ) ÷ ( 2 × σ<super>2</super> )", "formula"),
                  P("结果小于 0 取 0（清仓），大于 1 取 1（满仓）", "sub")]))
story.append(Spacer(1, 3 * mm))
story.append(grid([
    ["符号", "含义", "取值 / 来源"],
    ["PE_TTM", "沪深300 滚动市盈率", "中证指数官网、理杏仁、Wind，月末收盘值"],
    ["10年国债", "中债 10 年期国债到期收益率", "中债估值，月末值，单位 %"],
    ["1/PE - 国债", "股债收益差 ERP：股票比国债每年多赚多少", "例：1/13.2 - 1.68% = 5.89%"],
    ["σ", "沪深300 日收益率的年化波动率", "用全部历史日数据算（不是近一年），目前约 21%~22%"],
    ["2", "风险厌恶系数 γ", "固定值，不调。更保守可用 3（仓位整体 ×2/3）"],
], [25 * mm, 65 * mm, 80 * mm]))

story.append(P("二、买卖规则（每月只看一次）", "h1"))
rules = [
    ["步骤", "时间", "动作"],
    ["① 取数", "每月最后一个交易日收盘后", "记录沪深300 PE_TTM、10年国债收益率；更新历史波动率 σ"],
    ["② 算目标", "同上", "代入公式得到目标仓位 w*（或直接查第 2 页速查表）"],
    ["③ 判断", "同上", "计算差值 = w* - 当前实际股票仓位"],
    ["④ 买入", "下一个交易日", "若差值 > +10 个百分点：买入沪深300，把股票仓位加到 w*"],
    ["⑤ 卖出", "下一个交易日", "若差值 < -10 个百分点：卖出沪深300，把股票仓位降到 w*"],
    ["⑥ 不动", "—", "若差值在 ±10 个百分点以内：什么都不做，等下个月"],
]
t = grid([[P(c, "cell") for c in r] if i else r for i, r in enumerate(rules)], [22 * mm, 45 * mm, 103 * mm])
t.setStyle(TableStyle([("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#eaf6ec")),
                       ("BACKGROUND", (0, 5), (-1, 5), colors.HexColor("#fbeceb")),
                       ("ALIGN", (2, 1), (2, -1), "LEFT")]))
story.append(t)
story.append(Spacer(1, 3 * mm))
story.append(P("要点：<br/>• 只在月末看，月中无论涨跌都不操作。<br/>• 10 个百分点的「不动区」用来过滤噪声，回测 14 年只调了 30 次（约每 5 个月一次）。<br/>• 非股票部分放在货币基金 / 短债 / 国债 ETF 中，不闲置。<br/>• 没有止损、没有追涨：价格下跌本身会让 ERP 上升，规则会让你<b>越跌越买</b>；上涨会让你<b>越涨越卖</b>。", "small"))

# ---------------- 速查表 ----------------
story.append(PageBreak())
story.append(P("三、目标仓位速查表", "h1"))
story.append(P(f"按 σ = {SIGMA:.1%}、γ = 2 计算。月末找到当时的 PE（行）和 10年国债收益率（列），交叉处即目标股票仓位。"))
story.append(Spacer(1, 2 * mm))
ys = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
pes = [8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20, 25]
data = [["PE \\ 国债"] + [f"{y:.1f}%" for y in ys]]
for pe in pes:
    data.append([f"{pe}"] + [f"{w_of(pe, y):.0%}" for y in ys])
t = grid(data, [24 * mm] + [20.8 * mm] * len(ys), size=10)
st = []
for r, pe in enumerate(pes, 1):
    for c, y in enumerate(ys, 1):
        w = w_of(pe, y)
        st.append(("BACKGROUND", (c, r), (c, r), colors.Color(0.69, 0.23, 0.18, alpha=0.06 + 0.5 * w)))
t.setStyle(TableStyle(st))
story.append(t)
story.append(Spacer(1, 2 * mm))
story.append(P("颜色越深仓位越高。波动率 σ 每变化 1 个百分点，仓位大约同向反比变化 9%（例：σ=23% 时，表中数值约 ×0.87）。", "small"))

story.append(P("四、仓位与股债收益差的对应关系", "h2"))
erps = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
story.append(grid([["ERP"] + [f"{e}%" for e in erps],
                   ["目标仓位"] + [f"{max(0, min(1, e / 100 / (GAMMA * SIGMA ** 2))):.0%}" for e in erps]],
                  [24 * mm] + [14.6 * mm] * len(erps), size=9.5))
story.append(Spacer(1, 2 * mm))
story.append(P("经验参照（2011-2026）：ERP ≈ 2%~3% 对应 2015 年 6 月、2021 年 2 月这类泡沫顶部，仓位降到 25%~35%；"
               "ERP ≈ 7%~8% 对应 2014 年、2024 年初这类底部，仓位升到 75%~90%。历史均值约 5.3%。", "small"))

story.append(P("五、算一遍：2026-09-30 的信号", "h1"))
ex = [["项目", "数值"],
      ["沪深300 PE_TTM", "13.20  →  盈利收益率 1/13.20 = 7.58%"],
      ["10年国债收益率", "1.68%"],
      ["股债收益差 ERP", "7.58% - 1.68% = 5.89%"],
      ["历史年化波动率 σ", "21.3%  →  2 × 0.213² = 0.0907"],
      ["目标仓位 w*", "5.89% ÷ 0.0907 = 65%"],
      ["当前实际仓位（按回测路径）", "56%"],
      ["差值", "+9 个百分点 < 10  →  本月不动"]]
t = grid([[P(c, "cell") for c in r] if i else r for i, r in enumerate(ex)], [60 * mm, 110 * mm])
t.setStyle(TableStyle([("ALIGN", (1, 1), (1, -1), "LEFT"),
                       ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fff8c5"))]))
story.append(t)
story.append(Spacer(1, 2 * mm))
story.append(P("如果你现在是从零开始（空仓），差值 = 65% - 0% > 10 个百分点，应在下一个交易日买入至 65% 股票 + 35% 货币/债券。"
               "之后每月按上面的步骤复核。", "small"))

# ---------------- 历史交易 ----------------
story.append(PageBreak())
story.append(P("六、历史上每一次买卖（回测 2012-11 至 2026-09）", "h1"))
story.append(P("首次建仓 2012-11-01，仓位 78%。之后共 30 次调仓，绿色为买入（加仓），红色为卖出（减仓）。"
               "信号日 = 月末，执行日 = 下一个交易日。"))
story.append(Spacer(1, 2 * mm))
tr = pd.read_csv("trades.csv")
rows = [["执行日", "沪深300", "PE", "国债%", "ERP%", "调仓前", "调仓后", "方向"]]
style = []
for i, r in tr.iterrows():
    buy = r.after > r.before
    rows.append([r["exec"], f"{r.close:.0f}", f"{r.pe:.1f}", f"{r.y10:.2f}", f"{r.erp:.2f}",
                 f"{r.before:.0f}%", f"{r.after:.0f}%", "买入 ▲" if buy else "卖出 ▼"])
    style.append(("TEXTCOLOR", (7, i + 1), (7, i + 1), BUY if buy else SELL))
t = grid(rows, [26 * mm, 22 * mm, 16 * mm, 18 * mm, 18 * mm, 22 * mm, 22 * mm, 22 * mm], size=8.5)
t.setStyle(TableStyle(style))
story.append(t)
story.append(Spacer(1, 2 * mm))
story.append(P("注意几次典型操作：2015 年 1 月至 5 月指数从 4193 涨到 5518，规则连续三次卖出，仓位从 85% 降到 27%，躲过了 2015 年股灾的大部分跌幅；"
               "2021 年 1 月在 6864 点（核心资产泡沫）降到 29%；2024 年 2 月在 4475 点加到 72%。"
               "同时也要看到，它在 2024-10 的 6081 点就减仓了，错过了后续一部分涨幅——它只看估值，不看趋势。", "small"))

# ---------------- 回测结果 ----------------
story.append(PageBreak())
story.append(P("七、回测表现", "h1"))
story.append(grid([
    ["", "年化收益", "年化波动", "夏普", "最大回撤", "卡玛"],
    ["本策略", "10.0%", "10.9%", "0.92", "-14.9%", "0.67"],
    ["买入持有（含股息）", "9.8%", "21.4%", "0.46", "-45.3%", "0.22"],
    ["静态 52% 股 + 48% 债", "7.1%", "11.1%", "0.63", "-25.2%", "0.28"],
], [52 * mm, 24 * mm, 24 * mm, 20 * mm, 26 * mm, 24 * mm]))
story.append(Spacer(1, 2 * mm))
story.append(P("第三行是关键对照：策略平均仓位 52%，与相同仓位但从不择时的组合相比，每年多出约 2.9%，这才是「越跌越买、越涨越卖」本身的价值。", "small"))
story.append(Image("nav.png", width=170 * mm, height=170 * mm * 1100 / 1210))

story.append(PageBreak())
story.append(P("八、为什么认为它没有过拟合", "h1"))
story.append(grid([[P(c, "cell") for c in r] for r in [
    ["检验", "结果"],
    ["规则预先写死", "公式和全部参数在跑回测之前写入代码，跑完后未修改；γ=2 取自理论，不是搜出来的"],
    ["无前视", "只用当天及以前的数据；信号月末产生、次日执行；波动率用扩展窗口"],
    ["参数网格 240 组", "γ 1~4、σ 四种算法、不动区 0~20%、执行滞后 1/5/21 天：96% 跑赢同仓位静态组合，100% 回撤更小"],
    ["推迟一个月执行", "超额几乎不变，说明不靠精确择点"],
    ["分段", "2012-16、2017-20、2021-26 三段均跑赢同仓位静态组合"],
    ["安慰剂", "把仓位序列随机错位 300 次，随机结果的超额中位数为 -0.2%，没有一次达到真实值"],
]], [40 * mm, 130 * mm]))
story.append(Spacer(1, 3 * mm))
story.append(Image("robustness.png", width=150 * mm, height=75 * mm))

story.append(P("九、局限与风险（请务必读）", "h1"))
for s in [
    "<b>合理预期是每年 1%~2% 的择时超额</b>，而不是回测主方案的 2.9%：主方案在 240 组参数中排位偏上，网格中位数是 1.6%。",
    "<b>牛市里会跑输满仓。</b>2017-2020 年策略年化 11.0%，买入持有 16.8%。滚动 3 年看，只有约一半时间跑赢满仓。它的价值是用一半的波动拿到接近满仓的收益。",
    "<b>现金收益假设偏乐观。</b>回测中非股票部分按 10 年国债票息计息（目前约 1.7%）。实际放货币基金收益可能更低，放长债则会承担价格波动。",
    "<b>样本有限。</b>只有约 14 年、2~3 个牛熊周期。规则虽然取自理论，但设计者知道这段历史，无法完全排除事后偏差。",
    "<b>盈利收益率可能高估真实回报。</b>沪深300 银行权重高，若盈利持续下滑（PE 被动抬高前的「价值陷阱」），E/P 会显得便宜但并不便宜。可以用 PB 或股息率交叉核对。",
    "<b>没有止损。</b>2015、2018 年这样的连续下跌中，它会持续加仓，账面浮亏会很难受，必须事先确认能承受。",
]:
    story.append(P("• " + s))
    story.append(Spacer(1, 1.5 * mm))
story.append(Spacer(1, 3 * mm))
story.append(P("本文为基于历史数据的研究，不构成投资建议。复现代码：erp_merton.py；交易明细：trades.csv。", "small"))

doc = SimpleDocTemplate("沪深300_风险溢价定仓策略.pdf", pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=16 * mm, bottomMargin=18 * mm, title="沪深300 风险溢价定仓策略",
                        author="ERP-Merton")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("ok")
