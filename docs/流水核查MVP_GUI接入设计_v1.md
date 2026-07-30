# 流水核查 MVP GUI 接入设计 v1

更新时间：2026-07-29

## 1. 当前结论与冻结边界

- 第一版流水核查 MVP 九项已经完成、验证并提交。第九项功能提交为 `4241ba9 feat: close traceable evidence output`，续接记录提交为 `7833959 docs: record traceable evidence checkpoint`；均未推送。
- 当前标准结果固定为 `schema_version: "1.16"`。GUI 第一版接入期间冻结现有字段名称和业务含义；发现展示缺口时先记录为不可用或后续契约需求，不在 GUI 代码中补算业务结果。
- GUI 第一版只消费 `build_bankflow_result()` 生成的标准结果及 `result.evidence`，不恢复经营 AI 调用，不启动生活轨迹，不解冻 v1C、v1D、微信银行扣款扩展或支付宝关联。
- 基础 GUI 接入调用 `build_bankflow_result()` 时必须显式传入空的禁用配置 `ai_config={}` 和 `ai_evaluator=None`，不得因本机环境变量存在而隐式装载外部模型运行配置。
- GUI 不重新计算快进快出、敏感词、经营关联、申报对照或人工核实问题，不直接读取解析器内部变量，不建立与 `Transaction` 或 `original_transactions` 平行的交易对象。

### 1.1 第一轮最小纵向切片实现状态

2026-07-29 已完成第一轮实现：

- 新增独立 `启动流水核查工作台.bat → gui_verification_app.py`，不修改或调用旧 `启动GUI.bat → gui_v2.py`；
- 独立 `VerificationWorker(QThread)` 在解析完成后生成 schema 1.16，固定显式传入 `ai_config={}`；
- 新增只读标准结果校验、历史 JSON 加载、版本不兼容提示和 transaction_id 证据直查；
- 新增概览、人工核实、敏感交易、50 条分页表格和共享证据面板；其余模块保持禁用“后续”状态；
- `ResultListModel` 只保存标准结果引用和 `range` 行序号，不复制 `Transaction`；
- 新增协作取消、逐来源进度、错误来源和默认脱敏。

真实任如冰案例沿独立 Worker 链路验收：2 个输入文件、标准结果 2 个来源、2075 笔原始交易、5 项人工核实、11 项敏感候选；transaction_id 成功定位微信来源第 3 页第 3 行，证据完整性为完整。解析及标准结果构建约 22.213 秒，结果绑定及首次绘制约 76.0 毫秒。

### 1.2 整体信息架构重构状态

2026-07-29 在继续接入第4至第10项前，已先完成工作台信息架构重构：

- 未加载案件时只显示 `WelcomePage`，不显示空案件概览和证据详情；
- 新建案件进入独立 `ProcessingPage`，展示当前文件、完成数、阶段、总体进度、错误来源和运行期协作取消；
- 左侧从10个平级业务标签改为首页、当前案件、历史案件和设置的全局导航；业务编号仅保留在 Dashboard 卡片和详情标题；
- `CaseDashboardPage` 统一展示案件头部、缩写金额、最多3项人工关注和9张自适应分析摘要卡；
- 现有人工核实和敏感交易迁移到统一 `ModuleDetailPage`，继续复用 `QTableView + QAbstractTableModel + 50条分页`；
- `EvidencePanel` 默认折叠，只有点击具体交易或引用时才通过 `QSplitter` 展开，并支持关闭、上一条和下一条；
- “打开已有案件”优先读取案件目录内可兼容的 schema 1.16 JSON；只有不存在可用结果时才询问是否重新解析。

本轮没有修改 schema 1.16、`VerificationWorker`、解析器、交易模型或证据索引；没有接入第4至第10项的明细展示，没有恢复经营AI，也没有启动生活轨迹。

## 2. 第九项及 schema 1.16 的 GUI 可用性

### 2.1 直接证据回跳

标准结果提供：

```text
result.original_transactions[]
result.evidence.transaction_index{}
result.evidence.references[]
result.evidence.coverage{}
result.evidence.integrity{}
```

