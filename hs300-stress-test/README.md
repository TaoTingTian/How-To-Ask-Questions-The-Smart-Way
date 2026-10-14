# 沪深300策略 V1.6–V1.9 全场景压力测试

按《沪深300策略V1.6-V1.9 全场景压力测试回测提示词》执行的合成数据回测，报告见 **`report.html`**（自包含，浏览器直接打开）。

## 文件

| 文件 | 内容 |
|---|---|
| `gen.py` | 30 年日度合成行情：估值中枢（缓慢漂移 / 快速跳变）、危机与回调、波动率聚集、利率与 ROE 联动、假回归陷阱生成与识别 |
| `indicators.py` | 估值分 V（附录 C）、趋势分 U、日线 / 周线 RSI 与 KC、冲高回落 S、日线超卖 B；多周期中枢漂移预警指标；真实漂移标签 |
| `engine.py` | 四版策略逐日回测引擎（先进先出、30 天限制、T+3 到账、挂账、加大额度、第十节复核、全口径成本、预警分级应对） |
| `analysis.py` | 全部实验：10 条主路径 + 300 条蒙特卡洛 + 100 条留出验证；输出 `results/raw.json`（不入库，可复现） |
| `summarize.py` / `extra.py` | 汇总统计 → `results/summary.json`、`results/extra.json` |
| `gen2.py` / `study.py` | 中枢漂移专项：利率、风险溢价、ROE、分红率四个驱动推导各指标中枢；18 个情景 + 81 组全组合 → `results/drift_study.json` |
| `report.py` + `report_assets/` | 生成 `report.html` |

## 复现

```bash
python analysis.py && python summarize.py && python extra.py && python study.py && python report.py   # 4 核约 12–15 分钟，仅依赖 numpy / pandas
```
