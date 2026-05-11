import json
from datetime import date

import pandas as pd

from app.config import settings
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


def test_get_window_status_normalizes_stale_running_rows_without_active_task(test_db):
    test_db.add(Stock(code="000001", name="PingAn"))
    test_db.add_all([
        StockDaily(code="000001", trade_date=date(2024, 1, 3), open=10, close=11, high=11, low=9, volume=100),
        StockDaily(code="000001", trade_date=date(2024, 1, 2), open=10, close=10.5, high=11, low=9, volume=100),
    ])
    test_db.add_all([
        TomorrowStarRun(pick_date=date(2024, 1, 3), status="running", candidate_count=0, analysis_count=0, trend_start_count=0),
        TomorrowStarRun(pick_date=date(2024, 1, 2), status="running", candidate_count=0, analysis_count=0, trend_start_count=0),
    ])
    test_db.add(Candidate(pick_date=date(2024, 1, 3), code="000001", strategy="b1"))
    test_db.add(
        AnalysisResult(
            pick_date=date(2024, 1, 3),
            code="000001",
            reviewer="quant",
            verdict="PASS",
            signal_type="trend_start",
        )
    )
    test_db.commit()

    summary = TomorrowStarWindowService(test_db).get_window_status(window_size=2)

    assert summary.ready_count == 1
    assert summary.missing_count == 1
    assert summary.running_count == 0
    assert summary.items[0]["pick_date"] == "2024-01-03"
    assert summary.items[0]["status"] == "success"
    assert summary.items[1]["pick_date"] == "2024-01-02"
    assert summary.items[1]["status"] == "missing"


def test_market_regime_blocked_item_is_effectively_ready(test_db):
    test_db.add(Stock(code="000001", name="PingAn"))
    test_db.add(StockDaily(code="000001", trade_date=date(2024, 1, 3), open=10, close=11, high=11, low=9, volume=100))
    test_db.add(
        TomorrowStarRun(
            pick_date=date(2024, 1, 3),
            status="success",
            candidate_count=0,
            analysis_count=0,
            trend_start_count=0,
            meta_json={
                "market_regime_blocked": True,
                "market_regime_info": {"summary": "blocked"},
            },
        )
    )
    test_db.commit()

    service = TomorrowStarWindowService(test_db)
    summary = service.get_window_status(window_size=1)

    assert summary.items[0]["status"] == "market_regime_blocked"
    assert service._is_effectively_ready_item(summary.items[0]) is True


def test_ensure_window_recovers_stale_running_rows_before_rebuild(test_db, mocker):
    test_db.add(Stock(code="000001", name="PingAn"))
    test_db.add_all([
        StockDaily(code="000001", trade_date=date(2024, 1, 3), open=10, close=11, high=11, low=9, volume=100),
        StockDaily(code="000001", trade_date=date(2024, 1, 2), open=10, close=10.5, high=11, low=9, volume=100),
    ])
    test_db.add_all([
        TomorrowStarRun(pick_date=date(2024, 1, 3), status="running", candidate_count=0, analysis_count=0, trend_start_count=0),
        TomorrowStarRun(pick_date=date(2024, 1, 2), status="running", candidate_count=0, analysis_count=0, trend_start_count=0),
    ])
    test_db.commit()

    mocker.patch(
        "app.services.tomorrow_star_window_service.TomorrowStarWindowService._build_window_via_backtest",
        return_value={"success": True, "built_dates": [], "failed_dates": []},
    )

    result = TomorrowStarWindowService(test_db).ensure_window(window_size=2, source="bootstrap")

    assert result["recovered_incomplete_runs"] == 2
    rows = test_db.query(TomorrowStarRun).order_by(TomorrowStarRun.pick_date.desc()).all()
    assert [row.status for row in rows] == ["failed", "failed"]
    assert all(row.source == "bootstrap_recovered" for row in rows)


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


