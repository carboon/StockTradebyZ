"""LLM prompts for the News Event Analysis Agent."""
from __future__ import annotations

SYSTEM_PROMPT = """你是一名严谨的 A 股事件驱动市场分析师。

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
10. 证据不足时输出需要补充的数据，不要强行下结论。"""


CLASSIFICATION_PROMPT = """请分析以下新闻事件，判断其类型、市场范围和可分析性。

新闻标题：{title}
新闻摘要：{summary}
新闻分类：{category}
新闻来源：{source}
发布时间：{published_at}
事件时间：{event_time}

请返回 JSON 格式，包含以下字段：
- event_type: 事件类型，必须是以下之一：
  domestic_company（国内公司）, domestic_industry（国内产业）, overseas_company（海外公司）,
  overseas_industry（海外产业）, macro_policy（宏观政策）, geopolitical_broad（宽泛地缘）,
  market_movement（市场波动）, unverifiable_rumor（不可验证传闻）, not_analyzable（不可分析）
- market_scope: 市场范围，domestic/overseas/both/none
- analyzable: 是否可分析，true/false
- mapping_required: 是否需要产业链映射，true/false
- reason: 分类理由

分类规则：
1. 涉及国内公司公告、财报、产品发布的 -> domestic_company
2. 涉及国内产业政策、监管变化的 -> domestic_industry
3. 涉及海外公司（苹果、英伟达、特斯拉等）的 -> overseas_company
4. 涉及海外产业趋势的 -> overseas_industry
5. 涉及央行政策、财政政策的 -> macro_policy
6. 涉及国际访问、外交关系、地缘冲突的 -> geopolitical_broad
7. 涉及大盘走势、指数波动的 -> market_movement
8. 涉及未经证实传闻的 -> unverifiable_rumor
9. 不包含具体企业/产业信息的 -> not_analyzable

停止条件（返回 analyzable=false）：
- 宽泛外交、访问、会晤、国际关系表态，缺少明确产业/政策/订单/价格/供需/监管变量
- 影响范围过宽，只能得出"风险偏好变化"等泛结论
- 只有低质量传闻，缺少可信来源
- 无法映射到具体板块或标的，且缺少后续可验证指标"""


ANALYSIS_PROMPT = """请基于以下输入，输出对应分析或状态判断。

## 输入
新闻信息：
- 标题：{title}
- 摘要：{summary}
- 分类：{category}
- 来源：{source}
- 发布时间：{published_at}
- 事件时间：{event_time}

事件分类：{classification}

证据列表：
{evidence}

证据质量摘要：
{evidence_quality}

缺失信息：
{missing_slots}

实体列表：
{entities}

产业链映射：
{industry_chains}

行情兑现状态：
{market_realization}

允许输出的 A 股代码列表：
{allowed_stock_codes}

当前轮次：{round_num} / {max_rounds}

## 输出要求

你在每轮只能返回以下三种状态之一：

### 1. ready - 证据足够，输出完整分析
```json
{{
  "status": "ready",
  "event_type": "事件类型",
  "confidence": 0.76,
  "event_summary": "事件一句话摘要",
  "core_facts": ["事实1", "事实2"],
  "impact_path": [
    {{"description": "影响传导路径", "confidence": 0.8}}
  ],
  "direct_sectors": ["直接受益板块"],
  "indirect_sectors": ["间接受益板块"],
  "related_stocks": [
    {{"code": "300308.SZ", "name": "中际旭创", "relation": "光模块", "mapping_strength": "strong", "reason": "理由", "evidence_ids": ["ev_001"]}}
  ],
  "upstream_downstream": ["上游环节", "下游环节"],
  "risks": ["风险点"],
  "watch_points": ["后续观察点"]
}}
```

### 2. need_more_data - 证据不足，需要补充检索
```json
{{
  "status": "need_more_data",
  "reason": "缺少原因说明",
  "search_queries": ["查询关键词1", "查询关键词2"]
}}
```

### 3. stopped - 事件不适合分析
```json
{{
  "status": "stopped",
  "reason": "停止原因",
  "event_summary": "事件概要",
  "watch_points": ["观察点1"]
}}
```

重要提醒：
- 股票代码必须来自输入数据，不得编造
- related_stocks.code 只能从“允许输出的 A 股代码列表”中选择；不在列表中必须删除
- 每个 related_stocks 必须能被证据或产业链映射支撑，reason 中说明证据依据
- 缺少 A/B 级证据时，不得输出 strong 关联
- 如果事件没有具体板块/股票关联，必须 stopped
- 如果达到最大轮次 {max_rounds} 仍证据不足，输出 stopped 并标注证据不足
- 置信度必须客观，不确定时降低置信度"""


ROUND_DECISION_PROMPT = """根据当前分析状态判断是否需要补充证据。

事件：{title}
当前轮次：{round_num} / {max_rounds}
当前证据数：{evidence_count}
已有实体：{entity_count}
行情数据覆盖：{market_data_count}

请判断：证据是否足够输出完整分析？

如果证据不足，生成最多 {max_queries} 个补充检索 query。
如果证据足够，返回 ready。
如果事件不适合分析，返回 stopped。

仅返回 JSON：
{{
  "status": "ready|need_more_data|stopped",
  "reason": "判断理由",
  "search_queries": ["补充查询1"] // 仅 need_more_data 时需要
}}"""
