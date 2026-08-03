# Web GUI 12B-0A WebView2 验证报告

## 结论

状态：**pywebview + Microsoft Edge WebView2 技术路线验证通过；本轮完成，不进入 12B-1。**

独立源码入口和 PyInstaller one-folder 均能强制使用 `edgechromium`，本地 React 生产构建、JS-Python 白名单 API、既有 schema 1.16 DTO/CaseSession/ResultAdapter、50 条分页和 transaction_id 证据契约均已接通。最小窗口连续启动 5/5，打包后启动退出为 0，未发现新增残留 WebView2 进程，包内未混入 Qt、CEF、Node.js 或 npm。

仓库内仍未找到任如冰、韩鹏飞或其他可用 schema 1.16 真实结果，因此没有伪造真实案例结论。进入 12B-1 前仍应以用户明确提供的既有 schema 1.16 结果完成真实案件、真实 transaction_id 和大文件切换门槛；本轮不重新解析 PDF。

## 1. 开始 Git 状态与 12B-0 保护

- 分支：`work/2026-07-18-bankflow-verification`
- HEAD：`32b6f4b52ff4be1e23ef25173452c16900df73d6`
- 开始时 tracked diff：空
- 12B-0 未跟踪源文件：28 个，开始前全部计算 SHA256
- 12B-0 定向测试：运行 18 项，结果 OK，其中旧 Qt 离屏测试按环境开关跳过 1 项
- `web_frontend` 生产构建：通过
- Qt WebEngine 失败记录继续保留在 `docs/Web_GUI_12B0_集成验证报告.md`

结束前复核 28 个 12B-0 文件：27 个 SHA256 完全不变；唯一变化是明确复用调整的 `web_frontend/src/main.tsx`，从直接 QWebChannel 调用改为桌面框架无关的 `DesktopBridge`。以下文件未覆盖或删除：

- `gui_web_spike_app.py`
- `BankFlowWebSpike.spec`
- `tests/test_web_shell_smoke.py`
- `bankflow_web/contracts.py`
- `bankflow_web/case_session.py`
- `bankflow_web/result_adapter.py`
- `docs/Web_GUI_桥接契约_v1.md`
- `docs/Web_GUI_12B0_集成验证报告.md`

`web_frontend/src/main.tsx` SHA256：

- 调整前：`7459FB9DF0E97EAE81121CFD81863B14C36A84A2E00567E961E795E7BE95BF45`
- 调整后：`AA5F6B926D5BF0504B99EEF0C88767B89E22EEE535CB01D0EEAC5692D41BE0AB`

## 2. 新增内容

```text
bankflow_webview2/
  __init__.py
  app.py
  api.py
  bridge_adapter.py
  resource_paths.py
  runtime_check.py
  security_policy.py
  smoke.py

tests/
  test_webview2_api.py
  test_webview2_bridge_adapter.py
  test_webview2_runtime_check.py
  test_webview2_shell_smoke.py

web_frontend/src/bridge/desktopBridge.ts
gui_webview2_spike_app.py
启动WebView2流水核查集成切片.bat
requirements-webview2-desktop.txt
BankFlowWebView2Spike.spec
docs/Web_GUI_12B0A_WebView2空状态.png
docs/Web_GUI_12B0A_WebView2验证报告.md
```

独立构建产物：

```text
build-webview2-spike/
dist-webview2-spike/BankFlowWebView2Spike/
```

没有修改旧 GUI、旧启动器、schema、解析器、购车规则、经营 AI 规则或 recent_cases。

## 3. 隔离环境

环境：`D:\Investigator PDF\.venvs\cd-bankflow-webview2-spike`

- Python 3.12.9 x64
- pywebview 6.2.1
- pythonnet 3.1.0
- PyInstaller 6.21.0
- psutil 7.2.2
- pdfplumber 0.11.10
- pandas 3.0.5
- openpyxl 3.1.5
- Pillow 12.3.0
- WebView2 Runtime 依赖由 pywebview wheel 提供

隔离环境未安装 PyQt6、PyQt6-WebEngine、PySide、Qt pywebview extras 或 CEF。项目根 `requirements.txt` 含 PyQt6，因此本轮没有整体安装该文件，只安装既有后端导入所需的非 Qt 项。

## 4. WebView2 Runtime 与渲染器

- Windows：Windows 11，build 22631
- Python 架构：64-bit
- 系统架构：AMD64/x64
- Runtime：`150.0.4078.105`
- Runtime 架构：x64（读取 `msedgewebview2.exe` PE machine 字段确认）
- 注册来源：HKLM 32-bit registry view 的 Evergreen Runtime client key
- 实际 pywebview 渲染器：`edgechromium`

Runtime 状态模型包含：

- `AVAILABLE`
- `MISSING`
- `VERSION_UNAVAILABLE`
- `INITIALIZATION_FAILED`

缺失时不联网下载，不回退 MSHTML，由独立入口显示自然中文错误。窗口初始化事件若返回任何非 `edgechromium` 值，会取消启动并报错；代码中没有 MSHTML 启动路径。

