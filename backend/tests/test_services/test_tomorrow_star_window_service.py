from datetime import date

import pandas as pd

from app.models import AnalysisResult, Candidate, Stock, StockDaily, TomorrowStarRun
from app.services.candidate_service import CandidateService
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


def test_maintain_trade_date_rebuilds_inconsistent_candidate_and_analysis_rows(test_db, mocker):
    target_date = date(2024, 1, 3)
    test_db.add(Stock(code="000001", name="PingAn"))
    test_db.add(Stock(code="000002", name="Vanke"))
    for trade_date in [date(2024, 1, 2), target_date]:
        test_db.add(StockDaily(code="000001", trade_date=trade_date, open=10, close=11, high=11, low=9, volume=100))
        test_db.add(StockDaily(code="000002", trade_date=trade_date, open=20, close=21, high=22, low=19, volume=200))

    # 先写入一组不一致的旧数据：候选 2 条，但分析/运行统计只有 1 条。
    test_db.add_all([
        Candidate(pick_date=target_date, code="000001", strategy="b1"),
        Candidate(pick_date=target_date, code="000002", strategy="b1"),
        AnalysisResult(
            pick_date=target_date,
            code="000001",
            reviewer="quant",
            verdict="FAIL",
            signal_type="prefilter_blocked",
        ),
        TomorrowStarRun(
            pick_date=target_date,
            status="success",
            source="bootstrap",
            candidate_count=1,
            analysis_count=1,
            trend_start_count=0,
        ),
    ])
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
            },
            {
                "pick_date": "2024-01-03",
                "code": "000002",
                "strategy": "b1",
                "close": 21.0,
                "turnover_n": 223456.0,
                "kdj_j": 8.8,
                "verdict": "WATCH",
                "total_score": 3.6,
                "signal_type": "watch",
                "comment": "watch",
                "details_json": {"signal_type": "watch"},
            },
        ]
    )
    mocker.patch("pipeline.backtest_quant.run_backtest", return_value=(events_df, {"date_range": {}}))
    mocker.patch("app.services.tushare_service.TushareService.sync_stock_names_to_db", return_value=None)

    result = TomorrowStarWindowService(test_db).rebuild_trade_date(
        "2024-01-03",
        source="incremental_update",
        window_size=2,
    )

    assert result["success"] is True

    rebuilt_candidates = (
        test_db.query(Candidate)
        .filter(Candidate.pick_date == target_date)
        .order_by(Candidate.code.asc())
        .all()
    )
    rebuilt_analysis = (
        test_db.query(AnalysisResult)
        .filter(AnalysisResult.pick_date == target_date)
        .order_by(AnalysisResult.code.asc())
        .all()
    )
    run = test_db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == target_date).one()

    assert [row.code for row in rebuilt_candidates] == ["000001", "000002"]
    assert [row.code for row in rebuilt_analysis] == ["000001", "000002"]
    assert run.candidate_count == 2
    assert run.analysis_count == 2
    assert run.trend_start_count == 1
    assert run.source == "incremental_update"


def test_window_status_includes_consecutive_candidate_metrics(test_db):
    test_db.add(Stock(code="688183", name="生益电子"))
    test_db.add_all([
        StockDaily(code="688183", trade_date=date(2024, 5, 6), open=10, close=10.5, high=10.8, low=9.9, volume=100),
        StockDaily(code="688183", trade_date=date(2024, 5, 7), open=10.4, close=10.9, high=11.0, low=10.2, volume=110),
    ])
    test_db.add_all([
        Candidate(pick_date=date(2024, 5, 6), code="688183", strategy="b1"),
        Candidate(pick_date=date(2024, 5, 7), code="688183", strategy="b1"),
    ])
    test_db.add_all([
        TomorrowStarRun(pick_date=date(2024, 5, 6), status="success", candidate_count=1, analysis_count=0, trend_start_count=0),
        TomorrowStarRun(pick_date=date(2024, 5, 7), status="success", candidate_count=1, analysis_count=0, trend_start_count=0),
    ])
    test_db.commit()

    CandidateService.recalculate_consecutive_metrics(test_db)

    may_6 = test_db.query(Candidate).filter(Candidate.pick_date == date(2024, 5, 6)).one()
    may_7 = test_db.query(Candidate).filter(Candidate.pick_date == date(2024, 5, 7)).one()
    assert may_6.consecutive_days == 1
    assert may_7.consecutive_days == 2

    summary = TomorrowStarWindowService(test_db).get_window_status(window_size=2)

    assert summary.items[0]["pick_date"] == "2024-05-07"
    assert summary.items[0]["consecutive_candidate_count"] == 1
    assert summary.items[1]["pick_date"] == "2024-05-06"
    assert summary.items[1]["consecutive_candidate_count"] == 0
