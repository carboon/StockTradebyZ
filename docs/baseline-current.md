# 系统基线配置文档

> 创建时间: 2025-05-01
> 目的: 记录 StockTradebyZ 系统当前配置基线，为100用户并发优化提供参考

---

## 1. 部署架构

### 1.1 容器化部署

- **后端容器**: `stocktrade-backend`
- **前端代理**: `stocktrade-nginx`
- **网络**: `stocktrade-net` (bridge driver)
- **重启策略**: `always` (生产环境)

### 1.2 端口映射

| 服务 | 容器内端口 | 外部端口 | 说明 |
|------|-----------|---------|------|
| backend | 8000 | - | 仅内部访问，通过nginx代理 |
| nginx | 80 | 127.0.0.1:80 | 生产环境仅监听本地 |

---

## 2. 后端服务配置

### 2.1 Uvicorn 启动参数

**当前配置** (`Dockerfile` line 47):
```dockerfile
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

- **Workers 数量**: `1` (单进程)
- **Host**: `0.0.0.0`
- **Port**: `8000`
- **应用入口**: `backend.app.main:app`

> **关键发现**: 单 worker 配置是100并发的主要瓶颈之一。SQLite + 单进程无法有效利用多核CPU。

### 2.2 应用配置 (`backend/app/config.py`)

| 配置项 | 当前值 | 说明 |
|--------|--------|------|
| `app_name` | StockTrader | 应用名称 |
| `debug` | True | 调试模式 |
| `host` | 0.0.0.0 | 监听地址 |
| `port` | 8000 | 监听端口 |
| `environment` | development | 运行环境 |
| `database_url` | `sqlite:///data/db/stocktrade.db` | 数据库连接 |
| `access_token_expire_minutes` | 1440 | Token有效期(24小时) |

### 2.3 CORS 配置

- **开发环境**: 自动补充 `localhost:3000`, `localhost:5173` 等
- **生产环境**: 仅允许配置的域名

---

## 3. 数据库配置

### 3.1 SQLite 配置 (`backend/app/database.py`)

**连接参数**:
```python
sqlite_connect_args = {
    "check_same_thread": False,
    "timeout": 30,  # 30秒锁超时
}
```

**优化设置** (WAL模式):
```python
PRAGMA journal_mode=WAL
PRAGMA synchronous=NORMAL
PRAGMA busy_timeout=30000  # 30秒
```

**连接池**: `StaticPool` (SQLite 使用静态连接池)

### 3.2 数据库位置

- **路径**: `/app/data/db/stocktrade.db`
- **当前大小**: 约 1.2 MB (主文件)
- **WAL 文件**: 约 2 MB (stocktrade.db-wal)
- **共享内存**: 32 KB (stocktrade.db-shm)

### 3.3 数据目录结构

```
data/
├── candidates/      # 候选股票数据 (40KB)
├── db/              # 数据库文件 (4.1MB)
│   ├── stocktrade.db
│   ├── stocktrade.db-wal
│   └── stocktrade.db-shm
├── kline/           # K线图数据 (0B - 未使用)
├── logs/            # 日志文件 (5.0MB)
├── raw/             # 原始数据 (338MB)
├── review/          # 复核数据 (392KB)
├── run/             # 运行时文件 (16KB)
└── tushare_cache/   # Tushare缓存 (23MB)
```

---

## 4. 中间件配置

### 4.1 用量追踪中间件 (`UsageTrackingMiddleware`)

- **记录表**: `usage_logs`
- **跳过路径**: `/health`, `/docs`, `/redoc`, `/openapi.json`, `/static`, `/data`
- **记录内容**: user_id, api_key_id, endpoint, method, ip_address, status_code
- **写入模式**: fire-and-forget (不阻塞请求)

> **潜在风险**: 每次API请求都写数据库，100并发下会产生大量写入

### 4.2 限流中间件 (`RateLimitMiddleware`)

| 角色 | 限制 | 窗口 |
|------|------|------|
| 匿名用户 | 60 次 | 60 秒 |
| 已认证 | 300 次 | 60 秒 |
| 管理员 | 1000 次 | 60 秒 |

- **实现方式**: 基于内存的滑动窗口
- **存储**: `defaultdict` (进程内存)
- **跳过路径**: 同用量追踪

> **单点问题**: 内存限流状态在多worker场景下不共享

---

## 5. Nginx 反向代理配置

### 5.1 上游配置

```nginx
upstream backend {
    server backend:8000;
}
```

> **单一后端**: 无负载均衡配置

### 5.2 关键配置

- **worker_connections**: 1024
- **keepalive_timeout**: 65s
- **WebSocket 超时**: 86400s (24小时)
- **gzip**: 启用，压缩级别 6

### 5.3 安全头

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`

---

## 6. 健康检查

### 6.1 后端健康检查 (`/health`)

```json
{
  "status": "ok",
  "version": "2.0.0",
  "environment": "development",
  "database": "ok"
}
```

### 6.2 Docker健康检查

- **间隔**: 30秒
- **超时**: 10秒
- **启动等待**: 10-15秒
- **重试次数**: 3次

---

## 7. Python 依赖版本

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
sqlalchemy==2.0.36
pydantic==2.10.0
aiosqlite==0.20.0
websockets==13.1
```

---

## 8. 关键发现与风险点

### 8.1 并发瓶颈

1. **单 Worker**: 当前仅1个 uvicorn worker，无法利用多核CPU
2. **SQLite 写锁**: 即使有WAL模式，写操作仍会序列化
3. **同步限流**: 内存限流在多worker下状态不共享

### 8.2 数据风险

1. **用量日志写压力**: 每次API请求都写数据库
2. **无连接池限制**: 虽使用StaticPool，但高并发下可能耗尽文件句柄

### 8.3 监控缺失

1. **无性能监控**: 缺少响应时间、吞吐量统计
2. **无错误追踪**: 错误仅记录到日志，无聚合分析

---

## 9. 优化方向概览

基于当前基线，针对100用户并发的主要优化方向：

| 阶段 | 主题 | 关键措施 |
|------|------|---------|
| 0 | 基线确认 | ✅ 本文档 |
| 1 | 读接口止血 | 缓存、批量接口合并 |
| 2 | 个股分析去重 | 结果复用、避免重复计算 |
| 3 | 降低SQLite写压力 | 用量日志异步化、批量写入 |
| 4 | 重分析任务化 | 后台任务解耦API |
| 5 | 数据边界收敛 | 清理历史数据、设置保留策略 |
| 6 | 数据库迁移准备 | PostgreSQL迁移评估 |

---

## 10. 文件参考

| 文件 | 路径 | 说明 |
|------|------|------|
| 后端入口 | `backend/app/main.py` | FastAPI应用主入口 |
| 配置管理 | `backend/app/config.py` | 应用配置定义 |
| 数据库配置 | `backend/app/database.py` | SQLite连接配置 |
| 用量中间件 | `backend/app/middleware/usage.py` | API用量追踪 |
| 限流中间件 | `backend/app/middleware/rate_limit.py` | API限流 |
| Dockerfile | `Dockerfile` | 后端容器构建 |
| Compose配置 | `docker-compose.yml` | 开发环境编排 |
| Compose配置 | `docker-compose.prod.yml` | 生产环境编排 |
| Nginx配置 | `nginx/nginx.conf` | 反向代理配置 |
