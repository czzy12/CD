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

- 保留 `启动GUI.bat → gui_v2.py` 和 `BankFlowGUI.spec`；
- 现有 `Worker(QThread)` 在解析完成后生成 schema 1.16，固定显式传入 `ai_config={}`；
- 新增只读标准结果校验、历史 JSON 加载、版本不兼容提示和 transaction_id 证据直查；
- 新增概览、人工核实、敏感交易、50 条分页表格和共享证据面板；其余模块保持禁用“后续”状态；
- `ResultListModel` 只保存标准结果引用和 `range` 行序号，不复制 `Transaction`；
- 新增协作取消、逐来源进度、错误来源和默认脱敏。

真实任如冰案例沿同一 Worker 链路验收：2 个输入文件、标准结果 2 个来源、2075 笔原始交易、5 项人工核实、11 项敏感候选；transaction_id 成功定位微信来源第 3 页第 3 行，证据完整性为完整。解析及标准结果构建约 14.922 秒，结果绑定及首次绘制约 76.0 毫秒。

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
| 有效源码入口 | `启动GUI.bat` 执行 `python gui_v2.py` |
| GUI 框架 | PyQt6，`requirements.txt` 要求 `PyQt6>=6.5`；不是 PySide6 |
| 主窗口 | `gui_v2.MainWindow(QMainWindow)` |
| 解析工作线程 | `gui_v2.Worker(QThread)`，逐文件自动识别、专用解析、通用兜底、证据附加、日期筛选和汇总 |
| 进度与完成信号 | `progress`、`stage_progress`、`source_error`、`cancelled`、`failed`、`finished` |
| 当前数据持有 | 原工具继续兼容 `FileResult`；核查工作台只读持有 schema 1.16 标准结果 |
| 当前表格 | 原工具保留 `DropTable(QTableWidget)`；新增列表使用 `QTableView + QAbstractTableModel` 和 50 条分页 |
| 当前页面 | 新增概览、人工核实、敏感交易及证据面板；原月度/文件/明细/异常工具保留 |
| 当前主题 | 核查工作台使用集中 `BriefTheme` 与 QSS；原工具样式局部保留 |
| 当前后台能力 | 解析和标准结果构建均在现有 `QThread`；支持文件边界协作取消和逐来源状态 |
| 当前大表行为 | 新增核查列表按页创建索引；原工具大表行为暂不改 |
| 当前标准结果接入 | 已接入；构建固定 `ai_config={}`，支持加载历史 schema 1.16 JSON |
| 当前打包入口 | `BankFlowGUI.spec` 以 `gui_v2.py` 为入口，PyInstaller one-dir、无控制台，打包 `assets/`、`configs/`、发布说明和版本信息 |
| 旧入口 | `gui_app.py` 是旧 PyQt6 界面并依赖旧 `core.pipeline`；不属于当前启动或打包入口 |

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
- 交易 ID：显示短形式，内部和复制定位操作保留完整值；
- 文件：只显示标准结果中的文件名，不显示本地绝对路径；
- 页码、行号和 `evidence_locator`：完整显示；
- 对手、摘要、备注、用途、商品和商户类别：保留业务文字，只对其中嵌入的账号、手机号、身份证号做字段级掩码，不能整列删除。

### 8.2 实现约束

- 使用一个集中式展示脱敏器，所有表格、详情、复制、提示框和导出预览共用；
- 脱敏只作用于显示副本，不修改内存中的标准结果或写回 JSON；
- 默认复制当前脱敏文本；复制完整交易 ID 使用独立操作；
- 证据抽屉默认仍为脱敏显示，“查看完整原文”若以后开放，必须有明确权限、操作提示和审计要求；
- API Key、授权头和外部模型运行配置不得进入 GUI 日志、错误详情或标准结果。

## 9. 分轮实施计划

### 第 0 轮：契约冻结与基线

- 以 `4241ba9` 和 `7833959` 为第九项已提交基线；
- 固定 schema 1.16 字段含义；
- 增加只读契约测试：索引回跳、原始字段、引用状态和重复/悬空降级；
- 不修改 GUI。

完成标准：当前 225 项单元测试、统一回归基线和第九项真实样本证据审计保持有效。

### 第 1 轮：标准结果接入骨架

- 保留 `gui_v2.py`、PyQt6、现有启动和打包方式；
- 后台解析完成后统一生成一次 schema 1.16 标准结果；
- 标准结果构建显式传入 `ai_config={}`，保证基础接入不读取外部模型环境配置；
- GUI 状态只保存标准结果，不让新增核查页面读取解析器内部变量；
- 建立模块导航、统一状态映射和共享证据抽屉空壳；
- 现有调整/收入佐证功能保持原边界，不混入流水核查结果。

完成标准：打开真实案件后可显示 schema 版本、完整性、来源数和十二个模块的可用/不可用状态。

### 第 2 轮：摘要模块接入

- 接入客户/资料、来源覆盖、基本事实、申报对照和人工核实事项；
- 默认只显示摘要和数量；
- 所有不可用原因和“可靠字段内未发现”表述通过验收。

完成标准：不遍历原交易即可完成上述页面展示；同一状态在所有页面文案一致。

### 第 3 轮：候选与资金模块接入

- 接入经营关联、下定购车、主要对手、大额/快进快出、余额结息、敏感交易；
- 复用标准结果中的候选、公式、覆盖和证据 ID；
- 不在 GUI 重算任何规则。

完成标准：模块数量与同一标准 JSON 的 Markdown 汇总一致，详情能回到证据交易。

### 第 4 轮：分页证据与脱敏

- 引入 `QTableView + QAbstractTableModel` 的分页视图；
- 完成共享证据抽屉、直接索引回跳、短交易 ID 和集中式脱敏；
- 增加空索引、越界、ID不一致、重复和悬空引用的负向界面测试。

完成标准：数千笔交易不一次性创建全部单元格；默认视图不显示完整账号、手机号和身份证号；来源及页/行仍完整。

### 第 5 轮：任务进度、取消和错误来源

- 将解析前检查、标准结果构建和报告生成移出主线程；
- 增加逐来源/逐阶段进度、协作取消、部分来源状态和稳定错误码；
- 明确当前文件不可中断时的“取消等待”状态。

完成标准：处理期间窗口可响应；取消不会留下被误认为完整的案件结果；错误可定位到来源文件。

### 第 6 轮：真实案例 GUI 验收与第一版收口

- 使用任如冰、韩鹏飞两组已验收本地案例；
- 核对十二个模块、候选数量、状态、分页、证据回跳和脱敏；
- 运行全量单元测试、统一回归、GUI定向测试和打包冒烟测试；
- 用户确认后再决定是否重新打包发布。

完成标准：GUI只消费 schema 1.16；后端数字和语义不因 GUI 接入变化；不存在外部模型隐式调用。

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
