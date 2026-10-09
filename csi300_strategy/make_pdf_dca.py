"""生成《沪深300 每日定投 · 目标仓位 + 价值陷阱修正 操作手册》PDF。"""
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(TTFont("CN", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", subfontIndex=0))
F = "CN"
INK, MUTED, ACCENT, SOFT, LINE = (colors.HexColor(c) for c in
                                  ["#1f2328", "#59636e", "#b03a2e", "#f6f1ef", "#d0d7de"])
S = dict(
    title=ParagraphStyle("t", fontName=F, fontSize=21, leading=29, textColor=INK, alignment=TA_CENTER),
    sub=ParagraphStyle("s", fontName=F, fontSize=10.5, leading=16, textColor=MUTED, alignment=TA_CENTER),
    h1=ParagraphStyle("h1", fontName=F, fontSize=14.5, leading=21, textColor=ACCENT, spaceBefore=8, spaceAfter=5),
    h2=ParagraphStyle("h2", fontName=F, fontSize=11.5, leading=17, textColor=INK, spaceBefore=5, spaceAfter=3),
    body=ParagraphStyle("b", fontName=F, fontSize=10, leading=16, textColor=INK, wordWrap="CJK"),
    small=ParagraphStyle("sm", fontName=F, fontSize=8.5, leading=13, textColor=MUTED, wordWrap="CJK"),
    cell=ParagraphStyle("c", fontName=F, fontSize=9, leading=13, textColor=INK, wordWrap="CJK"),
    formula=ParagraphStyle("f", fontName=F, fontSize=11, leading=19, textColor=INK, wordWrap="CJK"),
)
P = lambda t, s="body": Paragraph(t, S[s])


def box(flows, bg=SOFT, border=ACCENT):
    t = Table([[flows]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.8, border),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return t


def grid(data, widths, size=9, wrap=False, left_cols=()):
    if wrap:
        data = [data[0]] + [[P(str(c), "cell") for c in r] for r in data[1:]]
    t = Table(data, colWidths=widths, repeatRows=1)
    st = [("FONTNAME", (0, 0), (-1, -1), F), ("FONTSIZE", (0, 0), (-1, -1), size),
          ("TEXTCOLOR", (0, 0), (-1, -1), INK), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("GRID", (0, 0), (-1, -1), 0.4, LINE),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
          ("BACKGROUND", (0, 0), (-1, 0), INK), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    st += [("ALIGN", (c, 1), (c, -1), "LEFT") for c in left_cols]
    t.setStyle(TableStyle(st))
    return t


def footer(c, doc):
    c.saveState(); c.setFont(F, 8); c.setFillColor(MUTED)
    c.drawString(20 * mm, 10 * mm, "沪深300 每日定投 · 目标仓位 + 价值陷阱修正 · 仅供研究，不构成投资建议")
    c.drawRightString(190 * mm, 10 * mm, f"第 {doc.page} 页"); c.restoreState()


SIG2 = 2 * 0.215 ** 2
w_of = lambda pe, y: max(0.0, min(1.0, (1 / pe - y / 100) / SIG2))
story = []

# ---------- 第 1 页 ----------
story += [Spacer(1, 8 * mm), P("沪深300 每日定投操作手册", "title"),
          P("目标仓位引导 + 价值陷阱修正 + 高估止盈 · 均值回归 · 无拟合参数", "sub"),
          P("数据 2011-09 ~ 2026-09 · 回测 2012-10 ~ 2026-09", "sub"), Spacer(1, 6 * mm)]

story.append(P("一、结论先说", "h1"))
story.append(box([P("• 每天都定投，但<b>每天的钱买股票还是存进备用金，由「目标仓位」决定</b>；每月复核一次，低估时用备用金加仓，高估时卖出止盈。"),
                  P("• 回测 14 年：<b>最终资产与普通定投基本持平（-1% ~ -5%），最大回撤从 -49% 降到 -21% ~ -24%</b>。"),
                  P("• 2015 年股灾、2021-2024 年下跌和价值陷阱期间，明显好于普通定投（见第 3 页）。"),
                  P("• 它<b>不能</b>让你比普通定投多赚很多钱。它的作用是用一半的波动拿到同样的收益。")]))

story.append(P("二、价值陷阱怎么处理", "h1"))
story.append(P("上一版直接用 PE_TTM。问题在于：盈利正在下滑时，PE_TTM 用的还是过去较高的盈利，看起来便宜，其实不便宜。"
               "这一版在计算「便宜程度」之前，先让盈利通过两道检验，<b>两道都没有可调参数</b>："))
story.append(Spacer(1, 2 * mm))
story.append(grid([
    ["检验", "做法", "防的是什么"],
    ["① 盈利下滑外推", "若隐含每股盈利 E（= 点位 ÷ PE）比一年前下降了 g，就假设明年再降一次：E 修正 = E × (1 - |g|)", "盈利下行周期中「越跌越便宜」的假象（如 2016、2022-2024）"],
    ["② 不用景气高点盈利", "再取 E 修正 与 过去 3 年 E 的平均值，两者中较小的一个", "盈利处在周期高点时 PE 显得偏低（周期股陷阱）"],
], [32 * mm, 80 * mm, 58 * mm], wrap=True, left_cols=(1, 2)))
story.append(Spacer(1, 2 * mm))
story.append(P("数据验证（2012-2026）：原始估值显示「便宜」的日子里，若盈利同比在下滑，指数未来 1 年涨幅中位数为 13%，下跌概率 19%；"
               "盈利在增长时则为 24% 和 16%。<b>陷阱效应确实存在，但在这段历史里，「陷阱」平均仍然是赚钱的</b>。"
               "因此修正的代价是少赚一点（约 0.6%/年），换来的是回撤再小 3 个百分点左右。你可以按自己的偏好选择保守版（修正）或标准版（不修正），见第 3 页对比。", "small"))

story.append(P("三、目标仓位公式", "h1"))
story.append(box([P("E = 点位 ÷ PE_TTM　　g = E ÷ 一年前的 E - 1", "formula"),
                  P("E 保守 = min( E × (1 + min(g, 0)) , 过去 3 年 E 的平均值 )", "formula"),
                  P("ERP = E 保守 ÷ 点位 - 10年国债收益率", "formula"),
                  P("<b>目标仓位 w* = ERP ÷ (2 × σ²)</b>，限制在 0% ~ 100%；σ 为全部历史数据算出的年化波动率（约 21%）", "formula")]))

# ---------- 第 2 页 ----------
story.append(PageBreak())
story.append(P("四、每日 / 每月操作流程", "h1"))
story.append(grid([
    ["频率", "时间", "动作"],
    ["每天", "收盘后", "更新 w*（PE、国债每天都有；E 的一年前值和 3 年均值月更即可）"],
    ["每天", "下一交易日", "定投 X 元（例如每天 200 元）：<br/>• 若 股票市值 ÷ (总资产 + X) &lt; w* → X 元全部买入沪深300 ETF<br/>• 否则 → X 元买入货币基金 / 短债 / 国债 ETF（备用金）"],
    ["每月", "首个交易日", "• 若 股票占比 &lt; w* - 10 个百分点 → 卖出备用金，买股票补到 w*（低估加仓）<br/>• 若 股票占比 &gt; w* + 10 个百分点 → 卖出股票降到 w*，钱转入备用金（高估止盈）<br/>• 在 ±10 个百分点以内 → 不动"],
], [18 * mm, 24 * mm, 128 * mm], wrap=True, left_cols=(2,)))
story.append(Spacer(1, 2 * mm))
story.append(P("要点：<br/>• <b>备用金一定要放在有收益的地方</b>（货币基金 / 国债 ETF）。回测显示备用金不计息时，终值会低 10% 左右。<br/>"
               "• 日常的定投只决定新钱的去向，真正的买低卖高靠每月复核（±10 个百分点以内不动，调仓并不频繁）。<br/>"
               "• 下跌时新钱自动多进股票、上涨时自动多进备用金，这就是「拉低均价」的方式，而且有纪律地兑现。", "small"))

story.append(P("五、算一遍：2026-09-30", "h1"))
story.append(grid([
    ["项目", "计算"],
    ["点位 / PE_TTM", "6547.69 / 13.20  →  E = 496.0"],
    ["一年前 E", "469.8  →  g = +5.6%（盈利在增长，① 不触发）"],
    ["过去 3 年 E 平均", "451.6  →  E 保守 = min(496.0, 451.6) = 451.6（② 触发，盈利高于 3 年均值）"],
    ["ERP", "451.6 ÷ 6547.69 - 1.68% = 6.90% - 1.68% = 5.22%"],
    ["σ", "21.3%  →  2 × 0.213² = 0.0911"],
    ["目标仓位 w*", "5.22% ÷ 0.0911 = <b>57%</b>（不做陷阱修正为 65%）"],
    ["今天怎么做", "股票占比低于 57% → 今天的定投款全部买沪深300；高于 57% → 今天的钱放进备用金"],
], [42 * mm, 128 * mm], wrap=True, left_cols=(1,)))

story.append(P("六、速查表：「保守 PE」× 10年国债 → 目标仓位", "h1"))
story.append(P("保守 PE = 点位 ÷ E 保守（不做修正时就是普通 PE_TTM）。σ 按 21.5% 计算。", "small"))
ys = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
pes = [9, 10, 11, 12, 13, 14, 15, 16, 18, 20]
t = grid([["保守PE \\ 国债"] + [f"{y:.1f}%" for y in ys]] + [[str(pe)] + [f"{w_of(pe, y):.0%}" for y in ys] for pe in pes],
         [28 * mm] + [23.6 * mm] * len(ys), size=9.5)
t.setStyle(TableStyle([("BACKGROUND", (c, r), (c, r), colors.Color(0.69, 0.23, 0.18, alpha=0.06 + 0.5 * w_of(pe, y)))
                       for r, pe in enumerate(pes, 1) for c, y in enumerate(ys, 1)]))
story.append(t)

# ---------- 第 3 页 ----------
story.append(PageBreak())
story.append(P("七、回测结果（每天投入 1 份，共 3392 份，2012-10 ~ 2026-09）", "h1"))
story.append(grid([
    ["方案", "期末资产 / 投入", "资金年化 XIRR", "最大回撤"],
    ["普通每日定投（每天全买沪深300）", "1.82", "8.2%", "-49.3%"],
    ["本方案·标准版（不做陷阱修正）", "1.80", "8.0%", "-24.3%"],
    ["本方案·保守版（陷阱修正）", "1.72", "7.4%", "-20.8%"],
    ["只买不卖版（不止盈，标准版）", "1.70", "7.3%", "-40.8%"],
], [72 * mm, 32 * mm, 32 * mm, 34 * mm], wrap=True, left_cols=(0,)))
story.append(Spacer(1, 1 * mm))
story.append(P("最大回撤按「资产 ÷ 累计投入」计算。备用金按 10 年国债票息计息。", "small"))
story.append(Image("dca_target_nav.png", width=170 * mm, height=170 * mm * 550 / 1210))
story.append(P("关键时期（期末资产 ÷ 投入 / 期间最大回撤）", "h2"))
story.append(grid([
    ["时期", "普通定投", "标准版", "保守版"],
    ["2015-01 ~ 2016-12　泡沫 + 股灾", "0.98 / -43.5%", "1.04 / -14.7%", "1.04 / -11.9%"],
    ["2021-01 ~ 2024-09　泡沫 + 价值陷阱期", "0.87 / -25.6%", "0.96 / -11.9%", "0.96 / -10.7%"],
], [70 * mm, 33 * mm, 33 * mm, 34 * mm], wrap=True, left_cols=(0,)))
story.append(P("稳健性", "h2"))
story.append(grid([
    ["检验", "结果"],
    ["滚动起点（每季度一个，持有 3 / 5 年）", "终值高于普通定投的比例约 45%（基本一半一半）；<b>回撤更小的比例 100%</b>"],
    ["安慰剂（目标仓位序列随机错位 200 次）", "随机择时平均比普通定投少 16%，真实规则只少 1%，200 次中没有一次比它好（p &lt; 0.01）：择时信息是真的"],
    ["参数", "公式沿用上一版事先写死的 γ=2、±10 个百分点，未针对定投重新调整"],
], [62 * mm, 108 * mm], wrap=True, left_cols=(1,)))

# ---------- 第 4 页 ----------
story.append(PageBreak())
story.append(P("八、我测过但不推荐的做法：只按估值调整每日金额", "h1"))
story.append(P("最直观的「智能定投」是：便宜时每天多投（最多 3 倍），贵时少投或不投，<b>只买不卖</b>。我事先写好规则跑了一次，结果如下："))
story.append(grid([
    ["方案", "期末资产 / 投入", "平均成本", "结论"],
    ["普通每日定投", "1.82", "3605", "基准"],
    ["估值加权定投（无陷阱修正）", "1.76", "3644", "更差"],
    ["估值加权定投（陷阱修正）", "1.71", "3583", "成本只低 0.6%，终值更差"],
], [62 * mm, 32 * mm, 26 * mm, 50 * mm], wrap=True, left_cols=(0, 3)))
story.append(Spacer(1, 2 * mm))
story.append(P("在 180 组参数中，只有 35% 跑赢普通定投；安慰剂检验 p = 0.37，说明和随机调整金额没有区别。原因有两个："
               "① 沪深300 的估值波动范围有限，每日金额只在 0.6 到 1.8 倍之间变化，均价能降的幅度很小；"
               "② 贵的时候钱积在手里，长期没投出去，在上涨的市场里反而吃亏。"
               "<b>均值回归的收益主要来自「高估时卖出」，只买不卖拿不到</b>。所以本手册采用了带止盈的目标仓位法。"))

story.append(P("九、关于「定投拉低均价」", "h1"))
story.append(P("普通定投的平均成本（调和平均）在数学上总是不高于期间平均价格，但这<b>不等于多赚钱</b>，"
               "因为跌的时候你买得多，持有的份额也承受了后续的涨跌。定投真正的价值是分散买入时点、让你坚持下去。"
               "本方案在此基础上加了一条纪律：<b>贵了就把一部分兑现到备用金，跌下来再用备用金买回</b>。"
               "这样做的效果不是多赚，而是回撤减半，坚持起来更容易。"))

story.append(P("十、局限与风险", "h1"))
for s in [
    "终值<b>和普通定投持平，并不更高</b>。在单边牛市中会因为止盈而跑输。",
    "价值陷阱修正只能识别「盈利已经开始下滑」，无法预测盈利会突然崩溃；修正本身也会少赚一点。",
    "数据只有约 14 年；E 是用点位 ÷ PE 反推出来的，指数成分股调整会带来噪声。",
    "备用金按 10 年国债票息计息；实际用货币基金收益更低，用长债则有价格波动。",
    "止盈卖出在非税收优惠账户中可能涉及费用（A 股 ETF 目前免印花税和资本利得税，但有佣金）。",
]:
    story.append(P("• " + s)); story.append(Spacer(1, 1.2 * mm))
story.append(Spacer(1, 2 * mm))
story.append(P("复现：dca_target.py（本方案），smart_dca.py（第八节的反例），erp_merton.py（目标仓位公式）。本文不构成投资建议。", "small"))

SimpleDocTemplate("沪深300_每日定投策略.pdf", pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                  topMargin=15 * mm, bottomMargin=18 * mm, title="沪深300 每日定投策略").build(
    story, onFirstPage=footer, onLaterPages=footer)
print("ok")
