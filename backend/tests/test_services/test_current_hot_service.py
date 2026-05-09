from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from app.models import CurrentHotAnalysisResult, CurrentHotCandidate, CurrentHotRun, Stock, StockDaily
from app.services.current_hot_service import CurrentHotService


def _seed_stock_history(test_db, code: str, end_date: date, days: int = 90, base: float = 10.0) -> None:
    if test_db.query(Stock).filter(Stock.code == code).first() is None:
        test_db.add(Stock(code=code, name=code, market="SH" if code.startswith("6") else "SZ"))
        test_db.commit()
    current = end_date - timedelta(days=days + 30)
    inserted = 0
    while inserted < days:
        if current.weekday() < 5:
            price = base + inserted * 0.05
            test_db.add(
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
    test_db.commit()


class _FakeSelector:
    def prepare_df(self, df: pd.DataFrame) -> pd.DataFrame:
        prepared = df.copy()
        prepared["_vec_pick"] = [False] * (len(prepared) - 1) + [True]
        prepared["J"] = [10.0] * len(prepared)
        prepared["zxdq"] = [2.0] * len(prepared)
        prepared["zxdkx"] = [1.0] * len(prepared)
        prepared["wma_bull"] = [True] * len(prepared)
        return prepared


@pytest.mark.service
def test_get_pool_entries_merges_duplicate_sector_memberships(test_db) -> None:
    service = CurrentHotService(test_db)
    with patch.object(
        CurrentHotService,
        "_load_pool_config",
        return_value={
            "AI服务器": {"中科曙光": "603019"},
            "液冷": {"中科曙光": "603019"},
        },
    ):
        entries = service.get_pool_entries()

    assert len(entries) == 1
    assert entries[0].code == "603019"
    assert entries[0].sector_names == ["AI服务器", "液冷"]
    assert entries[0].board_group == "other"


@pytest.mark.service
def test_generate_current_hot_persists_and_updates_consecutive_metrics(test_db) -> None:
    first_date = date(2026, 5, 7)
    second_date = date(2026, 5, 8)
    _seed_stock_history(test_db, "600000", second_date, base=10.0)
    _seed_stock_history(test_db, "688001", second_date, base=20.0)

    service = CurrentHotService(test_db)

    def fake_quant_review(code: str, df: pd.DataFrame, check_date: str) -> dict:
        score = 5.2 if code == "600000" else 4.1
        return {
            "score": score,
            "verdict": "PASS",
            "signal_type": "trend_start" if code == "600000" else "rebound",
            "comment": f"{code}-{check_date}",
            "signal_reasoning": None,
            "scores": {},
            "trend_reasoning": None,
            "position_reasoning": None,
            "volume_reasoning": None,
            "abnormal_move_reasoning": None,
        }

    with patch.object(
        CurrentHotService,
        "_load_pool_config",
        return_value={"测试主题": {"浦发银行": "600000", "测试科创": "688001"}},
    ), patch("app.services.current_hot_service.analysis_service._build_b1_selector", return_value=_FakeSelector()), patch(
        "app.services.current_hot_service.analysis_service._quant_review_for_date",
        side_effect=fake_quant_review,
    ):
        first_payload = service.generate_for_trade_date(first_date)
        second_payload = service.generate_for_trade_date(second_date)

    assert first_payload["status"] == "ok"
    assert second_payload["status"] == "ok"

    first_run = test_db.query(CurrentHotRun).filter(CurrentHotRun.pick_date == first_date).one()
    second_run = test_db.query(CurrentHotRun).filter(CurrentHotRun.pick_date == second_date).one()
    assert first_run.candidate_count == 2
    assert first_run.trend_start_count == 1
    assert first_run.consecutive_candidate_count == 0
    assert second_run.candidate_count == 2
    assert second_run.trend_start_count == 1
    assert second_run.consecutive_candidate_count == 2

    first_candidates = (
        test_db.query(CurrentHotCandidate)
        .filter(CurrentHotCandidate.pick_date == first_date)
        .order_by(CurrentHotCandidate.code.asc())
        .all()
    )
    second_candidates = (
        test_db.query(CurrentHotCandidate)
        .filter(CurrentHotCandidate.pick_date == second_date)
        .order_by(CurrentHotCandidate.code.asc())
        .all()
    )
    assert [row.consecutive_days for row in first_candidates] == [1, 1]
    assert [row.consecutive_days for row in second_candidates] == [2, 2]

    results_payload = service.get_results(second_date.isoformat())
    assert [item["code"] for item in results_payload["results"]] == ["600000", "688001"]
    assert results_payload["results"][0]["total_score"] == 5.2
    assert test_db.query(CurrentHotAnalysisResult).count() == 4


@pytest.mark.service
def test_generate_current_hot_backfills_history_before_analysis(test_db) -> None:
    target_date = date(2026, 5, 8)
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_db.add(
        StockDaily(
            code="600000",
            trade_date=target_date,
            open=10.0,
            close=10.2,
            high=10.3,
            low=9.9,
            volume=100000,
        )
    )
    test_db.commit()

    def fake_fetch_daily_data(_self, code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        del start_date, end_date
        rows: list[dict] = []
        current = target_date - timedelta(days=120)
        inserted = 0
        while inserted < 80:
            if current.weekday() < 5:
                base = 10.0 + inserted * 0.05
                rows.append(
                    {
                        "code": code,
                        "trade_date": current,
                        "open": base,
                        "high": base + 0.2,
                        "low": base - 0.1,
                        "close": base + 0.1,
                        "volume": 100000 + inserted * 100,
                    }
                )
                inserted += 1
            current += timedelta(days=1)
        return pd.DataFrame(rows)

    service = CurrentHotService(test_db)
    with patch.object(
        CurrentHotService,
        "_load_pool_config",
        return_value={"测试主题": {"浦发银行": "600000"}},
    ), patch(
        "app.services.current_hot_service.DailyDataService.fetch_daily_data",
        autospec=True,
        side_effect=fake_fetch_daily_data,
    ) as mock_fetch, patch(
        "app.services.current_hot_service.analysis_service._build_b1_selector",
        return_value=_FakeSelector(),
    ), patch(
        "app.services.current_hot_service.analysis_service._quant_review_for_date",
        return_value={
            "score": 5.6,
            "verdict": "PASS",
            "signal_type": "trend_start",
            "comment": "filled-history",
            "signal_reasoning": None,
            "scores": {},
            "trend_reasoning": None,
            "position_reasoning": None,
            "volume_reasoning": None,
            "abnormal_move_reasoning": None,
        },
    ):
        payload = service.generate_for_trade_date(target_date)

    assert payload["status"] == "ok"
    assert mock_fetch.call_count == 1
    candidate = test_db.query(CurrentHotCandidate).filter(CurrentHotCandidate.pick_date == target_date).one()
    analysis = test_db.query(CurrentHotAnalysisResult).filter(CurrentHotAnalysisResult.pick_date == target_date).one()
    assert candidate.kdj_j == 10.0
    assert candidate.b1_passed is True
    assert analysis.total_score == 5.6
    assert analysis.signal_type == "trend_start"
    assert test_db.query(StockDaily).filter(StockDaily.code == "600000").count() >= 60


@pytest.mark.service
def test_ensure_window_rebuilds_missing_trade_dates(test_db) -> None:
    trade_dates = [date(2026, 5, 7), date(2026, 5, 8)]
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_db.add_all([
        StockDaily(
            code="600000",
            trade_date=trade_date,
            open=10.0,
            close=10.2,
            high=10.3,
            low=9.9,
            volume=100000,
        )
        for trade_date in trade_dates
    ])
    test_db.commit()

    service = CurrentHotService(test_db)
    generated_dates: list[date] = []

    def fake_generate_for_trade_date(target_trade_date: date, reviewer: str = "quant") -> dict:
        generated_dates.append(target_trade_date)
        test_db.add(
            CurrentHotRun(
                pick_date=target_trade_date,
                status="success",
                candidate_count=1,
                analysis_count=1,
                trend_start_count=1,
                consecutive_candidate_count=0,
                reviewer=reviewer,
            )
        )
        test_db.add(
            CurrentHotCandidate(
                pick_date=target_trade_date,
                code="600000",
                sector_names_json=["测试主题"],
                board_group="other",
                open_price=10.0,
                close_price=10.2,
                change_pct=2.0,
                b1_passed=True,
                kdj_j=10.0,
            )
        )
        test_db.add(
            CurrentHotAnalysisResult(
                pick_date=target_trade_date,
                code="600000",
                reviewer=reviewer,
                b1_passed=True,
                verdict="PASS",
                total_score=5.1,
                signal_type="trend_start",
                comment="rebuilt",
                details_json={"comment": "rebuilt"},
            )
        )
        test_db.commit()
        return {"status": "ok"}

    with patch.object(service, "generate_for_trade_date", side_effect=fake_generate_for_trade_date):
        result = service.ensure_window(window_size=2)

    assert generated_dates == trade_dates
    assert result["rebuilt_dates"] == ["2026-05-07", "2026-05-08"]
    assert result["failed_dates"] == []
    assert [item["pick_date"] for item in result["summary"]["history"]] == ["2026-05-08", "2026-05-07"]
    assert all(item["status"] == "success" for item in result["summary"]["history"])
