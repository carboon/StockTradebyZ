from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "backend" / "scripts" / "repair_incomplete_stock_daily.py"
SPEC = spec_from_file_location("repair_incomplete_stock_daily", MODULE_PATH)
assert SPEC and SPEC.loader
repair_incomplete_stock_daily = module_from_spec(SPEC)
SPEC.loader.exec_module(repair_incomplete_stock_daily)


def test_frame_to_records_normalizes_payload():
    frame = pd.DataFrame({
        "date": ["2026-05-08", "2026-05-09"],
        "open": [10, 11],
        "close": [10.5, 11.5],
        "high": [10.8, 11.8],
        "low": [9.8, 10.8],
        "volume": [1000, 2000],
    })

    records = repair_incomplete_stock_daily.frame_to_records("1234", frame)

    assert len(records) == 2
    assert records[0]["code"] == "001234"
    assert records[0]["trade_date"].isoformat() == "2026-05-08"
    assert records[1]["close"] == 11.5


def test_flush_records_returns_bulk_upsert_summary(monkeypatch):
    calls: list[tuple[list[dict], int]] = []

    def _fake_bulk_upsert_stock_daily(db, records, batch_size):  # type: ignore[no-untyped-def]
        del db
        calls.append((list(records), batch_size))
        return {"inserted": 12, "failed": 3}

    monkeypatch.setattr(
        repair_incomplete_stock_daily,
        "bulk_upsert_stock_daily",
        _fake_bulk_upsert_stock_daily,
    )

    result = repair_incomplete_stock_daily.flush_records(
        object(),
        [{"code": "000001", "trade_date": pd.Timestamp("2026-05-08").date()}],
        batch_size=5000,
    )

    assert calls and calls[0][1] == 5000
    assert result == {"written": 12, "failed": 3}


def test_get_target_codes_filters_and_limits(monkeypatch):
    monkeypatch.setattr(
        repair_incomplete_stock_daily,
        "get_stock_daily_counts",
        lambda: [("000001", 1), ("000002", 10), ("000003", 300), ("000004", 0)],
    )

    result = repair_incomplete_stock_daily.get_target_codes(min_days=20, limit=2)

    assert result == [("000001", 1), ("000002", 10)]
