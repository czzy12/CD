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
build_bankflow_result(transactions, metadata=None) -> dict
write_bankflow_json(result, path) -> Path
```

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

当前实现的 `schema_version: "1.1"` JSON 必须包含：

```json
{
  "schema_version": "1.1",
  "module": "bankflow",
  "analysis_source": "original_transactions",
  "created_at": "",
  "source_files": [],
  "result": {
    "summary": {},
    "original_transactions": [],
    "facts": []
  },
  "manual_review": {
    "required": true,
    "items": []
  },
  "warnings": [],
  "notes": []
}
```

每笔 `original_transactions` 必须包含 `transaction_id`、`source_file_id`、`source_file`、`evidence_locator`、标准金额字段和原始字段；金额以两位小数字符串输出，避免 JSON 浮点精度变化。`result.facts[]` 只输出由原始交易直接复算的事实（笔数、金额、期间和可用余额），每项必须包含 `fact_type`、`value` 与 `evidence_transaction_ids`。`manual_review.items[]` 必须包含 `scope`、`reasons` 与 `evidence_transaction_ids`；交易范围项目保留交易、来源文件和页/行定位。该接口不读取调整结果，不输出风险定性或调查结论。

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
