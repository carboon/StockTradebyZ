# Tomorrow Star 180D Rolling Window Plan

## 1. 目标

将“明日之星”从当前仅展示少量最新日期，升级为：

- 始终保留最近 `180` 个交易日的持久化结果
- 系统启动后自动检查并补齐缺失日期
- 每日增量更新成功后自动追加当天结果
- 以滚动窗口方式删除窗口外最早一天的派生结果
- 页面和 API 全部只读持久化结果，不在查询接口中临时重算

严格口径：

- 对任意交易日 `T` 的候选、趋势启动数、候选明细、Top5 分析结果，都只能基于 `<= T` 的数据计算
- 不允许使用 `T` 之后的数据回头污染历史结果

---

## 2. 范围

本方案仅管理“明日之星”派生结果：

- `candidates`
- `analysis_results`
- 如保留文件缓存，则包括：
  - `data/candidates/candidates_<date>.json`
  - `data/review/<date>/`

不纳入滚动删除范围：

- `stock_daily`
- `stocks`
- 其他业务表

说明：

- 原始行情 `stock_daily` 必须长期保留，用于重算、追溯、补数、回测
- 滚动窗口只作用于明日之星派生结果

---

## 3. 当前问题

当前代码存在以下结构性风险：

1. `candidates`、`analysis_results` 缺少业务唯一约束
2. 查询接口仍保留文件回退和部分临时重算路径，口径不够收敛
3. 缺少按日期的生成状态表，无法明确区分：
   - 未生成
   - 生成中
   - 已完成
   - 失败
4. 启动补齐与每日增量更新之间缺少任务互斥
5. 缺少统一的窗口维护能力：
   - 补齐
   - 追加
   - 裁剪
6. 历史展示虽然可以扩展到 180 日，但尚未建立完整的数据一致性保障

---

## 4. 数据量评估

基于当前真实数据估算：

- 平均每日候选数约 `80~100`
- `180` 个交易日约 `1.5 万 ~ 1.8 万` 条候选
- `analysis_results` 同量级
- 两表合计库内体量通常约 `60~100 MB`

结论：

- PostgreSQL 存储压力很低
- 主要关注点不是容量，而是：
  - 幂等性
  - 索引
  - 任务互斥
  - 历史口径一致性

---

## 5. 最终运行模型

### 5.1 启动阶段

服务启动后，不阻塞 HTTP 可用性，异步触发：

- `ensure_tomorrow_star_window(window_size=180)`

执行逻辑：

1. 确认本地 `stock_daily` 已具备足够交易日数据
2. 识别最近 `180` 个有效交易日
3. 检查这些日期在明日之星派生结果中是否完整
4. 对缺失日期逐日补齐
5. 更新状态表

注意：

- 启动时不直接做 Tushare 全量拉取
- 如果原始行情本身不完整，只记录状态，不强行补算派生结果

### 5.2 每日增量阶段

每日增量更新成功后，串行执行：

1. 校验当天交易日数据完整
2. 生成当天 `candidates`
3. 生成当天 `analysis_results`
4. 将当天标记为完整成功
5. 执行 `prune_tomorrow_star_window(window_size=180)`

### 5.3 查询阶段

所有查询接口只读持久化结果：

- 左侧历史记录：数据库聚合
- 右侧候选列表：数据库读取
- 右侧分析结果：数据库读取

禁止：

- 在 GET 接口中补算
- 在 GET 接口中写文件
- 在 GET 接口中修数据

---

## 6. 数据库改造任务

### 6.1 为派生表增加唯一约束

必须新增：

- `candidates (pick_date, code)` 唯一约束
- `analysis_results (pick_date, code, reviewer)` 唯一约束

目的：

- 防止重复写入
- 支持补齐任务重试
- 支持幂等 upsert / replace 策略

### 6.2 增加复合索引

必须新增：

- `candidates (pick_date, code)`
- `analysis_results (pick_date, code)`
- `analysis_results (pick_date, signal_type)`

建议新增：

- `analysis_results (pick_date, reviewer)`
- `candidates (pick_date, id)` 或保留按 `id` 排序的同时评估实际执行计划

说明：

- 左侧历史记录按 `pick_date` 聚合，并按 `signal_type='trend_start'` 统计
- 右侧候选和分析都是典型的“按日期查全量明细”
- 复合索引能减少后续 180 日历史下的扫描范围

### 6.3 新增按日期状态表

建议新增新表，例如：

- `tomorrow_star_runs`

字段建议：

- `pick_date`
- `status`：`pending/running/success/failed`
- `candidate_count`
- `analysis_count`
- `trend_start_count`
- `reviewer`
- `strategy_version`
- `window_size`
- `started_at`
- `finished_at`
- `error_message`
- `source`
  - `bootstrap`
  - `incremental_update`
  - `manual_rebuild`