## 5. 最小窗口与 JS-Python 桥接

最小烟测内容：本地内存 HTML、中文字体、`window.pywebview.api.ping()`、Python `pong`、桥接完成后自动关闭。

首次诊断时，烟测 API 将 pywebview Window 放在公开属性，pywebview 尝试递归序列化原生窗口对象，导致桥接超时。该问题属于烟测封装错误；改为私有 `_window` 后，公开表面只剩 `ping` 和 `complete`，桥接立即通过。业务 API 从一开始即使用全部私有状态和明确白名单方法。

连续 5 次结果：

- 成功率：5/5
- 单次生命周期：1.209–1.262 秒
- 中文结果：`中文显示正常`
- JS-Python：`ping → pong`
- 关闭后新增 `msedgewebview2` 残留进程：0

完整 React 壳自动烟测同样通过：前端调用 `get_app_state` 后自动关闭，退出码 0。

## 6. 本地前端资源与视觉

继续复用 `web_frontend/dist`，没有重新设计 GUI。保留 V5 的字体栈、Linear 式侧栏、分组交易列表、Inspector、深浅主题、Lucide 图标、Command Palette、hover/选中/焦点状态。

资源加载方式：Python 读取本地 Vite `dist/index.html`、JS 和 CSS，组装为一份内存 HTML 后交给 WebView2。没有启动 HTTP 服务，没有监听端口，没有访问局域网或互联网。内存 HTML 大小为 183,354 bytes。

空状态实际截图：`docs/Web_GUI_12B0A_WebView2空状态.png`。截图人工复核显示深色 V5 空状态、侧栏、标题栏和打开按钮正常，无明显视觉退化。

TypeScript 默认桌面实现为 `PyWebviewBridgeAdapter`；只有显式 `?bridge=qwebchannel` 才启用历史 `QWebChannelAdapter`。普通浏览器或未连接桌面 API 时显示“未连接桌面后端”，不回退 mock。

## 7. 网络与安全

内存文档设置 CSP：

```text
default-src 'none'
script-src 'unsafe-inline'
style-src 'unsafe-inline'
img-src data: blob:
font-src 'none'
connect-src 'none'
object-src 'none'
frame-src 'none'
base-uri 'none'
form-action 'none'
```

前端额外防护：

- 阻止外部链接点击和 `window.open`
- 外部 `fetch`/XHR/WebSocket/EventSource 直接拒绝
- 下载关闭
- 外部链接不交给系统浏览器
- file URL 权限关闭
- 开发者工具默认关闭，仅 `--debug` 显式开启
- JavaScript 中无 API Key
- 不向前端返回客户绝对路径

实际烟测在 CSP 页面执行 `fetch('https://example.invalid/...')`，三次均得到 `networkBlocked: true`，请求由浏览器策略在发出前拒绝。

## 8. 桥接、DTO、文件选择与线程

前端统一 `DesktopBridge` 提供：

- `getAppState`
- `selectStandardResult`
- `loadStandardResult`
- `getCaseHeader`
- `getPurchaseSummary`
- `listPurchaseTransactions`
- `getEvidence`
- `closeCase`

Python `WebView2Api` 的公开方法集合经测试严格对应上述八项 snake_case API；窗口、会话、锁、事件和桥接对象均为私有属性。

每次响应使用稳定 `ApiEnvelope`，含 `ok/data/error/meta`、`request_id`、`elapsed_ms` 和 `payload_bytes`。未知异常写开发日志，返回 `INTERNAL_ERROR`，不把 Python traceback 或内部异常文本传给 React。

文件选择使用 pywebview Windows 原生打开对话框，只允许 `*.json`。取消返回稳定 `CANCELLED / 未选择文件`；绝对路径只留在 Python。

pywebview JS API 在工作线程执行文件读取，避免长时间占用 GUI 主线程。`WebView2Api` 用 `RLock` 串行化加载、查询、关闭和案件切换，防止并发覆盖；窗口关闭设置关闭标记并清空会话。本轮没有启动 VerificationWorker，也没有解析 PDF。

## 9. 业务复用边界

复用：

- `bankflow_web.case_session.CaseSession`
- `bankflow_web.result_adapter.PurchaseResultAdapter`
- `bankflow_web.contracts`
- `bankflow_v2.standard_result_view.evidence_transaction`

应用没有扫描或重算 `original_transactions`，只读取既有 `purchase_prepayment_funding_candidates` observation。完整标准结果只存在 Python；React 只持有案件头、摘要、当前 50 条、当前选中 ID 和当前单笔证据。

证据仍通过 transaction_id 精确索引，保持索引越界和 ID 不一致时 fail closed。默认显示脱敏原字段；用户主动展开时只显示当前一笔完整原字段。

## 10. 真实案例

在当前仓库范围按文件名及 schema 版本搜索，未找到：

- 任如冰 schema 1.16 结果
- 韩鹏飞 schema 1.16 结果
- 其他可供本轮使用的 schema 1.16 JSON

