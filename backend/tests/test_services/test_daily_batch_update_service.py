from pathlib import Path

import pandas as pd

import app.services.daily_batch_update_service as daily_batch_module
from app.config import settings
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
