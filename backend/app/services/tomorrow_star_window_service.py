"""
Tomorrow Star 120-day rolling window maintenance service.
"""
from __future__ import annotations

import json
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

from app.config import settings
from app.database import SessionLocal
from app.models import AnalysisResult, Candidate, Stock, StockDaily, Task, TomorrowStarRun
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
    DEFAULT_WINDOW_SIZE = 120
    DEFAULT_REVIEWER = "quant"
    DEFAULT_SOURCE = "bootstrap"
    DEFAULT_STRATEGY_VERSION = "v1"
    LOCK_KEY = 902180
    ACTIVE_TASK_TYPES = ("full_update", "incremental_update", "tomorrow_star", "recent_120_rebuild")

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

    def _has_active_generation_task(self) -> bool:
        active_task = (
            self.db.query(Task.id)
            .filter(
                Task.task_type.in_(self.ACTIVE_TASK_TYPES),
                Task.status.in_(("pending", "running")),
            )
            .order_by(Task.created_at.desc())
            .first()
        )
        return active_task is not None

    def _resolve_display_status(
        self,
        run: Optional[TomorrowStarRun],
        *,
        candidate_count: int,
        analysis_count: int,
        has_active_task: bool,
    ) -> str:
        if run is None:
            return "success" if candidate_count > 0 and analysis_count > 0 else "missing"

        # 检查市场环境阻断
        if run.meta_json and run.meta_json.get("market_regime_blocked"):
            return "market_regime_blocked"

        status = str(run.status or "").strip().lower() or "missing"
        if status == "success":
            return "success"
        if status in {"running", "pending"}:
            if candidate_count > 0 and analysis_count > 0:
                return "success"
            if not has_active_task:
                return "missing"
        return status

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, path)

    @staticmethod
    def _is_recommendable_result(result: dict[str, Any], min_score_threshold: float) -> bool:
        score = result.get("total_score", result.get("score"))
        if score is None:
            return False
        try:
            normalized_score = float(score)
        except (TypeError, ValueError):
            return False
        return result.get("verdict") == "PASS" and normalized_score >= min_score_threshold

    def _build_suggestion_payload(
        self,
        trade_date: str,
        results: list[dict[str, Any]],
        *,
        min_score_threshold: float,
    ) -> dict[str, Any]:
        passed = [
            item for item in results
            if self._is_recommendable_result(item, min_score_threshold)
        ]
        passed.sort(
            key=lambda item: float(item.get("total_score", item.get("score")) or 0),
            reverse=True,
        )
        recommendations = [
            {
                "rank": index + 1,
                "code": item.get("code"),
                "verdict": item.get("verdict", ""),
                "total_score": item.get("total_score", item.get("score")),
                "signal_type": item.get("signal_type", ""),
                "comment": item.get("comment", ""),
            }
            for index, item in enumerate(passed)
        ]
        excluded = [
            item.get("code")
            for item in results
            if not self._is_recommendable_result(item, min_score_threshold) and item.get("code")
        ]

        blocked_by_counts: dict[str, int] = {}
        prefilter_passed = 0
        for item in results:
            prefilter = item.get("prefilter") or {}
            if prefilter.get("passed", True):
                prefilter_passed += 1
            for key in prefilter.get("blocked_by", []):
                key_text = str(key).strip()
                if not key_text:
                    continue
                blocked_by_counts[key_text] = blocked_by_counts.get(key_text, 0) + 1

        return {
            "date": trade_date,
            "min_score_threshold": min_score_threshold,
            "total_reviewed": len(results),
            "recommendations": recommendations,
            "excluded": excluded,
            "prefilter_summary": {
                "passed": prefilter_passed,
                "blocked": len(results) - prefilter_passed,
                "blocked_by": blocked_by_counts,
            },
        }

    @staticmethod
    def _infer_market(code: str) -> str:
        normalized = str(code or "").strip().split(".")[0].zfill(6)
        if normalized.startswith(("600", "601", "603", "605", "688", "689")):
            return "SH"
        if normalized.startswith(("430", "8", "920")):
            return "BJ"
        return "SZ"

    def _ensure_stock_rows(self, codes: list[str]) -> None:
        normalized_codes = sorted(
            {
                str(code or "").strip().split(".")[0].zfill(6)
                for code in codes
                if str(code or "").strip()
            }
        )
        if not normalized_codes:
            return

        try:
            TushareService().sync_stock_names_to_db(self.db, normalized_codes)
        except Exception:
            logger.warning("sync_stock_names_to_db failed for codes=%s", normalized_codes[:10])

        existing_codes = {
            code
            for code, in self.db.query(Stock.code).filter(Stock.code.in_(normalized_codes)).all()
        }
        for code in normalized_codes:
            if code in existing_codes:
                continue
            self.db.add(
                Stock(
                    code=code,
                    name=code,
                    market=self._infer_market(code),
                )
            )
        self.db.flush()

    def _sync_candidate_files_for_date(self, trade_date: str, *, write_latest: bool) -> int:
        if str(ROOT / "pipeline") not in sys.path:
            sys.path.insert(0, str(ROOT / "pipeline"))

        from pipeline_io import save_candidates
        from schemas import Candidate as PipelineCandidate, CandidateRun

        pick_dt = date.fromisoformat(trade_date)
        candidate_rows = (
            self.db.query(Candidate)
            .filter(Candidate.pick_date == pick_dt)
            .order_by(Candidate.turnover.is_(None).asc(), Candidate.turnover.desc(), Candidate.id.asc())
            .all()
        )
        run = CandidateRun(
            run_date=utc_now().date().isoformat(),
            pick_date=trade_date,
            candidates=[
                PipelineCandidate(
                    code=row.code,
                    date=trade_date,
                    strategy=row.strategy or "b1",
                    close=float(row.close_price or 0.0),
                    turnover_n=float(row.turnover or 0.0),
                    extra={"kdj_j": float(row.kdj_j)} if row.kdj_j is not None else {},
                )
                for row in candidate_rows
            ],
            meta={
                "config": None,
                "data_dir": None,
                "total": len(candidate_rows),
            },
        )
        save_candidates(
            run,
            candidates_dir=settings.candidates_dir,
            write_dated=True,
            write_latest=write_latest,
        )
        return len(candidate_rows)

    def _sync_review_files_for_date(self, trade_date: str, *, reviewer: str) -> int:
        from app.services.analysis_cache import analysis_cache

        pick_dt = date.fromisoformat(trade_date)
        candidate_map = {
            row.code: row
            for row in self.db.query(Candidate).filter(Candidate.pick_date == pick_dt).all()
        }
        analysis_rows = (
            self.db.query(AnalysisResult)
            .filter(AnalysisResult.pick_date == pick_dt)
            .order_by(AnalysisResult.id.asc())
            .all()
        )

        review_dir = Path(settings.review_dir) / trade_date
        review_dir.mkdir(parents=True, exist_ok=True)

        valid_names = {"suggestion.json"}
        exported_results: list[dict[str, Any]] = []
        for row in analysis_rows:
            code = str(row.code).zfill(6)
            payload = dict(row.details_json or {})
            candidate_row = candidate_map.get(code)
            payload.setdefault("code", code)
            payload.setdefault("reviewer", reviewer)
            payload.setdefault("strategy", getattr(candidate_row, "strategy", None) or "b1")
            payload.setdefault("pick_date", trade_date)
            payload.setdefault("analysis_date", trade_date)
            payload.setdefault("verdict", row.verdict)
            payload.setdefault("signal_type", row.signal_type)
            payload.setdefault("comment", row.comment)
            if payload.get("total_score") is None and row.total_score is not None:
                payload["total_score"] = float(row.total_score)

            analysis_cache.save_analysis_result(code, trade_date, payload)
            valid_names.add(f"{code}.json")
            exported_results.append(payload)

        for path in review_dir.glob("*.json"):
            if path.name not in valid_names:
                path.unlink()

        suggestion_payload = self._build_suggestion_payload(
            trade_date,
            exported_results,
            min_score_threshold=float(settings.min_score_threshold),
        )
        self._atomic_write_json(review_dir / "suggestion.json", suggestion_payload)
        return len(exported_results)

    def _sync_trade_date_artifacts(self, trade_date: str, *, reviewer: str, write_latest: bool) -> dict[str, int]:
        candidate_count = self._sync_candidate_files_for_date(trade_date, write_latest=write_latest)
        analysis_count = self._sync_review_files_for_date(trade_date, reviewer=reviewer)
        return {
            "candidate_count": candidate_count,
            "analysis_count": analysis_count,
        }

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
        candidate_count: Optional[int] = None,
        analysis_count: Optional[int] = None,
        trend_start_count: Optional[int] = None,
        consecutive_candidate_count: Optional[int] = None,
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
        # 如果提供了具体数量，直接设置；否则稍后通过 _refresh_run_counts 计算
        if candidate_count is not None:
            run.candidate_count = candidate_count
        if analysis_count is not None:
            run.analysis_count = analysis_count
        if trend_start_count is not None:
            run.trend_start_count = trend_start_count
        if consecutive_candidate_count is not None:
            run.consecutive_candidate_count = consecutive_candidate_count
        return run

    def _refresh_run_counts(self, run: TomorrowStarRun) -> None:
        pick_dt = run.pick_date
        run.candidate_count = int(
            self.db.query(func.count(Candidate.id)).filter(Candidate.pick_date == pick_dt).scalar() or 0
        )
        run.consecutive_candidate_count = int(
            self.db.query(func.count(Candidate.id))
            .filter(Candidate.pick_date == pick_dt, Candidate.consecutive_days >= 2)
            .scalar()
            or 0
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

    def _refresh_run_counts_for_dates(self, trade_dates: list[str]) -> None:
        normalized_dates = sorted(
            {
                date.fromisoformat(str(trade_date).strip()).isoformat()
                for trade_date in trade_dates
                if str(trade_date).strip()
            }
        )
        if not normalized_dates:
            return

        pick_dates = [date.fromisoformat(item) for item in normalized_dates]
        candidate_counts = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in self.db.query(Candidate.pick_date, func.count(Candidate.id))
            .filter(Candidate.pick_date.in_(pick_dates))
            .group_by(Candidate.pick_date)
            .all()
        }
        analysis_counts = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in self.db.query(AnalysisResult.pick_date, func.count(AnalysisResult.id))
            .filter(AnalysisResult.pick_date.in_(pick_dates))
            .group_by(AnalysisResult.pick_date)
            .all()
        }
        trend_counts = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in self.db.query(AnalysisResult.pick_date, func.count(AnalysisResult.id))
            .filter(
                AnalysisResult.pick_date.in_(pick_dates),
                AnalysisResult.signal_type == "trend_start",
            )
            .group_by(AnalysisResult.pick_date)
            .all()
        }
        consecutive_counts = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in self.db.query(Candidate.pick_date, func.count(Candidate.id))
            .filter(
                Candidate.pick_date.in_(pick_dates),
                Candidate.consecutive_days >= 2,
            )
            .group_by(Candidate.pick_date)
            .all()
        }
        run_map = {
            run.pick_date.isoformat(): run
            for run in self.db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date.in_(pick_dates)).all()
        }

        for trade_date in normalized_dates:
            run = run_map.get(trade_date)
            if run is None:
                continue
            run.candidate_count = candidate_counts.get(trade_date, 0)
            run.analysis_count = analysis_counts.get(trade_date, 0)
            run.trend_start_count = trend_counts.get(trade_date, 0)
            run.consecutive_candidate_count = consecutive_counts.get(trade_date, 0)

        self.db.flush()

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
        self._ensure_stock_rows(codes)

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
        recalculate_consecutive: bool = True,
    ) -> dict[str, int]:
        pick_dt = date.fromisoformat(trade_date)
        codes = sorted({str(event.get("code", "")).zfill(6) for event in events if event.get("code")})
        self._ensure_stock_rows(codes)

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
        self.db.flush()

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
        if recalculate_consecutive:
            from app.services.candidate_service import CandidateService

            CandidateService.recalculate_consecutive_metrics(self.db, commit=False)
            run.consecutive_candidate_count = int(
                self.db.query(func.count(Candidate.id))
                .filter(Candidate.pick_date == pick_dt, Candidate.consecutive_days >= 2)
                .scalar()
                or 0
            )
        else:
            run.consecutive_candidate_count = 0
        self.db.flush()
        return {
            "candidate_count": run.candidate_count,
            "analysis_count": run.analysis_count,
            "trend_start_count": run.trend_start_count,
            "consecutive_candidate_count": run.consecutive_candidate_count,
        }

    def _check_market_regime_before_generation(
        self,
        trade_dates: list[str],
        reviewer: str,
    ) -> dict[str, Any]:
        """在候选生成前检查市场环境。

        Returns:
            包含以下字段的字典：
            - valid_dates: 市场环境良好的日期列表
            - skipped_dates: 市场环境不佳的日期列表
            - regime_info: 每个日期的市场环境信息
        """
        from review_prefilter import Step4Prefilter
        from quant_reviewer import load_config

        review_cfg = load_config()
        prefilter = Step4Prefilter(review_cfg)

        valid_dates = []
        skipped_dates = []
        regime_info: dict[str, dict[str, Any]] = {}

        for trade_date in trade_dates:
            result = prefilter.check_market_regime_only(trade_date)
            regime_info[trade_date] = result

            if result.get("passed", True):
                valid_dates.append(trade_date)
            else:
                skipped_dates.append(trade_date)
                logger.info(
                    "市场环境检查未通过 %s: %s",
                    trade_date,
                    result.get("summary", ""),
                )

        return {
            "valid_dates": valid_dates,
            "skipped_dates": skipped_dates,
            "regime_info": regime_info,
        }

    def _replace_trade_date_with_market_regime_blocked(
        self,
        trade_date: str,
        regime_info: dict[str, Any],
        *,
        reviewer: str,
        source: str,
        window_size: int,
        started_at: datetime,
    ) -> dict[str, int]:
        """当市场环境不佳时，清空候选/分析数据并记录市场环境信息。

        Args:
            trade_date: 交易日期
            regime_info: 市场环境检查结果
            reviewer: 复核者
            source: 来源
            window_size: 窗口大小
            started_at: 开始时间

        Returns:
            包含候选数、分析数等统计信息的字典
        """
        pick_dt = date.fromisoformat(trade_date)

        # 清空该日期的候选数据
        deleted_candidates = (
            self.db.query(Candidate)
            .filter(Candidate.pick_date == pick_dt)
            .delete()
        )

        # 清空该日期的分析数据
        deleted_analysis = (
            self.db.query(AnalysisResult)
            .filter(AnalysisResult.pick_date == pick_dt)
            .delete()
        )

        # 更新运行记录
        run = self._upsert_run(
            trade_date,
            status="success",
            reviewer=reviewer,
            source=source,
            window_size=window_size,
            candidate_count=0,
            analysis_count=0,
            trend_start_count=0,
            consecutive_candidate_count=0,
            started_at=started_at,
            finished_at=utc_now(),
            error_message=None,
        )

        # 在运行记录的 meta_json 中保存市场环境信息
        run.meta_json = {
            **(run.meta_json or {}),
            "market_regime_blocked": True,
            "market_regime_info": regime_info,
        }
        self.db.flush()

        logger.info(
            "市场环境不佳 %s: 清空候选(%d)和分析(%d), 原因: %s",
            trade_date,
            deleted_candidates,
            deleted_analysis,
            regime_info.get("summary", ""),
        )

        return {
            "candidate_count": 0,
            "analysis_count": 0,
            "trend_start_count": 0,
            "consecutive_candidate_count": 0,
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

        # 提前检查市场环境，避免在恶劣环境下进行无意义的计算
        market_regime_check = self._check_market_regime_before_generation(trade_dates, reviewer)
        skipped_dates = market_regime_check["skipped_dates"]
        valid_dates = market_regime_check["valid_dates"]

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

        # 对于市场环境不佳的日期，直接记录为空结果
        for trade_date in skipped_dates:
            regime_info = market_regime_check["regime_info"].get(trade_date, {})
            self._replace_trade_date_with_market_regime_blocked(
                trade_date,
                regime_info,
                reviewer=reviewer,
                source=source,
                window_size=window_size,
                started_at=started_at,
            )

        # 如果没有有效日期，直接返回
        if not valid_dates:
            self.db.commit()
            return {
                "success": True,
                "built_dates": skipped_dates,
                "failed_dates": [],
                "market_regime_skipped": skipped_dates,
            }

        start_date = min(valid_dates)
        end_date = max(valid_dates)
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
        should_recalculate_each_date = len(trade_dates) <= 1
        for trade_date in trade_dates:
            counts = self._replace_trade_date_payload(
                trade_date,
                grouped_events.get(trade_date, []),
                reviewer=reviewer,
                source=source,
                window_size=window_size,
                started_at=started_at,
                recalculate_consecutive=should_recalculate_each_date,
            )
            built_dates.append(trade_date)
            logger.info(
                "tomorrow star backfilled %s candidates=%s analysis=%s trend_start=%s",
                trade_date,
                counts["candidate_count"],
                counts["analysis_count"],
                counts["trend_start_count"],
            )
        if not should_recalculate_each_date and built_dates:
            from app.services.candidate_service import CandidateService

            CandidateService.recalculate_consecutive_metrics(self.db, commit=False)
            self._refresh_run_counts_for_dates(built_dates)
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
        consecutive_counts = {
            row.pick_date.isoformat(): int(row.count or 0)
            for row in self.db.query(
                Candidate.pick_date,
                func.count(Candidate.id).label("count"),
            )
            .filter(
                Candidate.pick_date.in_(pick_dates),
                Candidate.consecutive_days >= 2,
            )
            .group_by(Candidate.pick_date)
            .all()
        }
        tomorrow_star_counts = self._get_tomorrow_star_counts(pick_dates)

        has_active_task = self._has_active_generation_task()
        items: list[dict[str, Any]] = []
        ready_count = missing_count = running_count = failed_count = pending_count = 0
        for pick_date_text in target_dates:
            run = run_map.get(pick_date_text)
            candidate_count = candidate_counts.get(pick_date_text, 0)
            analysis_count = analysis_counts.get(pick_date_text, 0)
            trend_start_count = trend_counts.get(pick_date_text, 0)
            consecutive_candidate_count = consecutive_counts.get(pick_date_text, 0)
            tomorrow_star_count = tomorrow_star_counts.get(pick_date_text, 0)

            # 检查市场环境阻断
            is_market_regime_blocked = False
            market_regime_info = None
            if run and run.meta_json and run.meta_json.get("market_regime_blocked"):
                is_market_regime_blocked = True
                market_regime_info = run.meta_json.get("market_regime_info", {})

            status = self._resolve_display_status(
                run,
                candidate_count=candidate_count,
                analysis_count=analysis_count,
                has_active_task=has_active_task,
            )

            # 市场环境阻断时，状态显示为 success 但候选为0
            if is_market_regime_blocked and status == "success":
                status = "market_regime_blocked"

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
                    "consecutive_candidate_count": consecutive_candidate_count,
                    "tomorrow_star_count": tomorrow_star_count,
                    "status": status,
                    "error_message": run.error_message if run else None,
                    "is_latest": pick_date_text == latest_date,
                    "reviewer": run.reviewer if run else None,
                    "source": run.source if run else None,
                    "started_at": run.started_at.isoformat() if run and run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run and run.finished_at else None,
                    "market_regime_blocked": is_market_regime_blocked,
                    "market_regime_info": market_regime_info,
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

    @staticmethod
    def _extract_prefilter_passed(details_json: Optional[dict[str, Any]]) -> Optional[bool]:
        if not isinstance(details_json, dict):
            return None
        prefilter = details_json.get("prefilter")
        if not isinstance(prefilter, dict):
            return None
        value = prefilter.get("passed")
        return value if isinstance(value, bool) else None

    @staticmethod
    def _extract_tomorrow_star_pass(details_json: Optional[dict[str, Any]]) -> Optional[bool]:
        if not isinstance(details_json, dict):
            return None
        direct = details_json.get("tomorrow_star_pass")
        if isinstance(direct, bool):
            return direct
        rules = details_json.get("rules")
        if isinstance(rules, dict) and isinstance(rules.get("tomorrow_star_pass"), bool):
            return rules["tomorrow_star_pass"]
        details = details_json.get("details")
        if isinstance(details, dict) and isinstance(details.get("tomorrow_star_pass"), bool):
            return details["tomorrow_star_pass"]
        return None

    @classmethod
    def _is_tomorrow_star_analysis(cls, row: AnalysisResult) -> bool:
        explicit = cls._extract_tomorrow_star_pass(row.details_json)
        if explicit is not None:
            return explicit
        prefilter_passed = cls._extract_prefilter_passed(row.details_json)
        if prefilter_passed is None:
            return False
        return bool(
            prefilter_passed
            and row.verdict == "PASS"
            and row.signal_type == "trend_start"
        )

    def _get_tomorrow_star_counts(self, pick_dates: list[date]) -> dict[str, int]:
        if not pick_dates:
            return {}
        counts: dict[str, int] = {}
        rows = (
            self.db.query(AnalysisResult)
            .filter(AnalysisResult.pick_date.in_(pick_dates))
            .all()
        )
        for row in rows:
            if self._is_tomorrow_star_analysis(row):
                key = row.pick_date.isoformat()
                counts[key] = counts.get(key, 0) + 1
        return counts

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

    def rebuild_trade_date(
        self,
        trade_date: str,
        *,
        reviewer: str = DEFAULT_REVIEWER,
        source: str = DEFAULT_SOURCE,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ) -> dict[str, Any]:
        """基于回测结果重建指定交易日的候选/分析/运行统计。

        与旧的 build_for_trade_date 不同，这里不依赖 data/review/<date> 文件是否完整，
        而是直接用回测事件一次性替换 Candidate / AnalysisResult / TomorrowStarRun，
        以保证三者始终一致。
        """
        if not self._try_advisory_lock():
            return {"success": False, "status": "locked", "pick_date": trade_date}

        try:
            rebuild_result = self._build_window_via_backtest(
                [trade_date],
                reviewer=reviewer,
                source=source,
                window_size=window_size,
            )
            self.reconcile_run_rows(window_size, reviewer=reviewer, source=source)
            self._sync_trade_date_artifacts(
                trade_date,
                reviewer=reviewer,
                write_latest=(trade_date == self._get_latest_trade_date()),
            )

            run = (
                self.db.query(TomorrowStarRun)
                .filter(TomorrowStarRun.pick_date == date.fromisoformat(trade_date))
                .first()
            )
            if trade_date in set(rebuild_result.get("failed_dates", [])):
                return {
                    "success": False,
                    "status": "failed",
                    "pick_date": trade_date,
                    "candidate_count": int(getattr(run, "candidate_count", 0) or 0),
                    "analysis_count": int(getattr(run, "analysis_count", 0) or 0),
                    "trend_start_count": int(getattr(run, "trend_start_count", 0) or 0),
                }

            return {
                "success": True,
                "status": "success",
                "pick_date": trade_date,
                "candidate_count": int(getattr(run, "candidate_count", 0) or 0),
                "analysis_count": int(getattr(run, "analysis_count", 0) or 0),
                "trend_start_count": int(getattr(run, "trend_start_count", 0) or 0),
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
            logger.exception("rebuild_trade_date failed: %s", trade_date)
            return {"success": False, "status": "failed", "pick_date": trade_date, "error": str(exc)}
        finally:
            self._unlock_advisory()

    def rebuild_trade_dates(
        self,
        trade_dates: list[str],
        *,
        reviewer: str = DEFAULT_REVIEWER,
        source: str = DEFAULT_SOURCE,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ) -> list[dict[str, Any]]:
        normalized_dates = sorted(
            {
                date.fromisoformat(str(trade_date).strip()).isoformat()
                for trade_date in trade_dates
                if str(trade_date).strip()
            }
        )
        if not normalized_dates:
            return []

        if not self._try_advisory_lock():
            return [
                {"success": False, "status": "locked", "pick_date": trade_date}
                for trade_date in normalized_dates
            ]

        try:
            rebuild_result = self._build_window_via_backtest(
                normalized_dates,
                reviewer=reviewer,
                source=source,
                window_size=window_size,
            )
            self.reconcile_run_rows(window_size, reviewer=reviewer, source=source)

            latest_trade_date = self._get_latest_trade_date()
            pick_dates = [date.fromisoformat(item) for item in normalized_dates]
            run_map = {
                row.pick_date.isoformat(): row
                for row in self.db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date.in_(pick_dates)).all()
            }

            for trade_date in normalized_dates:
                self._sync_trade_date_artifacts(
                    trade_date,
                    reviewer=reviewer,
                    write_latest=(trade_date == latest_trade_date),
                )

            failed_dates = set(rebuild_result.get("failed_dates", []))
            return [
                {
                    "success": trade_date not in failed_dates,
                    "status": "failed" if trade_date in failed_dates else "success",
                    "pick_date": trade_date,
                    "candidate_count": int(getattr(run_map.get(trade_date), "candidate_count", 0) or 0),
                    "analysis_count": int(getattr(run_map.get(trade_date), "analysis_count", 0) or 0),
                    "trend_start_count": int(getattr(run_map.get(trade_date), "trend_start_count", 0) or 0),
                }
                for trade_date in normalized_dates
            ]
        except Exception as exc:
            self.db.rollback()
            failed_results: list[dict[str, Any]] = []
            for trade_date in normalized_dates:
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
                failed_results.append(
                    {
                        "success": False,
                        "status": "failed",
                        "pick_date": trade_date,
                        "error": str(exc),
                        "candidate_count": int(getattr(run, "candidate_count", 0) or 0),
                        "analysis_count": int(getattr(run, "analysis_count", 0) or 0),
                        "trend_start_count": int(getattr(run, "trend_start_count", 0) or 0),
                    }
                )
            self.db.commit()
            logger.exception("rebuild_trade_dates failed: %s", normalized_dates)
            return failed_results
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
        latest_trade_date = self._get_latest_trade_date()
        if latest_trade_date:
            self._sync_trade_date_artifacts(
                latest_trade_date,
                reviewer=reviewer,
                write_latest=True,
            )
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


def get_tomorrow_star_window_service() -> TomorrowStarWindowService:
    """返回一个新的 service 实例。

    不复用全局 Session，避免在 asyncio.to_thread / 后台线程中跨线程使用同一个
    SQLAlchemy Session，导致窗口补齐任务无法稳定执行。
    """
    return TomorrowStarWindowService()


def ensure_tomorrow_star_window(
    window_size: int = TomorrowStarWindowService.DEFAULT_WINDOW_SIZE,
    *,
    reviewer: str = TomorrowStarWindowService.DEFAULT_REVIEWER,
    source: str = TomorrowStarWindowService.DEFAULT_SOURCE,
) -> dict[str, Any]:
    """在线程内创建独立 service，执行 120 日窗口补齐。"""
    with TomorrowStarWindowService() as service:
        return service.ensure_window(window_size=window_size, reviewer=reviewer, source=source)


def maintain_tomorrow_star_for_trade_date(
    trade_date: str,
    *,
    reviewer: str = TomorrowStarWindowService.DEFAULT_REVIEWER,
    source: str = TomorrowStarWindowService.DEFAULT_SOURCE,
    window_size: int = TomorrowStarWindowService.DEFAULT_WINDOW_SIZE,
) -> dict[str, Any]:
    """在线程内为指定交易日构建并裁剪明日之星窗口。"""
    with TomorrowStarWindowService() as service:
        build_result = service.rebuild_trade_date(
            trade_date,
            reviewer=reviewer,
            source=source,
            window_size=window_size,
        )
        prune_result = service.prune_window(window_size)
        return {
            "build": build_result,
            "prune": prune_result,
        }
