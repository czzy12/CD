# PDF流水项目集成契约

## 目的

本文件是代码仓库内的开发约束，用于保证 PDF 流水识别项目后续可以稳定接入车贷报告自动化总项目。

Obsidian 记忆文件：

```text
D:\OneDrive\应用\remotely-save\Note Data\Vibe Coding\PDF流水\项目集成记忆.md
```

总项目规范：

```text
D:\OneDrive\应用\remotely-save\Note Data\车贷\自动化项目\05-子项目与总项目集成规范.md
```

## 当前边界

本项目负责：

- PDF / Excel / 微信流水识别。
- 银行解析器适配。
- 原始明细标准化。
- 月度统计。
- 流水调整测算。
- Excel 导出。
- 标准 JSON 导出。
- 后续收入佐证 Word 填写。

本项目不负责：

- 车贷产品路径判断。
- 征信说明。
- 企业信息说明。
- 完整调查报告生成。
- 系统粘贴文本总控。

## 必须保持稳定的内部接口

### Transaction

`bankflow_v2/models.py` 中的 `Transaction` 是核心标准模型。

新增银行解析器必须输出 `Transaction` 列表。

不要让银行解析器直接输出 Word、Excel 行或自然语言结论。

### StatementMetadata / TransactionList

`bankflow_v2/models.py` 中的 `StatementMetadata` 是账户和文件级字段容器，承载户名、账号、查询区间、文件生成时间、分段标识、总页数及对应来源、置信度和人工复核信息。

`TransactionList` 继承 `list[Transaction]` 并通过 `metadata` 属性携带 `StatementMetadata`。解析器需要返回文件级字段时使用该容器；既有只按交易列表迭代、排序、汇总的调用保持兼容。

文件级字段不得为了省事重复写入每笔 `Transaction`。调用方可使用 `get_statement_metadata(transactions)` 安全取得元数据；普通列表返回空的 `StatementMetadata`。

### Summary

`bankflow_v2/summary.py` 是统一统计口径。

GUI、Excel 导出、未来 JSON 导出和 Word 填写都应复用这里的统计结果，避免多套口径。

### Adjustment

`bankflow_v2/adjustment.py` 是识别后的测算层。

调整结果不得覆盖原始统计，必须和原始结果并存。

## 标准结果导出接口

已实现：

```text
bankflow_v2/result_export.py
```

对外提供：

```python
build_bankflow_result(transactions, metadata=None, verification_context=None) -> dict
write_bankflow_json(result, path) -> Path
```

`verification_context` 是可选外部核实上下文。当前仅接受 `confirmed_owned_accounts[]`，每项必须包含完整账号、稳定 `account_ref`、`verification_status: "confirmed"` 和 `ownership_evidence_ref`；缺少上下文时既有调用保持兼容。

案件文件夹账户发现与一次性角色确认由：

```text
bankflow_v2/case_accounts.py
```

提供：

```python
discover_case_accounts(case_folder) -> dict
confirm_case_roles(discovery, role_by_account_ref) -> dict
verification_context_from_manifest(manifest) -> dict
write_case_manifest(manifest, path) -> Path
```

发现只接受文件抬头中户名、完整账号均可靠的 `StatementMetadata`；文件夹只定义案件边界，不自动认定同一主体。角色确认只引用 `account_ref`，不得要求用户重新录入完整账号；`generic_pdf` 和未确认混合字段不得用于账户发现。

后续新增收入佐证 Word 填写时，建议新增：

```text
bankflow_v2/word_fill.py
```

建议提供：

```python
fill_income_proof_docx(result, template_path, output_path) -> None
```

Word 填写只读取标准结果，不直接解析 PDF。

## 2026-06-01 已新增收入佐证 JSON 草稿导出

当前已新增：

```text
bankflow_v2/income_proof_export.py
```

GUI 已新增：

```text
导出佐证JSON
```

