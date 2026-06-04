# 消息板块优化方案

## 目标

将消息板块从“页面请求时实时拉取 Tushare”改为“后台定时增量抓取、Redis 缓存、页面只读缓存”的模式。

核心目标：

1. 降低页面刷新对 Tushare 的请求压力。
2. 所有消息统一按实际发生时间展示，不再按来源分组。
3. 后台按时间窗口增量抓取，并用回看窗口避免延迟入库导致漏抓。
4. 写入 Redis 前做关键词、实体和相似度去重。
5. 消息按事件发生时间设置 24 小时过期。
6. 展示接口全部从 Redis 获取数据。

## 当前现状

当前消息板块主要由以下文件实现：

- `backend/app/api/news_board.py`
- `frontend/src/views/NewsBoard.vue`
- `backend/app/cache.py`

当前后端 `/news-board/items` 请求会同步调用 Tushare `pro.news` 多个来源，然后在接口内归一化、简单按标题去重、构造来源状态并返回。

当前前端展示逻辑包含：

- 来源状态条。
- 左侧 9 个来源分类。
- 列表中展示来源、来源级别。
- 详情中展示来源、来源级别、事件时间、发布时间、抓取时间。

当前 Redis 封装 `RedisCache` 主要是 KV、MGET、MSET 能力。新闻流需要 ZSET、EXPIREAT、分布式锁等操作，建议新增服务内直接使用 Redis client，或扩展 `RedisCache` 的底层操作能力。

## Tushare 接口确认

Tushare `news` 接口支持按 `src/start_date/end_date` 查询。

参数格式：

```text
start_date = "YYYY-MM-DD HH:MM:SS"
end_date   = "YYYY-MM-DD HH:MM:SS"
```

官方说明包含：

- `src` 必填。
- `start_date`、`end_date` 必填。
- 单次最多 1500 条新闻。
- news 接口需要单独权限。
- 可根据时间参数循环提取历史。

结论：可以做秒级时间窗口增量查询，但不能假设严格差量一定完整。新闻源和 Tushare 入库可能存在延迟，所以需要回看窗口。

## 推荐总体架构

新增后端服务：

- `NewsBoardCacheService`
- `NewsBoardUpdateScheduler`

职责划分：

```text
NewsBoardUpdateScheduler
  每 5 分钟触发一次更新
  负责启动、停止、调度、异常日志

NewsBoardCacheService
  负责 Tushare 抓取
  负责新闻归一化
  负责去重
  负责 Redis 写入、读取、清理
```

展示接口：

```text
GET /api/v1/news-board/items?window_hours=24&limit=100
```

接口保留现有路径，内部改为只读 Redis。旧响应结构可以保留，避免前端和其他调用方大范围改动。

## Redis 数据结构

使用当前全局前缀 `stocktrade:`，新闻模块 key 如下：

```text
stocktrade:news:items
  类型：ZSET
  score：event_ts 秒级时间戳
  member：item_id
  用途：按事件时间排序读取 24 小时消息

stocktrade:news:item:{item_id}
  类型：STRING JSON
  TTL：expireat(event_time + 24h)
  用途：保存完整 NewsBoardItem 数据

stocktrade:news:fingerprints
  类型：ZSET
  score：event_ts 秒级时间戳
  member：fingerprint
  用途：保存 24 小时内去重指纹集合

stocktrade:news:fingerprint:{fingerprint}
  类型：STRING
  value：item_id
  TTL：expireat(event_time + 24h)
  用途：通过指纹快速找到已存在消息

stocktrade:news:sync:{src}
  类型：STRING
  value：last_success_end_at ISO 字符串或北京时间字符串
  用途：每个 Tushare 来源独立记录成功抓取水位

stocktrade:news:update_lock
  类型：STRING
  TTL：略大于单轮更新最长耗时，例如 240 秒
  用途：防止多 worker 或多实例重复抓取

stocktrade:news:stats
  类型：STRING JSON
  用途：保存最近一次更新统计，如 fetched、inserted、duplicates、errors、updated_at
```