def test_ensure_window_creates_missing_stock_rows_for_backtest_events(test_db, mocker):
    test_db.add(Stock(code="000001", name="PingAn"))
    for trade_date in [date(2024, 1, 2), date(2024, 1, 3)]:
        test_db.add(
            StockDaily(
                code="000001",
                trade_date=trade_date,
                open=10,
                close=11,
                high=11,
                low=9,
                volume=100,
            )
        )
    test_db.commit()

    events_df = pd.DataFrame(
        [
            {
                "pick_date": "2024-01-03",
                "code": "603056",
                "strategy": "b1",
                "close": 18.6,
                "turnover_n": 987654.0,
                "kdj_j": 15.6,
                "verdict": "PASS",
                "total_score": 4.8,
                "signal_type": "trend_start",
                "comment": "created-stock-row",
                "details_json": {"signal_type": "trend_start"},
            }
        ]
    )
    mocker.patch("pipeline.backtest_quant.run_backtest", return_value=(events_df, {"date_range": {}}))
    mocker.patch("app.services.tushare_service.TushareService.sync_stock_names_to_db", return_value=None)

    result = TomorrowStarWindowService(test_db).ensure_window(window_size=2)

    assert result["failed_dates"] == []
    created_stock = test_db.query(Stock).filter(Stock.code == "603056").one()
    candidate = test_db.query(Candidate).filter(Candidate.pick_date == date(2024, 1, 3)).one()
    analysis = test_db.query(AnalysisResult).filter(AnalysisResult.pick_date == date(2024, 1, 3)).one()

    assert created_stock.market == "SH"
    assert candidate.code == "603056"
    assert analysis.code == "603056"


def test_maintain_trade_date_rebuilds_inconsistent_candidate_and_analysis_rows(test_db, mocker, tmp_path, monkeypatch):
    target_date = date(2024, 1, 3)
    monkeypatch.setattr(settings, "candidates_dir", tmp_path / "candidates")
    monkeypatch.setattr(settings, "review_dir", tmp_path / "review")
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

    latest_payload = json.loads((tmp_path / "candidates" / "candidates_latest.json").read_text(encoding="utf-8"))
    dated_payload = json.loads((tmp_path / "candidates" / "candidates_2024-01-03.json").read_text(encoding="utf-8"))
    suggestion_payload = json.loads((tmp_path / "review" / "2024-01-03" / "suggestion.json").read_text(encoding="utf-8"))

    assert latest_payload["pick_date"] == "2024-01-03"
    assert latest_payload["meta"]["total"] == 2
    assert dated_payload["pick_date"] == "2024-01-03"
    assert suggestion_payload["date"] == "2024-01-03"
    assert suggestion_payload["total_reviewed"] == 2
    assert suggestion_payload["recommendations"][0]["code"] == "000001"
    assert (tmp_path / "review" / "2024-01-03" / "000001.json").exists()
    assert (tmp_path / "review" / "2024-01-03" / "000002.json").exists()


def test_rebuild_trade_dates_batches_backtest_and_consecutive_recalc_once(test_db, tmp_path, monkeypatch, mocker):
    monkeypatch.setattr(settings, "candidates_dir", tmp_path / "candidates")
    monkeypatch.setattr(settings, "review_dir", tmp_path / "review")

    dates = [date(2024, 1, 2), date(2024, 1, 3)]
    test_db.add_all([
        Stock(code="000001", name="PingAn"),
        Stock(code="000002", name="Vanke"),
    ])
    for trade_date in dates:
        test_db.add(StockDaily(code="000001", trade_date=trade_date, open=10, close=11, high=11, low=9, volume=100))
        test_db.add(StockDaily(code="000002", trade_date=trade_date, open=20, close=21, high=22, low=19, volume=200))
    test_db.commit()

    events_df = pd.DataFrame(
        [
            {
                "pick_date": "2024-01-02",
                "code": "000001",
                "strategy": "b1",
                "close": 10.8,
                "turnover_n": 120000.0,
                "kdj_j": 10.1,
                "verdict": "WATCH",
                "total_score": 3.7,
                "signal_type": "watch",
                "comment": "watch",
                "details_json": {"signal_type": "watch"},
            },
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
    run_backtest_mock = mocker.patch("pipeline.backtest_quant.run_backtest", return_value=(events_df, {"date_range": {}}))
    recalc_mock = mocker.patch.object(
        CandidateService,
        "recalculate_consecutive_metrics",
        wraps=CandidateService.recalculate_consecutive_metrics,
    )
    mocker.patch("app.services.tushare_service.TushareService.sync_stock_names_to_db", return_value=None)

    results = TomorrowStarWindowService(test_db).rebuild_trade_dates(
        ["2024-01-02", "2024-01-03"],
        source="manual_repair",
        window_size=2,
    )

    assert run_backtest_mock.call_count == 1
    assert run_backtest_mock.call_args.kwargs["start_date"] == "2024-01-02"
    assert run_backtest_mock.call_args.kwargs["end_date"] == "2024-01-03"
    assert recalc_mock.call_count == 1
    assert [item["pick_date"] for item in results] == ["2024-01-02", "2024-01-03"]
    assert all(item["success"] is True for item in results)

    run_day_1 = test_db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == date(2024, 1, 2)).one()
    run_day_2 = test_db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == date(2024, 1, 3)).one()
    assert run_day_1.candidate_count == 1
    assert run_day_1.analysis_count == 1
    assert run_day_1.consecutive_candidate_count == 0
    assert run_day_2.candidate_count == 2
    assert run_day_2.analysis_count == 2
    assert run_day_2.trend_start_count == 1
    assert run_day_2.consecutive_candidate_count == 1

    latest_payload = json.loads((tmp_path / "candidates" / "candidates_latest.json").read_text(encoding="utf-8"))
    assert latest_payload["pick_date"] == "2024-01-03"
    assert (tmp_path / "candidates" / "candidates_2024-01-02.json").exists()
    assert (tmp_path / "candidates" / "candidates_2024-01-03.json").exists()


