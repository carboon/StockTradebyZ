# StockTrader 2.0

面向 A 股的技术筛选与复核系统，核心输出包括：

- `明日之星`：按既定规则筛出候选股，并给出结构化复核结果
- `当前热盘`：跟踪当前交易日的活跃方向与强势股票
- `中盘分析`：基于 `09:30~11:30` 的盘中快照，输出大盘总览和个股对比
- `单股诊断`：对单只股票做独立检查，不依赖它是否进入候选池
- `重点观察`：面向持仓和跟踪管理，偏执行层

系统用于技术筛选、复核和过程管理，不构成投资建议。

## 当前形态

项目当前已经收敛为 `PostgreSQL + Docker` 运行模型。

- 运行时主链路只支持 PostgreSQL
- 普通用户查询优先读数据库和快照结果
- 大规模抓数、补数、重建都走离线脚本
- 生产环境不再支持 SQLite，也不再推荐宿主机直启服务

## 架构概览

运行链路：

`Browser -> nginx/nginx-dev -> FastAPI backend -> PostgreSQL`

模块分工：

- `frontend/`：Vue 3 + Vite 页面
- `backend/`：FastAPI API、任务编排、数据服务、缓存和持久化
- `pipeline/`：候选构建、回测、批量重建等离线流程
- `agent/`：量化复核、分析模板、研究辅助逻辑
- `deploy/`：Docker Compose、镜像、启动脚本、systemd
- `data/`：原始快照、缓存、导出、日志和运行期文件

更完整的架构说明见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 核心原理

### 1. 数据流

- 日线历史以 `Tushare` 为主，统一写入 `stock_daily`
- 盘中分时优先尝试 `Eastmoney`，失败时回退 `Tencent`，再回退 `Tushare rt_min`
- 原始日线按交易日落到 `data/raw_daily/*.jsonl`
- 原始分时落到 `data/raw_intraday/`
- 派生结果再写入数据库，供页面直接查询

### 2. 在线与离线边界

- 在线接口负责查询、拼装、展示，不在普通页面请求里做全市场重算
- 离线脚本负责抓数、补数、重建明日之星、当前热盘和盘中快照
- 页面尽量消费“已经算好的结果”，避免把重负载工作放到用户请求里

### 3. 结果生成逻辑

- `明日之星`：先做流动性范围约束，再做 B1 条件筛选，再进入量化复核
- `当前热盘`：围绕当前交易日活跃股票池生成候选和结果
- `中盘分析`：以当日上午行情为准，只使用 `09:30~11:30` 数据生成快照
- `重点观察`：把技术结论与用户持仓/计划结合，偏执行建议

### 4. 更新原则

- `daily`：更新指定交易日或最新交易日的日线，并重建当日结果
- `generate`：不重新抓日线，只基于现有数据库重建近窗口派生数据
- `intraday`：11:30 后生成中盘快照，默认截止 `11:30:00`
- 每日更新除了判断“日期是否最新”，也会检查关键指标完整性；若换手率/量比不完整，会继续补抓，不会误判为“已最新”

## 快速开始

初始化：

```bash
cp .env.example deploy/.env
```

本地开发启动：

```bash
./start.sh
```

停止服务：

```bash
./stop.sh
```

生产启动：

```bash
./deploy/scripts/start.sh prod --build
```

常用地址：

- 主入口：`http://127.0.0.1:8080`
- 前端直连：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`

## 常用操作

### 服务运维

```bash
./deploy/scripts/start.sh ps
./deploy/scripts/start.sh logs backend
./deploy/scripts/start.sh exec-backend
```

### 数据更新

统一入口：

```bash
./update-data.sh daily
./update-data.sh generate
./update-data.sh intraday
./update-data.sh repair daily
./update-data.sh repair scores
```

常见示例：

```bash
./update-data.sh daily --target-date 2026-05-14
./update-data.sh intraday --target-date 2026-05-14
./update-data.sh generate --window-size 120
./update-data.sh repair daily --min-days 250 --limit 200
./update-data.sh repair scores --scope both
```

含义：

- `daily`：抓取日线并重建当日明日之星、当前热盘
- `generate`：只重建派生结果，不重新抓日线
- `intraday`：生成明日之星/当前热盘中盘快照
- `repair daily`：修复 `stock_daily` 缺失或样本不足
- `repair scores`：修复历史候选、评分和结果不一致

如需保留宿主机后台定时更新，可参考：

- [deploy/systemd/stocktrade-background-update.service](deploy/systemd/stocktrade-background-update.service)
- [deploy/systemd/stocktrade-background-update.timer](deploy/systemd/stocktrade-background-update.timer)

## 配置说明

启动前至少确认 `deploy/.env` 中以下变量：

- `TUSHARE_TOKEN`
- `DATABASE_URL`
- `SECRET_KEY`
- `ADMIN_DEFAULT_USERNAME`
- `ADMIN_DEFAULT_PASSWORD`

生产环境还应检查：

- `ENVIRONMENT=production`
- `POSTGRES_PASSWORD`
- `BACKEND_CORS_ORIGINS`
- `NGINX_BASE_IMAGE`

如启用 AI 分析，再配置：

- `ZHIPUAI_API_KEY`
- `DASHSCOPE_API_KEY`
- `GEMINI_API_KEY`

说明：

- 容器内访问数据库应使用 `postgres:5432`
- 宿主机直接跑 Python 或 pytest 时，应改用 `127.0.0.1` 或 `localhost`
- 不要提交 `.env`、`deploy/.env`、`data/`、日志和真实密钥

## 仓库结构

- `frontend/src/`：页面、状态管理、接口类型
- `backend/app/`：API、模型、服务、配置
- `backend/scripts/`：抓数、补数、重建、导入脚本
- `backend/tests/`：后端测试
- `frontend/tests/`：前端测试
- `deploy/`：Compose、Dockerfile、启动/发布/systemd
- `docs/`：部署、修复工具、开发附加说明

## 文档导航

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [README.dev.md](README.dev.md)
- [docs/README.md](docs/README.md)
- [docs/repair-tools.md](docs/repair-tools.md)

## 测试

宿主机运行 Python 或 pytest 时，统一使用仓库根目录 `.venv`：

```bash
.venv/bin/python -m pytest
```

前端常用命令：

```bash
cd frontend
npm run dev
npm run build
npm run test
npm run lint
```

补充说明：

- 当前测试隔离仍允许使用内存 SQLite，但这不代表运行时支持 SQLite
- 当前推荐的数据维护入口只有仓库根目录 `./update-data.sh`
