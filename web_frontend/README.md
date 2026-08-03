# 流水核查 Web 集成切片前端

本目录是 V5 Linear Web 视觉基线的仓库内独立副本，默认只通过 QWebChannel 读取 Python 端 schema 1.16 案件会话。

```powershell
npm.cmd install
npm.cmd run build
```

桌面正式模式直接加载 `dist/index.html`，不启动 Vite、不访问 `127.0.0.1`、不依赖 Node.js。浏览器直接打开时只显示“未连接桌面后端”，不会自动显示模拟案件。