不建议用 Redis HASH 保存 `dedup_hash -> item_id`，因为 HASH 字段不能单独设置 TTL。使用 ZSET 加单独 fingerprint key 更适合按事件时间清理。

## 消息过期策略

每条消息以事件发生时间为准：

```text
expire_at = event_time + 24h
```

写入时：

1. `SET news:item:{id} json`
2. `EXPIREAT news:item:{id} expire_at`
3. `SET news:fingerprint:{fp} item_id`
4. `EXPIREAT news:fingerprint:{fp} expire_at`
5. `ZADD news:items event_ts item_id`
6. `ZADD news:fingerprints event_ts fingerprint`

ZSET member 不会自动随 item key 过期，所以更新任务和读接口都要做索引清理：

```text
ZREMRANGEBYSCORE news:items -inf now-24h
ZREMRANGEBYSCORE news:fingerprints -inf now-24h
```

读接口如果发现 ZSET 中的 item_id 对应 JSON 已过期，也应跳过；可选地异步清理这些悬空 member。

## 增量抓取与回看窗口

后台每 5 分钟执行一次。

每个来源独立维护水位：

```text
last = GET stocktrade:news:sync:{src}
now = current_time
```

如果没有水位，说明首次启动或 Redis 被清空：

```text
start = now - 24h
end = now
```

如果已有水位：

```text
start = last_success_end_at - overlap_minutes
end = now
```

推荐配置：

```text
interval_seconds = 300
overlap_minutes = 15
```

如果发现漏新闻或 Tushare 入库延迟明显，可将 `overlap_minutes` 调整到 30。

回看窗口的意义：

```text
上次成功抓取到：10:00:00
当前时间：10:05:00
回看窗口：15 分钟

实际查询：09:45:00 - 10:05:00
```

这样即使一条事件时间为 09:58 的新闻在 10:04 才被 Tushare 返回，也能被补抓。重复抓到的旧消息由 Redis 去重处理。

成功更新水位的条件：

- 该来源接口调用成功。
- 返回空数据也算成功，因为表示该时间段暂无新消息。
- 归一化、写 Redis 过程中出现单条异常，不影响整批；但来源级接口异常不更新该来源水位。

## 抓取来源

当前代码配置了 9 个来源：

```text
xq
jinshi
sina
jinrongjie
yicai
10jqka
cls
eastmoney
wallstreetcn
```

需要核对 Tushare 官方 news 来源列表。官方常见来源包含：

```text
sina
wallstreetcn
10jqka
eastmoney
yuncaijing
fenghuang
jinrongjie
cls
yicai
```

如果 `xq`、`jinshi` 当前实际可用，可以保留；如果 Tushare 返回异常，应在来源状态中记录错误并跳过，不应阻断其他来源。

## 去重策略

第一版不建议使用 LLM 实时抽取实体，成本和延迟都不适合 5 分钟更新任务。

第一版也不建议直接引入 `jieba`、`sklearn` 等新依赖。当前工程没有这些依赖，先用规则抽取和 Python 标准库相似度即可落地。

### 归一化

对标题和正文做标准化：

1. 去 HTML。
2. 合并空白。
3. 去常见快讯前缀，如“快讯：”“财联社电”“金十数据”。
4. 去标题末尾来源后缀。
5. 中文统一全角半角。
6. 英文统一小写。
7. 保留数字、金额、百分比、公司名、人名。

### 实体抽取

实体来源：

1. 本地股票列表中的公司名、简称、代码。
2. 当前 `STOCK_HINTS`、`INDUSTRY_HINTS` 规则中的关键词。
3. 固定国家、地区、机构词典。
4. 高频人物词典，如特朗普、马斯克、黄仁勋、鲍威尔等。
5. 从标题中抽取的核心名词短语。

实体类型：

```text
companies
people
subjects
locations
countries
industries
numbers
```

### 指纹生成

建议生成两个指纹：

