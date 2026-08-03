# Web GUI 12B-0 集成验证报告

## 结论

状态：**阻塞，未完成，不建议进入 12B-1。**

React/Vite 本地生产构建、Python DTO/CaseSession/结果适配/Bridge 契约和 18 项定向测试已完成；但 PyQt6 `QWebEngineProfile` 在当前 Windows 环境初始化时稳定以 `0xC0000409` 退出。该问题在沙箱内外、offscreen 和实际 Windows 平台、PyQt/Qt 6.11 与干净的 6.8 配套环境均可复现。因此触发停止条件，未继续 PyInstaller、真实案件、截图、DPI 和性能验收，也未通过放松网络隔离、改用 PySide6 或其他架构绕过。

## 1. 开始前 Git 状态

- 分支：`work/2026-07-18-bankflow-verification`
- HEAD：`32b6f4b52ff4be1e23ef25173452c16900df73d6`
- 上游：`origin/work/2026-07-18-bankflow-verification`
- ahead/behind：`47/0`
- 工作区：开始前干净，无未提交文件
- merge/rebase/冲突：无

仓库通过 worktree `.git` 文件连接到主仓库。沙箱账户触发 Git safe-directory 所有者检查，审计命令使用单次 `-c safe.directory=...`，未修改全局 Git 配置。

## 2. 既有入口与代码定位

- 生产流水核查入口：`启动流水核查工作台.bat → gui_verification_app.py`
- schema 1.16 加载和校验：`bankflow_v2/standard_result_view.py`
- 旧 GUI 购车映射：`gui_verification.py` 中 `_purchase_categories`、`_purchase_rows`、`_purchase_overview`
- transaction_id 证据定位：`standard_result_view.evidence_transaction()`
- V5 视觉基线存在且含 11 张截图

## 3. 旧工作区保护

开始前没有未提交文件，因此没有“旧未提交文件前后 SHA”集合。最终 tracked diff 为空，所有本轮文件均为未跟踪的新切片文件。抽检保护文件 SHA256：

- `gui_verification.py`：`A4359C3320E76B604E61CC125FDA78D2DB0AC90EA17ED981E430F1172D3CEDAA`
- `gui_verification_app.py`：`FD2B61CB28E94AC5CA95C670636CD8A8FE2DC7B756E6BB643FBBD7D2A051EB77`
- `recent_cases.py`：`3A850F374C673FC4CA608F6E6B7A1A389E6738A23C4B372208A2CAD2DB237345`
- `启动流水核查工作台.bat`：`B84B2D66AE532B9BFBE0C9297AE7F2D6D7E1DBA3591EB8DF14148A241B60788F`

schema 常量仍为 `SUPPORTED_SCHEMA_VERSION = "1.16"`。旧 GUI、旧启动器、解析器、经营规则、original_transactions 模型、recent_cases 逻辑和原测试均未修改或删除。

## 4. 新增结构

```text
bankflow_web/                    Python 外壳、Bridge、会话、DTO、适配和网络策略
web_frontend/                    V5 基线 React/TypeScript/Vite 前端
tests/test_web_*.py              4 个定向测试文件
docs/Web_GUI_桥接契约_v1.md
docs/Web_GUI_12B0_集成验证报告.md
gui_web_spike_app.py
启动Web流水核查集成切片.bat
requirements-web-desktop.txt
BankFlowWebSpike.spec
```

`web_frontend/dist` 和 `node_modules` 是本地生成物，由目录内 `.gitignore` 排除。

## 5. Python 桌面外壳与数据边界

计划结构为 `QApplication → QMainWindow → QWebEngineView → QWebChannel → WebBridge → CaseSession`。窗口标题和 1500×850 默认尺寸已写入独立入口，未修改旧 GUI。

`CaseSession` 保存完整结果、结果路径和只读 `PurchaseResultAdapter`。React 只接收案件头、购车摘要、当前页、当前选中 ID 和当前单笔证据；不接收完整 `standard_result`、`original_transactions`、全量证据索引或所有 raw 字段。

适配器只读取既有 `purchase_prepayment_funding_candidates` observation，不重新扫描 `original_transactions`，不重算关键词、下定、此前收入窗口或资金来源。边界固定显示：“此前收入只作时间并列，不表示资金来源。”

证据调用复用现有 `evidence_transaction()`，保持精确 ID、索引边界和原交易 ID 一致性检查。默认返回脱敏内容；完整原始字段仅针对当前一笔，在用户主动展开时显示。

## 6. React 构建与 V5 基线

- 保留字体栈：`Inter, Microsoft YaHei UI, Microsoft YaHei, Noto Sans CJK SC, Segoe UI`
- 保留深浅主题、Linear 侧栏、分组列表、Inspector、Lucide、Command Palette、hover/选中/焦点状态
- 默认不含静态模拟交易；构建产物不存在 `BF-001` 和“布局演示案例”
- QWebChannel 缺失时显示“未连接桌面后端”，不回退模拟案件
- `base: "./"`，正式设计为加载本地 `dist/index.html`
- 无 CDN、远程字体、远程图片或运行时 Node/npm 依赖

