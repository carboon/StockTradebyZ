# News Event Analysis Agent Development Plan

## 1. 目标

建设一个面向消息板块的事件驱动型股票市场分析 Agent。

用户在消息板块右侧选择一条新闻后，点击“详情分析”，系统自动完成：

- 判断新闻是否适合做板块/个股分析
- 获取新闻事件详情、原文和背景证据
- 区分国内事件和海外事件
- 国内事件直接映射 A 股板块和标的
- 海外科技/财经/产业事件映射到国内产业链、板块和股票
- 对复杂地缘、外交、泛宏观事件执行停止机制
- 查询本地行情数据，判断相关标的是否已出现利好兑现或提前异动
- 必要时通过 `web_search` 工具补证，最多 5 轮
- 调用 LLM 输出结构化市场影响分析

Agent 的定位是“事件研究助手”，不是交易建议系统。它输出市场影响、证据、传导路径、兑现状态和不确定性，不输出买入、卖出、仓位、目标价等投资指令。

## 2. 设计原则

1. 模块化：Agent 只编排流程，检索、证据、行情、产业链、LLM 都独立封装。
2. 可替换：`web_search` 工具不绑定 SearXNG，后续可切换 Bocha、Tavily 或混合 provider。
3. 可停止：不适合分析的事件必须停止，不强行输出板块和股票。
4. 证据优先：LLM 只能基于输入证据分析，不允许编造股票代码、供应链关系和行情数据。
5. 国内/海外分流：只有海外科技、财经、产业事件才走海外到 A 股映射；国内事件直接做国内板块和标的分析。
6. 行情校验程序化：是否已兑现由本地行情数据计算，再交给 LLM 解释。
7. 多轮有限：补证最多 5 轮，每轮 query 和结果数量受限。
8. 输出结构化：后端返回 JSON，前端按模块渲染，不依赖 LLM 自由作文。

## 3. 总体架构

```text
frontend/NewsBoard.vue
  |
  | POST /api/v1/news-board/analyze-detail
  v
NewsEventAnalysisAgent
  |
  +-- EventClassifier
  +-- SearchOrchestrator
  |     +-- web_search tool
  |           +-- SearXNGSearchProvider
  |           +-- BochaSearchProvider
  |           +-- TavilySearchProvider
  +-- ArticleExtractor
  +-- EvidenceRanker
  +-- EntityResolver
  +-- IndustryChainMapper
  +-- MarketRealizationAnalyzer
  +-- LLMAnalysisService
  +-- AnalysisCache
```

推荐目录：

```text
backend/app/agents/news_event/
  __init__.py
  agent.py
  schemas.py
  prompts.py
  event_classifier.py
  search_orchestrator.py
  article_extractor.py
  evidence_ranker.py
  entity_resolver.py
  industry_chain_mapper.py
  market_realization_analyzer.py

backend/app/services/search/
  __init__.py
  base.py
  searxng_search_service.py
  bocha_search_service.py
  tavily_search_service.py

data/knowledge/
  industry_chains.json
```

## 4. 运行流程

### 4.1 基础流程

```text
1. 用户选择新闻并点击详情分析
2. 后端创建分析任务
3. EventClassifier 判断事件类型、市场范围和可分析性
4. 如果不可分析，直接返回 stopped
5. SearchOrchestrator 生成初始检索 query
6. web_search 执行检索
7. ArticleExtractor 抓取正文和发布时间
8. EvidenceRanker 给证据打分
9. EntityResolver 抽取实体并映射本地股票
10. IndustryChainMapper 生成产业链、板块和候选股票
11. MarketRealizationAnalyzer 查询本地行情并判断是否已兑现
12. LLMAnalysisService 判断证据是否足够
13. 如果不足，生成补充 query，最多循环 5 轮
14. 输出 ready / stopped / need_more_data_final
```

### 4.2 Agent 状态

每轮只能进入以下状态之一：

