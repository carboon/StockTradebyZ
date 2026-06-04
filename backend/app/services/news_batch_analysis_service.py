"""News batch analysis service - aggregates multiple news items and calls LLM."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

A_SHARE_KEYWORDS = [
    "A股", "上海", "深圳", "创业板", "科创板", "北交所",
    "涨停", "跌停", "异动", "放量", "拉升", "跳水",
]

SECTOR_KEYWORDS = [
    "半导体", "芯片", "存储", "光刻", "封测", "晶圆",
    "AI", "人工智能", "算力", "GPU", "服务器",
    "新能源", "光伏", "锂电", "电池", "储能",
    "消费电子", "汽车", "机器人", "医药",
    "白酒", "银行", "保险", "地产", "券商",
    "煤炭", "石油", "有色", "钢铁", "化工",
    "军工", "低空", "卫星", "航天",
]

NEGATIVE_KW = ["跌", "暴跌", "跳水", "利空", "减持", "处罚", "下降", "亏损", "不及预期", "下滑"]
POSITIVE_KW = ["涨", "大涨", "利好", "增长", "突破", "订单", "创新高", "超预期"]

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

BATCH_ANALYSIS_PROMPT = """你是一名 A 股市场分析师。请分析以下批量新闻，输出结构化结果。

新闻列表（共 {total} 条）：
{news_text}

请输出 JSON：
{{
  "summary": "200字以内的综合摘要，概括这批新闻的核心趋势",
  "themes": [
    {{"topic": "主题名", "count": 条数, "sentiment": "positive/negative/neutral/mixed", "description": "一句话概述"}}
  ],
  "key_items": [
    {{"title": "新闻标题", "event_time": "时间", "weight": "high/medium/low", "reason": "对A股影响原因"}}
  ] (最多5条),
  "market_impact": "偏利好/偏利空/中性/分化 — 一句话判断",
  "watch_points": ["后续观察点1", "后续观察点2"]
}}

规则：
- 同一主题的多条新闻自动合并
- weight 判断标准：直接提及A股/板块/具体标的 → high；涉及海外但有映射路径 → medium；纯海外/泛宏观 → low
- 不输出股票代码（相关标的由单独的详情分析处理）
- 只说事实和可验证推断"""


class NewsBatchAnalysisService:
    """批量新闻分析服务."""

    @classmethod
    def analyze(cls, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {"status": "empty", "reason": "无搜索结果"}

        total = len(items)
        items = sorted(items, key=lambda x: x.get("eventTime") or x.get("publishedAt") or "", reverse=True)
        items = items[:50]

        for item in items:
            item["_weight"] = cls._calc_weight(item)
            item["_dedup_key"] = cls._dedup_key(item)

        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            key = item["_dedup_key"]
            grouped.setdefault(key, []).append(item)

        themes_map: dict[str, dict[str, Any]] = {}
        for item in items:
            title = item.get("title", "")
            summary = item.get("summary", "")
            text = f"{title} {summary}"
            for kw in SECTOR_KEYWORDS:
                if kw in text:
                    if kw not in themes_map:
                        themes_map[kw] = {"topic": kw, "count": 0, "sentiments": []}
                    themes_map[kw]["count"] += 1
                    if any(k in text for k in NEGATIVE_KW):
                        themes_map[kw]["sentiments"].append("negative")
                    elif any(k in text for k in POSITIVE_KW):
                        themes_map[kw]["sentiments"].append("positive")

        themes = []
        for t in sorted(themes_map.values(), key=lambda x: x["count"], reverse=True)[:6]:
            s_list = t["sentiments"]
            pos = sum(1 for s in s_list if s == "positive")
            neg = sum(1 for s in s_list if s == "negative")
            sentiment = "mixed" if pos > 0 and neg > 0 else ("positive" if pos > neg else ("negative" if neg > 0 else "neutral"))
            themes.append({
                "topic": t["topic"], "count": t["count"],
                "sentiment": sentiment,
                "description": "",
            })

        news_text = cls._build_news_text(items, grouped)

        llm_result = cls._call_llm(total=total, news_text=news_text)

        if llm_result:
            llm_themes = llm_result.get("themes", [])
            if llm_themes:
                for t in themes:
                    for lt in llm_themes:
                        if lt.get("topic") == t["topic"]:
                            t["description"] = lt.get("description", "")
                            t["sentiment"] = lt.get("sentiment", t["sentiment"])

            key_items = llm_result.get("key_items", [])
        else:
            key_items = sorted(items, key=lambda x: x.get("_weight", 0), reverse=True)[:5]
            key_items = [
                {"title": i.get("title", ""), "event_time": i.get("eventTime", ""),
                 "weight": i.get("_weight", "medium"), "reason": ""}
                for i in key_items
            ]

        summary_text = llm_result.get("summary", "") if llm_result else ""

        if not themes and not key_items:
            return {"status": "empty", "reason": "未识别到 A 股相关主题"}

        return {
            "status": "ready",
            "total": total,
            "summary": summary_text,
            "themes": themes,
            "key_items": key_items[:5],
            "market_impact": llm_result.get("market_impact", "") if llm_result else "",
            "watch_points": llm_result.get("watch_points", []) if llm_result else [],
        }

    @staticmethod
    def _calc_weight(item: dict[str, Any]) -> str:
        title = item.get("title", "")
        summary = item.get("summary", "")
        text = f"{title} {summary}"

        has_stock_code = bool(re.search(r"\d{6}\.(SZ|SH|BJ)", text, re.IGNORECASE))
        has_sector = any(kw in text for kw in SECTOR_KEYWORDS)
        has_a_share = any(kw in text for kw in A_SHARE_KEYWORDS)

        if has_stock_code or (has_sector and has_a_share):
            return "high"
        if has_sector:
            return "medium"
        return "low"

    @staticmethod
    def _dedup_key(item: dict[str, Any]) -> str:
        title = item.get("title", "")[:60]
        return hashlib.md5(title.encode()).hexdigest()[:8]

    @staticmethod
    def _build_news_text(
        items: list[dict[str, Any]],
        grouped: dict[str, list[dict[str, Any]]],
    ) -> str:
        lines = []
        for i, item in enumerate(items):
            title = item.get("title", "")
            summary = item.get("summary", "")[:120]
            weight = item.get("_weight", "low")
            event_time = item.get("eventTime", "") or ""
            dup_count = len(grouped.get(item.get("_dedup_key", ""), []))
            dup_note = f" [同类{dup_count}条]" if dup_count > 1 else ""
            lines.append(
                f"{i+1}. [{weight}] {title}{dup_note}"
                f"{' — ' + summary if summary else ''}"
                f"{' 时间:' + event_time[:16] if event_time else ''}"
            )
        return "\n".join(lines)

    @staticmethod
    def _call_llm(total: int, news_text: str) -> dict[str, Any] | None:
        import os as _os
        api_key = str(settings.deepseek_api_key or "").strip()
        if not api_key:
            api_key = str(_os.environ.get("DEEPSEEK_API_KEY", "")).strip()
        if not api_key:
            return None

        from openai import OpenAI
        try:
            client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL, timeout=60.0, max_retries=1)
            prompt = BATCH_ANALYSIS_PROMPT.format(total=total, news_text=news_text)
            response = client.chat.completions.create(
                model=DEFAULT_MODEL, temperature=0.2,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content if response.choices else None
            if not content:
                return None
            return json.loads(content)
        except Exception as exc:
            logger.warning("Batch LLM 调用失败: %s", exc)
            return None
