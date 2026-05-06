# StockTrader 开发者说明

## 开发入口

推荐流程：

```bash
cp .env.example deploy/.env
./start.sh
```

容器运维：

```bash
./deploy/scripts/start.sh ps
./deploy/scripts/start.sh logs backend
./deploy/scripts/start.sh exec-backend
```

## 开发环境组成

开发环境默认启动：

- `postgres`
- `backend`
- `frontend-dev`
- `nginx-dev`

特点：

- 后端源码挂载，支持热更新
- 前端使用 Vite HMR
- 浏览器统一入口为 `http://127.0.0.1:8080`

## 移动端本地联调

移动端兼容开发建议按两步执行：

1. 先用桌面模拟器快速调布局和交互
2. 再用手机真机通过局域网访问本机服务联调

### 局域网访问

前提：

- 电脑和手机连接同一个 Wi-Fi
- 本机防火墙允许访问 `5173`、`8000`、`8080`

当前前端 Vite 已支持监听所有网卡，也可以显式使用移动端开发脚本：

```bash
cd frontend
npm run dev:mobile
```

常用访问地址：

- 前端直连：`http://<LAN-IP>:5173`
- 统一入口：`http://<LAN-IP>:8080`
- 后端 API：`http://<LAN-IP>:8000`

查看本机局域网 IP 的常见方式：

```bash
ipconfig getifaddr en0
ifconfig | grep "inet "
```

如果使用 Docker 开发环境，推荐先启动：

```bash
./start.sh
```

然后在手机浏览器访问：

- `http://<LAN-IP>:8080`

推荐把手机验证分成两步：

1. 先访问 `http://<LAN-IP>:8080`，验证真实联调链路
2. 再访问 `http://<LAN-IP>:5173`，验证前端样式调试链路

这样可以同时覆盖：

- Nginx 入口是否正常
- 前后端接口联通是否正常
- 手机端样式和触控交互是否正常

### 环境变量与 API 地址

移动端联调时，不要把 API 地址写死为 `127.0.0.1` 或 `localhost`，因为手机访问时这会指向手机自身。

前端开发代理默认读取：

- `VITE_API_PROXY_TARGET`

默认值：

- `http://127.0.0.1:8000`

如果通过 Vite 直连页面在手机上访问，建议显式指定：

```bash
cd frontend
VITE_API_PROXY_TARGET=http://<LAN-IP>:8000 npm run dev:mobile
```

如果通过统一入口 `http://<LAN-IP>:8080` 访问，通常不需要单独改前端代理，但仍应确认：

- 后端服务可通过局域网地址访问
- CORS 没有只限制到 `127.0.0.1`
- WebSocket 推送在局域网地址下可正常建立

### 桌面模拟器

日常开发优先使用桌面模拟器做快速检查：

- Chrome DevTools Device Mode
- 可选：Responsively App

建议至少检查这些视口：

- `390x844`
- `430x932`
- `768x1024`
- `1024x768`

重点检查：

- 是否存在横向滚动
- 顶栏、抽屉、弹窗是否可用
- 表格是否在移动端降级为卡片或摘要
- 图表 resize 是否正常
- 底部操作栏和键盘弹出是否遮挡主要操作

### 真机访问

真机联调至少覆盖：

- iPhone Safari
- Android Chrome

建议重点检查：

- 抽屉导航
- 长列表滚动
- 输入法弹出遮挡
- 地址栏导致的视口变化
- 图表旋转后 resize
- WebSocket、日志、任务状态是否持续刷新

如果需要远程调试：

- iPhone：Safari Web Inspector
- Android：Chrome Remote Debugging

### 建议的前端命令

```bash
cd frontend
npm install
npm run dev
npm run dev:mobile
npm run build
npm run test
```

说明：

- `npm run dev`：本机桌面开发
- `npm run dev:mobile`：显式以局域网模式启动，便于手机访问
- `npm run build`：移动端样式改造后的构建回归
- `npm run test`：Vitest 单测回归

## 配置文件约定

- 部署与容器运行：`deploy/.env`
- 宿主机直接运行 Python/pytest：优先读取仓库根目录 `.env`
- 示例模板：`.env.example`

建议：

- 不要把真实凭据写进 `.env.example`
- 不要提交 `deploy/.env`、根目录 `.env`
- 新增配置项时，同时更新 `.env.example`、`README.md`、`DEPLOYMENT.md`

## Python 与 pytest

项目内本地 Python 一律使用仓库根目录 `.venv`，不要依赖系统级 `python` 或用户级 `pytest`。

本机运行测试：

```bash
.venv/bin/python -m pytest
```

创建虚拟环境：

```bash
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

说明：

- 不保证系统 `python`、`python3`、`pytest` 可直接用于本仓库
- `pytest` 如来自 `pipx` 或用户目录，可能与项目解释器脱钩
- 本地从仓库根目录执行测试时，配置会自动读取根目录 `.env` 和 `backend/.env`
- 当前运行时只支持 PostgreSQL；测试隔离仍允许使用内存 SQLite

## 改代码入口

- 改策略和复核逻辑：看 `pipeline/`、`agent/`
- 改 API、任务、数据拼装：看 `backend/`
- 改页面展示：看 `frontend/`
- 改运行和部署：看 `deploy/`

## 容器内调试

进入后端容器：

```bash
./deploy/scripts/start.sh exec-backend
```

容器内常见命令：

```bash
python run_all.py
python -m pipeline.cli preselect
pytest
```

说明：

- 容器内可以直接使用 `pytest`
- 容器外请优先使用 `.venv/bin/python -m pytest`
- `postgres` 只在 Docker Compose 网络内可解析；宿主机测试若仍使用 `@postgres:5432` 会失败

## 日更链路回放

```bash
python backend/daily_update_test.py --help
python backend/daily_update_test.py --target-date 2026-04-30
```
