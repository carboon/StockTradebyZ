# Scripts 目录整理

`scripts/` 现在只保留宿主机直接执行的主入口。

- `backend/scripts/`：实际功能实现，负责数据修复、重建、导入。
- `scripts/`：本地快捷入口，统一补齐 `.venv` 和 `PYTHONPATH` 后再调用 `backend/scripts/`。
- `deploy/scripts/`：Docker 和停服维护包装层，不作为功能脚本的主入口。

运行这些本地脚本前，默认要求当前 Python 环境已安装后端依赖；仓库约定优先使用项目 `.venv`。

## 主脚本清单

### 1. `rebuild_recent_120.sh`

用途：

- 重建最近 N 个交易日的原始数据和派生结果
- 会调用 `backend/scripts/rebuild_recent_120_data.py`

适用场景：

- 最近一段时间的数据窗口需要整体重建
- 明日之星、当前热盘、诊断历史需要连带重算

示例：

```bash
bash scripts/rebuild_recent_120.sh --help
bash scripts/rebuild_recent_120.sh --yes --window-size 120
```

### 2. `repair_historical_scores.sh`

用途：

- 修复历史评分链路异常
- 会调用 `backend/scripts/repair_historical_scores.py`

适用场景：

- 明日之星历史结果出现空评分、旧版 `prefilter_blocked`
- 当前热盘历史结果缺少详情
- 候选数量与分析数量不一致

示例：

```bash
bash scripts/repair_historical_scores.sh --help
bash scripts/repair_historical_scores.sh --scope both --window-size 5
```

### 3. `repair_incomplete_stock_daily.sh`

用途：

- 修复 `stock_daily` 缺失或样本不足的问题
- 会调用 `backend/scripts/repair_incomplete_stock_daily.py`

适用场景：

- 单股诊断提示样本不足
- 某些股票只有极少量历史日线

示例：

```bash
bash scripts/repair_incomplete_stock_daily.sh --help
bash scripts/repair_incomplete_stock_daily.sh --min-days 250 --limit 20 --dry-run
```

### 4. `import_users_from_export.py`

用途：

- 从仓库根目录 `user/*/users.csv` 导入用户到当前系统
- 默认按用户名幂等导入，避免重复插入
- 导入后会自动修正 `users` 表自增序列

适用场景：

- 将旧环境导出的用户账号批量恢复到当前 PostgreSQL
- 本地或服务器上重复执行增量导入

示例：

```bash
python backend/scripts/import_users_from_export.py --dry-run
python backend/scripts/import_users_from_export.py --database-url postgresql://stocktrade:stocktrade123@127.0.0.1:5432/stocktrade
python backend/scripts/import_users_from_export.py --update-existing
```

## 辅助脚本

### `benchmark_api_performance.py`

用途：

- 基于内存数据库和 `TestClient` 做 API 性能基准

示例：

```bash
python scripts/benchmark_api_performance.py
```

## 底层实现脚本

这些脚本仍然保留在 `backend/scripts/`，但不再作为 `scripts/` 的主入口暴露：

- `fetch_missing_stock_daily.py`
  只补 `stock_daily` 完全没有记录的股票，功能已被 `repair_incomplete_stock_daily.py` 大范围覆盖，属于旧工具。
- `backfill_stock_daily_market_metrics.py`
  回填 `data/raw/*.csv` 和数据库中的换手率、量比、资金流等扩展指标。
- `import_raw_daily_to_db.py`
  将 `data/raw_daily/*.jsonl` 导入数据库。
- `run_background_latest_trade_day_update.py`
  最新交易日后台更新脚本，主要由维护脚本或容器包装层调用。

## 本次清理

- 删除了旧的 `repair_historical.sh`
- 原因是它与历史评分修复功能重复，且包含硬编码本机路径，不适合作为仓库主脚本保留
- 统一改为 `repair_historical_scores.sh` 作为明确入口
