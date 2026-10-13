# 沪深300 V1.6 → V1.7 指标检验

运行顺序（Python 3，依赖 numpy / pandas）：

| 脚本 | 作用 |
|---|---|
| `data.py` | 按 V1.6 附录复现估值分 V、趋势分 U，计算技术指标，输出 `out/panel.pkl` |
| `engine.py` | V1.6 规则引擎（先进先出、30 天锁定、赎回费、在途款、挂账）+ 指标插槽 |
| `signals.py` | 9 个指标的超卖/超买信号，默认参数与 3×3 邻域 |
| `stage1_signal.py` | 关卡 1：信号层前瞻收益检验（Newey-West） |
| `stage2_strategy.py` | 关卡 2–3：各插槽 × 参数邻域 × 安慰剂，共 1,858 组回测 |
| `stage3_analyze.py` | 关卡 4：增量表、PBO（CSCV）、紧缩夏普 |
| `stage4_followup.py` | 波动率刹车、组合消融、起点敏感性 |
| `stage5_bprime.py` | "止盈等超买回落"的分段归因与结构敏感性 |
| `iv_module.py` | 期权 IV 分位接入：`python iv_module.py fetch` 后 `python iv_module.py test` |
| `build_report.py` | 生成 `report.html` |
