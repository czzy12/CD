# Web GUI 模块映射清单 v1

本清单只描述 schema 1.16 字段路径和只读展示映射，不记录客户账号、身份信息、完整流水或客户文件绝对路径。所有 Adapter 只读取既有结果，不扫描 `original_transactions` 生成候选，也不重算业务规则。

| 模块 | module_id | schema 1.16 来源 | 旧 GUI 展示来源 | display_kind | transaction_id | 证据 | 筛选 | 当前状态 / 原因 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 下定与购车 | `purchase` | `result.observations[purchase_prepayment_funding_candidates].value.purchase_candidates[]` 及其既有 `prior_income_candidates[]` | `_purchase_rows` / `_purchase_overview` | `transaction_list` | 有 | 支持 | 状态、分类、来源、关键词、日期 | `available`；直接复用既有观察；边界说明“此前收入只作时间并列，不表示资金来源” |
| 敏感交易 | `sensitive` | `result.observations[sensitive_transaction_context_candidates].value.candidates[]` | `_sensitive_rows` / `_sensitive_overview` | `transaction_list` | 有 | 支持 | 状态、分类、来源、关键词、日期 | `available`；只表示已有文字共现候选 |
| 经营痕迹 | `business` | `result.observations[ai_business_relevance_candidates].value.deterministic_candidates[]` 与既有 `ai_candidates[]` | `_business_rows` / `_business_overview` | `transaction_list` | 结果有时存在 | 支持 | 状态、分类、来源、关键词、日期 | 当前两案为 `unavailable`；观察不可用且没有正向候选，不调用 AI、不展示排除项冒充候选 |
| 资金与余额 | `funds_balance` | `result.observations[large_transaction_candidates].value.candidates[]` | `_fund_rows` / `_fund_overview` | `transaction_list` | 有 | 支持 | 状态、分类、来源、关键词、日期 | `available`；本阶段展示既有大额交易候选，不重算资金路径或余额规则 |
| 申报对照 | `declaration` | `result.observations[declaration_flow_cross_checks].value.items[]` 与 `display_only_items[]` | `_declaration_items` / `_declaration_rows` / `_declaration_overview` | `summary` | 可选 | 有 ID 时支持 | 状态、分类、关键词 | 当前两案为 `empty`；稳定结果存在但没有项目，显示真实空状态 |
| 人工核实 | `manual_review` | `result.observations[manual_verification_questions].value.questions[]` | `_manual_overview` | `summary` | 取既有首个证据 ID | 有 ID 时支持 | 状态、分类、关键词 | `available`；只展示既有问题，不创建查看进度 |
| 用车记录 | `vehicle_records` | 无稳定后端结果 | 无 | `disabled` | 无 | 不支持 | 无 | `not_implemented` |
| 居住/工作轨迹 | `life_trajectory` | 无稳定后端结果 | 无 | `disabled` | 无 | 不支持 | 无 | `not_implemented` |
| 消费水平 | `consumption_level` | 无稳定后端结果 | 无 | `disabled` | 无 | 不支持 | 无 | `not_implemented` |

## 状态规则

- `available`：schema 中有稳定结果且当前案件有可展示项。
- `empty`：模块结果结构稳定，但当前案件没有候选。
- `unavailable`：模块结构存在，但当前结果明确不可用或含义不足以安全展示。
- `not_implemented`：当前 schema/后端没有稳定结果，本阶段不实施。

模块数量、状态、筛选能力和证据支持均由 Python `ModuleRegistry` 返回；React 不硬编码案件数量或业务状态。
