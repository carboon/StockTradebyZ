# 数据边界收敛规范

> 阶段5：明确系统数据来源边界，统一离线生产与在线服务的数据读取路径。

## 1. 核心原则

### 1.1 数据分层

| 层级 | 类型 | 存储位置 | 特点 | 示例 |
|------|------|----------|------|------|
| **离线生产层** | 文件 | `data/raw/`, `data/candidates/`, `data/review/` | 批量计算结果，持久化快照 | K线CSV、候选快照、评分结果 |
| **在线服务层** | 数据库 | SQLite (`data/db/stocks.db`) | 实时查询，用户数据 | 用户、观察列表、任务状态 |
| **内存缓存层** | 内存 | 进程内存 | 临时加速，进程重启丢失 | 分析缓存、增量更新状态 |

### 1.2 数据读取优先级

```
1. 数据库（在线服务唯一真相源）
2. 内存缓存（进程内临时加速）
3. 文件快照（离线生产结果，仅当数据库无数据时读取）
```

---

## 2. 数据边界明细

### 2.1 明日之星数据

| 数据项 | 主存储 | 读取路径 | 说明 |
|--------|--------|----------|------|
| 候选股票代码 | **文件** | `data/candidates/candidates_{date}.json` | 离线生产，在线读取 |
| 评分结果 | **文件** | `data/review/{date}/{code}.json` | 离线生产，在线读取 |
| Top5推荐 | **文件** | `data/review/{date}/suggestion.json` | 离线生产，在线读取 |

**代码位置**: `backend/app/services/analysis_service.py`
- `load_candidate_codes()`: 从文件读取候选代码
- `get_analysis_results()`: 从文件读取评分结果

**API端点**: `GET /api/analysis/tomorrow-star/candidates`
- 优先从 `candidates_latest.json` 读取最新日期
- 如果指定日期，读取对应日期的快照文件

---

### 2.2 观察列表数据

| 数据项 | 主存储 | 读取路径 | 说明 |
|--------|--------|----------|------|
| 观察列表项 | **数据库** | `watchlist` 表 | 用户配置，数据库为唯一真相源 |
| 观察列表分析历史 | **数据库** | `watchlist_analysis` 表 | 分析结果存储到数据库 |
| 实时分析结果 | **文件** + **数据库** | `data/review/{date}/{code}.json` + 复用缓存 | 优先复用已有分析 |

**代码位置**: `backend/app/api/watchlist.py`
- `get_watchlist()`: 从数据库读取
- `analyze_watchlist_item()`: 分析结果写入 `watchlist_analysis` 表

---

### 2.3 单股诊断数据

| 数据项 | 主存储 | 读取路径 | 说明 |
|--------|--------|----------|------|
| 诊断请求任务 | **数据库** | `tasks` 表 | 任务状态追踪 |
| 诊断结果（实时） | **数据库** | `tasks.result_json` | 任务结果存储在数据库 |
| 诊断历史（预生成） | **文件** | `data/review/history/{code}.json` | 离线预生成，在线读取 |

**代码位置**: `backend/app/api/analysis.py`
- `analyze_stock()`: 创建任务，结果存入数据库
- `get_diagnosis_history()`: 优先从历史文件读取

---

### 2.4 市场数据

| 数据项 | 主存储 | 读取路径 | 说明 |
|--------|--------|----------|------|
| 原始K线数据 | **文件** | `data/raw/{code}.csv` | Tushare同步结果 |
| 最新交易日 | **文件** | `data/.market_cache.json` | 市场服务缓存 |
| 股票基本信息 | **数据库** | `stocks` 表 | 从Tushare同步 |

**代码位置**: `backend/app/services/market_service.py`
- `incremental_update()`: 更新CSV文件
- `TushareService`: 同步股票信息到数据库

---

### 2.5 用户与认证数据

| 数据项 | 主存储 | 读取路径 | 说明 |
|--------|--------|----------|------|
| 用户信息 | **数据库** | `users` 表 | 用户配置 |
| API密钥 | **数据库** | `api_keys` 表 | API认证 |
| 配置项 | **数据库** | `configs` 表 | 系统配置 |

---

## 3. 数据生产者与消费者

### 3.1 离线生产（文件）

