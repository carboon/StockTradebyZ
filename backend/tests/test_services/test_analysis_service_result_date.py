from datetime import date
from pathlib import Path

import app.services.analysis_service as analysis_service_module
from app.models import AnalysisResult, Stock
from app.services.analysis_service import AnalysisService


def test_get_latest_result_date_prefers_database(test_db) -> None:
    test_db.add(Stock(code="000001", name="Ping An", market="SZ"))
    test_db.add(Stock(code="000002", name="Vanke", market="SZ"))
    test_db.add(
        AnalysisResult(
            pick_date=date(2026, 5, 6),
            code="000001",
            reviewer="quant",
            verdict="PASS",
            signal_type="trend_start",
        )
    )
    test_db.add(
        AnalysisResult(
            pick_date=date(2026, 5, 8),
            code="000002",
            reviewer="quant",
            verdict="PASS",
            signal_type="trend_start",
        )
    )
    test_db.commit()

    original_session_local = analysis_service_module.SessionLocal
    analysis_service_module.SessionLocal = lambda: test_db
    try:
        service = AnalysisService()
        assert service.get_latest_result_date() == "2026-05-08"
    finally:
        analysis_service_module.SessionLocal = original_session_local


def test_get_latest_result_date_falls_back_to_review_directory(tmp_path, monkeypatch) -> None:
    review_dir = tmp_path / "data" / "review"
    (review_dir / "2026-05-06").mkdir(parents=True, exist_ok=True)
    (review_dir / "2026-05-06" / "suggestion.json").write_text("{}", encoding="utf-8")
    (review_dir / "2026-05-08").mkdir(parents=True, exist_ok=True)
    (review_dir / "2026-05-08" / "suggestion.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(analysis_service_module, "ROOT", tmp_path)
    monkeypatch.setattr(analysis_service_module.settings, "review_dir", Path("data/review"))

    class _FailingSessionLocal:
        def __call__(self):
            raise RuntimeError("db unavailable")

    original_session_local = analysis_service_module.SessionLocal
    analysis_service_module.SessionLocal = _FailingSessionLocal()
    try:
        service = AnalysisService()
        assert service.get_latest_result_date() == "2026-05-08"
    finally:
        analysis_service_module.SessionLocal = original_session_local
