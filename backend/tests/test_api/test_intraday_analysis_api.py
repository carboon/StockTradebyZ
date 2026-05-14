from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
from app.config import settings
from app.models import Candidate, DailyB1Check, IntradayAnalysisSnapshot, Stock, StockDaily
from app.services.intraday_analysis_service import ASIA_SHANGHAI


def _seed_stock_history(test_client_with_db: Any, code: str, trade_date: date, days: int = 80) -> None:
    db = test_client_with_db.db
    db.flush()
    stock = db.query(Stock).filter(Stock.code == code).first()
    if stock is None:
        stock = Stock(code=code, name="测试股票", market="SH" if code.startswith("6") else "SZ")
        db.add(stock)
    start = trade_date - timedelta(days=days + 30)
    current = start
    inserted = 0
    while inserted < days:
        if current.weekday() < 5:
            base = 10 + inserted * 0.05
            db.add(
                StockDaily(
                    code=code,
                    trade_date=current,
                    open=base,
                    close=base + 0.1,
                    high=base + 0.2,
                    low=base - 0.1,
                    volume=100000 + inserted * 100,
                )
            )
            inserted += 1
        current += timedelta(days=1)
    db.commit()


def test_intraday_status_allows_logged_in_user(test_client_with_db: Any) -> None:
    response = test_client_with_db.get("/api/v1/analysis/intraday/status")
    assert response.status_code == 200


