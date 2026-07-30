# 流水核查 MVP GUI 分步骤实施状态

更新时间：2026-07-30

## 1. 文档定位

本文记录独立流水核查工作台的当前真实代码状态、可复用组件、缺口和后续分步实施边界。

本次核对只读取实际 Git、启动入口、PyInstaller spec、GUI 源码、schema 1.16 视图适配、经营观察及证据索引实现。除新增本文档外，没有修改业务代码或 GUI，没有调用外部模型，没有提交或推送。

后续每一步开始前都必须重新核验实际 Git 和当前代码，不得把本文中的可变状态长期视为事实。

## 2. 当前 Git 基线

核对时间：2026-07-30。

| 项目 | 当前实际状态 |
| --- | --- |
| 仓库 | `D:\Investigator PDF\CD-bankflow-refactor` |
| 分支 | `work/2026-07-18-bankflow-verification` |
| HEAD | `3cb75d6 refactor: reorganize verification workbench navigation` |
| 远端跟踪 | `origin/work/2026-07-18-bankflow-verification` |
| ahead / behind | ahead 43 / behind 0 |
| 工作区 | 本轮开始前已有 12 个修改文件，工作区不干净 |
| 推送状态 | 本轮未推送 |

本轮开始前已有的未提交文件：

- `INTEGRATION_CONTRACT.md`
- `PROJECT_STATUS.md`
- `bankflow_v2/result_export.py`
- `bankflow_v2/standard_result_view.py`
- `bankflow_v2/verification_worker.py`
- `docs/change-history/2026-07.md`
- `docs/流水核查MVP_GUI接入设计_v1.md`
- `gui_verification.py`
- `gui_verification_app.py`
- `tests/test_gui_verification.py`
- `tests/test_standard_result_view.py`
- `技术变更记录.md`

这些文件属于本轮开始前已经存在的本地变更；本轮不回退、不提交，也不把它们误记为本轮代码修改。

## 3. 当前真实入口、启动脚本和打包状态

### 3.1 独立流水核查工作台

当前有效源码入口：

```text
启动流水核查工作台.bat
→ python gui_verification_app.py
→ VerificationMainWindow
→ VerificationWorkspace
→ VerificationWorker(QThread)
→ schema 1.16 标准结果
```

`启动流水核查工作台.bat` 会切换到仓库目录，设置 `PYTHONUTF8=1` 和 `PYTHONUNBUFFERED=1`，然后把命令行参数传给 `gui_verification_app.py`。

### 3.2 旧 GUI

旧入口仍为：

```text
启动GUI.bat
→ python gui_v2.py
```

旧入口没有被删除，但不属于当前独立流水核查工作台的信息架构和页面实现。

### 3.3 PyInstaller spec

仓库当前只有一个 `BankFlowGUI.spec`，其中入口仍是：

```python
Analysis(["gui_v2.py"], ...)
```

因此：

- 当前 spec 只对应旧 GUI；
- 独立流水核查工作台尚无专用 PyInstaller spec；
- 现有 `BankFlowGUI.spec` 不能作为新工作台打包已接入的依据；
- 本轮不修改 spec，也不打包。

## 4. 当前顶部和左侧导航

### 4.1 顶部结构

当前没有贯穿所有页面的独立“顶部全局导航栏”。

现有顶部信息由各页面自行承担：

- 首页使用产品标题和操作入口；
- 案件概览使用 `BriefPageHeader` 展示案件名、期间和状态徽标；
- 模块详情使用“案件概览”返回按钮和 `案件概览 > 模块名称` 面包屑；
- 任务处理页和分析前确认页使用各自的 `SectionHeader`；
- 取消按钮位于 `ProcessingPage`，不是全局顶部按钮。

因此，最新目标中的“首页 → 当前案件整体画像 → 模块分析概要 → 候选交易明细”尚未形成统一的顶部层级导航。

### 4.2 左侧导航

当前左侧为固定宽度 220 像素的全局导航：

```text
首页

当前案件
  案件概览
  人工核实
  证据中心

历史案件
设置
```

实际行为：

