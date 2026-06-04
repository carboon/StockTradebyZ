"""Tests for news board API endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services.news_board_cache_service import NewsBoardCacheService

NOW = datetime.now(timezone.utc)


class TestNewsBoardItemsApi:
    def test_items_endpoint_does_not_call_tushare(self, test_client):
        with patch.object(NewsBoardCacheService, "get_items") as mock_get:
            mock_get.return_value = MagicMock(
                window_hours=24,
                generated_at=NOW,
                items=[],
                sources=[],
                duplicate_count=0,
                has_more=False,
                message=None,
            )
            resp = test_client.get("/api/v1/news-board/items?window_hours=24&limit=50")
            assert resp.status_code == 200
            mock_get.assert_called_once()

    def test_items_returns_empty_when_no_data(self, test_client):
        with patch.object(NewsBoardCacheService, "get_items") as mock_get:
            mock_get.return_value = MagicMock(
                window_hours=24,
                generated_at=NOW,
                items=[],
                sources=[],
                duplicate_count=0,
                has_more=False,
                message="暂无数据",
            )
            resp = test_client.get("/api/v1/news-board/items?window_hours=24&limit=50")
            assert resp.status_code == 200
            data = resp.json()
            assert data["items"] == []


class TestNewsBoardStatusApi:
    def test_status_endpoint_returns_status(self, test_client):
        with patch.object(NewsBoardCacheService, "get_status") as mock_status:
            mock_status.return_value = {
                "redis_available": True,
                "last_update": None,
                "index_count": 0,
            }
            resp = test_client.get("/api/v1/news-board/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "redis_available" in data


class TestNewsBoardRefreshApi:
    def test_refresh_endpoint_calls_service(self, test_client):
        with patch.object(NewsBoardCacheService, "update_once") as mock_update:
            mock_update.return_value = {"status": "ok", "fetched": 0, "inserted": 0, "duplicate": 0, "errors": []}
            resp = test_client.post("/api/v1/news-board/refresh")
            assert resp.status_code == 200
            mock_update.assert_called_once()

    def test_refresh_returns_error_on_failure(self, test_client):
        with patch.object(NewsBoardCacheService, "update_once") as mock_update:
            mock_update.return_value = {"status": "error", "error": "Redis down"}
            resp = test_client.post("/api/v1/news-board/refresh")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "error"