```text
ready
  证据足够，输出结构化分析。

need_more_data
  当前证据不足，生成补充检索 query，继续下一轮。

stopped
  事件不适合输出具体板块和股票，停止分析。

failed
  系统异常，例如检索服务不可用、LLM 调用失败、行情数据查询异常。
```

### 4.3 停止条件

以下情况应返回 `stopped`：

- 宽泛外交、访问、会晤、国际关系表态，缺少明确产业、政策、订单、价格、供需或监管变量
- 影响范围过宽，只能得出“风险偏好变化”等泛结论
- 只有低质量传闻，缺少可信来源
- 检索证据互相矛盾，无法确认事件事实
- 只能通过概念联想硬凑股票
- 事件无法映射到具体板块或标的，且缺少后续可验证指标

停止输出示例：

```json
{
  "status": "stopped",
  "event_type": "geopolitical_broad",
  "reason": "该事件属于宽泛外交访问，缺少明确产业、政策、订单、价格、供需或监管变量，不适合输出具体板块和个股。",
  "event_summary": "...",
  "watch_points": [
    "等待是否出现具体政策文件",
    "观察是否涉及关税、出口管制、行业补贴、订单变化等可交易变量"
  ]
}
```

## 5. 事件分类模块

### 5.1 分类枚举

```text
domestic_company
domestic_industry
overseas_company
overseas_industry
macro_policy
geopolitical_broad
market_movement
unverifiable_rumor
not_analyzable
```

### 5.2 分类输出

```json
{
  "event_type": "overseas_industry",
  "market_scope": "overseas",
  "analyzable": true,
  "mapping_required": true,
  "reason": "新闻主体为海外科技产业事件，存在通过产业链映射到 A 股的可能。"
}
```

### 5.3 分流规则

国内公司、国内产业、国内政策：

```text
直接分析国内相关板块、股票和行情兑现状态。
```

海外公司、海外产业、海外科技、海外财经：

```text
先确认事件事实，再通过产业链映射到国内板块和 A 股标的。
```

宽泛地缘、外交、泛宏观：

```text
只有存在明确行业变量时才继续；否则 stopped。
```

传闻类：

```text
优先补证；补证后仍缺可信来源则 stopped。
```

## 6. web_search 工具

### 6.1 工具定位

`web_search` 是 Agent 的标准工具，不直接暴露 SearXNG、Bocha、Tavily 的差异。

Agent 只调用：

```python
web_search(
    query: str,
    *,
    freshness: str = "day",
    max_results: int = 8,
    categories: list[str] | None = None,
    language: str = "zh-CN",
) -> list[SearchResult]
```

### 6.2 标准返回结构

```json
{
  "title": "...",
  "url": "...",
  "summary": "...",
  "source": "...",
  "published_at": "...",
  "provider": "searxng",
  "score": 0.82
}
```

### 6.3 Provider 策略

支持配置：

```text
SEARCH_PROVIDER=auto|searxng|bocha|tavily
```

策略：

- `searxng`：默认自托管检索，低成本、适合广泛检索
- `bocha`：商业搜索，可作为中文财经补充
- `tavily`：商业搜索，可作为网页语义搜索补充
- `auto`：优先 SearXNG，失败或结果不足时 fallback 到商业 provider

### 6.4 SearXNG 接入

配置项：

```env
SEARCH_PROVIDER=searxng
SEARXNG_BASE_URL=http://searxng:8080
SEARCH_TIMEOUT_SECONDS=12
SEARCH_MAX_ROUNDS=5
SEARCH_MAX_QUERIES_PER_ROUND=5
SEARCH_MAX_RESULTS_PER_QUERY=8
```

调用形式：

```text
GET {SEARXNG_BASE_URL}/search
  ?q={query}
  &format=json
  &language=zh-CN
  &categories=news,general
  &time_range=day
```

SearXNG 配置必须启用 JSON 输出：

```yaml
search:
  formats:
    - html
    - json
```

Docker 服务建议：

