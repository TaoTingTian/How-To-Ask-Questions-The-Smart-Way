"""由 results/summary.json + results/extra.json 生成自包含的可视化报告 report.html（无外部脚本依赖）。"""
import json
import os
import html

HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "results", "summary.json")))
X = json.load(open(os.path.join(HERE, "results", "extra.json")))
R = json.load(open(os.path.join(HERE, "results", "drift_study.json")))
VERS = ["1.6", "1.7", "1.8", "1.9"]
VCOL = {"1.6": "var(--v16)", "1.7": "var(--v17)", "1.8": "var(--v18)", "1.9": "var(--v19)", "bh": "var(--bh)", "dca": "var(--dca)"}
KIND_CN = {"base": "基准震荡", "slow_up": "缓慢上移", "slow_down": "缓慢下移", "jump_up": "快速跳升",
           "jump_down": "快速跳降", "cycle": "强周期", "bubble": "泡沫崩盘", "stagnation": "长停滞",
           "fake_reversion": "高频假回归", "mixed": "混合极端"}
KINDS = list(KIND_CN)
OM, OC = S["overall_main"], S["overall_mc"]


def key(v):
    return f"{v}|net|{'rev' if v != '1.6' else 'norev'}"


def pc(x, d=2):
    return "—" if x is None else f"{x * 100:.{d}f}%"


def pp(x, d=2, sign=True):
    if x is None:
        return "—"
    return f"{x * 100:+.{d}f}" if sign else f"{x * 100:.{d}f}"


def neg(x, d=2):
    """把负的超额写成“跑输 N”里的正数 N。"""
    return "—" if x is None else f"{abs(x) * 100:.{d}f}"


def num(x, d=0):
    return "—" if x is None else f"{x:,.{d}f}"


def days(s):
    if s is None or s.get("median") is None:
        return "—"
    return f"{s['median']:.0f}"


def esc(s):
    return html.escape(str(s))


def heat(v, scale):
    """红涨绿跌：正值红、负值绿，强度按 |v|/scale。"""
    if v is None:
        return ""
    a = max(-1.0, min(1.0, v / scale))
    pct = int(abs(a) * 38)
    col = "var(--pos)" if a > 0 else "var(--neg)"
    return f' style="background:color-mix(in oklab, {col} {pct}%, transparent)"'


def vtag(v):
    return f'<span class="vt" style="--c:{VCOL[v]}">V{v}</span>'


