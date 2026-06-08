"""External A-share market sentiment pulse service."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from app.cache import RedisCache
from app.config import settings

logger = logging.getLogger(__name__)

_cache = RedisCache(default_ttl=360)


class MarketSentimentService:
    """Fetch and cache the external A-share sentiment pulse index."""

    CACHE_KEY = "market:sentiment:gjzq"

    def get_current(self, force_refresh: bool = False) -> dict[str, Any]:
        if not settings.market_sentiment_enabled:
            return self._unavailable("disabled", "市场情绪服务未启用")

        if not force_refresh:
            cached = _cache.get(self.CACHE_KEY)
            if isinstance(cached, dict):
                cached["cached"] = True
                return cached

        if not settings.gjzq_sentiment_mcp_url.strip():
            return self._unavailable("not_configured", "未配置 GJZQ_SENTIMENT_MCP_URL")

        try:
            payload = self._fetch_remote()
            normalized = self._normalize(payload)
            _cache.set(
                self.CACHE_KEY,
                normalized,
                ttl=settings.market_sentiment_cache_ttl_seconds,
            )
            return normalized
        except Exception as exc:
            logger.warning("获取国金证券 A 股情绪指数失败: %s", exc)
            cached = _cache.get(self.CACHE_KEY)
            if isinstance(cached, dict):
                cached["cached"] = True
                cached["stale"] = True
                cached["message"] = f"远程获取失败，使用缓存: {exc}"
                return cached
            return self._unavailable("fetch_failed", f"获取失败: {exc}")

    def _fetch_remote(self) -> Any:
        url = settings.gjzq_sentiment_mcp_url.strip()
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        api_key = settings.gjzq_sentiment_api_key.strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            headers["X-API-Key"] = api_key

        if url.rstrip("/").endswith("/getSentiment"):
            direct_response = requests.post(
                url,
                json={},
                headers=headers,
                timeout=settings.market_sentiment_timeout_seconds,
            )
            if direct_response.ok:
                return self._parse_response(direct_response)
            logger.warning(
                "国金情绪直连接口失败: status=%s body=%s",
                direct_response.status_code,
                direct_response.text[:200],
            )

        payload = {
            "jsonrpc": "2.0",
            "id": "getSentiment",
            "method": "tools/call",
            "params": {"name": "getSentiment", "arguments": {}},
        }
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=settings.market_sentiment_timeout_seconds,
        )
        if response.status_code in {404, 405}:
            response = requests.get(
                url,
                headers=headers,
                timeout=settings.market_sentiment_timeout_seconds,
            )
        response.raise_for_status()
        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: requests.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        text = response.text.strip()
        if "text/event-stream" in content_type or text.startswith("event:") or text.startswith("data:"):
            data_lines = [
                line.removeprefix("data:").strip()
                for line in text.splitlines()
                if line.startswith("data:")
            ]
            if data_lines:
                import json

                return json.loads(data_lines[-1])
        return response.json()

    def _normalize(self, payload: Any) -> dict[str, Any]:
        data = self._unwrap_payload(payload)
        score = self._extract_score(data)
        if score is None:
            raise ValueError("远程结果中未找到情绪指数")

        score = max(0.0, min(100.0, float(score)))
        level = self._level(score)
        return {
            "status": "ok",
            "provider": "gjzq",
            "score": round(score, 2),
            "level": level,
            "level_label": self._level_label(level),
            "interpretation": self._interpretation(score),
            "risk_hint": self._risk_hint(score),
            "updated_at": self._extract_updated_at(data),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "stale": False,
            "raw": data if isinstance(data, dict) else {},
        }

    @classmethod
    def _unwrap_payload(cls, payload: Any) -> Any:
        data = payload
        if isinstance(data, dict) and "result" in data:
            data = data["result"]
        if isinstance(data, dict) and "content" in data and isinstance(data["content"], list):
            for item in data["content"]:
                if isinstance(item, dict) and item.get("type") == "json":
                    return item.get("json")
                if isinstance(item, dict) and item.get("text"):
                    return cls._try_json(item["text"])
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        return cls._try_json(data)

    @staticmethod
    def _try_json(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        import json

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    @staticmethod
    def _extract_score(data: Any) -> float | None:
        if isinstance(data, (int, float)):
            return float(data)
        if not isinstance(data, dict):
            return None
        keys = (
            "sentiment",
            "sentiment_index",
            "sentimentIndex",
            "index",
            "score",
            "value",
            "pulse",
        )
        for key in keys:
            value = data.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _extract_updated_at(data: Any) -> str | None:
        if not isinstance(data, dict):
            return None
        for key in ("updated_at", "updatedAt", "time", "timestamp", "datetime"):
            value = data.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _level(score: float) -> str:
        if score >= 85:
            return "extreme_high"
        if score > 75:
            return "high"
        if score < 15:
            return "extreme_low"
        if score < 25:
            return "low"
        return "neutral"

    @staticmethod
    def _level_label(level: str) -> str:
        return {
            "extreme_high": "极度亢奋",
            "high": "情绪偏热",
            "neutral": "情绪中性",
            "low": "情绪低迷",
            "extreme_low": "极度低迷",
        }.get(level, "未知")

    @staticmethod
    def _interpretation(score: float) -> str:
        if score > 75:
            return "市场情绪较亢奋，投资者风险偏好偏高。"
        if score < 25:
            return "市场情绪较低迷，投资者信心偏弱。"
        return "市场情绪处于中性区间，需结合成交和板块扩散确认。"

    @staticmethod
    def _risk_hint(score: float) -> str:
        if score > 75:
            return "短线利好更容易被快速兑现，追高需关注回调风险。"
        if score < 25:
            return "低位利好可能形成修复催化，但持续性需要成交放大确认。"
        return "新闻影响主要看事件确定性、产业链映射和盘口承接。"

    @staticmethod
    def _unavailable(reason: str, message: str) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "provider": "gjzq",
            "reason": reason,
            "message": message,
            "score": None,
            "level": "unknown",
            "level_label": "未接入",
            "interpretation": "",
            "risk_hint": "",
            "updated_at": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "stale": False,
        }


market_sentiment_service = MarketSentimentService()