必要约束：

- `pick_date` 唯一

作用：

- 启动检查时判断缺口
- 前端可以显示“补齐中 / 失败 / 已完成”
- 故障恢复和重试更可控

### 6.4 保留原始行情全量

明确规则：

- 不对 `stock_daily` 做 180 日裁剪
- 原始行情继续全量保存

---

## 7. 后端服务改造任务

### 7.1 新增窗口维护服务

新增服务模块，例如：

- `backend/app/services/tomorrow_star_window_service.py`

至少提供以下能力：

1. `get_recent_trade_dates(window_size: int) -> list[str]`
2. `ensure_window(window_size: int = 180) -> dict`
3. `build_for_trade_date(trade_date: str, reviewer: str = "quant") -> dict`
4. `prune_window(window_size: int = 180) -> dict`
5. `get_window_status(window_size: int = 180) -> dict`

### 7.2 单日构建必须严格 as-of

`build_for_trade_date(T)` 的计算规则必须保证：

- 候选计算只看 `<= T`
- 分析计算只看 `<= T`
- 不读取 `T` 之后的快照或缓存

落地要求：

- 对 `prepared` / `DataFrame` 明确切片到 `<= T`
- 不允许复用“最新日期”的临时产物直接映射到历史日期

### 7.3 单日写入必须原子化

单日写入流程必须做到：

1. 开始状态写入 `running`
2. 在内存中完成当天候选和分析结果计算
3. 在一个事务里替换：
   - 当天 `candidates`
   - 当天 `analysis_results`
   - 当天 `tomorrow_star_runs`
4. 成功后提交
5. 失败则整体回滚并标记 `failed`

禁止：

- 候选先落库，分析稍后再补
- 中途暴露半成品日期

### 7.4 启动补齐后台化

需要在应用生命周期中接入：

- 服务启动后创建后台任务
- 不阻塞 API 启动

要求：

- 若已有同类任务运行，则跳过重复启动
- 日志中明确打印：
  - 目标窗口
  - 缺口日期数
  - 当前处理日期
  - 成功/失败汇总

### 7.5 每日增量任务串联窗口维护

每日增量更新成功后，必须调用：

1. `build_for_trade_date(today_trade_date)`
2. `prune_window(180)`

前提：

- 当天行情完整
- Tushare 判定该交易日数据已可读

### 7.6 任务互斥

必须实现互斥，防止以下任务并发：

- 启动补齐
- 每日增量
- 手工重建某一天/某个窗口

实现方式可选：

- 数据库任务锁表
- PostgreSQL advisory lock
- 现有任务表中增加互斥控制

要求：

- 同一时间只能有一个 tomorrow star 窗口维护任务运行

### 7.7 故障恢复和重试

需要定义重试策略：

- `failed` 日期可单独重试
- 启动检查时可自动拾取失败日期
- 支持人工触发重建单天或重建窗口

---

## 8. API 改造任务

### 8.1 历史接口

目标：

- 支持返回最近 `180` 个交易日历史

任务：

- `GET /api/v1/analysis/tomorrow-star/dates`
  - 默认返回 `180`
  - 从数据库读取
  - 结合 `tomorrow_star_runs` 返回状态信息

返回建议增加：

- `status`
- `is_complete`
- `latest_available`

### 8.2 候选列表接口

目标：

- 只读数据库持久化结果

任务：

- `GET /api/v1/analysis/tomorrow-star/candidates`
  - 优先且仅从数据库读取
  - 移除或禁用 GET 场景下的临时重算路径
  - 明确对历史日期直接按 `pick_date` 返回

### 8.3 分析结果接口

目标：

- 只读数据库持久化结果

任务：

- `GET /api/v1/analysis/tomorrow-star/results`
  - 优先改为数据库读取
  - 不依赖 `suggestion.json`
  - 不依赖 `review/<date>/*.json`

### 8.4 状态接口

建议新增：

- `GET /api/v1/analysis/tomorrow-star/window-status`

返回内容建议包括：

- 目标窗口大小
- 已完成天数
- 缺失天数
- 失败天数
- 当前运行状态
- 正在处理的日期

---

## 9. 前端改造任务

### 9.1 左侧历史记录

改造目标：

- 支持滚动展示最近 `180` 个交易日
- 展示状态信息

建议展示字段：

- 日期
- 候选数
- 趋势启动数
- 状态：完成 / 生成中 / 失败 / 缺失

### 9.2 右侧候选和分析

要求：

- 点击任意历史日期时，直接读取该日期数据库结果
- 不依赖“最新缓存”
- 不做日期映射或隐式回退

### 9.3 启动补齐中的 UX

建议：

- 若 180 日历史未补齐，页面显示：
  - 正在补齐
  - 已完成多少天
  - 最近可查看日期