```yaml
searxng:
  image: searxng/searxng:latest
  container_name: stocktrade-searxng
  ports:
    - "${SEARXNG_PORT:-8081}:8080"
  volumes:
    - searxng_data:/etc/searxng
  environment:
    - SEARXNG_BASE_URL=http://localhost:${SEARXNG_PORT:-8081}/
  networks:
    - stocktrade-net
```

### 6.5 检索 query 设计

初始 query 应覆盖：

- 新闻事件原文
- 事件发布时间
- 事件详情
- 相关公司或机构
- 产业影响
- A 股映射
- 最近行情异动

示例：

```text
{title} 原文 事件详情
{核心实体} {关键词} 影响 哪些行业
{海外公司} 产业链 A股 相关公司
{关键词} A股 板块 受益 股票
{股票或板块} 最近 涨停 异动 原因
```

## 7. 证据模块

### 7.1 ArticleExtractor

职责：

- 根据 URL 抓取网页
- 提取正文、标题、发布时间、站点名称
- 清洗广告、导航、脚本内容
- 对失败 URL 做错误记录

第一期可以只使用搜索结果摘要；第二期再补全文抽取。

### 7.2 EvidenceRanker

证据等级：

```text
A: 交易所、公司公告、监管部门、政府官网
B: 财联社、证券时报、上证报、主流财经媒体、权威行业媒体
C: 门户财经、普通行业媒体、新闻转载
D: 自媒体、论坛、股吧、来源不明
```

约束：

- D 类证据不能单独支撑强结论
- 多个转载同源新闻不能当作多条独立证据
- 证据发布时间必须和事件时间一起传给 LLM
- 搜索结果只作为线索，原文和高质量来源优先

证据结构：

```json
{
  "id": "ev_001",
  "title": "...",
  "url": "...",
  "source": "...",
  "source_level": "B",
  "published_at": "...",
  "summary": "...",
  "key_points": [],
  "provider": "searxng",
  "confidence": 0.74
}
```

## 8. 实体识别与股票消歧

### 8.1 EntityResolver

职责：

- 抽取公司、股票、行业、技术、政策、商品、地区等实体
- 区分海外公司和 A 股标的
- 使用本地股票库确认股票代码和名称
- 处理多义词

实体类型：

```text
company_entity
stock_entity
industry_entity
technology_entity
policy_entity
commodity_entity
country_region_entity
```

### 8.2 消歧规则

示例：

```text
苹果
  上下文为 Apple、iPhone、Mac、供应链时 -> 海外公司 Apple
  上下文为农产品、水果价格时 -> 农业商品

英伟达
  海外公司实体，不是 A 股股票

京东方
  查询本地股票库 -> 000725.SZ

寒武纪
  查询本地股票库 -> A 股公司
```

硬规则：

- LLM 不得直接生成最终股票代码
- 最终股票代码必须由本地股票库或可信映射表确认
- 未确认代码的标的只能作为 `unresolved_company` 展示

## 9. 产业链映射模块

### 9.1 IndustryChainMapper

职责：

- 根据事件实体、关键词、证据，匹配产业链节点
- 区分直接受益、间接受益、潜在受压
- 输出板块、上下游和候选 A 股标的

### 9.2 知识库结构

建议维护：

```text
data/knowledge/industry_chains.json
```

示例：

```json
{
  "英伟达": {
    "chains": [
      {
        "sector": "AI算力",
        "nodes": ["GPU", "服务器", "PCB", "光模块", "液冷", "存储"],
        "a_share_mapping": [
          {
            "code": "300308.SZ",
            "name": "中际旭创",
            "relation": "光模块",
            "strength": "strong",
            "reason": "处于 AI 高速互联光模块链条"
          }
        ]
      }
    ]
  }
}
```

映射强度：

```text
strong
  明确业务、公告、供应链或产品关联。

medium
  同产业链受益，但需要进一步验证订单、价格或需求传导。

weak
  概念相关或市场联想，不能作为强结论。
```

