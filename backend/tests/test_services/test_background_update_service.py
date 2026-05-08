from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models import Stock, StockDaily
from app.services.background_update_service import BackgroundLatestTradeDayUpdateService


def _seed_stock_daily(test_db, *, code: str, trade_date: str) -> None:
    test_db.add(Stock(code=code, name=f"Stock {code}", market="SZ"))
    test_db.add(
        StockDaily(
            code=code,
            trade_date=date.fromisoformat(trade_date),
            open=10.0,
            close=10.2,
            high=10.3,
            low=9.9,
            volume=1000.0,
        )
    )
    test_db.commit()


def test_assess_freshness_detects_stale_db_and_csv(test_db, tmp_path, monkeypatch) -> None:
    import app.services.background_update_service as background_update_module

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "000001.csv").write_text(
        "date,open,close,high,low,volume\n2026-05-06,10,10.2,10.3,9.9,1000\n",
        encoding="utf-8",
    )

    _seed_stock_daily(test_db, code="000001", trade_date="2026-05-07")

    monkeypatch.setattr(background_update_module, "SessionLocal", lambda: test_db)
    monkeypatch.setattr(background_update_module.settings, "raw_data_dir", raw_dir)
    monkeypatch.setattr(
        background_update_module.MarketService,
        "get_latest_trade_date",
        lambda self: "2026-05-08",
    )

    service = BackgroundLatestTradeDayUpdateService()
    status = service.assess_freshness()

    assert status.latest_trade_date == "2026-05-08"
    assert status.latest_db_date == "2026-05-07"
    assert status.latest_csv_date == "2026-05-06"
    assert status.db_needs_update is True
    assert status.csv_needs_update is True
    assert status.needs_update is True


def test_run_skips_when_data_is_latest(test_db, tmp_path, monkeypatch) -> None:
    import app.services.background_update_service as background_update_module

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "000001.csv").write_text(
        "date,open,close,high,low,volume\n2026-05-08,10,10.2,10.3,9.9,1000\n",
        encoding="utf-8",
    )

    _seed_stock_daily(test_db, code="000001", trade_date="2026-05-08")

    monkeypatch.setattr(background_update_module, "SessionLocal", lambda: test_db)
    monkeypatch.setattr(background_update_module.settings, "raw_data_dir", raw_dir)
    monkeypatch.setattr(
        background_update_module.MarketService,
        "get_latest_trade_date",
        lambda self: "2026-05-08",
    )
    monkeypatch.setattr(
        background_update_module.analysis_service,
        "get_latest_candidate_date",
        lambda: "2026-05-08",
    )
    monkeypatch.setattr(
        background_update_module.analysis_service,
        "get_latest_result_date",
        lambda: "2026-05-08",
    )

    called = {"batch": False, "star": False}

    class _UnexpectedBatchService:
        def __init__(self, *args, **kwargs):
            called["batch"] = True

    monkeypatch.setattr(background_update_module, "DailyBatchUpdateService", _UnexpectedBatchService)

    def _unexpected_star(*args, **kwargs):
        called["star"] = True
        return {}

    monkeypatch.setattr(background_update_module, "maintain_tomorrow_star_for_trade_date", _unexpected_star)

    service = BackgroundLatestTradeDayUpdateService()
    result = service.run()

    assert result["success"] is True
    assert result["skipped"] is True
    assert called["batch"] is False
    assert called["star"] is False


