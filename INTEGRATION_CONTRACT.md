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

流水核查 MVP 的最小案件上下文由：

```text
bankflow_v2/case_context.py
```

提供：

```python
build_case_context(case_id, sources) -> dict
```

`sources[]` 必须显式提供 `source_ref / source_role / text`。当前允许的来源角色为：

- `system_customer_data`：系统复制的客户信息；
- `customer_manager_description`：客户经理描述，固定为未核实；
- `risk_investigation_report`：风控调查报告，只保存为人工报告叙述。

系统复制文本在“本人分析/个人分析”边界停止；客户经理描述字段即使位于系统页面中，也按字段角色单独标记。输出只包含流水搜索所需的姓名/主体、单位、明确行业、工作/居住/上牌地点、车型和经销商等最小上下文及来源状态，不写入 `Transaction`，也不自动进入当前标准结果 JSON。后续关键词、AI 经营关联和申报对照只能读取该上下文与 `original_transactions`，不得直接从 TXT 或 PDF 自由推断。

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

当前实现的 `schema_version: "1.12"` JSON 必须包含：

```json
{
  "schema_version": "1.12",
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

schema 1.8 在 `result.observations[]` 新增三项流水核查 MVP 确定性观察：

- `controlled_keyword_candidates`：只搜索非空且 `field_confidence == 1.0` 的现有标准文字字段；输出命中词组、命中字段、完整交易上下文、交易 ID 和证据定位。基础词表覆盖下定购车、用车轨迹、经营收入和敏感交易；单位、行业、地点、车型及经销商动态词只来自显式 `case_context.search_context`。不对“车、电、资、法”等单字做无条件匹配。
- `industry_text_search_coverage`：按 `source_file_id` 输出有效收支交易数、可识别对手、明确摘要/用途、商户/商品字段和去重行业搜索覆盖。空值、掩码、占位及“转账、消费、商户消费、扫码付款、微信支付、电子汇入、其他”等通用值不算有信息量。该覆盖率不是行业相关交易占比或解析准确率。
- `purchase_prepayment_funding_candidates`：对下定/定金/品牌或经销商支出候选，并列此前 1/3/7 日收入；同额或收入/支出比例在 90% 至 110% 内视为近似金额，任意 `>=30000` 元收入也展示。允许跨案件来源作时间并列，但 `fund_source_attribution` 固定为 `false`。

`build_bankflow_result(..., case_context=...)` 的案件上下文仅供上述动态搜索使用；业务观察仍直接读取原 `Transaction` 列表并与 `original_transactions` 使用同一交易 ID，不改写交易，不建立平行交易模型。关键词无命中、搜索字段不可用和无下定支出候选必须分别返回明确原因；任何命中都不得输出异常、欺诈、资金来源或准入结论。

案件上下文除标准“行业/经营行业/主营业务”字段外，可从“工作介绍及收入情况（是否和流水匹配）”中提取带明确“主要是做/从事/经营”表述的工作内容，作为 `customer_manager_description`、`unverified` 的申报行业上下文。只提取明确工作内容；“其他生意”、信用卡用途、日常消费、位置轨迹或其他备注不得混入行业上下文，也不得从普通叙述或单位名称反向补造结构化行业值。

schema 1.9 新增 `ai_business_relevance_candidates`：

- 观察层保持模型无关；结果出口在未显式传入其他适配器时，可从环境变量装载 DeepSeek 官方 OpenAI 兼容接口。所有开关默认关闭，默认 `ai_data_authorization_missing`，不会进行网络调用。
- 只有 `enabled`、`data_authorized`、`retention_policy_confirmed`、`provider` 和 `model` 均明确配置后才允许调用；任一缺失、模型失败或返回无效时必须给出稳定降级原因，schema 1.8 的确定性结果保持完整。
- 显式申报单位或行业在可靠字段中的精确命中优先形成 `deterministic_exact_match`，不会被模型改写或覆盖。
- 模型输入只含交易 ID、月份、方向、金额和允许的可靠标准文字字段，不含来源路径、账号、原始 PDF 字段或证件信息。企业/商户名称须另行允许；疑似个人对手名称不进入模型输入。
- 模型输出只能使用 `directly_related`、`possibly_related`、`no_relation_evidence`、`undetermined`，必须逐条覆盖输入交易，只能引用输入中真实存在的交易 ID 和字段；否则整批记为 `ai_response_invalid`。
- 该观察只表示经营关联候选，不表示真实经营、实际经营主体、欺诈、包装或准入结论。

DeepSeek 运行配置不进入 JSON、不写入仓库，只从当前进程环境读取：

- `BANKFLOW_AI_API_KEY`：必填；只用于 `Authorization: Bearer` 请求头，禁止输出或持久化到报告。
- 当前经营关联 AI 任务固定为 `task_type=business_relevance`。缓存命名空间、输入指纹、提示版本和结果契约均按任务类型隔离；后续 `task_type=life_trajectory` 必须使用独立提示词、结果 schema 和验收样本，不得改变经营关联含义。
- 生活轨迹仅列入后续路线，当前第一版流水核查 MVP 不实现；详见 `docs/流水核查MVP后续路线图.md`。
- `BANKFLOW_AI_BASE_URL`：默认 `https://api.deepseek.com`，只接受 HTTPS。
- `BANKFLOW_AI_MODEL`：默认 `deepseek-v4-flash`。
- `BANKFLOW_AI_ENABLED`、`BANKFLOW_AI_DATA_AUTHORIZED`、`BANKFLOW_AI_RETENTION_CONFIRMED`：三者必须均为真。
- `BANKFLOW_AI_ALLOW_BUSINESS_NAMES`：为真时可发送满足组织标记的企业/商户名称；疑似个人名称仍留在本地。
- `BANKFLOW_AI_TIMEOUT_SECONDS`、`BANKFLOW_AI_BATCH_SIZE`：默认 60 秒、每批 50 笔。