## 10. 行情兑现判断模块

### 10.1 MarketRealizationAnalyzer

职责：

- 查询本地股票行情数据
- 计算候选股票近期表现
- 判断消息前是否已有异动
- 判断利好是否已经短线兑现
- 为 LLM 提供结构化行情证据

### 10.2 推荐指标

```text
change_1d
change_3d
change_5d
change_20d
limit_up
volume_ratio
high_open_low_close
moved_before_news
sector_spread_count
realization_status
```

### 10.3 兑现状态

```text
not_realized
partially_realized
likely_priced_in
moved_before_news
insufficient_market_data
```

输出示例：

```json
{
  "code": "000725.SZ",
  "name": "京东方A",
  "change_1d": 9.98,
  "change_3d": 15.2,
  "change_5d": 18.7,
  "change_20d": 31.4,
  "limit_up": true,
  "volume_ratio": 2.6,
  "moved_before_news": true,
  "realization_status": "likely_priced_in",
  "reason": "消息发布前股价已涨停，短线利好可能已提前反应。"
}
```

## 11. 多轮补证机制

### 11.1 轮次限制

默认：

```text
最少 1 轮
最多 5 轮
每轮最多 5 条 query
每条 query 最多 8 条搜索结果
```

### 11.2 LLM 轮次输出

LLM 每轮只能返回：

```json
{
  "status": "need_more_data",
  "reason": "缺少原文发布时间和供应链映射证据。",
  "search_queries": [
    "...",
    "..."
  ]
}
```

或：

```json
{
  "status": "ready"
}
```

或：

```json
{
  "status": "stopped",
  "reason": "事件过于宽泛，缺少明确产业变量。"
}
```

### 11.3 去噪策略

- query 去重
- URL 去重
- 同源转载去重
- 低质量来源降权
- 搜索结果数量上限
- 超时和失败 provider 不阻塞整体流程

## 12. LLM 提示词

### 12.1 系统提示词

```text
你是一名严谨的 A 股事件驱动市场分析师。

你的任务是基于新闻事件、检索证据、产业链映射和本地行情数据，判断该事件对 A 股板块和股票的潜在影响。

硬性规则：
1. 不得编造未提供的数据、股票代码、供应链关系和行情表现。
2. 必须区分事实、推断和不确定项。
3. 不能默认所有新闻都是海外新闻。
4. 海外事件只有存在明确产业链传导路径时，才映射到 A 股。
5. 国内事件直接分析国内板块和股票，不执行海外映射。
6. 宽泛地缘、外交访问、宏观情绪类事件，如缺少明确产业、政策、订单、价格、供需、监管变量，必须停止输出具体股票。
7. 判断是否已兑现时，必须使用输入的行情数据。
8. 不输出买入、卖出、目标价、仓位建议。
9. 低质量来源不能支撑强结论。
10. 证据不足时输出需要补充的数据，不要强行下结论。
```

### 12.2 最终分析要求

LLM 输出必须覆盖：

- 事件摘要
- 核心事实
- 影响路径
- 直接影响板块
- 间接影响板块
- 相关股票
- 已兑现判断
- 上下游扩散
- 风险点
- 后续观察
- 证据列表
- 置信度

## 13. API 设计

### 13.1 创建详情分析

```text
POST /api/v1/news-board/analyze-detail
```

请求：

```json
{
  "news_id": "...",
  "title": "...",
  "summary": "...",
  "category": "...",
  "source": "...",
  "published_at": "...",
  "event_time": "...",
  "url": "..."
}
```

响应可以先同步返回，也可以返回任务 ID。

第一期建议同步返回，第二期改为后台任务：

```json
{
  "task_id": "nea_...",
  "status": "running"
}
```

### 13.2 查询分析结果

```text
GET /api/v1/news-board/analyze-detail/{task_id}
```

响应：

