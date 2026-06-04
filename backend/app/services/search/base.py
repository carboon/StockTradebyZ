"""Base search provider interface for web_search tool."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.agents.news_event.schemas import SearchResult


class BaseSearchProvider(ABC):
    """可替换的搜索 Provider 抽象基类。"""

    @property
    @abstractmethod
    def enabled(self) -> bool:
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        freshness: str = "day",
        max_results: int = 8,
        categories: list[str] | None = None,
        language: str = "zh-CN",
        timeout: int = 12,
    ) -> list[SearchResult]:
        ...

    @staticmethod
    def _normalize_result(raw: dict[str, Any], provider: str) -> SearchResult:
        title = str(raw.get("title") or raw.get("name") or "").strip()
        url = str(raw.get("url") or raw.get("link") or "").strip()
        summary = str(raw.get("summary") or raw.get("content") or raw.get("snippet") or raw.get("description") or "").strip()
        source = str(raw.get("source") or raw.get("siteName") or raw.get("site") or raw.get("displayUrl") or "").strip()
        published_at = raw.get("published_at") or raw.get("publishedAt") or raw.get("datePublished") or raw.get("date") or raw.get("published_date")
        score = float(raw.get("score") or raw.get("relevance") or 0.0)

        return SearchResult(
            title=title,
            url=url,
            summary=summary,
            source=source,
            published_at=str(published_at) if published_at else None,
            provider=provider,
            score=score,
        )
