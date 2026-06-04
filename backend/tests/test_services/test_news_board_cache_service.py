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

    def test_entity_bucket_duplicate_uses_similarity(self):
        from app.services.news_board_cache_service import (
            ENTITY_BUCKET_SECONDS,
            KEY_FINGERPRINT_PREFIX,
            KEY_ITEM_PREFIX,
            NewsBoardCacheService,
        )

        svc = NewsBoardCacheService()
        event_ts = utc_ts(hours_ago=1)
        existing = make_item(id="dup-base", title="英伟达发布新一代AI芯片", event_ts=event_ts)
        incoming = make_item(id="dup-new", title="英伟达发布新一代 AI 芯片", event_ts=event_ts)
        fps = svc.build_news_fingerprints(existing)
        bucket = int(event_ts // ENTITY_BUCKET_SECONDS)
        bucket_fp = f"{fps['entity']}:{bucket}"

        svc._cache.set(f"{KEY_ITEM_PREFIX}{existing.id}", existing.model_dump(mode="json"), ttl=3600)
        svc._cache.set(f"{KEY_FINGERPRINT_PREFIX}{bucket_fp}", existing.id, ttl=3600)

        is_dup, key = svc.is_duplicate(incoming)
        assert is_dup
        assert key == bucket_fp

        svc._cache.delete(f"{KEY_ITEM_PREFIX}{existing.id}")
        svc._cache.delete(f"{KEY_FINGERPRINT_PREFIX}{bucket_fp}")


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

    def test_read_skips_stale_members_and_reports_has_more(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        svc._cache._redis_available = True
        raw_mock = MagicMock()
        raw_mock.ping.return_value = True
        svc._cache._redis = raw_mock

        raw_mock.zrevrangebyscore.return_value = [
            ("stale", _score(3)),
            ("r1", _score(2)),
            ("r2", _score(1)),
        ]
        raw_mock.mget.return_value = [
            None,
            _item_json("r1", "First visible"),
            _item_json("r2", "Second visible"),
        ]
        raw_mock.zrem.return_value = 1

        result = svc.get_items(window_hours=24, limit=1)

        assert len(result.items) == 1
        assert result.items[0].id == "r1"
        assert result.has_more is True
        raw_mock.zrem.assert_called_once()

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
            with patch.object(svc, "update_sync_watermark") as mock_watermark:
                with patch.object(svc, "_store_status"):
                    r = svc._do_update(now=datetime.now(timezone.utc))
                    assert len(r["errors"]) > 0
                    mock_watermark.assert_not_called()

    def test_missing_token_does_not_update_watermark(self):
        from app.services.news_board_cache_service import NewsBoardCacheService

        svc = NewsBoardCacheService()
        svc._cache._redis_available = True
        raw_mock = MagicMock()
        raw_mock.ping.return_value = True
        raw_mock.zremrangebyscore.return_value = 0
        svc._cache._redis = raw_mock

        with patch.object(svc, "fetch_tushare_source", return_value=([], "Tushare token 未配置")):
            with patch.object(svc, "update_sync_watermark") as mock_watermark:
                r = svc._do_update(now=datetime.now(timezone.utc))
                assert r["sources_updated"] == 0
                assert len(r["errors"]) > 0
                mock_watermark.assert_not_called()



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