```json
{
  "status": "ready",
  "event_type": "overseas_industry",
  "confidence": 0.76,
  "event_summary": "...",
  "core_facts": [],
  "impact_path": [],
  "direct_sectors": [],
  "indirect_sectors": [],
  "related_stocks": [],
  "market_realization": [],
  "upstream_downstream": [],
  "risks": [],
  "watch_points": [],
  "evidence": [],
  "rounds": []
}
```

### 13.3 前端状态

前端至少展示：

```text
idle
running
ready
stopped
failed
```

运行中展示：

- 当前步骤
- 当前轮次
- 已获取证据数量
- 当前检索 query

## 14. 数据与缓存

### 14.1 Redis 缓存

建议 key：

```text
stocktrade:news_agent:analysis:{analysis_id}
stocktrade:news_agent:evidence:{evidence_hash}
stocktrade:news_agent:search:{query_hash}
```

TTL：

```text
分析结果：24h - 7d
搜索结果：6h - 24h
证据正文：24h - 7d
```

### 14.2 持久化

第一期可只用 Redis。后续如果要历史复盘，可以新增数据库表：

```text
news_event_analysis_runs
news_event_analysis_evidence
news_event_analysis_related_stocks
```

## 15. 配置项

建议新增：

```env
NEWS_AGENT_ENABLED=true
NEWS_AGENT_MAX_ROUNDS=5
NEWS_AGENT_MAX_QUERIES_PER_ROUND=5
NEWS_AGENT_MAX_RESULTS_PER_QUERY=8
NEWS_AGENT_SEARCH_TIMEOUT_SECONDS=12
NEWS_AGENT_ARTICLE_FETCH_TIMEOUT_SECONDS=10
NEWS_AGENT_CACHE_TTL_SECONDS=86400

SEARCH_PROVIDER=auto
SEARXNG_BASE_URL=http://searxng:8080
SEARXNG_PORT=8081

NEWS_AGENT_MIN_EVIDENCE_LEVEL=B
NEWS_AGENT_ALLOW_LOW_QUALITY_EVIDENCE=false
```

## 16. 开发步骤

### 阶段一：基础 Agent 骨架

目标：打通从消息板块到结构化结果的最小闭环。

任务：

1. 新增 `backend/app/agents/news_event/` 目录和 schema。
2. 新增 `NewsEventAnalysisAgent` 编排类。
3. 新增 `EventClassifier`，支持事件分类和停止机制。
4. 新增 `/api/v1/news-board/analyze-detail` 接口。
5. 前端右侧新增“详情分析”按钮和状态展示。
6. 先用现有规则和 LLM 一次性输出结果，不做多轮补证。

验收：

- 国内事件不走海外映射。
- 海外产业事件走 A 股映射。
- 宽泛地缘事件返回 `stopped`。
- 返回结构化 JSON。

### 阶段二：web_search 工具与 SearXNG

目标：实现可替换的搜索工具。

任务：

1. 新增 `backend/app/services/search/base.py`。
2. 新增 `SearXNGSearchProvider`。
3. 将 Bocha/Tavily 封装到统一 provider 接口。
4. 新增 `SearchOrchestrator`。
5. Docker Compose 增加 SearXNG 服务。
6. `.env.example` 增加搜索相关配置。
7. 给 `web_search` 增加单元测试，mock HTTP 响应。

验收：

- `SEARCH_PROVIDER=searxng` 可以正常搜索。
- `SEARCH_PROVIDER=auto` 可以 fallback。
- Agent 不直接依赖具体 provider。

### 阶段三：证据处理

目标：避免把搜索摘要直接当事实。

任务：

1. 新增 `ArticleExtractor`。
2. 新增 `EvidenceRanker`。
3. 实现 URL 去重和同源转载去重。
4. 实现来源等级评分。
5. 将证据包传给 LLM。

验收：

- 证据列表包含来源、URL、发布时间、等级。
- 低质量证据不能单独支撑强结论。
- 抓取失败不导致整个分析失败。

### 阶段四：实体识别与股票消歧

