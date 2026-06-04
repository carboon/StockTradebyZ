"""Event classification module - determines event type, scope, and analyzability."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from openai import OpenAI

from app.config import get_settings
from .prompts import CLASSIFICATION_PROMPT
from .schemas import EventClassification, EventType, MarketScope

logger = logging.getLogger(__name__)

DOMESTIC_KEYWORDS = [
    "A股", "沪市", "深市", "创业板", "科创板", "沪深", "涨停", "跌停",
    "证监会", "央行", "发改委", "工信部", "财政部", "商务部",
    "上交所", "深交所", "北交所",
]

DOMESTIC_COMPANY_INDICATORS = [
    "公告", "财报", "业绩", "分红", "回购", "增持", "减持", "重组",
    "上市", "IPO", "定增", "股权激励",
]

DOMESTIC_INDUSTRY_INDICATORS = [
    "政策", "补贴", "监管", "规划", "产能", "国产替代", "自主可控",
]

OVERSEAS_KEYWORDS = [
    "美股", "纳斯达克", "纽交所", "标普", "道琼斯", "华尔街",
    "硅谷", "美联储", "SEC",
    "苹果", "英伟达", "特斯拉", "微软", "谷歌", "亚马逊", "Meta", "OpenAI",
    "台积电", "三星", "博通", "美光", "AMD", "超威", "英特尔", "Intel",
    "高通", "ARM", "安谋", "英飞凌", "德州仪器", "恩智浦", "意法半导体",
    "阿斯麦", "ASML", "应用材料", "泛林", "东京电子", "SK海力士",
    "费城半导体", "费城半导体指数", "SOX", "半导体指数",
]

GEOPOLITICAL_KEYWORDS = [
    "访问", "会晤", "会谈", "外交", "制裁", "关税", "贸易战",
    "地缘", "冲突", "战争", "军事",
]


class EventClassifier:
    """Classifies news events for analysis routing."""

    DEEPSEEK_BASE_URL = "https://api.deepseek.com"
    DEFAULT_MODEL = "deepseek-v4-flash"

    def classify(self, title: str, summary: str, category: str = "",
                 source: str = "", published_at: str = "",
                 event_time: str = "") -> EventClassification:
        text = f"{title} {summary}".lower()

        if not text.strip():
            return EventClassification(
                event_type=EventType.NOT_ANALYZABLE,
                market_scope=MarketScope.NONE,
                analyzable=False,
                mapping_required=False,
                reason="新闻内容为空。",
            )

        llm_result = self._classify_with_llm(
            title=title, summary=summary, category=category,
            source=source, published_at=published_at,
            event_time=event_time,
        )
        if llm_result:
            return llm_result

        return self._classify_with_rules(text)

    def _classify_with_llm(self, **kwargs: Any) -> EventClassification | None:
        api_key = str(get_settings().deepseek_api_key or "").strip()
        if not api_key:
            api_key = str(os.environ.get("DEEPSEEK_API_KEY", "")).strip()
        if not api_key:
            return None

        prompt = CLASSIFICATION_PROMPT.format(**kwargs)
        try:
            client = OpenAI(api_key=api_key, base_url=self.DEEPSEEK_BASE_URL, timeout=30.0, max_retries=1)
            response = client.chat.completions.create(
                model=self.DEFAULT_MODEL,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            content = response.choices[0].message.content if response.choices else None
            if not content:
                return None
            data = json.loads(content)
            return EventClassification(
                event_type=EventType(data.get("event_type", "not_analyzable")),
                market_scope=MarketScope(data.get("market_scope", "none")),
                analyzable=bool(data.get("analyzable", False)),
                mapping_required=bool(data.get("mapping_required", False)),
                reason=str(data.get("reason", "")),
            )
        except Exception as exc:
            logger.warning("EventClassifier LLM 调用失败: %s", exc)
            return None

    @staticmethod
    def _classify_with_rules(text: str) -> EventClassification:
        has_domestic = any(kw in text for kw in DOMESTIC_KEYWORDS)
        has_overseas = any(kw in text for kw in OVERSEAS_KEYWORDS)
        has_geopolitical = any(kw in text for kw in GEOPOLITICAL_KEYWORDS)
        has_company = any(ind in text for ind in DOMESTIC_COMPANY_INDICATORS)
        has_industry = any(ind in text for ind in DOMESTIC_INDUSTRY_INDICATORS)

        if has_geopolitical and not has_company and not has_industry:
            return EventClassification(
                event_type=EventType.GEOPOLITICAL_BROAD,
                market_scope=MarketScope.BOTH,
                analyzable=False,
                mapping_required=False,
                reason="该事件属于宽泛地缘/外交事件，缺少明确产业或政策变量，不适合输出具体板块和个股。",
            )

        if has_company and has_domestic:
            return EventClassification(
                event_type=EventType.DOMESTIC_COMPANY,
                market_scope=MarketScope.DOMESTIC,
                analyzable=True,
                mapping_required=False,
                reason="涉及国内公司事件，直接分析国内相关标的。",
            )

        if has_industry and has_domestic:
            return EventClassification(
                event_type=EventType.DOMESTIC_INDUSTRY,
                market_scope=MarketScope.DOMESTIC,
                analyzable=True,
                mapping_required=False,
                reason="涉及国内产业事件，直接分析国内板块和标的。",
            )

        if has_overseas:
            return EventClassification(
                event_type=EventType.OVERSEAS_COMPANY,
                market_scope=MarketScope.OVERSEAS,
                analyzable=True,
                mapping_required=True,
                reason="涉及海外公司或产业事件，需要通过产业链映射到 A 股。",
            )

        if re.search(r"(政策|央行|降准|降息|加息|LPR|MLF|逆回购)", text):
            return EventClassification(
                event_type=EventType.MACRO_POLICY,
                market_scope=MarketScope.DOMESTIC,
                analyzable=True,
                mapping_required=False,
                reason="涉及宏观政策事件，分析对相关板块的影响。",
            )

        return EventClassification(
            event_type=EventType.NOT_ANALYZABLE,
            market_scope=MarketScope.NONE,
            analyzable=False,
            mapping_required=False,
            reason="无法明确分类的事件类型，缺少具体的产业或公司信息。",
        )


event_classifier = EventClassifier()
