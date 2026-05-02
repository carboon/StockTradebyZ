# PostgreSQL 后端故障修复跟踪

> 更新时间：2026-05-02
> 目标：恢复 Docker 部署下后端可用性，并建立 PostgreSQL 稳定运行基线

本文档用于跟踪 SQLite 迁移到 PostgreSQL 后出现的后端不可用问题，覆盖：

- 故障现状
- 根因拆解
- 修复清单
- 验证方案
- 回归测试方案

## 1. 当前现状

当前 Docker 状态表现为：

- `postgres` 容器健康
- `backend` 容器健康
- `/health` 可稳定返回

本轮确认结果：

- `docker compose -f deploy/docker-compose.yml ps` 中 `backend` 为 `healthy`
- 连续 5 次 `curl http://127.0.0.1:8000/health` 均返回 `200`
- 单次耗时约 `0.003-0.004s`

## 2. 已确认的问题

### P0-1. `stock_daily` 主键序列未对齐

现象：

- PostgreSQL 日志反复出现：
  - `duplicate key value violates unique constraint "stock_daily_pkey"`
  - `Key (id)=(1)/(2)/(3)/(4) already exists`

判断：

- 数据迁移后，`stock_daily.id` 的 PostgreSQL sequence 没有同步到 `MAX(id)`
- 应用运行时继续新增 `stock_daily` 记录时，从错误的 sequence 值取号，持续撞主键

影响：

- 增量更新无法正常写入
- 后端后台任务持续报错

### P0-2. `stock_daily` 与 `stocks` 存在主从数据不一致

现象：

- PostgreSQL 日志出现：
  - `Key (code)=(300344) is not present in table "stocks"`
  - `Key (code)=(002231) is not present in table "stocks"`

判断：

- `stock_daily` 已导入，但 `stocks` 表缺少部分对应股票主数据
- 导入顺序、导入完整性或补偿脚本存在缺陷

影响：

- 外键约束失败
- 单股诊断、观察列表、K 线查询等依赖股票主数据的功能存在隐患

### P0-3. 后端健康检查被同步长任务拖死

现象：

- `backend` 健康检查第一次成功，随后连续超时 10 秒
- 同时日志显示后端仍在持续执行大批量 `stock_daily` 写入

代码位置：

- [backend/app/api/tasks.py](/Volumes/DATA/StockTradebyZ/backend/app/api/tasks.py:250)

判断：

- `asyncio.create_task()` 启动的是 async 包装函数
- 但其中直接执行同步的 `daily_data_service.incremental_update(...)`
- 该长任务阻塞事件循环，导致 `/health` 无法及时响应

影响：

- 后端容器变为 `unhealthy`
- Nginx / 前端 / 运维视角均表现为“服务不可用”

### P1-1. 布尔字段迁移不符合 PostgreSQL 类型要求

现象：

- PostgreSQL 日志出现：
  - `column "is_active" is of type boolean but expression is of type integer`

判断：

- 迁移脚本或导入 SQL 沿用了 SQLite 的 `0/1`
- PostgreSQL 布尔字段需要 `true/false` 或显式转换

影响：

- 用户、观察列表、API key 等相关表的导入和初始化存在失败风险

### P1-2. 补偿 SQL 假设不满足 PostgreSQL 非空约束

现象：

- PostgreSQL 日志出现：
  - `null value in column "created_at" of relation "stocks" violates not-null constraint`

判断：

- 补数据时仅插入 `code`
- 但 `stocks.created_at` 在当前模型中非空

影响：

- 自动修复孤儿 `stock_daily.code` 的补偿脚本不可用

## 3. 修复清单

### 第一阶段：先恢复服务可用性

- [x] 停止当前自动触发的增量更新任务
- [x] 确认后端在“无数据更新任务运行”时可稳定返回 `/health`
- [x] 记录当前 `backend` 容器健康状态恢复结果

完成标准：

- `docker compose -f deploy/docker-compose.yml ps` 中 `backend` 不再是 `unhealthy`
- 连续 5 次 `curl http://127.0.0.1:8000/health` 均在 1 秒内返回

### 第二阶段：修复 PostgreSQL 数据一致性

- [x] 校准 `stock_daily` 的 sequence 到当前 `MAX(id)`
- [x] 检查并校准其他自增表 sequence
- [x] 检查 `stock_daily` 中引用但 `stocks` 缺失的代码
- [x] 补齐缺失的 `stocks` 主数据
- [x] 对无法补齐的脏数据决定处理策略：
  - 删除孤儿 `stock_daily`
  - 或导入最小合法 `stocks` 占位记录

完成标准：

- `stock_daily` 不再出现主键冲突
- `stock_daily.code -> stocks.code` 外键一致

### 第三阶段：修复迁移脚本

- [x] 修复 `users.is_active` 等布尔字段导入转换逻辑
- [x] 修复补偿 SQL 对 `created_at` / `updated_at` 非空字段的处理
- [x] 增加迁移后的 sequence 校准步骤
- [x] 增加迁移完成后的完整性校验输出

完成标准：

- 迁移脚本可在空 PostgreSQL 上完整执行
- 不再依赖手工补 sequence 或手工补布尔字段

### 第四阶段：修复运行时架构问题

