"""Tavily web search service for company evidence lookup.

Replaces BochaSearchService with Tavily API - already integrated for hot news.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Config

logger = logging.getLogger(__name__)


class TavilySearchService:
    """Tavily AI 搜索封装，用于公司画像证据检索。"""

    API_URL = "https://api.tavily.com/search"

    def __init__(self, db: Session, api_key: str | None = None) -> None:
        self.db = db
        self.api_key = str(api_key or self._load_config_or_env("tavily_api_key", settings.tavily_api_key) or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(
        self,
        query: str,
        *,
        count: int = 5,
        freshness: str = "oneYear",
        timeout: int = 15,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not self.enabled or not query:
            return []

        payload: dict[str, Any] = {
            "query": query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": max(1, min(int(count or 5), 10)),
            "include_answer": False,
            "include_raw_content": False,
        }
        if freshness == "oneYear":
            payload["days"] = 365

        try:
            response = requests.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("Tavily 搜索失败: query=%s error=%s", query, exc)
            return []

        return self._normalize_results(data)

    def _load_config_or_env(self, key: str, env_value: str) -> str:
        try:
            if self.db is not None:
                value = self.db.query(Config.value).filter(Config.key == key).scalar()
                if value:
                    return str(value).strip()
        except Exception:
            pass
        return str(env_value or "").strip()

    @staticmethod
    def _normalize_results(data: dict[str, Any]) -> list[dict[str, Any]]:
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            return []

        items: list[dict[str, Any]] = []
        for raw in results:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            url = str(raw.get("url") or "").strip()
            summary = str(raw.get("content") or raw.get("snippet") or "").strip()
            if not title and not summary:
                continue
            items.append(
                {
                    "title": title,
                    "url": url,
                    "summary": summary,
                    "published_at": raw.get("published_date"),
                    "source": raw.get("source"),
                }
            )
        return items
