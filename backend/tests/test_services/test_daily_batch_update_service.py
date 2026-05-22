from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

import app.services.daily_batch_update_service as daily_batch_module
from app.config import settings
from app.models import Stock, StockDaily
from app.services.daily_batch_update_service import DailyBatchUpdateService


def test_sync_raw_csv_files_appends_latest_trade_date(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daily_batch_module, "ROOT", tmp_path)
    monkeypatch.setattr(settings, "raw_data_dir", Path("data/raw"))

    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    existing_path = raw_dir / "000001.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-05-06",
                "open": 10.0,
                "close": 10.2,
                "high": 10.3,
                "low": 9.9,
                "volume": 1000.0,
            }
        ]
    ).to_csv(existing_path, index=False)

    frame = pd.DataFrame(
        [
            {
                "code": "000001",
                "trade_date": pd.Timestamp("2026-05-07"),
                "open": 10.3,
                "close": 10.5,
                "high": 10.6,
                "low": 10.2,
                "volume": 1200.0,
            }
        ]
    )

    DailyBatchUpdateService._sync_raw_csv_files(frame)

    result = pd.read_csv(existing_path)
    assert list(result["date"]) == ["2026-05-06", "2026-05-07"]
    assert float(result.iloc[-1]["close"]) == 10.5


def test_fetch_trade_date_snapshot_fills_missing_volume_ratio_from_history(test_db) -> None:
    test_db.add(Stock(code="000001", name="Ping An", market="SZ"))
    for trade_date, volume in [
        ("2026-05-14", 1000.0),
        ("2026-05-15", 1200.0),
        ("2026-05-18", 1100.0),
        ("2026-05-19", 1300.0),
        ("2026-05-20", 1400.0),
    ]:
        test_db.add(
            StockDaily(
                code="000001",
                trade_date=date.fromisoformat(trade_date),
                open=10.0,
                close=10.0,
                high=10.0,
                low=10.0,
                volume=volume,
                turnover_rate=1.0,
                volume_ratio=1.0,
            )
        )
    test_db.commit()

    service = DailyBatchUpdateService(db=test_db)
    mock_pro = MagicMock()
    mock_pro.daily.return_value = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260521",
                "open": 10.0,
                "high": 10.5,
                "low": 9.9,
                "close": 10.3,
                "vol": 1500.0,
            }
        ]
    )
    mock_pro.daily_basic.return_value = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260521",
                "turnover_rate": 2.5,
                "turnover_rate_f": 2.6,
                "volume_ratio": None,
                "free_share": 10000.0,
                "circ_mv": 20000.0,
            }
        ]
    )
    mock_pro.moneyflow.return_value = pd.DataFrame(
        [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260521",
                "buy_sm_amount": 1.0,
                "sell_sm_amount": 2.0,
                "buy_md_amount": 3.0,
                "sell_md_amount": 4.0,
                "buy_lg_amount": 5.0,
                "sell_lg_amount": 6.0,
                "buy_elg_amount": 7.0,
                "sell_elg_amount": 8.0,
                "net_mf_amount": 9.0,
            }
        ]
    )
    service.tushare_service._pro = mock_pro

    frame = service.fetch_trade_date_snapshot("2026-05-21")

    assert len(frame.index) == 1
    assert float(frame.iloc[0]["volume_ratio"]) == 1.25