def table(head, rows, cls="", note=None):
    h = "".join(f"<th>{c}</th>" for c in head)
    body = "".join("<tr>" + "".join(c if c.startswith("<td") or c.startswith("<th") else f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    n = f'<p class="tnote">{note}</p>' if note else ""
    return f'<div class="tw"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>{n}'


def callout(title, body, kind="key"):
    return f'<div class="callout {kind}"><div class="ct">{title}</div><div class="cb">{body}</div></div>'


def chart(cid, title, sub="", h=260):
    s = f'<p class="csub">{sub}</p>' if sub else ""
    return f'<figure class="fig"><figcaption><span class="ctitle">{title}</span>{s}</figcaption><div class="chart" id="{cid}" style="height:{h}px"></div></figure>'


# ============================================================ 数据（给前端图表）
series = {}
for no, ser in S["series"].items():
    k = 2
    sd = {kk: (vv[::k] if isinstance(vv, list) else vv) for kk, vv in ser.items()}
    series[no] = sd
ov_js = [dict(no=o["no"], name=o["name"], events=[e for e in o["events"] if e["type"] in ("crisis", "bubble")],
              traps=o["trap_list"], drift=o["drift"]) for o in S["overview"]]
G = S["grid"]
_me = {}
for _f in ("pe", "roe", "p", "y"):
    _lv = list(R["main_effects"][_f].keys())
    _me[_f] = dict(levels=_lv, **{v: [R["main_effects"][_f][l][v] for l in _lv] for v in VERS})
DATA_DRIFT = dict(scen=[dict(key=x["key"], name=x["name"], series=x.get("series")) for x in R["scen"]], me=_me)
DATA = dict(series=series, ov=ov_js, drift=DATA_DRIFT,
            bars_overall=dict(cats=[f"V{v}" for v in VERS] + ["买入持有", "定额定投"],
                              gross=[OM[v + "|gross"]["xirr"]["mean"] for v in VERS] + [OM["1.6|gross"]["xirr_bh"]["mean"], OM["1.6|gross"]["xirr_dca"]["mean"]],
                              net=[OM[v + "|net"]["xirr"]["mean"] for v in VERS] + [OM["1.6|net"]["xirr_bh"]["mean"], OM["1.6|net"]["xirr_dca"]["mean"]],
                              mc=[OC[v + "|net"]["xirr"]["mean"] for v in VERS] + [OC["1.6|net"]["xirr_bh"]["mean"], OC["1.6|net"]["xirr_dca"]["mean"]]),
            mdd=dict(cats=[f"V{v}" for v in VERS] + ["买入持有"],
                     main=[OM[v + "|net"]["mdd"]["mean"] for v in VERS] + [OM["1.6|net"]["mdd_bh"]["mean"]],
                     mc=[OC[v + "|net"]["mdd"]["mean"] for v in VERS] + [OC["1.6|net"]["mdd_bh"]["mean"]]),
            quad=dict(cats=["基准震荡", "缓慢上移", "快速跳升", "缓慢下移", "快速跳降"],
                      **{v: [S["quad"][k][v]["ex"] for k in ("base", "slow_up", "jump_up", "slow_down", "jump_down")] for v in VERS}),
            trap=dict(cats=["上升趋势·假回落", "下降趋势·假反弹"],
                      **{v: [S["traps_all"][f"{v}|up"]["prob"], S["traps_all"][f"{v}|down"]["prob"]] for v in VERS}),
            oat={k: dict(levels=G["1.6"]["oat"][k]["levels"], **{v: G[v]["oat"][k]["vals"] for v in VERS}) for k in ("SL", "RB", "TH", "FL")},
            mcw=dict(cats=["单周期", "双周期", "三周期共振", "短+中", "中+长", "短+长"],
                     prec=[S["multicycle"][f"both|{n}|全部"]["prec_day"] for n in ("单周期(任一)", "双周期(任两)", "三周期共振", "短+中", "中+长", "短+长")],
                     fpr=[S["multicycle"][f"both|{n}|全部"]["fpr"] for n in ("单周期(任一)", "双周期(任两)", "三周期共振", "短+中", "中+长", "短+长")],
                     miss=[S["multicycle"][f"both|{n}|全部"]["miss"] for n in ("单周期(任一)", "双周期(任两)", "三周期共振", "短+中", "中+长", "短+长")]),
            resp=dict(cats=["一级", "二级", "三级", "分级组合"],
                      all=[sum(S["warn_hold"][f"{v}|{s}|全部"]["d"]["mean"] for v in VERS) / 4 for s in ("L1", "L2", "L3", "graded")],
                      slow=[sum(S["warn_hold"][f"{v}|{s}|slow_up"]["d"]["mean"] for v in VERS) / 4 for s in ("L1", "L2", "L3", "graded")]),
            )

DRS = {x["key"]: x for x in R["scen"]}
# ============================================================ 常用数字
net_main = {v: OM[v + "|net"]["xirr"]["mean"] for v in VERS}
net_mc = {v: OC[v + "|net"]["xirr"]["mean"] for v in VERS}
ex_main = {v: OM[v + "|net"]["ex_bh"]["mean"] for v in VERS}
exg_main = {v: OM[v + "|gross"]["ex_bh"]["mean"] for v in VERS}
mdd_main = {v: OM[v + "|net"]["mdd"]["mean"] for v in VERS}
bh_net, bh_mdd = OM["1.6|net"]["xirr_bh"]["mean"], OM["1.6|net"]["mdd_bh"]["mean"]
bh_mc = OC["1.6|net"]["xirr_bh"]["mean"]
CS = S["cost_struct"]
P = X["paired"]
T = S["traps_all"]
C, B = S["crisis"], S["bubble"]
Q = S["quad"]
DR = S["drift"]
HV = S["highvol"]
MCW = S["multicycle"]
SEC = S["sec10"]
WH, WR = S["warn_hold"], S["warn_resp"]
n_main_traps = sum(o["traps_up"] + o["traps_down"] for o in S["overview"])
n_main_crisis = sum(o["n_crisis"] for o in S["overview"])

parts = []
A = parts.append

# ============================================================ 头部 + 结论速览
loss_cost = sum(CS[v]["loss_xirr"] for v in VERS) / 4
A(f"""
<header class="cover">
  <p class="eyebrow">沪深300 估值策略 · 全场景压力测试 · 合成数据回测</p>
  <h1>V1.6 – V1.9 四版策略，放进 410 条 30 年行情里跑一遍</h1>
  <p class="lede">按《全场景压力测试回测提示词》逐项执行：10 条规范路径（训练 / 测试 / 复核）、300 条蒙特卡洛复核路径、100 条留出验证路径；
  四版策略逐日执行原文规则，叠加申赎费、佣金滑点与冲击成本；专项检验中枢漂移速度、假回归陷阱、极端压力、参数鲁棒性与多周期共振预警。</p>
  <dl class="meta">
    <div><dt>单条路径</dt><dd>30 年 · 7,560 交易日（前 8 年预热，回测 22 年）</dd></div>
    <div><dt>回测次数</dt><dd>约 4.9 万次逐日回测</dd></div>
    <div><dt>口径</dt><dd>毛 = 不计任何成本；净 = 申赎费 + 佣金滑点 + 冲击成本</dd></div>
    <div><dt>生成日期</dt><dd>2026-10-14</dd></div>
  </dl>
</header>
""")

A(f"""
<section id="tldr" class="tldr">
<h2 class="h2s">结论速览</h2>
<ol class="findings">
<li><b>收益排序 V1.7 &gt; V1.9 ≈ V1.8 &gt; V1.6，但差距不大。</b>10 条主路径净年化 XIRR：{" / ".join(f"V{v} {pc(net_main[v])}" for v in VERS)}，买入持有 {pc(bh_net)}。
300 条复核路径上 V1.7 比 V1.6 高 {pp(P['1.7-1.6']['mean'])} 个百分点（标准误 {pp(P['1.7-1.6']['se'], sign=False)}），V1.9 比 V1.8 只高 {pp(P['1.9-1.8']['mean'])}，在 2 个标准误以内。</li>
<li><b>四版的真正价值在“少亏”，不在“多赚”。</b>扣全口径成本后，相对买入持有的年化超额只有 {pp(min(ex_main.values()))} ~ {pp(max(ex_main.values()))} 个百分点；但最大回撤 {pc(min(mdd_main.values()),1)} ~ {pc(max(mdd_main.values()),1)}，比买入持有的 {pc(bh_mdd,1)} 低 11 ~ 16 个百分点。危机后净值修复中位数 {min(C[v]['repair']['median'] for v in VERS):.0f} ~ {max(C[v]['repair']['median'] for v in VERS):.0f} 天，买入持有 {days(C['bh']['repair'])} 天。</li>
<li><b>交易成本每年吃掉约 {pp(loss_cost, sign=False)} 个百分点，其中近九成是冲击成本。</b>冲击成本 = 0.5 × ATR/收盘价，单笔约 0.8%（高波动日约 1.7%），一半以上发生在波动最高的 20% 交易日。换手率与成本占比相关系数 {S['turnover_cost_corr']:.2f}。</li>
<li><b>缓慢上移的中枢是四版共同的最大敌人。</b>缓慢上移场景年化跑输买入持有 {neg(Q['slow_up']['1.7']['ex'])} ~ {neg(Q['slow_up']['1.6']['ex'])} 个百分点，快速跳升只跑输 {neg(Q['jump_up']['1.7']['ex'])} ~ {neg(Q['jump_up']['1.6']['ex'])}；中枢下移（无论快慢）反而跑赢。</li>
<li><b>假回归陷阱整体并不伤人，伤人的是陷阱里的“卖出”。</b>四版在假回归窗口内的交易合计是正贡献；亏损集中在“上升趋势假回落”时触发的卖出（卖出亏损率 {pc(T['1.7|up']['sell_loss_rate'],0)} ~ {pc(T['1.6|up']['sell_loss_rate'],0)}）。V1.6 的趋势分最少踩雷（触发概率 {pc(T['1.6|all']['prob'],0)}），V1.7 的周线信号在上升趋势陷阱里触发概率高达 {pc(T['1.7|up']['prob'],0)}。</li>
<li><b>多周期共振：共振越多越准、越少误报，但也越晚、越容易漏。</b>单周期 → 双周期 → 三周期：准确率 {pc(MCW['both|单周期(任一)|全部']['prec_day'],0)} → {pc(MCW['both|双周期(任两)|全部']['prec_day'],0)} → {pc(MCW['both|三周期共振|全部']['prec_day'],0)}，假阳性率 {pc(MCW['both|单周期(任一)|全部']['fpr'],0)} → {pc(MCW['both|双周期(任两)|全部']['fpr'],0)} → {pc(MCW['both|三周期共振|全部']['fpr'],1)}，漏警率 {pc(MCW['both|单周期(任一)|全部']['miss'],0)} → {pc(MCW['both|双周期(任两)|全部']['miss'],0)} → {pc(MCW['both|三周期共振|全部']['miss'],0)}。</li>
<li><b>最优应对：只自动执行一级（温和调线），二、三级只用于触发人工复核。</b>留出验证集上，一级应对平均 {pp(DATA['resp']['all'][0])} 个百分点且回撤减少约 2 个百分点；二级、三级与分级组合平均 {pp(DATA['resp']['all'][1])} / {pp(DATA['resp']['all'][2])} / {pp(DATA['resp']['all'][3])}，只有缓慢上移场景受益。</li>
<li><b>中枢漂移专项：真正决定策略成败的是 PE 中枢本身动没动。</b>在 73 组经济上自洽的“各指标中枢各走各的”组合里，PE 中枢每上移约 20%，四版年化超额平均少 {abs(R['reg']['avg']['pe'])*100:.2f} 个百分点；ROE、分红率、利率在 PE 中枢不变时只把估值分 V 拉偏 1–2 点，对收益影响 ≤ 0.4 个百分点。沪深300 2015–2026 型（降息被盈利下滑对冲）让 V 平均偏低约 {abs(DRS['C1']['dV']['orig']):.1f} 点：策略仓位更重，超额略增、回撤加深约 2 个百分点。</li>
</ol>
</section>
""")

# ============================================================ 读前须知
A(f"""
<section id="glossary">
<h2 class="h2s">先看懂 6 个词</h2>
<div class="gloss">
<div><b>估值分 V</b><span>0~100，当前估值在过去 5~10 年里的位置。越高越贵。V&gt;70 进入止盈区，V&lt;50 进入回投区。</span></div>
<div><b>估值中枢</b><span>市场长期“认可”的合理 PE。中枢可以慢慢漂（缓慢漂移），也可以几个月内跳一级（快速跳变）。</span></div>
<div><b>XIRR</b><span>考虑每笔定投入金时间的年化收益率。四版入金规则相同，XIRR 可直接横比。</span></div>
<div><b>最大回撤</b><span>按时间加权净值算，从高点到低点最多亏了多少。衡量“最难熬的时候有多难熬”。</span></div>
<div><b>假回归陷阱</b><span>估值从极端位置回到中枢附近（±0.2σ 内、停留 ≤10 天），随后又沿原方向偏离 ≥1σ。看起来“回归了”，其实没有。</span></div>
<div><b>冲击成本</b><span>大额成交推动价格造成的隐性损失，按 成交额 × 0.5 × 当日 ATR / 收盘价 计提，波动越大越贵。</span></div>
</div>
<p class="note">颜色约定：表格按 A 股习惯 <span class="chip pos">红 = 正 / 占优</span> <span class="chip neg">绿 = 负 / 落后</span>，数字始终同时标出。版本颜色固定：{vtag('1.6')} {vtag('1.7')} {vtag('1.8')} {vtag('1.9')} <span class="vt" style="--c:var(--bh)">买入持有</span></p>
</section>
""")

# ============================================================ 1. 模拟数据概览
rows = []
for o in S["overview"]:
    st = o["stats"]
    dr = "、".join(("缓慢" if d["type"] == "slow" else "跳变") + ("↑" if d["dir"] > 0 else "↓") for d in o["drift"]) or "无"
    rows.append([f'<td class="l">{o["no"]}. {esc(o["name"])}</td>', o["set"], dr, pc(st["ann_tr_bt"], 1), pc(st["vol"], 1), pc(st["mdd"], 0),
                 f'{st["pe_min"]:.1f}–{st["pe_max"]:.1f}', pp(st["center_chg"], 0) + "%", f'{st["V_mean"]:.0f}', pc(st["V_hi"], 0),
                 f'{o["n_crisis"]}' + (" + 泡沫" if o["n_bubble"] else ""), f'{o["traps_up"]} / {o["traps_down"]}', str(st["fail_days"])])
tbl_paths = table(["路径", "数据集", "中枢漂移", "回测期全收益年化", "年化波动", "价格最大跌幅", "PE 区间", "中枢累计变化", "V 均值", "V&gt;70 占比", "回测期危机", "假回归 上/下", "数据验证失败日"], rows, "num")
A(f"""
<section id="s1">
<h2><span class="sn">1</span>模拟数据概览</h2>
<p>先说清楚“考场”长什么样。每条路径是 30 年日度行情：<b>价格 = PE × 每股盈利</b>，PE 围绕“估值中枢”均值回归；PB = PE × ROE，股息率 = 分红率 / PE，10 年国债收益率与政策联动（危机后宽松下行、过热时收紧上行），中枢上移时收益率同步下行、ROE 永久抬升。前 8 年用于预热估值分 V（需 5 年 ROE 均值 + 3 年分位样本），有效回测 22 年。每条路径还随机设置 0.3% 的交易日“数据验证不通过”，按文档规则暂停当日止盈与回投。</p>
<div class="grid2">
<div>
<h3>每条路径都嵌入了什么</h3>
<ul class="tight">
<li><b>大型危机</b>：每 7–10 年一次，估值从高点下跌 35%–55%（叠加盈利下修后，价格最大跌幅约 {pc(C['drop']['mean'],0)}），前置一年过热；危机前后波动率放大 2–3 倍。</li>
<li><b>中型回调</b>：每 3–4 年一次，跌 15%–25%。</li>
<li><b>假回归陷阱</b>：每段危机前的过热（上升趋势）嵌入一次“假回落”，每段崩盘（下降趋势）嵌入一次“假反弹”；路径 9 额外交替嵌入独立陷阱。所有陷阱都按定义在实际生成的偏离序列上<b>重新识别并打标签</b>，不满足定义的种子会被丢弃重生成。</li>
<li><b>中枢漂移</b>：缓慢型年均 5%（蒙特卡洛 3%–8% 随机）持续 20 年以上；跳变型 1–3 个月内跳 20%（蒙特卡洛 15%–30%），两次跳变间隔 ≥ 3 年。</li>
</ul>
</div>
<div>
<h3>数据集划分</h3>
<ul class="tight">
<li><b>训练集 4 条</b>：1 基准震荡、2 缓慢上移、4 快速跳升、6 强周期，用于复现原始参数表现、做参数寻优。</li>
<li><b>测试集 3 条</b>：3 缓慢下移、5 快速跳降、7 泡沫崩盘（样本外极端：V≥90 后 3 个月跌超 50%）。</li>
<li><b>复核集 3 条</b>：8 长停滞、9 高频假回归、10 混合极端，独立随机种子。</li>
<li><b>扩展</b>：10 类 × 30 = 300 条蒙特卡洛路径做稳健性统计；方案定型后再生成 100 条<b>留出验证</b>路径，只用于检验预警应对方案。</li>
</ul>
</div>
</div>
<p>10 条主路径的中枢漂移类型：无漂移 4 条（1、6、7、9），缓慢漂移 3 条（2、3、8），快速跳变 2 条（4、5），复合 1 条（10）。回测期内共 {n_main_crisis} 次大型危机、1 次泡沫崩盘、{n_main_traps} 个假回归陷阱（上升趋势 {sum(o['traps_up'] for o in S['overview'])} 个、下降趋势 {sum(o['traps_down'] for o in S['overview'])} 个）。全部 310 条路径合计 {S['n_traps_total']:,} 个陷阱、{S['n_crises_total']} 次危机。</p>
{tbl_paths}
<h3>路径浏览器</h3>
<p class="muted">选择一条路径，查看估值与中枢、估值分 V、四版策略（净成本）与买入持有的净值。竖线 = 危机 / 泡沫高点，圆点 = 假回归触碰中枢的日子（红：上升趋势假回落，绿：下降趋势假反弹）。</p>
<div class="seg" role="group" aria-label="选择路径" id="pathsel"></div>
<div class="explorer">
{chart('c_pe', '估值 PE 与估值中枢', '实线 = PE(TTM)，虚线 = 真实中枢（策略看不到）', 230)}
{chart('c_v', '估值分 V', '灰色区域为 8 年预热期；70 以上止盈区，50 以下回投区', 200)}
{chart('c_nav', '净值（时间加权，扣全口径成本，对数刻度）', '起点 = 1，回测首日', 260)}
{chart('c_p', '持仓占比 p', '其余为资金池现金', 180)}
</div>
</section>
""")

# ============================================================ 2. 全周期总览
mets = [("期末总财富（万元）", "final", lambda s: num(s / 1e4, 1)), ("年化 XIRR", "xirr", pc), ("超额 vs 买入持有", "ex_bh", lambda x: pp(x) + " pp"),
        ("超额 vs 定额定投", "ex_dca", lambda x: pp(x) + " pp"), ("最大回撤", "mdd", lambda x: pc(x, 1)),
        ("最长回撤修复（交易日）", "uw_days", lambda x: num(x)), ("下行波动率", "down_vol", lambda x: pc(x, 1)),
        ("索提诺比率", "sortino", lambda x: f"{x:.2f}"), ("夏普比率", "sharpe", lambda x: f"{x:.2f}"), ("卡玛比率", "calmar", lambda x: f"{x:.2f}"),
        ("总成本 / 期末资产", "cost_ratio", lambda x: pc(x, 2)), ("年换手率", "turnover", lambda x: f"{x:.2f}"),
        ("止盈次数", "n_sell", lambda x: num(x, 1)), ("回投次数", "n_rebuy", lambda x: num(x, 1)),
        ("平均卖出价 / 回投价 − 1", "spread", lambda x: pc(x, 1)), ("资金池闲置占比", "pool_idle", lambda x: pc(x, 0))]
rows = []
for lab, m, fm in mets:
    for c in (("net", "gross") if m in ("xirr", "ex_bh", "ex_dca", "sharpe", "final") else ("net",)):
        r = [f'<td class="l">{lab}{"（净）" if c == "net" and m in ("xirr","ex_bh","ex_dca","sharpe","final") else ("（毛）" if c == "gross" else "")}</td>']
        vals = [OM[f"{v}|{c}"][m] for v in VERS]
        best = None
        if m in ("xirr", "ex_bh", "ex_dca", "sortino", "sharpe", "calmar", "final", "spread"):
            best = max(range(4), key=lambda i: vals[i]["mean"])
        elif m in ("mdd", "uw_days", "down_vol", "cost_ratio"):
            best = min(range(4), key=lambda i: vals[i]["mean"])
        for i, s in enumerate(vals):
            cell = f'{fm(s["mean"])}<small>中位 {fm(s["median"])} · σ {fm(s["std"]).replace(" pp","")}</small>'
            r.append(f'<td class="{"best" if i == best else ""}">{cell}</td>')
        rows.append(r)
tbl_overall = table(["指标（10 条主路径均值）"] + [vtag(v) for v in VERS], rows, "num big",
                    note="每格：均值，下方为中位数与标准差。加粗 = 该行最优。买入持有：净 XIRR " + pc(bh_net) + "，最大回撤 " + pc(bh_mdd, 1) + "；定额定投净 XIRR " + pc(OM['1.6|net']['xirr_dca']['mean']) + "。")

rows = []
for p in S["per_path"]:
    r = [f'<td class="l">{p["no"]}. {esc(p["name"])}</td>', p["set"]]
    for v in VERS:
        d = p[v]["net"] - p["bh"]
        r.append(f'<td{heat(d, 0.04)}>{pc(p[v]["net"])}<small>{pp(d)} · 回撤 {pc(p[v]["mdd"],0)}</small></td>')
    r.append(f'<td>{pc(p["bh"])}<small>回撤 {pc(p["mdd_bh"],0)}</small></td>')
    r.append(pc(p["dca"]))
    rows.append(r)
tbl_pp = table(["路径", "数据集"] + [vtag(v) for v in VERS] + ["买入持有", "定额定投"], rows, "num",
               note="单元格：净 XIRR；下方为相对买入持有的超额（百分点）与最大回撤。底色深浅 = 超额大小。")

rows = []
for sn in ("训练集", "测试集", "复核集"):
    ss = S["sets"][sn]
    rows.append([f'<td class="l">{sn}（{ss["n"]} 条）</td>'] + [f'<td{heat(ss[v]["ex"], 0.02)}>{pc(ss[v]["net"])}<small>{pp(ss[v]["ex"])} pp</small></td>' for v in VERS])
rows.append(['<td class="l">蒙特卡洛 300 条</td>'] + [f'<td{heat(OC[v+"|net"]["ex_bh"]["mean"], 0.02)}>{pc(net_mc[v])}<small>{pp(OC[v+"|net"]["ex_bh"]["mean"])} pp</small></td>' for v in VERS])
tbl_sets = table(["数据集"] + [vtag(v) for v in VERS], rows, "num")

rows = []
for a in VERS:
    r = [f'<td class="l">{vtag(a)} 胜过 →</td>']
    for b in VERS:
        r.append("<td>—</td>" if a == b else f'<td{heat(S["winrate"][f"{a}>{b}"] - 0.5, 0.25)}>{pc(S["winrate"][f"{a}>{b}"], 0)}</td>')
    rows.append(r)
tbl_win = table([""] + [vtag(v) for v in VERS], rows, "num", note="300 条蒙特卡洛路径中，行版本净 XIRR 高于列版本的路径占比。")

cost_bar = ""
for v in VERS:
    c = CS[v]
    cost_bar += f'''<div class="sbar"><span class="sl">{vtag(v)}</span><div class="track">
<i style="width:{c['fee']*100:.1f}%;background:var(--c-fee)" title="申赎费 {pc(c['fee'],1)}"></i><i style="width:{c['comm']*100:.1f}%;background:var(--c-comm)" title="佣金滑点 {pc(c['comm'],1)}"></i><i style="width:{c['imp']*100:.1f}%;background:var(--c-imp)" title="冲击成本 {pc(c['imp'],1)}"></i></div>
<span class="sv">申赎 {pc(c['fee'],1)} · 佣金 {pc(c['comm'],1)} · 冲击 {pc(c['imp'],1)}</span></div>'''
rows = []
for v in VERS:
    c = CS[v]
    rows.append([vtag(v), pc(OM[v + "|net"]["cost_ratio"]["mean"]), pp(c["loss_xirr"]).replace("+", "−") + " pp", pp(c["loss_xirr_mc"]).replace("+", "−") + " pp",
                 pc(c["kind"]["sell"], 0), pc(c["kind"]["rebuy"], 0), pc(c["kind"]["dca"], 0), f'{OM[v + "|net"]["turnover"]["mean"]:.2f}'])
tbl_cost = table(["版本", "总成本 / 期末资产", "XIRR 损耗（主路径）", "XIRR 损耗（MC）", "来自止盈卖出", "来自回投", "来自日常定投", "年换手率"], rows, "num")

rows = []
for v in ["1.7", "1.8", "1.9"]:
    g = S["review_gain"][v]
    rows.append([vtag(v), pp(g["main"]["mean"]) + " pp", f'{pp(g["mc_all"]["mean"])} ± {pp(g["mc_all"]["se"], sign=False)}',
                 pp(g["mc_type"]["slow_up"]["mean"]), pp(g["mc_type"]["jump_up"]["mean"]), pp(g["mc_type"]["mixed"]["mean"]), pp(g["mdd"]["mean"]) + " pp"])
tbl_rev = table(["版本", "主路径（10 条）", "MC 全部（±标准误）", "MC 缓慢上移", "MC 快速跳升", "MC 混合极端", "回撤变化"], rows, "num",
                note="复核增益 = 启用第十节人工复核流程（按文档复核内容自动化判断）− 不启用复核的对照组，单位：净 XIRR 百分点。")

A(f"""
<section id="s2">
<h2><span class="sn">2</span>全周期回测总览</h2>
{callout("一句话", f"扣掉全部成本后，四版都只比买入持有多赚一点点甚至略少（{pp(min(ex_main.values()))} ~ {pp(max(ex_main.values()))} 个百分点 / 年），但回撤普遍少 11–16 个百分点。V1.7 收益最高、回撤最大；V1.6 回撤最小、收益最低；V1.8、V1.9 夹在中间。")}
<div class="grid2">
{chart('c_xirr', '年化 XIRR：毛 vs 净', '10 条主路径均值；毛 = 不计任何成本', 250)}
{chart('c_mdd', '最大回撤', '10 条主路径均值 vs 300 条蒙特卡洛均值', 250)}
</div>
<h3>综合绩效对比表（毛 / 净双口径）</h3>
{tbl_overall}
<h3>成本损耗：钱被谁吃掉了</h3>
<p>四版的成本结构几乎一样：<b>冲击成本占 88%–90%</b>，佣金滑点约 7%，法定申赎费约 4%–5%（规则本身已避开 30 天内赎回，≥180 天赎回免费）。按交易类型看，止盈卖出与回投各占一半左右，日常定投仅约 4%——小额定投金额小，冲击成本也小。成本让净 XIRR 比毛 XIRR 低 0.67–0.74 个百分点；换手率越高，成本占比越高（相关系数 {S['turnover_cost_corr']:.2f}）。</p>
<div class="sbars">{cost_bar}<div class="slegend"><span><i style="background:var(--c-fee)"></i>法定申赎费</span><span><i style="background:var(--c-comm)"></i>佣金 + 滑点</span><span><i style="background:var(--c-imp)"></i>冲击成本</span></div></div>
{tbl_cost}
<h3>逐路径净收益</h3>
{tbl_pp}
<div class="grid2">
<div><h3>按数据集</h3>{tbl_sets}<p class="tnote">单元格：净 XIRR；下方为相对买入持有的超额。复核集（长停滞、高频假回归、混合极端）四版都跑输买入持有。</p></div>
<div><h3>两两胜率（蒙特卡洛）</h3>{tbl_win}</div>
</div>
<h3>第十节人工复核的增益</h3>
<p>复核流程按文档内容自动化：触发后暂停止盈 20 个交易日，第 20 日判断“10 年国债较 t0 下降 ≥50bp 且持续 1 年以上”或“ROE 5 年均值较 t0 上升 ≥5%”，任一成立即判定中枢上移，用可用资金池 50% 申购并停止本轮止盈。结果：复核对整体收益影响很小，只在缓慢上移场景略有正贡献，在快速跳升和混合场景略为负。</p>
{tbl_rev}
</section>
""")

# ============================================================ 3. 中枢漂移速度
rows = []
for k, lab in (("base", "基准震荡（对照）"), ("slow_up", "缓慢上移"), ("jump_up", "快速跳升"), ("slow_down", "缓慢下移"), ("jump_down", "快速跳降")):
    q = Q[k]
    r = [f'<td class="l">{lab}<small>{q["1.6"]["n"]} 条</small></td>']
    for v in VERS:
        r.append(f'<td{heat(q[v]["ex"], 0.04)}>{pp(q[v]["ex"])}<small>XIRR {pc(q[v]["xirr"])} · 回撤 {pc(q[v]["mdd"],0)}</small></td>')
    r.append(f'<td>{pc(q["bh"]["xirr"])}<small>回撤 {pc(q["bh"]["mdd"],0)}</small></td>')
    rows.append(r)
tbl_quad = table(["场景（主路径 + MC）"] + [vtag(v) for v in VERS] + ["买入持有"], rows, "num",
                 note="单元格：相对买入持有的年化超额（百分点），下方为净 XIRR 与最大回撤。")
rows = []
for v in VERS:
    du = Q["slow_up"][v]["xirr"] - Q["jump_up"][v]["xirr"]
    dd = Q["slow_down"][v]["xirr"] - Q["jump_down"][v]["xirr"]
    mu = Q["slow_up"][v]["mdd"] - Q["jump_up"][v]["mdd"]
    md = Q["slow_down"][v]["mdd"] - Q["jump_down"][v]["mdd"]
    rows.append([vtag(v), f'<td{heat(du,0.03)}>{pp(du)}</td>', pp(mu), f'<td{heat(dd,0.03)}>{pp(dd)}</td>', pp(md)])
tbl_speed = table(["版本", "上移：慢 − 快 年化收益差", "上移：慢 − 快 最大回撤差", "下移：慢 − 快 年化收益差", "下移：慢 − 快 最大回撤差"], rows, "num",
                  note="单位：百分点。负的收益差 = 缓慢漂移比快速跳变更伤收益。")
rows = []
for key2, lab in (("slow_up", "缓慢上移"), ("jump_up", "快速跳升"), ("slow_down", "缓慢下移"), ("jump_down", "快速跳降")):
    d = DR[key2]
    r = [f'<td class="l">{lab}<small>{d["n"]} 次</small></td>', days(d["v_left"]), days(d["v_back"])]
    for v in VERS:
        x = d[v]
        tr = "—" if v == "1.6" else (days(x["first_trigger"]) + f'<small>触发率 {pc(x["trigger_rate"],0)}</small>')
        r.append(f'<td>{pp(x["slope"]["median"])}%/年<small>3 年 {pp(x["loss3"]["median"])}% · 复核 {tr if v != "1.6" else "无第十节"}</small></td>')
    rows.append(r)
tbl_lag = table(["漂移事件", "V 偏离正常带（天）", "V 回到正常带（天）"] + [vtag(v) for v in VERS], rows, "num",
                note="V 正常带 = 120 日均值在 35–65 之间，天数为距漂移开始的交易日中位数。版本格：相对买入持有的收益衰减速率（漂移期内对数超额收益的线性斜率），下方为 3 年累计超额与第十节首次触发天数中位数。")
A(f"""
<section id="s3">
<h2><span class="sn">3</span>中枢漂移速度专项：慢慢漂 vs 突然跳</h2>
{callout("一句话", f"<b>缓慢上移破坏性最强。</b>中枢每年悄悄抬 3%–8%，V 长期停在高位，资金池卖出后就再也等不到 V&lt;50 的回投机会：四版年化跑输买入持有 {neg(Q['slow_up']['1.7']['ex'])} ~ {neg(Q['slow_up']['1.6']['ex'])} 个百分点。快速跳升只跑输 {neg(Q['jump_up']['1.7']['ex'])} ~ {neg(Q['jump_up']['1.6']['ex'])}，因为跳完后估值窗口约 2 年就消化掉新中枢。中枢下移（无论快慢）四版都跑赢买入持有。")}
{chart('c_quad', '四象限：相对买入持有的年化超额（净）', '每组 31 条路径（1 条主路径 + 30 条蒙特卡洛）', 270)}
{tbl_quad}
<h3>慢与快的差距</h3>
{tbl_speed}
<h3>感知滞后与收益衰减</h3>
{tbl_lag}
<div class="grid2">
<div>
<h3>为什么“慢”比“快”更致命</h3>
<ul class="tight">
<li><b>感知滞后：</b>缓慢上移开始后约 {days(DR['slow_up']['v_left'])} 天 V 就离开正常带，但要 {days(DR['slow_up']['v_back'])} 天才回来——而且回来后中枢还在继续漂，V 会再次偏高，资金池“卡死”（≥1 年无法回投）的比例为 {pc(DR['slow_up']['1.7']['stuck_rate'],0)}。</li>
<li><b>收益衰减：</b>缓慢上移期间四版每年相对买入持有衰减 {pp(DR['slow_up']['1.7']['slope']['median'])}% ~ {pp(DR['slow_up']['1.8']['slope']['median'])}%，3 年累计 {pp(DR['slow_up']['1.9']['loss3']['median'])}% ~ {pp(DR['slow_up']['1.8']['loss3']['median'])}%。</li>
<li><b>快速跳升</b>后 3 年内四版反而小幅跑赢（{pp(DR['jump_up']['1.7']['loss3']['median'])}% ~ {pp(DR['jump_up']['1.8']['loss3']['median'])}%）：跳升本身是一段大涨，策略在前半段还持有大部分仓位；损失主要来自之后资金池长期闲置。</li>
<li><b>第十节复核的触发时点：</b>缓慢上移中位 {days(DR['slow_up']['1.8']['first_trigger'])} 天（主要靠条件 A 的 3 年时长），快速跳升中位 {days(DR['jump_up']['1.9']['first_trigger'])} ~ {days(DR['jump_up']['1.7']['first_trigger'])} 天（主要靠条件 B 的 1.3 倍涨幅）。</li>
</ul>
</div>
<div>
<h3>破坏性排序（相对基准震荡场景的超额变化）</h3>
<ol class="tight rank">
<li><b>缓慢上移</b>：{pp(Q['slow_up']['1.8']['ex']-Q['base']['1.8']['ex'])} pp（V1.8）</li>
<li><b>快速跳升</b>：{pp(Q['jump_up']['1.8']['ex']-Q['base']['1.8']['ex'])} pp</li>
<li><b>快速跳降</b>：{pp(Q['jump_down']['1.8']['ex']-Q['base']['1.8']['ex'])} pp（买入持有更惨，策略相对占优）</li>
<li><b>缓慢下移</b>：{pp(Q['slow_down']['1.8']['ex']-Q['base']['1.8']['ex'])} pp（同上）</li>
</ol>
<p><b>适配性：</b>中枢上移时，止盈越晚、卖得越少的版本受伤越轻——V1.7（只在周线冲高回落后卖）在两种上移场景都是四版最好；中枢下移时，V1.6 的“下跌线”回投更慢，缓慢下移场景最好。</p>
</div>
</div>
</section>
""")

# ============================================================ 4. 假回归
rows = []
for v in VERS:
    for side, lab in (("all", "全部"), ("up", "上升趋势·假回落"), ("down", "下降趋势·假反弹")):
        x = T[f"{v}|{side}"]
        r = [vtag(v) if side == "all" else "", f'<td class="l">{lab}<small>{x["n"]} 个</small></td>', f'<td{heat(-x["prob"]+0.3,0.3)}>{pc(x["prob"],1)}</td>',
             f'{x["trades"]:.2f}', f'<td{heat(-x["loss_mean"],0.06)}>{pp(-x["loss_mean"])}%</td>',
             pc(x["loss_pos_rate"], 1), pc(x["loss_given_loss"], 2), pc(max(0, x["loss_max"]), 2),
             f'{pp(x["g_sell"])}% / {pp(x["g_buy"])}%', f'{pc(x["sell_loss_rate"],0)} / {pc(x["buy_loss_rate"],0)}',
             days(x["payback"])]
        rows.append(r)
tbl_trap = table(["版本", "陷阱类型", "触发概率", "平均交易笔数", "每次触发的平均盈亏（占账户）", "亏损陷阱占比", "亏损时平均亏损", "单次最大亏损", "卖出 / 买入 的平均盈亏", "卖出 / 买入 亏损率", "回本天数（中位）"], rows, "num",
                 note="统计窗口：触碰中枢前 20 个交易日至离开中枢后 20 个交易日；盈亏衡量到“恢复原趋势、偏离 ≥1σ”之日（至少 20 个交易日后）。卖出的盈亏 = 卖出金额 ×（卖出价 / 结算价 − 1）。正数 = 盈利。样本：全部 310 条路径、" + f"{S['n_traps_total']:,}" + " 个陷阱。")
rows = []
for v in VERS:
    im = T[f"{v}|impact"]
    rows.append([vtag(v), f'{pp(-im["mean"])}%', f'{pp(-im["median"])}%', pc(T[f"{v}|impact_pos"], 0)])
tbl_cf = table(["版本", "陷阱期交易对总收益的贡献（均值）", "中位数", "陷阱交易造成净损失的路径占比"], rows, "num",
               note="反事实对照：把所有陷阱窗口内的止盈与回投全部屏蔽、其余规则不变重跑一遍。贡献 = (实际总收益 − 屏蔽后总收益) / 屏蔽后总收益。正数 = 陷阱期交易整体赚钱。")
A(f"""
<section id="s4">
<h2><span class="sn">4</span>假回归陷阱专项</h2>
{callout("一句话", f"按提示词定义的假回归，对估值类均值回归策略<b>整体不是陷阱，而是机会</b>：估值回到中枢附近时，回投买入在“假回落”后赚到了后续上涨，止盈卖出在“假反弹”后躲过了后续下跌。真正亏钱的是<b>上升趋势假回落中触发的卖出</b>，这正是 V1.6 趋势分和 V1.7 周线信号的“误判点”。")}
{chart('c_trap', '各版本在两类陷阱中的触发概率', '陷阱窗口内至少发生一笔止盈或回投的陷阱占比', 240)}
{tbl_trap}
<h3>对总收益的影响（反事实）</h3>
{tbl_cf}
<div class="grid2">
<div>
<h3>哪类陷阱杀伤力更强</h3>
<p><b>上升趋势的假回落更危险。</b>它的触发概率是下降趋势假反弹的 1.3–10 倍（V1.7 为 {pc(T['1.7|up']['prob'],0)} vs {pc(T['1.7|down']['prob'],0)}），亏损陷阱占比也更高（V1.8 {pc(T['1.8|up']['loss_pos_rate'],0)} vs {pc(T['1.8|down']['loss_pos_rate'],0)}），单次最大亏损 {pc(T['1.9|up']['loss_max'],1)}（V1.9）。原因：估值从高位跌回中枢时，趋势分转弱、周线过热刚结束，两套规则都倾向“卖到更低的目标”，随后行情重新走高。</p>
<p>下降趋势假反弹里，止盈卖出几乎总是对的（卖出亏损率 0%–3%），亏损来自反弹中回投买入（V1.9 买入亏损率 {pc(T['1.9|down']['buy_loss_rate'],0)}，V1.6 {pc(T['1.6|down']['buy_loss_rate'],0)}）。</p>
</div>
<div>
<h3>哪类规则更能规避</h3>
<ol class="tight rank">
<li><b>V1.6 趋势分 U</b>：触发概率最低（{pc(T['1.6|all']['prob'],0)}），亏损陷阱占比仅 {pc(T['1.6|all']['loss_pos_rate'],1)}，亏损时平均只亏 {pc(T['1.6|all']['loss_given_loss'],2)}。</li>
<li><b>V1.8 / V1.9 两段式（并列）</b>：V1.8 触发更少（{pc(T['1.8|all']['prob'],0)} vs {pc(T['1.9|all']['prob'],0)}），V1.9 亏损陷阱更少（{pc(T['1.9|all']['loss_pos_rate'],0)} vs {pc(T['1.8|all']['loss_pos_rate'],0)}）但单次最大亏损最大（{pc(T['1.9|all']['loss_max'],1)}）。</li>
<li><b>V1.7 周线 S + 日线 B</b>（第 4）：下降趋势陷阱几乎不碰（{pc(T['1.7|down']['prob'],0)}），但上升趋势陷阱触发 {pc(T['1.7|up']['prob'],0)}，亏损陷阱 {pc(T['1.7|all']['loss_pos_rate'],0)}。</li>
</ol>
<p class="muted">结论：趋势分（看价格是否站上 40/80/160 日线）在假回落时更“迟钝”，反而少犯错；周线冲高回落信号对“过热结束”很敏感，正好被假回落骗到。</p>
</div>
</div>
</section>
""")

# ============================================================ 5. 极端事件
rows = []
for lab, src in (("大型危机", C), ("泡沫崩盘", B)):
    for v in VERS:
        x = src[v]
        rows.append([f'<td class="l">{lab}<small>{src["n"]} 次 · 平均跌幅 {pc(src["drop"]["mean"],0)}</small></td>' if v == "1.6" else "<td></td>", vtag(v),
                     f'<td{heat(x["escape"]-0.8,0.25)}>{pc(x["escape"],0)}</td>', f'{pc(x["p_peak"]["mean"],0)}', f'<td{heat(x["bottom"]-0.4,0.4)}>{pc(x["bottom"],0)}</td>',
                     pc(x["dd"]["mean"], 1), days(x["repair"]), pc(x["repair_cens"], 0)])
    rows.append(["<td></td>", '<span class="vt" style="--c:var(--bh)">买入持有</span>', "—", "100%", "—", pc(src["bh"]["dd"]["mean"], 1), days(src["bh"]["repair"]), pc(src["bh"]["repair_cens"], 0)])
tbl_crisis = table(["事件", "版本", "逃顶成功率", "高点时平均持仓", "抄底成功率", "事件回撤", "净值修复天数（中位）", "到期末仍未修复"], rows, "num",
                   note="逃顶成功 = 危机高点当日持仓 ≤ 60%；抄底成功 = 高点之后至低点后 126 日内，在不高于低点 1.15 倍的价格有过回投；修复天数 = 从低点到重回危机前净值高点的交易日数（未修复的不计入中位数）。")
rows = []
for k2, lab in (("jump_up", "跳升 ↑"), ("jump_down", "跳降 ↓")):
    d = DR[k2]
    for v in VERS:
        x = d[v]
        if k2 == "jump_up":
            order = [("回投估值线卡死", x["stuck"]["median"]), ("止盈估值线触发卖出", x["first_sell"]["median"]), ("估值窗口回归正常", d["v_back"]["median"])]
        else:
            order = [("回投估值线触发买入", x["first_buy"]["median"]), ("资金池耗尽", x["exhausted"]["median"]), ("估值窗口回归正常", d["v_back"]["median"])]
        order = sorted([o for o in order if o[1] is not None], key=lambda o: o[1])
        rows.append([f'<td class="l">{lab}</td>' if v == "1.6" else "<td></td>", vtag(v), f'{pp(x["loss3"]["median"])}%',
                     " → ".join(f'{o[0]}<small>{o[1]:.0f} 天</small>' for o in order)])
tbl_jump = table(["跳变", "版本", "跳变后 3 年相对买入持有", "参数失灵顺序（距跳变开始的交易日中位数）"], rows, "num l3")
rows = []
for v in VERS:
    h = HV[v]
    rows.append([vtag(v), pc(h["imp_share_hv"], 0), f'{h["imp_rate_hv"]*100:.2f}% / {h["imp_rate_lv"]*100:.2f}%', f'{pp(h["gap_hi"])} / {pp(h["gap_lo"])}',
                 f'{pp(h["exg_hi"])} → {pp(h["ex_hi"])}', f'{pp(h["exg_lo"])} → {pp(h["ex_lo"])}', f'{h["corr_turn_gap"]:.2f}'])
tbl_hv = table(["版本", "冲击成本落在最高波动 20% 交易日的比例", "单笔冲击成本率 高波动日 / 其余", "成本拖累 XIRR：高波动路径 / 低波动路径（pp）",
                "高波动路径超额：毛 → 净（pp）", "低波动路径超额：毛 → 净（pp）", "换手率与成本拖累相关"], rows, "num")
A(f"""
<section id="s5">
<h2><span class="sn">5</span>极端压力测试</h2>
{callout("一句话", f"四版在危机和泡沫里都显著优于买入持有：大型危机平均回撤 {pc(C['1.6']['dd']['mean'],0)}–{pc(C['1.7']['dd']['mean'],0)}（买入持有 {pc(C['bh']['dd']['mean'],0)}），净值修复快 2–3 倍。V1.6 逃顶最彻底（{pc(C['1.6']['escape'],0)}），V1.7 卖得最晚、逃顶率最低（{pc(C['1.7']['escape'],0)}）。主要风险点是“中枢跳升后资金池卡死”和“高波动期的冲击成本”。")}
<h3>危机崩盘与泡沫崩盘</h3>
{tbl_crisis}
<h3>中枢跳变：失效滞后与参数失灵顺序</h3>
<p>跳升后，最先失灵的是<b>回投估值线</b>：V 长期 ≥ 50，资金池里的现金在 1–6 个月内就进入“至少一年用不出去”的状态（{pc(DR['jump_up']['1.8']['stuck_rate'],0)} 的跳升事件出现）；接着<b>止盈估值线</b>在高位继续卖出，把更多仓位换成闲置现金；最后约 {days(DR['jump_up']['v_back'])} 个交易日后 <b>5/10 年估值分位窗口</b>消化掉新中枢，V 才回到正常区间。跳降则相反：回投线 2–3 个月内触发、资金池 5–8 个月内用完，之后只能靠定投。</p>
{tbl_jump}
<h3>高波动场景：冲击成本的侵蚀</h3>
<p>冲击成本与波动率挂钩，而策略恰恰在波动最大时交易最多（危机中回投、过热后止盈）：超过一半的冲击成本发生在波动最高的 20% 交易日，那时单笔冲击成本率约是平时的 2 倍。高波动路径（平均 ATR/价格 {HV['atr_hi']*100:.2f}%）的成本拖累比低波动路径（{HV['atr_lo']*100:.2f}%）多 0.12–0.17 个百分点 / 年。即便如此，高波动路径上四版扣成本后的超额仍高于低波动路径——波动越大，估值策略越有用武之地，只是要付更多“过路费”。</p>
{tbl_hv}
</section>
""")

# ============================================================ 6. 参数鲁棒性
rows = []
PN = {"SL": "止盈估值线", "RB": "回投估值线", "TH": "交易阈值", "FL": "底仓比例"}
fmtlv = {"SL": lambda x: f"{x:g}", "RB": lambda x: f"{x:g}", "TH": lambda x: f"{x*100:g}%", "FL": lambda x: f"{x*100:g}%"}
for k in ("SL", "FL", "RB", "TH"):
    r = [f'<td class="l">{PN[k]}<small>{" / ".join(fmtlv[k](l) for l in G["1.6"]["oat"][k]["levels"])}</small></td>']
    for v in VERS:
        o = G[v]["oat"][k]
        r.append(f'<td{heat(o["range"],0.008)}>{pp(o["range"],2,False)} pp<small>{" / ".join(pc(x) for x in o["vals"])}</small></td>')
    rows.append(r)
tbl_oat = table(["参数（三档）"] + [vtag(v) for v in VERS], rows, "num",
                note=f"单参数敏感性：其余参数固定在原值（70 / 50 / 5% / 20%），{S['grid_n_paths']} 条路径（10 主路径 + 100 条 MC）平均净 XIRR。格内：三档的极差，下方为各档数值。")
heats = ""
for v in VERS:
    hm = G[v]["heat"]
    base = hm["70|50"]
    cells = "".join(f"<tr><th>止盈 {sl}</th>" + "".join(f'<td{heat(hm[f"{sl}|{rb}"]-base,0.005)}>{pc(hm[f"{sl}|{rb}"])}</td>' for rb in (45, 50, 55)) + "</tr>" for sl in (75, 70, 65))
    heats += f'<div class="hm"><div class="hmt">{vtag(v)}</div><div class="tw"><table class="num"><thead><tr><th></th><th>回投 45</th><th>回投 50</th><th>回投 55</th></tr></thead><tbody>{cells}</tbody></table></div></div>'
rows = []
for v in VERS:
    of = G[v]["overfit"]
    sl = X["sl_mdd"][v]
    rows.append([vtag(v), of["best_train"].replace("|", " / "), pp(of["train_gain"]) + " pp", pp(of["test_gain"]) + " pp", f'{of["rank_test"]} / 81',
                 pp(of["mc_gain"]) + " pp", f'{of["rank_mc"]} / 81', f'{pp(sl["75"]["xirr"]-sl["70"]["xirr"])} / {pp(sl["75"]["mdd"]-sl["70"]["mdd"])}'])
tbl_of = table(["版本", "训练集最优组合（止盈/回投/阈值/底仓）", "训练集增益", "测试+复核主路径增益", "测试排名", "MC 增益", "MC 排名", "止盈线 70→75：XIRR / 回撤变化"], rows, "num",
               note=f"增益 = 最优组合 − 原始参数的平均净 XIRR。最后一列在 {X['sl_mdd_n']} 条路径上单独复算回撤。")
A(f"""
<section id="s6">
<h2><span class="sn">6</span>参数鲁棒性分析（净收益口径）</h2>
{callout("一句话", f"对 4 个参数做 3×3×3×3 = 81 组全组合、{S['grid_n_paths']} 条路径的敏感性测试。<b>最敏感的是止盈估值线</b>（三档极差 0.45–0.71 个百分点），其次是底仓比例，回投线和交易阈值几乎不影响结果。止盈线上移到 75 在四版里一致提高收益（+0.15 ~ +0.35 pp），回撤只多 0.1–0.4 个百分点，属于稳健的改进方向。")}
{chart('c_oat', '单参数敏感性：净 XIRR 随参数档位变化', '其余参数保持原值；四个小图共用同一纵轴', 300)}
{tbl_oat}
<h3>止盈线 × 回投线热力图（阈值 5%、底仓 20%）</h3>
<div class="hms">{heats}</div>
<p class="tnote">底色 = 相对原参数（70 / 50）的差值。四版的“高原”都在止盈 75 这一行：同一行里回投线从 45 到 55 变化不超过 0.1 个百分点。</p>
<div class="grid2">
<div>
<h3>最敏感参数排名</h3>
<ol class="tight rank">
<li><b>止盈估值线</b>：卖得越晚收益越高，65 档明显吃亏。</li>
<li><b>底仓比例</b>：30% 底仓略好于 20%，10% 最差——在长期上涨的合成市场里，多留底仓少踏空。</li>
<li><b>回投估值线</b>：±5 点影响 ≤ 0.1 个百分点。</li>
<li><b>交易阈值</b>：3%/5%/7% 差异 ≤ 0.03 个百分点，冲击成本按金额计提，阈值只改变交易次数不改变总量。</li>
</ol>
</div>
<div>
<h3>稳健区间（参数高原）</h3>
<p>以“与 81 组中最优值相差 ≤ 0.25 个百分点”为高原：V1.6 有 {G['1.6']['plateau_n']} 组、V1.7 有 {G['1.7']['plateau_n']} 组、V1.8 有 {G['1.8']['plateau_n']} 组、V1.9 有 {G['1.9']['plateau_n']} 组，全部落在<b>止盈线 75</b> 这一档（V1.7 另有 9 组止盈 70），回投线、阈值、底仓在高原内几乎任意。V1.7 的高原最宽，对参数最不挑剔。</p>
</div>
</div>
<h3>过拟合风险</h3>
<p>在训练集 4 条路径上选出最优组合，再拿到其余主路径和 MC 路径上检验：增益方向全部保持为正，但在独立 MC 路径上幅度缩小到训练集的 45%–100%，且最优组合在 MC 上的排名掉到第 3–15 名。说明“止盈线上移”是真实规律，但具体到某一组精确参数存在明显的过拟合成分，<b>不建议按训练集最优值精调</b>，选高原中心即可。</p>
{tbl_of}
</section>
""")

# ============================================================ 7. 预警
rows = []
for cnd, lab in (("all", "现有触发（A 或 B）"), ("A", "A：止盈后满 3 年 V 未回 50"), ("B", "B：全收益 ≥ 1.3×卖出均价且站上 160 日线")):
    for g in ("全部", "缓慢漂移", "快速跳升", "无漂移"):
        x = SEC[f"1.8|{cnd}|{g}"]
        rows.append([f'<td class="l">{lab}</td>' if g == "全部" else "<td></td>", g, num(x["events"]), pc(x["prec_day"], 0), pc(x["fpr"], 1),
                     "—" if x["miss"] is None else pc(x["miss"], 0), "—" if x["lead"]["median"] is None else f'{x["lead"]["median"]:.0f}'])
tbl_sec = table(["触发条件（V1.8）", "场景", "触发次数", "预警准确率", "假阳性率", "漏警率", "提前天数（中位）"], rows, "num",
                note="准确率 = 预警激活日中、前 126 日至后 504 日内确有同向中枢漂移的比例；假阳性率 = 无漂移期内预警处于激活状态的天数占比；漏警率 = 漂移起点前 2 年到起点后 1 年内从未预警的漂移事件占比；提前天数 = 漂移起点 − 首次预警（负数 = 事后才报）。真实漂移 = 过去 3 年中枢累计变动 ≥ 12%。V1.7 / V1.9 结果相近，见下表。")
rows = []
for v in ["1.7", "1.8", "1.9"]:
    x = SEC[f"{v}|all|全部"]
    rows.append([vtag(v), num(x["events"]), pc(x["prec_day"], 0), pc(x["fpr"], 1), pc(x["miss"], 0), f'{x["lead"]["median"]:.0f}',
                 pc(SEC[f"{v}|all|缓慢漂移"]["miss"], 0), pc(SEC[f"{v}|all|快速跳升"]["miss"], 0)])
tbl_sec2 = table(["版本", "触发次数", "准确率", "假阳性率", "漏警率", "提前天数", "漏警率：缓慢", "漏警率：快速"], rows, "num")
VN = ["单周期(任一)", "双周期(任两)", "三周期共振", "短+中", "中+长", "短+长", "仅短周期", "仅中周期", "仅长周期"]
rows = []
for vn in VN:
    x = MCW[f"both|{vn}|全部"]
    xs, xf, xn = MCW[f"both|{vn}|缓慢"], MCW[f"both|{vn}|快速"], MCW[f"both|{vn}|无漂移"]
    rows.append([f'<td class="l">{vn}</td>', f'<td{heat(x["prec_day"]-0.4,0.3)}>{pc(x["prec_day"],0)}</td>', f'<td{heat(0.15-x["fpr"],0.3)}>{pc(x["fpr"],1)}</td>',
                 f'<td{heat(0.4-x["miss"],0.5)}>{pc(x["miss"],0)}</td>', f'{x["lead"]["median"]:.0f}',
                 f'{pc(xs["prec_day"],0)} / {pc(xf["prec_day"],0)}', f'{pc(xs["miss"],0)} / {pc(xf["miss"],0)}', pc(xn["fpr"], 1)])
tbl_mcw = table(["触发方式", "准确率", "假阳性率", "漏警率", "提前天数", "准确率 慢 / 快", "漏警率 慢 / 快", "无漂移路径假阳性率"], rows, "num",
                note="上移、下移两个方向合并统计，全部 310 条路径。每个周期 3 项指标中 ≥2 项成立即视为该周期触发；共振状态保持 20 个交易日防止闪烁。")
SCN = [("第十节复核", "第十节人工复核"), ("L1", "一级：止盈线 +5、回投线 −5、回投减半"), ("L2", "二级：暂停新止盈 + 50% 资金池回补"),
       ("L3", "三级：全量回补 + 估值窗口改近 3 年"), ("graded", "分级组合（1/2/3 级按共振数自动切换）"),
       ("L1ML", "优化候选 A：一级 + “中+长”共振才二级"), ("L1L3", "优化候选 B：一级 + 三周期共振才三级")]
rows = []
for sc, lab in SCN:
    vs = [v for v in VERS if f"{v}|{sc}|全部" in WH]
    davg = sum(WH[f"{v}|{sc}|全部"]["d"]["mean"] for v in vs) / len(vs)
    mavg = sum(WH[f"{v}|{sc}|全部"]["mdd"]["mean"] for v in vs) / len(vs)
    dmc = sum(WR[f"{v}|{sc}|全部"]["d"]["mean"] for v in vs) / len(vs)
    r = [f'<td class="l">{lab}</td>', f'<td{heat(dmc,0.006)}>{pp(dmc)}</td>', f'<td{heat(davg,0.006)}>{pp(davg)}</td>', f'<td{heat(-mavg,0.06)}>{pp(mavg)}</td>']
    for k in ("base", "slow_up", "jump_up", "slow_down", "jump_down", "bubble", "cycle", "mixed"):
        dk = sum(WH[f"{v}|{sc}|{k}"]["d"]["mean"] for v in vs) / len(vs)
        r.append(f'<td{heat(dk,0.015)}>{pp(dk)}</td>')
    rows.append(r)
tbl_resp = table(["应对方案", "Δ净 XIRR（310 条）", "Δ净 XIRR（留出 100 条）", "Δ最大回撤（留出）"] + [KIND_CN[k] for k in ("base", "slow_up", "jump_up", "slow_down", "jump_down", "bubble", "cycle", "mixed")],
                 rows, "num", note="Δ = 相对“无预警、无复核”的同版本差值（百分点），四版平均。场景列为留出验证集（每类 10 条）。下移方向预警采用镜像动作：一级回投线 −5 且回投减半，二级暂停回投，三级改用 3 年窗口。")
A(f"""
<section id="s7">
<h2><span class="sn">7</span>多周期中枢漂移预警专项</h2>
{callout("一句话", f"假设成立一半：<b>共振数量越多，准确率越高、假阳性率越低</b>（三周期共振准确率 {pc(MCW['both|三周期共振|全部']['prec_day'],0)}、假阳性率 {pc(MCW['both|三周期共振|全部']['fpr'],1)}），<b>但漏警率从 0 升到 {pc(MCW['both|三周期共振|全部']['miss'],0)}，平均晚于漂移起点 {-MCW['both|三周期共振|全部']['lead']['median']:.0f} 天</b>。现有第十节触发条件对快速跳升有效（漏警率 {pc(SEC['1.8|all|快速跳升']['miss'],0)}、提前 {SEC['1.8|all|快速跳升']['lead']['median']:.0f} 天），对缓慢漂移基本失效（漏警率 {pc(SEC['1.8|all|缓慢漂移']['miss'],0)}）。")}
<h3>7.1 现有触发条件（第十节）的表现</h3>
{tbl_sec}
{tbl_sec2}
<p><b>两条阈值各自的有效性：</b>条件 A（3 年时长）几乎不误报（假阳性率 &lt;1%）但几乎总是来得太晚（漏警率 97%–99%，因为 3 年本身就超过了漂移被确认的时间）；条件 B（1.3 倍涨幅 + 站上 160 日线）贡献了绝大部分有效预警，也贡献了绝大部分误报——在没有中枢漂移的路径上，B 会把普通牛市当成中枢上移（无漂移路径假阳性率约 8%）。</p>
<h3>7.2 短 / 中 / 长三周期共振</h3>
<div class="defs">
<div><b>短周期 · 60 日</b><span>估值偏离（PE 相对 5 年均值 ≥ 1σ）· RSI(14) 60 日均值处于 50–70 · 20 日均线 60 日斜率 &gt; 0</span></div>
<div><b>中周期 · 252 日</b><span>V&gt;70 的天数 ≥ 150 · 160 日均线一年斜率 &gt; 0 · V 一年均值 − 50 ≥ 20</span></div>
<div><b>长周期 · 756 日</b><span>ROE 5 年均值 3 年变动 ≥ +5% · 10 年国债 3 年变动 ≤ −50bp · 观测中枢（5 年均值）移动速率 ≥ 3%/年</span></div>
</div>
{chart('c_mcw', '触发方式对比：准确率、假阳性率、漏警率', '全部 310 条路径，上移下移合并', 270)}
{tbl_mcw}
<p><b>验证结论：</b>“周期共振越多越准”在准确率和假阳性率上成立，且单调；但漏警率和提前量同时恶化，<b>没有一种触发方式同时做到准、早、不漏</b>。双周期中“中+长”组合性价比最高：准确率 {pc(MCW['both|中+长|全部']['prec_day'],0)} 接近三周期共振，假阳性率仅 {pc(MCW['both|中+长|全部']['fpr'],1)}。长周期指标（ROE、国债、中枢速率）是区分“中枢上移”和“泡沫”的关键：泡沫期利率上行、ROE 不变，长周期不确认。</p>
<h3>7.3 预警分级与应对效果</h3>
{chart('c_resp', '各级应对的净收益变化（留出验证集，四版平均）', '全部场景 vs 只看缓慢上移场景', 240)}
{tbl_resp}
<div class="grid2">
<div>
<h3>为什么重手应对反而亏钱</h3>
<p>二级、三级的核心动作是“暂停止盈 + 用资金池回补”，它押注的是“中枢已经上移，不会再跌回来”。预警准确率只有四到七成，押错一次就会在高位把现金全部换成股票，碰上随后的危机就是满仓扛回撤：留出集上二级、三级、分级组合的最大回撤平均增加 6–10 个百分点。只有缓慢上移场景（押对的概率最高、等待成本最大）能赚回来。</p>
</div>
<div>
<h3>最优分级应对</h3>
<ol class="tight rank">
<li><b>一级（任一周期触发）自动执行</b>：止盈线 +5、回投线 −5、回投减半。留出集四版平均 {pp(DATA['resp']['all'][0])} pp，最大回撤 −1.6 ~ −2.2 pp，在强周期、假回归、基准场景都为正。</li>
<li><b>二级（中+长共振）只触发人工复核</b>，不自动回补：复核结论为中枢上移时，才按第十节执行 50% 回补。</li>
<li><b>三级（三周期共振）作为复核的“确认证据”</b>，可配合改用 3 年估值窗口，但不建议自动全量回补。</li>
</ol>
<p class="muted">优化候选 A/B 是看过 310 条结果后提出的，在留出集上均未超过“只用一级”，因此不采纳。</p>
</div>
</div>
</section>
""")

# ============================================================ 8. 版本迭代
rows = []
steps = [("V1.6 → V1.7", "1.7-1.6", "趋势分 U 换成周线冲高回落 S（卖）+ 日线超卖 B（买）"),
         ("V1.7 → V1.8", "1.8-1.7", "两段式止盈（V1.6 前段 + V1.7 后段各一半），回投恢复 V1.6"),
         ("V1.8 → V1.9", "1.9-1.8", "保留两段式止盈，回投换回 V1.7 日线超卖")]
for lab, k, chg in steps:
    a, b = k.split("-")
    rows.append([f'<td class="l">{lab}</td>', f'<td class="l">{chg}</td>', f'<td{heat(P[k]["mean"],0.004)}>{pp(P[k]["mean"])} ± {pp(P[k]["se"],sign=False)}</td>',
                 f'<td{heat(-P[k]["mdd"],0.05)}>{pp(P[k]["mdd"])} ± {pp(P[k]["mdd_se"],sign=False)}</td>', pc(S["winrate"][f"{a}>{b}"], 0),
                 f'{OC[a+"|net"]["n_sell"]["mean"] - OC[b+"|net"]["n_sell"]["mean"]:+.0f} / {OC[a+"|net"]["n_rebuy"]["mean"] - OC[b+"|net"]["n_rebuy"]["mean"]:+.0f}',
                 pp(OC[a + "|net"]["cost_ratio"]["mean"] - OC[b + "|net"]["cost_ratio"]["mean"])])
tbl_iter = table(["迭代", "改了什么", "Δ净 XIRR（pp，±标准误）", "Δ最大回撤（pp）", "胜率", "Δ止盈 / 回投次数", "Δ成本占比（pp）"], rows, "num",
                 note="300 条蒙特卡洛路径的配对差值。")
A(f"""
<section id="s8">
<h2><span class="sn">8</span>版本迭代评估</h2>
{tbl_iter}
<div class="grid2">
<div>
<h3>每一步迭代的收益与代价</h3>
<ul class="tight">
<li><b>V1.6 → V1.7</b>：收益 +{P['1.7-1.6']['mean']*100:.2f} pp（显著，5 个标准误），代价是回撤 +{P['1.7-1.6']['mdd']*100:.1f} pp、危机逃顶率从 {pc(C['1.6']['escape'],0)} 降到 {pc(C['1.7']['escape'],0)}。止盈次数从约 46 次降到 16 次，交易更少、更集中。</li>
<li><b>V1.7 → V1.8</b>：收益 {P['1.8-1.7']['mean']*100:+.2f} pp，回撤 {P['1.8-1.7']['mdd']*100:+.1f} pp。两段式是 V1.6 和 V1.7 的折中，收益和回撤都落在两者之间，“对冲单一卖出节奏风险”的设计意图得到验证。</li>
<li><b>V1.8 → V1.9</b>：收益 {P['1.9-1.8']['mean']*100:+.2f} pp（1.7 个标准误，未达显著），回撤 {P['1.9-1.8']['mdd']*100:+.1f} pp。日线超卖回投让 V1.9 比 V1.8 略多赚、略多亏，且在假回归中回投踩雷更多。</li>
</ul>
</div>
<div>
<h3>按风险偏好选版本</h3>
<div class="pick"><b>稳健型（最在意回撤）</b><span>{vtag('1.6')} 回撤最小、逃顶最彻底、假回归最少踩雷；代价是年化最低。</span></div>
<div class="pick"><b>均衡型</b><span>{vtag('1.8')} 收益比 V1.6 高 {P['1.8-1.6']['mean']*100:.2f} pp，回撤只多 {P['1.8-1.6']['mdd']*100:.1f} pp，危机抄底率与 V1.6 接近。</span></div>
<div class="pick"><b>进取型（能扛更深回撤）</b><span>{vtag('1.7')} 收益最高，且在中枢上移场景受伤最轻；需要接受约 5–6 个百分点更深的回撤。</span></div>
<div class="pick"><b>V1.9</b><span>与 V1.8 的差异在统计误差附近，没有足够理由替换 V1.8；若已在用也无需换回。</span></div>
</div>
</div>
</section>
""")

# ============================================================ 9. 结论与建议
A(f"""
<section id="s9">
<h2><span class="sn">9</span>最终结论与优化建议</h2>
<h3>9.1 有效性排序与适用环境</h3>
{table(["排序", "版本", "最适合的市场", "最怕的市场"], [
    ["1", vtag('1.7'), "中枢上移（慢或快）、泡沫崩盘、基准震荡", "中枢下移（回投偏早）、危机前需要提前减仓的行情"],
    ["2", vtag('1.9') + " ≈ " + vtag('1.8'), "强周期、混合极端；需要兼顾收益与回撤", "缓慢上移（资金池长期闲置）"],
    ["4", vtag('1.6'), "缓慢下移、长停滞、危机频发（回撤最小）", "缓慢上移（跑输最多：" + neg(Q['slow_up']['1.6']['ex']) + " pp/年）"],
], "num l3")}
<h3>9.2 全口径成本下的净收益边界</h3>
<ul class="tight">
<li>毛收益口径下四版相对买入持有的超额为 {pp(min(exg_main.values()))} ~ {pp(max(exg_main.values()))} pp/年，全口径成本吃掉其中 0.67–0.74 pp，净超额落到 {pp(min(ex_main.values()))} ~ {pp(max(ex_main.values()))} pp。<b>换句话说，策略的收益超额与成本处于同一量级。</b></li>
<li>冲击成本是唯一需要重视的成本项。若实际冲击成本只有假设的一半（0.25 × ATR/价格），净超额约提高 0.3 pp；若翻倍，四版的净超额基本都会转负（只有 V1.7 在主路径上仍勉强为正）。</li>
<li>在收益边界之外，四版提供的是<b>风险边界</b>：最大回撤低 11–16 pp，危机后修复时间缩短到买入持有的 1/3 左右。</li>
</ul>
<h3>9.3 核心风险点与应对</h3>
<div class="risks">
<div><b>缓慢上移的中枢</b><span>V 长期偏高，资金池卡死，年化跑输 5.7–6.8 pp。应对：止盈线上移到 75；启用一级预警的温和调线；第十节复核把“10 年国债持续下行 + ROE 抬升”作为核心证据。</span></div>
<div><b>中枢快速跳升</b><span>回投线最先失灵，1–6 个月内资金池进入闲置。应对：保留第十节条件 B（对跳升最有效，中位提前约 50–85 个交易日），复核结论为上移时按 50% 回补。</span></div>
<div><b>上升趋势假回落中的卖出</b><span>周线冲高回落信号和趋势分转弱都会在假回落里卖出。应对：假回落后若长周期指标（ROE、国债）未转向，可把这类卖出推迟 20 个交易日确认。</span></div>
<div><b>高波动期冲击成本</b><span>一半以上的冲击成本发生在最高波动 20% 交易日。应对：高波动日把单笔交易拆成 3–5 个交易日分批执行，或提高该时段的交易阈值。</span></div>
</div>
<h3>9.4 可落地的优化方向与操作指南</h3>
<ol class="tight">
<li><b>止盈估值线 70 → 75</b>（四版一致 +0.15 ~ +0.35 pp，回撤 +0.2 ~ +0.4 pp，非训练集过拟合）。</li>
<li><b>底仓 20% → 25%–30%</b>（小幅正贡献，长期上涨市场中减少踏空）。回投线与交易阈值保持原值即可。</li>
<li><b>加一级预警作为常驻规则</b>：任一周期预警时止盈线 +5、回投线 −5、回投减半；二、三级只触发人工复核。</li>
<li><b>第十节复核保留，但要知道它的边界</b>：对快速跳升有用，对缓慢上移几乎来不及；复核结论应以长周期证据为准。</li>
<li><b>大额交易分批执行</b>，控制冲击成本；冲击成本是决定能否跑赢买入持有的关键变量。</li>
<li><b>版本选择</b>：均衡选 V1.8，进取选 V1.7，稳健选 V1.6；V1.9 相对 V1.8 的改进未通过显著性检验。</li>
</ol>
</section>
""")


# ============================================================ 10. 中枢漂移专项研究
PRM = R["params"]


def dexcell(x, se_=None, scale=0.012):
    return f'<td{heat(x, scale)}>{pp(x)}' + (f'<small>± {se_*100:.2f}</small>' if se_ is not None else "") + "</td>"


def pegroup(k):
    a = DRS[k]["analytic"]["pe"]
    return "up" if a > 0.05 else ("down" if a < -0.05 else "flat")


GRP_CN = {"up": "PE 中枢上移", "down": "PE 中枢下移", "flat": "PE 中枢基本不动、其他指标各走各的"}
import gen2 as _g2
unit = [("10 年国债 +1pp", dict(y=0.01)), ("要求的风险溢价 +1pp", dict(rp=0.01)), ("ROE +1pp", dict(roe=0.01)), ("分红率 +5pp", dict(p=0.05))]
rows = []
for lab, dr in unit:
    a = _g2.analytic(dr)
    rows.append([f'<td class="l">{lab}</td>', pp(a["pe"], 1) + "%", pp(a["pb"], 1) + "%", pp(a["dy"], 1) + "%", pp(a["ey"], 1) + "%", pp(a["erp"]) + " pp", pp(a["g"]) + " pp"])
tbl_unit = table(["驱动因素变化", "PE 中枢", "PB 中枢", "股息率中枢", "盈利收益率", "股债利差", "每股收益增速"], rows, "num",
                 note=f"参数：股票久期 D = {PRM['D']:g}，增长传导 κ = {PRM['kappa']:g}，分红率直接弹性 λ = {PRM['lam']:.2f}（使分红率变化在基准 ROE 下对估值中性）；基准 ROE {PRM['roe0']*100:g}%、分红率 {PRM['p0']*100:g}%、国债 {PRM['y0']*100:g}%、PE 中枢 13 倍、每股收益增速 {PRM['g0']*100:g}%。")
c1 = DRS["C1"]["analytic"]
tbl_cal = table(["指标", "沪深300 实际（2015 年后 / 2011 年起）", "模拟情景 C1（12 年后）", "方向"], [
    ['<td class="l">PE 中枢</td>', "11–13.3 倍，基本稳定", pp(c1["pe"], 1) + "%", "一致"],
    ['<td class="l">PB 中枢</td>', "2.95 → 1.38（−53%，含 2011–14 年 PE 中枢下移）", pp(c1["pb"], 1) + "%", "一致"],
    ['<td class="l">ROE 中枢</td>', "15.3% → 10.8%", "12% → 8.5%", "一致"],
    ['<td class="l">股息率中枢</td>', "1.5% → 2.76%", pp(c1["dy"], 1) + "%", "一致"],
    ['<td class="l">10 年国债中枢</td>', "3.5% → 2.3%", "−1.2 pp", "一致"],
    ['<td class="l">股债利差中枢</td>', "升至约 5.7 pp", pp(c1["erp"]) + " pp", "一致"],
    ['<td class="l">每股收益增速</td>', "年化约 3.4%", f"{(PRM['g0']+c1['g'])*100:.1f}%（基准 {PRM['g0']*100:g}%）", "一致"],
], "txt", note="模拟取保守幅度；实际 PB、股息率的变化里还叠加了 2011–2014 年 PE 中枢下移（泡沫期估值移出窗口）的影响。")

rows = []
for x in R["scen"]:
    a = x["analytic"]
    sp = "，".join({"y": "利率", "rp": "风险溢价"}[k] + "快速" for k, v in x["speeds"].items() if v == "fast")
    rows.append([f'<td class="l"><b>{x["key"]}</b> {esc(x["name"])}<small>{esc(x["desc"])}{("；" + sp) if sp else ""}</small></td>',
                 f'<td{heat(a["pe"],0.3)}>{pp(a["pe"],0)}%</td>', f'<td{heat(a["pb"],0.5)}>{pp(a["pb"],0)}%</td>', f'<td{heat(-a["dy"],0.5)}>{pp(a["dy"],0)}%</td>',
                 f'<td{heat(-a["erp"],0.03)}>{pp(a["erp"])}</td>', pp(a["g"])])
tbl_scen = table(["情景（12 年缓慢完成；“快速”= 2 个月内完成）", "PE 中枢", "PB 中枢", "股息率中枢", "股债利差（pp）", "盈利增速（pp）"], rows, "num",
                 note="终点相对起点的理论中枢变化。底色：红 = 变贵方向，绿 = 变便宜方向（股息率、股债利差上升代表变便宜）。")

rows = []
for x in R["scen"][1:]:
    dp = x["dpct"]
    rows.append([f'<td class="l"><b>{x["key"]}</b> {esc(x["name"])}</td>'] +
                [f'<td{heat(dp[k],12)}>{dp[k]:+.1f}</td>' for k in ("ey", "bp", "dy", "erp")] +
                [f'<td{heat(x["dV"]["orig"],10)}><b>{x["dV"]["orig"]:+.1f}</b></td>', f'<td{heat(x["dV_post"]["orig"],10)}>{x["dV_post"]["orig"]:+.1f}</td>',
                 f'{x["corr"]["orig"]:.2f}'])
tbl_vbias = table(["情景", "盈利收益率分位", "PB 分位", "股息率分位", "股债利差分位", "V 偏移（漂移期）", "V 偏移（漂移结束后 9 年）", "V 与真实偏离的相关系数"], rows, "num",
                  note=f"与基准情景 S0 同种子配对，单位：V 点（0–100）。正 = 看起来更贵，负 = 看起来更便宜。基准情景下 V 与真实估值偏离的相关系数为 {DRS['S0']['corr']['orig']:.2f}。")

rows = []
for x in R["scen"][1:]:
    pf = x["perf"]
    rows.append([f'<td class="l"><b>{x["key"]}</b> {esc(x["name"])}</td>'] +
                [dexcell(pf[f"orig|{v}"]["dex"], pf[f"orig|{v}"]["dex_se"]) for v in VERS] +
                [pp(sum(pf[f"orig|{v}"]["dmdd"] for v in VERS) / 4, 1), pp(sum(pf[f"orig|{v}"]["didle"] for v in VERS) / 4, 0) + "%"])
tbl_perf = table(["情景"] + [vtag(v) for v in VERS] + ["最大回撤变化（pp，四版平均）", "资金池闲置变化（四版平均）"], rows, "num",
                 note=f"单元格：相对买入持有的年化超额，减去同种子基准情景下的超额（百分点 / 年，± 标准误）。每个情景 {PRM['N1']} 条 30 年路径。")

reg = R["reg"]
FN = [("pe", "PE 中枢 ±18%"), ("roe", "ROE ±3pp"), ("p", "分红率 −8 / +12pp"), ("y", "10 年国债 ±1.5pp")]
rows = []
for f, lab in FN:
    rows.append([f'<td class="l">{lab}</td>', f'<td{heat(reg["dV"][f],5)}>{reg["dV"][f]:+.2f}</td>'] +
                [f'<td{heat(reg[v][f],0.008)}>{pp(reg[v][f])}</td>' for v in VERS] + [f'<td{heat(reg["avg"][f],0.008)}><b>{pp(reg["avg"][f])}</b></td>'])
rows.append(['<td class="l">模型解释度 R²</td>', f'{reg["dV"]["r2"]:.2f}'] + [f'{reg[v]["r2"]:.2f}' for v in VERS] + [f'{reg["avg"]["r2"]:.2f}'])
tbl_reg = table(["因子（每上升一档）", "V 偏移（点）"] + [vtag(v) for v in VERS] + ["四版平均"], rows, "num",
                note=f"对 {R['n_kept']} 组自洽组合做线性回归（因子编码 −1 / 0 / +1，四个因子同时放入）。版本列：相对买入持有的年化超额变化（百分点）。R² 接近 1 说明各因子的影响基本可以相加，交互作用很小。")
excl = [c for c in R["combos"] if not c["kept"]]

GV = {}
for g in ("up", "down", "flat"):
    ks = [x["key"] for x in R["scen"][1:] if pegroup(x["key"]) == g]
    GV[g] = ks
rows = []
for g in ("up", "down", "flat"):
    ks = GV[g]
    for vk, lab in (("orig", "原版（4 项）"), ("nopb", "去掉 PB（3 项）"), ("ey", "只用盈利收益率")):
        dvb = sum(DRS[k]["dV"][vk] for k in ks) / len(ks)
        cor = sum(DRS[k]["corr"][vk] for k in ks) / len(ks)
        dvr = sum(DRS[k]["perf"][f"{vk}|{v}"]["dvar"] for k in ks for v in VERS) / (4 * len(ks))
        rows.append([f'<td class="l">{GRP_CN[g]}<small>{"、".join(ks)}</small></td>' if vk == "orig" else "<td></td>", lab,
                     f'{dvb:+.1f}', f'{cor:.2f}', "—" if vk == "orig" else f'<td{heat(dvr,0.003)}>{pp(dvr)}</td>'])
b0 = DRS["S0"]
for vk, lab in (("orig", "原版（4 项）"), ("nopb", "去掉 PB（3 项）"), ("ey", "只用盈利收益率")):
    dvr = sum(b0["perf"][f"{vk}|{v}"]["dvar"] for v in VERS) / 4
    rows.append(['<td class="l">基准 S0</td>' if vk == "orig" else "<td></td>", lab, "0.0", f'{b0["corr"][vk]:.2f}', "—" if vk == "orig" else f'<td{heat(dvr,0.003)}>{pp(dvr)}</td>'])
tbl_vvar = table(["情景组", "估值分 V 的构成", "V 平均偏移（点）", "与真实偏离的相关系数", "年化收益相对原版（pp，四版平均）"], rows, "num")

rows = []
for v in ["1.7", "1.8", "1.9"]:
    agg = {k: 0 for k in ("n_old", "up_old", "false_up_old", "miss_old", "n_new", "up_new", "false_up_new", "miss_new", "true_up")}
    go = gn = 0.0
    for x in R["scen"]:
        rv = x["review"][v]
        for k in agg:
            agg[k] += rv[k]
        go += rv["gain_old"]
        gn += rv["gain_new"]
    m = len(R["scen"])
    rows.append([vtag(v), "原规则（国债 / ROE）", num(agg["n_old"]), num(agg["up_old"]), num(agg["false_up_old"]), num(agg["miss_old"]),
                 pc(1 - (agg["false_up_old"] + agg["miss_old"]) / agg["n_old"], 1), pp(go / m)])
    rows.append(["", "修订规则（PE 滚动中位数为主）", num(agg["n_new"]), num(agg["up_new"]), num(agg["false_up_new"]), num(agg["miss_new"]),
                 pc(1 - (agg["false_up_new"] + agg["miss_new"]) / agg["n_new"], 1), pp(gn / m)])
tbl_rev2 = table(["版本", "复核判断规则", "复核次数", "判为中枢上移", "其中误判", "漏判", "判断准确率", "复核增益（pp，18 情景平均）"], rows, "num",
                 note="“真上移” = 本轮首次止盈到复核结论日之间真实 PE 中枢上升 ≥ 8%。修订规则：PE 滚动 5 年中位数上升 ≥10% 或 ROE 5 年均值上升 ≥5%，国债下行仅在股债利差未同步上升 ≥0.5pp 时计入。")
c1r = DRS["C1"]["review"]["1.8"]

up_dex = sum(DRS[k]["perf"][f"orig|{v}"]["dex"] for k in GV["up"] for v in VERS) / (4 * len(GV["up"]))
dn_dex = sum(DRS[k]["perf"][f"orig|{v}"]["dex"] for k in GV["down"] for v in VERS) / (4 * len(GV["down"]))
fl_dex = sum(DRS[k]["perf"][f"orig|{v}"]["dex"] for k in GV["flat"] for v in VERS) / (4 * len(GV["flat"]))
fl_mdd = sum(DRS[k]["perf"][f"orig|{v}"]["dmdd"] for k in GV["flat"] for v in VERS) / (4 * len(GV["flat"]))
C1P = DRS["C1"]["perf"]
A(f"""
<section id="s10">
<h2><span class="sn">10</span>中枢漂移专项研究：各指标中枢各走各的</h2>
{callout("一句话", f"按经济规律推导，“中枢漂移”可以只发生在 PB、股息率、股债利差上，而 PE 中枢纹丝不动——沪深300 2015–2026 年就是这样。模拟 18 个情景、{R['n_kept']} 组自洽组合后发现：<b>决定策略成败的是 PE 中枢本身</b>（每档 ±18% 让四版年化超额变化约 ∓{abs(R['reg']['avg']['pe'])*100:.2f} 个百分点）；其他指标的中枢单独漂移只会把 V 拉偏几点，让策略仓位更重或更轻，对收益影响小，但会改变回撤。V 识别真实贵贱的能力几乎不受影响（相关系数 {min(x['corr']['orig'] for x in R['scen']):.2f}–{max(x['corr']['orig'] for x in R['scen']):.2f}，基准 {DRS['S0']['corr']['orig']:.2f}）。")}
<h3>10.1 经济框架：四个驱动，五个中枢</h3>
<p>之前的模拟把所有指标绑在 PE 中枢上一起动。现实中它们由四个更底层的驱动共同决定：<b>10 年国债收益率</b>、<b>投资者要求的风险溢价</b>（风险偏好）、<b>ROE</b>（盈利能力）、<b>分红率</b>（分配政策）。各指标中枢通过两类关系联系起来：</p>
<div class="defs">
<div><b>恒等式（必然成立）</b><span>PB = PE × ROE；股息率 = 分红率 ÷ PE；盈利收益率 ≈ 1 ÷ PE；股债利差 = 盈利收益率 − 国债收益率</span></div>
<div><b>估值规律（股利折现的线性近似）</b><span>PE 中枢的对数变化 = 久期 × (−Δ国债 − Δ风险溢价 + Δ盈利增速) + 分红率效应；盈利增速 = ROE × (1 − 分红率) 的一半传导</span></div>
<div><b>速度约束</b><span>ROE 与分红率是结构性变量，只能慢慢变；利率与风险溢价可以慢变，也可以在政策或冲击下 2 个月内跳变</span></div>
</div>
<p>每个驱动单独变化时，各指标中枢的反应如下。可以看到“各走各的”是常态：利率和风险溢价同等地影响 PE，但只有风险溢价会改变股债利差；ROE 主要改变 PB；分红率几乎只改变股息率。</p>
{tbl_unit}
<p><b>用沪深300 实际情况校准：</b>你提供的 2015–2026 年数据（PE 中枢稳定、PB 中枢随 ROE 下行、股息率中枢上升、国债下行而 PE 没涨、股债利差抬升）可以被情景 C1 复现：降息对 PE 的推升被 ROE 下滑带来的增速下降抵消，股债利差因此被动抬升。</p>
{tbl_cal}
<h3>10.2 情景设计</h3>
<p>18 个具名情景：7 个单因素、6 个经济组合、4 个快速版本，外加基准。每个情景 {PRM['N1']} 条 30 年路径，与基准情景使用完全相同的随机种子（相同的短期波动、危机和假回归），差别只在中枢，因此任何结果差异都可以归因于中枢漂移。漂移从第 9 年开始、12 年内完成；快速版本在第 12 年用 2 个月完成。</p>
{tbl_scen}
<h3>10.3 情景浏览器</h3>
<p class="muted">选择情景，查看各指标中枢的走法（第一张图以起点为 1）、利率与股债利差中枢，以及三种构成的估值分 V（120 日均值）。以种子 {5000} 为例。</p>
<div class="seg" role="group" aria-label="选择情景" id="scensel"></div>
<div class="explorer ex2">
{chart('c_dc1', '估值指标中枢（起点 = 1）', 'PE、PB、股息率的中枢路径', 230)}
{chart('c_dc2', '利率与股债利差中枢（%）', '股债利差 = 1/PE 中枢 − 国债中枢', 230)}
{chart('c_dc3', '估值分 V 的三种构成（120 日均值）', '原版 4 项 / 去掉 PB / 只用盈利收益率', 240)}
</div>
<h3>10.4 V 被拉偏了多少</h3>
<p>V 是四个分项分位数的平均，所以中枢漂移对 V 的影响 = 各分项被拉偏的平均。PE 中枢不动时（S7、C1、F4），盈利收益率分位几乎不变，但 PB、股息率、股债利差分位被拉向“便宜”，V 平均偏低 {abs(DRS['C1']['dV']['orig']):.1f} 点（C1）。漂移结束后，5~10 年窗口逐渐吸收新中枢，偏移收敛到 {DRS['C1']['dV_post']['orig']:+.1f} 点。</p>
{tbl_vbias}
<h3>10.5 策略受到的影响</h3>
<div class="grid2">
<div><p><b>PE 中枢上移</b>（{"、".join(GV['up'])}）：四版年化超额平均 {pp(up_dex)} 个百分点，资金池闲置增加——卖出后等不到回投机会。</p>
<p><b>PE 中枢下移</b>（{"、".join(GV['down'])}）：平均 {pp(dn_dex)} 个百分点，相对买入持有占优，但最大回撤加深，因为 V 偏低让策略更早、更多地回投。</p></div>
<div><p><b>PE 不动、其他指标各走各的</b>（{"、".join(GV['flat'])}）：平均 {pp(fl_dex)} 个百分点，最大回撤 {pp(fl_mdd,1)} 个百分点。C1 中 V1.7 回撤多 {C1P['orig|1.7']['dmdd']*100:.1f} 个百分点。风险不是少赚，而是“以为便宜、仓位偏重”。</p>
<p><b>快与慢：</b>同样的利率下行，快速版（F1）对收益的伤害约是缓慢版（S1）的一半；风险溢价急升（F2）比缓慢上升（S3）多出约 1.5–3 个百分点回撤。</p></div>
</div>
{tbl_perf}
<h3>10.6 组合全景：{R['n_kept']} 组自洽组合</h3>
<p>把 PE 中枢、ROE、分红率、国债四个因子各取三档（下 / 不变 / 上）做全组合，风险溢价作为差额吸收项，用来满足估值规律。{len(excl)} 组需要风险溢价变化超过 ±3 个百分点才能成立（例如“PE 中枢下降、ROE 上升、利率下降”），视为经济上不自洽，予以剔除。每组 {PRM['N2']} 条路径，与中心组合配对比较。</p>
{chart('c_me', '各因子的主效应：相对买入持有的年化超额变化', '其余因子在所有自洽组合上取平均；四个小图共用纵轴', 280)}
{tbl_reg}
<p><b>排序很清楚：</b>PE 中枢 ≫ ROE &gt; 分红率 ≈ 利率。ROE 在 PE 中枢固定时仍有影响，来自两方面：PB 分位被拉偏，以及盈利增速变化改变了买入持有的回报节奏；分红率和利率在 PE 中枢固定时，只是让股息率或股债利差“看起来”更便宜或更贵。</p>
<h3>10.7 应对方案检验</h3>
<div class="grid2">
<div>
<h4>改 V 的构成？不建议</h4>
<p>去掉 PB 或只用盈利收益率，确实能减少 PE 不动时的偏移（C1：{DRS['C1']['dV']['orig']:+.1f} → {DRS['C1']['dV']['nopb']:+.1f} → {DRS['C1']['dV']['ey']:+.1f} 点），但 V 与真实偏离的相关系数下降，收益在大多数情景下略低。四项平均本身就是对单一指标漂移的分散。</p>
</div>
<div>
<h4>改第十节复核规则？不建议（收回上一轮的建议）</h4>
<p>上一轮我提出“以 PE 滚动中位数为主证据、利率只作辅助”。检验结果更差：PE 滚动中位数在普通周期里也常涨 10%，误判上移从每版约 {sum(x['review']['1.8']['false_up_old'] for x in R['scen'])} 次增加到约 {sum(x['review']['1.8']['false_up_new'] for x in R['scen'])} 次（V1.8），复核增益由约 0 变为负。原规则在 C1 型情景下 {c1r['n_old']} 次复核只误判 {c1r['false_up_old']} 次，因为“下降 ≥50bp 且持续 1 年以上”加上必须先触发复核，已经足够保守。</p>
</div>
</div>
{tbl_vvar}
{tbl_rev2}
<h3>10.8 专项结论</h3>
<ol class="tight">
<li><b>中枢漂移要拆开看。</b>先问 PE 中枢动没动，再看 PB、股息率、股债利差的中枢是否因为 ROE、分红率、利率而单独移动。只有前者会系统性地改变策略收益。</li>
<li><b>PE 中枢上移是唯一的系统性威胁</b>：每 18% 让年化超额少约 {abs(R['reg']['avg']['pe'])*100:.2f} 个百分点；即便 PE 中枢不变，ROE 每上一档（+3pp）也会再少约 {abs(R['reg']['avg']['roe'])*100:.2f} 个百分点。</li>
<li><b>“成分漂移、PE 不动”只改变风险，不改变收益</b>：V 偏低几点，策略仓位更重，超额略增，回撤加深 0.7–2.8 个百分点。沪深300 当前正处于这种状态，实盘时可预期策略比“看起来”更进取。</li>
<li><b>V 的识别能力稳健</b>：各种组合下与真实偏离的相关系数仍在 0.84 以上；保留四项构成，不必为单一指标漂移改公式。</li>
<li><b>可操作的监控</b>：每季度分别计算四个分项的分位数；若 PB、股息率、股债利差的分位长期比盈利收益率分位低 5 点以上，说明正处于“成分漂移”，可把回投估值线临时下调 3–5 点，以抵消 V 偏低带来的额外仓位。</li>
</ol>
<p class="tnote">局限：估值规律采用线性近似，久期、增长传导系数为假设值；“真实中枢”只在模拟中可知。结论用于理解方向和相对大小，不宜直接作为精确的数值预测。</p>
</section>
""")

# ============================================================ 附录
A(f"""
<section id="appx" class="appx">
<h2>附录：方法、口径与局限</h2>
<div class="grid2">
<div>
<h3>回测执行</h3>
<ul class="tight">
<li>严格按各版本文档：T−1 日数据计算 V、U、S、B、p，T 日净值成交；先进先出，持有 &lt;30 天不卖；交易阈值 5%；20% 底仓；止盈日不定投、不回投；赎回款 T+3 到账、在途计入 C；定投挂账满 10 元成交，加大额度每轮 ≤ 5 万。</li>
<li>统一初始条件：10 万元 100% 持仓、资金池 0、E = 0；基金净值 = 全收益指数（未扣管理费）；资金池现金收益为 0。</li>
<li>成本：申购 0.1%，赎回按持有期 1.5% / 0.5% / 0.25% / 0；佣金 + 滑点单边 0.1%；冲击成本 = 0.5 × ATR(10)/收盘价，买卖双向、所有交易（含定投）都收取。</li>
<li>买入持有基准：初始 10 万 + 与策略相同的外部入金，当日全额买入，扣同样的成本；定额定投基准：总入金相同、每日等额。</li>
</ul>
</div>
<div>
<h3>局限</h3>
<ul class="tight">
<li>全部结论来自合成数据。合成市场的假设（例如真实中枢漂移伴随 ROE 与国债收益率变化、泡沫期利率上行）直接决定了长周期预警的有效性；真实市场的中枢漂移未必有这么“干净”的基本面信号。</li>
<li>日线最高 / 最低价为模拟近似值，日线 KC 下轨与实盘会有差异。</li>
<li>第十节人工复核以文档列出的两项可量化证据自动化判断，无法模拟“成分股与行业结构变化”这一项。</li>
<li>冲击成本按提示词公式计提，对小额定投偏保守（真实小额交易几乎没有冲击）。</li>
<li>启用任何调整前，应先在 2014–2026 真实历史上逐笔核对关键时点的动作。</li>
</ul>
</div>
</div>
<p class="muted">复现：<code>python analysis.py &amp;&amp; python summarize.py &amp;&amp; python extra.py &amp;&amp; python report.py</code>（4 核约 8 分钟）。代码与原始结果位于仓库 <code>hs300-stress-test/</code> 目录。</p>
</section>
""")

BODY = "\n".join(parts)
TOC = [("tldr", "结论速览"), ("s1", "1 模拟数据概览"), ("s2", "2 全周期总览"), ("s3", "3 中枢漂移速度"), ("s4", "4 假回归陷阱"),
       ("s5", "5 极端压力测试"), ("s6", "6 参数鲁棒性"), ("s7", "7 多周期预警"), ("s8", "8 版本迭代评估"), ("s9", "9 结论与建议"), ("s10", "10 中枢漂移专项"), ("appx", "附录")]
toc_html = "".join(f'<a href="#{a}">{b}</a>' for a, b in TOC)

CSS = open(os.path.join(HERE, "report_assets", "style.css"), encoding="utf-8").read()
JS = open(os.path.join(HERE, "report_assets", "charts.js"), encoding="utf-8").read()

page = f"""<title>沪深300策略压力测试</title>
<meta name="description" content="V1.6–V1.9 四版沪深300估值策略在 410 条合成行情上的全场景压力测试报告">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>{CSS}</style>
<div class="page">
<nav class="rail" aria-label="目录"><div class="rail-in"><p class="rail-t">目录</p>{toc_html}</div></nav>
<main class="main">
<nav class="toc-m" aria-label="目录">{toc_html}</nav>
{BODY}
</main>
</div>
<div id="tip" class="tip" hidden></div>
<script id="data" type="application/json">{json.dumps(DATA, ensure_ascii=False, separators=(",", ":"))}</script>
<script>{JS}</script>
"""
import sys
full = ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + page.replace("<style>", "<style>body{margin:0}[hidden]{display:none!important}", 1).replace('<div class="page">', '</head>\n<body>\n<div class="page">', 1)
        + "\n</body>\n</html>\n")
with open(os.path.join(HERE, "report.html"), "w", encoding="utf-8") as f:
    f.write(full)
if len(sys.argv) > 1:          # 额外输出无文档骨架的片段（用于发布为 Artifact）
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write(page)
print("report.html", len(full) // 1024, "KB")
