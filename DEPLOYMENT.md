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

## 后台交易日更新

仓库已提供独立后台更新脚本：

```bash
./deploy/scripts/start.sh update-latest
```

如需用 systemd 以受限资源方式在宿主机后台执行，可使用：

```bash
deploy/systemd/stocktrade-background-update.service
deploy/systemd/stocktrade-background-update.timer
```

该 service 已内置以下限制：

- `CPUQuota=100%`
- `MemoryMax=1500M`
- `Nice=10`
- `IOSchedulingClass=idle`

当前仓库中的 service 已按这台宿主机预设为：

- `WorkingDirectory=/root/StockTradebyZ`
- `User=root`
- `Group=root`
- `Restart=on-failure`
- `RestartPreventExitStatus=1`
- `RestartSec=10min`
- Docker 服务已启动，且 `backend` 容器处于运行状态

当前 timer 规则为：

- `OnCalendar=Mon..Fri *-*-* 16:30:00 Asia/Shanghai`
- `Persistent=true`

当前行为约定为：

- 由 systemd 在交易日北京时间 `16:30` 触发首次更新
- 若当天交易数据在 Tushare 仍未就绪，脚本会以 `TEMPFAIL(75)` 退出，service 每 `10` 分钟自动重试一次
- 一旦更新成功，自动重试终止
- 普通脚本错误不会进入自动重试循环，需要人工处理

启用方式示例：

```bash
sudo mkdir -p /root/StockTradebyZ/data/logs /root/StockTradebyZ/.docker
sudo cp deploy/systemd/stocktrade-background-update.service /etc/systemd/system/
sudo cp deploy/systemd/stocktrade-background-update.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stocktrade-background-update.timer
sudo systemctl start stocktrade-background-update.service
sudo systemctl status stocktrade-background-update.timer
```

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