def test_run_fails_after_1630_when_latest_trade_date_data_not_ready(test_db, tmp_path, monkeypatch) -> None:
    import app.services.background_update_service as background_update_module

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "000001.csv").write_text(
        "date,open,close,high,low,volume\n2026-05-07,10,10.2,10.3,9.9,1000\n",
        encoding="utf-8",
    )

    _seed_stock_daily(test_db, code="000001", trade_date="2026-05-07")

    monkeypatch.setattr(background_update_module, "SessionLocal", lambda: test_db)
    monkeypatch.setattr(background_update_module.settings, "raw_data_dir", raw_dir)
    monkeypatch.setattr(
        background_update_module.MarketService,
        "get_latest_trade_date",
        lambda self: "2026-05-08",
    )
    monkeypatch.setattr(
        background_update_module.analysis_service,
        "get_latest_candidate_date",
        lambda: "2026-05-07",
    )
    monkeypatch.setattr(
        background_update_module.analysis_service,
        "get_latest_result_date",
        lambda: "2026-05-07",
    )
    monkeypatch.setattr(
        background_update_module.BackgroundLatestTradeDayUpdateService,
        "_is_retry_window_open",
        classmethod(lambda cls, now=None: True),
    )
    monkeypatch.setattr(
        background_update_module.TushareService,
        "is_trade_date_data_ready",
        lambda self, trade_date: False,
    )

    service = BackgroundLatestTradeDayUpdateService()

    try:
        service.run()
        assert False, "expected run() to fail for systemd retry"
    except RuntimeError as exc:
        assert "10 分钟后重试" in str(exc)


def test_run_does_not_fail_before_1630_when_latest_trade_date_data_not_ready(test_db, tmp_path, monkeypatch) -> None:
    import app.services.background_update_service as background_update_module

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "000001.csv").write_text(
        "date,open,close,high,low,volume\n2026-05-08,10,10.2,10.3,9.9,1000\n",
        encoding="utf-8",
    )

    _seed_stock_daily(test_db, code="000001", trade_date="2026-05-08")

    monkeypatch.setattr(background_update_module, "SessionLocal", lambda: test_db)
    monkeypatch.setattr(background_update_module.settings, "raw_data_dir", raw_dir)
    monkeypatch.setattr(
        background_update_module.MarketService,
        "get_latest_trade_date",
        lambda self: "2026-05-08",
    )
    monkeypatch.setattr(
        background_update_module.analysis_service,
        "get_latest_candidate_date",
        lambda: "2026-05-08",
    )
    monkeypatch.setattr(
        background_update_module.analysis_service,
        "get_latest_result_date",
        lambda: "2026-05-08",
    )
    monkeypatch.setattr(
        background_update_module.BackgroundLatestTradeDayUpdateService,
        "_is_retry_window_open",
        classmethod(lambda cls, now=None: False),
    )
    monkeypatch.setattr(
        background_update_module.TushareService,
        "is_trade_date_data_ready",
        lambda self, trade_date: False,
    )

    service = BackgroundLatestTradeDayUpdateService()
    result = service.run()

    assert result["success"] is True
    assert result["skipped"] is True