- “当前案件”是分组标题，不可点击；
- 三个案件子项缩进显示；
- 未加载 schema 1.16 结果时，案件子项禁用；
- 加载结果后默认进入案件概览；
- 可见导航中没有“分析结果”；
- 历史 `analysis` 路由仍兼容重定向到 `dashboard`；
- 敏感交易、经营关联及其他业务模块不在左侧平级展示，通过 Dashboard 摘要卡进入。

## 5. 当前页面和组件状态

### 5.1 页面能力

| 能力 | 当前实现 | 说明 |
| --- | --- | --- |
| 首页 | `WelcomePage` | 新建案件、打开已有案件、导入标准结果、设置入口、最近案件文字列表 |
| 分析前确认 | `CasePreparationPage` | 展示提取的经营上下文，允许人工确认和显式 AI 授权 |
| 任务处理 | `ProcessingPage` | 逐来源进度、错误来源、协作取消 |
| 案件概览 | `CaseDashboardPage` | 案件头部、关键数据、人工关注、分组模块摘要、证据完整性 |
| 人工核实 | `ModuleDetailPage` 的 `manual` 模式 | 50 条分页表格，点击带 ID 的事项展开证据 |
| 敏感交易 | `ModuleDetailPage` 的 `sensitive` 模式 | 50 条分页表格，点击候选展开证据 |
| 经营关联 | `ModuleDetailPage` 的 `business` 模式 | 经营候选分页表和经营上下文补充入口 |
| 证据详情 | `EvidencePanel` | 默认隐藏，交易选中后在右侧展开 |
| 历史案件 | 简单占位页 | 尚无持久化案件索引或完整历史管理 |
| 设置 | 简单说明页 | 不保存模型 Key；尚无完整设置功能 |

人工核实、敏感交易和经营关联不是三个独立页面类，而是统一 `ModuleDetailPage` 中的三个模式。

### 5.2 指定组件核对

| 组件或能力 | 是否存在 | 当前实际实现 |
| --- | --- | --- |
| `CaseDashboardPage` | 是 | 唯一案件总览页 |
| `ModuleSummaryPage` | 否 | 模块摘要目前位于 Dashboard 卡片，详情摘要位于 `ModuleDetailPage` 顶部 |
| `TransactionListPanel` | 否 | 当前由 `PagedTable` 承担分页候选表职责 |
| `ModuleDetailPage` | 是 | 统一承载模块标题、摘要、经营提示及候选表 |
| `EvidencePanel` | 是 | `QSplitter` 右侧共享证据面板 |
| `QTableView` | 是 | `PagedTable.table` 及未接入模块的占位表 |
| `QAbstractTableModel` | 是 | `ResultListModel` |
| 分页 | 是 | `ResultListModel` 默认每页 50 条，`PagedTable` 提供前后翻页 |
| 协作取消 | 是 | GUI 调用 `requestInterruption()`；Worker 在文件间及结果构建前后检查 |

当前没有 25/50/100 页大小选择，页大小固定为 50。

### 5.3 可复用组件

后续应优先复用：

- `VerificationWorkspace`：全局页面栈、导航、详情与证据面板编排；
- `CaseDashboardPage`：案件整体画像和模块摘要入口；
- `AnalysisModuleCard`：模块摘要卡；
- `KeyMetricsPanel`：六项关键指标整体面板；
- `ModuleDetailPage`：当前模块详情容器；
- `PagedTable`：分页、行选择、前后翻页；
- `ResultListModel`：只持有标准结果引用和行序号的只读视图模型；
- `EvidencePanel`：transaction_id 证据详情、上一条、下一条、关闭及展开完整证据；
- `EvidenceSummaryPanel`：案件证据完整性摘要；
- `StatusBadge`、`SectionHeader`、`HardShadowCard`：现有视觉体系；
- `redact_sensitive_text()`、`mask_account()`：集中展示脱敏；
- `validate_standard_result()`、`observation_by_type()`、`evidence_transaction()`：schema 1.16 读取边界；
- `VerificationWorker(QThread)`：现有解析、进度和协作取消链路。

后续不得为每个业务模块复制一套 Dashboard、证据面板、分页模型或交易对象。

## 6. 经营关联当前状态

### 6.1 候选展示

后端 schema 1.16 经营观察目前包含：

- `deterministic_candidates`
- `deterministic_non_business_candidates`
- `ai_candidates`
- `provisional_ai_candidates`
- AI 可用状态、失败原因和验证摘要

