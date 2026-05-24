# StockTrader Docker 部署说明

## 当前运行方案

项目只保留 `PostgreSQL + Redis + Docker` 运行方案。

统一入口/生产组件：

- `postgres`
- `redis`
- `backend`
- `nginx`

开发 HMR 组件：

- `postgres`
- `redis`
- `backend`
- `frontend-dev`

主 Compose 文件：

```bash
deploy/docker-compose.yml
```

## 配置文件

容器运行依赖：

```bash
deploy/.env
```

初始化：

```bash
cp .env.example deploy/.env
```

至少需要检查：

- `TUSHARE_TOKEN`
- `SECRET_KEY`
- `ADMIN_DEFAULT_USERNAME`
- `ADMIN_DEFAULT_PASSWORD`
- `POSTGRES_PASSWORD`

推荐同时确认：

- `DATABASE_URL`
- `BACKEND_CORS_ORIGINS`
- `BACKEND_WORKERS`
- `DB_POOL_SIZE`
- `DB_MAX_OVERFLOW`
- `DB_POOL_TIMEOUT`
- `DB_POOL_RECYCLE`
- `REDIS_PASSWORD`
- `NGINX_PORT`
- `NGINX_BASE_IMAGE`

生产环境必须额外确认：

- `ENVIRONMENT=production`
- `DATABASE_URL` 不再使用示例默认连接串
- `SECRET_KEY` 不再使用示例占位值
- `ADMIN_DEFAULT_PASSWORD` 不再使用示例口令
- `BACKEND_CORS_ORIGINS` 已替换为真实域名

可选 AI Key：

- `ZHIPUAI_API_KEY`
- `DASHSCOPE_API_KEY`
- `GEMINI_API_KEY`
- `DEEPSEEK_API_KEY`

## 本地统一入口

根目录快捷启动：

```bash
./start.sh
```

该脚本实际调用：

```bash
./deploy/scripts/start.sh prod --build
```

它会构建并启动 `postgres`、`redis`、`backend`、`nginx`，适合日常本机使用和接近生产形态的验证。

访问地址：

- 主入口：由 `deploy/.env` 的 `NGINX_PORT` 决定；未设置时 Compose 默认绑定 `127.0.0.1:80`
- 后端 API：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

如希望主入口使用 `8080`：

```bash
NGINX_PORT=127.0.0.1:8080
```

停止服务：

```bash
./stop.sh
```

谨慎删除 volume：

```bash
./stop.sh --volumes
```

## 开发 HMR 模式

开发模式启动：

```bash
./deploy/scripts/start.sh dev --build
```

开发模式启动 `frontend-dev`，不会启动生产 `nginx`。常用地址：

- 前端直连：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

常用命令：

```bash
./deploy/scripts/start.sh ps
./deploy/scripts/start.sh logs backend
./deploy/scripts/start.sh logs frontend-dev
./deploy/scripts/start.sh restart backend
./deploy/scripts/start.sh exec-backend
```

## 生产启动

直接启动：

```bash
./deploy/scripts/start.sh prod --build
```

## 后端并发与数据库连接池

后端镜像使用 `uvicorn backend.app.main:app` 启动，不额外引入 Gunicorn。可通过 `deploy/.env` 调整：

```bash
BACKEND_WORKERS=1
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
```

连接上限估算：

```text
最大后端连接数 ~= BACKEND_WORKERS * (DB_POOL_SIZE + DB_MAX_OVERFLOW)
```

默认值偏保守，兼容单 worker 部署。Mac mini M4 推荐从 `BACKEND_WORKERS=2` 开始；如果 CPU 仍有余量且 PostgreSQL 连接数稳定，再试 `3`。例如：

```bash
BACKEND_WORKERS=2
DB_POOL_SIZE=8
DB_MAX_OVERFLOW=8
```

应用内每日自动更新调度器会通过 `data/locks/auto_update_scheduler.lock` 做进程间单例保护；即使 `BACKEND_WORKERS>1`，也只会有一个 worker 启动调度器。

压测建议：

```bash
./deploy/scripts/start.sh prod --build
curl http://127.0.0.1:8000/health
.venv/bin/python scripts/perf/http_api_load_test.py --scenario page-switch --concurrency 8 --duration 60
docker exec -it stocktrade-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from pg_stat_activity;"
```

每次只调整一个变量，观察后端日志、响应延迟和 PostgreSQL 活跃连接数；如果出现连接等待或超时，优先降低 `BACKEND_WORKERS`、`DB_POOL_SIZE` 或 `DB_MAX_OVERFLOW`。

如果宿主机访问 Docker Hub 较慢，导致 `nginx:1.27-alpine` 拉取超时，可在 `deploy/.env` 中覆盖基础镜像：

