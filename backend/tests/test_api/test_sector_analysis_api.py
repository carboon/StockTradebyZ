import json
from datetime import date
from typing import Any

from app.models import (
    Config,
    SectorAnalysisCandidate,
    SectorAnalysisResult,
    SectorAnalysisRun,
    Stock,
    StockActivePoolRank,
)


def _seed_sector_config(db: Any) -> None:
    db.add_all([
        Config(
            key="sector_analysis_catalog",
            value=json.dumps({
                "version": 1,
                "menuTitle": "板块分析",
                "defaultSectorKey": "overview",
                "sectors": [
                    {
                        "key": "compute",
                        "name": "算力",
                        "description": "算力主题",
                        "policyFocus": ["人工智能+"],
                        "focusTracks": ["服务器"],
                        "industryHints": ["通信设备"],
                        "order": 10,
                    },
                    {
                        "key": "marine",
                        "name": "海工",
                        "description": "海工主题",
                        "policyFocus": ["海洋强国"],
                        "focusTracks": ["船舶"],
                        "industryHints": ["船舶制造"],
                        "order": 20,
                    },
                ],
            }, ensure_ascii=False),
        ),
        Config(
            key="sector_analysis_pool",
            value=json.dumps({
                "compute": {
                    "算力A": "600001",
                    "算力B": "600002",
                },
                "marine": {
                    "海工A": "300001",
                },
            }, ensure_ascii=False),
        ),
    ])


