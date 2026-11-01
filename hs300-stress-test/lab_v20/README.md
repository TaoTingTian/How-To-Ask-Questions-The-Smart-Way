# 回测实验室加入 V2.0

把 V2.0（每日净额）加入“沪深300策略回测实验室”页面（https://claude.ai/artifact/QsNvxSjoRYSrwwoy4Bbu5i）。

- `engine.js`：页面引擎，新增 `runV20`（经 `runStrategy` 的 `cfg.mode === 'v20'` 分派）和 `IRP2 = DY + g − y`。
- `compute.js`：在页面的 90 条路径上（10 条主路径 + 80 条新种子）计算 V2.0 各报告字段；同时用同一口径重算原方案，用于校验口径。
- `build.py` + `v20page.js`：并入 RES、修改报告代码、新增“5c · V2.0 回测”页。
- `results_v20.json`：compute.js 的输出。

脚本里的路径指向本次会话的临时目录，复现时需要改成本地路径。
