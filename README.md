# StockTrader 2.0

面向 A 股的技术筛选、盘面复核和观察管理系统。系统以规则和量化复核为主，围绕“先准备数据、再生成候选、再做复核、最后进入观察/执行管理”的工作流运转。

本系统用于技术筛选、复核和过程管理，不构成投资建议。

## 最新功能

### 全盘分析

全盘分析页面聚合两条主线：

- `明日之星`：按流动性池、B1 条件、前置过滤和量化复核生成候选与分析结果
- `当前热盘`：围绕当前交易日活跃股票池输出强势标的、热度结果和板块强弱

页面支持按交易日查看候选、结果、历史记录、信号收益表现，并可查看 `09:30~11:30` 口径的中盘快照。

### 板块分析

板块分析基于当前热盘与行业/概念聚合结果，展示板块强弱、轮动方向、板块内个股明细和阶段对比，用于判断个股机会是否有板块共振。

### 单股诊断

单股诊断对单只股票做独立检查，不要求它已经进入候选池。诊断会读取日线、周线、B1 细项、量化评分、历史检查结果和中盘信息。若本地历史样本明显不足，服务侧会尝试按股补齐基础日线后再继续分析。

### 重点观察

重点观察用于跟踪自选或持仓股票，支持记录观察理由、优先级、成本、仓位和进场日期，并查看观察项分析、图表和执行层建议。

### 任务中心与运维管理

任务中心提供数据初始化、每日更新、近 120 交易日重建、数据完整性检查、任务日志、任务取消/恢复、运行环境诊断和管理员摘要。更新期间，读页面会进入“更新数据中”状态，避免读取半更新结果。

### 用户、配置与接口

系统包含登录、注册验证、个人资料、管理员用户管理、用量统计、API Key 管理和配置管理。数据源、默认 reviewer、AI Key、CORS 等配置可通过 `deploy/.env` 和配置页面管理。

## 当前架构

项目已经收敛为 `PostgreSQL + Redis + Docker` 运行模型。

生产/统一入口链路：

```text
Browser -> Nginx -> FastAPI backend -> PostgreSQL
                         |
                         +-> Redis cache
                         |
                         +-> data/ snapshots, logs, exports
```

开发链路：

```text
Browser -> Vite frontend-dev -> FastAPI backend -> PostgreSQL
                                      |
                                      +-> Redis cache
```

核心边界：

- PostgreSQL 是正式主库，运行时不再支持 SQLite
- Redis 用于读缓存、诊断历史缓存和活跃池等加速；不可用时服务会降级到内存缓存
- `data/` 只存放原始快照、分时数据、缓存、导出和日志
- 在线 API 负责查询、拼装和任务编排，不在普通页面请求里做全市场重算
- 大规模抓数、补数、重建和修复由离线脚本或任务中心执行

模块分工：

- `frontend/`：Vue 3 + Vite 前端页面、状态和接口类型
- `backend/`：FastAPI API、认证、任务编排、数据服务、缓存和持久化
- `pipeline/`：行情抓取、候选构建、回测和离线流程
- `agent/`：量化复核、AI reviewer、单股诊断和持仓报告辅助逻辑
- `deploy/`：Docker Compose、Dockerfile、启动/发布/备份脚本和 systemd service
- `config/`：策略、reviewer、图表和分析配置
- `data/`：运行期数据，不应提交到 Git

更完整的架构说明见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 数据与结果生成

数据来源：

- 日线历史以 Tushare 为主，统一写入 `stock_daily`
- 日线原始分片落在 `data/raw_daily/*.jsonl`
- 盘中分时优先尝试 Eastmoney，失败后回退 Tencent，再回退 Tushare `rt_min`
- 分时原始数据落在 `data/raw_intraday/`
- 候选、评分、板块分析和中盘快照写入数据库或运行期快照，供页面查询

生成逻辑：

- `明日之星`：流动性范围约束 -> B1 条件筛选 -> 前置过滤 -> 量化/AI 复核 -> PASS/WATCH/FAIL
- `当前热盘`：围绕活跃股票池生成候选、强弱评分、板块聚合和结果
- `板块分析`：基于近期窗口聚合板块强弱、轮动和成分股表现
- `中盘分析`：以 `09:30~11:30` 上午行情为准生成大盘与个股快照
- `重点观察`：把技术结论与用户记录的观察/持仓信息结合，偏执行层管理

## 快速开始

初始化配置：

```bash
cp .env.example deploy/.env
```

至少编辑并确认：

- `TUSHARE_TOKEN`
- `SECRET_KEY`
- `ADMIN_DEFAULT_USERNAME`
- `ADMIN_DEFAULT_PASSWORD`
- `POSTGRES_PASSWORD`

本地统一入口启动：

```bash
./start.sh
```

说明：

- 根目录 `./start.sh` 是快捷入口，实际调用 `./deploy/scripts/start.sh prod --build`
- 它会启动 `postgres`、`redis`、`backend`、`nginx`
- 主入口端口由 `deploy/.env` 的 `NGINX_PORT` 决定；未设置时使用 Compose 默认的 `127.0.0.1:80`
- 如需本机常用 `8080`，可在 `deploy/.env` 设置 `NGINX_PORT=127.0.0.1:8080`

