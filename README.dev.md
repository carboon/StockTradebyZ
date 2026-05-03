# StockTrader 开发者说明

## 当前开发入口

只推荐：

```bash
./start.sh
```

容器运维：

```bash
./deploy/scripts/start.sh ps
./deploy/scripts/start.sh logs backend
./deploy/scripts/start.sh exec-backend
```

## 当前开发环境

开发环境运行的是：

- `postgres`
- `backend`
- `frontend-dev`
- `nginx-dev`

特点：

- 后端源码挂载，支持热更新
- 前端使用 Vite HMR
- 浏览器推荐走统一入口 `http://127.0.0.1:8080`

## 改代码的入口判断

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
