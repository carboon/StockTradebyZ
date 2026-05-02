# PostgreSQL 快速开始

## 一键启动（使用 PostgreSQL）

```bash
cd deploy
docker compose --profile postgres up -d
```

## 环境变量配置

创建或编辑 `.env` 文件：

```bash
# PostgreSQL 配置
POSTGRES_DB=stocktrade
POSTGRES_USER=stocktrade
POSTGRES_PASSWORD=changeme123
POSTGRES_PORT=5432

# 数据库 URL (自动生成)
DATABASE_URL=postgresql://stocktrade:changeme123@postgres:5432/stocktrade
```

## 数据迁移

从 SQLite 迁移已有数据到 PostgreSQL：

```bash
# 方式 1: 在容器内运行
docker exec -it stocktrade-backend python /app/scripts/migrate_sqlite_to_postgres.py

# 方式 2: 本地运行
python scripts/migrate_sqlite_to_postgres.py \\
    --postgres "postgresql://stocktrade:changeme123@localhost:5432/stocktrade"
```

## 验证

```bash
# 检查 PostgreSQL 数据
docker exec stocktrade-postgres psql -U stocktrade -d stocktrade -c "
  SELECT COUNT(*) FROM stock_daily;
  SELECT COUNT(*) FROM stocks;
"

# 测试 API
curl http://localhost:8000/api/health
```

## 增量更新

增量更新逻辑已适配 PostgreSQL，无需修改代码：

```bash
# 通过 API 触发增量更新
curl -X POST http://localhost:8000/api/v1/tasks/incremental \\
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 回退到 SQLite

只需移除 `DATABASE_URL` 环境变量：

```bash
# 编辑 .env，注释掉 DATABASE_URL
# DATABASE_URL=postgresql://...

docker compose up -d
```