```text
strict_fingerprint
  来源于 normalized_title
  用于标题几乎完全一致的重复消息

event_fingerprint
  来源于 companies + people + subjects + locations + countries + event_time_bucket
  用于跨来源同一事件去重
```

时间分桶建议：

```text
event_time_bucket = floor(event_ts / 1800)
```

即 30 分钟一个桶。避免同一公司不同时间发布的不同事件被误杀。

### 相似度判断

同一批次或 Redis 最近 24 小时内存在候选时，做二次相似度判断。

候选筛选：

1. strict fingerprint 命中，直接判重复。
2. event fingerprint 命中，再比较标题和实体。
3. 同一公司、同一人物、同一地点、同一 30 分钟桶内的消息作为候选。

相似度计算第一版可用标准库：

```text
difflib.SequenceMatcher
token Jaccard
```

建议阈值：

```text
标题相似度 >= 0.86
  判重复

实体集合重合度 >= 0.70 且标题相似度 >= 0.72
  判重复

只有来源相同、标题完全相同
  判重复
```

不能只按公司名去重。例如同一家公司 30 分钟内可能有“涨停”“澄清”“减持”“订单”多条不同事件。

### 重复消息处理

发现重复时：

1. 不新增新 item。
2. 可选：更新已有 item 的 `duplicate_sources`、`duplicate_count`、`last_seen_at`。
3. 页面不展示来源，但后台保留来源信息用于排障。

第一版可以只统计 duplicate_count，不展示重复来源。

## 后台调度

在 `backend/app/main.py` lifespan 中启动。

建议行为：

1. 测试模式不启动。
2. 支持环境变量禁用，例如 `DISABLE_NEWS_BOARD_SCHEDULER=1`。
3. 使用 Redis lock 或现有 runtime lock，避免多 worker 重复执行。
4. 启动后先延迟数秒，避免和其他预热任务争抢资源。
5. 首次 Redis 无数据时拉取最近 24 小时。
6. 之后每 5 分钟增量更新。

伪代码：

```python
class NewsBoardUpdateScheduler:
    def start(self) -> None:
        self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        await asyncio.sleep(startup_delay)
        while not stopped:
            await asyncio.to_thread(service.update_once)
            await wait(interval_seconds)
```

## API 设计

保留现有接口：

```text
GET /api/v1/news-board/items?window_hours=24&limit=100
```

改动：

1. 不再实时调用 Tushare。
2. 从 Redis `news:items` 读取最近 `window_hours` 数据。
3. 按 `event_time` 倒序返回。
4. `sources` 可以返回空数组或只返回缓存状态，不再给前端展示各来源。
5. `duplicate_count` 返回最近一次更新统计中的去重数量。
6. 如果 Redis 无数据，返回空列表和明确 message，不在请求链路上触发 Tushare 抓取。

可新增管理接口，仅管理员可用：

```text
POST /api/v1/news-board/refresh
GET  /api/v1/news-board/status
```

用途：

- 手动触发一次后台更新。
- 查看最近一次更新时间、抓取窗口、错误来源、插入数量、去重数量。

## 前端展示调整

页面目标：统一时间线。

需要移除：

1. 来源状态条。
2. 左侧 9 个来源分类。
3. 顶部“几个来源”统计。
4. 列表 footer 中的 `item.source`、`sourceLevel`。
5. 详情中的来源、来源级别。
6. “按 Tushare news 来源分组”文案。

建议保留：

1. 搜索框。
2. 刷新按钮。
3. 有效消息数。
4. 去重条数。
5. 最后更新时间。
6. 事件时间、抓取时间、延迟。
7. 地区、关联股票数。
8. AI 分析面板。

分类筛选可以从“来源分类”改为“事件类型分类”：

```text
全部
政策
市场异动
海外
人物
天气
产业
公司
```

第一版也可以先去掉分类，只保留搜索和时间线。

## 配置项

建议新增配置：