适配器使用 `/chat/completions`、`response_format={"type":"json_object"}`，关闭思考模式并要求逐笔结构化结果。单项结构、字段引用或强度违规时拒绝该项并继续同批及后续批次，最终聚合失败原因；存在关键违规时本次 AI 候选整体不采用。网络、鉴权、超时或无法继续调用的系统错误仍立即终止。`tools/enable_deepseek_ai.ps1` 仅在当前 PowerShell 进程内设置授权和模型配置，并以隐藏输入读取 Key；`tools/test_ai_connection.py` 只用虚构交易检查连通性，不读取客户资料。

真实案例首次验收使用 `tools/run_ai_sample_acceptance.py`：只选择排除确定性单位/行业精确命中后、确有可发送可靠文字字段的交易，并强制读取 `--sample-manifest` 中冻结的 `development` 语义签名；该固定集合不得超过已配置单批大小，且必须显式传入 `--confirm-real-data`。输出本地 Markdown，逐笔保留分类、理由、使用字段原文和证据定位；小批结果不代表完整流水分布，也不得自动触发完整案例调用。`reserved_acceptance` 签名不用于反复调参。

小批验收通过并由用户单独确认后，完整语义验收使用 `tools/run_ai_full_acceptance.py`。该入口必须同时传入 `--confirm-real-data` 与 `--confirm-full-run`，先统计旧口径完整语义范围、确定性排除项及真正需模型判断的规范化唯一语义，再按唯一语义分批判断并展开回全部原交易ID。报告必须记录完整本地验收范围、送模唯一语义数、预计批次、展开结果、失败聚合、交易ID、使用字段及证据定位；关键违规或展开数不一致时失败关闭，但业务项错误不得阻止后续语义继续接受校验。请求正文与原始响应仅保存在用户指定的本地忽略目录缓存中，不写入仓库记录或终端；缓存不得包含 API Key 或授权头。

AI行业资格按整笔交易判断，而不是按单列排除：