目标：防止 LLM 编造股票代码。

任务：

1. 新增 `EntityResolver`。
2. 接入本地股票库搜索。
3. 实现公司名、股票简称、股票代码归一。
4. 实现海外公司和 A 股公司的区分。
5. 未确认实体进入 `unresolved_entities`。

验收：

- 京东方可解析到本地股票。
- 英伟达识别为海外公司。
- 未确认股票不进入最终 `related_stocks.code`。

### 阶段五：产业链知识库

目标：提升海外事件和复杂产业事件的映射质量。

任务：

1. 新增 `data/knowledge/industry_chains.json`。
2. 新增 `IndustryChainMapper`。
3. 支持关键词、公司、技术、商品到产业链节点的匹配。
4. 输出强中弱关联。
5. 将知识库匹配结果与检索证据一并交给 LLM。

验收：

- 英伟达事件可映射到 AI 算力链条。
- 存储涨价事件可映射到存储、模组、设备、材料。
- 弱关联不会被输出成强结论。

### 阶段六：行情兑现判断

目标：程序化判断是否已被市场交易。

任务：

1. 新增 `MarketRealizationAnalyzer`。
2. 查询本地 `stock_daily` 或现有行情服务。
3. 计算 1/3/5/20 日涨跌幅。
4. 判断涨停、放量、提前异动。
5. 输出 `realization_status`。

验收：

- 消息发布时间晚于涨停时，标记 `moved_before_news`。
- 最近多日大涨时，标记 `likely_priced_in` 或 `partially_realized`。
- 无行情数据时，标记 `insufficient_market_data`。

### 阶段七：多轮补证 Agent

目标：实现最少 1 轮、最多 5 轮的检索补证。

任务：

1. LLM 支持输出 `need_more_data`。
2. Agent 根据补充 query 再次调用 `web_search`。
3. 累积证据包、实体、产业链和行情结果。
4. 超过轮次后输出低置信结果或 stopped。
5. 前端展示轮次进度。

验收：

- 最多执行 5 轮。
- 每轮 query 和结果数量受限。
- 噪音结果不会无限扩大上下文。

### 阶段八：异步任务与持久化

目标：提升用户体验和可追溯性。

任务：

1. 详情分析改为后台任务。
2. 增加任务状态查询接口。
3. Redis 缓存分析结果。
4. 可选持久化到数据库。
5. 前端轮询或 WebSocket 展示进度。

验收：

- 页面不会被长耗时分析阻塞。
- 刷新后可恢复分析结果。
- 同一新闻重复点击优先读缓存。

## 17. 测试策略

### 17.1 单元测试

覆盖：

- 事件分类
- 停止条件
- SearXNG 响应归一化
- Provider fallback
- 证据评分
- 实体消歧
- 产业链映射
- 行情兑现计算

### 17.2 API 测试

覆盖：

- `ready`
- `stopped`
- `failed`
- 检索服务不可用
- LLM 不可用
- 无行情数据

### 17.3 回归样例

建议维护固定新闻样例：

```text
国内公司公告
国内产业政策
海外科技公司新闻
海外财经事件
宽泛外交访问
市场传闻
盘后利好但盘中已涨停
```

## 18. 风险与防护

主要风险：

1. LLM 编造股票代码或供应链关系。
2. 把相关性当因果。
3. 海外新闻强行映射到 A 股。
4. 宽泛地缘新闻硬拆成板块机会。
5. 忽略消息发布时间与股价异动时间。
6. 搜索轮次越多，噪音越多。
7. 低质量来源支撑强结论。
8. 输出“什么都利好一点”的无效结论。

防护：

- 股票代码必须本地确认
- 停止机制前置
- 证据等级约束
- 行情兑现程序化
- 多轮检索限流
- 输出结构化
- 所有结论带置信度和不确定项

## 19. 建议优先级

优先做：

```text
1. Agent 骨架
2. 事件分类与停止机制
3. web_search 工具和 SearXNG provider
4. 结构化输出
5. 行情兑现判断
```

