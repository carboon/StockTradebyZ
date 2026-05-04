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
