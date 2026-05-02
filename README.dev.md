# StockTrader 2.0 开发者说明

这份文档只保留开发入口和调试要点。完整架构说明以 [ARCHITECTURE.md](ARCHITECTURE.md) 为准，部署说明以 [DEPLOYMENT.md](DEPLOYMENT.md) / [WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md) 为准。

## 先看什么

- 想理解当前系统怎么拼起来：看 [ARCHITECTURE.md](ARCHITECTURE.md)
- 想启动本地个人部署：看 [DEPLOYMENT.md](DEPLOYMENT.md)
- 想改选股结果：先看 `pipeline/` 和 `agent/`
- 想改页面或任务编排：再看 `backend/` 和 `frontend/`

## 当前代码边界

- `run_all.py` 仍是全量业务流程的总入口
- `pipeline/` 负责抓数、初选、回测
- `agent/` 负责 quant 复核、单票分析、持仓报告
- `backend/app/services/task_service.py` 不是重写业务逻辑，而是把 `run_all.py` 包装成后台任务
- `backend/app/services/market_service.py` 负责最新交易日增量更新和断点恢复
- `frontend/src/components/common/PageLayout.vue` 负责全局右上角进度卡、初始化状态提示和顶部告警

## 本地开发启动

### 一键开发模式

```bash
./start-dev.sh
```

会启动：

- 后端: `http://127.0.0.1:8000`
- 前端 dev server: `http://127.0.0.1:5173`

### 本地部署模式调试

```bash
./start.sh
```

这不是双服务模式。它会：

- 检查 Python / Node 运行环境
- 缺少系统级 Python / Node 时自动执行包管理器安装
- 按需安装或更新 `.venv` 和前端依赖
- 构建 `frontend/dist`
- 启动 FastAPI
- 由后端统一托管前端页面

默认访问：

- 应用首页: `http://127.0.0.1:8000`
- API 文档: `http://127.0.0.1:8000/docs`

## 常用命令

```bash
# 完整流程
python run_all.py

# 从第 2 步开始重跑
python run_all.py --start-from 2

# 只做量化初选
python -m pipeline.cli preselect

# 单股 quant 复核
python agent/quant_reviewer.py --code 600519 --date 2026-04-28

# 后端测试
pytest

# 前端构建
cd frontend
npm run build
```

## 排障定位

### 页面打不开或路由 404

- 本地部署模式要确认 `frontend/dist` 已构建
- 后端入口在 `backend/app/main.py`
- 页面路由是 `/update`，接口路径是 `/api/v1/tasks/*`

### 初始化任务异常

- 任务编排看 `backend/app/api/tasks.py` 和 `backend/app/services/task_service.py`
- 抓数断点看 `pipeline/fetch_kline.py`
- 增量更新断点看 `backend/app/services/market_service.py`
- 运行日志和 pid 文件在 `data/logs/`、`data/run/`

### 结果不符合预期

- 第 1 步抓数配置：`config/fetch_kline.yaml`
- 第 2 步初选配置：`config/rules_preselect.yaml`
- 第 4 步 quant 配置：`config/quant_review.yaml`

## 一个重要事实

当前仓库不是“全新 Web 项目驱动业务”，而是“既有量化主流程 + 本地 Web 编排层”。

所以：

- 改策略，优先看 `pipeline/` / `agent/`
- 改 API、任务、部署体验，优先看 `backend/` / `tools/localctl.py`
- 改交互、引导、进度展示，优先看 `frontend/`
