"""Tomorrow star aggregate cache helpers."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.cache import cache
from app.models import AnalysisResult, Candidate, Task

logger = logging.getLogger(__name__)

AGGREGATE_CACHE_PREFIX = "tomorrow_star:aggregate:v1"
AGGREGATE_CACHE_TTL = 120


class TomorrowStarAggregateCache:
    """Redis/memory cache for the tomorrow-star aggregate endpoint."""

    def __init__(self, db: Session):
        self.db = db

    def get(self, *, candidate_limit: int) -> dict[str, Any] | None:
        key = self.build_key(candidate_limit=candidate_limit)
        cached = cache.get(key)
        if not isinstance(cached, dict):
            return None
        cached["cache_hit"] = True
        return cached

    def set(self, payload: dict[str, Any], *, candidate_limit: int) -> None:
        key = self.build_key(candidate_limit=candidate_limit)
        cache.set(key, payload, ttl=AGGREGATE_CACHE_TTL)

    def build_key(self, *, candidate_limit: int) -> str:
        latest_candidate_date = self.db.query(func.max(Candidate.pick_date)).scalar()
        latest_result_date = self.db.query(func.max(AnalysisResult.pick_date)).scalar()
        latest_candidate_count = self._count_for_date(Candidate, "pick_date", latest_candidate_date)
        latest_result_count = self._count_for_date(AnalysisResult, "pick_date", latest_result_date)
        running_task = (
            self.db.query(Task)
            .filter(
                Task.task_type.in_(["tomorrow_star", "full_update", "incremental_update", "recent_120_rebuild"]),
                Task.status.in_(["pending", "running"]),
            )
            .order_by(Task.created_at.desc(), Task.id.desc())
            .first()
        )
        version = "|".join([
            str(candidate_limit),
            self._date_text(latest_candidate_date),
            str(latest_candidate_count),
            self._date_text(latest_result_date),
            str(latest_result_count),
            str(running_task.id if running_task else ""),
            str(running_task.status if running_task else ""),
        ])
        return f"{AGGREGATE_CACHE_PREFIX}:{version}"

    def _count_for_date(self, model: Any, column_name: str, value: Any) -> int:
        if value is None:
            return 0
        column = getattr(model, column_name)
        return int(self.db.query(model).filter(column == value).count())

    @staticmethod
    def _date_text(value: Any) -> str:
        if isinstance(value, datetime):
            return value.date().isoformat()
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value or "")

    @staticmethod
    def invalidate_cache() -> None:
        try:
            cache.delete_prefix(AGGREGATE_CACHE_PREFIX)
        except Exception:
            logger.warning("tomorrow-star aggregate cache invalidation failed", exc_info=True)
