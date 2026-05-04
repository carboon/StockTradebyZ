"""
Tomorrow Star 180-day rolling window maintenance service.
"""
from __future__ import annotations

import os
import logging
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AnalysisResult, Candidate, StockDaily, TomorrowStarRun
from app.services.tushare_service import TushareService
from app.time_utils import utc_now

ROOT = Path(__file__).parent.parent.parent.parent
logger = logging.getLogger(__name__)


def _safe_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@dataclass
class TomorrowStarWindowSummary:
    window_size: int
    latest_date: Optional[str]
    ready_count: int
    missing_count: int
    running_count: int
    failed_count: int
    pending_count: int
    items: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_size": self.window_size,
            "latest_date": self.latest_date,
            "ready_count": self.ready_count,
            "missing_count": self.missing_count,
            "running_count": self.running_count,
            "failed_count": self.failed_count,
            "pending_count": self.pending_count,
            "items": self.items,
            "history": self.items,
        }


class TomorrowStarWindowService:
    DEFAULT_WINDOW_SIZE = 180
    DEFAULT_REVIEWER = "quant"
    DEFAULT_SOURCE = "bootstrap"
    DEFAULT_STRATEGY_VERSION = "v1"
    LOCK_KEY = 902180

    def __init__(self, db: Optional[Session] = None):
        self.db = db or SessionLocal()
        self._owns_session = db is None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._owns_session:
            self.db.close()

    def _try_advisory_lock(self) -> bool:
        try:
            return bool(self.db.execute(select(func.pg_try_advisory_lock(self.LOCK_KEY))).scalar())
        except Exception:
            return True

    def _unlock_advisory(self) -> None:
        try:
            self.db.execute(select(func.pg_advisory_unlock(self.LOCK_KEY)))
            self.db.commit()
        except Exception:
            self.db.rollback()

    def get_recent_trade_dates(self, window_size: int = DEFAULT_WINDOW_SIZE) -> list[str]:
        rows = self.db.execute(
            select(StockDaily.trade_date)
            .distinct()
            .order_by(StockDaily.trade_date.desc())
            .limit(window_size)
        ).scalars().all()
        return [row.isoformat() for row in rows if row]

    def _get_latest_trade_date(self) -> Optional[str]:
        row = self.db.execute(
            select(StockDaily.trade_date)
            .order_by(StockDaily.trade_date.desc())
            .limit(1)
        ).scalar()
        return row.isoformat() if row else None

    def _upsert_run(
        self,
        pick_date_text: str,
        *,
        status: str,
        reviewer: str = DEFAULT_REVIEWER,
        window_size: int = DEFAULT_WINDOW_SIZE,
        source: str = DEFAULT_SOURCE,
        strategy_version: str = DEFAULT_STRATEGY_VERSION,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> TomorrowStarRun:
        pick_dt = date.fromisoformat(pick_date_text)
        run = self.db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == pick_dt).first()
        if run is None:
            run = TomorrowStarRun(
                pick_date=pick_dt,
                reviewer=reviewer,
                window_size=window_size,
                source=source,
                strategy_version=strategy_version,
            )
            self.db.add(run)

        run.status = status
        run.reviewer = reviewer
        run.window_size = window_size
        run.source = source
        run.strategy_version = strategy_version
        run.error_message = error_message
        if started_at is not None:
            run.started_at = started_at
        if finished_at is not None:
            run.finished_at = finished_at
        return run

    def _refresh_run_counts(self, run: TomorrowStarRun) -> None:
        pick_dt = run.pick_date
        run.candidate_count = int(
            self.db.query(func.count(Candidate.id)).filter(Candidate.pick_date == pick_dt).scalar() or 0
        )
        run.analysis_count = int(
            self.db.query(func.count(AnalysisResult.id)).filter(AnalysisResult.pick_date == pick_dt).scalar() or 0
        )
        run.trend_start_count = int(
            self.db.query(func.count(AnalysisResult.id))
            .filter(
                AnalysisResult.pick_date == pick_dt,
                AnalysisResult.signal_type == "trend_start",
            )
            .scalar()
            or 0
        )

    def _sync_analysis_results_for_date(self, trade_date: str, reviewer: str) -> int:
        review_dir = ROOT / "data" / "review" / trade_date
        if not review_dir.exists():
            return 0

        pick_dt = date.fromisoformat(trade_date)
        stock_files = sorted(
            path for path in review_dir.glob("*.json")
            if path.name != "suggestion.json"
        )
        if not stock_files:
            return 0

        codes = [path.stem.zfill(6) for path in stock_files if path.stem.isdigit()]
        if codes:
            try:
                TushareService().sync_stock_names_to_db(self.db, codes)
            except Exception:
                logger.warning("sync_stock_names_to_db failed for %s", trade_date)

        self.db.query(AnalysisResult).filter(AnalysisResult.pick_date == pick_dt).delete(synchronize_session=False)
        rows: list[AnalysisResult] = []
        for path in stock_files:
            payload = {}
            try:
                payload = __import__("json").load(path.open("r", encoding="utf-8"))
            except Exception:
                logger.warning("failed to read review payload: %s", path)
                continue
            code = str(payload.get("code") or path.stem).zfill(6)
            if not code or code == "000000":
                continue
            rows.append(
                AnalysisResult(
                    pick_date=pick_dt,
                    code=code,
                    reviewer=reviewer,
                    verdict=payload.get("verdict"),
                    total_score=float(payload["total_score"]) if payload.get("total_score") is not None else None,
                    signal_type=payload.get("signal_type"),
                    comment=payload.get("comment"),
                    details_json=payload,
                )
            )

        if rows:
            self.db.add_all(rows)
        self.db.flush()
        return len(rows)

    def _replace_trade_date_payload(
        self,
        trade_date: str,
        events: list[dict[str, Any]],
        *,
        reviewer: str,
        source: str,
        window_size: int,
        started_at: datetime,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> dict[str, int]:
        pick_dt = date.fromisoformat(trade_date)
        codes = sorted({str(event.get("code", "")).zfill(6) for event in events if event.get("code")})
        if codes:
            try:
                TushareService().sync_stock_names_to_db(self.db, codes)
            except Exception:
                logger.warning("sync_stock_names_to_db failed for %s", trade_date)

        self.db.query(Candidate).filter(Candidate.pick_date == pick_dt).delete(synchronize_session=False)
        self.db.query(AnalysisResult).filter(AnalysisResult.pick_date == pick_dt).delete(synchronize_session=False)

        candidate_rows: list[Candidate] = []
        analysis_rows: list[AnalysisResult] = []
        for event in events:
            code = str(event.get("code", "")).zfill(6)
            if not code or code == "000000":
                continue
            candidate_rows.append(
                Candidate(
                    pick_date=pick_dt,
                    code=code,
                    strategy=event.get("strategy"),
                    close_price=_safe_optional_float(event.get("close")),
                    turnover=_safe_optional_float(event.get("turnover_n")),
                    b1_passed=event.get("strategy") == "b1",
                    kdj_j=_safe_optional_float(event.get("kdj_j")),
                )
            )
            analysis_rows.append(
                AnalysisResult(
                    pick_date=pick_dt,
                    code=code,
                    reviewer=reviewer,
                    verdict=event.get("verdict"),
                    total_score=_safe_optional_float(event.get("total_score")),
                    signal_type=event.get("signal_type"),
                    comment=event.get("comment"),
                    details_json=event.get("details_json") or event,
                )
            )

        if candidate_rows:
            self.db.add_all(candidate_rows)
        if analysis_rows:
            self.db.add_all(analysis_rows)

        run = self._upsert_run(
            trade_date,
            status=status,
            reviewer=reviewer,
            source=source,
            window_size=window_size,
            started_at=started_at,
            finished_at=utc_now(),
            error_message=error_message,
        )
        run.candidate_count = len(candidate_rows)
        run.analysis_count = len(analysis_rows)
        run.trend_start_count = sum(1 for event in events if event.get("signal_type") == "trend_start")
        self.db.flush()
        return {
            "candidate_count": run.candidate_count,
            "analysis_count": run.analysis_count,
            "trend_start_count": run.trend_start_count,
        }

    def _build_window_via_backtest(
        self,
        trade_dates: list[str],
        *,
        reviewer: str,
        source: str,
        window_size: int,
    ) -> dict[str, Any]:
        if not trade_dates:
            return {"success": True, "built_dates": [], "failed_dates": []}

        from pipeline.backtest_quant import run_backtest

        started_at = utc_now()
        for trade_date in trade_dates:
            self._upsert_run(
                trade_date,
                status="running",
                reviewer=reviewer,
                source=source,
                window_size=window_size,
                started_at=started_at,
                finished_at=None,
                error_message=None,
            )
        self.db.commit()

        start_date = min(trade_dates)
        end_date = max(trade_dates)
        events_df, _summary = run_backtest(
            start_date=start_date,
            end_date=end_date,
        )
        if events_df is None or events_df.empty:
            grouped_events: dict[str, list[dict[str, Any]]] = {}
        else:
            normalized = events_df.where(pd.notna(events_df), None)
            grouped_events = {
                str(pick_date): group.to_dict(orient="records")
                for pick_date, group in normalized.groupby("pick_date", sort=False)
            }

        built_dates: list[str] = []
        for trade_date in trade_dates:
            counts = self._replace_trade_date_payload(
                trade_date,
                grouped_events.get(trade_date, []),
                reviewer=reviewer,
                source=source,
                window_size=window_size,
                started_at=started_at,
            )
            built_dates.append(trade_date)
            logger.info(
                "tomorrow star backfilled %s candidates=%s analysis=%s trend_start=%s",
                trade_date,
                counts["candidate_count"],
                counts["analysis_count"],
                counts["trend_start_count"],
            )
        self.db.commit()
        return {"success": True, "built_dates": built_dates, "failed_dates": []}

    def get_window_status(self, window_size: int = DEFAULT_WINDOW_SIZE) -> TomorrowStarWindowSummary:
        target_dates = self.get_recent_trade_dates(window_size)
        latest_date = target_dates[0] if target_dates else None
        if not target_dates:
            return TomorrowStarWindowSummary(
                window_size=window_size,
                latest_date=None,
                ready_count=0,
                missing_count=0,
                running_count=0,
                failed_count=0,
                pending_count=0,
                items=[],
            )

        pick_dates = [date.fromisoformat(value) for value in target_dates]
        run_map = {
            run.pick_date.isoformat(): run
            for run in self.db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date.in_(pick_dates)).all()
        }
        candidate_counts = {
            row.pick_date.isoformat(): int(row.count or 0)
            for row in self.db.query(
                Candidate.pick_date,
                func.count(Candidate.id).label("count"),
            )
            .filter(Candidate.pick_date.in_(pick_dates))
            .group_by(Candidate.pick_date)
            .all()
        }
        analysis_counts = {
            row.pick_date.isoformat(): int(row.count or 0)
            for row in self.db.query(
                AnalysisResult.pick_date,
                func.count(AnalysisResult.id).label("count"),
            )
            .filter(AnalysisResult.pick_date.in_(pick_dates))
            .group_by(AnalysisResult.pick_date)
            .all()
        }
        trend_counts = {
            row.pick_date.isoformat(): int(row.count or 0)
            for row in self.db.query(
                AnalysisResult.pick_date,
                func.count(AnalysisResult.id).label("count"),
            )
            .filter(
                AnalysisResult.pick_date.in_(pick_dates),
                AnalysisResult.signal_type == "trend_start",
            )
            .group_by(AnalysisResult.pick_date)
            .all()
        }

        items: list[dict[str, Any]] = []
        ready_count = missing_count = running_count = failed_count = pending_count = 0
        for pick_date_text in target_dates:
            run = run_map.get(pick_date_text)
            candidate_count = candidate_counts.get(pick_date_text, 0)
            analysis_count = analysis_counts.get(pick_date_text, 0)
            trend_start_count = trend_counts.get(pick_date_text, 0)

            if run is not None:
                status = run.status
            elif candidate_count > 0 and analysis_count > 0:
                status = "success"
            else:
                status = "missing"

            if status == "success":
                ready_count += 1
            elif status == "running":
                running_count += 1
            elif status == "failed":
                failed_count += 1
            elif status == "pending":
                pending_count += 1
            else:
                missing_count += 1

            items.append(
                {
                    "pick_date": pick_date_text,
                    "date": pick_date_text,
                    "count": candidate_count,
                    "pass_count": trend_start_count,
                    "candidate_count": candidate_count,
                    "analysis_count": analysis_count,
                    "trend_start_count": trend_start_count,
                    "status": status,
                    "error_message": run.error_message if run else None,
                    "is_latest": pick_date_text == latest_date,
                    "reviewer": run.reviewer if run else None,
                    "source": run.source if run else None,
                    "started_at": run.started_at.isoformat() if run and run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run and run.finished_at else None,
                }
            )

        return TomorrowStarWindowSummary(
            window_size=window_size,
            latest_date=latest_date,
            ready_count=ready_count,
            missing_count=missing_count,
            running_count=running_count,
            failed_count=failed_count,
            pending_count=pending_count,
            items=items,
        )

    def _is_effectively_ready_item(self, item: dict[str, Any]) -> bool:
        if item.get("status") != "success":
            return False
        candidate_count = int(item.get("candidate_count", 0) or 0)
        analysis_count = int(item.get("analysis_count", 0) or 0)
        if candidate_count > 0 or analysis_count > 0:
            return True

        pick_date = item.get("pick_date")
        if not pick_date:
            return True

        source = item.get("source")
        if source == "manual_rebuild":
            # 手工单日旧逻辑曾产出“success 但 0 行”的假完成记录，不能阻止后续批量补齐。
            return False

        return True

    def reconcile_run_rows(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        *,
        reviewer: str = DEFAULT_REVIEWER,
        source: str = "reconciled",
    ) -> int:
        summary = self.get_window_status(window_size)
        inserted = 0
        for item in summary.items:
            if item["status"] != "success":
                continue
            if item.get("reviewer"):
                continue
            run = self._upsert_run(
                item["pick_date"],
                status="success",
                reviewer=reviewer,
                source=source,
                window_size=window_size,
                started_at=utc_now(),
                finished_at=utc_now(),
                error_message=None,
            )
            run.candidate_count = int(item.get("candidate_count", 0) or 0)
            run.analysis_count = int(item.get("analysis_count", 0) or 0)
            run.trend_start_count = int(item.get("trend_start_count", 0) or 0)
            inserted += 1
        if inserted:
            self.db.commit()
        return inserted

    def build_for_trade_date(
        self,
        trade_date: str,
        *,
        reviewer: str = DEFAULT_REVIEWER,
        source: str = DEFAULT_SOURCE,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ) -> dict[str, Any]:
        if not self._try_advisory_lock():
            return {"success": False, "status": "locked", "pick_date": trade_date}

        try:
            started_at = utc_now()
            run = self._upsert_run(
                trade_date,
                status="running",
                reviewer=reviewer,
                source=source,
                window_size=window_size,
                started_at=started_at,
                finished_at=None,
                error_message=None,
            )
            self.db.commit()

            env = dict(os.environ)
            env["TARGET_DATE"] = trade_date
            result = subprocess.run(
                [sys.executable, str(ROOT / "run_all.py"), "--reviewer", reviewer, "--skip-fetch", "--db"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=3600,
                env=env,
            )
            if result.returncode != 0:
                run = self._upsert_run(
                    trade_date,
                    status="failed",
                    reviewer=reviewer,
                    source=source,
                    window_size=window_size,
                    error_message=(result.stderr or result.stdout or "").strip()[:4000],
                    finished_at=utc_now(),
                )
                self._refresh_run_counts(run)
                self.db.commit()
                return {
                    "success": False,
                    "status": "failed",
                    "pick_date": trade_date,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }

            synced_analysis = self._sync_analysis_results_for_date(trade_date, reviewer)

            run = self._upsert_run(
                trade_date,
                status="success",
                reviewer=reviewer,
                source=source,
                window_size=window_size,
                error_message=None,
                finished_at=utc_now(),
            )
            self._refresh_run_counts(run)
            self.db.commit()
            return {
                "success": True,
                "status": "success",
                "pick_date": trade_date,
                "candidate_count": run.candidate_count,
                "analysis_count": run.analysis_count,
                "trend_start_count": run.trend_start_count,
                "analysis_synced": synced_analysis,
            }
        except Exception as exc:
            self.db.rollback()
            run = self._upsert_run(
                trade_date,
                status="failed",
                reviewer=reviewer,
                source=source,
                window_size=window_size,
                error_message=str(exc)[:4000],
                finished_at=utc_now(),
            )
            self._refresh_run_counts(run)
            self.db.commit()
            logger.exception("build_for_trade_date failed: %s", trade_date)
            return {"success": False, "status": "failed", "pick_date": trade_date, "error": str(exc)}
        finally:
            self._unlock_advisory()

    def ensure_window(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        *,
        reviewer: str = DEFAULT_REVIEWER,
        source: str = DEFAULT_SOURCE,
    ) -> dict[str, Any]:
        summary = self.get_window_status(window_size)
        target_dates = [item["pick_date"] for item in summary.items]
        missing_dates = [
            item["pick_date"]
            for item in summary.items
            if not self._is_effectively_ready_item(item)
        ]
        results = []
        if missing_dates:
            backfill_result = self._build_window_via_backtest(
                sorted(missing_dates),
                reviewer=reviewer,
                source=source,
                window_size=window_size,
            )
            results.extend(
                {
                    "success": failed_date not in set(backfill_result.get("failed_dates", [])),
                    "pick_date": failed_date,
                }
                for failed_date in backfill_result.get("built_dates", [])
            )
        self.reconcile_run_rows(window_size, reviewer=reviewer, source=source)
        pruned = self.prune_window(window_size)
        return {
            "window_size": window_size,
            "target_dates": target_dates,
            "rebuilt_dates": [item.get("pick_date") for item in results if item.get("success")],
            "failed_dates": [item.get("pick_date") for item in results if not item.get("success")],
            "pruned_dates": pruned.get("deleted_dates", []),
            "summary": self.get_window_status(window_size).to_dict(),
        }

    def prune_window(self, window_size: int = DEFAULT_WINDOW_SIZE) -> dict[str, Any]:
        keep_dates = self.get_recent_trade_dates(window_size)
        if not keep_dates:
            return {"deleted_dates": []}
        keep_pick_dates = [date.fromisoformat(value) for value in keep_dates]

        delete_candidate_rows = (
            self.db.query(Candidate)
            .filter(~Candidate.pick_date.in_(keep_pick_dates))
            .all()
        )
        delete_analysis_rows = (
            self.db.query(AnalysisResult)
            .filter(~AnalysisResult.pick_date.in_(keep_pick_dates))
            .all()
        )
        delete_run_rows = (
            self.db.query(TomorrowStarRun)
            .filter(~TomorrowStarRun.pick_date.in_(keep_pick_dates))
            .all()
        )
        deleted_dates = sorted(
            {
                *(row.pick_date.isoformat() for row in delete_candidate_rows),
                *(row.pick_date.isoformat() for row in delete_analysis_rows),
                *(row.pick_date.isoformat() for row in delete_run_rows),
            }
        )

        self.db.query(Candidate).filter(~Candidate.pick_date.in_(keep_pick_dates)).delete(synchronize_session=False)
        self.db.query(AnalysisResult).filter(~AnalysisResult.pick_date.in_(keep_pick_dates)).delete(synchronize_session=False)
        self.db.query(TomorrowStarRun).filter(~TomorrowStarRun.pick_date.in_(keep_pick_dates)).delete(synchronize_session=False)
        self.db.commit()
        return {"deleted_dates": deleted_dates, "keep_dates": keep_dates}


_tomorrow_star_window_service: Optional[TomorrowStarWindowService] = None


def get_tomorrow_star_window_service() -> TomorrowStarWindowService:
    global _tomorrow_star_window_service
    if _tomorrow_star_window_service is None:
        _tomorrow_star_window_service = TomorrowStarWindowService()
    return _tomorrow_star_window_service
