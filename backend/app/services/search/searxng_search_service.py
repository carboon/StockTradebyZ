"""SearXNG search provider - self-hosted metasearch engine."""
from __future__ import annotations

import logging
from typing import Any

import requests

from app.config import settings
from app.agents.news_event.schemas import SearchResult
from .base import BaseSearchProvider

logger = logging.getLogger(__name__)


class SearXNGSearchProvider(BaseSearchProvider):
    """SearXNG 自托管搜索 Provider。"""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or settings.searxng_base_url or "").strip().rstrip("/")
        self._timeout = settings.search_timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

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
        if not self.enabled or not query.strip():
            return []

        if categories is None:
            categories = ["news", "general"]

        params: dict[str, Any] = {
            "q": query.strip(),
            "format": "json",
            "language": language,
            "categories": ",".join(categories),
        }

        freshness_map = {"day": "day", "week": "week", "month": "month", "year": "year"}
        if freshness in freshness_map:
            params["time_range"] = freshness_map[freshness]

        try:
            response = requests.get(
                f"{self.base_url}/search",
                params=params,
                timeout=min(timeout, self._timeout) if self._timeout else timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("SearXNG 搜索失败: query=%s error=%s", query, exc)
            return []

        return self._parse_results(data, max_results)

    def _parse_results(self, data: dict[str, Any], max_results: int) -> list[SearchResult]:
        raw_results = data.get("results") or []
        if not isinstance(raw_results, list):
            return []

        items: list[SearchResult] = []
        for raw in raw_results[:max_results]:
            if not isinstance(raw, dict):
                continue
            item = self._normalize_result(raw, "searxng")
            if item.title or item.summary:
                items.append(item)

        return items
