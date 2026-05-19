"""Best-effort warming for read-heavy analysis views."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func

from app.database import SessionLocal
from app.models import AnalysisResult, Candidate, CurrentHotRun, SectorAnalysisRun
from app.services.analysis_service import analysis_service
from app.services.candidate_service import CandidateService
from app.services.current_hot_service import CurrentHotService
from app.services.sector_analysis_service import SectorAnalysisService
from app.services.tomorrow_star_window_service import TomorrowStarWindowService

logger = logging.getLogger(__name__)


def _serialize_window_summary(summary: Any) -> dict[str, Any]:
    if hasattr(summary, "to_dict"):
        return summary.to_dict()
    if hasattr(summary, "model_dump"):
        return summary.model_dump(mode="json")
    if isinstance(summary, dict):
        return summary
    raise TypeError(f"Unsupported tomorrow star window summary type: {type(summary)!r}")


def prewarm_latest_analysis_views(trade_date: str | None = None) -> dict[str, Any]:
    """Warm the latest read paths after data update.

    This is a best-effort operation. Failures are collected and returned without
    aborting the parent update workflow.
    """

    result: dict[str, Any] = {
        "success": True,
        "trade_date": trade_date,
        "steps": {},
        "failed": [],
    }

    with SessionLocal() as db:
        latest_tomorrow_star_date = trade_date or analysis_service.get_latest_candidate_date() or analysis_service.get_latest_result_date()
        latest_current_hot_date = (
            trade_date
            or db.query(func.max(CurrentHotRun.pick_date)).filter(CurrentHotRun.status == "success").scalar()
        )
        latest_sector_date = (
            trade_date
            or db.query(func.max(SectorAnalysisRun.pick_date)).filter(SectorAnalysisRun.status == "success").scalar()
        )

        def run_step(name: str, callback):
            try:
                value = callback()
                result["steps"][name] = value
            except Exception as exc:
                logger.warning("视图预热失败: step=%s error=%s", name, exc)
                result["success"] = False
                result["failed"].append({"step": name, "error": str(exc)})

        run_step(
            "tomorrow_star_window",
            lambda: _serialize_window_summary(TomorrowStarWindowService(db).get_window_status(window_size=120)),
        )

        if latest_tomorrow_star_date:
            run_step(
                "tomorrow_star_candidates",
                lambda: {
                    "pick_date": str(latest_tomorrow_star_date),
                    "total": len(CandidateService(db).load_candidates(str(latest_tomorrow_star_date), limit=2000)[1]),
                },
            )
            run_step(
                "tomorrow_star_results",
                lambda: {
                    "pick_date": str(latest_tomorrow_star_date),
                    "total": int(analysis_service.get_analysis_results(str(latest_tomorrow_star_date)).get("total", 0) or 0),
                },
            )

        current_hot_service = CurrentHotService(db)
        run_step("current_hot_dates", lambda: current_hot_service.get_dates(window_size=120))
        if latest_current_hot_date:
            current_hot_date_text = str(latest_current_hot_date)
            run_step(
                "current_hot_candidates",
                lambda: current_hot_service.load_candidates(current_hot_date_text, limit=200),
            )
            run_step(
                "current_hot_results",
                lambda: current_hot_service.get_results(current_hot_date_text),
            )
        run_step(
            "current_hot_sector_overview",
            lambda: current_hot_service.get_sector_analysis(window_size=120, top_n=5),
        )

        sector_service = SectorAnalysisService(db)
        sector_overview = None
        run_step(
            "sector_analysis_overview",
            lambda: sector_service.get_sector_analysis(window_size=120, top_n=5),
        )
        sector_overview = result["steps"].get("sector_analysis_overview")
        if isinstance(sector_overview, dict):
            sectors = sector_overview.get("sectors") or []
            sector_key = str(sectors[0].get("sector_key") or "").strip() if sectors else ""
            if sector_key and latest_sector_date:
                sector_date_text = str(latest_sector_date)
                run_step(
                    "sector_analysis_rows",
                    lambda: sector_service.get_sector_date_rows(sector_key=sector_key, pick_date=sector_date_text),
                )

    return result