该导出用于生成 `D:\report workflow\income_proof_tool\INPUT_SCHEMA.md` 所定义的自雇流水佐证输入 JSON 草稿。

当前导出边界：

- 自动导出流水月度统计。
- 自动把金额从元转换成万元。
- 自动区分个人/微信与对公流水。
- 客户姓名、系统月收入、企业信息、账号、地区等仍由人工补充或未来 API 填入。
- 对公流水默认不启用，必须人工确认后再启用。
- 暂不自动混入流水调整结果，避免原始识别口径和人工测算口径混杂。

## 标准 JSON 要求

当前实现的 `schema_version: "1.7"` JSON 必须包含：

```json
{
  "schema_version": "1.7",
  "module": "bankflow",
  "analysis_source": "original_transactions",
  "created_at": "",
  "source_files": [],
  "result": {
    "summary": {},
    "original_transactions": [],
    "facts": [],
    "indicators": [],
    "observations": []
  },
  "manual_review": {
    "required": true,
    "items": []
  },
  "warnings": [],
  "notes": []
}
```

每笔 `original_transactions` 必须包含 `transaction_id`、`source_file_id`、`source_file`、`evidence_locator`、`neutral`、标准金额字段和原始字段；金额以两位小数字符串输出，避免 JSON 浮点精度变化。`neutral` 是复算事实和指标参与范围所需的布尔值：`true` 表示该原始交易不进入收支统计及 v1B 非中性交易指标，不能仅凭金额为零或文字方向推断。`result.facts[]` 只输出由原始交易直接复算的事实（笔数、金额、期间和可用余额），每项必须包含 `fact_type`、`value` 与 `evidence_transaction_ids`。

`result.indicators[]` 只读取 `original_transactions`，每项必须包含 `indicator_type`、`value`、`parameters`、`evidence_transaction_ids` 与 `field_coverage`。v1A 固定包含：

- 1/3/7 天收入后支出时间邻近观察，窗口起止均含边界；该指标只表示时间共现，不表示支出资金来源于某笔收入。
- 收入和支出交易对手集中度；对手身份优先使用可靠账号，其次使用可靠名称，只接受非空且 `field_confidence == 1.0` 的现有字段。
- 指标可用性与交易 ID、来源文件 ID、页/行定位的证据覆盖。

v1B 固定包含：

- 收入连续性：按首末交易所在自然月的连续月桶，输出有收入月份、无收入月份、覆盖率和最长连续收入月份数；含两端月份，不解释为工资稳定性或经营真实性。
- 余额观察：按 `source_file_id + 自然日` 选择当日最后一笔有余额交易，输出余额快照分布；不得解释为账户日均余额或资金充足。
- 金额形态：输出非零收支绝对金额可被 1/100/1000 元整除的笔数与占比；不得解释为流水包装。
- 收支规模与近期变化：以末笔交易所在月为锚，比较最近 3 个自然月与此前 3 个自然月；不足连续 6 个月时比较不可用，边界月可能不完整。

对手字段缺失或置信度不足时必须输出不可用状态和覆盖率，不得从摘要、备注、原始混合文本或 `generic_pdf` 猜测。可靠文字观察、外部 `event` / `case_context` 参数和跨资料比对不属于当前 `result.indicators[]`，其边界登记于 `docs/流水事实指标字典_v1.md`。`manual_review.items[]` 必须包含 `scope`、`reasons` 与 `evidence_transaction_ids`；交易范围项目保留交易、来源文件和页/行定位。该接口不读取调整结果，不输出风险定性或调查结论。

v1C 新增独立 `result.observations[]`，包含 `confirmed_own_account_transfer_candidates`：