GUI 按完整 `transaction_id` 直接查找：

```python
entry = result["result"]["evidence"]["transaction_index"][transaction_id]
transaction = result["result"]["original_transactions"][
    entry["original_transaction_index"]
]
```

取得的内容包括：

- 既有 `original_transactions` 中的完整交易；
- `source_file_id` 与 `source_file`；
- `page_no`、`row_no` 和 `evidence_locator`；
- `original.raw_time/raw_amount/raw_balance/raw_text/raw_headers/raw_fields/source_fields`；
- `standard_fields`、字段来源和字段置信度；
- 全局 `integrity`、逐消费者 `references[].status` 及悬空/歧义 ID。

索引只保存原交易序号和定位信息，不复制原始字段或标准字段。重复交易 ID 不进入唯一索引，相关引用标记为歧义；缺失、悬空或定位不足都会降低完整性。

GUI 取回交易后必须校验：

```text
transaction.transaction_id == 请求的 transaction_id
```

若索引不存在、序号越界或 ID 不一致，显示“证据不可用”，不得遍历全量交易猜测替代记录。

### 2.2 非平行模型

项目唯一核心交易类为 `bankflow_v2.models.Transaction`；`TransactionList` 只是携带 `StatementMetadata` 的兼容列表。`result.evidence.transaction_index` 是指向既有原交易数组的目录，不是第二套交易模型。

后续 Qt 表格允许使用只读的视图模型或分页适配器，但它只能保存标准结果引用、当前页序号和展示状态，不能复制交易字段形成新的业务交易对象。

### 2.3 Markdown 边界

`render_mvp_markdown()` 只显示证据链完整性、交易/索引/定位覆盖数、被引用交易数、证据链接数及悬空/歧义数。完整交易索引、逐消费者引用状态和原交易内容只保留在结构化结果中，供 GUI 按需展开。

## 3. 当前 GUI 技术栈核验

| 项目 | 当前实际状态 |
| --- | --- |
| 新工作台入口 | `启动流水核查工作台.bat` 执行 `python gui_verification_app.py` |
| 旧 GUI 边界 | `启动GUI.bat → gui_v2.py` 保持原样，不参与新工作台启动或运行 |
| GUI 框架 | PyQt6，`requirements.txt` 要求 `PyQt6>=6.5`；不是 PySide6 |
| 主窗口 | `gui_verification_app.VerificationMainWindow(QMainWindow)` |
| 解析工作线程 | `bankflow_v2.verification_worker.VerificationWorker(QThread)`，逐文件自动识别、专用解析、通用兜底、证据附加和标准结果生成 |
| 进度与完成信号 | `progress`、`stage_progress`、`source_error`、`cancelled`、`failed`、`finished` |
| 当前数据持有 | 核查工作台只读持有 schema 1.16 标准结果 |
| 当前表格 | 新工作台列表使用 `QTableView + QAbstractTableModel` 和 50 条分页 |
| 当前页面 | 概览、人工核实、敏感交易及证据面板 |
| 当前主题 | 核查工作台使用集中 `BriefTheme` 与 QSS |
| 当前后台能力 | 解析和标准结果构建均在现有 `QThread`；支持文件边界协作取消和逐来源状态 |
| 当前大表行为 | 核查列表按页创建索引 |
| 当前标准结果接入 | 已接入；构建固定 `ai_config={}`，支持加载历史 schema 1.16 JSON |
| 当前打包边界 | 新工作台尚未新增 PyInstaller spec；旧 `BankFlowGUI.spec` 不属于新项目入口 |

当前线程缺口：

- 解析前的部分密码/未识别检查仍在主线程；
- 报告生成和导出目前由按钮直接在主线程执行；
- `Worker` 没有 `requestInterruption()` 检查和取消状态；
- 单个超长 PDF 解析期间只能等待当前解析器返回。

以上是 GUI 接入阶段需要逐轮修正的技术债，不改变现有解析器和 schema 1.16 业务口径。

## 4. GUI 数据边界

固定数据流：

