"""Search orchestrator - manages web_search with provider fallback."""
from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from app.cache import cache
from app.config import settings
from app.services.search.base import BaseSearchProvider
from app.services.search.searxng_search_service import SearXNGSearchProvider
from .schemas import SearchResult

logger = logging.getLogger(__name__)

SEARCH_QUERY_TEMPLATES = [
    "{title} 原文 事件详情",
    "{title} 影响 哪些行业",
    "{core_entity} {keyword} 产业链 A股",
    "{core_entity} A股 概念股 受益公司",
    "{keyword} A股 板块 受益 股票",
    "{title} 最近 异动 涨停 原因",
]


class SearchOrchestrator:
    """检索编排器 - 统一 web_search 接口，支持 provider 回退。"""

    def __init__(self) -> None:
        self._searxng: Optional[SearXNGSearchProvider] = None
        self._bocha: Optional[Any] = None
        self._tavily: Optional[Any] = None
        self._max_rounds = settings.news_agent_max_rounds
        self._max_queries_per_round = settings.news_agent_max_queries_per_round
        self._max_results_per_query = settings.news_agent_max_results_per_queries
        self._cache_ttl = min(settings.news_agent_cache_ttl_seconds, 1800)

    @property
    def searxng(self) -> SearXNGSearchProvider:
        if self._searxng is None:
            self._searxng = SearXNGSearchProvider()
        return self._searxng

    def _get_bocha(self, db: Any = None) -> Any:
        if self._bocha is None:
            try:
                from app.services.bocha_search_service import BochaSearchService
                self._bocha = BochaSearchService(db=db) if db else None
            except Exception:
                self._bocha = None
        return self._bocha

    def _get_tavily(self, db: Any = None) -> Any:
        if self._tavily is None:
            try:
                from app.services.tavily_search_service import TavilySearchService
                self._tavily = TavilySearchService(db=db) if db else None
            except Exception:
                self._tavily = None
        return self._tavily

    def search(
        self,
        query: str,
        *,
        freshness: str = "day",
        max_results: int = 8,
        categories: list[str] | None = None,
        language: str = "zh-CN",
        db: Any = None,
    ) -> list[SearchResult]:
        provider = settings.search_provider.lower()
        results: list[SearchResult] = []
        cache_key = self._cache_key(
            query=query,
            freshness=freshness,
            max_results=max_results,
            categories=categories,
            language=language,
            provider=provider,
        )
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            try:
                return [SearchResult(**item) for item in cached if isinstance(item, dict)]
            except Exception:
                pass

        if provider in ("searxng", "auto") and self.searxng.enabled:
            results = self.searxng.search(
                query=query, freshness=freshness, max_results=max_results,
                categories=categories, language=language,
            )
            if results:
                self._store_cache(cache_key, results)
                return results

        if provider in ("auto", "bocha"):
            bocha = self._get_bocha(db)
            if bocha and bocha.enabled:
                try:
                    raw = bocha.search(query=query, count=max_results, freshness="oneYear")
                    results = [self._normalize_bocha(r) for r in raw]
                    if results:
                        self._store_cache(cache_key, results)
                        return results
                except Exception as exc:
                    logger.warning("Bocha fallback 失败: %s", exc)

        if provider in ("auto", "tavily"):
            tavily = self._get_tavily(db)
            if tavily and tavily.enabled:
                try:
                    raw = tavily.search(query=query, count=max_results, freshness="oneYear")
                    results = [self._normalize_tavily(r) for r in raw]
                    if results:
                        self._store_cache(cache_key, results)
                        return results
                except Exception as exc:
                    logger.warning("Tavily fallback 失败: %s", exc)

        return results

    def search_many(
        self,
        queries: list[str],
        *,
        freshness: str = "day",
        max_results: int = 8,
        categories: list[str] | None = None,
        language: str = "zh-CN",
        db: Any = None,
    ) -> list[SearchResult]:
        """Run one search round concurrently and deduplicate all results."""
        unique_queries = []
        seen: set[str] = set()
        for query in queries[:self._max_queries_per_round]:
            normalized = " ".join(query.split())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_queries.append(normalized)
        if not unique_queries:
            return []

        workers = min(len(unique_queries), max(1, self._max_queries_per_round))
        all_results: list[SearchResult] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(
                    self.search,
                    query,
                    freshness=freshness,
                    max_results=max_results,
                    categories=categories,
                    language=language,
                    db=db,
                )
                for query in unique_queries
            ]
            for future in as_completed(futures):
                try:
                    all_results.extend(future.result())
                except Exception as exc:
                    logger.warning("并发搜索失败: %s", exc)
        return self.deduplicate(all_results)

    def generate_initial_queries(self, title: str, core_entity: str = "",
                                  keyword: str = "") -> list[str]:
        queries: list[str] = []
        for template in SEARCH_QUERY_TEMPLATES:
            q = template.format(
                title=title, core_entity=core_entity or title[:30],
                keyword=keyword or title[:30],
            )
            queries.append(q)
        return queries[:self._max_queries_per_round]

    def health_status(self) -> dict[str, Any]:
        if not self.searxng.enabled:
            return {"searxng_enabled": False, "searxng_ok": False, "error": "SEARXNG_BASE_URL 未配置"}
        ok = self.searxng.health_check(force=True)
        return {"searxng_enabled": True, "searxng_ok": ok, "error": self.searxng.last_error}

    def _normalize_bocha(self, item: dict[str, Any]) -> SearchResult:
        return SearchResult(
            title=str(item.get("title") or "").strip(),
            url=str(item.get("url") or "").strip(),
            summary=str(item.get("summary") or "").strip(),
            source=str(item.get("source") or "").strip(),
            published_at=item.get("published_at"),
            provider="bocha",
            score=0.5,
        )

    def _normalize_tavily(self, item: dict[str, Any]) -> SearchResult:
        return SearchResult(
            title=str(item.get("title") or "").strip(),
            url=str(item.get("url") or "").strip(),
            summary=str(item.get("summary") or "").strip(),
            source=str(item.get("source") or "").strip(),
            published_at=item.get("published_at"),
            provider="tavily",
            score=0.5,
        )

    @staticmethod
    def deduplicate(results: list[SearchResult]) -> list[SearchResult]:
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        deduped: list[SearchResult] = []

        for r in results:
            url_hash = hashlib.md5(r.url.encode()).hexdigest() if r.url else ""
            title_hash = hashlib.md5(r.title.encode()).hexdigest() if r.title else ""

            if url_hash and url_hash in seen_urls:
                continue
            if title_hash and title_hash in seen_titles:
                continue

            if url_hash:
                seen_urls.add(url_hash)
            if title_hash:
                seen_titles.add(title_hash)
            deduped.append(r)

        return deduped

    @staticmethod
    def _cache_key(
        *,
        query: str,
        freshness: str,
        max_results: int,
        categories: list[str] | None,
        language: str,
        provider: str,
    ) -> str:
        raw = {
            "query": query.strip(),
            "freshness": freshness,
            "max_results": max_results,
            "categories": categories or [],
            "language": language,
            "provider": provider,
        }
        digest = hashlib.sha1(str(raw).encode("utf-8")).hexdigest()[:24]
        return f"news_agent:search:{digest}"

    def _store_cache(self, key: str, results: list[SearchResult]) -> None:
        cache.set(key, [item.model_dump() for item in results], ttl=self._cache_ttl)


search_orchestrator = SearchOrchestrator()
