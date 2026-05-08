from pathlib import Path
from datetime import timezone
from unittest.mock import patch

import pandas as pd

import app.services.market_service as market_service_module
from app.config import settings
from app.services.market_service import MarketService
from app.time_utils import utc_now


def test_incremental_update_includes_end_date_when_local_csv_is_previous_day(tmp_path, monkeypatch) -> None:
    root = tmp_path
    pipeline_dir = root / "pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"symbol": ["000001"]}).to_csv(pipeline_dir / "stocklist.csv", index=False)

    raw_dir = root / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "date": ["2026-04-28"],
            "open": [11.36],
            "close": [11.46],
            "high": [11.50],
            "low": [11.20],
            "volume": [1000000],
        }
    ).to_csv(raw_dir / "000001.csv", index=False)

    run_dir = root / "data" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(market_service_module, "ROOT", root)
    monkeypatch.setattr(market_service_module, "RUN_DIR", run_dir)
    monkeypatch.setattr(settings, "raw_data_dir", Path("data/raw"))
    monkeypatch.setattr(MarketService, "get_latest_trade_date", lambda self: "2026-04-29")
    monkeypatch.setattr(MarketService, "update_cache", lambda self, latest_date: None)
    monkeypatch.setattr(settings, "database_url_env", "postgresql://test:test@localhost:5432/test")

    captured = {}

    def fake_fetch_one_incremental(code, end, out_dir, progress_callback=None, db_url=None):
        captured["code"] = code
        captured["end"] = end
        captured["out_dir"] = out_dir
        captured["db_url"] = db_url
        pd.DataFrame(
            {
                "date": ["2026-04-28", "2026-04-29"],
                "open": [11.36, 11.50],
                "close": [11.46, 11.60],
                "high": [11.50, 11.70],
                "low": [11.20, 11.30],
                "volume": [1000000, 1200000],
            }
        ).to_csv(raw_dir / "000001.csv", index=False)
        return {"code": code, "success": True, "updated": True, "new_count": 1, "error": None}

    with patch("pipeline.fetch_kline.fetch_one_incremental", side_effect=fake_fetch_one_incremental):
        service = MarketService(token="test_token_123456")
        result = service.incremental_update(end_date="2026-04-29")

    assert result["ok"] is True
    assert result["updated"] == 1
    assert result["skipped"] == 0
    assert captured["code"] == "000001"
    assert captured["end"] == "20260429"
    assert captured["db_url"] == "postgresql://test:test@localhost:5432/test"

    updated_df = pd.read_csv(raw_dir / "000001.csv")
    updated_df["date"] = pd.to_datetime(updated_df["date"])
    assert updated_df["date"].max() == pd.Timestamp("2026-04-29")


def test_incremental_update_resolves_920_code_from_stocklist(tmp_path, monkeypatch) -> None:
    root = tmp_path
    pipeline_dir = root / "pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "ts_code": ["920964.BJ"],
            "symbol": ["920964"],
            "name": ["润农节水"],
            "area": ["河北"],
            "industry": ["建筑工程"],
        }
    ).to_csv(pipeline_dir / "stocklist.csv", index=False)

    raw_dir = root / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"]).to_csv(
        raw_dir / "920964.csv",
        index=False,
    )

    run_dir = root / "data" / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(market_service_module, "ROOT", root)
    monkeypatch.setattr(market_service_module, "RUN_DIR", run_dir)
    monkeypatch.setattr(settings, "raw_data_dir", Path("data/raw"))
    monkeypatch.setattr(MarketService, "get_latest_trade_date", lambda self: "2026-04-29")
    monkeypatch.setattr(MarketService, "update_cache", lambda self, latest_date: None)
    monkeypatch.setattr(settings, "database_url_env", "postgresql://test:test@localhost:5432/test")

    captured_codes: list[str] = []

    def fake_fetch_one_incremental(code, end, out_dir, progress_callback=None, db_url=None):
        captured_codes.append(code)
        pd.DataFrame(
            {
                "date": ["2026-04-29"],
                "open": [8.88],
                "close": [9.12],
                "high": [9.20],
                "low": [8.80],
                "volume": [200000],
            }
        ).to_csv(raw_dir / "920964.csv", index=False)
        return {"code": code, "success": True, "updated": True, "new_count": 1, "error": None}

    with patch("pipeline.fetch_kline.fetch_one_incremental", side_effect=fake_fetch_one_incremental):
        service = MarketService(token="test_token_123456")
        result = service.incremental_update(end_date="2026-04-29")

    assert result["ok"] is True
    assert result["updated"] == 1
    assert captured_codes == ["920964"]

    updated_df = pd.read_csv(raw_dir / "920964.csv")
    updated_df["date"] = pd.to_datetime(updated_df["date"])
    assert updated_df["date"].max() == pd.Timestamp("2026-04-29")


def test_update_progress_accepts_timezone_aware_started_at() -> None:
    started_at = utc_now().isoformat()
    market_service_module._update_state["started_at"] = started_at
    market_service_module._update_state["running"] = True
    market_service_module._update_state["message"] = ""

    MarketService.update_progress(
        {
            "current": 0,
            "total": 1,
            "progress": 10,
            "message": "进行中",
        }
    )

    assert market_service_module._update_state["elapsed_seconds"] >= 0
    assert market_service_module._update_state["message"] == "进行中"


def test_elapsed_seconds_since_accepts_naive_isoformat() -> None:
    naive_started_at = utc_now().astimezone(timezone.utc).replace(tzinfo=None).isoformat()

    elapsed = MarketService._elapsed_seconds_since(naive_started_at)

    assert elapsed >= 0
