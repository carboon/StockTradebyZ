"""Tests for market sentiment API."""
from __future__ import annotations

from unittest.mock import patch


def test_get_current_market_sentiment(test_client):
    payload = {
        "status": "ok",
        "provider": "gjzq",
        "score": 51.0,
        "level": "neutral",
        "level_label": "情绪中性",
        "interpretation": "市场情绪处于中性区间。",
        "risk_hint": "结合成交确认。",
        "updated_at": None,
        "fetched_at": "2026-06-08T00:00:00+00:00",
        "cached": False,
        "stale": False,
    }
    with patch("app.api.market_sentiment.market_sentiment_service.get_current", return_value=payload) as mock_get:
        resp = test_client.get("/api/v1/market-sentiment/current")

    assert resp.status_code == 200
    assert resp.json()["score"] == 51.0
    mock_get.assert_called_once_with(force_refresh=False)
