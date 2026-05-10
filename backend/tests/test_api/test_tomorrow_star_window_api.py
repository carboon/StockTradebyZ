from datetime import date

from app.models import AnalysisResult, Candidate, Stock, StockDaily, TomorrowStarRun


def test_get_tomorrow_star_dates_reads_window_status(test_client_with_db):
    db = test_client_with_db.db
    db.add(Stock(code="000001", name="PingAn"))
    db.add(StockDaily(code="000001", trade_date=date(2024, 1, 3), open=10, close=11, high=11, low=9, volume=100))
    db.add(Candidate(pick_date=date(2024, 1, 3), code="000001", strategy="b1"))
    db.add(AnalysisResult(pick_date=date(2024, 1, 3), code="000001", reviewer="quant", verdict="PASS", signal_type="trend_start"))
    db.add(TomorrowStarRun(pick_date=date(2024, 1, 3), status="success", candidate_count=1, analysis_count=1, trend_start_count=1))
    db.commit()

    response = test_client_with_db.get("/api/v1/analysis/tomorrow-star/dates")
    assert response.status_code == 200
    data = response.json()
    assert data["dates"] == ["2024-01-03"]
    assert data["history"][0]["status"] == "success"
    assert data["window_status"]["ready_count"] == 1


def test_get_tomorrow_star_dates_exposes_market_regime_block_reason(test_client_with_db):
    db = test_client_with_db.db
    db.add(Stock(code="000001", name="PingAn"))
    db.add(StockDaily(code="000001", trade_date=date(2024, 1, 3), open=10, close=11, high=11, low=9, volume=100))
    db.add(
        TomorrowStarRun(
            pick_date=date(2024, 1, 3),
            status="success",
            candidate_count=0,
            analysis_count=0,
            trend_start_count=0,
            meta_json={
                "market_regime_blocked": True,
                "market_regime_info": {
                    "passed": False,
                    "summary": "中证 500 / 创业板指环境未达标",
                    "details": ["中证 500 趋势偏弱", "创业板指量价配合不足"],
                },
            },
        )
    )
    db.commit()

    response = test_client_with_db.get("/api/v1/analysis/tomorrow-star/dates")
    assert response.status_code == 200
    data = response.json()

    assert data["history"][0]["status"] == "market_regime_blocked"
    assert data["history"][0]["market_regime_blocked"] is True
    assert data["history"][0]["market_regime_info"]["summary"] == "中证 500 / 创业板指环境未达标"
    assert data["window_status"]["history"][0]["market_regime_info"]["details"] == ["中证 500 趋势偏弱", "创业板指量价配合不足"]


def test_get_tomorrow_star_results_reads_db(test_client_with_db):
    db = test_client_with_db.db
    db.add(Stock(code="000001", name="PingAn"))
    db.add(AnalysisResult(
        pick_date=date(2024, 1, 3),
        code="000001",
        reviewer="quant",
        verdict="PASS",
        total_score=4.2,
        signal_type="trend_start",
        comment="ok",
        details_json={
            "prefilter": {
                "passed": False,
                "summary": "中证 500 / 创业板指环境未达标",
                "blocked_by": ["market_regime"],
            }
        },
    ))
    db.commit()

    response = test_client_with_db.get("/api/v1/analysis/tomorrow-star/results?date=2024-01-03")
    assert response.status_code == 200
    data = response.json()
    assert data["pick_date"] == "2024-01-03"
    assert data["total"] == 1
    assert data["results"][0]["code"] == "000001"
    assert data["results"][0]["name"] == "PingAn"
    assert data["results"][0]["total_score"] == 4.2
    assert data["results"][0]["prefilter_passed"] is False
    assert data["results"][0]["prefilter_summary"] == "中证 500 / 创业板指环境未达标"
    assert data["results"][0]["prefilter_blocked_by"] == ["market_regime"]


def test_get_tomorrow_star_results_prioritizes_trend_start_then_score(test_client_with_db):
    db = test_client_with_db.db
    pick_date = date(2024, 1, 3)
    db.add_all([
        Stock(code="000001", name="A"),
        Stock(code="000002", name="B"),
        Stock(code="000003", name="C"),
        Stock(code="000004", name="D"),
    ])
    db.add_all([
        AnalysisResult(pick_date=pick_date, code="000001", reviewer="quant", verdict="WATCH", total_score=4.6, signal_type="rebound"),
        AnalysisResult(pick_date=pick_date, code="000002", reviewer="quant", verdict="PASS", total_score=4.2, signal_type="trend_start"),
        AnalysisResult(pick_date=pick_date, code="000003", reviewer="quant", verdict="PASS", total_score=5.0, signal_type="trend_start"),
        AnalysisResult(pick_date=pick_date, code="000004", reviewer="quant", verdict="FAIL", total_score=4.9, signal_type="distribution_risk"),
    ])
    db.commit()

    response = test_client_with_db.get("/api/v1/analysis/tomorrow-star/results?date=2024-01-03")

    assert response.status_code == 200
    data = response.json()
    assert [item["code"] for item in data["results"]] == ["000003", "000002", "000004", "000001"]