当前 GUI 主表通过 `_business_rows()` 展示：

- 确定性文字/名称正向候选；
- 已通过后端整轮校验并进入 `ai_candidates` 的 AI 观察。

表格列已经能够显示：

- 判断来源；
- `directly_related / possibly_related / no_relation_evidence / undetermined` 的中文映射；
- `strong / medium / weak / none` 的中文映射；
- 日期、方向、金额、交易对手和判断依据。

但当前分层只算“部分完成”：

- strong、medium、weak、undetermined、none 通过同一表格的分类和强度列区分，没有独立筛选、计数区或分组；
- `deterministic_non_business_candidates` 只在顶部状态文字中显示数量，不进入明细表；
- `provisional_ai_candidates` 不展示，符合整轮校验失败时不得采用模型结果的边界；
- 当前真实案例 AI 未执行，因此尚未完成 GUI 对 strong/medium/weak/undetermined/none 全状态的真实模型结果验收。

确定性排除不进入主候选表是已有设计选择。如果后续需求要求查看排除明细，应作为只读的次级分组或筛选接入，不能与正向候选混在默认主表，也不能在 GUI 重算排除规则。

### 6.2 人工经营上下文

当前已经具备完整入口和最小闭环：

```text
选择客户资料目录
→ 快速扫描 TXT 和案件字段
→ CasePreparationPage
→ 确认后完整解析
→ 案件概览
```

已有输入：

- `confirmed_primary_business`
- `confirmed_products_or_services`
- `confirmation_note`
- `confirmed_by`
- 是否启用 AI 经营语义辅助
- 仅本次进程使用的 DeepSeek API Key

已有持久化：

- 文件名：`manual_case_context.json`
- 保存位置：案件目录；
- 使用临时文件替换方式写入；
- 保存原始提取信息、人工确认、来源、确认状态、确认人、UTC 确认时间和 AI 授权选择；
- API Key 不写入该文件、标准结果或日志；
- 不修改客户 TXT、PDF、微信、支付宝或银行流水。

已有局部重算：

- 按钮为“应用并重新分析经营关联”；
- 优先复用内存中的现有 `Transaction`；
- 打开已有结果时可从 schema 1.16 `original_transactions` 恢复现有 `Transaction` 值；
- 调用 `rebuild_business_context_result()`；
- 只重建经营关联、申报对照中的经营部分、相关人工核实和证据审计；
- 不重新解析 PDF；
- 不创建平行交易模型；
- 不改变 `original_transactions`。

AI 默认关闭。只有 GUI 明确勾选并点击确认后才调用 `_explicit_ai_runtime()`；未勾选时不会因为环境变量存在而装载 AI。

## 7. schema 1.16 和证据回跳

### 7.1 结构校验

`validate_standard_result()` 固定只接受 schema 1.16，并校验：

- `original_transactions`
- `facts`
- `indicators`
- `observations`
- `evidence.transaction_index`
- `evidence.references`
- `evidence.coverage`
- `evidence.integrity`

### 7.2 transaction_id 回跳

当前回跳链路为：

```text
候选或人工事项中的 transaction_id
→ evidence.transaction_index[transaction_id]
→ original_transaction_index
→ original_transactions[original_transaction_index]
→ 校验返回交易的 transaction_id
→ EvidencePanel
```

索引缺失、序号越界或 ID 不一致时会显式报“证据不可用”，不会遍历交易猜测替代记录。

`EvidencePanel` 已支持：

- 默认紧凑业务字段；
- 来源文件、页码和行号；
- 账号及敏感文字脱敏；
- 展开后显示短交易 ID、evidence locator、消费者引用状态和完整性；
- 同一候选表内上一条、下一条；
- 关闭并释放右侧内容宽度。

韩鹏飞真实案例最近重新核验为：

- 3 个来源；
- 3135 笔原始交易；
- 3135 笔唯一交易索引；
- 39431 条有效证据引用；
- 0 条悬空引用；
- 0 条歧义引用；
- 47 笔确定性经营文字/名称候选；
- 0 笔 AI 观察；
- 经营状态为 `business_context_confirmation_required`。

