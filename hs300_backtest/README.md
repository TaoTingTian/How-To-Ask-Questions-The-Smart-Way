# 沪深300 Plan C 回测与 Plan D

- `REPORT.md`：回测结果、过拟合诊断、评价与修改建议（**先读这个**）
- `PlanD_rulebook.md`：修改后的策略规则书
- `PlanC_rulebook_original.md`：原规则书
- `engine.py`：回测引擎（复现 Plan C 的全部清仓/回补日期）
- `analysis.py` / `plan_d.py` / `extra_checks.py`：诊断脚本，输出到 `results_*.txt`

运行：`python3 analysis.py && python3 plan_d.py && python3 extra_checks.py`（需 pandas、numpy）

补 2005–2011 数据：按相同格式（`date,value`；price.csv 为 `日期,收盘点位,...`）把更早的行加到 `data/*.csv` 头部，重新运行即可。
