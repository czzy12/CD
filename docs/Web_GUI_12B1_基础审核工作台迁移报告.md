# Web GUI 12B-1 基础审核工作台迁移报告

验收日期：2026-08-03（Asia/Shanghai）

## 结论

基于 pywebview + Microsoft Edge WebView2 的基础审核工作台已完成源码正式迁移。正式入口与技术切片分离，共用唯一 React 前端、运行时检查、安全策略、CaseSession、DTO、ResultAdapter、Bridge 和资源定位。旧 Qt GUI 默认入口未修改，未打包、未提交、未推送。

本轮源码正式入口验收通过；最新基础功能打包验收暂缓至阶段收口，不阻断后续开发。

## 1. Git 与开始基线

- 分支：`work/2026-07-18-bankflow-verification`
- 开始 HEAD：`2c6c246c33f2c44f442ff7bd43f1632df5851003`
- 开始状态：tracked diff 为空、未跟踪文件为空、无冲突或合并状态，与 origin 同步。
- 12B-0A/12B-0B 功能提交：`28a70e4`；交接记录提交：`2c6c246`。
- 仓库外基线快照：系统临时目录 `CD-bankflow-refactor-12B1-baseline-20260803`，含 226 个 tracked 文件清单和 SHA256 清单。
- 两个批准 JSON 的大小、修改时间和 SHA256 与 12B-0B 验收记录一致；本报告不记录客户路径或内容。
- 开始测试：334 PASS / 2 SKIP。
- 开始前端构建：TypeScript 与 Vite 6.4.3 生产构建通过。

## 2. 入口与资源

- 旧 GUI：`gui_v2.py` / `启动GUI.bat`，未修改。
- 保留技术切片：`gui_webview2_spike_app.py` / `启动WebView2流水核查集成切片.bat`。
- 新增正式入口：`gui_webview2_app.py`。
- 新增正式启动器：`启动WebView2流水核查工作台.bat`。
- 窗口标题：`流水核查工作台`。
- 正式与切片入口均只加载 `web_frontend/dist`，不启动 Vite、不打开浏览器、无地址栏，运行时不依赖 Node.js/npm。
- Windows 强制 `edgechromium`，继续检查 WebView2 Runtime；开发者工具仅 debug 模式开放。

## 3. 前端结构与视觉

```text
web_frontend/src/
  app/App.tsx
  app/requestGuard.ts
  bridge/contracts.ts
  bridge/desktopBridge.ts
  bridge/pywebviewBridgeAdapter.ts
  components/IconButton.tsx
  styles/tokens.css
  styles/app.css
  main.tsx
```

V5 Linear 基线保持：紧凑侧栏、三栏布局、CSS Grid issue list、右侧 Inspector、Lucide 图标、深浅主题、Command Palette、字体栈、hover/选中/焦点、滚动条和 CSS 令牌。没有引入 UI 框架、传统 table、Dashboard 卡片墙、远程字体、CDN 或模拟案件数据。125% 与 150% 实际 WebView2 缩放分别返回 DPR 1.25/1.5，完整进程内 QA 通过。

## 4. Python 应用层与 Bridge

- `CaseSession` 持有完整 schema 结果、内部路径、Adapter、ModuleRegistry、`case_session_id` 和 `case_revision`。
- `ModuleRegistry` 返回模块状态、数量、筛选能力和证据能力；React 不计算业务数量。
- API 信封继续包含稳定错误码、`request_id`、`elapsed_ms` 和 `payload_bytes`。
- 前端版本 `0.2.0`，API 版本 `1`，只支持 schema `1.16`。
- 正式前端只经集中 `PyWebviewBridgeAdapter` 调用白名单 API，不散布 `window.pywebview.api`。
- 未来服务仅在文档边界中保留，没有创建 AI、客户信息、位置、recent cases 或任务按钮。

## 5. 模块状态

| 模块 | case-025 | case-129 | 说明 |
| --- | ---: | ---: | --- |
| 下定与购车 | available / 6 | available / 31 | 既有购车与此前收入观察 |
| 敏感交易 | available / 2 | available / 26 | 既有敏感文字上下文候选 |
| 经营痕迹 | unavailable / 0 | unavailable / 0 | 现有观察不可用且没有正向候选；未调用 AI |
| 资金与余额 | available / 818 | available / 486 | 既有大额交易候选 |
| 申报对照 | empty / 0 | empty / 0 | 稳定结构，当前无项目 |
| 人工核实 | available / 4 | available / 4 | 既有人工问题 |
| 用车记录 | not_implemented | not_implemented | 无稳定后端结果 |
| 居住/工作轨迹 | not_implemented | not_implemented | 无稳定后端结果 |
| 消费水平 | not_implemented | not_implemented | 无稳定后端结果 |

逐项 schema 路径、旧 GUI 来源和能力见《Web GUI 模块映射清单 v1》。本轮没有重算业务规则，也没有扫描原交易生成候选。

## 6. 分页、筛选和 Inspector

- 统一 `list_module_items`，默认 50 条，允许 25/50/100。
- Python 执行状态、分类、来源、关键词和稳定日期范围筛选；筛选后页码、选择和 Inspector 清空。
- 列表只接收当前页 DTO，不持有完整结果或完整原交易。
- 上下键切换，Enter 聚焦当前 Inspector，Esc 关闭；上一笔/下一笔只在当前页内移动。
- 证据只按 `transaction_id` 精确索引；不按金额、日期或文本猜测。
- 默认脱敏，用户主动展开后只显示当前一笔的完整允许内容。

