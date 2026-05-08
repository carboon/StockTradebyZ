# StockTrader 2.0

当前仓库的运行方案已经收敛为 `PostgreSQL + Docker`。生产路径不再支持 SQLite，也不再提供本机直启服务脚本。

## 快速开始

本地开发：

```bash
cp .env.example deploy/.env
./start.sh
```

停止服务：

```bash
./stop.sh
```

生产启动：

```bash
cp .env.example deploy/.env
./deploy/scripts/start.sh prod --build
```

如需宿主机重启后自动拉起生产服务，可启用：

```bash
deploy/systemd/stocktrade-prod.service
```

后台交易日更新：

```bash
./deploy/scripts/start.sh update-latest
```

如需宿主机后台限流运行，可使用：

```bash
deploy/systemd/stocktrade-background-update.service
deploy/systemd/stocktrade-background-update.timer
```

当前仓库内的 service 已按这台服务器预设为 `/root/StockTradebyZ`、`root:root`，并把后台任务限制为最多 `1 vCPU + 1500M` 内存。systemd 默认会在交易日北京时间 `16:30` 首次触发；若当天交易数据尚未就绪，则脚本返回 `TEMPFAIL(75)`，service 会每 `10` 分钟自动重试，直到成功；普通脚本错误返回 `1`，不会自动重试。

访问地址：

- 开发主入口：`http://127.0.0.1:8080`
- 前端直连：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

## 必填配置

启动前至少确认 `deploy/.env` 中以下变量：

- `TUSHARE_TOKEN`
- `DATABASE_URL`
- `SECRET_KEY`
- `ADMIN_DEFAULT_USERNAME`
- `ADMIN_DEFAULT_PASSWORD`

生产环境还应同时检查：

- `ENVIRONMENT=production`
- `BACKEND_CORS_ORIGINS` 改为实际域名
- `POSTGRES_PASSWORD` 不使用示例默认值
- 如启用 AI 分析，再配置 `ZHIPUAI_API_KEY` / `DASHSCOPE_API_KEY` / `GEMINI_API_KEY`

## 安全说明

- `.env`、`deploy/.env`、`data/`、本地数据库文件、日志文件都不应提交到 Git
- `.env.example` 里的口令仅用于示例，占位值必须在生产环境替换
- 不要把真实 API Key、JWT 密钥、管理员口令直接写入文档、脚本或已跟踪配置文件

## 仓库结构

- `frontend/`：Vue 页面层
- `backend/`：FastAPI、任务编排、数据接口
- `pipeline/` / `agent/`：离线量化流程与复核逻辑
- `deploy/`：Docker Compose、Dockerfile、运行脚本
- `data/`：快照、缓存、导出和运行期文件

## 文档

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [README.dev.md](README.dev.md) - 本地开发、容器调试、移动端联调入口
- [docs/README.md](docs/README.md)

## 测试说明

宿主机直接运行 Python 或 pytest 时，请使用仓库根目录 `.venv`：

```bash
.venv/bin/python -m pytest
```

补充说明：

- `postgres` 是 Docker Compose 服务名，只在 Compose 网络内有效
- 容器内运行后端或测试时，`DATABASE_URL=...@postgres:5432/...` 是正确的
- 宿主机直接运行测试且未通过 Docker 网络访问数据库时，应改用 `127.0.0.1` 或 `localhost`
- 当前推荐通过 `./deploy/scripts/start.sh update-latest` 在 `backend` 容器内执行后台更新，避免宿主机单独处理数据库地址
- 当前测试基座仍使用内存 SQLite 做隔离，这不属于生产部署能力
