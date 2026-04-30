# 100 人服务化架构诊断与改造方案

本文档面向当前仓库的真实实现，回答一个更现实的问题：

- 在 `2U4G` 单机上，面向约 `100` 个用户使用时，当前架构的主要问题是什么？
- 哪些问题必须先改，哪些可以后置？
- 如何定义一套最小验证集合与最终集成测试方案？

本文聚焦 `100` 人规模，不以 `1000` 人 SaaS 级别设计为目标。

## 1. 目标与边界

### 目标

- 支撑约 `100` 个已注册用户。
- 支撑低到中等并发的日常使用。
- 保证 `明日之星`、K 线查看、观察列表等读路径稳定可用。
- 将 `单股诊断` 和 `观察分析` 收敛到可控负载范围内。
- 在不引入过重基础设施的前提下完成第一轮服务化改造。

### 非目标

- 不在本轮把系统改造成分布式微服务。
- 不追求 `1000` 人同时高频分析。
- 不要求首轮就引入完整消息队列体系。
- 不以多机多活为前提设计。

## 2. 当前架构分析

### 2.1 真实运行形态

当前仓库的主定位仍然是“本地工具 + Web 包装层”：

- 业务主流程由 `run_all.py` 驱动。
- 数据源来自 `Tushare`，主数据以 `data/raw/*.csv` 存储。
- 结果数据大量以 `data/candidates/*.json`、`data/review/**/*.json` 组织。
- Web 层为 `FastAPI + Vue`。
- 默认生产启动为单进程 `uvicorn --workers 1`。
- 默认数据库为 `SQLite`。

关键证据：

- [ARCHITECTURE.md](/Volumes/DATA/StockTradebyZ/ARCHITECTURE.md:7)
- [Dockerfile](/Volumes/DATA/StockTradebyZ/Dockerfile:47)
- [backend/app/database.py](/Volumes/DATA/StockTradebyZ/backend/app/database.py:21)

### 2.2 对 100 人场景有利的部分

以下部分天然适合 100 人规模：

- `明日之星` 结果具有强公共性，所有用户看到的是同一份日更结果。
- Tushare 主数据是日更，不是高频实时行情。
- 候选结果、中间结果、评分结果可以预计算。
- 观察列表本身是小数据量。
- 当前数据体量不大，`data/` 目录约 `370M`，单机可承载。

这意味着真正需要在线承压的，主要不是全市场计算，而是用户触发的查询与个股分析。

### 2.3 当前最主要的架构风险

#### 风险 1：服务进程是单 worker

生产启动命令固定为：