生产构建结果：Vite 6.4.3；JS 166.93 kB（gzip 53.18 kB）；CSS 12.81 kB（gzip 3.30 kB）；`npm audit` 为 0 vulnerabilities。

## 7. Bridge、DTO、分页和错误码

详见 `docs/Web_GUI_桥接契约_v1.md`。已实现统一 JSON 信封、request_id、elapsed_ms 和 payload_bytes。稳定错误码包含附件要求的九类错误；未知异常只写开发日志，前端不接收 Python 堆栈或内部异常对象。

分页允许 `25/50/100`，默认 50；筛选在 Python 端只过滤适配器读取到的既有分类。不会向 React 返回完整案件结果。

## 8. 网络隔离

`OfflineRequestInterceptor` 默认只允许 `file/qrc/data/blob/about`，阻止其他协议并写稳定日志。显式开发模式只允许指定的 `http://127.0.0.1` origin。前端资产全部本地化。

由于 `QWebEngineProfile` 无法初始化，网络拦截器尚未完成真实运行态验证，不能宣称断网验收通过。

## 9. 测试与构建结果

已通过：

- Python 新文件语法检查
- TypeScript `tsc -b`
- `npm.cmd run build`
- 18 项 Web 定向测试通过
- 覆盖 schema 1.16 fixture、schema 不兼容、损坏 JSON、无案件、既有购车 observation、无重新扫描、默认 50 条、分页参数、既有分类筛选、DTO 边界、精确证据、缺失 ID、索引越界、ID 不一致、默认脱敏、关闭/切换案件和 Bridge 堆栈不泄露

未执行或未完成：

- WebEngine 离屏启动：失败
- 全量 Python 单元测试与完整统一回归：停止条件触发后未执行
- 实际桌面启动和体验：未完成
- `git diff --check`：tracked diff 为空；未跟踪文件未形成可提交 diff

## 10. WebEngine 阻塞记录

环境：系统 Python 3.12.9、系统 PyQt6 6.11.0（未修改）、Node 24.15.0、npm 11.12.1、PyInstaller 系统 6.20.0/干净隔离环境 6.21.0。

验证环境：

1. `D:\Investigator PDF\.venvs\cd-bankflow-web-spike`：继承系统包后分别验证 PyQt/Qt/WebEngine 6.11 和 6.8 配套组合。
2. `D:\Investigator PDF\.venvs\cd-bankflow-web-spike-isolated`：不继承系统包，安装 PyQt6 6.8.1、Qt 6.8.2、PyQt6-WebEngine 6.8.0、WebEngine Qt 6.8.2。

两种环境均能导入 `PyQt6.QtWebEngineWidgets`，但在创建或首次访问 `QWebEngineProfile` 时进程退出。6.11 的 Windows Application Error 记录为：故障模块 `Qt6Core.dll 6.11.1.0`，异常 `0xc0000409`（BEX64），偏移 `0x000000000001cf68`。

沙箱内外、offscreen、实际 Windows 平台、禁用 GPU/Chromium sandbox 等诊断组合均未改变结果。未采用会破坏正式网络隔离或持久化边界的替代方案。

## 11. 真实案例、性能、截图和打包

在允许扫描的现有工作区范围内未找到任如冰或韩鹏飞 schema 1.16 JSON；只找到包含姓名的旧 schema 1.5 证据文件。未重新解析 PDF、未构造虚假真实结果。Python 契约测试使用现有 `build_bankflow_result(..., ai_config={})` 生成的明确测试 fixture。

由于 WebEngine 启动阻塞，启动到 frontend_ready、内存、两个真实案件耗时、真实分页/证据 payload、关闭释放、连续案件残留、子进程退出、DPI、桌面截图和实际离线体验均无有效数据。

`BankFlowWebSpike.spec` 已新增为独立 one-folder 草案。为遵守停止条件，未执行 PyInstaller 构建，因此没有包体、首次启动、资源完整性或杀毒误报结果。

## 12. 最终 Git 状态与未实施范围

所有本轮内容保持未提交、未推送。最终只有 Web 集成切片相关文件为 untracked；tracked diff 为空。

- 没有替换旧 GUI；没有执行完整 GUI 迁移
- 没有新建案件或重新解析 PDF
- 没有接入人工经营上下文修改、历史案件、人工核实/敏感交易/经营关联/资金余额/申报对照完整模块
- 没有接入消费水平、生活轨迹、用车轨迹、高德、AI 或公司客户信息 API
- 没有调用模型
- 没有修改 schema 1.16、解析器、业务规则、经营 AI 规则或 recent_cases
- 没有提交；没有推送

## 13. 是否建议进入 12B-1

**不建议。** 先在用户可控的本机 Python/Qt 环境中单独解决 `QWebEngineProfile` 的 `0xc0000409` 初始化故障，并完成“最小 Profile + 本地 HTML”运行测试。该门槛通过后，才能继续真实案件、运行时网络隔离、DPI、性能、截图和 PyInstaller one-folder 风险验证。