- 仅匹配外部上下文中已确认归属、带稳定引用和证据引用的完整账号。
- 交易侧只接受非中性、非零收支、存在交易 ID、完整对手账号且 `field_confidence.counterparty_account == 1.0` 的记录。
- 账号只移除空白和连字符后做完整精确匹配；不按姓名、摘要、备注、账号尾号或掩码猜测。
- 输出匹配方向、时间、金额、账户引用、归属证据引用和交易证据 ID，不回显外部账户集合。
- 缺少有效账户集合时输出 `confirmed_owned_accounts_unavailable`；存在账户集合但可靠完整对手账号覆盖为 0 时输出 `reliable_counterparty_accounts_unavailable`。两种情况均为 `available: false`，不得把零覆盖解释为“已检查且无本人互转”。
- 匹配结果不表示资金来源、资金闭环或账户实际控制关系。

跨笔资金闭环、拆分/合并交易配对、手续费容差和唯一资金路径归因不属于 v1C。

v1D 新增 `confirmed_own_account_transfer_pair_candidates`：

- 仅在已确认账户同时提供其可靠来源文件 ID 映射时可用；上下文由案件 manifest 自动提供该映射，外部手工上下文缺失时明确输出不可用原因。
- 双方交易必须各自来自对应已确认账户的来源文件、可靠完整对手账号相互精确匹配、同一自然日、金额完全相等且方向相反；不会按姓名、摘要、备注、尾号、掩码、金额容差、拆分或合并推测。
- 输出唯一双边配对、单边候选、歧义候选和不可用原因，并保留双方交易 ID、账户引用和金额日期证据；不回显完整账号。
- 配对结果仅为可复核候选，不表示资金来源、资金闭环、实际控制、风险或案件结论。

微信支付扣款银行流水关联新增独立 `wechat_payment_bank_debit_link_candidates`，不属于 v1C 或 v1D：

- 微信来源文件须在外部上下文 `confirmed_owned_payment_sources` 中以 `wechat_account` 记录确认归属，并同时具备稳定 `account_ref`、归属证据引用、姓名、完整身份证号和微信号；交易来源文件 ID 必须精确对应该记录。
- 银行扣款来源文件必须精确映射到一个已确认完整银行账户；微信交易方式中的银行卡尾号须唯一对应该账户。
- 仅匹配同一自然日、精确同额的支出，且银行交易文字同时含“财付通”和“微信支付”、微信交易对方的规范化商户组成部分唯一命中银行文字。多候选只输出歧义，绝不强配。
- 输出只保留交易 ID、账户引用和证据引用，不回显完整银行卡号、身份证号或微信号；它不表示本人账户互转、资金来源、资金闭环、实际控制或案件结论。

支付宝银行扣款关联当前固定输出 `alipay_payment_bank_debit_link_pending_field_confirmation`；未取得支付宝原件字段确认前，不进行自动匹配。

字段变化必须更新 `schema_version`。

## 新增银行解析器规则

新增银行或新版式时：

1. 新增或修改专用解析器。
2. 接入 `auto_detect.py`。
3. 接入 `pipeline.py`。
4. 增加或更新回归样本。
5. 更新 `tools/regression_cases.json`。
6. 更新 `技术变更记录.md`。
7. 更新 `银行适配手册.md`。
8. 跑编译和回归。

标准验证：

```powershell
python -m py_compile bankflow_v2\summary.py bankflow_v2\pipeline.py bankflow_v2\adjustment.py gui_v2.py tools\regression.py
python tools\regression.py --all
```

如果回归失败是因为样本文件不存在，记录为样本缺失，不等同于解析失败。

## 禁止事项

不要把核心逻辑写死在 GUI 事件里。

不要让解析器直接生成 Word。

不要用调整后统计覆盖原始统计。

不要让车贷总项目依赖 GUI 表格内容。

不要在代码里写死个人桌面样本路径作为业务逻辑。

## 集成原则

未来车贷报告自动化总项目只读取：

- 标准 JSON。
- 收入佐证 Word。
- 必要时读取导出 Excel。

总项目不应该重新实现 PDF 流水解析逻辑。

一句话：

```text
PDF流水项目负责把流水变成可信结构化结果；
车贷总项目负责把结构化结果整合进报告流程。
```
