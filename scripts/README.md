# Scripts 目录整理

数据运维入口已统一收口到仓库根目录：

```bash
./update-data.sh daily
./update-data.sh generate
./update-data.sh intraday
./update-data.sh repair daily
./update-data.sh repair scores
```

含义：

- `daily`：更新最新交易日或指定交易日的日线，并重建当日明日之星/当前热盘
- `generate`：基于已有日线重建近 120 交易日窗口结果
- `intraday`：11:30 后生成中盘快照，默认只取 `09:30~11:30`
- `repair daily`：修复 `stock_daily` 缺失或样本不足
- `repair scores`：修复明日之星/当前热盘历史评分结果

目录职责：

- `backend/scripts/`：功能实现脚本，供 `update-data.sh` 或服务内部调用
- `scripts/`：保留少量辅助脚本，不再承载数据更新主入口
- `deploy/scripts/`：Docker 起停、发布、运维脚本

仍建议直接保留和使用的实现脚本：

- `backend/scripts/rebuild_recent_120_data.py`
- `backend/scripts/run_background_latest_trade_day_update.py`
- `backend/scripts/generate_intraday_snapshots.py`
- `backend/scripts/repair_incomplete_stock_daily.py`
- `backend/scripts/repair_historical_scores.py`
- `backend/scripts/import_users_from_export.py`

辅助脚本示例：

```bash
python scripts/benchmark_api_performance.py
python backend/scripts/import_users_from_export.py --dry-run
```