当前证据索引和已接入三个候选模块的 transaction_id 回跳链路完整。证据中心尚未提供全部交易的完整列表、筛选和分页，因此“证据中心完整功能”仍未完成。

## 8. 已接入和未接入模块

| 模块 | Dashboard 摘要 | 详情 | transaction_id 回跳 | 当前结论 |
| --- | --- | --- | --- | --- |
| 人工核实 | 已接入 | 已接入 | 已接入 | 已完成当前纵向切片 |
| 敏感交易 | 已接入 | 已接入 | 已接入 | 已完成当前纵向切片 |
| 经营关联 | 已接入 | 已接入候选主表 | 已接入 | 人工上下文闭环已完成；候选分层仍可加强 |
| 下定购车 | 已接入摘要 | 通用占位表 | 未接入 | 待实施 |
| 交易对手 | 已接入摘要 | 通用占位表 | 未接入 | 待实施 |
| 资金观察 | 已接入摘要 | 通用占位表 | 未接入 | 待与余额合并实施 |
| 余额与月度 | 已接入摘要 | 通用占位表 | 未接入 | 待与资金观察合并实施 |
| 申报对照 | 已接入摘要 | 通用占位表 | 未接入 | 待实施 |
| 证据中心 | 已接入完整性摘要和左侧入口 | 通用占位表 | 已有底层直查，缺列表入口 | 待实施完整功能 |
| 历史案件 | 首页仅有会话内最近名称 | 简单占位页 | 不适用 | 不在近期业务模块范围 |
| 设置 | 说明页 | 简单占位页 | 不适用 | 不保存 Key |

## 9. 现有设计文档的冲突和重复

需要以本文和实际代码为准修正 `docs/流水核查MVP_GUI接入设计_v1.md` 中以下内容。

### 9.1 已过时或冲突

1. 文档前部仍写“GUI 第一版不恢复经营 AI、基础 Worker 固定 `ai_config={}`”，但后部 1.5 节和当前代码已经改为：AI 默认关闭，只有 GUI 明确授权后才显式装载经营 AI。旧表述不能继续作为绝对冻结条件。
2. 3 节“当前线程缺口”写 `Worker` 没有 `requestInterruption()` 检查，与当前 `VerificationWorker` 在文件间、结果构建前后检查取消的实现冲突。
3. 5.1 节仍描述顶部全局状态栏和左侧十二个模块导航，与当前“左侧全局分组 + Dashboard 模块卡片 + 详情面包屑”冲突。
4. 5.2 节把十二个模块作为当前信息架构，和当前八张业务摘要卡加独立证据摘要的结构重复且口径不同。
5. 1.2 节写“业务编号保留在 Dashboard 卡片和详情标题”，但当前视觉编号已经全部删除。
6. 7 节写默认页大小可选 25/50/100，当前实际只实现固定 50 条。
7. 9 节仍把“经营关联 + 下定购车”列为同一后续轮次；当前经营关联详情和人工确认闭环已完成，下定购车被明确暂停并应单独实施。
8. 9 节把资金观察与余额月度分在不同轮次或独立页面，最新要求是 Dashboard 合并为“资金与余额概览”，详情用页签区分。
9. 3 节同时写“当前页面只有概览、人工核实、敏感交易”，遗漏已经实现的经营关联详情和 `CasePreparationPage`。
10. 3 节只说明新工作台未新增 spec，该结论仍正确；但后续打包验收不得继续使用现有 `BankFlowGUI.spec` 代表新工作台。

### 9.2 重复内容

- 1.2、1.3、5、9 节重复描述导航和模块轮次，但分别代表不同日期的方案；
- 1.4、1.5 与 9 节重复描述经营关联状态，且“禁止 AI”与“显式授权后可用”并存；
- 2、4、7 节重复说明 transaction_id、非平行模型和分页边界；
- 5.2 的十二模块清单与当前 Dashboard 八张业务卡及证据摘要重复。

后续应将旧设计文档保留为历史设计记录，不再在其中继续叠加新的“当前状态”。当前实施进度、顺序和停止条件统一维护在本文。

## 10. 当前主要缺口

### 10.1 信息架构