```text
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

见 [Dockerfile](/Volumes/DATA/StockTradebyZ/Dockerfile:47)。

影响：

- 所有普通请求、后台任务状态推进、WebSocket 连接共享单进程容量。
- 任何同步重计算接口都会直接拖慢整体响应。
- 一旦出现长请求，用户侧会感知到明显排队和抖动。

对 100 人场景的判断：

- 低频访问可勉强承受。
- 如果在同一时段多人集中点击诊断类接口，风险明显。

#### 风险 2：SQLite + `StaticPool` + 高频小写入

数据库配置见 [backend/app/database.py](/Volumes/DATA/StockTradebyZ/backend/app/database.py:21)：

- SQLite
- `check_same_thread=False`
- WAL
- `StaticPool`

这不是多人在线服务的理想组合，尤其在当前还叠加了多种小写入：

- `usage_logs` 每次 API 请求写一条，见 [backend/app/middleware/usage.py](/Volumes/DATA/StockTradebyZ/backend/app/middleware/usage.py:23)
- `audit_logs` 关键操作写一条，见 [backend/app/audit.py](/Volumes/DATA/StockTradebyZ/backend/app/audit.py:15)
- API Key 使用会更新 `last_used_at`，见 [backend/app/api/deps.py](/Volumes/DATA/StockTradebyZ/backend/app/api/deps.py:136)
- 任务状态与任务日志持续写库，见 [backend/app/services/task_service.py](/Volumes/DATA/StockTradebyZ/backend/app/services/task_service.py:98)

影响：

- 高峰期容易出现锁等待和长尾延迟。
- 读接口也会因为伴随写入而被放大成本。
- 当在线分析和后台更新叠加时更明显。

#### 风险 3：请求链路中存在同步重计算

最危险的不是普通读接口，而是“用户点击一下，服务现场算一遍”。

典型位置：

- 单股分析：`analysis_service.analyze_stock()`，见 [backend/app/services/analysis_service.py](/Volumes/DATA/StockTradebyZ/backend/app/services/analysis_service.py:322)
- 观察股立即分析：`POST /api/v1/watchlist/{id}/analyze`，见 [backend/app/api/watchlist.py](/Volumes/DATA/StockTradebyZ/backend/app/api/watchlist.py:377)

这些路径会做：

- 读取本地 CSV
- 计算 B1 指标
- 执行 quant review
- 持久化分析结果

影响：

- CPU 和 IO 抖动直接暴露给用户请求。
- 热门股票被多人分析时会重复计算。
- 单 worker 形态下，容易出现“一个重请求拖住一串轻请求”。

#### 风险 4：读接口会隐式触发补算

`get_analysis_results()` 在读取结果文件缺失时，会在线触发自动评分，见 [backend/app/services/analysis_service.py](/Volumes/DATA/StockTradebyZ/backend/app/services/analysis_service.py:530)。

这会造成典型的服务化问题：

- 用户以为自己在“看结果”
- 实际系统在“补生产数据”

影响：

- 页面首次打开的耗时不可预期。
- 多人同时进入页面时可能重复补算。
- 结果一致性与容量管理都不清晰。

这是本轮必须优先消除的行为。

#### 风险 5：核心数据仍以文件系统为主，不利于在线服务治理

当前在线查询经常直接读：

- `data/raw/*.csv`
- `data/review/**/*.json`
- `data/cache/*.pkl`

相关代码：

- [backend/app/services/analysis_service.py](/Volumes/DATA/StockTradebyZ/backend/app/services/analysis_service.py:29)
- [backend/app/services/market_service.py](/Volumes/DATA/StockTradebyZ/backend/app/services/market_service.py:360)

问题不在于“文件一定慢”，而在于：

- 一致性边界不清晰
- 缓存与结果管理分散
- 在线请求和离线产出共享同一批文件对象
- 后续扩 worker 或迁移多实例时不好治理

#### 风险 6：进程内状态不利于后续扩展

典型包括：

- `_update_state` 进程内共享，见 [backend/app/services/market_service.py](/Volumes/DATA/StockTradebyZ/backend/app/services/market_service.py:27)
- WebSocket 连接表在进程内 dict，见 [backend/app/main.py](/Volumes/DATA/StockTradebyZ/backend/app/main.py:312)
- 限流窗口在进程内内存，见 [backend/app/middleware/rate_limit.py](/Volumes/DATA/StockTradebyZ/backend/app/middleware/rate_limit.py:25)

对 100 人场景，这不是首要瓶颈，但意味着：

- 当前系统短期内只能按“单实例”思路运行
- 不适合直接通过多 worker 解决压力

### 2.4 结构上的根因

当前系统把三类职责混在了一起：

1. 离线数据生产
2. 在线只读查询
3. 用户触发的即时分析

对 100 人规模来说，真正需要的是把这三类职责分层，而不是一开始大拆架构。

## 3. 100 人场景下的结论

### 可以保留的部分

- 单机部署模式
- Tushare 日更主数据流程
- `run_all.py` 作为离线生产入口
- Vue + FastAPI 基本技术栈
- 文件系统继续作为离线中间产物存储

### 必须先改的部分

- 去掉读接口中的自动补算
- 单股分析结果做去重和缓存复用
- 降低高频明细写库
- 将重计算从同步请求链路中挪走或弱化
- 为未来迁移 PostgreSQL 做好边界准备

### 不必首轮就做的部分

- 微服务拆分
- Redis 全面接管所有缓存
- 分布式任务队列
- 多实例部署

## 4. 改造原则

### 原则 1：公共结果优先预计算

`明日之星`、候选结果、评分结果、推荐结果，优先在日更任务中一次性产出，在线只读。

### 原则 2：个股分析优先复用已有结果

同一只股票、同一交易日、同一策略口径，不应该因不同用户重复计算。

### 原则 3：读接口只读

任何 `GET` 接口都不应隐式触发大计算、补文件、补评分。

### 原则 4：服务化优先减少写放大

先减少 SQLite 压力，再谈并发优化。

### 原则 5：本轮允许单实例，但要预留数据库替换路径

100 人场景可以暂时单实例，但不应把 SQLite 继续绑定为长期形态。

## 5. 分阶段改造计划

### 阶段 A：止血改造

目标：在不重构部署方式的前提下，先把最危险的在线重计算行为收住。

改造项：

- 禁止 `GET /analysis/tomorrow-star/results` 等读路径触发自动评分。
- `watchlist/analyze` 优先读取当日已有分析记录，无则创建后台任务或显式返回“待分析”。
- 为单股分析增加“同股票同交易日结果复用”。
- 暂时关闭或降级 `usage_logs` 明细写入。
- 对 API Key `last_used_at` 更新做降频或异步化。

预期收益：

- 页面打开时延更稳定。
- 避免多人同时触发同一只股票的重复计算。
- SQLite 锁竞争显著下降。

### 阶段 B：数据边界收敛

目标：把“离线生产结果”和“在线查询数据”边界明确下来。

改造项：

- 明日之星相关结果统一落数据库或统一结果快照表。
- 观察分析结果以 `watchlist_analysis` 为准，不再依赖临时文件状态。
- 单股历史分析明确区分：
  - 离线预生成
  - 在线按需任务
- 为热点股票增加预生成策略。

预期收益：

- 在线接口的稳定性更可控。
- 结果来源统一，便于做缓存和测试。

### 阶段 C：数据库切换准备

目标：将在线服务核心状态迁移到更适合多人服务的数据库。

优先迁移表：

- `users`
- `api_keys`
- `watchlist`
- `watchlist_analysis`
- `tasks`
- `task_logs`
- `usage_logs` 或其聚合替代
- `audit_logs`
- `stock_daily`（如果后续在线更多依赖库中行情）

建议目标：

- PostgreSQL

说明：

- 对 100 人，PostgreSQL 不是今天必须上线的动作。
- 但如果打算稳定长期运行，阶段 C 应尽早排期。

### 阶段 D：任务化与缓存化

目标：把真正重的个股分析从同步请求中抽离。

改造项：

- 单股分析改为后台任务。
- 前端轮询任务状态或用现有 WebSocket 订阅结果。
- 增加分析结果 TTL / 交易日维度缓存。
- 热门股票诊断优先命中缓存。

预期收益：

- 用户体验从“卡住等待”改为“提交后查看结果”。
- 重请求不再堵塞轻请求。

## 6. 最小验证集合

最小验证集合只验证“这轮改造最核心的目标是否达成”，不覆盖全量业务正确性。

### 6.1 接口行为验证

必须验证：

1. `GET /api/v1/analysis/tomorrow-star/results`
   - 仅读取结果
   - 不再触发自动分析

2. `POST /api/v1/watchlist/{id}/analyze`
   - 若当日已有分析，直接返回已有结果
   - 同一股票同一日期重复触发不重复计算

3. `GET /api/v1/watchlist/{id}/analysis`
   - 只读数据库结果
   - 不隐式触发分析

4. `GET /api/v1/stock/kline`
   - 只做查询与轻量指标计算
   - 在后台更新运行中仍可稳定返回

### 6.2 数据一致性验证

必须验证：

1. 同一股票同一交易日只保留一条有效观察分析结果。
2. 单股分析结果与观察分析结果的复用策略明确。
3. 读接口失败不会写入半成品文件。
4. 后台任务中断后，不会污染前台已发布结果。

### 6.3 负载保护验证

必须验证：

1. 连续快速点击同一分析接口，不会产生重复任务洪泛。
2. 高频读取明日之星页面时，不会触发补算。
3. 关闭 `usage_logs` 明细写入后，主要功能不受影响。
4. 后台全量/增量更新运行时，普通查询接口仍可返回。

### 6.4 回归验证

必须验证：

1. 明日之星日期列表仍正确。
2. 候选列表分页/limit 逻辑仍正确。
3. 观察列表 CRUD 不回归。
4. 登录、注册、鉴权不回归。

## 7. 最终集成测试方案

最终集成测试方案分为四层：接口层、任务层、并发层、手工验收层。

### 7.1 自动化接口层

基于现有后端测试目录扩展：

- [backend/tests/test_api/test_analysis_api.py](/Volumes/DATA/StockTradebyZ/backend/tests/test_api/test_analysis_api.py:1)
- [backend/tests/test_api/test_watchlist_api.py](/Volumes/DATA/StockTradebyZ/backend/tests/test_api/test_watchlist_api.py:1)
- [backend/tests/test_api/test_tasks_api.py](/Volumes/DATA/StockTradebyZ/backend/tests/test_api/test_tasks_api.py:1)

新增重点用例：

- 读接口不触发自动补算
- 重复分析请求命中已有结果
- 重复分析请求只创建一个任务
- 更新任务运行中前台查询仍能成功
- 停用 `usage_logs` 明细模式后接口仍通过

### 7.2 自动化服务层

新增或扩展服务层测试：

- `analysis_service`
  - 结果复用
  - 不在读路径补算
  - 单股分析缓存命中

- `task_service`
  - 同股票同日期分析任务去重
  - 后台任务状态流转正确

- `market_service`
  - 更新任务与查询任务的并存边界

### 7.3 自动化并发层

这里不做重型压测，做轻量并发语义验证即可。

建议场景：

1. 10 个并发请求同时访问 `tomorrow-star/results`
   - 验证无补算
   - 验证结果一致

2. 10 个并发请求同时触发同一只股票的分析
   - 验证只产生一份有效结果或一个有效任务

3. 后台增量更新运行中，同时发起：
   - 20 次 K 线查询
   - 20 次明日之星结果查询
   - 5 次观察列表读取
   验证接口仍可返回，且无明显异常状态

### 7.4 手工验收层

手工验收建议按真实用户路径走：

1. 管理员登录
2. 查看明日之星结果
3. 搜索个股并查看 K 线
4. 加入观察列表
5. 触发一次观察股分析
6. 刷新页面后查看分析历史
7. 运行增量更新
8. 更新运行中继续浏览结果页和 K 线页
9. 检查任务中心状态与页面功能是否一致

验收关注点：

- 页面是否明显卡顿
- 是否出现重复分析
- 是否出现锁等待或错误响应
- 任务进行中前台是否仍可读

## 8. 推荐的落地顺序

如果只允许做一轮有限改造，建议顺序如下：

1. 去掉读接口自动补算
2. 观察分析结果去重与复用
3. 降低 `usage_logs`/`last_used_at` 写频率
4. 单股分析任务化
5. 收敛结果数据边界
6. 规划 PostgreSQL 迁移

## 9. 最终判断

当前系统在 100 人规模下不是“完全不能用”，而是“可以通过一轮中等强度改造达到稳定可用”。

最关键的不是推翻现有技术栈，而是修正以下四件事：

- 读接口不能补算
- 重分析不能同步压在请求上
- SQLite 不能继续承受无必要的高频小写入
- 公共结果和个性化结果要分层

只要这四点收住，`2U4G` 单机服务 100 人规模会现实很多。