def test_ensure_window_repairs_latest_candidate_and_review_files(test_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "candidates_dir", tmp_path / "candidates")
    monkeypatch.setattr(settings, "review_dir", tmp_path / "review")

    target_date = date(2024, 1, 3)
    test_db.add(Stock(code="000001", name="PingAn"))
    test_db.add(StockDaily(code="000001", trade_date=target_date, open=10, close=11, high=11, low=9, volume=100))
    test_db.add(
        Candidate(
            pick_date=target_date,
            code="000001",
            strategy="b1",
            close_price=11.0,
            turnover=123456.0,
            kdj_j=12.3,
        )
    )
    test_db.add(
        AnalysisResult(
            pick_date=target_date,
            code="000001",
            reviewer="quant",
            verdict="PASS",
            total_score=4.2,
            signal_type="trend_start",
            comment="ok",
            details_json={
                "code": "000001",
                "strategy": "b1",
                "verdict": "PASS",
                "total_score": 4.2,
                "signal_type": "trend_start",
                "comment": "ok",
                "prefilter": {
                    "enabled": True,
                    "passed": True,
                    "blocked_by": [],
                    "summary": "通过第 4 步预过滤",
                },
            },
        )
    )
    test_db.add(
        TomorrowStarRun(
            pick_date=target_date,
            status="success",
            reviewer="quant",
            source="bootstrap",
            candidate_count=1,
            analysis_count=1,
            trend_start_count=1,
        )
    )
    test_db.commit()

    result = TomorrowStarWindowService(test_db).ensure_window(window_size=1)

    assert result["rebuilt_dates"] == []

    latest_payload = json.loads((tmp_path / "candidates" / "candidates_latest.json").read_text(encoding="utf-8"))
    suggestion_payload = json.loads((tmp_path / "review" / "2024-01-03" / "suggestion.json").read_text(encoding="utf-8"))
    stock_payload = json.loads((tmp_path / "review" / "2024-01-03" / "000001.json").read_text(encoding="utf-8"))

    assert latest_payload["pick_date"] == "2024-01-03"
    assert latest_payload["meta"]["total"] == 1
    assert suggestion_payload["date"] == "2024-01-03"
    assert suggestion_payload["recommendations"][0]["code"] == "000001"
    assert stock_payload["pick_date"] == "2024-01-03"
    assert stock_payload["verdict"] == "PASS"


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


def test_window_status_includes_tomorrow_star_count(test_db):
    trade_date = date(2024, 5, 8)
    test_db.add_all([
        Stock(code="000001", name="A"),
        Stock(code="000002", name="B"),
        Stock(code="000003", name="C"),
    ])
    test_db.add_all([
        StockDaily(code="000001", trade_date=trade_date, open=10, close=11, high=11, low=9, volume=100),
        StockDaily(code="000002", trade_date=trade_date, open=10, close=11, high=11, low=9, volume=100),
        StockDaily(code="000003", trade_date=trade_date, open=10, close=11, high=11, low=9, volume=100),
    ])
    test_db.add_all([
        AnalysisResult(
            pick_date=trade_date,
            code="000001",
            reviewer="quant",
            verdict="WATCH",
            signal_type="rebound",
            details_json={"tomorrow_star_pass": True},
        ),
        AnalysisResult(
            pick_date=trade_date,
            code="000002",
            reviewer="quant",
            verdict="PASS",
            signal_type="trend_start",
            details_json={"prefilter": {"passed": True}},
        ),
        AnalysisResult(
            pick_date=trade_date,
            code="000003",
            reviewer="quant",
            verdict="PASS",
            signal_type="trend_start",
            details_json={"prefilter": {"passed": False}},
        ),
    ])
    test_db.add(TomorrowStarRun(pick_date=trade_date, status="success", candidate_count=3, analysis_count=3, trend_start_count=2))
    test_db.commit()

    summary = TomorrowStarWindowService(test_db).get_window_status(window_size=1)

    assert summary.items[0]["tomorrow_star_count"] == 2