---

## 10. 文件缓存策略任务

需要先做一个明确决策：

### 方案 A：数据库为唯一正式来源

做法：

- 页面/API 全部只读数据库
- 文件仅作调试输出
- 可逐步下线文件回退逻辑

优点：

- 口径最统一
- 理解成本最低

### 方案 B：数据库 + 文件双写保留

做法：

- 生成时同时写 DB 和文件
- 查询只读 DB
- prune 时同步删文件

如果选 B，必须补任务：

- 窗口裁剪时同步删除：
  - `data/candidates/candidates_<date>.json`
  - `data/review/<date>/`

建议：

- 优先采用方案 A 的方向
- 至少把“查询回退到文件”的逻辑收敛掉

---

## 11. 测试任务

### 11.1 单元测试

必须补：

1. `ensure_window` 在窗口不足时补齐缺口
2. `ensure_window` 遇到已完成日期时跳过
3. `build_for_trade_date` 严格只使用 `<= T`
4. `prune_window` 只删窗口外派生结果
5. 重复执行同一天不会生成重复记录

### 11.2 集成测试

必须补：

1. 启动检查触发后台补齐
2. 历史接口返回最近 180 日
3. 每日增量后新增当天并删除最早一天
4. 候选接口与分析接口对同一天返回的数据口径一致

### 11.3 回归测试

重点覆盖：

- Tomorrow Star 页面日期切换
- 左右两侧日期一致性
- 趋势启动数与 `signal_type='trend_start'` 一致
- 候选列表中的开盘价、收盘价、涨跌幅正常显示

---

## 12. 运维与观测任务

### 12.1 日志

窗口维护任务应输出：

- 当前窗口目标
- 缺失日期列表
- 当前处理日期
- 单日耗时
- 成功/失败计数

### 12.2 指标

建议至少记录：

- 窗口完整率
- 单日构建耗时
- 启动补齐总耗时
- prune 删除日期
- 失败日期数

### 12.3 人工修复入口

建议提供：

- 重建某一天
- 重建最近 N 天
- 重新执行 prune

---

## 13. 实施顺序

建议按以下顺序执行：

1. 数据库迁移
   - 唯一约束
   - 复合索引
   - `tomorrow_star_runs` 状态表

2. 后端服务
   - 新增窗口维护 service
   - 单日原子构建
   - prune 逻辑
   - 任务互斥

3. API 收敛
   - dates 只读数据库
   - candidates 只读数据库
   - results 只读数据库
   - 新增 window-status

4. 前端
   - 左侧扩展到 180 日
   - 展示状态
   - 日期切换只读对应日期结果

5. 测试
   - 单元
   - 集成
   - 回归

6. 文件回退清理
   - 视最终决策逐步删除回退逻辑

---

## 14. Todo Checklist

### P0

- [ ] 为 `candidates` 增加唯一约束 `(pick_date, code)`
- [ ] 为 `analysis_results` 增加唯一约束 `(pick_date, code, reviewer)`
- [ ] 为 `candidates` 增加复合索引 `(pick_date, code)`
- [ ] 为 `analysis_results` 增加复合索引 `(pick_date, code)`
- [ ] 为 `analysis_results` 增加复合索引 `(pick_date, signal_type)`
- [ ] 新增 `tomorrow_star_runs` 状态表
- [ ] 新增 `tomorrow_star_window_service`
- [ ] 实现 `ensure_window(window_size=180)`
- [ ] 实现 `build_for_trade_date(trade_date)`
- [ ] 实现 `prune_window(window_size=180)`
- [ ] 确保单日构建严格遵守 `as-of trade date`
- [ ] 确保单日写入事务原子化
- [ ] 实现窗口维护任务互斥
- [ ] 启动后异步触发窗口补齐，不阻塞 API 启动
- [ ] 每日增量成功后串联“生成当天 + prune”

### P1

- [ ] `GET /tomorrow-star/dates` 扩展到最近 `180` 个交易日
- [ ] 历史接口增加状态字段
- [ ] `GET /tomorrow-star/candidates` 收敛为只读数据库
- [ ] `GET /tomorrow-star/results` 收敛为只读数据库
- [ ] 新增 `GET /tomorrow-star/window-status`
- [ ] 前端左侧历史列表支持 `180` 日滚动展示
- [ ] 前端展示“补齐中 / 失败 / 已完成”状态
- [ ] 前端日期点击后严格读取该日期结果

### P2

- [ ] 明确文件缓存是否继续保留
- [ ] 若保留文件缓存，prune 时同步删 `data/candidates` 和 `data/review`
- [ ] 补齐日志与运行指标
- [ ] 提供单日重建 / 最近 N 日重建入口
- [ ] 清理历史文件回退逻辑

