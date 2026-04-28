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
.\bootstrap-local.bat
```

行为说明：

- 首次执行会自动创建 `.venv`
- 自动安装 Python 和前端依赖
- 自动从 `.env.example` 复制 `.env`
- 如果尚未配置 `TUSHARE_TOKEN`，会先启动应用，等待你在页面内完成配置
- 如果已配置 `TUSHARE_TOKEN`，会自动启动服务，再通过任务中心 API 执行初始化数据
- 初始化和增量更新过程中，CLI 和页面右上角都会显示进度、总数和预计剩余时间

## 分步执行

```powershell
.\install-local.bat
.\preflight-local.bat
.\init-data.bat
.\start-local.bat
.\status-local.bat
.\stop-local.bat
.\uninstall-local.bat
```

也可以直接执行 PowerShell 版本：

```powershell
.\install-local.ps1
.\preflight-local.ps1
.\start-local.ps1
```

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
.\uninstall-local.bat
```

会清理以下内容：

- 停止前后端进程
- 删除 `.env`
- 删除 `.venv`
- 删除 `frontend/.env.local`
- 删除 `frontend/node_modules`
- 删除 `frontend/dist`
- 删除 `data`
- 删除 `deploy`

## 常见问题

### PowerShell 拒绝执行脚本

优先使用 `*.bat` 入口，例如：

```powershell
.\bootstrap-local.bat
```

这些包装器会自动使用 `ExecutionPolicy Bypass` 调用 PowerShell。

### 端口被占用

可以先执行：

```powershell
.\status-local.bat
.\stop-local.bat
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

当前 Windows 入口已经按绝对路径和参数数组调用进程，支持这类目录，但建议仍在首次部署时执行一次 `.\status-local.bat` 验证前后端是否都能正常拉起。