```text
文件/案件资料
→ 现有自动识别与解析器
→ Transaction / original_transactions
→ build_bankflow_result()
→ facts / indicators / observations / manual_review / evidence
→ GUI只读视图适配
→ 摘要、分页列表、证据抽屉
```

允许 GUI 做的事情：

- 选择页面、筛选已有状态、排序已有字段；
- 将现有候选数量、状态和原因码映射为中文展示；
- 根据 `transaction_id` 直接访问 `transaction_index`；
- 分页、虚拟加载、折叠、复制已脱敏的显示文本；
- 展示来源、页/行、字段覆盖和完整性；
- 保存纯界面状态，例如当前页、页大小、展开项和排序字段。

禁止 GUI 做的事情：

- 从交易重新计算事实、指标或观察；
- 重新跑关键词、金额窗口、余额路径或经营规则；
- 将“可靠字段内未发现”改写为客户没有相应行为；
- 从原始字段猜测缺失的对手、地点、用途或关系；
- 为展示方便复制一套可独立修改的交易业务对象；
- 让下游依赖当前表格中的文本或列顺序。

当前 schema 未直接提供而页面需要的信息，统一显示“不可用”并记录原因；不得在 GUI 临时解析 PDF 或扩展字段含义。

## 5. 第一版信息架构

### 5.1 总体布局

沿用 PyQt6 和当前桌面窗口：

- 顶部：案件名称、资料数量、处理状态、总进度、取消按钮和主要操作；
- 左侧：十二个信息模块导航；
- 中部：当前模块的摘要卡、统一状态、候选数量和分页列表；
- 右侧抽屉：共享的证据交易详情；默认关闭，点击候选或证据数后打开；
- 底部状态区：当前任务、错误来源、不可用原因和完成时间。

所有模块默认只显示摘要、状态和候选数量。逐项候选、证据交易和原始字段在用户点击后分页展开。

### 5.2 十二个模块及数据来源

| 模块 | schema 1.16 数据来源 | 默认摘要 | 展开内容 |
| --- | --- | --- | --- |
| 1. 客户和资料概览 | `statement_metadata`、`source_files`、`declaration_flow_cross_checks` 中的申报/展示项 | 主体、期间、资料数、总体可用性 | 来源角色、来源引用、申报值和核实状态 |
| 2. 来源文件及字段覆盖 | `source_files`、各指标/观察的 `field_coverage` 和逐来源覆盖 | 来源数、交易数、可搜索/不可用来源数 | 每来源文件、期间、字段覆盖和原因码 |
| 3. 流水基本事实 | `result.summary`、`facts[]`、`manual_review` | 笔数、收支、净额、期间、余额状态 | 事实值、证据数和技术复核项 |
| 4. 经营关联 | `ai_business_relevance_candidates` 及确定性经营命中 | 直接/候选/未发现/不可用数量 | 分类、强度、理由、使用字段和证据 |
| 5. 下定与购车 | `controlled_keyword_candidates`、`purchase_prepayment_funding_candidates`、申报对照 | 下定支出候选数、此前收入候选数 | 时间、金额、对手、同/跨来源和非归因说明 |
| 6. 主要交易对手 | `top_counterparties`、`cross_source_counterparty_occurrences`、对手集中度指标 | 收入/支出 Top 5、覆盖率、跨来源同名数 | 金额、占比、月份、来源和证据 |
| 7. 快进快出和大额资金观察 | 1/3/7 日指标、`large_transaction_candidates`、`large_inflow_balance_paths` | 各窗口数量、大额数、低留存候选数 | 金额、比例、余额公式、窗口及证据 |
| 8. 余额、结息及月度变化 | 收入连续性、近期变化、余额观察、`end_of_day_balance_and_interest` | 月份覆盖、余额可用性、结息数 | 月度窗口、日末余额统计、逐笔结息和季度变化 |
| 9. 敏感交易候选 | `sensitive_transaction_context_candidates` | 候选数、搜索覆盖、不可用来源数 | 命中词组、字段、完整可靠文字上下文和证据 |
| 10. 客户申报与流水事实对照 | `declaration_flow_cross_checks` | 四状态数量 | 申报值、来源、搜索范围、命中字段和证据 |
| 11. 人工核实事项 | `manual_verification_questions`、`manual_review.items[]` | 一般核实数、需关注数、技术复核数 | 问题、触发原因、核实要点、状态和证据 |
| 12. 证据交易明细 | `evidence.transaction_index/references/integrity`、`original_transactions` | 完整性、覆盖率、证据链接数 | 按消费者或交易 ID 分页查看原交易、来源及页/行 |

