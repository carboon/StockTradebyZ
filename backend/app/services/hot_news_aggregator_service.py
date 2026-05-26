"""Market hot-topic aggregation service."""
from __future__ import annotations

import html
import json
import logging
import re
import uuid
from datetime import date, timedelta
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Config
from app.services.deepseek_service import DeepSeekService
from app.services.tushare_service import TushareService

logger = logging.getLogger(__name__)


class HotNewsAggregatorService:
    """Aggregate recent A-share hot topics from news and market-flow evidence."""

    PUBLIC_NEWS_SOURCES = [
        ("sina_stock", "新浪财经股票", "https://finance.sina.com.cn/stock/"),
        ("eastmoney_finance", "东方财富财经", "https://finance.eastmoney.com/"),
    ]
    PUBLIC_NEWS_HEADERS = {
        "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    PUBLIC_NEWS_TITLE_RE = re.compile(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
    STRIP_TAG_RE = re.compile(r"<[^>]+>")
    COMMON_HOT_TOKENS = (
        "半导体",
        "芯片",
        "PCB",
        "AI",
        "算力",
        "机器人",
        "自主可控",
        "贸易战",
        "关税",
        "特朗普",
        "存储",
        "低空经济",
        "军工",
        "新能源",
        "光伏",
        "固态电池",
        "商业航天",
        "卫星互联网",
        "数据要素",
        "创新药",
        "CPO",
        "液冷",
        "铜缆",
    )
    DEFAULT_SEARCH_QUERIES = (
        "近三天 A股 热点 题材 板块",
        "今日 A股 涨停 题材 热点",
        "A股 半导体 PCB 存储 自主可控 热点",
        "财联社 A股 热点 题材 近三天",
        "东方财富 A股 热点 板块 近三天",
        "A股 资金流入 板块 热点 今日",
    )
    _search_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
    SEARCH_CACHE_TTL_SECONDS = 6 * 60 * 60

    def __init__(
        self,
        db: Session,
        *,
        tushare_service: TushareService | None = None,
        deepseek_service: DeepSeekService | None = None,
    ) -> None:
        self.db = db
        self.tushare_service = tushare_service or TushareService()
        self.deepseek_service = deepseek_service or DeepSeekService(api_key=self._load_deepseek_api_key())
        self.bocha_api_key = self._load_config_or_env("bocha_api_key", settings.bocha_api_key)
        self.ai360_api_key = self._load_config_or_env("ai360_api_key", settings.ai360_api_key)
        self.tavily_api_key = self._load_config_or_env("tavily_api_key", settings.tavily_api_key)

    def _load_deepseek_api_key(self) -> str:
        value = self.db.query(Config.value).filter(Config.key == "deepseek_api_key").scalar()
        return str(value or "").strip()

    def _load_config_or_env(self, key: str, env_value: str) -> str:
        value = self.db.query(Config.value).filter(Config.key == key).scalar()
        return str(value or env_value or "").strip()

    def get_market_hot_topics(
        self,
        *,
        trade_date: date,
        window_days: int = 3,
        limit: int = 12,
        sector_flow: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        window_days = max(1, min(int(window_days or 3), 7))
        limit = max(1, min(int(limit or 12), 20))
        start_date = trade_date - timedelta(days=window_days)
        search_queries = self._build_search_queries(trade_date=trade_date, window_days=window_days)
        news_items = self._collect_news_items(
            start_date=start_date,
            end_date=trade_date,
            limit=160,
            search_queries=search_queries,
        )
        flow_items = self._normalize_sector_flow_items(sector_flow)
        evidence = self._build_evidence(news_items=news_items, flow_items=flow_items, limit=120)
        fallback_topics = self._fallback_hot_topics(evidence=evidence, limit=limit)

        if not self.deepseek_service.enabled:
            return self._build_payload(
                source="local_fallback",
                start_date=start_date,
                end_date=trade_date,
                window_days=window_days,
                keywords=fallback_topics,
                summary="DeepSeek API Key 未配置，热点关键词来自新闻标题、公开资讯和板块资金流本地归纳。",
                evidence=evidence,
                search_queries=search_queries,
            )

        ai_topics = self._infer_hot_topics_with_ai(
            trade_date=trade_date,
            start_date=start_date,
            window_days=window_days,
            evidence=evidence,
            fallback_topics=fallback_topics,
            limit=limit,
        )
        if ai_topics:
            return self._build_payload(
                source="deepseek",
                start_date=start_date,
                end_date=trade_date,
                window_days=window_days,
                keywords=ai_topics.get("keywords") or fallback_topics,
                summary=ai_topics.get("summary"),
                evidence=evidence,
                confidence=ai_topics.get("confidence"),
                search_queries=search_queries,
            )

        return self._build_payload(
            source="local_fallback",
            start_date=start_date,
            end_date=trade_date,
            window_days=window_days,
            keywords=fallback_topics,
            summary="DeepSeek 热点提取失败，已使用本地归纳。",
            evidence=evidence,
            search_queries=search_queries,
        )

    def _collect_news_items(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int,
        search_queries: list[str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items.extend(self._fetch_search_news(search_queries=search_queries, start_date=start_date, end_date=end_date))
        items.extend(self._fetch_tushare_news(start_date=start_date, end_date=end_date, limit=limit))
        items.extend(self._fetch_public_finance_news(limit=80))
        return self._dedupe_news_items(items)[:limit]

    def _build_search_queries(self, *, trade_date: date, window_days: int) -> list[str]:
        max_queries = int(settings.hot_news_search_max_queries or 6)
        fallback = list(self.DEFAULT_SEARCH_QUERIES[:max_queries])
        if not self._search_provider_enabled() or not self.deepseek_service.enabled:
            return fallback

        system_prompt = (
            "你是A股资讯检索词规划助手。输出 JSON object，不能输出 markdown。"
            "目标是为搜索引擎生成能找到近几天A股热点题材、行业和事件的中文检索词。"
        )
        user_prompt = (
            f"请为 {trade_date.isoformat()} 收盘后的近{window_days}天A股热点聚合生成 {max_queries} 个搜索词。"
            "固定返回 JSON：{\"queries\":[\"string\"]}。"
            "搜索词应覆盖：题材热度、涨停原因、板块资金、半导体/PCB/AI/自主可控等可能方向。"
        )
        try:
            result = self.deepseek_service.infer_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
            )
        except Exception:
            logger.warning("AI 搜索词生成失败，使用默认搜索词", exc_info=True)
            return fallback
        queries = result.get("queries") if isinstance(result, dict) else None
        if not isinstance(queries, list):
            return fallback
        normalized = [str(query).strip() for query in queries if str(query).strip()]
        return list(dict.fromkeys(normalized + fallback))[:max_queries]

    def _search_provider_enabled(self) -> bool:
        if not settings.hot_news_search_enabled:
            return False
        provider = str(settings.hot_news_search_provider or "auto").strip().lower()
        if provider == "bocha":
            return bool(self.bocha_api_key)
        if provider == "ai360":
            return bool(self.ai360_api_key)
        if provider == "tavily":
            return bool(self.tavily_api_key)
        return bool(self.bocha_api_key or self.ai360_api_key or self.tavily_api_key)

    def _fetch_search_news(self, *, search_queries: list[str], start_date: date, end_date: date) -> list[dict[str, Any]]:
        provider = self._resolve_search_provider()
        if provider is None:
            return []
        import time
        cache_key = f"{provider}:{start_date.isoformat()}:{end_date.isoformat()}:{'|'.join(search_queries)}"
        cached = self._search_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < self.SEARCH_CACHE_TTL_SECONDS:
            return cached[1]

        items: list[dict[str, Any]] = []
        for query in search_queries:
            if provider == "bocha":
                items.extend(self._search_bocha_news(query=query))
            elif provider == "ai360":
                items.extend(self._search_ai360_news(query=query))
            elif provider == "tavily":
                items.extend(self._search_tavily_news(query=query, start_date=start_date, end_date=end_date))
        result = self._dedupe_news_items(items)
        self._search_cache[cache_key] = (now, result)
        return result

    def _resolve_search_provider(self) -> str | None:
        if not settings.hot_news_search_enabled:
            return None
        provider = str(settings.hot_news_search_provider or "auto").strip().lower()
        if provider == "bocha":
            return "bocha" if self.bocha_api_key else None
        if provider == "ai360":
            return "ai360" if self.ai360_api_key else None
        if provider == "tavily":
            return "tavily" if self.tavily_api_key else None
        if self.bocha_api_key:
            return "bocha"
        if self.ai360_api_key:
            return "ai360"
        if self.tavily_api_key:
            return "tavily"
        return None

    def _search_bocha_news(self, *, query: str) -> list[dict[str, Any]]:
        if not self.bocha_api_key:
            return []
        payload = {
            "query": query,
            "count": int(settings.hot_news_search_max_results or 5),
            "freshness": "oneWeek",
            "summary": True,
        }
        try:
            response = requests.post(
                "https://api.bochaai.com/v1/web-search",
                headers={
                    "Authorization": f"Bearer {self.bocha_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.warning("博查热点搜索失败: query=%s", query, exc_info=True)
            return []
        return self._extract_bocha_items(data, query=query)

    def _extract_bocha_items(self, data: Any, *, query: str) -> list[dict[str, Any]]:
        raw_items = self._walk_possible_search_items(data)
        items: list[dict[str, Any]] = []
        for item in raw_items:
            title = str(item.get("title") or item.get("name") or "").strip()
            if not title:
                continue
            summary = item.get("summary") or item.get("snippet") or item.get("description") or item.get("content") or ""
            items.append({
                "datetime": item.get("datePublished") or item.get("date") or item.get("time") or item.get("publish_time"),
                "title": title,
                "content": summary,
                "src": item.get("siteName") or item.get("site") or item.get("source") or "博查AI搜索",
                "source_type": "search",
                "url": item.get("url") or item.get("link"),
                "source_key": "bocha",
                "query": query,
            })
            if len(items) >= int(settings.hot_news_search_max_results or 5):
                break
        return items

    def _search_tavily_news(self, *, query: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
        if not self.tavily_api_key:
            return []
        payload = {
            "query": query,
            "topic": "news",
            "search_depth": "basic",
            "max_results": int(settings.hot_news_search_max_results or 5),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "include_answer": False,
            "include_raw_content": False,
        }
        try:
            response = requests.post(
                "https://api.tavily.com/search",
                headers={
                    "Authorization": f"Bearer {self.tavily_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.warning("Tavily 热点搜索失败: query=%s", query, exc_info=True)
            return []
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return []
        items: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            items.append({
                "datetime": item.get("published_date"),
                "title": title,
                "content": item.get("content") or "",
                "src": item.get("source") or "Tavily",
                "source_type": "search",
                "url": item.get("url"),
                "source_key": "tavily",
                "query": query,
            })
        return items

    def _search_ai360_news(self, *, query: str) -> list[dict[str, Any]]:
        if not self.ai360_api_key:
            return []
        try:
            response = requests.get(
                "https://api.360.cn/v2/mwebsearch",
                headers={
                    "Authorization": f"Bearer {self.ai360_api_key}",
                    "Content-Type": "application/json",
                },
                params={
                    "q": query,
                    "ref_prom": "aiso-news",
                    "sid": str(uuid.uuid4()),
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            logger.warning("360 智搜热点搜索失败: query=%s", query, exc_info=True)
            return []
        return self._extract_ai360_items(data, query=query)

    def _extract_ai360_items(self, data: Any, *, query: str) -> list[dict[str, Any]]:
        raw_items = self._walk_possible_search_items(data)
        items: list[dict[str, Any]] = []
        for item in raw_items:
            title = str(item.get("title") or item.get("name") or "").strip()
            if not title:
                continue
            summary = item.get("summary_ai") or item.get("summary") or item.get("snippet") or item.get("content") or ""
            items.append({
                "datetime": item.get("date") or item.get("time") or item.get("publish_time"),
                "title": title,
                "content": summary,
                "src": item.get("site") or item.get("source") or "360智搜",
                "source_type": "search",
                "url": item.get("url") or item.get("link"),
                "source_key": "ai360",
                "query": query,
            })
            if len(items) >= int(settings.hot_news_search_max_results or 5):
                break
        return items

    @classmethod
    def _walk_possible_search_items(cls, value: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if isinstance(value, dict):
            if any(key in value for key in ("title", "summary_ai", "snippet", "url", "link")):
                found.append(value)
            for nested in value.values():
                found.extend(cls._walk_possible_search_items(nested))
        elif isinstance(value, list):
            for nested in value:
                found.extend(cls._walk_possible_search_items(nested))
        return found

    def _fetch_tushare_news(self, *, start_date: date, end_date: date, limit: int) -> list[dict[str, Any]]:
        try:
            return self.tushare_service.get_news_items(
                src="yicai",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                limit=limit,
            )
        except Exception:
            logger.warning("Tushare 新闻获取失败", exc_info=True)
            return []

    def _fetch_public_finance_news(self, *, limit: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for source_key, source_name, url in self.PUBLIC_NEWS_SOURCES:
            try:
                response = requests.get(url, headers=self.PUBLIC_NEWS_HEADERS, timeout=6)
                response.raise_for_status()
                response.encoding = response.apparent_encoding or response.encoding
            except Exception:
                logger.warning("公开财经资讯源获取失败: %s", url, exc_info=True)
                continue

            for href, raw_title in self.PUBLIC_NEWS_TITLE_RE.findall(response.text):
                title = self._clean_html_text(raw_title)
                if not self._is_relevant_title(title):
                    continue
                items.append({
                    "datetime": None,
                    "title": title,
                    "content": "",
                    "src": source_name,
                    "source_type": "public_web",
                    "url": href,
                    "source_key": source_key,
                })
                if len(items) >= limit:
                    return items
        return items

    @classmethod
    def _clean_html_text(cls, value: str) -> str:
        text = cls.STRIP_TAG_RE.sub("", value or "")
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    @classmethod
    def _is_relevant_title(cls, title: str) -> bool:
        if len(title) < 6 or len(title) > 120:
            return False
        bad_fragments = ("登录", "注册", "广告", "专题", "视频", "微博", "APP", "客户端下载")
        return not any(fragment in title for fragment in bad_fragments)

    @staticmethod
    def _dedupe_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for item in items:
            title = str(item.get("title") or "").strip()
            if not title or title in seen:
                continue
            seen.add(title)
            result.append(item)
        return result

    @staticmethod
    def _normalize_sector_flow_items(sector_flow: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(sector_flow, dict):
            return []
        items: list[dict[str, Any]] = []
        for key, direction in (("inflow_top3", "inflow"), ("outflow_top3", "outflow")):
            raw_items = sector_flow.get(key)
            if not isinstance(raw_items, list):
                continue
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("sector_name") or "").strip()
                if not name:
                    continue
                items.append({
                    "sector_name": name,
                    "net_mf_amount": item.get("net_mf_amount"),
                    "direction": direction,
                })
        return items

    @staticmethod
    def _build_evidence(
        *,
        news_items: list[dict[str, Any]],
        flow_items: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for item in flow_items:
            direction = "净流入" if item.get("direction") == "inflow" else "净流出"
            evidence.append({
                "type": "sector_flow",
                "title": f"{item.get('sector_name')} 资金{direction}",
                "source": "sector_flow",
                "published_at": None,
                "url": None,
                "summary": f"板块资金{direction} {item.get('net_mf_amount')} 万",
                "sector_name": item.get("sector_name"),
                "net_mf_amount": item.get("net_mf_amount"),
            })
        for item in news_items:
            evidence.append({
                "type": "news",
                "title": item.get("title"),
                "source": item.get("src") or item.get("source_key") or "news",
                "published_at": item.get("datetime") or item.get("pub_time") or item.get("date"),
                "url": item.get("url"),
                "summary": str(item.get("content") or "")[:220],
                "query": item.get("query"),
                "source_key": item.get("source_key"),
            })
            if len(evidence) >= limit:
                break
        return evidence[:limit]

    def _infer_hot_topics_with_ai(
        self,
        *,
        trade_date: date,
        start_date: date,
        window_days: int,
        evidence: list[dict[str, Any]],
        fallback_topics: list[dict[str, Any]],
        limit: int,
    ) -> dict[str, Any] | None:
        evidence_context = [
            {
                "type": item.get("type"),
                "title": str(item.get("title") or "")[:160],
                "source": item.get("source"),
                "published_at": item.get("published_at"),
                "summary": str(item.get("summary") or "")[:220],
            }
            for item in evidence[:90]
            if item.get("title")
        ]
        context = {
            "trade_date": trade_date.isoformat(),
            "window": {"start_date": start_date.isoformat(), "days": window_days},
            "evidence": evidence_context,
            "fallback_keywords": fallback_topics,
            "limit": limit,
        }
        system_prompt = (
            "你是A股热点新闻聚合助手。只能基于 evidence 中的标题、摘要、来源、时间和板块资金流提炼热点，"
            "必须输出 JSON object，不能输出 markdown。关键词应优先是行业、产业链、政策、事件或核心公司名。"
            "不要输出没有 evidence 支撑的关键词。"
        )
        user_prompt = (
            f"请提取近{window_days}天 A股 最核心的股票热点关键词，最多 {limit} 个。固定返回 JSON："
            '{"keywords":[{"keyword":"string","category":"industry|company|policy|event|theme",'
            '"heat":0,"reason":"string","related_sectors":["string"],"related_companies":["string"],'
            '"evidence":["string"]}],"summary":"string","confidence":0}\n'
            f"上下文：\n{json.dumps(context, ensure_ascii=False, default=str)}"
        )
        try:
            result = self.deepseek_service.infer_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
            )
        except Exception:
            logger.warning("DeepSeek 热点提取失败", exc_info=True)
            return None
        keywords = result.get("keywords") if isinstance(result, dict) else None
        if not isinstance(keywords, list) or not keywords:
            return None
        result["keywords"] = self._normalize_ai_keywords(keywords, evidence=evidence, limit=limit)
        return result if result["keywords"] else None

    @classmethod
    def _normalize_ai_keywords(
        cls,
        keywords: list[Any],
        *,
        evidence: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        evidence_by_title = {str(item.get("title") or ""): item for item in evidence if item.get("title")}
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in keywords:
            if isinstance(item, str):
                raw = {"keyword": item}
            elif isinstance(item, dict):
                raw = item
            else:
                continue
            keyword = str(raw.get("keyword") or "").strip()
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            raw_evidence = raw.get("evidence")
            evidence_titles = [str(value).strip() for value in raw_evidence if str(value).strip()] if isinstance(raw_evidence, list) else []
            matched_evidence = [evidence_by_title[title] for title in evidence_titles if title in evidence_by_title]
            if not matched_evidence:
                matched_evidence = [
                    ev for ev in evidence
                    if keyword in str(ev.get("title") or "") or keyword in str(ev.get("summary") or "")
                ][:3]
            normalized.append({
                "keyword": keyword,
                "category": raw.get("category") or "theme",
                "heat": cls._safe_heat(raw.get("heat"), default=max(50, 95 - len(normalized) * 5)),
                "reason": str(raw.get("reason") or "基于近期新闻和资金流证据归纳"),
                "related_sectors": cls._string_list(raw.get("related_sectors")),
                "related_companies": cls._string_list(raw.get("related_companies")),
                "evidence": matched_evidence[:3],
            })
            if len(normalized) >= limit:
                break
        return normalized

    @classmethod
    def _fallback_hot_topics(cls, *, evidence: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        for item in evidence:
            title = str(item.get("title") or "")
            sector_name = str(item.get("sector_name") or "")
            source_type = item.get("type")
            tokens = [sector_name] if source_type == "sector_flow" and sector_name else []
            tokens.extend(token for token in cls.COMMON_HOT_TOKENS if token in title)
            for token in tokens:
                if not token:
                    continue
                entry = candidates.setdefault(
                    token,
                    {
                        "keyword": token,
                        "category": "industry" if source_type == "sector_flow" else "theme",
                        "heat": 50,
                        "reason": "来自新闻标题、公开资讯或板块资金流归纳",
                        "related_sectors": [sector_name] if sector_name else [],
                        "related_companies": [],
                        "evidence": [],
                    },
                )
                entry["heat"] = min(100, float(entry["heat"]) + (18 if source_type == "sector_flow" else 8))
                if len(entry["evidence"]) < 3:
                    entry["evidence"].append(item)
        ranked = sorted(candidates.values(), key=lambda item: float(item.get("heat") or 0), reverse=True)
        return ranked[:limit]

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _safe_heat(value: Any, *, default: float) -> float:
        try:
            return max(0.0, min(float(value), 100.0))
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _build_payload(
        *,
        source: str,
        start_date: date,
        end_date: date,
        window_days: int,
        keywords: list[dict[str, Any]],
        summary: str | None,
        evidence: list[dict[str, Any]],
        confidence: Any = None,
        search_queries: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "source": source,
            "window_days": window_days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "search_queries": search_queries or [],
            "keywords": keywords,
            "summary": summary,
            "confidence": confidence,
            "evidence": evidence[:30],
        }