| 生产者 | 输出文件 | 触发方式 |
|--------|----------|----------|
| `run_all.py` | `data/candidates/candidates_{date}.json` | 后台任务/手动 |
| `run_all.py` | `data/review/{date}/{code}.json` | 后台任务/手动 |
| `run_all.py` | `data/review/{date}/suggestion.json` | 后台任务/手动 |
| 增量更新 | `data/raw/{code}.csv` | 后台任务/手动 |
| 历史生成 | `data/review/history/{code}.json` | 手动API触发 |

### 3.2 在线服务（数据库）

| 生产者 | 输出表 | 触发方式 |
|--------|--------|----------|
| 用户操作 | `watchlist`, `watchlist_analysis` | REST API |
| 任务系统 | `tasks`, `task_logs` | 后台任务 |
| Tushare同步 | `stocks`, `stock_daily` | 后台任务 |

---

## 4. 统一数据访问接口

### 4.1 明日之星 - 推荐统一方式

**当前状态**: 数据分散在文件系统
**推荐优化**: 逐步迁移到数据库（见阶段6）

**临时规范**:
1. 候选代码：继续从文件读取（`candidates_latest.json`）
2. 评分结果：继续从文件读取（`review/{date}/{code}.json`）
3. API负责组装返回，不修改文件

### 4.2 观察列表 - 已统一

- 所有读取/写入都通过 `watchlist` 和 `watchlist_analysis` 表
- 文件系统仅作为临时缓存（通过 `analysis_cache` 服务）

### 4.3 单股诊断 - 双轨制

- 实时诊断：结果存入 `tasks.result_json`
- 历史数据：从预生成文件读取（`review/history/{code}.json`）

---

## 5. 数据一致性策略

### 5.1 缓存失效策略

```python
# analysis_cache.py
# 策略版本控制：策略变更时自动失效缓存
STRATEGY_VERSION = "v1"  # 修改策略逻辑时更新此版本
```

### 5.2 去重机制

1. **分析去重**: 同一股票同一交易日只分析一次
   - 通过 `analysis_cache.is_analysis_in_progress()` 防止并发
   - 通过 `analysis_cache.get_cached_analysis()` 复用结果

2. **任务去重**: 同一股票同一交易日只创建一个任务
   - `TaskService._get_active_single_analysis_task()` 查询已有任务

---

## 6. 未来演进方向（阶段6）

### 6.1 文件数据数据库化

| 文件 | 目标表 | 优先级 |
|------|--------|--------|
| `candidates_{date}.json` | `candidates` 表 | 高 |
| `review/{date}/{code}.json` | `analysis_results` 表 | 高 |
| `review/history/{code}.json` | `daily_b1_checks` 表 | 中 |

### 6.2 原子性保证

- 当前文件写入无法保证原子性
- 数据库事务可保证多表写入的原子性

---

## 7. 附录：关键路径

### 7.1 明日之星完整流程

```
1. run_all.py (离线)
   ├─ 生成 candidates_{date}.json
   ├─ 生成 review/{date}/{code}.json
   └─ 生成 review/{date}/suggestion.json

2. GET /api/analysis/tomorrow-star/candidates (在线)
   ├─ 读取 candidates_latest.json
   ├─ 实时计算 B1 指标
   └─ 返回候选列表

3. GET /api/analysis/tomorrow-star/results (在线)
   ├─ 读取 review/{date}/suggestion.json
   └─ 返回 Top5 推荐
```

### 7.2 观察列表分析流程

```
1. POST /api/watchlist (在线)
   └─ 写入 watchlist 表

2. POST /api/watchlist/{id}/analyze (在线)
   ├─ 检查缓存 (analysis_cache)
   ├─ 执行分析 (analysis_service)
   ├─ 写入 review/{date}/{code}.json (文件)
   └─ 写入 watchlist_analysis 表 (数据库)

3. GET /api/watchlist/{id}/analysis (在线)
   └─ 读取 watchlist_analysis 表
```

---

## 8. 代码修改记录

### 8.1 已完成（本阶段）

1. **确认数据边界**: 梳理所有数据读取路径
2. **创建文档**: 本文档 (`docs/data-boundary.md`)

### 8.2 待完成（未来阶段）

1. **候选结果数据库化**: 迁移 `candidates` 到数据库表
2. **评分结果数据库化**: 迁移 `analysis_results` 到数据库表
3. **历史分析数据库化**: 迁移 `daily_b1_checks` 到数据库表

---

*最后更新: 2026-05-01*
