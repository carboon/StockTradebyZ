from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from app.models import (
    CurrentHotAnalysisResult,
    CurrentHotCandidate,
    CurrentHotIntradaySnapshot,
    CurrentHotRun,
    Stock,
    StockDaily,
)
from app.services.current_hot_intraday_service import ASIA_SHANGHAI


def _seed_stock_history(test_client_with_db: Any, code: str, trade_date: date, days: int = 80, base: float = 10.0) -> None:
    db = test_client_with_db.db
    if db.query(Stock).filter(Stock.code == code).first() is None:
        db.add(Stock(code=code, name=code, market="SH" if code.startswith("6") else "SZ"))
        db.commit()
    start = trade_date - timedelta(days=days + 30)
    current = start
    inserted = 0
    while inserted < days:
        if current.weekday() < 5:
            price = base + inserted * 0.05
            db.add(
                StockDaily(
                    code=code,
                    trade_date=current,
                    open=price,
                    close=price + 0.1,
                    high=price + 0.2,
                    low=price - 0.1,
                    volume=100000 + inserted * 100,
                )
            )
            inserted += 1
        current += timedelta(days=1)
    db.commit()


class _FakeSelector:
    def prepare_df(self, df: pd.DataFrame) -> pd.DataFrame:
        prepared = df.copy()
        prepared["_vec_pick"] = [False] * (len(prepared) - 1) + [True]
        prepared["J"] = [10.0] * len(prepared)
        prepared["zxdq"] = [2.0] * len(prepared)
        prepared["zxdkx"] = [1.0] * len(prepared)
        prepared["wma_bull"] = [True] * len(prepared)
        return prepared