停止服务：

```bash
./stop.sh
```

开发 HMR 模式：

```bash
./deploy/scripts/start.sh dev --build
```

开发模式启动 `postgres`、`redis`、`backend`、`frontend-dev`，常用地址：

- 前端直连：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`

生产启动：

```bash
./deploy/scripts/start.sh prod --build
```

生产发布：

```bash
./deploy/scripts/release.sh
```

常用运维命令：

```bash
./deploy/scripts/start.sh ps
./deploy/scripts/start.sh logs backend
./deploy/scripts/start.sh restart backend
./deploy/scripts/start.sh exec-backend
```

## 数据更新

统一入口：

```bash
./update-data.sh daily
./update-data.sh generate
./update-data.sh intraday
./update-data.sh repair daily
./update-data.sh repair scores
```

命令含义：

- `daily`：抓取最新交易日或指定交易日的日线，并重建当日明日之星、当前热盘和相关派生结果
- `generate`：检查近 120 交易日窗口的数据缺口，补齐缺失日线和缺失市场指标后重建结果；如只想重建可追加 `--skip-data-fetch`
- `intraday`：生成明日之星/当前热盘中盘快照，默认截止 `11:30:00`
- `repair daily`：修复 `stock_daily` 历史缺失或样本不足
- `repair scores`：修复明日之星/当前热盘历史评分、候选和运行记录不一致

常见示例：

```bash
./update-data.sh daily --target-date 2026-05-14
./update-data.sh generate --window-size 120
./update-data.sh generate --skip-data-fetch
./update-data.sh intraday --target-date 2026-05-14
./update-data.sh repair daily --min-days 250 --limit 200
./update-data.sh repair scores --scope both
```

任务中心也支持应用内每日自动更新：

- 配置入口：`任务中心 -> 总览 -> 自动更新配置`
- 默认交易日北京时间 `16:30` 触发
- 若 Tushare 当日数据未就绪，会间隔 `10` 分钟重试
- 更新完成后会预热全盘分析、当前热盘和板块分析读路径
- 日志写入 `data/logs/auto-update/auto-update.log`

## 部署与备份

生产环境必须确认：

- `ENVIRONMENT=production`
- `DATABASE_URL` 不使用示例默认连接串
- `BACKEND_WORKERS` 与数据库连接池容量匹配
- `DB_POOL_SIZE`、`DB_MAX_OVERFLOW`、`DB_POOL_TIMEOUT`、`DB_POOL_RECYCLE` 符合 PostgreSQL 连接预算
- `SECRET_KEY` 不使用示例占位值
- `ADMIN_DEFAULT_PASSWORD` 不使用示例口令
- `BACKEND_CORS_ORIGINS` 替换为真实域名
- 对外端口、反向代理和防火墙符合实际部署需求

后端默认使用 Uvicorn 单 worker。Mac mini M4 可先在 `deploy/.env` 设置 `BACKEND_WORKERS=2`，配合 `DB_POOL_SIZE=8`、`DB_MAX_OVERFLOW=8` 做 60 秒压测；连接上限约为 `BACKEND_WORKERS * (DB_POOL_SIZE + DB_MAX_OVERFLOW)`。若 CPU 和 PostgreSQL 连接数都稳定，再尝试 `BACKEND_WORKERS=3`。详细步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)。
多 worker 部署下，应用内每日自动更新调度器会通过运行期锁保持单例，避免多个 worker 重复触发自动更新。

如 Docker Hub 拉取基础镜像较慢，可在 `deploy/.env` 覆盖：

```bash
NODE_BASE_IMAGE=docker.m.daocloud.io/library/node:20-bookworm-slim
NGINX_BASE_IMAGE=docker.m.daocloud.io/library/nginx:1.27-alpine
```

宿主机重启后自动拉起生产服务：

```bash
sudo cp deploy/systemd/stocktrade-prod.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stocktrade-prod.service
sudo systemctl status stocktrade-prod.service
```

备份数据库和 `data/`：

```bash
./deploy/scripts/backup.sh
```

详细部署说明见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 本地开发与测试

后端测试：

```bash
.venv/bin/python -m pytest
```

前端命令：

```bash
cd frontend
npm run dev
npm run build
npm run test
npm run test:coverage
npm run lint
```

说明：

- 宿主机直接跑 Python 或 pytest 时，数据库地址应使用 `127.0.0.1` 或 `localhost`
- 容器内访问 PostgreSQL 使用 `postgres:5432`
- 测试隔离仍允许使用内存 SQLite，但这不代表运行时支持 SQLite

## 文档导航

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [README.dev.md](README.dev.md)
- [docs/README.md](docs/README.md)
- [docs/repair-tools.md](docs/repair-tools.md)
- [docs/directory-structure.md](docs/directory-structure.md)

## 安全提示

不要提交以下内容：

- `.env`
- `deploy/.env`
- `data/`
- 日志、缓存、导出文件
- 真实 API Key、数据库密码、JWT 密钥