- 可使交易进入AI候选池的语义证据字段为可靠的企业/商户名称、非通用摘要、备注、用途、商品说明和商户类别。
- `transaction_type`、`counterparty_bank`、月份、金额、方向和商户地点只作上下文，不能单独使交易入选，也不能单独支持行业相关。
- 一笔交易只要存在至少一个语义证据字段，就连同该笔允许发送的其他可靠上下文字段一起输入；“转账、扫码付款、二维码收款、商户消费”等通用类型不得抵消企业名称、用途或商品中的行业语义。
- 账号、证件、电话、本地路径、PDF页面和疑似个人对手名称不发送。个人名称不发送同时也是因为姓名本身通常不提供行业语义，不以其猜测经营关系。
- 固定样本清单创建时按 `source_file_id` 平衡来源并保存稳定语义签名；后续小批只按签名读取，不因提示词版本临时改变50条内容。

`tools/inspect_ai_input_coverage.py` 只在本地解析并统计上述候选数、输入字段和语义证据字段，不装载Key、不调用模型。该统计表示“存在可供AI判断的可靠文字”，不表示交易已经与申报行业相关。

schema 1.10 新增六项确定性资金观察：

- `large_transaction_candidates`：收入或支出单笔 `>=10000` 元的完整交易候选。
- `large_inflow_balance_paths`：收入 `>=30000` 元时，只在同一 `source_file_id` 内展示入账前余额及其后1/3/7日路径；参与累计的支出单笔须达到 `max(1000元, 入账额5%)`。累计比例100%为精确同额、90%-110%为近似总额、80%以上为短期大部分转出；当日末余额相对入账前余额的增量不超过入账额20%时标记低留存候选。所有标签必须同时输出公式输入和比例，且 `fund_source_attribution` 固定为 `false`。
- `end_of_day_balance_and_interest`：逐来源选择每个自然日最后一笔有余额交易，输出最低值、中位数、平均值和期末值；可靠文字命中结息/利息时逐笔展示并按季度汇总变化。微信等无余额来源明确返回 `reliable_balance_unavailable`。
- `top_counterparties`：按可靠可识别名称优先、完整可靠账号其次，分别输出收入和支出 Top 5；空值、掩码、占位和明显字母数字前缀拼接短姓名不进入排名。
- `cross_source_counterparty_occurrences`：只按可靠对手名称去空白后的精确同名，展示在两个及以上来源中的笔数、收支和证据；不作关系、归属或资金闭环推断。
- `explicit_purpose_candidates`：工资、报销、税费、工程款、材料款、采购、货款、商户收款、还款、结息/利息等可靠文字候选。

上述观察全部直接读取传入的原 `Transaction` 列表，证据 ID 与 `original_transactions` 一致；不得把短期金额/余额共现解释为某笔支出的资金来源。

schema 1.11 新增 `declaration_flow_cross_checks` 和 Markdown 验收视图：

- 只对显式 `case_context` 字段与可靠流水文字进行比对，固定使用 `direct_match`、`candidate_match`、`no_evidence_in_reliable_fields`、`unavailable` 四种状态。
- `no_evidence_in_reliable_fields` 仅表示在当前可靠字段及流水期间内未发现对应文字依据，`unavailable` 表示字段覆盖不足；两者均不得解释为客户陈述虚假。
- 每个对照项保留申报值、来源角色、核实状态、命中字段和交易证据 ID。客户经理描述继续标为未核实参考，不与系统客户资料或调查报告混为一类。
- `bankflow_v2.mvp_report.render_mvp_markdown()` 将来源范围、申报对照、关键词/下定前资金、资金余额、Top 5、跨来源同名、明确用途、AI降级状态和重要提示组织成首版文字验收视图。
- `tools/generate_mvp_acceptance.py` 只读取指定案件目录，复用自动识别、既有解析器和统一结果出口生成本地 Markdown；默认不调用外部模型，只有同一进程环境已明确启用上述全部授权开关时才允许调用。

schema 1.12 收紧AI行业输入并新增证据强度：

