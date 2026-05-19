# StockTrader Docker 部署说明

## 当前运行方案

项目只保留 `PostgreSQL + Docker`。

开发环境组件：

- `postgres`
- `backend`
- `frontend-dev`
- `nginx-dev`

生产环境组件：

- `postgres`
- `backend`
- `nginx`

主 Compose 文件：

```bash
deploy/docker-compose.yml
```

## 配置文件

容器运行依赖：

```bash
deploy/.env
```

初始化方式：

```bash
cp .env.example deploy/.env
```

至少需要检查以下变量：

- `TUSHARE_TOKEN`
- `DATABASE_URL`
- `SECRET_KEY`
- `ADMIN_DEFAULT_USERNAME`
- `ADMIN_DEFAULT_PASSWORD`
- `POSTGRES_PASSWORD`

生产环境必须额外确认：

- `ENVIRONMENT=production`
- `BACKEND_CORS_ORIGINS` 已替换为实际域名
- `DATABASE_URL` 不再使用示例默认连接串
- `SECRET_KEY` 不再使用示例占位值
- `ADMIN_DEFAULT_PASSWORD` 不再使用示例口令

可选变量：

- `ZHIPUAI_API_KEY`
- `DASHSCOPE_API_KEY`
- `GEMINI_API_KEY`
- `NGINX_BASE_IMAGE`
- `POSTGRES_PORT`
- `BACKEND_PORT`
- `FRONTEND_PORT`
- `NGINX_PORT`

## 本地开发部署

启动：

```bash
./start.sh
```

常用命令：

```bash
./stop.sh
./deploy/scripts/start.sh ps
./deploy/scripts/start.sh logs
./deploy/scripts/start.sh logs backend
./deploy/scripts/start.sh exec-backend
```

访问地址：

- 主入口：`http://127.0.0.1:8080`
- 前端直连：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

## 生产部署

直接启动：

```bash
./deploy/scripts/start.sh prod --build
```

如果宿主机访问 Docker Hub 较慢，导致 `nginx:1.27-alpine` 拉取超时，可在 `deploy/.env` 中覆盖基础镜像：

```bash
NGINX_BASE_IMAGE=docker.m.daocloud.io/library/nginx:1.27-alpine
```

也可以改为你自己的私有仓库完整镜像名。

如需宿主机重启后自动拉起同一套生产服务：

```bash
sudo cp deploy/systemd/stocktrade-prod.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stocktrade-prod.service
sudo systemctl status stocktrade-prod.service
```

该 service 会执行与你当前手工启动一致的命令：

```bash
docker compose -f deploy/docker-compose.yml --profile postgres --profile prod up -d --build postgres redis backend nginx
```

标准发布：

```bash
./deploy/scripts/release.sh
```

访问地址：

- 主入口：`http://127.0.0.1`
- 后端 API：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

## 数据脚本入口

仓库主入口已统一为：

```bash
./update-data.sh daily
./update-data.sh generate
./update-data.sh intraday
./update-data.sh repair daily
./update-data.sh repair scores
```

说明：

- `daily`：更新最新交易日或指定交易日的日线，并重建当日结果
- `generate`：不拉新日线，只基于现有数据重建近 120 交易日窗口结果
- `intraday`：11:30 后生成中盘快照，默认只取 `09:30~11:30`
- `repair`：专项修复历史日线或历史评分结果

## 任务中心自动更新

当前每日数据自动更新由应用内调度完成，不再依赖宿主机 `systemd timer`。

配置入口：

- 任务中心 -> 总览 -> 自动更新配置

当前行为：

- 支持开关控制是否启用每日自动更新
- 支持配置触发时间，默认交易日北京时间 `16:30`
- 到点后会先确认远端 Tushare 当日数据是否已具备
- 若数据未就绪，会延迟 `10` 分钟后再次确认
- 更新完成后会自动预热 `当前热盘`、`全盘分析`、`板块分析` 的读路径
- 若更新进行中，业务页会返回“更新数据中”提示页，避免读取半更新数据
- 调度和异常会写入 `data/logs/auto-update/auto-update.log`

## 宿主机与容器的数据库地址差异

- 容器内访问 PostgreSQL：`postgres:5432`
- 宿主机访问 PostgreSQL：通常使用 `127.0.0.1:${POSTGRES_PORT:-5432}`

当前推荐的后台更新方式是通过 `backend` 容器执行，因此不需要单独修改后台更新任务的数据库地址。
只有在宿主机直接运行 Python、脚本或 pytest 时，才不要继续使用 `@postgres:5432` 作为数据库地址。

## 数据与备份

- PostgreSQL 数据存储在 Docker volume `postgres_data`
- 业务文件数据在宿主机 `data/`

备份脚本：

```bash
./deploy/scripts/backup.sh
```

## 安全检查清单

- `deploy/.env` 未纳入 Git 跟踪
- 未把真实 API Key、数据库密码、JWT 密钥写入文档或示例文件
- 生产环境未使用 `change-me-in-production`、`admin123`、`stocktrade123` 这类示例值
- 对外暴露端口和 CORS 域名符合实际部署需求
