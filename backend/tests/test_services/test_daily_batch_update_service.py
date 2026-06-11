from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

import app.services.daily_batch_update_service as daily_batch_module
from app.config import settings
from app.models import Stock, StockDaily
from app.services.daily_batch_update_service import DailyBatchUpdateService
from app.services.realtime_daily_bar_service import RealtimeDailyBar


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


def test_sync_raw_csv_from_db_rewrites_warmup_history(test_db, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(daily_batch_module, "ROOT", tmp_path)
    monkeypatch.setattr(settings, "raw_data_dir", Path("data/raw"))

    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "date": "2026-05-21",
                "open": 99.0,
                "close": 99.0,
                "high": 99.0,
                "low": 99.0,
                "volume": 1.0,
            }
        ]
    ).to_csv(raw_dir / "000001.csv", index=False)

    test_db.add(Stock(code="000001", name="Ping An", market="SZ"))
    for idx, trade_date in enumerate(pd.bdate_range("2026-01-01", "2026-05-21")):
        test_db.add(
            StockDaily(
                code="000001",
                trade_date=trade_date.date(),
                open=10.0 + idx,
                close=10.2 + idx,
                high=10.3 + idx,
                low=9.9 + idx,
                volume=1000.0 + idx,
                turnover_rate=1.0,
                turnover_rate_f=1.1,
                volume_ratio=1.2,
            )
        )
    test_db.commit()

    service = DailyBatchUpdateService(db=test_db)
    result = service._sync_raw_csv_from_db(codes=["000001"], end_date=date(2026, 5, 21), min_history_days=60)

    csv = pd.read_csv(raw_dir / "000001.csv")
    assert result["updated_files"] == 1
    assert result["synced_rows"] == len(csv.index)
    assert len(csv.index) >= 60
    assert csv.iloc[0]["date"] == "2026-01-01"
    assert csv.iloc[-1]["date"] == "2026-05-21"
    assert float(csv.iloc[-1]["close"]) != 99.0


def test_delete_stale_records_for_trade_date_removes_codes_outside_snapshot(test_db) -> None:
    trade_day = date(2026, 6, 10)
    for code in ["000001", "000002"]:
        test_db.add(Stock(code=code, name=code, market="SZ"))
        test_db.add(
            StockDaily(
                code=code,
                trade_date=trade_day,
                open=10.0,
                close=10.1,
                high=10.2,
                low=9.9,
                volume=1000.0,
            )
        )
    test_db.commit()

    service = DailyBatchUpdateService(db=test_db)
    deleted_count = service._delete_stale_records_for_trade_date(trade_day, ["000001"])

    remaining_codes = [
        code
        for code, in test_db.query(StockDaily.code)
        .filter(StockDaily.trade_date == trade_day)
        .order_by(StockDaily.code.asc())
        .all()
    ]
    assert deleted_count == 1
    assert remaining_codes == ["000001"]


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


def test_fetch_trade_date_snapshot_falls_back_to_realtime_when_tushare_daily_empty(test_db) -> None:
    previous_date = date(2026, 5, 7)
    target_date = date(2026, 5, 8)
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_db.add(
        StockDaily(
            code="600000",
            trade_date=previous_date,
            open=10.0,
            close=10.1,
            high=10.2,
            low=9.9,
            volume=1000.0,
        )
    )
    test_db.commit()

    service = DailyBatchUpdateService(db=test_db)
    mock_pro = MagicMock()
    mock_pro.daily.return_value = pd.DataFrame()
    service.tushare_service._pro = mock_pro
    bar = RealtimeDailyBar(
        code="600000",
        trade_date=target_date,
        open=10.2,
        close=10.5,
        high=10.6,
        low=10.1,
        volume=1500.0,
        amount=16000.0,
        turnover_rate=2.5,
        volume_ratio=1.6,
        total_mv=10_000_000_000.0,
        circ_mv=9_000_000_000.0,
        source="tencent_quote",
        quote_time="20260508150100",
    )
    service.realtime_daily_bar_service.fetch_bars = MagicMock(return_value={"600000": bar})

    frame = service.fetch_trade_date_snapshot("2026-05-08")

    assert len(frame.index) == 1
    row = frame.iloc[0]
    assert row["ts_code"] == "600000.SH"
    assert row["trade_date"] == target_date
    assert float(row["close"]) == 10.5
    assert float(row["turnover_rate"]) == 2.5
    assert float(row["volume_ratio"]) == 1.6
    assert float(row["circ_mv"]) == 900000.0
    service.realtime_daily_bar_service.fetch_bars.assert_called_once_with(["600000"], trade_date=target_date)


def test_fetch_trade_date_snapshot_rejects_invalid_realtime_zero_ohlcv(test_db) -> None:
    previous_date = date(2026, 6, 9)
    target_date = date(2026, 6, 10)
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_db.add(
        StockDaily(
            code="600000",
            trade_date=previous_date,
            open=10.0,
            close=10.1,
            high=10.2,
            low=9.9,
            volume=1000.0,
        )
    )
    test_db.commit()

    service = DailyBatchUpdateService(db=test_db)
    mock_pro = MagicMock()
    mock_pro.daily.return_value = pd.DataFrame()
    service.tushare_service._pro = mock_pro
    bar = RealtimeDailyBar(
        code="600000",
        trade_date=target_date,
        open=0.0,
        close=10.1,
        high=0.0,
        low=0.0,
        volume=0.0,
        amount=0.0,
        turnover_rate=0.0,
        volume_ratio=0.0,
        total_mv=None,
        circ_mv=None,
        source="tencent_quote",
        quote_time="20260610091200",
    )
    service.realtime_daily_bar_service.fetch_bars = MagicMock(return_value={"600000": bar})

    frame = service.fetch_trade_date_snapshot("2026-06-10")

    assert frame.empty
    service.realtime_daily_bar_service.fetch_bars.assert_called_once_with(["600000"], trade_date=target_date)