- [x] 将增量更新改为真正后台执行
- [x] 避免在事件循环线程中直接执行同步长任务
- [ ] 为长任务增加显式运行状态、超时和错误记录

建议修法：

- 方案 A：`asyncio.to_thread(...)`
- 方案 B：专用 worker 线程/进程
- 方案 C：拆为独立任务执行器

当前推荐：

- 先用 `asyncio.to_thread(...)` 作为最小修复
- 后续再考虑独立 worker

完成标准：

- 增量更新运行时，`/health` 仍稳定返回
- 增量更新失败不会拖垮 Web API

## 4. 修复方案

### 方案 1：数据库紧急修复

目标：

- 快速恢复当前 PostgreSQL 环境可用性

步骤：

1. 暂停增量更新触发
2. 对所有自增表执行 sequence 对齐
3. 查找并修复 `stocks` / `stock_daily` 数据不一致
4. 重新验证后端健康检查

优点：

- 恢复最快
- 不需要立刻重做整套迁移

缺点：

- 只能修当前库
- 迁移脚本问题仍然存在

### 方案 2：重建 PostgreSQL 并重跑规范化迁移

目标：

- 从源头纠正迁移过程

步骤：

1. 修迁移脚本
2. 清空当前 PostgreSQL 测试库
3. 从 SQLite 重新导入
4. 执行迁移后完整性校验
5. 再启动后端

优点：

- 数据库状态最干净
- 后续可重复部署

缺点：

- 修复周期更长
- 需要可接受重建当前 PostgreSQL

### 当前建议

建议按以下顺序执行：

1. 先走“方案 1”恢复当前环境
2. 再补“方案 2”把迁移流程固化

原因：

- 当前首要目标是恢复后端可用性
- 不是立刻重构整套迁移链路

## 5. 最小验证集合

修复过程中，每完成一项至少执行以下最小验证：

### V1. 后端健康检查

- `curl http://127.0.0.1:8000/health`
- 连续执行 5 次

通过标准：

- 全部返回 200
- JSON 中 `database=ok`
- 单次耗时 < 1 秒

当前结果：

- 已通过

### V2. PostgreSQL sequence 校验

检查项：

- `stock_daily`
- `users`
- `tasks`
- `watchlist`
- `watchlist_analysis`
- `usage_logs`

通过标准：

- 所有 sequence 当前值 >= 对应表 `MAX(id)`

当前结果：

- 已通过关键表与修复脚本验证
- `stock_daily_id_seq.last_value = stock_daily.max(id)`
- `users_id_seq.last_value = users.max(id)`

### V3. 数据完整性校验

检查项：

- `stock_daily` 中不存在引用缺失 `stocks.code` 的记录
- `users.is_active` / `watchlist.is_active` 等布尔字段可正常查询

通过标准：

- 孤儿外键数量为 0
- 布尔字段查询无类型错误

当前结果：

- 已通过
- `stock_daily` 孤儿外键数量为 `0`
- `users.is_active` 当前类型与查询正常

### V4. 基本接口可用性

至少验证：

- `/health`
- `/api/v1/tasks/overview`
- `/api/v1/stock/search?q=000001`
- `/api/v1/stock/kline`

通过标准：

- 无 500
- 响应时间可接受

## 6. 集成测试方案

### 阶段 A：数据库层验证

- [ ] 使用 PostgreSQL 新库执行迁移
- [ ] 执行 sequence 校验脚本
- [ ] 执行外键完整性检查
- [ ] 执行布尔字段抽样检查

### 阶段 B：服务启动验证

- [ ] `docker compose -f deploy/docker-compose.yml up -d`
- [ ] 观察 `backend` 容器是否健康
- [ ] 连续 5 分钟监控 `docker compose ... ps`
- [ ] 确认无健康检查超时

### 阶段 C：接口回归验证

- [ ] 登录
- [ ] 搜索股票
- [ ] 获取 K 线
- [ ] 单股诊断
- [ ] 观察列表读取
- [ ] 任务中心读取

### 阶段 D：更新任务回归验证

- [ ] 手动启动一次增量更新
- [ ] 更新期间持续轮询 `/health`
- [ ] 更新期间访问 `/api/v1/tasks/overview`
- [ ] 更新完成后检查错误日志

通过标准：

- 更新期间 Web API 不失联
- 更新完成后无主键冲突、外键冲突、布尔类型错误

## 7. 当前结论

当前可以确认：

- PostgreSQL 迁移后导致后端不可用的核心故障已修复
- `backend` / `postgres` 容器均为健康状态
- 关键 sequence 已对齐
- `stock_daily -> stocks` 外键一致性已恢复
- 增量更新不再直接阻塞事件循环
- `scripts/fix_postgresql_sequences.sql` 与 `scripts/fix_postgresql_sequences.sh` 已可实际执行

当前仍建议保留的后续项：

- 对长任务增加更明确的超时、失败收敛和运行状态记录
- 再做一轮真实增量更新期间的接口冒烟验证

## 8. 跟踪结论模板

每次修复后建议按以下模板更新：

- 修复项：
- 修改文件：
- 验证命令：
- 验证结果：
- 是否关闭该问题：
- 剩余风险：