若某观察类型不存在、`available=false` 或覆盖不足，模块仍保留并显示“不可用”及原始原因码，不隐藏成“无候选”。

### 5.3 统一展示状态

GUI 顶层徽标固定为：

| 展示状态 | 典型原始状态 |
| --- | --- |
| 直接命中 | `direct_match`、确定性精确命中、`directly_related` |
| 候选命中 | `candidate_match`、候选观察、`possibly_related` |
| 可靠字段内未发现 | `no_evidence_in_reliable_fields`、可靠字段已搜索但无命中 |
| 不可用 | `unavailable`、字段覆盖不足、来源缺失、AI未授权或其他稳定原因码 |

映射只影响显示。详情必须保留原始状态码和解释，不能改变后端含义。“可靠字段内未发现”固定附注“仅表示当前可靠字段及交易覆盖期内未发现对应依据”。

## 6. 线程与任务模型

### 6.1 主线程职责

GUI 主线程只负责：

- 窗口、导航、表格和抽屉渲染；
- 用户输入和任务调度；
- 接收不可变的进度事件、错误事件和完成结果；
- 轻量分页、排序及脱敏格式化。

不得在主线程执行：

- PDF/Excel/微信解析和银行识别；
- `build_bankflow_result()`；
- 外部 AI 调用；
- Markdown/JSON/Excel 等报告生成和大批量写盘。

### 6.2 后台任务

第一版沿用 PyQt6 `QThread`，不切换框架：

1. `ParseResultWorker`：识别、解析、证据附加和标准结果生成；
2. `ReportWorker`：按已生成的标准结果写出 Markdown/JSON/Excel；
3. 后续如恢复 AI，使用独立 `AiObservationWorker`，不得与本轮基础解析隐式绑定。

`ParseResultWorker` 构建基础标准结果时固定显式禁用 AI；是否存在本机 Key 或授权环境变量都不能改变基础 GUI 的网络行为。

线程信号至少包含：

```text
started(task_id, total_sources)
progress(task_id, source_file_id, stage, completed, total, message)
source_error(task_id, source_file_id, stable_code, message)
cancel_pending(task_id)
finished(task_id, standard_result)
cancelled(task_id, partial_source_status)
failed(task_id, stable_code, message)
```

### 6.3 取消语义

- 使用 `requestInterruption()` 协作取消；
- 在文件之间、识别后、解析后、标准结果生成前和报告分页写出之间检查取消；
- 现有单个解析器没有中断接口时，不强制终止线程；界面显示“正在取消，等待当前文件结束”；
- 已完成来源保留状态，未完成来源标记为取消，不把部分结果显示成完整案件结果；
- 不使用 `QThread.terminate()`。

## 7. 分页和大数据量表格

当前 `QTableWidget` 全量创建单元格不适合数千笔证据。第一版接入采用：

- 摘要卡继续使用现有 QWidget/QFrame；
- 证据和候选大表改用 `QTableView + QAbstractTableModel`；
- 视图模型只持有标准结果引用、行序号和当前页，不复制交易业务字段；
- 默认每页 50 条，可选 25/50/100；
- 排序优先使用后端已给出的业务顺序；纯展示字段排序只改变当前视图，不重算结果；
- 证据交易按 `transaction_id → transaction_index → original_transaction_index` 直接取值；
- 模块候选列表使用观察中已经生成的候选数组，不重新扫描 `original_transactions`；
- 不在每次翻页时调用 `resizeColumnsToContents()` 扫描全表，只对表头和当前页计算列宽。

