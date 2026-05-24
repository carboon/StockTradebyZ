# 每日更新读路径保护

本文记录“每日数据更新快速更新”完成后的缓存失效、预热和非破坏验证方式，避免在更新窗口结束后让首个用户查询承担冷启动成本。

## 当前链路

后台日更入口是 `BackgroundLatestTradeDayUpdateService.run()`：

1. `assess_freshness()` 判断 DB、CSV、候选和分析结果是否落后。
2. 需要行情更新时调用 `DailyBatchUpdateService.update_trade_date()`，按交易日抓取、写日分片、同步 CSV、批量入库。
3. 构建活跃池排名因子。
4. 重建明日之星、当前热盘和板块分析。
5. 更新交易日缓存并结束运行中状态。
6. 统一失效运行期读缓存。
7. Best-effort 预热榜单读路径和单股诊断历史缓存。

第 7 步不会阻断已经完成的数据更新：预热失败会写入返回值和 warning 日志，但不回滚前面的结果。

## 缓存失效与预热顺序

更新成功后先执行 `_invalidate_runtime_caches()`：

- `freshness:*`
- `candidates:*`
- `analysis_results:*`
- `active_pool_rank:*`
- Tushare 数据状态缓存

随后执行 `prewarm_latest_analysis_views(trade_date)`，覆盖这些读路径：

- 明日之星窗口状态
- 明日之星候选
- 明日之星分析结果
- 当前热盘日期、候选、结果和板块概览
- 板块分析概览和首个板块详情

最后执行 `diagnosis_history_cache_service.prewarm()`，预热单股诊断历史缓存。

## 结构化耗时输出

日更返回值中的 `timings` 现在包含更新主链路和读路径预热耗时：

- `freshness_check`
- `daily_batch_*`
- `active_pool_rank`
- `tomorrow_star_rebuild`
- `current_hot_rebuild`
- `sector_analysis_rebuild`
- `view_cache_prewarm`
- `diagnosis_cache_prewarm`
- `total`

返回值也包含 `read_path_prewarm`，里面按 `view_data`、`diagnosis_cache` 和 `timings` 聚合预热结果，便于测试或日志采集直接断言。

`prewarm_latest_analysis_views()` 的返回值包含 `steps`、`failed` 和每个 step 的 `timings`，用于定位具体慢读路径。

## 非破坏验证建议

不要在共享环境直接运行 `backend/daily_update_test.py`，它会删除并重算指定交易日数据。优先使用以下非破坏方式：

```bash
.venv/bin/python -m pytest backend/tests/test_services/test_background_update_service.py
.venv/bin/python -m pytest backend/tests/test_services/test_view_prewarm_service.py
```

如果需要人工验证预热函数，只在只读查询可接受的环境执行，并指定已经存在的交易日：

```bash
.venv/bin/python - <<'PY'
from app.services.view_prewarm_service import prewarm_latest_analysis_views
print(prewarm_latest_analysis_views("2026-05-08"))
PY
```

这只会读取现有派生结果并写缓存，不会触发行情抓取、删除、补数或重算。

如必须验证完整日更回放，请使用 `docs/dailyUpdateTest.md` 中的 `--restore-after` 流程，并只在可恢复的数据副本上执行。
