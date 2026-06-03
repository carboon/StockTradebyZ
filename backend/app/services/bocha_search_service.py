"""Bocha web search service for company evidence lookup."""
from __future__ import annotations

import logging
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Config

logger = logging.getLogger(__name__)


class BochaSearchService:
    """独立 Bocha 搜索封装，用于公司画像证据检索。"""

    API_URL = "https://api.bochaai.com/v1/web-search"

    def __init__(self, db: Session, api_key: str | None = None) -> None:
        self.db = db
        self.api_key = str(api_key or self._load_config_or_env("bocha_api_key", settings.bocha_api_key) or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def search(
        self,
        query: str,
        *,
        count: int = 5,
        freshness: str = "oneYear",
        timeout: int = 20,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not self.enabled or not query:
            return []

        payload = {
            "query": query,
            "count": max(1, min(int(count or 5), 10)),
            "freshness": freshness,
            "summary": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(self.API_URL, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("Bocha 搜索失败: query=%s error=%s", query, exc)
            return []

        return self._normalize_results(data)

    def _load_config_or_env(self, key: str, env_value: str) -> str:
        value = self.db.query(Config.value).filter(Config.key == key).scalar()
        return str(value or env_value or "").strip()

    @staticmethod
    def _normalize_results(data: dict[str, Any]) -> list[dict[str, Any]]:
        raw_items = []
        if isinstance(data.get("data"), dict):
            web_pages = data["data"].get("webPages")
            if isinstance(web_pages, dict):
                raw_items = web_pages.get("value") or []
            elif isinstance(data["data"].get("value"), list):
                raw_items = data["data"].get("value") or []
        elif isinstance(data.get("webPages"), dict):
            raw_items = data["webPages"].get("value") or []
        elif isinstance(data.get("value"), list):
            raw_items = data.get("value") or []

        items: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("name") or raw.get("title") or "").strip()
            url = str(raw.get("url") or raw.get("link") or "").strip()
            summary = str(raw.get("summary") or raw.get("snippet") or raw.get("description") or "").strip()
            if not title and not summary:
                continue
            items.append(
                {
                    "title": title,
                    "url": url,
                    "summary": summary,
                    "published_at": raw.get("datePublished") or raw.get("published_at") or raw.get("date"),
                    "source": raw.get("siteName") or raw.get("site") or raw.get("displayUrl"),
                }
            )
        return items