稍后做：

```text
1. 正文抽取
2. 产业链知识库
3. 多轮补证
4. 异步任务
5. 数据库持久化
```

最低可用版本不需要一次性完成所有模块。先做固定流程版，再逐步替换内部模块，可以保证架构可升级且不强耦合当前消息板块实现。

---

## ✅ 开发完成状态 (2026-06-04)

### 已完成模块

| 阶段 | 模块 | 状态 |
|------|------|------|
| 阶段一 | Agent 骨架 (schemas, agent, event_classifier, prompts) | ✅ |
| 阶段一 | `/api/v1/news-board/analyze-detail` 接口 | ✅ |
| 阶段二 | `web_search` 工具 + SearXNG Provider + SearchOrchestrator | ✅ |
| 阶段三 | ArticleExtractor + EvidenceRanker (来源分级/去重/评分) | ✅ |
| 阶段四 | EntityResolver (实体抽取+海外公司识别+本地股票库消歧) | ✅ |
| 阶段五 | IndustryChainMapper + `data/knowledge/industry_chains.json` (含 AI算力/光伏/半导体/新能源等产业链) | ✅ |
| 阶段六 | MarketRealizationAnalyzer (涨跌幅/涨停/放量/提前异动/兑现状态) | ✅ |
| 阶段七 | 多轮补证机制 (1-5轮, LLM决策, query去重, 自动停止) | ✅ |
| 前端 | NewsBoard.vue "详情分析"按钮 + 结构化结果展示 | ✅ |
| 基础设施 | SearXNG Docker 服务 + `deploy/docker-compose.yml` | ✅ |
| 配置 | `.env.example` + `deploy/.env` + `config.py` 新增配置项 | ✅ |
| 测试 | 29 个单元测试覆盖事件分类/证据评分/实体消歧/产业链映射/行情兑现/搜索编排 | ✅ |

### 文件清单

**新建文件:**
- `backend/app/agents/__init__.py`
- `backend/app/agents/news_event/__init__.py`
- `backend/app/agents/news_event/schemas.py` - Pydantic 数据模型
- `backend/app/agents/news_event/prompts.py` - LLM 提示词
- `backend/app/agents/news_event/event_classifier.py` - 事件分类器
- `backend/app/agents/news_event/agent.py` - 主编排 Agent
- `backend/app/agents/news_event/search_orchestrator.py` - 搜索编排器
- `backend/app/agents/news_event/article_extractor.py` - 文章提取器
- `backend/app/agents/news_event/evidence_ranker.py` - 证据评分器
- `backend/app/agents/news_event/entity_resolver.py` - 实体识别器
- `backend/app/agents/news_event/industry_chain_mapper.py` - 产业链映射器
- `backend/app/agents/news_event/market_realization_analyzer.py` - 行情兑现分析器
- `backend/app/services/search/__init__.py`
- `backend/app/services/search/base.py` - 搜索 Provider 抽象基类
- `backend/app/services/search/searxng_search_service.py` - SearXNG Provider
- `data/knowledge/industry_chains.json` - 产业链知识库
- `backend/tests/test_agent/test_news_event/` - 6 个测试文件 (29 个测试用例)

**修改文件:**
- `backend/app/config.py` - 新增 News Agent + Search 配置项
- `backend/app/schemas.py` - 新增详情分析请求/响应 Schema
- `backend/app/api/news_board.py` - 新增 `/analyze-detail` 端点
- `frontend/src/views/NewsBoard.vue` - 新增"详情分析"按钮和完整结果展示
- `.env.example` - 新增配置项
- `deploy/.env` - 新增配置项
- `deploy/docker-compose.yml` - 新增 SearXNG 服务

### 测试结果
```
29 passed (event_classifier: 7, evidence_ranker: 5, entity_resolver: 4,
           industry_chain_mapper: 5, market_realization: 4,
           search_orchestrator: 4)
```