def test_intraday_status_returns_admin_debug_state_without_snapshot(test_client_with_db: Any) -> None:
    fake_now = datetime(2026, 5, 8, 10, 30, tzinfo=ASIA_SHANGHAI)

    with patch("app.services.intraday_analysis_service.IntradayAnalysisService.now_shanghai", return_value=fake_now):
        response = test_client_with_db.get("/api/v1/analysis/intraday/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "window_closed"
    assert data["window_open"] is False
    assert data["has_data"] is False


def test_intraday_data_returns_snapshot_for_admin_when_exists(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    trade_date = date(2026, 5, 8)
    source_pick_date = date(2026, 5, 7)
    snapshot_time = datetime(2026, 5, 8, 12, 35, tzinfo=ASIA_SHANGHAI)

    db.add(Stock(code="600000", name="浦发银行", market="SH"))
    db.add(
        DailyB1Check(
            code="600000",
            check_date=source_pick_date,
            b1_passed=True,
            active_pool_rank=21,
            turnover_rate=5.6,
            volume_ratio=1.8,
            score=4.8,
        )
    )
    db.add(
        IntradayAnalysisSnapshot(
            trade_date=trade_date,
            code="600000",
            source_pick_date=source_pick_date,
            snapshot_time=snapshot_time,
            open_price=10.0,
            close_price=10.5,
            high_price=10.8,
            low_price=9.9,
            volume=123456.0,
            amount=7890000.0,
            change_pct=2.5,
            b1_passed=True,
            score=5.2,
            verdict="PASS",
            signal_type="trend_start",
            kdj_j=12.3,
            zx_long_pos=True,
            weekly_ma_aligned=True,
            volume_healthy=True,
            details_json={
                "midday_price": 10.3,
                "latest_price": 10.5,
                "latest_change_pct": 2.5,
                "midday_time": "11:30:00",
                "analysis_basis": "test basis",
                "previous_analysis": {"verdict": "PASS", "score": 4.8, "signal_type": "trend_start"},
                "turnover_rate": 5.6,
                "volume_ratio": 1.8,
                "active_pool_rank": 21,
                "benchmark_name": "中证500",
                "benchmark_change_pct": 1.1,
                "relative_market_status": "强于大盘",
                "relative_market_strength_pct": 1.4,
                "manager_note": "弱市中仍跑赢指数，先持有再看承接。",
            },
        )
    )
    db.commit()

    with patch("app.services.intraday_analysis_service.IntradayAnalysisService.now_shanghai", return_value=snapshot_time):
        response = test_client_with_db.get("/api/v1/analysis/intraday/data")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["has_data"] is True
    assert data["total"] == 1
    assert data["items"][0]["code"] == "600000"
    assert data["items"][0]["name"] == "浦发银行"
    assert data["items"][0]["midday_price"] == 10.3
    assert data["items"][0]["benchmark_name"] == "中证500"
    assert data["items"][0]["turnover_rate"] == 5.6
    assert data["items"][0]["volume_ratio"] == 1.8
    assert data["items"][0]["active_pool_rank"] == 21


def test_intraday_generate_creates_snapshot_for_admin(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    trade_date = date(2026, 5, 8)
    source_pick_date = date(2026, 5, 7)
    db.add(Stock(code="600000", name="浦发银行", market="SH"))
    db.add(Candidate(pick_date=source_pick_date, code="600000", strategy="b1"))
    _seed_stock_history(test_client_with_db, "600000", source_pick_date, days=90)

    fake_now = datetime(2026, 5, 8, 12, 30, tzinfo=ASIA_SHANGHAI)
    fake_quote = pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "open": 12.0,
                "close": 12.5,
                "high": 12.8,
                "low": 11.9,
                "vol": 250000,
                "amount": 3100000,
                "trade_time": "2026-05-08 12:29:30",
            },
            {"ts_code": "000905.SH", "trade_date": "20260507", "close": 5000, "vol": 1000000},
        ]
    )
    fake_index_daily = pd.DataFrame(
        [
            {"ts_code": "000905.SH", "trade_date": "20260508", "close": 5020, "vol": 1050000},
        ]
    )
    fake_quote = pd.concat(
        [
            fake_quote,
            pd.DataFrame(
                [
                    {"ts_code": "000905.SH", "open": 5010, "close": 5030, "vol": 1400000},
                ]
            ),
        ],
        ignore_index=True,
    )

    class FakeSelector:
        def prepare_df(self, df: pd.DataFrame) -> pd.DataFrame:
            prepared = df.copy()
            prepared["_vec_pick"] = [False] * (len(prepared) - 1) + [True]
            prepared["J"] = [10.0] * len(prepared)
            prepared["zxdq"] = [2.0] * len(prepared)
            prepared["zxdkx"] = [1.0] * len(prepared)
            prepared["wma_bull"] = [True] * len(prepared)
            return prepared

    with patch("app.api.analysis.ensure_tushare_ready_if_configured", return_value=None), \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService.now_shanghai", return_value=fake_now), \
         patch("app.services.intraday_analysis_service.TushareService") as mock_tushare_cls, \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_eastmoney_trends", return_value=pd.DataFrame([
             {"ts_code": "600000.SH", "normalized_ts_code": "600000.SH", "code": "600000", "trade_time": "2026-05-08 11:30:00", "time": "2026-05-08 11:30:00", "open": 12.0, "close": 12.4, "high": 12.5, "low": 11.9, "vol": 125000.0, "amount": 1550000.0, "pre_close": 10.92},
             {"ts_code": "600000.SH", "normalized_ts_code": "600000.SH", "code": "600000", "trade_time": "2026-05-08 12:29:00", "time": "2026-05-08 12:29:00", "open": 12.4, "close": 12.5, "high": 12.8, "low": 12.3, "vol": 125000.0, "amount": 1550000.0, "pre_close": 10.92},
         ])), \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_tencent_minute_trends", return_value=pd.DataFrame()), \
         patch("app.services.intraday_analysis_service.analysis_service.load_stock_data") as mock_load_stock_data, \
         patch("app.services.intraday_analysis_service.analysis_service._build_b1_selector", return_value=FakeSelector()), \
         patch("app.services.intraday_analysis_service.analysis_service._quant_review_for_date", return_value={"score": 5.8, "verdict": "PASS", "signal_type": "trend_start", "comment": "ok", "signal_reasoning": None, "scores": {}, "trend_reasoning": None, "position_reasoning": None, "volume_reasoning": None, "abnormal_move_reasoning": None}):
        mock_service = MagicMock()
        mock_service.pro.rt_k.return_value = fake_quote
        mock_service.pro.index_daily.return_value = fake_index_daily
        mock_tushare_cls.return_value = mock_service
        mock_load_stock_data.return_value = pd.DataFrame(
            [
                {
                    "date": row.trade_date,
                    "open": row.open,
                    "close": row.close,
                    "high": row.high,
                    "low": row.low,
                    "volume": row.volume,
                }
                for row in db.query(StockDaily).filter(StockDaily.code == "600000").order_by(StockDaily.trade_date.asc()).all()
            ]
        )

        response = test_client_with_db.post("/api/v1/analysis/intraday/generate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["generated_count"] == 1
    row = db.query(IntradayAnalysisSnapshot).filter(IntradayAnalysisSnapshot.trade_date == trade_date).one()
    assert row.code == "600000"
    assert row.source_pick_date == source_pick_date
    assert row.close_price == 12.5
    assert row.details_json["midday_price"] == 12.4


def test_intraday_generate_rebuilds_from_local_raw_cache(
    test_client_with_db: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db = test_client_with_db.db
    trade_date = date(2026, 5, 8)
    source_pick_date = date(2026, 5, 7)
    monkeypatch.setattr(settings, "intraday_raw_data_dir", tmp_path / "raw_intraday")

    db.add(Stock(code="600000", name="浦发银行", market="SH"))
    db.add(Candidate(pick_date=source_pick_date, code="600000", strategy="b1"))
    _seed_stock_history(test_client_with_db, "600000", source_pick_date, days=90)

    fake_now = datetime(2026, 5, 8, 12, 30, tzinfo=ASIA_SHANGHAI)
    fake_index_daily = pd.DataFrame(
        [
            {"ts_code": "000905.SH", "trade_date": "20260508", "close": 5020, "vol": 1050000},
        ]
    )
    minute_rows = pd.DataFrame([
        {"ts_code": "600000.SH", "normalized_ts_code": "600000.SH", "code": "600000", "trade_time": "2026-05-08 11:30:00", "time": "2026-05-08 11:30:00", "open": 12.0, "close": 12.4, "high": 12.5, "low": 11.9, "vol": 125000.0, "amount": 1550000.0, "pre_close": 10.92},
        {"ts_code": "600000.SH", "normalized_ts_code": "600000.SH", "code": "600000", "trade_time": "2026-05-08 12:29:00", "time": "2026-05-08 12:29:00", "open": 12.4, "close": 12.5, "high": 12.8, "low": 12.3, "vol": 125000.0, "amount": 1550000.0, "pre_close": 10.92},
    ])

    class FakeSelector:
        def prepare_df(self, df: pd.DataFrame) -> pd.DataFrame:
            prepared = df.copy()
            prepared["_vec_pick"] = [False] * (len(prepared) - 1) + [True]
            prepared["J"] = [10.0] * len(prepared)
            prepared["zxdq"] = [2.0] * len(prepared)
            prepared["zxdkx"] = [1.0] * len(prepared)
            prepared["wma_bull"] = [True] * len(prepared)
            return prepared

    with patch("app.services.intraday_analysis_service.IntradayAnalysisService.now_shanghai", return_value=fake_now), \
         patch("app.services.intraday_analysis_service.TushareService") as mock_tushare_cls, \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_eastmoney_trends", return_value=minute_rows), \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_tencent_minute_trends", return_value=pd.DataFrame()), \
         patch("app.services.intraday_analysis_service.analysis_service.load_stock_data") as mock_load_stock_data, \
         patch("app.services.intraday_analysis_service.analysis_service._build_b1_selector", return_value=FakeSelector()), \
         patch("app.services.intraday_analysis_service.analysis_service._quant_review_for_date", return_value={"score": 5.8, "verdict": "PASS", "signal_type": "trend_start", "comment": "ok", "signal_reasoning": None, "scores": {}, "trend_reasoning": None, "position_reasoning": None, "volume_reasoning": None, "abnormal_move_reasoning": None}):
        mock_service = MagicMock()
        mock_service.token = ""
        mock_service.pro.index_daily.return_value = fake_index_daily
        mock_service.pro.rt_k.return_value = pd.DataFrame()
        mock_tushare_cls.return_value = mock_service
        mock_load_stock_data.return_value = pd.DataFrame(
            [
                {
                    "date": row.trade_date,
                    "open": row.open,
                    "close": row.close,
                    "high": row.high,
                    "low": row.low,
                    "volume": row.volume,
                }
                for row in db.query(StockDaily).filter(StockDaily.code == "600000").order_by(StockDaily.trade_date.asc()).all()
            ]
        )

        first = test_client_with_db.post("/api/v1/analysis/intraday/generate?date=2026-05-08")
        assert first.status_code == 200

    with patch("app.services.intraday_analysis_service.IntradayAnalysisService.now_shanghai", return_value=fake_now), \
         patch("app.services.intraday_analysis_service.TushareService") as mock_tushare_cls, \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_eastmoney_trends", return_value=pd.DataFrame()), \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_tencent_minute_trends", return_value=pd.DataFrame()), \
         patch("app.services.intraday_analysis_service.analysis_service.load_stock_data") as mock_load_stock_data, \
         patch("app.services.intraday_analysis_service.analysis_service._build_b1_selector", return_value=FakeSelector()), \
         patch("app.services.intraday_analysis_service.analysis_service._quant_review_for_date", return_value={"score": 5.8, "verdict": "PASS", "signal_type": "trend_start", "comment": "ok", "signal_reasoning": None, "scores": {}, "trend_reasoning": None, "position_reasoning": None, "volume_reasoning": None, "abnormal_move_reasoning": None}):
        mock_service = MagicMock()
        mock_service.token = ""
        mock_service.pro.index_daily.return_value = fake_index_daily
        mock_service.pro.rt_k.return_value = pd.DataFrame()
        mock_tushare_cls.return_value = mock_service
        mock_load_stock_data.return_value = pd.DataFrame(
            [
                {
                    "date": row.trade_date,
                    "open": row.open,
                    "close": row.close,
                    "high": row.high,
                    "low": row.low,
                    "volume": row.volume,
                }
                for row in db.query(StockDaily).filter(StockDaily.code == "600000").order_by(StockDaily.trade_date.asc()).all()
            ]
        )

        second = test_client_with_db.post("/api/v1/analysis/intraday/generate?date=2026-05-08")

    assert second.status_code == 200
    payload = second.json()
    assert payload["status"] == "ok"
    row = db.query(IntradayAnalysisSnapshot).filter(IntradayAnalysisSnapshot.trade_date == trade_date).one()
    assert row.close_price == 12.5
    assert row.details_json["midday_price"] == 12.4


