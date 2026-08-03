# Web GUI 桥接契约 v1

状态：GUI 步骤 12B-0 集成切片草案。当前运行环境在 `QWebEngineProfile` 初始化阶段阻塞，本契约已通过 Python 定向测试，但尚未完成实际桌面端到端验收。

## 边界

- 完整 schema 1.16 `standard_result`、`original_transactions` 和 `evidence` 只保存在 Python `CaseSession`。
- React 只接收案件头、购车摘要、当前页交易和当前一笔证据。
- 候选来自既有 `purchase_prepayment_funding_candidates` observation；Bridge 和 React 不重新扫描关键词或重算业务结论。
- 证据复用 `bankflow_v2.standard_result_view.evidence_transaction()` 的精确索引链。
- 默认本地模式拦截 `http`、`https`、`ws`、`wss`；仅允许 `file`、`qrc`、`data`、`blob`、`about`。显式 `--dev-url` 只允许 `127.0.0.1`。

## 统一信封

成功：

```json
{"ok":true,"data":{},"error":null,"meta":{"request_id":"hex","elapsed_ms":1.25,"payload_bytes":512}}
```

失败：

```json
{"ok":false,"data":null,"error":{"code":"NO_CASE","message":"尚未打开标准结果"},"meta":{"request_id":"hex","elapsed_ms":0.1,"payload_bytes":220}}
```

Python 堆栈、内部异常对象、客户绝对路径和凭据不得进入信封。

## Bridge 接口

| 方法 | 参数 | 返回 data | 职责 |
| --- | --- | --- | --- |
| `frontend_ready_event` | 无 | `AppStateDTO` | 记录前端就绪 |
| `get_app_state` | 无 | `AppStateDTO` | 查询连接和案件状态 |
| `select_standard_result` | 无 | `CaseHeaderDTO` | 使用原生文件选择框并加载结果 |
| `load_standard_result` | `path` | `CaseHeaderDTO` | 加载并用现有逻辑校验 schema 1.16 |
| `get_case_header` | 无 | `CaseHeaderDTO` | 返回案件头最小摘要 |
| `get_purchase_summary` | 无 | `PurchaseSummaryDTO` | 返回既有购车 observation 摘要 |
| `list_purchase_transactions` | `page, page_size, filters_json` | `PagedTransactionsDTO` | Python 端分页和既有分类过滤 |
| `get_evidence` | `transaction_id` | `EvidenceDetailDTO` | 精确返回当前一笔证据 |
| `close_case` | 无 | `AppStateDTO` | 释放完整结果和索引引用 |

`page_size` 只允许 `25/50/100`，默认 `50`。当前筛选值为 `all/direct/deposit/prior_income/review`，只过滤适配器已经读取到的分类。

## DTO

- `AppStateDTO`：`frontend_ready, case_loaded, loading, mode`
- `CaseHeaderDTO`：`case_name, period_start, period_end, source_count, transaction_count, analysis_status, evidence_status, schema_version, review_source_count, review_sources`
- `review_sources[]` 只包含正式 `source_files[]` 中状态为 `review` 的来源文件名和复核原因；不读取 Worker 私有对象，不传客户目录绝对路径。
- `PurchaseSummaryDTO`：总数、直接命中、订金/定金、此前收入、待判断、既有分类计数和边界说明
- `TransactionListItemDTO`：`transaction_id, date, direction, amount, counterparty, matched_text, interpretation, source_name, category, review_status`
- `PagedTransactionsDTO`：当前页 items、页码、总数、筛选、查询耗时和 payload 大小
- `EvidenceDetailDTO`：当前交易定位、业务字段、引用/完整性状态、默认脱敏字段和用户主动展开后的单笔完整字段

## 错误码

`NO_CASE`、`FILE_NOT_FOUND`、`INVALID_JSON`、`SCHEMA_INCOMPATIBLE`、`INVALID_ARGUMENT`、`TRANSACTION_NOT_FOUND`、`EVIDENCE_UNAVAILABLE`、`FRONTEND_NOT_READY`、`INTERNAL_ERROR`。

## 证据失败关闭

`transaction_id` 必须精确命中 `evidence.transaction_index`。索引缺失返回 `TRANSACTION_NOT_FOUND`；序号越界、原交易 ID 不一致及其他索引异常返回 `EVIDENCE_UNAVAILABLE`。不遍历全表猜测替代交易。