def test_run_executes_batch_and_tomorrow_star_when_update_needed(test_db, tmp_path, monkeypatch) -> None:
    import app.services.background_update_service as background_update_module

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "000001.csv").write_text(
        "date,open,close,high,low,volume\n2026-05-07,10,10.2,10.3,9.9,1000\n",
        encoding="utf-8",
    )

    _seed_stock_daily(test_db, code="000001", trade_date="2026-05-07")

    monkeypatch.setattr(background_update_module, "SessionLocal", lambda: test_db)
    monkeypatch.setattr(background_update_module.settings, "raw_data_dir", raw_dir)
    monkeypatch.setattr(
        background_update_module.MarketService,
        "get_latest_trade_date",
        lambda self: "2026-05-08",
    )
    monkeypatch.setattr(
        background_update_module.MarketService,
        "update_cache",
        lambda self, latest_date: None,
    )
    monkeypatch.setattr(
        BackgroundLatestTradeDayUpdateService,
        "_load_tomorrow_star_run_stats",
        staticmethod(
            lambda trade_date: {
                "candidate_count": 5,
                "analysis_count": 5,
                "trend_start_count": 2,
                "consecutive_candidate_count": 1,
            }
        ),
    )

    calls: list[str] = []

    class _FakeBatchService:
        def __init__(self, *args, **kwargs):
            calls.append("batch_init")

        def __enter__(self):
            calls.append("batch_enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            calls.append("batch_exit")

        def update_trade_date(self, trade_date, source, progress_callback):
            calls.append(f"batch_update:{trade_date}:{source}")
            progress_callback({"stage": "daily_batch_fetch", "message": "抓取开始"})
            progress_callback({"stage": "daily_batch_load_db", "message": "入库完成"})
            return {
                "ok": True,
                "trade_date": trade_date,
                "record_count": 2,
                "stock_count": 1,
                "db_stock_count": 1,
            }

    monkeypatch.setattr(background_update_module, "DailyBatchUpdateService", _FakeBatchService)
    monkeypatch.setattr(
        background_update_module,
        "maintain_tomorrow_star_for_trade_date",
        lambda trade_date, reviewer, source, window_size: {
            "build": {"success": True, "pick_date": trade_date},
            "prune": {"deleted_dates": []},
        },
    )

    service = BackgroundLatestTradeDayUpdateService()
    result = service.run()

    assert result["success"] is True
    assert result["skipped"] is False
    assert result["trade_date"] == "2026-05-08"
    assert result["timings"]["tomorrow_star_rebuild"] >= 0
    assert "daily_batch_fetch" in result["timings"]
    assert "daily_batch_load_db" in result["timings"]
    assert calls[:3] == ["batch_init", "batch_enter", "batch_update:2026-05-08:background_cli"]


def test_run_rebuilds_tomorrow_star_when_market_data_is_latest(test_db, tmp_path, monkeypatch) -> None:
    import app.services.background_update_service as background_update_module

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "000001.csv").write_text(
        "date,open,close,high,low,volume\n2026-05-08,10,10.2,10.3,9.9,1000\n",
        encoding="utf-8",
    )

    _seed_stock_daily(test_db, code="000001", trade_date="2026-05-08")

    monkeypatch.setattr(background_update_module, "SessionLocal", lambda: test_db)
    monkeypatch.setattr(background_update_module.settings, "raw_data_dir", raw_dir)
    monkeypatch.setattr(
        background_update_module.MarketService,
        "get_latest_trade_date",
        lambda self: "2026-05-08",
    )
    monkeypatch.setattr(
        background_update_module.MarketService,
        "update_cache",
        lambda self, latest_date: None,
    )
    monkeypatch.setattr(
        background_update_module.analysis_service,
        "get_latest_candidate_date",
        lambda: "2026-05-08",
    )
    monkeypatch.setattr(
        background_update_module.analysis_service,
        "get_latest_result_date",
        lambda: "2026-05-06",
    )
    monkeypatch.setattr(
        BackgroundLatestTradeDayUpdateService,
        "_load_tomorrow_star_run_stats",
        staticmethod(
            lambda trade_date: {
                "candidate_count": 5,
                "analysis_count": 5,
                "trend_start_count": 2,
                "consecutive_candidate_count": 1,
            }
        ),
    )

    called = {"batch": False, "star": False}

    class _UnexpectedBatchService:
        def __init__(self, *args, **kwargs):
            called["batch"] = True

    monkeypatch.setattr(background_update_module, "DailyBatchUpdateService", _UnexpectedBatchService)

    def _fake_star(*args, **kwargs):
        called["star"] = True
        return {
            "build": {"success": True, "pick_date": "2026-05-08"},
            "prune": {"deleted_dates": []},
        }

    monkeypatch.setattr(background_update_module, "maintain_tomorrow_star_for_trade_date", _fake_star)

    service = BackgroundLatestTradeDayUpdateService()
    result = service.run()

    assert result["success"] is True
    assert result["skipped"] is False
    assert result["freshness"]["needs_market_update"] is False
    assert result["freshness"]["needs_tomorrow_star_rebuild"] is True
    assert called["batch"] is False
    assert called["star"] is True