```text
NEWS_BOARD_UPDATE_INTERVAL_SECONDS=300
NEWS_BOARD_OVERLAP_MINUTES=15
NEWS_BOARD_WINDOW_HOURS=24
NEWS_BOARD_FETCH_LIMIT_PER_SOURCE=1500
NEWS_BOARD_LOCK_TTL_SECONDS=240
DISABLE_NEWS_BOARD_SCHEDULER=0
```

如新增配置，需要同步更新：

- `.env.example`
- `README.md`
- 部署说明

## 测试计划

后端单元测试：

1. 时间窗口计算：
   - 无 sync 水位时取最近 24h。
   - 有 sync 水位时取 `last - overlap` 到 `now`。
2. TTL 计算：
   - `expire_at = event_time + 24h`。
   - 过期事件不写入或写入后立即不可见。
3. 去重：
   - 标题完全一致判重复。
   - 同实体、同时间桶、标题高度相似判重复。
   - 同公司不同事件不误杀。
4. Redis 读取：
   - ZSET 按事件时间倒序。
   - item key 缺失时跳过。
   - 只返回 window_hours 内数据。
5. 调度：
   - 接口异常不更新该 source 水位。
   - 空数据成功更新水位。
   - lock 存在时跳过。

前端测试：

1. 无来源侧栏和来源状态条。
2. 消息按事件时间倒序展示。
3. 搜索可过滤标题、摘要、地区、关联股票。
4. Redis 返回空列表时显示空状态。
5. 手动刷新不触发来源展示回退。

推荐验证命令：

```bash
.venv/bin/python -m pytest backend/tests/test_api/test_news_board_api.py
.venv/bin/python -m pytest backend/tests/test_services/test_news_board_cache_service.py
cd frontend && npm run test
cd frontend && npm run build
```

具体测试文件可在实现时按现有测试结构新增。

## 风险与处理

### Tushare 延迟导致漏数据

处理：使用 15-30 分钟回看窗口，并依赖 Redis 去重消化重复抓取。

### 多 worker 重复抓取

处理：使用 Redis lock 或现有 runtime lock。只有拿到锁的 worker 启动调度器。

### Redis 不可用

当前 `RedisCache` 支持内存降级，但新闻缓存依赖 ZSET 和跨进程共享。消息板块建议 Redis 不可用时返回空数据和提示，不建议后台调度降级到进程内存，否则多 worker 状态不一致。

### 去重误杀

处理：不要只按公司名或人物去重，必须结合标题相似度、实体集合、时间桶。第一版阈值保守，宁可少去重，不要误删真实不同事件。

### ZSET 索引残留

处理：每轮更新和读接口都执行 24 小时窗口清理，并在读取时跳过缺失 item。

### 单次 1500 条上限

处理：通常 5 分钟加 15 分钟回看不会超过上限。如果首次 24 小时拉取超过 1500，应按更小时间片循环抓取，例如 1 小时一段。

## 具体任务拆解

下面任务按建议实施顺序排列。每个任务都应保持小范围提交，完成后运行对应测试。

### 任务 1：新增新闻缓存配置

目标：为消息板块后台任务提供可配置参数。

建议修改文件：

- `backend/app/config.py`
- `.env.example`
- `README.md` 或部署说明文档

新增配置：

```text
NEWS_BOARD_UPDATE_INTERVAL_SECONDS=300
NEWS_BOARD_OVERLAP_MINUTES=15
NEWS_BOARD_WINDOW_HOURS=24
NEWS_BOARD_FETCH_LIMIT_PER_SOURCE=1500
NEWS_BOARD_LOCK_TTL_SECONDS=240
DISABLE_NEWS_BOARD_SCHEDULER=0
```

验收标准：

1. 后端可通过 `settings` 读取上述配置。
2. 默认值与文档一致。
3. 未配置环境变量时系统可正常启动。

### 任务 2：新增 Redis 新闻缓存底层访问能力

目标：支持新闻模块需要的 ZSET、EXPIREAT、锁、批量读取能力。

建议修改文件：

