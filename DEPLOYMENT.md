# StockTrader Docker 部署说明

## 当前运行方案

项目只保留 PostgreSQL + Docker。

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

## 开发环境

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

## 生产环境

启动：

```bash
./deploy/scripts/start.sh prod --build
```

发布：

```bash
./deploy/scripts/release.sh
```

## 数据与备份

- PostgreSQL 数据在 Docker volume `postgres_data`
- 业务文件数据在宿主机 `data/`

备份脚本：

```bash
./deploy/scripts/backup.sh
```
