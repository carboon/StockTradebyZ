# PostgreSQL 迁移指南

## 概述

本文档描述如何将 StockTrade 应用从 SQLite 迁移到 PostgreSQL。

## 迁移原因

| 特性 | SQLite | PostgreSQL |
|------|--------|------------|
| 并发写入 | 受限 | 优秀 |
| 连接数限制 | 单连接写入 | 无限制 |
| 数据量 | 适合中小规模 | 适合大规模 |
| 生产环境 | 不推荐 | 推荐 |

## 配置变更

### 1. 环境变量

在 `.env` 文件中添加：

```bash
# PostgreSQL 配置
POSTGRES_DB=stocktrade
POSTGRES_USER=stocktrade
POSTGRES_PASSWORD=your_secure_password
POSTGRES_PORT=5432

# 数据库 URL (backend 会自动使用)
DATABASE_URL=postgresql://stocktrade:your_secure_password@postgres:5432/stocktrade
```

### 2. Docker Compose

启动 PostgreSQL 服务：

```bash
# 带 PostgreSQL 启动
cd deploy
docker compose --profile postgres up -d

# 或使用环境变量
USE_POSTGRES=true docker compose up -d
```

## 数据迁移

### 方法 1: 迁移脚本

```bash
# 确保 PostgreSQL 容器运行
docker compose up -d postgres

# 运行迁移
python scripts/migrate_sqlite_to_postgres.py \\
    --sqlite ./data/db/stocktrade.db \\
    --postgres "postgresql://stocktrade:password@localhost:5432/stocktrade"
```

### 方法 2: Docker 内部迁移

```bash
# 进入后端容器
docker exec -it stocktrade-backend bash

# 运行迁移
python /app/scripts/migrate_sqlite_to_postgres.py
```

## 迁移后验证

### 1. 检查数据完整性

```bash
# 对比行数
# SQLite
docker exec stocktrade-backend python -c "
from sqlalchemy import create_engine, text
engine = create_engine('sqlite:///data/db/stocktrade.db')
with engine.begin() as conn:
    result = conn.execute(text('SELECT COUNT(*) FROM stock_daily'))
    print(f'SQLite: {result.scalar():,} 行')
"

# PostgreSQL
docker exec stocktrade-postgres psql -U stocktrade -d stocktrade -c "
SELECT COUNT(*) FROM stock_daily;"
```

### 2. 验证增量更新

增量更新逻辑已适配 PostgreSQL，无需修改：

```python
# daily_data_service.py 中的增量更新逻辑
# 会自动检测每只股票的最新日期，只获取新数据
```

### 3. 测试 API

```bash
# 测试健康检查
curl http://localhost:8000/api/health

# 测试 K线查询
curl -H "Authorization: Bearer YOUR_TOKEN" \\
     "http://localhost:8000/api/v1/stock/kline?code=000001&days=30"
```

## 常见问题

### Q: 迁移后能回退到 SQLite 吗？

A: 可以。只需移除 `DATABASE_URL` 环境变量，系统会自动使用 SQLite。

### Q: PostgreSQL 数据会丢失吗？

A: 不会。PostgreSQL 数据存储在 Docker volume `postgres_data` 中，持久化保存。

### Q: 增量更新是否需要修改？

A: 不需要。`daily_data_service.py` 的增量更新逻辑已经过测试，兼容 PostgreSQL。

## 性能对比

| 操作 | SQLite | PostgreSQL |
|------|--------|------------|
| 单条查询 | ~1ms | ~2ms |
| 批量插入 (1000条) | ~200ms | ~150ms |
| 并发查询 (10) | 队列等待 | 并行执行 |
| 全量更新 | 受锁限制 | 无限制 |

## 生产建议

1. **使用 PostgreSQL**：生产环境推荐使用 PostgreSQL
2. **配置备份**：定期备份 PostgreSQL 数据
3. **监控连接池**：观察 `pool_size` 和 `max_overflow` 使用情况
4. **索引优化**：根据查询模式添加适当索引
