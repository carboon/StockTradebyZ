"""SearXNG search provider - self-hosted metasearch engine."""
from __future__ import annotations

import logging
import time
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
        self._last_health_check = 0.0
        self._last_health_ok = False
        self._last_error = ""

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    @property
    def last_error(self) -> str:
        return self._last_error

    def health_check(self, *, force: bool = False) -> bool:
        """Check whether the SearXNG JSON API is currently usable."""
        if not self.enabled:
            self._last_error = "SEARXNG_BASE_URL 未配置"
            return False
        now = time.time()
        if not force and now - self._last_health_check < 60:
            return self._last_health_ok

        self._last_health_check = now
        try:
            response = requests.get(
                f"{self.base_url}/search",
                params={
                    "q": "healthcheck",
                    "format": "json",
                    "categories": "general",
                    "language": "all",
                    "safesearch": 0,
                },
                headers=self._headers(),
                timeout=min(5, self._timeout) if self._timeout else 5,
            )
            if response.status_code == 403:
                self._last_error = "SearXNG 返回 403，请检查 settings.yml 是否启用 json format/私有 API 访问"
                self._last_health_ok = False
                return False
            response.raise_for_status()
            data = response.json()
            self._last_health_ok = isinstance(data, dict)
            self._last_error = "" if self._last_health_ok else "SearXNG 未返回 JSON object"
            return self._last_health_ok
        except Exception as exc:
            self._last_error = str(exc)
            self._last_health_ok = False
            return False

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
        if not self.health_check():
            logger.warning("SearXNG 不可用: %s", self._last_error)
            return []

        if categories is None:
            categories = ["news", "general"]

        params: dict[str, Any] = {
            "q": query.strip(),
            "format": "json",
            "language": language,
            "categories": ",".join(categories),
            "safesearch": 0,
            "pageno": 1,
        }

        freshness_map = {"day": "day", "week": "week", "month": "month", "year": "year"}
        if freshness in freshness_map:
            params["time_range"] = freshness_map[freshness]

        try:
            response = requests.get(
                f"{self.base_url}/search",
                params=params,
                headers=self._headers(),
                timeout=min(timeout, self._timeout) if self._timeout else timeout,
            )
            if response.status_code == 403:
                self._last_error = "SearXNG 返回 403"
                logger.warning("SearXNG 搜索失败: query=%s error=%s", query, self._last_error)
                return []
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("SearXNG 搜索失败: query=%s error=%s", query, exc)
            return []

        return self._parse_results(data, max_results)

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Accept": "application/json",
            "User-Agent": "StockTradebyZ/2.0 news-agent",
        }

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