- 当前提示词版本为 `business-relevance-mvp-v11`；schema结构未变化。v6明确具体产品或服务优先形成中等候选，`货款`不得把同笔已有的具体产品或服务语义降为弱提示；v7为每笔附加仅由字段名派生的 `classification_constraints`，没有摘要、备注、用途、商品说明或商户类别时明确禁止 `directly_related`；v8要求所有正向分类均与申报行业或工作单位明确体现的行业语义相关，具体但无关的生活或通用服务不得判正向；v9固定建材、护栏、栏杆、围栏、塑木和园林景观设计在本案上下文中的具体相关语义，货款不得将其降为weak，同时排除无具体课题、产品、项目或行业对象的泛化咨询费、材料费和采购款；v10在AI语义入口排除纯字母数字代码备注；v11将业务硬边界、聚合校验、缓存和固定样本从提示依赖中剥离。
- AI行业模型只接收可靠企业/商户名称、非通用摘要、备注、用途、商品说明和商户类别；金额、日期、方向、银行名、账号、交易方式、地点、路径和原始PDF字段不发送。上述字段继续完整保留在本地 `original_transactions` 及确定性资金/轨迹观察中。
- `directly_related` 的 `evidence_strength` 固定为 `strong`，且必须引用摘要、备注、用途、商品说明或商户类别；仅有企业名称不能成为直接相关。
- `possibly_related` 使用 `medium` 或 `weak`：具体行业产品/服务但用途未确认时为中等候选；实业、贸易、科技、工业、工程等泛化类型或货款只能形成弱提示。
- `no_relation_evidence`、`undetermined` 的强度固定为 `none`。分类、强度、理由或使用字段不一致时整次响应不采用。
- 候选统计、唯一语义抽样和DeepSeek适配器共用同一规范化语义签名；同一企业/用途/商品组合只判断一次，再把相同分类、强度、理由和字段引用映射回全部原交易ID。任一代表记录缺失、重复或格式错误时，外层全量ID校验仍会拒绝整次结果。
- `classification_constraints` 必须由本地候选构建代码生成，模型不得覆盖。每项至少包含 `directly_related_allowed`、`directly_related_evidence_fields` 和 `maximum_allowed_strength`；只有企业/商户名称而没有有效用途文字时最高为 `medium`，纯代码不能开放直接证据门槛，泛化货款/咨询费等可进一步限制为 `weak`。
- 模型只返回 `semantic_judgement: strong / medium / weak / none / undetermined`、理由和使用字段；`directly_related / possibly_related / no_relation_evidence / undetermined` 由本地代码派生并再次校验。明确餐饮、便利店、话费、银行年费、医疗和打车等当前经营模块生活类由本地规则归为 `none`，不发送模型；混有明确经营用途时保留冲突字段并进入边界判断，不把不同字段拼成原件不存在的句子。
- AI经营判断只读取统一标准字段 `counterparty_name / summary / remark / purpose / product_description / merchant_name / merchant_category`；当前项目商品字段名为 `product_description`，不是 `goods_description`。`transaction_type / transaction_method / payment_method` 保留为可追溯标准字段，可供本地确定性排除，但不能单独构成行业证据。银行名、原始表头字符串、PDF列位置和字段排列不得改变行业判断标准。
- 原始交易、原始字段、标准字段来源、来源文件、交易ID及页/行证据继续保留；标准字段为空时降级或不可用，不回退全文扫描，不从其他不可靠字段猜测，也不把多个字段拼接成原件不存在的完整表述。
- 完整验收对单项结构或业务校验失败采用“逐项拒绝、继续后续语义、最终聚合失败类型/数量/代表样本”；存在关键违规时整轮仍失败且不采用任何模型候选。网络、鉴权、超时或其他无法继续调用的系统错误仍可立即终止。
- 真实调用必须启用本地缓存：按提供方、模型、提示词版本、规范化语义签名和实际输入指纹保存不含凭据的请求正文、提供方原始响应、逐项响应和校验结果。修改本地校验器或展开逻辑时先离线重放；只有模型、提示词、案件上下文或该语义实际输入变化时，才允许重新调用受影响签名。
- 小批验收必须读取固定样本清单；开发样本与保留验收样本分开，保留集不用于反复调提示词。曹国民4份流水的真实调用只证明该客户及4个来源的语义表现；统一字段层通过本地契约测试不等于所有银行、版式和客户均已完成真实模型验收。

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
- 银行扣款来源文件必须精确映射到一个可靠完整银行抬头账户；微信交易方式中的银行卡尾号须唯一对应该账户。该专用来源不放宽 v1C/v1D 的人工角色确认门槛。
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