- `backend/app/cache.py`
- 或新增 `backend/app/services/news_board_cache_service.py` 内部直接创建 Redis client

要求：

1. 能执行 `zadd`、`zrangebyscore`、`zrevrangebyscore`、`zremrangebyscore`。
2. 能执行 `expireat`。
3. 能执行 `set nx ex` 形式的锁。
4. Redis 不可用时，新闻模块应明确返回不可用状态，不建议降级到进程内存。

验收标准：

1. 不影响现有 `RedisCache` 的 KV 行为。
2. Redis 不可用时不会导致应用启动失败。
3. 新闻接口可识别 Redis 不可用并返回空数据和提示。

### 任务 3：新增 `NewsBoardCacheService` 骨架

目标：把新闻缓存逻辑从 API 文件中拆到服务层。

建议新增文件：

- `backend/app/services/news_board_cache_service.py`

建议类和方法：

```python
class NewsBoardCacheService:
    def get_items(self, *, window_hours: int, limit: int) -> NewsBoardItemsResponse: ...
    def update_once(self, *, now: datetime | None = None) -> dict[str, Any]: ...
    def cleanup_expired_indexes(self, *, now: datetime | None = None) -> int: ...
    def get_status(self) -> dict[str, Any]: ...
```

验收标准：

1. 服务可实例化。
2. Redis 无数据时 `get_items` 返回空列表。
3. `cleanup_expired_indexes` 可清理 24 小时前 ZSET member。
4. 不修改前端，不改变 API 行为。

### 任务 4：迁移新闻归一化逻辑

目标：把 `backend/app/api/news_board.py` 中现有新闻规范化逻辑迁移到服务层，供缓存写入复用。

建议修改文件：

- `backend/app/api/news_board.py`
- `backend/app/services/news_board_cache_service.py`

迁移内容：

1. `_normalize_news_items`
2. `_title_from_content`
3. `_parse_datetime`
4. `_parse_china_datetime`
5. `_infer_category`
6. `_infer_impact`
7. `_infer_region`
8. `_infer_related_stocks`
9. `_infer_related_industries`
10. `_stable_id`

验收标准：

1. 迁移后现有 `/news-board/items` 响应字段不破坏。
2. 现有分析接口 `/news-board/analyze` 可继续使用股票和行业推断逻辑。
3. 如果函数仍需被 API 和服务共用，放到服务或独立 helper，避免复制两份。

### 任务 5：实现时间窗口计算

目标：实现首次 24 小时拉取和后续 `last - overlap` 增量拉取。

建议新增方法：

```python
def resolve_fetch_window(src: str, now: datetime) -> tuple[datetime, datetime]: ...
def update_sync_watermark(src: str, end: datetime) -> None: ...
```

规则：

1. 无 `news:sync:{src}` 时，`start = now - NEWS_BOARD_WINDOW_HOURS`。
2. 有水位时，`start = last_success_end_at - NEWS_BOARD_OVERLAP_MINUTES`。
3. `end = now`。
4. `start` 不应早于 `now - NEWS_BOARD_WINDOW_HOURS` 太多，避免异常水位导致大范围抓取。

验收标准：

1. 单元测试覆盖无水位、有水位、水位异常。
2. 空数据但接口成功时更新水位。
3. 来源接口异常时不更新该来源水位。

### 任务 6：实现 Tushare 增量抓取

目标：后台按来源抓取指定时间窗口内新闻。

建议方法：

```python
def fetch_tushare_source(src: str, start_dt: datetime, end_dt: datetime) -> list[dict[str, Any]]: ...
```

要求：

1. 使用北京时间格式 `YYYY-MM-DD HH:MM:SS`。
2. 单来源每次最多读取 `NEWS_BOARD_FETCH_LIMIT_PER_SOURCE`。
3. 单个来源异常只记录错误，不阻断其他来源。
4. 如果首次 24 小时数据超过 1500，后续可再实现按小时切片；第一版至少要记录超限风险。

验收标准：

