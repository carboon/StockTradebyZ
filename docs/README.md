# Docs 导航

当前 `docs/` 目录按三类信息组织：

## 1. 长期有效文档

- [deploy.md](/Volumes/DATA/StockTradebyZ/docs/deploy.md:1)
  生产部署说明。

- [baseline-current.md](/Volumes/DATA/StockTradebyZ/docs/baseline-current.md:1)
  当前部署与运行基线，用于容量和优化讨论。

- [data-boundary.md](/Volumes/DATA/StockTradebyZ/docs/data-boundary.md:1)
  数据边界与读写分层规则。

- [logging-strategy.md](/Volumes/DATA/StockTradebyZ/docs/logging-strategy.md:1)
  日志与写入削峰策略。

- [database-migration.md](/Volumes/DATA/StockTradebyZ/docs/database-migration.md:1)
  SQLite 到 PostgreSQL 的迁移规划。

## 2. 方案与执行文档

- [service-readiness-100-users.md](/Volumes/DATA/StockTradebyZ/docs/service-readiness-100-users.md:1)
  面向 `2U4G / 100 用户` 目标的架构分析与改造方案。

- [service-readiness-100-users-todo.md](/Volumes/DATA/StockTradebyZ/docs/service-readiness-100-users-todo.md:1)
  该方案对应的执行 TODO。

- [postgresql-backend-fix-tracker.md](/Volumes/DATA/StockTradebyZ/docs/postgresql-backend-fix-tracker.md:1)
  PostgreSQL 迁移后后端不可用问题的修复清单、方案与测试跟踪。

## 3. 当前状态文档

- [service-readiness-status.md](/Volumes/DATA/StockTradebyZ/docs/service-readiness-status.md:1)
  当前最新状态、已确认结果、待确认事项、灰度前结论。

## 说明

以下阶段性评估/修复过程文档已被收敛，不再单独保留：

- 旧版集成测试阶段报告
- 旧版评估报告
- 旧版精确修复清单
- 旧版最新评估快照

如需判断“现在是否可支撑 100 用户规模”，请优先看：

1. [service-readiness-status.md](/Volumes/DATA/StockTradebyZ/docs/service-readiness-status.md:1)
2. [service-readiness-100-users-todo.md](/Volumes/DATA/StockTradebyZ/docs/service-readiness-100-users-todo.md:1)