def test_get_sector_analysis_overview_returns_independent_rankings(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    latest_date = date(2026, 5, 8)
    previous_date = date(2026, 5, 7)

    _seed_sector_config(db)
    db.add_all([
        Stock(code="600001", name="算力A", market="SH", industry="通信设备"),
        Stock(code="600002", name="算力B", market="SH", industry="通信设备"),
        Stock(code="300001", name="海工A", market="SZ", industry="船舶制造"),
        SectorAnalysisRun(pick_date=previous_date, sector_key="compute", status="success", candidate_count=2, analysis_count=2, trend_start_count=0, b1_count=0),
        SectorAnalysisRun(pick_date=previous_date, sector_key="marine", status="success", candidate_count=1, analysis_count=1, trend_start_count=1, b1_count=1),
        SectorAnalysisRun(pick_date=latest_date, sector_key="compute", status="success", candidate_count=2, analysis_count=2, trend_start_count=2, b1_count=2),
        SectorAnalysisRun(pick_date=latest_date, sector_key="marine", status="success", candidate_count=1, analysis_count=1, trend_start_count=0, b1_count=1),
        SectorAnalysisCandidate(pick_date=previous_date, sector_key="compute", code="600001", sector_names_json=["算力"], board_group="other", change_pct=2.0, b1_passed=False),
        SectorAnalysisCandidate(pick_date=previous_date, sector_key="compute", code="600002", sector_names_json=["算力"], board_group="other", change_pct=1.0, b1_passed=False),
        SectorAnalysisCandidate(pick_date=previous_date, sector_key="marine", code="300001", sector_names_json=["海工"], board_group="other", change_pct=6.5, b1_passed=True),
        SectorAnalysisCandidate(pick_date=latest_date, sector_key="compute", code="600001", sector_names_json=["算力"], board_group="other", change_pct=5.6, b1_passed=True),
        SectorAnalysisCandidate(pick_date=latest_date, sector_key="compute", code="600002", sector_names_json=["算力"], board_group="other", change_pct=4.9, b1_passed=True),
        SectorAnalysisCandidate(pick_date=latest_date, sector_key="marine", code="300001", sector_names_json=["海工"], board_group="other", change_pct=-2.3, b1_passed=True),
        SectorAnalysisResult(pick_date=previous_date, sector_key="compute", code="600001", reviewer="quant", b1_passed=False, verdict="WATCH", total_score=4.1, signal_type="rebound", comment="weak", details_json={}),
        SectorAnalysisResult(pick_date=previous_date, sector_key="compute", code="600002", reviewer="quant", b1_passed=False, verdict="WATCH", total_score=4.0, signal_type="rebound", comment="weak", details_json={}),
        SectorAnalysisResult(pick_date=previous_date, sector_key="marine", code="300001", reviewer="quant", b1_passed=True, verdict="PASS", total_score=5.5, signal_type="trend_start", comment="strong", details_json={}),
        SectorAnalysisResult(pick_date=latest_date, sector_key="compute", code="600001", reviewer="quant", b1_passed=True, verdict="PASS", total_score=5.4, signal_type="trend_start", comment="strong", details_json={}),
        SectorAnalysisResult(pick_date=latest_date, sector_key="compute", code="600002", reviewer="quant", b1_passed=True, verdict="PASS", total_score=5.1, signal_type="trend_start", comment="strong", details_json={}),
        SectorAnalysisResult(pick_date=latest_date, sector_key="marine", code="300001", reviewer="quant", b1_passed=True, verdict="WATCH", total_score=4.2, signal_type="rebound", comment="cool", details_json={}),
        StockActivePoolRank(trade_date=latest_date, code="600001", active_pool_rank=12, top_m=2000, n_turnover_days=43, turnover_n=10.0),
        StockActivePoolRank(trade_date=latest_date, code="600002", active_pool_rank=18, top_m=2000, n_turnover_days=43, turnover_n=9.0),
        StockActivePoolRank(trade_date=latest_date, code="300001", active_pool_rank=30, top_m=2000, n_turnover_days=43, turnover_n=8.0),
    ])
    db.commit()

    response = test_client_with_db.get("/api/v1/analysis/sector-analysis/overview")

    assert response.status_code == 200
    data = response.json()
    assert data["latest_date"] == "2026-05-08"
    assert data["sectors"][0]["sector_key"] == "compute"
    assert data["sectors"][0]["trend_start_count"] == 2
    assert data["history"][0]["points"]


def test_get_sector_analysis_rows_returns_rows_without_current_hot_dependency(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    pick_date = date(2026, 5, 8)

    _seed_sector_config(db)
    db.add(Stock(code="600001", name="算力A", market="SH", industry="通信设备"))
    db.add(SectorAnalysisRun(pick_date=pick_date, sector_key="compute", status="success", candidate_count=1, analysis_count=1, trend_start_count=1, b1_count=1))
    db.add(
        SectorAnalysisCandidate(
            pick_date=pick_date,
            sector_key="compute",
            code="600001",
            sector_names_json=["算力"],
            board_group="other",
            open_price=10.1,
            close_price=10.8,
            change_pct=6.9,
            turnover_rate=3.2,
            volume_ratio=1.4,
            b1_passed=True,
            kdj_j=12.5,
        )
    )
    db.add(
        SectorAnalysisResult(
            pick_date=pick_date,
            sector_key="compute",
            code="600001",
            reviewer="quant",
            b1_passed=True,
            verdict="PASS",
            total_score=5.3,
            signal_type="trend_start",
            comment="独立板块评分",
            turnover_rate=3.2,
            volume_ratio=1.4,
            details_json={
                "prefilter": {"passed": False, "summary": "板块略弱但形态强", "blocked_by": ["sector_strength_soft"]},
                "pullback_quality": "contracting",
                "pullback_negative_flags": ["down_volume_increasing"],
            },
        )
    )
    db.add(StockActivePoolRank(trade_date=pick_date, code="600001", active_pool_rank=9, top_m=2000, n_turnover_days=43, turnover_n=10.0))
    db.commit()

    response = test_client_with_db.get("/api/v1/analysis/sector-analysis/rows?sector_key=compute&date=2026-05-08")

    assert response.status_code == 200
    data = response.json()
    assert data["sector_key"] == "compute"
    assert data["total"] == 1
    assert data["rows"][0]["code"] == "600001"
    assert data["rows"][0]["comment"] == "独立板块评分"
    assert data["rows"][0]["prefilter_summary"] == "板块略弱但形态强"
    assert data["rows"][0]["pullback_negative_flags"] == ["down_volume_increasing"]