- 缺贯穿案件层级的顶部导航或明确层级指示；
- 缺独立的模块分析概要层；
- `ModuleDetailPage` 同时承担模块摘要和候选交易列表，三级层级尚未清晰拆开；
- 没有名为 `ModuleSummaryPage` 的页面；
- 没有名为 `TransactionListPanel` 的通用组件；
- 左侧“人工核实”直接进入候选列表，与“所有业务模块从概要进入明细”的层级不完全一致。

### 10.2 业务详情

- 下定购车未接入；
- 交易对手未接入；
- 资金观察和余额月度尚未合并；
- 申报对照未接入；
- 证据中心缺完整交易列表、筛选和分页。

### 10.3 经营关联

- 经营候选只有一个统一表格，缺正向、AI各强度、无法判断、未发现依据和确定性排除的只读分层或筛选；
- 没有使用真实 AI 结果完成全部强度和空状态的 GUI 验收；
- 不得通过本轮 GUI 工作改动曹国民已冻结的经营 AI 规则。

### 10.4 打包

- 新工作台没有专用 PyInstaller spec；
- 旧 spec 仍指向 `gui_v2.py`；
- 打包只在全部核心模块和双案例验收完成后单独处理。

## 11. 后续分步骤清单

所有步骤都继续遵守：

- PyQt6、Qt Widgets、QSS 和现有 QThread；
- GUI 只消费 schema 1.16 和证据索引；
- 不重写解析器，不建立平行交易模型；
- 不在 GUI 重算业务规则；
- AI 默认关闭且不得由环境变量隐式调用；
- 不修改客户原始资料；
- 不启动生活轨迹、高德或用车轨迹；
- 不修改曹国民经营 AI 业务规则；
- 每一步是否提交由用户单独确认；
- 一个步骤达到停止条件并经用户确认后，才进入下一步。

### 步骤 2：顶部导航与三级页面骨架

目标结构：

```text
首页
→ 当前案件整体画像
→ 模块分析概要
→ 候选交易明细
→ 右侧交易证据
```

预计修改文件：

- `gui_verification.py`
- `tests/test_gui_verification.py`
- `docs/流水核查MVP_GUI分步骤实施状态.md`
- 必要时更新 `PROJECT_STATUS.md`、`技术变更记录.md` 和当月 change history

实施边界：

- 复用 `CaseDashboardPage`；
- 评估将现有 `ModuleDetailPage` 拆成明确的模块概要层和候选明细层；
- 复用或小范围演化 `PagedTable`，不复制业务数据；
- 保留共享 `EvidencePanel`；
- 不接入新的业务模块内容；
- 不做像素级统一打磨。

停止条件：

- 顶部或页面内层级导航能够明确显示当前位置；
- Dashboard 摘要卡先进入模块概要，而不是直接混合全部候选明细；
- 模块概要可进入候选交易明细；
- 候选交易仍能打开右侧证据；
- 左侧、返回路径和浏览历史不会出现两个 Dashboard；
- 现有人工核实、敏感交易、经营关联功能不退化；
- GUI 定向测试、全量测试、语法检查、离屏启动和 `git diff --check` 通过；
- 达到以上条件后停止，不进入下定购车。

### 步骤 3：经营关联展示分层验收

预计修改文件：

- `gui_verification.py`
- `tests/test_gui_verification.py`
- 相关状态文档

实施边界：

- 只消费 schema 1.16 已有分类和证据强度；
- 不修改曹国民经营 AI 规则；
- 不在 GUI 重分类；
- 默认主视图继续突出需复核的正向候选；
- 确定性排除如需展示，只做次级只读入口。

停止条件：

- 确定性正向、AI strong/medium/weak、undetermined、none、确定性排除的数量和展示边界清晰；
- AI 不可用时确定性结果仍正常；
- 所有带 transaction_id 的行可回跳；
- 分页、脱敏、空状态和不可用状态通过；
- 未授权时确认没有模型调用；
- 完成 GUI 和全量测试后停止，不进入下定购车。

### 步骤 4：下定购车

预计修改文件：

- `gui_verification.py`
- `bankflow_v2/standard_result_view.py`（仅增加标准结果只读访问器时）
- `tests/test_gui_verification.py`
- `tests/test_standard_result_view.py`（仅在增加只读访问器时）
- 相关状态文档

停止条件：

