from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from app.models import Candidate, IntradayAnalysisSnapshot, Stock, StockDaily
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


def test_intraday_status_blocks_normal_user_outside_window_without_snapshot(test_client_with_db: Any) -> None:
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
        )
    )
    db.commit()

    from app.api import deps
    admin_user = SimpleNamespace(id=999, role="admin", is_active=True)
    test_client_with_db.app.dependency_overrides[deps.require_user] = lambda: admin_user

    response = test_client_with_db.get("/api/v1/analysis/intraday/data")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["has_data"] is True
    assert data["total"] == 1
    assert data["items"][0]["code"] == "600000"
    assert data["items"][0]["name"] == "浦发银行"


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
            }
        ]
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

    with patch("app.api.analysis.ensure_tushare_ready", return_value=None), \
         patch("app.services.intraday_analysis_service.IntradayAnalysisService.now_shanghai", return_value=fake_now), \
         patch("app.services.intraday_analysis_service.TushareService") as mock_tushare_cls, \
         patch("app.services.intraday_analysis_service.analysis_service.load_stock_data") as mock_load_stock_data, \
         patch("app.services.intraday_analysis_service.analysis_service._build_b1_selector", return_value=FakeSelector()), \
         patch("app.services.intraday_analysis_service.analysis_service._quant_review_for_date", return_value={"score": 5.8, "verdict": "PASS", "signal_type": "trend_start", "comment": "ok", "signal_reasoning": None, "scores": {}, "trend_reasoning": None, "position_reasoning": None, "volume_reasoning": None, "abnormal_move_reasoning": None}):
        mock_service = MagicMock()
        mock_service.pro.rt_k.return_value = fake_quote
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
