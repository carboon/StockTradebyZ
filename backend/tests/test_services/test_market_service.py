from pathlib import Path
from unittest.mock import patch

import pandas as pd

import app.services.market_service as market_service_module
import app.utils.stock_metadata as stock_metadata_module
from app.config import settings
from app.services.market_service import MarketService
from app.utils.stock_metadata import clear_stock_metadata_cache


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

    fetched_df = pd.DataFrame(
        {
            "ts_code": ["000001.SZ"],
            "trade_date": ["20260429"],
            "open": [11.50],
            "close": [11.60],
            "high": [11.70],
            "low": [11.30],
            "vol": [1200000],
        }
    )

    monkeypatch.setattr(market_service_module, "ROOT", root)
    monkeypatch.setattr(market_service_module, "RUN_DIR", run_dir)
    monkeypatch.setattr(settings, "raw_data_dir", Path("data/raw"))
    monkeypatch.setattr(MarketService, "get_latest_trade_date", lambda self: "2026-04-29")
    monkeypatch.setattr(MarketService, "update_cache", lambda self, latest_date: None)

    with patch("app.utils.tushare_rate_limit.acquire_tushare_slot", lambda endpoint: None):
        with patch("tushare.pro_bar", return_value=fetched_df):
            service = MarketService(token="test_token_123456")
            result = service.incremental_update(end_date="2026-04-29")

    assert result["ok"] is True
    assert result["updated"] == 1
    assert result["skipped"] == 0

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

    fetched_df = pd.DataFrame(
        {
            "ts_code": ["920964.BJ"],
            "trade_date": ["20260429"],
            "open": [8.88],
            "close": [9.12],
            "high": [9.20],
            "low": [8.80],
            "vol": [200000],
        }
    )
    captured_ts_codes: list[str] = []

    def fake_pro_bar(*args, **kwargs):
        captured_ts_codes.append(kwargs["ts_code"])
        return fetched_df

    monkeypatch.setattr(market_service_module, "ROOT", root)
    monkeypatch.setattr(market_service_module, "RUN_DIR", run_dir)
    monkeypatch.setattr(settings, "raw_data_dir", Path("data/raw"))
    monkeypatch.setattr(stock_metadata_module, "STOCKLIST_PATH", pipeline_dir / "stocklist.csv")
    monkeypatch.setattr(MarketService, "get_latest_trade_date", lambda self: "2026-04-29")
    monkeypatch.setattr(MarketService, "update_cache", lambda self, latest_date: None)
    clear_stock_metadata_cache()

    try:
        with patch("app.utils.tushare_rate_limit.acquire_tushare_slot", lambda endpoint: None):
            with patch("tushare.pro_bar", side_effect=fake_pro_bar):
                service = MarketService(token="test_token_123456")
                result = service.incremental_update(end_date="2026-04-29")
    finally:
        clear_stock_metadata_cache()

    assert result["ok"] is True
    assert result["updated"] == 1
    assert captured_ts_codes == ["920964.BJ"]

    updated_df = pd.read_csv(raw_dir / "920964.csv")
    updated_df["date"] = pd.to_datetime(updated_df["date"])
    assert updated_df["date"].max() == pd.Timestamp("2026-04-29")