- Dashboard、模块概要和候选明细均完成；
- 下定、定金、购车款及此前收入候选保持非归因说明；
- 空状态与不可用状态明确；
- transaction_id 回跳、分页、脱敏通过；
- 不新增或重算购车规则；
- GUI 和全量测试通过后停止。

### 步骤 5：交易对手

预计修改文件：

- `gui_verification.py`
- `bankflow_v2/standard_result_view.py`（仅只读适配需要时）
- 对应测试及状态文档

停止条件：

- 收入和支出 Top 对手、覆盖率、月份和已有集中度信息可读；
- 无可靠对手字段与可靠字段内无候选严格区分；
- 完整账号默认脱敏；
- 所有证据 ID 可回跳；
- 不做关系、资金闭环或实际控制推断；
- GUI 和全量测试通过后停止。

### 步骤 6：资金与余额

预计修改文件：

- `gui_verification.py`
- `bankflow_v2/standard_result_view.py`（仅只读适配需要时）
- 对应测试及状态文档

实施目标：

- Dashboard 将“资金观察”和“余额与月度”合并为“资金与余额概览”；
- 详情页使用页签区分大额交易、资金路径、余额、结息和月度变化；
- 共用同一页面框架和证据面板。

停止条件：

- 两张旧摘要卡不再作为两个完全独立页面发展；
- 各页签只展示 schema 既有事实和观察；
- 资金路径保持时间共现和非归因说明；
- 余额、结息、月度变化不扩展为偿债能力结论；
- 回跳、分页、脱敏、空状态通过；
- GUI 和全量测试通过后停止。

### 步骤 7：申报对照

预计修改文件：

- `gui_verification.py`
- `bankflow_v2/standard_result_view.py`（仅只读适配需要时）
- 对应测试及状态文档

停止条件：

- 四状态、申报来源、搜索范围、命中字段和证据可读；
- 经营部分能读取人工上下文局部重算后的标准结果；
- “未发现”和“不可用”不被写成申报虚假；
- transaction_id 回跳和无直接交易 ID 的说明均正确；
- GUI 和全量测试通过后停止。

### 步骤 8：证据中心完整功能

预计修改文件：

- `gui_verification.py`
- `bankflow_v2/standard_result_view.py`（仅只读索引访问器需要时）
- 对应测试及状态文档

停止条件：

- `original_transactions` 可按 schema 索引分页查看；
- 可按已有来源、日期、方向和引用状态做纯展示筛选；
- 不复制交易业务对象，不扫描原始 PDF；
- 选择交易后复用同一 `EvidencePanel`；
- 悬空、歧义和索引缺失显式展示；
- GUI 和全量测试通过后停止。

### 步骤 9：任如冰、韩鹏飞双案例全模块验收

预计修改文件：

- 原则上只修改测试、验收记录和状态文档；
- 发现明确 GUI 缺陷时才修改对应 GUI 文件；
- 不在验收步骤扩展业务规则。

停止条件：

- 两个案例逐模块核对 Dashboard、概要、候选明细、空状态、不可用状态；
- transaction_id 证据回跳、分页、脱敏和协作取消通过；
- AI 不会被隐式调用；
- GUI 定向测试、全量单元测试、语法检查、离屏启动、统一回归和 `git diff --check` 通过；
- 用户确认 GUI 第一版业务功能收口。

### 步骤 10：新工作台打包入口

该步骤只在步骤 9 完成并由用户明确要求后执行。

预计修改文件：

- 新增独立流水核查工作台 PyInstaller spec；
- 必要的发布清单和打包说明；
- 打包相关测试或验收记录。

停止条件：

- spec 明确指向 `gui_verification_app.py`；
- 不覆盖或冒充旧 `BankFlowGUI.spec`；
- 源码入口、BAT 和打包产物行为一致；
- 启动、标准结果加载、脱敏和无隐式 AI 调用通过；
- 未经用户明确要求不执行该步骤。

## 12. 本轮停止位置

本轮只完成步骤 1：

- 已确认真实 Git 和 GUI 状态；
- 已确认当前入口、启动脚本和 spec；
- 已确认页面、组件、经营候选、人工上下文和证据回跳；
- 已记录设计文档冲突和后续步骤；
- 未实施步骤 2 或任何业务模块；
- 未调用模型；
- 未提交、未推送。