若后续单案结果大到内存压力明显，再评估 JSON 流式读取或只读本地结果存储；GUI 第一版不先引入数据库。

## 8. 脱敏与安全

### 8.1 默认显示

- 完整账号：只显示尾号，前部统一掩码；
- 手机号、身份证号、微信号及其他明确身份标识：默认隐藏；
- 交易 ID：人工核实和敏感交易列表不显示；内部仍以完整值索引，证据详情仅在用户点击“展开完整证据”后显示短形式；
- 文件：只显示标准结果中的文件名，不显示本地绝对路径；
- 页码、行号和 `evidence_locator`：完整显示；
- 对手、摘要、备注、用途、商品和商户类别：保留业务文字，只对其中嵌入的账号、手机号、身份证号做字段级掩码，不能整列删除。

### 8.2 实现约束

- 使用一个集中式展示脱敏器，所有表格、详情、复制、提示框和导出预览共用；
- 脱敏只作用于显示副本，不修改内存中的标准结果或写回 JSON；
- 默认复制当前脱敏文本；复制完整交易 ID 使用独立操作；
- 证据面板默认只显示日期、方向、金额、业务文字、账号尾号、来源文件及页/行；交易ID、定位、引用完整性和已脱敏原始字段仅在“展开完整证据”中显示；
- API Key、授权头和外部模型运行配置不得进入 GUI 日志、错误详情或标准结果。

## 9. 分轮实施计划

### 第 1 轮：最小纵向切片（已完成）

- 独立入口、标准结果生成/加载、概览；
- 01 概览、02 人工核实、03 敏感交易；
- 分页模型、共享证据面板、脱敏、进度、取消和错误来源。

### 第 2 轮：04 经营关联 + 05 下定购车

- 只消费 schema 1.16 已有观察和证据 ID；
- 经营关联不恢复 AI 调用，未授权或不可用按原状态展示；
- 下定、定金、购车款和此前收入候选保持非归因说明。

### 第 3 轮：06 主要交易对手 + 07 资金观察

- 接入收入/支出 Top 5、集中度和跨来源同名；
- 接入快进快出、大额交易和大额入账后余额路径；
- 所有详情通过 transaction_id 回到共享证据面板。

### 第 4 轮：08 余额结息 + 09 申报对照

- 接入月度变化、日末余额和结息观察；
- 接入客户申报与流水事实对照；
- 严格区分“可靠字段内未发现”和“不可用”。

### 第 5 轮：10 证据总表

- 提供 original_transactions 的分页/按批视图；
- 支持按来源、日期、方向和引用状态筛选；
- 仍通过 `transaction_index` 定位，不复制交易业务对象。

### 第 6 轮：双真实案例验收与第一版收口

- 使用任如冰、韩鹏飞核对全部模块；
- 完成性能、脱敏、错误、取消、启动 BAT 和打包入口验收；
- 收口后才进入生活轨迹后端阶段。

## 10. 生活轨迹后续里程碑

生活轨迹仅在 GUI 第一版收口后启动：

```text
GUI第一版收口
→ 生活轨迹核查 v1 后端
→ 生活轨迹真实样本验收
→ 接入 GUI 生活轨迹页面
```

后端采用混合方案：

1. 确定性行为分类；
2. 明确地名提取；
3. 城市、区县和地址标准化；
4. 必要时使用地图/POI查询并缓存；
5. AI仅处理模糊商户类型、隐含地点和非标准地名；
6. 按月份、频率、工作日和时间段聚合；
7. 与申报住址、单位地址和购车地作辅助对照。

生活轨迹必须拥有独立 `task_type`、提示词、缓存键、结果 schema 和验收样本，不复用经营关联强度语义。至少区分：

- 明确地点且长期持续；
- 明确地点但偶发；
- 仅行为类型、地点未知；
- 地点存在歧义；
- 与申报地区一致候选；
- 与申报地区不一致候选；
- 当前资料不可判断。

不得自动输出虚假住址、虚假单位、挂靠、实际常住地已确认、欺诈、通过或拒绝。
