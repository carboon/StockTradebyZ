"""Diagnosis history Redis cache and prewarm helpers."""
from __future__ import annotations

import logging
from datetime import date as date_class
from typing import Any, Optional

from sqlalchemy import and_, func

from app.cache import cache
from app.database import SessionLocal
from app.models import (
    AnalysisResult,
    Candidate,
    CurrentHotCandidate,
    DailyB1Check,
    DailyB1CheckDetail,
    Stock,
)
from app.services.analysis_service import analysis_service

logger = logging.getLogger(__name__)


class DiagnosisHistoryCacheService:
    """Cache full 120-day diagnosis history to avoid recomputing on page reads."""

    DEFAULT_DAYS = 120
    TTL_SECONDS = 24 * 60 * 60
    KEY_PREFIX = "diagnosis:history"

    @classmethod
    def _key(cls, code: str, days: int) -> str:
        return f"{cls.KEY_PREFIX}:{str(code).zfill(6)}:{int(days)}"

    @classmethod
    def invalidate(cls, code: Optional[str] = None) -> int:
        if code:
            cache.delete(cls._key(code, cls.DEFAULT_DAYS))
            return 1
        return cache.delete_prefix(f"{cls.KEY_PREFIX}:")

    @classmethod
    def get_payload(cls, code: str, days: int = DEFAULT_DAYS) -> Optional[dict[str, Any]]:
        payload = cache.get(cls._key(code, days))
        if not isinstance(payload, dict):
            return None
        history = payload.get("history")
        if not isinstance(history, list):
            return None
        return payload

    @classmethod
    def set_payload(cls, code: str, payload: dict[str, Any], days: int = DEFAULT_DAYS) -> dict[str, Any]:
        cache.set(cls._key(code, days), payload, ttl=cls.TTL_SECONDS)
        return payload

    @classmethod
    def _date_key(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        text = str(value)
        return text[:10] if text else None

    @classmethod
    def _load_stock_name(cls, code: str) -> Optional[str]:
        with SessionLocal() as db:
            return db.query(Stock.name).filter(Stock.code == code).scalar()

    @classmethod
    def _build_payload_from_pages(cls, code: str, days: int = DEFAULT_DAYS) -> dict[str, Any]:
        code = code.zfill(6)
        page_size = 50
        page = 1
        total = 0
        history: list[dict[str, Any]] = []
        seen_dates: set[str] = set()

        while True:
            rows, page_total = analysis_service.get_stock_history_checks(
                code,
                days=days,
                page=page,
                page_size=page_size,
            )
            total = max(int(total or 0), int(page_total or 0))
            for row in rows or []:
                row_dict = dict(row)
                check_date = cls._date_key(row_dict.get("check_date"))
                if check_date and check_date not in seen_dates:
                    seen_dates.add(check_date)
                    history.append(row_dict)
            if page * page_size >= max(total, len(history), 1):
                break
            page += 1
            if page > 10:
                break

        history.sort(key=lambda item: str(item.get("check_date") or ""), reverse=True)
        trend_start_dates = [
            str(item.get("check_date"))[:10]
            for item in history
            if item.get("signal_type") == "trend_start" and item.get("check_date")
        ]
        tomorrow_star_dates = [
            str(item.get("check_date"))[:10]
            for item in history
            if item.get("tomorrow_star_pass") is True and item.get("check_date")
        ]
        return {
            "code": code,
            "name": cls._load_stock_name(code),
            "history": history,
            "total": total or len(history),
            "generated_count": len(history),
            "days": days,
            "trend_start_dates": trend_start_dates,
            "tomorrow_star_dates": tomorrow_star_dates,
        }

    @classmethod
    def ensure_cached(
        cls,
        code: str,
        days: int = DEFAULT_DAYS,
        *,
        force: bool = False,
        generate_if_missing: bool = True,
    ) -> dict[str, Any]:
        code = code.zfill(6)
        days = max(1, min(int(days), analysis_service.HISTORY_WINDOW_DAYS))
        if not force:
            cached = cls.get_payload(code, days)
            if cached is not None:
                return cached

        payload = cls._build_payload_from_pages(code, days)
        generated_count = int(payload.get("generated_count") or len(payload.get("history") or []))
        expected_count = min(days, int(payload.get("total") or days))
        if generate_if_missing and (force or generated_count < expected_count):
            result = analysis_service.generate_stock_history_checks(code, days=days, clean=True)
            if not result.get("success"):
                logger.warning("诊断历史缓存补算失败: code=%s error=%s", code, result.get("error"))
            payload = cls._build_payload_from_pages(code, days)

        return cls.set_payload(code, payload, days)

    @classmethod
    def get_page(
        cls,
        code: str,
        *,
        days: int = DEFAULT_DAYS,
        page: int = 1,
        page_size: int = 10,
        force: bool = False,
        generate_if_missing: bool = True,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), days, 50))
        payload = cls.ensure_cached(
            code,
            days=days,
            force=force,
            generate_if_missing=generate_if_missing,
        )
        history = list(payload.get("history") or [])
        start = (page - 1) * page_size
        return {
            **payload,
            "history": history[start:start + page_size],
            "total": int(payload.get("total") or len(history)),
            "page": page,
            "page_size": page_size,
        }

    @classmethod
    def collect_prewarm_codes(cls, *, tomorrow_star_limit: int = 5) -> list[str]:
        codes: set[str] = set()
        with SessionLocal() as db:
            latest_pick_date = db.query(func.max(Candidate.pick_date)).scalar()
            if latest_pick_date:
                rows = (
                    db.query(
                        Candidate.code,
                        AnalysisResult.signal_type,
                        AnalysisResult.total_score,
                        DailyB1CheckDetail.rules_json,
                    )
                    .outerjoin(
                        AnalysisResult,
                        and_(
                            AnalysisResult.pick_date == Candidate.pick_date,
                            AnalysisResult.code == Candidate.code,
                            AnalysisResult.reviewer == "quant",
                        ),
                    )
                    .outerjoin(
                        DailyB1CheckDetail,
                        and_(
                            DailyB1CheckDetail.code == Candidate.code,
                            DailyB1CheckDetail.check_date == Candidate.pick_date,
                        ),
                    )
                    .filter(Candidate.pick_date == latest_pick_date)
                    .all()
                )
                sorted_rows = sorted(
                    rows,
                    key=lambda row: (
                        0 if isinstance(row.rules_json, dict) and row.rules_json.get("tomorrow_star_pass") is True else 1,
                        0 if row.signal_type == "trend_start" else 1,
                        -(float(row.total_score) if row.total_score is not None else -9999.0),
                        str(row.code),
                    ),
                )
                codes.update(str(row.code).zfill(6) for row in sorted_rows[:tomorrow_star_limit])

            current_hot_codes = [
                str(code).zfill(6)
                for code, in db.query(CurrentHotCandidate.code).distinct().all()
                if str(code or "").strip()
            ]
            codes.update(current_hot_codes)

        try:
            from app.services.current_hot_service import CurrentHotService

            with SessionLocal() as db:
                codes.update(entry.code for entry in CurrentHotService(db).get_pool_entries())
        except Exception as exc:
            logger.warning("读取当前热盘配置股票失败: %s", exc)

        return sorted(code for code in codes if code)

    @classmethod
    def prewarm(
        cls,
        *,
        codes: Optional[list[str]] = None,
        days: int = DEFAULT_DAYS,
        limit: int = 0,
        force: bool = False,
        generate_if_missing: bool = True,
    ) -> dict[str, Any]:
        target_codes = [str(code).zfill(6) for code in (codes or cls.collect_prewarm_codes()) if str(code or "").strip()]
        if limit > 0:
            target_codes = target_codes[:limit]

        success_codes: list[str] = []
        failed: list[dict[str, str]] = []
        total = len(target_codes)
        for index, code in enumerate(target_codes, start=1):
            try:
                logger.info(
                    "诊断历史缓存预热 %s/%s: code=%s force=%s generate_if_missing=%s",
                    index,
                    total,
                    code,
                    force,
                    generate_if_missing,
                )
                cls.ensure_cached(
                    code,
                    days=days,
                    force=force,
                    generate_if_missing=generate_if_missing,
                )
                success_codes.append(code)
            except Exception as exc:
                failed.append({"code": code, "error": str(exc)})
                logger.warning("诊断历史缓存预热失败: code=%s error=%s", code, exc)

        return {
            "success": not failed,
            "requested_count": len(target_codes),
            "success_count": len(success_codes),
            "failed": failed,
            "success_codes_sample": success_codes[:20],
        }


diagnosis_history_cache_service = DiagnosisHistoryCacheService
