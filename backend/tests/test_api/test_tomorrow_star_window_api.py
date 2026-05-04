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
    ))
    db.commit()

    response = test_client_with_db.get("/api/v1/analysis/tomorrow-star/results?date=2024-01-03")
    assert response.status_code == 200
    data = response.json()
    assert data["pick_date"] == "2024-01-03"
    assert data["total"] == 1
    assert data["results"][0]["code"] == "000001"
    assert data["results"][0]["total_score"] == 4.2
