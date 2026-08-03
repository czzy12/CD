# Web GUI 步骤 12B-0B：真实 schema 1.16 结果验收报告

验收时间：2026-08-02（Asia/Shanghai）

## 结论

当前结论：**来源状态数据链及源码实际 WebView2 窗口专项复验均已通过；12B-0B 阻断已解除，建议下一步进入 12B-1**。

首次验收时，实际 WebView2 源码窗口和打包后的 EXE 已完成两案加载、筛选、交易证据回跳、无重启切案、会话隔离及 DTO 边界检查，这些项目均通过。随后已修复 case-025 来源复核状态在 Worker 与标准结果之间丢失的问题：状态现在进入正式 `source_files[]`、JSON、CaseSession DTO 和 Web 案件头，不由前端猜测或重算。

## 验收对象

| 对象 | 大小 | SHA-256 |
| --- | ---: | --- |
| `case-025.json` | 16,535,425 bytes | `FAA8F5BC9738F48D5989BE4AED5ACA53FD111DDDC3EE0B388D1C7F265615C2A4` |
| `case-129.json` | 22,291,999 bytes | `3B3B2640CE957BD18AF0C0E2EBCD72A8A8F75829DA22BAF805DBE3BE241B88CE` |
| `BankFlowWebView2Spike.exe` | 12,011,933 bytes | `6A8E4EDF97F1716A0408DAD6F12DC1994189DB5F6484B9EC357A74F6D4A4A69D` |

两份结果均为 `schema_version == "1.16"`、`module == "bankflow"`。case-025 已按修复后的正式链路重新导出，因此哈希按预期更新；客户原资料的导出前后 SHA-256 快照一致。

## 实际 WebView2 验收

### case-025

- 案件头：`case-025`；时间范围 `2025-06-03—2026-06-06`；界面显示 10 个来源、schema 1.16。
- 下定购车摘要：直接命中 6、订金/定金 0、此前收入 0、待判断 0。
- 全部筛选 6 条，直接命中筛选 6 条；50 条分页规格下为第 1/1 页。
- 抽查并点击 3 笔，Inspector 显示的交易 ID 与列表及后端证据精确一致：
  - `tx:442de6c…f919fc`
  - `tx:442de6c…3863dd`
  - `tx:8952765…2c23fa`

### case-129

- 案件头：`case-129`；时间范围 `2025-05-01—2026-05-12`；界面显示 4 个来源、schema 1.16。
- 下定购车摘要：直接命中 9、订金/定金 0、此前收入 22、待判断 22。
- 全部筛选 31 条，直接命中筛选 9 条，此前收入/待判断筛选 22 条；50 条分页规格下为第 1/1 页。
- 抽查并点击 3 笔，Inspector 显示的交易 ID 与列表及后端证据精确一致：
  - `tx:1d76c42…dede38`
  - `tx:1d76c42…214cca`
  - `tx:1d76c42…8392ee`

### 无重启切案

从 case-025 直接切换到 case-129 后：

- 案件头、列表和摘要已替换为 case-129；
- Inspector 关闭，选中行数量为 0；
- 使用 case-025 的旧 `transaction_id` 查询证据返回 `TRANSACTION_NOT_FOUND`；
- 未发现旧列表、旧 Inspector 或旧交易 ID 串入新案件。

## 打包 EXE 复验（修复前基线）

使用打包后的 `BankFlowWebView2Spike.exe`、实际 Edge Chromium WebView2 和同一套前端资源重复执行上述两案验收。结果为：

- 两案均成功加载；
- 两案各 3 笔交易 ID 与证据匹配；
- 无重启切案后 Inspector 和选中状态清空；
- 旧交易 ID 返回 `TRANSACTION_NOT_FOUND`；
- DTO 边界检查通过；
- 进程正常退出，收尾检查未发现残留的验收 EXE 或专用 Python 进程。

以下机器可读摘要文件已由修复后的专项复验覆盖，当前记录的是 WebView2 `frontend ready` 超时，而不是修复前的通过结果：

- `D:\Investigator PDF\outputs\schema116-validation\qa-source-cli.json`
- `D:\Investigator PDF\outputs\schema116-validation\qa-packaged-exe.json`

摘要不包含原始交易内容。修复前的通过结果及短 ID 已记录在本报告前述章节；修复后不重复声称实际窗口已通过。

## 性能记录

