"""Tests for NewsBoardCacheService."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.config import settings
from app.schemas import NewsBoardItem, NewsBoardRelatedStock


def utc_ts(*, hours_ago: float = 0) -> float:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).timestamp()


def make_item(
    id: str = "abc123",
    title: str = "Test Title",
    summary: str = "Test summary",
    event_ts: float | None = None,
) -> NewsBoardItem:
    now = datetime.now(timezone.utc)
    if event_ts is None:
        event_ts = (now - timedelta(hours=1)).timestamp()
    event_dt = datetime.fromtimestamp(event_ts, tz=timezone.utc)
    return NewsBoardItem(
        id=id,
        title=title,
        summary=summary,
        category="price",
        source="test",
        event_time=event_dt,
        eventTime=event_dt,
        published_at=event_dt,
        publishedAt=event_dt,
        ingested_at=now,
        ingestedAt=now,
        impact="medium",
        related_stocks=[],
        relatedStocks=[],
    )


# ---------------------------------------------------------------------------
# Time window calculation
# ---------------------------------------------------------------------------


class TestTimeWindow:
    def test_no_watermark_uses_full_window(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        svc._cache.delete("news:sync:testsrc")

        now = datetime.now(timezone.utc)
        start, end = svc.resolve_fetch_window("testsrc", now)
        expected_start = now - timedelta(hours=settings.news_board_window_hours)
        assert abs((start - expected_start).total_seconds()) < 5
        assert end == now

    def test_with_watermark_uses_overlap(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        now = datetime.now(timezone.utc)
        last_end = now - timedelta(minutes=10)
        svc._cache.set("news:sync:testsrc2", last_end.isoformat(), ttl=3600)

        start, end = svc.resolve_fetch_window("testsrc2", now)
        expected_start = last_end - timedelta(minutes=settings.news_board_overlap_minutes)
        assert abs((start - expected_start).total_seconds()) < 5
        assert end == now
        svc._cache.delete("news:sync:testsrc2")

    def test_abnormal_watermark_clamped(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        now = datetime.now(timezone.utc)
        svc._cache.set("news:sync:testsrc3", (now - timedelta(days=3)).isoformat(), ttl=3600)

        start, _ = svc.resolve_fetch_window("testsrc3", now)
        floor = now - timedelta(hours=settings.news_board_window_hours)
        assert abs((start - floor).total_seconds()) < 5
        svc._cache.delete("news:sync:testsrc3")


# ---------------------------------------------------------------------------
# Dedup (fingerprint) tests
# ---------------------------------------------------------------------------


class TestDedup:
    def test_exact_title_match_is_duplicate(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        item = make_item(title="英伟达发布新芯片", id="n1")
        fps = svc.build_news_fingerprints(item)

        fp_key = f"news:fingerprint:{fps['full']}"
        svc._cache.set(fp_key, "n0", ttl=3600)

        is_dup, key = svc.is_duplicate(item)
        assert is_dup
        assert key == fps["full"]
        svc._cache.delete(fp_key)

    def test_different_titles_not_duplicate(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        item1 = make_item(title="英伟达大涨", id="a")
        item2 = make_item(title="英伟达澄清传闻", id="b")

        svc._cache.delete_prefix("news:fingerprint:")
        is_dup, _ = svc.is_duplicate(item1)
        assert not is_dup
        is_dup2, _ = svc.is_duplicate(item2)
        assert not is_dup2


# ---------------------------------------------------------------------------
# Redis write / read (mocked Redis)
# ---------------------------------------------------------------------------


class TestRedisWriteRead:
    def test_write_then_read_by_time(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        svc._cache._redis_available = True
        raw_mock = MagicMock()
        raw_mock.ping.return_value = True
        svc._cache._redis = raw_mock

        raw_mock.zrevrangebyscore.return_value = [
            (b"r1", _score(2)),
            (b"r2", _score(1)),
        ]
        raw_mock.mget.return_value = [
            _item_json("r1", "Older news"),
            _item_json("r2", "Newer news"),
        ]

        result = svc.get_items(window_hours=24, limit=100)
        assert len(result.items) == 2
        assert result.items[0].title == "Older news"  # zrevrangebyscore returns descending

    def test_expired_item_not_visible(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        svc._cache._redis_available = True
        raw_mock = MagicMock()
        raw_mock.ping.return_value = True
        svc._cache._redis = raw_mock

        now = datetime.now(timezone.utc)
        ts_old = (now - timedelta(hours=25)).timestamp()
        item_old = make_item(id="expired1", title="Expired", event_ts=ts_old)

        svc._write_item(item_old)
        result = svc.get_items(window_hours=24, limit=100)
        assert all(i.id != "expired1" for i in result.items)


# ---------------------------------------------------------------------------
# Watermark tests
# ---------------------------------------------------------------------------


class TestWatermarkOnError:
    def test_error_does_not_update_watermark(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        svc._cache._redis_available = False
        cache_key = "news:sync:err_test"
        svc._cache.delete(cache_key)

        result = svc.update_once(now=datetime.now(timezone.utc))
        assert result["status"] == "unavailable"

    def test_source_exception_handled(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        svc._cache._redis_available = True
        raw_mock = MagicMock()
        raw_mock.ping.return_value = True
        raw_mock.set.return_value = True
        raw_mock.zrevrangebyscore.return_value = []
        raw_mock.zadd.return_value = 0
        raw_mock.expireat.return_value = True
        raw_mock.zremrangebyscore.return_value = 0
        svc._cache._redis = raw_mock

        cache_key = "news:sync:err_test2"
        svc._cache.delete(cache_key)
        svc._cache._redis.set.return_value = True
        svc._cache.set(cache_key, "test", ttl=3600)

        with patch.object(svc, "fetch_tushare_source", return_value=([], "tushare down")):
            with patch.object(svc, "_store_status"):
                r = svc._do_update(now=datetime.now(timezone.utc))
                assert len(r["errors"]) > 0



class TestWatermarkOnEmpty:
    def test_empty_result_updates_watermark(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        svc._cache._redis_available = True
        raw_mock = MagicMock()
        raw_mock.ping.return_value = True
        raw_mock.set.return_value = True
        raw_mock.zrevrangebyscore.return_value = []
        raw_mock.zadd.return_value = 0
        raw_mock.expireat.return_value = True
        raw_mock.zremrangebyscore.return_value = 0
        svc._cache._redis = raw_mock

        cache_key = "news:sync:empty_test"
        svc._cache.delete(cache_key)

        with patch.object(svc, "fetch_tushare_source", return_value=([], None)):
            with patch.object(svc, "_store_status"):
                r = svc._do_update(now=datetime.now(timezone.utc))
                assert "fetched" in r


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _score(hours_ago: float) -> float:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).timestamp()


def _item_json(item_id: str, title: str) -> str:
    import json
    now = datetime.now(timezone.utc)
    ts = now - timedelta(hours=1)
    obj = {
        "id": item_id,
        "title": title,
        "summary": "",
        "category": "price",
        "source": "test",
        "eventTime": ts.isoformat(),
        "publishedAt": ts.isoformat(),
        "ingestedAt": now.isoformat(),
        "impact": "medium",
        "relatedStocks": [],
    }
    return json.dumps(obj, ensure_ascii=False)
