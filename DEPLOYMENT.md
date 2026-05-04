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

标准发布：

```bash
./deploy/scripts/release.sh
```

访问地址：

- 主入口：`http://127.0.0.1`
- 后端 API：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/docs`

## 宿主机与容器的数据库地址差异

- 容器内访问 PostgreSQL：`postgres:5432`
- 宿主机访问 PostgreSQL：通常使用 `127.0.0.1:${POSTGRES_PORT:-5432}`

如果你在宿主机直接运行 Python、脚本或 pytest，不要继续使用 `@postgres:5432` 作为数据库地址。

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
