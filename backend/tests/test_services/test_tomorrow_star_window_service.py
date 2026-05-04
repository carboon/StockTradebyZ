from datetime import date

import pandas as pd

from app.models import AnalysisResult, Candidate, Stock, StockDaily, TomorrowStarRun
from app.services.tomorrow_star_window_service import TomorrowStarWindowService


def test_get_window_status_counts(test_db):
    test_db.add(Stock(code="000001", name="PingAn"))
    test_db.add_all([
        StockDaily(code="000001", trade_date=date(2024, 1, 3), open=10, close=11, high=11, low=9, volume=100),
        StockDaily(code="000001", trade_date=date(2024, 1, 2), open=10, close=10.5, high=11, low=9, volume=100),
    ])
    test_db.add(Candidate(pick_date=date(2024, 1, 3), code="000001", strategy="b1"))
    test_db.add(AnalysisResult(pick_date=date(2024, 1, 3), code="000001", reviewer="quant", verdict="PASS", signal_type="trend_start"))
    test_db.add(TomorrowStarRun(pick_date=date(2024, 1, 3), status="success", candidate_count=1, analysis_count=1, trend_start_count=1))
    test_db.commit()

    summary = TomorrowStarWindowService(test_db).get_window_status(window_size=2)

    assert summary.window_size == 2
    assert summary.latest_date == "2024-01-03"
    assert len(summary.items) == 2
    assert summary.ready_count == 1
    assert summary.missing_count == 1
    assert summary.items[0]["status"] == "success"
    assert summary.items[1]["status"] == "missing"


def test_prune_window_removes_old_rows(test_db):
    test_db.add(Stock(code="000001", name="PingAn"))
    dates = [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    for trade_date in dates:
        test_db.add(StockDaily(code="000001", trade_date=trade_date, open=10, close=11, high=11, low=9, volume=100))
        test_db.add(Candidate(pick_date=trade_date, code="000001", strategy="b1"))
        test_db.add(AnalysisResult(pick_date=trade_date, code="000001", reviewer="quant", verdict="PASS", signal_type="trend_start"))
        test_db.add(TomorrowStarRun(pick_date=trade_date, status="success", candidate_count=1, analysis_count=1, trend_start_count=1))
    test_db.commit()

    result = TomorrowStarWindowService(test_db).prune_window(window_size=2)

    assert result["deleted_dates"] == ["2024-01-01"]
    assert test_db.query(Candidate).filter(Candidate.pick_date == date(2024, 1, 1)).count() == 0
    assert test_db.query(AnalysisResult).filter(AnalysisResult.pick_date == date(2024, 1, 1)).count() == 0
    assert test_db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == date(2024, 1, 1)).count() == 0


def test_ensure_window_backfills_from_backtest_events(test_db, mocker):
    test_db.add(Stock(code="000001", name="PingAn"))
    test_db.add(Stock(code="000002", name="Vanke"))
    for trade_date in [date(2024, 1, 2), date(2024, 1, 3)]:
        test_db.add(StockDaily(code="000001", trade_date=trade_date, open=10, close=11, high=11, low=9, volume=100))
        test_db.add(StockDaily(code="000002", trade_date=trade_date, open=20, close=21, high=22, low=19, volume=200))
    test_db.commit()

    events_df = pd.DataFrame(
        [
            {
                "pick_date": "2024-01-03",
                "code": "000001",
                "strategy": "b1",
                "close": 11.0,
                "turnover_n": 123456.0,
                "kdj_j": 12.3,
                "verdict": "PASS",
                "total_score": 4.2,
                "signal_type": "trend_start",
                "comment": "ok",
                "details_json": {"signal_type": "trend_start"},
            }
        ]
    )
    mocker.patch("pipeline.backtest_quant.run_backtest", return_value=(events_df, {"date_range": {}}))
    mocker.patch("app.services.tushare_service.TushareService.sync_stock_names_to_db", return_value=None)

    result = TomorrowStarWindowService(test_db).ensure_window(window_size=2)

    assert result["rebuilt_dates"] == ["2024-01-02", "2024-01-03"]
    run_zero = test_db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == date(2024, 1, 2)).one()
    assert run_zero.status == "success"
    assert run_zero.candidate_count == 0
    assert run_zero.analysis_count == 0
    run_one = test_db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == date(2024, 1, 3)).one()
    assert run_one.candidate_count == 1
    assert run_one.analysis_count == 1
    assert run_one.trend_start_count == 1

    candidate = test_db.query(Candidate).filter(Candidate.pick_date == date(2024, 1, 3)).one()
    assert candidate.code == "000001"
    assert candidate.close_price == 11.0
    assert candidate.turnover == 123456.0
    assert candidate.kdj_j == 12.3

    analysis = test_db.query(AnalysisResult).filter(AnalysisResult.pick_date == date(2024, 1, 3)).one()
    assert analysis.code == "000001"
    assert analysis.comment == "ok"
    assert analysis.signal_type == "trend_start"