```bash
NGINX_BASE_IMAGE=docker.m.daocloud.io/library/nginx:1.27-alpine
```

也可以改为自己的私有仓库完整镜像名。

标准发布：

```bash
./deploy/scripts/release.sh
```

发布脚本会执行生产环境检查、可选 `git pull`、顺序构建 `backend` 和 `nginx` 镜像、启动服务并做健康检查。

如果宿主机重启后需要自动拉起同一套生产服务：

```bash
sudo cp deploy/systemd/stocktrade-prod.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stocktrade-prod.service
sudo systemctl status stocktrade-prod.service
```

该 service 会执行与手工生产启动一致的 Compose profile。

## 服务运维

查看服务：

```bash
./deploy/scripts/start.sh ps
```

查看日志：

```bash
./deploy/scripts/start.sh logs
./deploy/scripts/start.sh logs backend
```

重启：

```bash
./deploy/scripts/start.sh restart
./deploy/scripts/start.sh restart backend
```

进入后端容器：

```bash
./deploy/scripts/start.sh exec-backend
```

说明：

- `dev` 模式默认会构建 `backend` 和 `frontend-dev`
- `prod` 模式只有显式传入 `--build` 才构建镜像
- `--no-cache` 可用于强制无缓存构建

## 数据脚本入口

仓库主入口统一为：

```bash
./update-data.sh daily
./update-data.sh generate
./update-data.sh intraday
./update-data.sh repair daily
./update-data.sh repair scores
```

说明：

- `daily`：更新最新交易日或指定交易日的日线，并重建当日明日之星、当前热盘和相关派生结果
- `generate`：检查近 120 日窗口缺口，补齐缺失日线和缺失市场指标后重建明日之星、当前热盘和板块分析；只重建可追加 `--skip-data-fetch`
- `intraday`：11:30 后生成中盘快照，默认只取 `09:30~11:30`
- `repair daily`：修复 `stock_daily` 历史缺失或样本不足
- `repair scores`：修复明日之星/当前热盘历史评分、候选和运行记录不一致

示例：

```bash
./update-data.sh daily --target-date 2026-05-14
./update-data.sh generate --window-size 120
./update-data.sh generate --skip-data-fetch
./update-data.sh intraday --target-date 2026-05-14
./update-data.sh repair daily --min-days 250 --limit 200
./update-data.sh repair scores --scope both
```

`update-data.sh` 会优先复用正在运行的 `stocktrade-backend` 容器；如果后端容器未运行，则通过 Compose 启动一次性 backend 容器执行脚本。

## 任务中心自动更新

每日数据自动更新由后端应用内调度完成，不再依赖宿主机 `systemd timer`。

配置入口：

- `任务中心 -> 总览 -> 自动更新配置`

当前行为：

- 支持开关控制是否启用每日自动更新
- 支持配置触发时间，默认交易日北京时间 `16:30`
- 到点后会确认远端 Tushare 当日数据是否已具备
- 若数据未就绪，会延迟 `10` 分钟后再次确认
- 更新进行中时，关键业务页会显示“更新数据中”
- 更新完成后会预热 `全盘分析`、`当前热盘`、`板块分析` 等读路径
- 调度和异常写入 `data/logs/auto-update/auto-update.log`

## 宿主机与容器地址

容器内：

- PostgreSQL：`postgres:5432`
- Redis：`redis:6379`
- Backend：`backend:8000`

宿主机：

- PostgreSQL：通常使用 `127.0.0.1:${POSTGRES_PORT:-5432}`
- Redis：通常使用 `127.0.0.1:${REDIS_PORT:-6379}`
- Backend：`http://127.0.0.1:8000`

当前推荐的后台更新方式是通过 `backend` 容器执行，因此不需要单独修改后台更新任务的数据库地址。只有在宿主机直接运行 Python、脚本或 pytest 时，才不要继续使用 `@postgres:5432` 作为数据库地址。

## 数据与备份

- PostgreSQL 数据存储在 Docker volume `postgres_data`
- Redis 数据存储在 Docker volume `redis_data`
- 业务文件数据在宿主机 `data/`

备份脚本：

```bash
./deploy/scripts/backup.sh
```

可选参数：

```bash
./deploy/scripts/backup.sh --no-db
./deploy/scripts/backup.sh --no-data
./deploy/scripts/backup.sh --keep-days 30
./deploy/scripts/backup.sh --dir /mnt/backup
```

## 安全检查清单

- `deploy/.env` 未纳入 Git 跟踪
- 未把真实 API Key、数据库密码、JWT 密钥写入文档或示例文件
- 生产环境未使用 `change-me-in-production`、`admin123`、`stocktrade123` 这类示例值
- 对外暴露端口、CORS 域名和反向代理域名符合实际部署需求
- 备份目录权限和保留周期符合数据安全要求