def test_intraday_generate_falls_back_to_tencent_minute_data(
    test_client_with_db: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db = test_client_with_db.db
    trade_date = date(2026, 5, 8)
    source_pick_date = date(2026, 5, 7)
    monkeypatch.setattr(settings, "intraday_raw_data_dir", tmp_path / "raw_intraday")

    db.add(Stock(code="600000", name="浦发银行", market="SH"))
    db.add(Candidate(pick_date=source_pick_date, code="600000", strategy="b1"))
    _seed_stock_history(test_client_with_db, "600000", source_pick_date, days=90)

    fake_now = datetime(2026, 5, 8, 12, 30, tzinfo=ASIA_SHANGHAI)
    fake_index_daily = pd.DataFrame(
        [
            {"ts_code": "000905.SH", "trade_date": "20260508", "close": 5020, "vol": 1050000},
        ]
    )
    tencent_rows = pd.DataFrame([
        {"ts_code": "600000.SH", "normalized_ts_code": "600000.SH", "code": "600000", "trade_time": "2026-05-08 09:30:00", "time": "2026-05-08 09:30:00", "open": 12.0, "close": 12.0, "high": 12.8, "low": 11.9, "vol": 5000.0, "amount": 62000.0, "pre_close": 10.92},
        {"ts_code": "600000.SH", "normalized_ts_code": "600000.SH", "code": "600000", "trade_time": "2026-05-08 11:30:00", "time": "2026-05-08 11:30:00", "open": 12.0, "close": 12.4, "high": 12.8, "low": 11.9, "vol": 120000.0, "amount": 1488000.0, "pre_close": 10.92},
        {"ts_code": "600000.SH", "normalized_ts_code": "600000.SH", "code": "600000", "trade_time": "2026-05-08 12:29:00", "time": "2026-05-08 12:29:00", "open": 12.0, "close": 12.5, "high": 12.8, "low": 11.9, "vol": 125000.0, "amount": 1550000.0, "pre_close": 10.92},
    ])

    class FakeSelector:
        def prepare_df(self, df: pd.DataFrame) -> pd.DataFrame:
            prepared = df.copy()
            prepared["_vec_pick"] = [False] * (len(prepared) - 1) + [True]
            prepared["J"] = [10.0] * len(prepared)
            prepared["zxdq"] = [2.0] * len(prepared)
            prepared["zxdkx"] = [1.0] * len(prepared)
            prepared["wma_bull"] = [True] * len(prepared)
            return prepared

    with patch("app.api.analysis.ensure_tushare_ready_if_configured", return_value=None), \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService.now_shanghai", return_value=fake_now), \
         patch("app.services.intraday_analysis_service.TushareService") as mock_tushare_cls, \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_eastmoney_trends", return_value=pd.DataFrame()), \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_tencent_minute_trends", return_value=tencent_rows), \
         patch("app.services.intraday_analysis_service.analysis_service.load_stock_data") as mock_load_stock_data, \
         patch("app.services.intraday_analysis_service.analysis_service._build_b1_selector", return_value=FakeSelector()), \
         patch("app.services.intraday_analysis_service.analysis_service._quant_review_for_date", return_value={"score": 5.8, "verdict": "PASS", "signal_type": "trend_start", "comment": "ok", "signal_reasoning": None, "scores": {}, "trend_reasoning": None, "position_reasoning": None, "volume_reasoning": None, "abnormal_move_reasoning": None}):
        mock_service = MagicMock()
        mock_service.pro.rt_k.return_value = pd.DataFrame()
        mock_service.pro.index_daily.return_value = fake_index_daily
        mock_tushare_cls.return_value = mock_service
        mock_load_stock_data.return_value = pd.DataFrame(
            [
                {
                    "date": row.trade_date,
                    "open": row.open,
                    "close": row.close,
                    "high": row.high,
                    "low": row.low,
                    "volume": row.volume,
                }
                for row in db.query(StockDaily).filter(StockDaily.code == "600000").order_by(StockDaily.trade_date.asc()).all()
            ]
        )

        response = test_client_with_db.post("/api/v1/analysis/intraday/generate?date=2026-05-08")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    row = db.query(IntradayAnalysisSnapshot).filter(IntradayAnalysisSnapshot.trade_date == trade_date).one()
    assert row.close_price == 12.5
    assert row.details_json["midday_price"] == 12.4
    assert (tmp_path / "raw_intraday" / "2026-05-08" / "tencent" / "600000.SH.json").exists()
