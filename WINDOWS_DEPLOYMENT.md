# Windows 本地部署

本文档仅覆盖 Windows 本地运行，不涉及 Docker。

## 前置依赖

- Python `3.11+`
- Node.js `18+`
- npm
- PowerShell `5.1+` 或 PowerShell `7+`

可选安装方式：

```powershell
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
```

## 一键安装与启动

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
```

行为说明：

- 首次执行会自动创建 `.venv`
- 如果系统缺少 Python / Node / npm，会自动执行 `winget`
- 自动安装或更新 Python 项目依赖和前端依赖
- 自动从 `.env.example` 复制 `.env`
- 默认优先使用国内镜像：`pypi.tuna.tsinghua.edu.cn`、`mirrors.aliyun.com`、`registry.npmmirror.com`
- 精简输出 `当前阶段/总阶段/预计剩余`
- 如果尚未配置 `TUSHARE_TOKEN`，会先启动应用，等待你在页面内完成配置
- 如果已配置 `TUSHARE_TOKEN` 且本地没有持久化数据，会自动启动服务并执行首次初始化
- 初始化和增量更新过程中，CLI 和页面右上角都会显示进度、总数和预计剩余时间

说明：

- 首次自动装系统依赖时，Windows 可能会弹出 UAC 提权确认
- 如果系统里的 `winget` 本身缺失，`start-local.ps1` 会先尝试自动修复 WinGet，再继续安装 Python

## 常用入口

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-local.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall-local.ps1
```

高级命令不再单独提供顶层脚本，可直接调用：

```powershell
py -3.11 .\tools\localctl.py init-data
py -3.11 .\tools\localctl.py status
```

说明：

- `start-local.ps1` 负责系统级 Python / Node 自举和应用启动
- `stop-local.ps1`、`uninstall-local.ps1` 是原生 PowerShell 脚本，不依赖 Python

## 默认地址

- 应用首页: `http://127.0.0.1:8000`
- API 文档: `http://127.0.0.1:8000/docs`

## 配置文件

首次安装会自动生成：

- `.env`
- `frontend/.env.local`

至少需要在 `.env` 中配置：

```env
TUSHARE_TOKEN=你的token
```

## 卸载

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall-local.ps1
```

会清理以下内容：

- 停止前后端进程
- 删除用户级 `launchd/systemd` 等项目服务文件（如存在）
- 删除 `.env`
- 删除 `.venv`
- 删除 `frontend/.env.local`
- 删除 `frontend/node_modules`
- 删除 `frontend/dist`
- 删除 `frontend/coverage`、`.coverage`、`htmlcov`
- 删除 `data`
- 删除 `deploy`

## 常见问题

### PowerShell 拒绝执行脚本

推荐直接这样执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
```

这样可以绕过本机默认执行策略限制。

### 端口被占用

可以先执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-local.ps1
```

默认端口可在 `.env` 中调整：

```env
BACKEND_PORT=8000
VITE_API_BASE_URL=/api
```

说明：

- 本地个人部署由后端统一提供前端页面，不再依赖 `5173` 开发服务器
- `FRONTEND_PORT` 仅对前端开发调试场景有意义

### 安装目录包含空格或中文

当前 Windows 入口已经按绝对路径和参数数组调用进程，支持这类目录。首次部署后可直接访问 `http://127.0.0.1:8000` 验证是否拉起成功。