没有读取生产 JSON、没有调用 recent_cases、没有重新解析 PDF、没有生成虚假“真实结果”。因此以下项目没有真实案例数据：真实案件头、真实 original_transactions 数量前后对照、真实证据索引前后对照、两名真实案件连续切换和真实 transaction_id 点击。

这些能力的契约与状态隔离由 schema 1.16 测试 fixture 覆盖，但不能替代真实验收。

## 11. 性能

源码完整壳自动烟测：

| 指标 | 结果 |
| --- | ---: |
| Runtime 检测 | 112.619 ms |
| 创建 pywebview Window 对象 | 152.902 ms（累计） |
| WebView2 initialized | 488.713 ms（累计） |
| React 调用桌面 API ready | 905.209 ms（累计） |
| ready 时 Python 进程 RSS | 104,898,560 bytes（约 100.0 MiB） |
| 前端内存 HTML | 183,354 bytes |
| 自动烟测总生命周期 | 1,824.313 ms |

明确标注为测试 fixture 的业务测量：

| 指标 | 结果 |
| --- | ---: |
| schema 1.16 双交易 fixture 构建并 bind | 2.214 ms |
| 加载前 Python RSS | 37,216,256 bytes |
| 加载后 Python RSS | 37,527,552 bytes |
| 关闭案件并 GC 后 Python RSS | 37,527,552 bytes |
| 50/60 条分页适配 | 0.002 ms |
| 50 条桥接封装 | 0.231 ms |
| 50 条 payload | 15,234 bytes |
| 单笔证据封装 | 0.922 ms |
| 单笔证据 payload | 722 bytes |

React 渲染耗时未单独使用浏览器 Performance API拆分；当前只有从进程启动到 React 调用桌面 API ready 的累计值。真实大文件加载、真实案件后内存和真实案件切换耗时因没有真实 schema 1.16 文件而未测。

## 12. DPI

通过 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--force-device-scale-factor` 分别启动最小 WebView2：

- 100%：`devicePixelRatio = 1`
- 125%：`devicePixelRatio = 1.25`
- 150%：`devicePixelRatio = 1.5`

三次中文、桥接、CSP 阻网和自动关闭均通过。该方法验证 WebView2 的对应缩放渲染路径，没有持久修改 Windows 系统缩放设置。

## 13. 测试与构建

通过：

- Python compileall
- TypeScript `tsc -b`
- Vite 6.4.3 生产构建
- WebView2 定向测试运行 14 项，结果 OK；可见 GUI 项按开关跳过 1 项并已单独实际运行
- 原 Web 定向测试运行 18 项，结果 OK；旧 Qt 离屏项跳过 1 项
- 当前全量 Python unittest 运行 327 项，结果 OK；2 项按 GUI 环境开关跳过
- 完整源码壳实际启动和前端 ready
- 最小窗口连续启动 5/5
- 100%/125%/150% scale factor
- CSP 实际阻止外部 fetch
- `git diff --check`

Vite 新构建：JS 168.68 kB（gzip 53.59 kB），CSS 12.81 kB（gzip 3.30 kB）。

## 14. PyInstaller

独立 spec：`BankFlowWebView2Spike.spec`

构建目录：

- work：`build-webview2-spike`
- dist：`dist-webview2-spike/BankFlowWebView2Spike`

结果：

- one-folder 文件数：1,027
- 总大小：116,694,755 bytes（111.29 MiB）
- 主 EXE：12,005,222 bytes
- 包含 `Microsoft.Web.WebView2.Core.dll`
- 包含 `Microsoft.Web.WebView2.WinForms.dll`
- 包含 x86/x64/arm64 `WebView2Loader.dll`
- 包含 `web_frontend/dist`
- 未发现 PyQt6、PySide、QtWebEngineProcess、Qt DLL 或 CEF
- 未发现 Node.js 或 npm
- 打包 EXE 自动烟测退出码：0
- 打包 EXE 关闭后新增 WebView2 残留进程：0

打包运行使用系统 Evergreen Runtime；没有携带 Fixed Version Runtime。离线运行不需要互联网，但目标机器必须已有 WebView2 Runtime。

分发策略对比：

- A 系统 Evergreen Runtime：包最小，本轮已验证；需启动前检测。
- B 安装包检测并安装 Evergreen：用户体验完整，但安装阶段需要独立授权和分发流程，本轮不实施。
- C Fixed Version Runtime：完全固定版本、包体明显增大，需额外更新与安全维护，本轮不强制采用。

## 15. 最终边界与建议

- 未提交、未推送
- 未替换生产 GUI
- 未进入 12B-1
- 未修改 schema 1.16
- 未修改解析器或下定购车规则
- 未接 AI、客户信息 API 或高德
- 未访问真实客户资料或生产 JSON
- 旧 Qt WebEngine 失败记录完整保留
- tracked diff 为空；本轮内容与 12B-0 内容均保持未跟踪

建议：**认可 WebView2 作为后续桌面壳候选，但暂不直接进入 12B-1。** 先由用户提供或明确授权一个既有 schema 1.16 标准结果，完成真实案件头、50 条真实分页、真实 transaction_id 证据、连续切换和大文件关闭行为后，再进入 12B-1。