def test_get_current_hot_dates_returns_history(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    db.add(Stock(code="600000", name="浦发银行", market="SH"))
    db.add(StockDaily(code="600000", trade_date=date(2026, 5, 8), open=10.0, close=10.5, high=10.6, low=9.9, volume=100000))
    db.add(
        CurrentHotRun(
            pick_date=date(2026, 5, 8),
            status="success",
            candidate_count=2,
            analysis_count=2,
            trend_start_count=1,
            consecutive_candidate_count=1,
        )
    )
    db.add(
        CurrentHotAnalysisResult(
            pick_date=date(2026, 5, 8),
            code="600000",
            reviewer="quant",
            b1_passed=True,
            verdict="PASS",
            total_score=4.6,
            signal_type="trend_start",
            comment="ok",
            details_json={"comment": "ok"},
        )
    )
    db.add(
        CurrentHotCandidate(
            pick_date=date(2026, 5, 8),
            code="600000",
            sector_names_json=["算力"],
            board_group="other",
            b1_passed=True,
            consecutive_days=2,
        )
    )
    db.commit()

    response = test_client_with_db.get("/api/v1/analysis/current-hot/dates")

    assert response.status_code == 200
    data = response.json()
    assert data["dates"] == ["2026-05-08"]
    assert data["history"][0]["trend_start_count"] == 1
    assert data["history"][0]["consecutive_candidate_count"] == 1


def test_get_current_hot_candidates_and_results(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    pick_date = date(2026, 5, 8)
    db.add(Stock(code="688001", name="华兴源创", market="SH"))
    db.add(
        CurrentHotRun(
            pick_date=pick_date,
            status="success",
            candidate_count=1,
            analysis_count=1,
            trend_start_count=1,
            consecutive_candidate_count=0,
        )
    )
    db.add(
        CurrentHotCandidate(
            pick_date=pick_date,
            code="688001",
            sector_names_json=["光芯片"],
            board_group="kechuang",
            open_price=10.0,
            close_price=10.5,
            change_pct=5.0,
            b1_passed=True,
            kdj_j=12.0,
        )
    )
    db.add(
        CurrentHotAnalysisResult(
            pick_date=pick_date,
            code="688001",
            reviewer="quant",
            b1_passed=True,
            verdict="PASS",
            total_score=5.3,
            signal_type="trend_start",
            comment="ok",
            details_json={"comment": "ok"},
        )
    )
    db.commit()

    candidates_response = test_client_with_db.get("/api/v1/analysis/current-hot/candidates?date=2026-05-08")
    results_response = test_client_with_db.get("/api/v1/analysis/current-hot/results?date=2026-05-08")

    assert candidates_response.status_code == 200
    assert results_response.status_code == 200
    candidates_data = candidates_response.json()
    results_data = results_response.json()
    assert candidates_data["candidates"][0]["board_group"] == "kechuang"
    assert candidates_data["candidates"][0]["sector_names"] == ["光芯片"]
    assert results_data["results"][0]["b1_passed"] is True
    assert results_data["results"][0]["total_score"] == 5.3


def test_get_current_hot_results_prioritizes_b1_then_trend_start_then_score(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    pick_date = date(2026, 5, 8)
    db.add_all([
        Stock(code="688001", name="A", market="SH"),
        Stock(code="688002", name="B", market="SH"),
        Stock(code="600001", name="C", market="SH"),
        Stock(code="600002", name="D", market="SH"),
    ])
    db.add_all([
        CurrentHotRun(
            pick_date=pick_date,
            status="success",
            candidate_count=4,
            analysis_count=4,
            trend_start_count=2,
            consecutive_candidate_count=0,
        ),
        CurrentHotCandidate(pick_date=pick_date, code="688001", sector_names_json=["芯片"], board_group="kechuang", b1_passed=True),
        CurrentHotCandidate(pick_date=pick_date, code="688002", sector_names_json=["芯片"], board_group="kechuang", b1_passed=True),
        CurrentHotCandidate(pick_date=pick_date, code="600001", sector_names_json=["算力"], board_group="other", b1_passed=False),
        CurrentHotCandidate(pick_date=pick_date, code="600002", sector_names_json=["算力"], board_group="other", b1_passed=False),
        CurrentHotAnalysisResult(pick_date=pick_date, code="688001", reviewer="quant", b1_passed=True, verdict="WATCH", total_score=4.8, signal_type="rebound", comment="a", details_json={}),
        CurrentHotAnalysisResult(pick_date=pick_date, code="688002", reviewer="quant", b1_passed=True, verdict="PASS", total_score=4.2, signal_type="trend_start", comment="b", details_json={}),
        CurrentHotAnalysisResult(pick_date=pick_date, code="600001", reviewer="quant", b1_passed=False, verdict="PASS", total_score=5.0, signal_type="trend_start", comment="c", details_json={}),
        CurrentHotAnalysisResult(pick_date=pick_date, code="600002", reviewer="quant", b1_passed=False, verdict="WATCH", total_score=4.9, signal_type="rebound", comment="d", details_json={}),
    ])
    db.commit()

    response = test_client_with_db.get("/api/v1/analysis/current-hot/results?date=2026-05-08")

    assert response.status_code == 200
    data = response.json()
    assert [item["code"] for item in data["results"]] == ["688002", "688001", "600001", "600002"]


def test_generate_current_hot_creates_daily_rows(test_client_with_db: Any) -> None:
    trade_date = date(2026, 5, 8)
    _seed_stock_history(test_client_with_db, "600000", trade_date, base=10.0)
    _seed_stock_history(test_client_with_db, "688001", trade_date, base=20.0)

    def fake_quant_review(code: str, df: pd.DataFrame, check_date: str) -> dict:
        score = 5.6 if code == "600000" else 4.4
        return {
            "score": score,
            "verdict": "PASS",
            "signal_type": "trend_start" if code == "600000" else "rebound",
            "comment": "ok",
            "signal_reasoning": None,
            "scores": {},
            "trend_reasoning": None,
            "position_reasoning": None,
            "volume_reasoning": None,
            "abnormal_move_reasoning": None,
        }

    with patch("app.api.analysis.ensure_tushare_ready", return_value=None), patch(
        "app.services.current_hot_service.CurrentHotService._load_pool_config",
        return_value={"测试主题": {"浦发银行": "600000", "测试科创": "688001"}},
    ), patch("app.services.current_hot_service.analysis_service._build_b1_selector", return_value=_FakeSelector()), patch(
        "app.services.current_hot_service.analysis_service._quant_review_for_date",
        side_effect=fake_quant_review,
    ):
        response = test_client_with_db.post("/api/v1/analysis/current-hot/generate?date=2026-05-08")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert test_client_with_db.db.query(CurrentHotCandidate).filter(CurrentHotCandidate.pick_date == trade_date).count() == 2
    assert test_client_with_db.db.query(CurrentHotAnalysisResult).filter(CurrentHotAnalysisResult.pick_date == trade_date).count() == 2
    run = test_client_with_db.db.query(CurrentHotRun).filter(CurrentHotRun.pick_date == trade_date).one()
    assert run.trend_start_count == 1


def test_generate_current_hot_intraday_creates_snapshot(test_client_with_db: Any) -> None:
    trade_date = date(2026, 5, 8)
    _seed_stock_history(test_client_with_db, "600000", trade_date, days=90, base=10.0)

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

    with patch("app.api.analysis.ensure_tushare_ready", return_value=None), patch(
        "app.services.current_hot_service.CurrentHotService._load_pool_config",
        return_value={"测试主题": {"浦发银行": "600000"}},
    ), patch(
        "app.services.current_hot_intraday_service.CurrentHotIntradayAnalysisService.now_shanghai",
        return_value=fake_now,
    ), patch("app.services.current_hot_intraday_service.TushareService") as mock_tushare_cls, patch(
        "app.services.current_hot_intraday_service.analysis_service._build_b1_selector",
        return_value=_FakeSelector(),
    ), patch(
        "app.services.current_hot_intraday_service.analysis_service._quant_review_for_date",
        return_value={
            "score": 5.8,
            "verdict": "PASS",
            "signal_type": "trend_start",
            "comment": "ok",
            "signal_reasoning": None,
            "scores": {},
            "trend_reasoning": None,
            "position_reasoning": None,
            "volume_reasoning": None,
            "abnormal_move_reasoning": None,
        },
    ):
        mock_service = MagicMock()
        mock_service.pro.rt_k.return_value = fake_quote
        mock_tushare_cls.return_value = mock_service
        response = test_client_with_db.post("/api/v1/analysis/current-hot/intraday/generate")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    row = (
        test_client_with_db.db.query(CurrentHotIntradaySnapshot)
        .filter(CurrentHotIntradaySnapshot.trade_date == trade_date)
        .one()
    )
    assert row.code == "600000"
    assert row.close_price == 12.5
