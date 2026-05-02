# 100 用户服务化方案

本文档只保留面向 `2U4G / 100 用户` 的长期有效方案结论，不再展开历史过程。

## 目标

- 支撑约 `100` 注册用户
- 支撑低到中等并发的日常使用
- 保证 `明日之星`、K 线、观察列表等读路径稳定可用
- 将 `单股诊断` 和 `观察分析` 收敛到可控负载范围

## 核心思路

### 1. 公共结果预计算

以下结果优先通过离线任务生成，在线只读：

- 明日之星候选结果
- 评分结果
- 推荐结果

### 2. 个股分析去重与任务化

以下路径不应继续同步重计算：

- 单股诊断
- 观察分析冷缓存路径

原则：

- 同股票、同交易日、同口径优先复用
- 冷缓存走后台任务
- 前端轮询或订阅结果

### 3. 降低 SQLite 写放大

重点控制：

- `usage_logs`
- `last_used_at`
- 任务日志

目标：

- 减少高频逐请求写库
- 保持关键审计能力

### 4. 明确数据边界

- 离线生产结果：文件快照
- 在线用户状态：数据库
- 进程内加速：内存缓存

详见：

- [data-boundary.md](/Volumes/DATA/StockTradebyZ/docs/data-boundary.md:1)

### 5. 允许单机首轮落地，但为 PostgreSQL 迁移留边界

当前阶段允许：

- 单实例
- SQLite

但长期不应把它们视为最终形态。

详见：

- [database-migration.md](/Volumes/DATA/StockTradebyZ/docs/database-migration.md:1)

## 当前适用结论

该方案适合以下结论边界：

- 可以争取 `100` 注册用户规模
- 建议先按 `10-20` 人同时在线验证
- 不默认等同于“稳定支持 100 人高频并发分析”

## 配套文档

- 当前真实状态与待确认事项：
  - [service-readiness-status.md](/Volumes/DATA/StockTradebyZ/docs/service-readiness-status.md:1)

- 当前剩余待确认清单：
  - [service-readiness-100-users-todo.md](/Volumes/DATA/StockTradebyZ/docs/service-readiness-100-users-todo.md:1)
