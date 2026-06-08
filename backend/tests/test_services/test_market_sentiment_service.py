"""Tests for MarketSentimentService."""
from __future__ import annotations

from app.config import settings
from app.services.market_sentiment_service import MarketSentimentService


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self.text = str(payload)
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"status={self.status_code}")


def test_market_sentiment_returns_unavailable_without_url(monkeypatch):
    monkeypatch.setattr(settings, "market_sentiment_enabled", True)
    monkeypatch.setattr(settings, "gjzq_sentiment_mcp_url", "")

    result = MarketSentimentService().get_current(force_refresh=True)

    assert result["status"] == "unavailable"
    assert result["reason"] == "not_configured"


def test_market_sentiment_normalizes_mcp_tool_result():
    result = MarketSentimentService()._normalize({
        "jsonrpc": "2.0",
        "result": {
            "content": [
                {
                    "type": "json",
                    "json": {
                        "sentiment_index": 82.4,
                        "updated_at": "2026-06-08 10:30:00",
                    },
                }
            ]
        },
    })

    assert result["status"] == "ok"
    assert result["score"] == 82.4
    assert result["level"] == "high"
    assert "兑现" in result["risk_hint"]


def test_market_sentiment_direct_get_sentiment_endpoint(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return _FakeResponse({"sentiment_index": 23.5, "updated_at": "2026-06-08 10:35:00"})

    monkeypatch.setattr(settings, "gjzq_sentiment_mcp_url", "https://example.com/getSentiment")
    monkeypatch.setattr(settings, "gjzq_sentiment_api_key", "gjzqtest")
    monkeypatch.setattr("app.services.market_sentiment_service.requests.post", fake_post)

    payload = MarketSentimentService()._fetch_remote()

    assert payload["sentiment_index"] == 23.5
    assert calls[0]["json"] == {}
    assert calls[0]["headers"]["Authorization"] == "Bearer gjzqtest"