## 7. 来源复核与切案隔离

- case-025：11 来源、1 来源需复核；面板只显示 schema `status == review`，`review_reason` 精确来自 schema。
- case-129：来源复核数量为 0，不残留 case-025 提示。
- 025→129 时模块、筛选、选择、Inspector、来源面板和旧错误立即清空；129→025 状态重新由 Python 加载。
- 旧会话请求返回 `STALE_CASE`；在新会话查询旧交易 ID 返回 `TRANSACTION_NOT_FOUND`。
- 前端以会话 ID 和请求序号双重丢弃过期响应。

## 8. 空、加载和错误状态

- 未加载案件只显示“打开标准结果”，无模拟数量和交易。
- 加载时禁止重复打开并保持列表布局。
- 取消文件选择不作为错误；无效 JSON、非 1.16、无案件、过期案件和证据不可用均使用稳定中文错误。
- `empty` 显示“当前结果中没有该类候选”；`not_implemented` 显示“未实施”并禁用；两者不混淆。

## 9. 网络与安全

- 本地 Vite dist 内联加载；CSP `connect-src 'none'`。
- 外链、`fetch`、XHR、WebSocket 和 EventSource 继续阻断；进程内同步 XHR 外网检查通过。
- 没有远程字体、图标、统计脚本、AI/API 请求、Key、通用文件读取或任意 Python 执行能力。
- DTO 检查不含完整结果、完整原交易、原始字段集合或客户绝对路径；来源面板不返回完整账号、身份证号、原文件内容或堆栈。

## 10. 实际源码验收

正式源码入口使用两个批准 JSON 完成进程内 QA：

- Edge Chromium 渲染、前端 ready、9 个模块和至少 4 个 available 模块通过。
- 未加载空状态由前端自动化测试与实际首次窗口确认。
- case-025 案件头、11 来源、1 来源需复核及原因通过。
- 下定与购车 3 笔、敏感交易 1 笔精确证据检查通过。
- 模块切换、Inspector 打开关闭、主题切换通过。
- 025→129→025 切案、来源提示清理、选择/Inspector 清理和旧 ID 失效通过。
- 外网阻断通过；前端脚本错误为 0。
- 125%/150% 缩放完整 QA 通过。
- QA 窗口自动关闭，进程正常退出。

## 11. 性能

| 项目 | 结果 |
| --- | ---: |
| case-025 加载（含 Session/Registry） | 105.317 ms |
| case-129 加载（含 Session/Registry） | 135.984 ms |
| 模块目录 | 0.278 / 0.233 ms |
| 50 条分页 | 0.209–0.270 ms（大列表） |
| 空闲 Python RSS | 31.48 MiB |
| case-025 后 RSS | 60.98 MiB |
| case-129 切换后 RSS | 84.35 MiB |

未传输完整结果、未重复解析当前案件、未重建证据索引、未在前端渲染全部交易，未见相对既有约 101/183ms 案件加载基线的明显倍数退化。React ready 与完整窗口 RSS 延续 12B-0A 路线，本轮以实际正式窗口 QA 无超时、无前端错误作为退化检查。

## 12. 测试与构建

- WebView2、模块、来源复核和证据定向测试：通过。
- 完整 Python unittest：343 PASS / 2 SKIP；跳过项仍是需要显式 GUI 环境开关的既有可见窗口测试。
- 前端 Node 测试：13 PASS，覆盖未连接/Bridge 错误契约、未加载与切案清理、会话过期保护、模块可用/禁用状态、统一模块调用、分页、筛选重置、Inspector 清理、来源复核提示、主题、API 版本和证据会话 ID；未增加测试依赖。
- TypeScript `tsc -b`：通过。
- Vite 6.4.3 生产构建：通过，1584 modules transformed，JS 171.70 kB、CSS 16.06 kB。
- Python `compileall`：通过。
- `git diff --check`：通过，仅有 Git 的 LF/CRLF 工作区提示，无空白错误。
- 没有删除、跳过或弱化既有测试；完整测试数由 334 增至 343。

## 13. 修改范围

新增正式入口、启动器、ModuleRegistry、工作台 Python 测试、前端 app/bridge/components/styles/tests 目录及三份 12B-1 文档；修改 CaseSession、DTO、WebView2 API/app/进程内 QA、现有 WebView2 测试和共享前端。未修改 schema、业务规则、解析器、旧 Qt GUI、recent cases、spec 或 Runtime 部署方式。

结束哈希复核：开始时 226 个 tracked 文件中 209 个保持完全一致，17 个变化均与上述清单及 Git diff 对应，0 个缺失；两个批准 JSON 的 SHA256 均保持不变。结束状态为 17 个 tracked 修改及本报告所列新增文件/目录，未提交、未推送。

## 14. 本轮未实施与下一步

未实施 AI 调用/授权、客户信息 API、高德、OCR、新建案件解析、Worker 进度、历史案件、经营上下文修改/重算、报告导出、消费/生活/用车后端、schema 升级、更新、登录、网络服务、打包和安装包。

建议在用户确认基础审核架构、Linear 视觉、模块导航、列表、Inspector 和来源复核后，再决定是否进入 12B-2；本轮不自动进入。
