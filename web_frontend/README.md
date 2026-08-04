# 流水核查工作台前端

本目录是正式 WebView2 候选工作台和保留的技术切片共用的唯一 React + TypeScript + Vite 前端。

- 正式源码入口：`gui_webview2_app.py`
- 正式启动器：`启动WebView2流水核查工作台.bat`
- 技术切片入口：`gui_webview2_spike_app.py`
- 生产资源：`web_frontend/dist`

运行时不启动 Vite，不依赖 Node.js/npm，不访问网络。开发阶段使用：

```powershell
npm run typecheck
npm test
npm run build
```