1. mock Tushare 返回 DataFrame 时可转成 raw item。
2. 空 DataFrame 返回空列表。
3. 异常返回错误统计且不更新水位。

### 任务 7：实现去重指纹和相似度判断

目标：写 Redis 前判断是否为重复事件。

建议方法：

```python
def normalize_news_text(title: str, summary: str) -> str: ...
def extract_news_entities(title: str, summary: str) -> dict[str, list[str]]: ...
def build_news_fingerprints(item: NewsBoardItem) -> dict[str, str]: ...
def is_duplicate(item: NewsBoardItem) -> tuple[bool, str | None]: ...
```

第一版实现规则：

1. 标题标准化后完全一致，判重复。
2. 同实体集合、同 30 分钟桶、标题相似度达到阈值，判重复。
3. 同公司不同动作词不能直接判重复。
4. 不引入 LLM。
5. 不强制引入 `jieba`、`sklearn`。

验收标准：

1. 标题完全相同跨来源只写入一次。
2. “英伟达大涨”和“英伟达澄清传闻”不应互相去重。
3. 相似标题可去重。
4. 单元测试覆盖误杀边界。

### 任务 8：实现 Redis 写入和读取

目标：将归一化后的消息写入 Redis，并从 Redis 读取统一时间线。

写入要求：

1. `news:item:{item_id}` 写 JSON。
2. `EXPIREAT = event_time + 24h`。
3. `news:items` ZSET score 使用 `event_ts`。
4. `news:fingerprints` ZSET score 使用 `event_ts`。
5. `news:fingerprint:{fingerprint}` 保存 item_id 并设置同样过期点。

读取要求：

1. 读取 `now - window_hours` 到 `now`。
2. 按事件时间倒序。
3. 批量 MGET item JSON。
4. 跳过已经过期或缺失的 item。
5. 返回数量受 `limit` 限制。

验收标准：

1. 写入后可按时间倒序读出。
2. 过期 item 不展示。
3. ZSET 残留 member 不导致接口报错。

### 任务 9：实现后台调度器

目标：后端启动后每 5 分钟自动更新新闻缓存。

建议新增文件：

- `backend/app/services/news_board_update_scheduler.py`

建议类：

```python
class NewsBoardUpdateScheduler:
    def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def run_once(self) -> dict[str, Any]: ...
```

要求：

1. 接入 `backend/app/main.py` lifespan。
2. 测试模式不启动。
3. `DISABLE_NEWS_BOARD_SCHEDULER=1` 时不启动。
4. 使用 Redis lock 或现有 runtime lock 防止多 worker 重复执行。
5. shutdown 时取消后台 task。

验收标准：

1. 应用启动时调度器正常启动。
2. 应用关闭时调度器正常停止。
3. 多 worker 只有一个执行更新。
4. 单轮异常不会终止后续调度。

### 任务 10：改造 `/news-board/items`

目标：页面读取接口全部从 Redis 获取，不再在请求链路实时调用 Tushare。

建议修改文件：

- `backend/app/api/news_board.py`

改动：

1. `get_news_board_items` 调用 `NewsBoardCacheService.get_items`。
2. 不再调用 `_fetch_tushare_news_board_items`。
3. Redis 无数据时返回空列表和明确 message。
4. 保留 `NewsBoardItemsResponse` 结构兼容前端。
5. `sources` 可返回空数组或缓存状态，不再用于页面展示。

验收标准：

1. 页面刷新不会触发 Tushare 调用。
2. Redis 有数据时正常返回。
3. Redis 无数据时接口不报错。

### 任务 11：新增管理接口

目标：便于人工验证和排障。

建议修改文件：

- `backend/app/api/news_board.py`

新增接口：

```text
GET  /api/v1/news-board/status
POST /api/v1/news-board/refresh
```

要求：

1. 仅管理员可调用手动 refresh。
2. status 返回最近一次更新统计、各来源水位、错误来源、Redis 可用状态。
3. refresh 触发一次 `update_once`，但要尊重 lock。

验收标准：

