# Web GUI 桥接契约 v2

## 版本与能力

- `api_version`: `1`
- `frontend_version`: `0.2.0`
- `schema_versions_supported`: `["1.16"]`
- `renderer`: `edgechromium`
- 能力：`load_standard_result`、`review_modules`、`paged_items`、`evidence_inspector`、`source_review`、`theme`、`case_switch`

不声明 AI、客户信息、位置、网络或报告导出能力。前端启动先调用 `get_app_state()`；API 版本不兼容时停止案件加载并显示中文错误。

## API 信封

所有公开方法返回：

```text
ApiEnvelope<T> = {
  ok,
  data,
  error: { code, message } | null,
  meta: { request_id, elapsed_ms, payload_bytes }
}
```

未知异常只写 Python 日志，对前端返回 `INTERNAL_ERROR`，不泄露堆栈或绝对路径。

## 白名单 API

| 方法 | 用途 |
| --- | --- |
| `get_app_state()` | 版本、渲染器、能力、加载状态和当前会话 |
| `select_standard_result()` | Windows 原生文件选择，仅 `*.json` |
| `load_standard_result(path)` | 内部/验收加载入口；绝对路径不返回前端 |
| `get_case_header()` | 案件头和来源复核数量 |
| `get_review_modules(case_session_id)` | 模块目录 |
| `get_module_summary(module_id, case_session_id)` | 模块摘要 |
| `list_module_items(module_id, page, page_size, filters, sort, case_session_id)` | 统一分页和筛选 |
| `list_source_reviews(case_session_id)` | 仅返回 `status == review` 的来源 |
| `get_evidence(transaction_id, case_session_id)` | 单笔精确证据 |
| `close_case()` | 清理完整结果、路径、Adapter、Registry 与会话 ID |

12B-0 已验证的购车兼容方法暂时保留，供技术切片回归；正式前端只调用统一模块 API。

## 会话隔离

- Python 每次成功绑定案件创建新的 `case_session_id`，并递增 `case_revision`。
- 当前结果绝对路径只保存在 `CaseSession`。
- 模块、分页、来源复核和证据响应携带当前 `case_session_id`。
- 请求可携带期望会话 ID；不一致返回 `STALE_CASE`。
- React 同时检查本地当前会话、响应会话和请求序号；旧响应不更新列表、Inspector、筛选或错误状态。
- 关闭案件清除完整结果、Registry、Adapter、路径和会话 ID。

## DTO 边界

`ReviewItemDTO` 只包含显示所需字段和可选 `transaction_id`。`PagedModuleItemsDTO` 只包含当前页，默认 50 条，允许 25/50/100。`SourceReviewItemDTO` 只包含稳定来源引用、显示名、类型、状态、schema `review_reason`、必要解析器诊断及是否生成交易。

禁止返回完整 `standard_result`、完整 `original_transactions`、完整原交易、客户绝对路径、完整账号、身份证号或 Python 堆栈。

## 证据契约

仍使用已验证的精确链路：

```text
transaction_id
→ result.evidence.transaction_index
→ original_transaction_index
→ result.original_transactions[index]
→ transaction_id 一致性校验
```

缺失索引返回 `TRANSACTION_NOT_FOUND`；越界、结构错误或 ID 不一致返回 `EVIDENCE_UNAVAILABLE`。默认返回脱敏字段；完整允许内容只在用户主动展开当前单笔证据时显示。

## 网络与资源

正式入口和技术切片共用 `web_frontend/dist`、资源内联、CSP 和外网拦截。运行时不启动 Vite、不监听端口、不依赖 Node.js/npm；仅 debug 模式允许开发者工具。