| 案件 | JSON 大小 | 加载 API / 墙钟 | RSS 前 / 后 | RSS 增量 | 50 条页 API / 墙钟 | 当前页载荷 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| case-025 | 16.53 MB | 101.051 / 101.139 ms | 102,817,792 / 133,480,448 bytes | 30,662,656 bytes（约 29.25 MiB） | 0.102 / 0.143 ms | 2,648 bytes（items 2,526 bytes） |
| case-129 | 22.29 MB | 183.324 / 183.383 ms | 133,894,144 / 156,200,960 bytes | 22,306,816 bytes（约 21.27 MiB） | 0.191 / 0.272 ms | 11,905 bytes（items 12,281 bytes，界面统计口径） |

单笔证据耗时（API / 墙钟 / 点击至 Inspector）：

- case-025：`1.096/1.162/10.320 ms`、`1.626/1.767/8.607 ms`、`2.361/2.498/8.513 ms`。
- case-129：`0.875/0.966/22.223 ms`、`0.637/0.707/14.324 ms`、`0.578/0.632/5.269 ms`。
- 单笔证据响应载荷约 1,169—1,266 bytes。

注：RSS 为同一验收进程连续切案时的进程工作集快照，增量不能直接等同于单案长期常驻内存。

## 前后端数据边界

分别检查了列表页响应和单笔证据响应：

- 前端列表只收到当前筛选、当前页的轻量 DTO；
- Inspector 只收到当前交易的证据 DTO；
- 响应中未出现 `original_transactions`、`standard_result` 或结果文件绝对路径；
- 未把完整 schema 1.16 结果或全部原始交易传给前端。

## 已修复：case-025“需复核”来源

正式 Worker 处理 case-025 时共有 11 个输入来源，其中 1 个来源状态为“需复核”。修复前导出 JSON 中只有 10 个 `source_files`，且 `warnings` 为空。

现已在既有 `source_files[]` 来源结构中正式保存 `status` 与 `review_reason`。Worker 将内部中文状态映射为稳定的 `included/review` 值；CaseSession 只向前端返回复核来源计数、来源文件名和原因。新 case-025 JSON 含 11 个来源、正好 1 个 `review` 来源，该来源交易数为 0 且原因非空；3798 笔原交易和 3798 项证据索引保持完整。新旧 `result` 的唯一差异是既有观察中的运行时间戳 `run_at`。

前端案件头已增加“1 来源需复核”提示，并通过标题提示显示来源文件名与原因。TypeScript 构建与 DTO 单元测试通过。

### 修复后源码实际窗口专项复验

2026-08-03 使用当前源码完成专项复验：

- WebView2 Runtime 为 `150.0.4078.105`，实际渲染器为 `edgechromium`；
- `pywebviewready` 正常触发，最小 JS→Python `ping()` 返回 `pong`；
- case-025 页面显示“11 来源 · 1 来源需复核 · schema 1.16”；
- 复核原因标题与 schema 1.16 JSON 中该来源的 `review_reason` 精确一致，不由前端判断或硬编码；
- schema 中正好 1 个 `review` 来源，其他 10 个来源没有被误标；
- 在 case-025 选中交易并打开 Inspector 后，不重启程序切换至 case-129，来源复核提示、选中行及 Inspector 均清空；
- case-129 显示 4 个来源，没有残留“1 来源需复核”；
- 再切回 case-025，11 个来源及“1 来源需复核”提示稳定恢复，Inspector 和选中状态保持清空；
- 窗口关闭后没有残留本轮 pywebview/Python 验收进程。

机器可读的脱敏专项摘要保存在 `D:\Investigator PDF\outputs\schema116-validation\qa-source-review-roundtrip.json`；摘要只记录计数、状态和布尔核验结果，不保存 `review_reason` 原文。

本次按范围只复验当前源码，不重新打包、不修改 spec、不测试旧 EXE。最新来源状态功能的打包复验暂缓至 12B-1 阶段收口；当前无需重新打包。此前已经通过的性能、6 笔交易证据回跳及完整双案证据验收未重复执行。

## 自动化与构建检查

- WebView2/API/桥接/结果适配定向测试：23 项通过，1 项按环境跳过。
- 本次来源状态定向测试：3 项通过。
- 本次 WebView2 相关定向测试：28 项通过，1 项按环境跳过。
- 项目完整虚拟环境全量回归：334 项通过，2 项按环境跳过。
- TypeScript 类型检查与 Vite 生产构建：通过。
- `git diff --check`：通过。
- 未提交、未推送。

## 测试事件说明

早期一次桌面焦点激活失败，验收脚本的本地 JSON 路径被输入到用户已打开的另一浏览器窗口。发现后立即停止所有全局键鼠自动化，后续改为 WebView2 进程内 DOM/桥接验收。应用自身未调用外部 API；但该误输入可能使浏览器尝试把本地路径当作地址或搜索词，因此不能把那次操作表述为“整个桌面测试期间绝无浏览器网络请求”。