1. 普通用户不能手动 refresh。
2. status 可用于判断后台是否正常工作。
3. refresh 不会并发执行多轮抓取。

### 任务 12：改造前端统一时间线

目标：前端不再展示来源，不再按来源分组。

建议修改文件：

- `frontend/src/views/NewsBoard.vue`

移除：

1. 来源状态条。
2. 左侧来源分类。
3. 顶部“几个来源”统计。
4. 列表中的来源和来源级别。
5. 详情中的来源和来源级别。
6. “按 Tushare news 来源分组”文案。

保留或调整：

1. 搜索框。
2. 刷新按钮。
3. 有效消息数。
4. 去重条数。
5. 最后更新时间。
6. 事件时间、发布时间、抓取时间、延迟。
7. 地区、关联股票数。
8. AI 分析面板。

验收标准：

1. 所有消息按 `eventTime || publishedAt` 倒序。
2. 页面没有来源侧栏、来源条、来源文字。
3. 搜索仍可用。
4. 空状态和加载状态正常。

### 任务 13：补后端测试

目标：覆盖核心缓存和增量逻辑。

建议新增或修改：

- `backend/tests/test_services/test_news_board_cache_service.py`
- `backend/tests/test_api/test_news_board_api.py`

测试点：

1. 时间窗口计算。
2. Redis 写入和读取。
3. TTL 过期点。
4. 指纹去重。
5. 相似度去重。
6. 来源异常不更新水位。
7. 空数据成功更新水位。
8. `/news-board/items` 不调用 Tushare。

验收命令：

```bash
.venv/bin/python -m pytest backend/tests/test_services/test_news_board_cache_service.py
.venv/bin/python -m pytest backend/tests/test_api/test_news_board_api.py
```

### 任务 14：补前端测试和构建验证

目标：确认页面改造后可正常构建和基础交互可用。

建议修改：

- `frontend/tests/`
- 或沿用现有前端测试结构

测试点：

1. 页面不渲染来源状态条。
2. 页面不渲染来源分类按钮。
3. 消息按时间排序。
4. 搜索过滤可用。
5. 空数据展示空状态。

验收命令：

```bash
cd frontend && npm run test
cd frontend && npm run build
```

### 任务 15：联调验证

目标：确认完整链路符合设计。

步骤：

1. 启动 Redis、后端、前端。
2. 调用 `POST /api/v1/news-board/refresh` 手动触发一次更新。
3. 调用 `GET /api/v1/news-board/status` 查看抓取统计。
4. 调用 `GET /api/v1/news-board/items?window_hours=24&limit=100` 查看 Redis 返回。
5. 刷新前端消息板块，确认页面只展示统一时间线。
6. 观察 5 分钟后后台是否自动增量更新。

验收标准：

1. 页面刷新不产生 Tushare 调用。
2. 后台 5 分钟任务产生 Tushare 调用。
3. 重复新闻不会重复展示。
4. Redis 里 24 小时前消息会被清理。
5. Redis 不可用时接口返回提示，不导致应用崩溃。

## 实施优先级

优先级 P0：

1. 任务 1：新增新闻缓存配置。
2. 任务 3：新增 `NewsBoardCacheService` 骨架。
3. 任务 5：实现时间窗口计算。
4. 任务 6：实现 Tushare 增量抓取。
5. 任务 8：实现 Redis 写入和读取。
6. 任务 10：改造 `/news-board/items`。

优先级 P1：

1. 任务 7：实现去重指纹和相似度判断。
2. 任务 9：实现后台调度器。
3. 任务 12：改造前端统一时间线。
4. 任务 13：补后端测试。

优先级 P2：

1. 任务 11：新增管理接口。
2. 任务 14：补前端测试和构建验证。
3. 任务 15：联调验证。

第一版上线后观察：

1. 每轮 Tushare 调用次数。
2. 每轮 fetched、inserted、duplicate 数量。
3. 是否存在明显漏新闻。
4. 是否存在误去重。
5. Redis key 数量和内存占用。
