"""Persisted active-pool rank factors.

Online diagnosis must not rebuild the full-market liquidity pool. This service
reads precomputed ranks from Redis/PostgreSQL and provides an explicit offline
compute path for rebuild/update jobs.
"""
from __future__ import annotations

from collections import deque
import logging
from datetime import date as date_class, datetime, timedelta
from typing import Any, Deque, Iterable, Optional

import pandas as pd
from sqlalchemy import func

from app.cache import cache
from app.database import SessionLocal
from app.models import StockActivePoolRank, StockDaily
from app.time_utils import utc_now

logger = logging.getLogger(__name__)


class ActivePoolRankService:
    """Read and build daily full-market active-pool rankings."""

    CACHE_PREFIX = "active_pool_rank"
    CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

    @staticmethod
    def _normalize_code(code: str) -> str:
        return str(code or "").strip().zfill(6)

    @staticmethod
    def _normalize_date(value: Any) -> Optional[date_class]:
        if value is None:
            return None
        if isinstance(value, date_class) and not isinstance(value, datetime):
            return value
        try:
            ts = pd.Timestamp(value)
        except Exception:
            return None
        if pd.isna(ts):
            return None
        return ts.date()

    @classmethod
    def _date_key(cls, trade_date: date_class, top_m: int, n_turnover_days: int) -> str:
        return f"{cls.CACHE_PREFIX}:{int(top_m)}:{int(n_turnover_days)}:{trade_date.isoformat()}"

    @staticmethod
    def _rank_row_to_payload(row: StockActivePoolRank) -> dict[str, Any]:
        return {
            "rank": int(row.active_pool_rank),
            "turnover_n": float(row.turnover_n),
            "in_active_pool": bool(row.in_active_pool),
        }

    def invalidate(self, trade_dates: Optional[Iterable[Any]] = None) -> int:
        if trade_dates is None:
            return cache.delete_prefix(f"{self.CACHE_PREFIX}:")

        deleted = 0
        # Parameter combinations are part of the key; delete by broad date suffix.
        # Redis fallback does not support suffix deletes, so clear all active-pool
        # rank cache for correctness after a dated rebuild.
        normalized = [self._normalize_date(item) for item in trade_dates]
        normalized = [item for item in normalized if item is not None]
        if normalized:
            deleted += cache.delete_prefix(f"{self.CACHE_PREFIX}:")
        return deleted

    def _load_date_payload_from_db(
        self,
        trade_date: date_class,
        *,
        top_m: int,
        n_turnover_days: int,
    ) -> Optional[dict[str, dict[str, Any]]]:
        with SessionLocal() as db:
            rows = (
                db.query(StockActivePoolRank)
                .filter(
                    StockActivePoolRank.trade_date == trade_date,
                    StockActivePoolRank.top_m == int(top_m),
                    StockActivePoolRank.n_turnover_days == int(n_turnover_days),
                )
                .all()
            )

        if not rows:
            return None
        return {
            self._normalize_code(row.code): self._rank_row_to_payload(row)
            for row in rows
            if row.code
        }

    def get_date_payload(
        self,
        trade_date: Any,
        *,
        top_m: int = 2000,
        n_turnover_days: int = 43,
    ) -> Optional[dict[str, dict[str, Any]]]:
        normalized_date = self._normalize_date(trade_date)
        if normalized_date is None:
            return None

        key = self._date_key(normalized_date, top_m, n_turnover_days)
        cached = cache.get(key)
        if isinstance(cached, dict):
            return cached

        payload = self._load_date_payload_from_db(
            normalized_date,
            top_m=top_m,
            n_turnover_days=n_turnover_days,
        )
        if payload is not None:
            cache.set(key, payload, ttl=self.CACHE_TTL_SECONDS)
        return payload

    def get_rankings(
        self,
        *,
        start_date: Any,
        end_date: Any,
        target_codes: set[str],
        top_m: int = 2000,
        n_turnover_days: int = 43,
    ) -> Optional[dict[str, dict[pd.Timestamp, int]]]:
        start = self._normalize_date(start_date)
        end = self._normalize_date(end_date)
        if start is None or end is None:
            return None
        codes = {self._normalize_code(code) for code in target_codes if str(code or "").strip()}
        if not codes:
            return {}

        rankings: dict[str, dict[pd.Timestamp, int]] = {code: {} for code in codes}
        with SessionLocal() as db:
            rows = (
                db.query(
                    StockActivePoolRank.code,
                    StockActivePoolRank.trade_date,
                    StockActivePoolRank.active_pool_rank,
                )
                .filter(
                    StockActivePoolRank.trade_date >= start,
                    StockActivePoolRank.trade_date <= end,
                    StockActivePoolRank.top_m == int(top_m),
                    StockActivePoolRank.n_turnover_days == int(n_turnover_days),
                    StockActivePoolRank.code.in_(sorted(codes)),
                )
                .all()
            )

        for row in rows:
            code = self._normalize_code(row.code)
            trade_date = self._normalize_date(row.trade_date)
            if code in rankings and trade_date is not None and row.active_pool_rank is not None:
                rankings[code][pd.Timestamp(trade_date).normalize()] = int(row.active_pool_rank)

        return rankings

    def get_available_dates(
        self,
        *,
        start_date: Any,
        end_date: Any,
        top_m: int = 2000,
        n_turnover_days: int = 43,
    ) -> set[date_class]:
        """Return dates that already have persisted active-pool rank factors."""
        start = self._normalize_date(start_date)
        end = self._normalize_date(end_date)
        if start is None or end is None:
            return set()

        with SessionLocal() as db:
            rows = (
                db.query(StockActivePoolRank.trade_date)
                .filter(
                    StockActivePoolRank.trade_date >= start,
                    StockActivePoolRank.trade_date <= end,
                    StockActivePoolRank.top_m == int(top_m),
                    StockActivePoolRank.n_turnover_days == int(n_turnover_days),
                )
                .group_by(StockActivePoolRank.trade_date)
                .all()
            )
        return {
            day
            for day in (self._normalize_date(row[0]) for row in rows)
            if day is not None
        }

    def get_pool_sets(
        self,
        *,
        start_date: Any,
        end_date: Any,
        top_m: int = 2000,
        n_turnover_days: int = 43,
    ) -> Optional[dict[pd.Timestamp, set[str]]]:
        start = self._normalize_date(start_date)
        end = self._normalize_date(end_date)
        if start is None or end is None:
            return None

        pool_sets: dict[pd.Timestamp, set[str]] = {}
        for trade_date in pd.date_range(start=start, end=end, freq="D"):
            day = trade_date.date()
            payload = self.get_date_payload(day, top_m=top_m, n_turnover_days=n_turnover_days)
            if payload is None:
                continue
            pool_sets[pd.Timestamp(day).normalize()] = {
                code
                for code, row in payload.items()
                if row.get("in_active_pool") is True
            }

        return pool_sets or None

    @staticmethod
    def _flush_rank_rows(
        db,
        *,
        day: Optional[date_class],
        rank_inputs: list[tuple[float, str]],
        top_m: int,
        n_turnover_days: int,
        now: datetime,
    ) -> tuple[int, Optional[str]]:
        if day is None or not rank_inputs:
            return 0, None

        ranked = sorted(rank_inputs, key=lambda item: (-item[0], item[1]))
        mappings = [
            {
                "trade_date": day,
                "code": code,
                "top_m": top_m,
                "n_turnover_days": n_turnover_days,
                "turnover_n": float(turnover_n),
                "active_pool_rank": rank,
                "in_active_pool": rank <= top_m,
                "computed_at": now,
            }
            for rank, (turnover_n, code) in enumerate(ranked, start=1)
        ]
        db.bulk_insert_mappings(StockActivePoolRank, mappings)
        return len(mappings), day.isoformat()

    def compute_for_dates(
        self,
        trade_dates: Iterable[Any],
        *,
        top_m: int = 2000,
        n_turnover_days: int = 43,
        force: bool = False,
    ) -> dict[str, Any]:
        """Compute and persist active-pool ranks for target dates.

        This is intended for rebuild/update jobs. It reads PostgreSQL
        stock_daily only and never touches CSV files.
        """
        normalized_dates = sorted({
            item for item in (self._normalize_date(value) for value in trade_dates)
            if item is not None
        })
        if not normalized_dates:
            return {"success": True, "computed_dates": [], "inserted_count": 0, "skipped": True}

        top_m = int(top_m)
        n_turnover_days = int(n_turnover_days)
        if top_m <= 0 or n_turnover_days <= 0:
            return {"success": False, "error": "top_m 和 n_turnover_days 必须大于 0"}

        with SessionLocal() as db:
            existing_dates = set()
            if not force:
                daily_counts = {
                    row[0]: int(row[1] or 0)
                    for row in (
                        db.query(StockDaily.trade_date, func.count(StockDaily.id))
                        .filter(StockDaily.trade_date.in_(normalized_dates))
                        .group_by(StockDaily.trade_date)
                        .all()
                    )
                    if row and row[0]
                }
                rank_counts = {
                    row[0]: int(row[1] or 0)
                    for row in (
                        db.query(StockActivePoolRank.trade_date, func.count(StockActivePoolRank.id))
                        .filter(
                            StockActivePoolRank.trade_date.in_(normalized_dates),
                            StockActivePoolRank.top_m == top_m,
                            StockActivePoolRank.n_turnover_days == n_turnover_days,
                        )
                        .group_by(StockActivePoolRank.trade_date)
                        .all()
                    )
                    if row and row[0]
                }
                existing_dates = {
                    day
                    for day, daily_count in daily_counts.items()
                    if daily_count > 0 and rank_counts.get(day, 0) >= daily_count
                }

            dates_to_compute = [day for day in normalized_dates if force or day not in existing_dates]
            if not dates_to_compute:
                return {
                    "success": True,
                    "computed_dates": [],
                    "inserted_count": 0,
                    "skipped": True,
                    "existing_dates_count": len(existing_dates),
                }

            start_date = min(dates_to_compute) - timedelta(days=n_turnover_days * 3 + 30)
            end_date = max(dates_to_compute)
            rows = (
                db.query(
                    StockDaily.code,
                    StockDaily.trade_date,
                    StockDaily.open,
                    StockDaily.close,
                    StockDaily.volume,
                )
                .filter(
                    StockDaily.trade_date >= start_date,
                    StockDaily.trade_date <= end_date,
                )
                .order_by(StockDaily.trade_date.asc(), StockDaily.code.asc())
                .yield_per(2000)
            )

            target_date_set = set(dates_to_compute)
            db.query(StockActivePoolRank).filter(
                StockActivePoolRank.trade_date.in_(dates_to_compute),
                StockActivePoolRank.top_m == top_m,
                StockActivePoolRank.n_turnover_days == n_turnover_days,
            ).delete(synchronize_session=False)
            db.flush()

            now = utc_now()
            rolling_windows: dict[str, Deque[float]] = {}
            rolling_sums: dict[str, float] = {}
            saw_rows = False
            current_day: Optional[date_class] = None
            current_rank_inputs: list[tuple[float, str]] = []
            computed_dates: list[str] = []
            inserted_count = 0
            for code, trade_date, open_price, close_price, volume in rows:
                saw_rows = True
                day = self._normalize_date(trade_date)
                if day is None:
                    continue
                if current_day is not None and day != current_day:
                    inserted, computed_day = self._flush_rank_rows(
                        db,
                        day=current_day,
                        rank_inputs=current_rank_inputs,
                        top_m=top_m,
                        n_turnover_days=n_turnover_days,
                        now=now,
                    )
                    inserted_count += inserted
                    if computed_day:
                        computed_dates.append(computed_day)
                    current_rank_inputs = []
                current_day = day

                normalized_code = self._normalize_code(code)
                signed_turnover = float(((open_price or 0.0) + (close_price or 0.0)) / 2 * (volume or 0.0))
                window = rolling_windows.get(normalized_code)
                if window is None:
                    window = deque()
                    rolling_windows[normalized_code] = window
                    rolling_sums[normalized_code] = 0.0
                if len(window) >= n_turnover_days:
                    rolling_sums[normalized_code] -= window.popleft()
                window.append(signed_turnover)
                rolling_sums[normalized_code] += signed_turnover

                if day in target_date_set:
                    current_rank_inputs.append((rolling_sums[normalized_code], normalized_code))

            if not saw_rows:
                return {"success": False, "error": "stock_daily 无可用数据"}

            inserted, computed_day = self._flush_rank_rows(
                db,
                day=current_day,
                rank_inputs=current_rank_inputs,
                top_m=top_m,
                n_turnover_days=n_turnover_days,
                now=now,
            )
            inserted_count += inserted
            if computed_day:
                computed_dates.append(computed_day)

            if not computed_dates:
                return {"success": False, "error": "目标交易日无 stock_daily 数据"}
            db.commit()

        self.invalidate(dates_to_compute)
        try:
            from app.services.analysis_service import analysis_service

            analysis_service.clear_active_pool_factor_cache()
        except Exception:
            logger.debug("Analysis active-pool memory cache clear skipped", exc_info=True)

        # Warm Redis for the computed dates.
        for day in dates_to_compute:
            self.get_date_payload(day, top_m=top_m, n_turnover_days=n_turnover_days)

        return {
            "success": True,
            "computed_dates": sorted(set(computed_dates), reverse=True),
            "computed_dates_count": len(set(computed_dates)),
            "inserted_count": inserted_count,
            "top_m": top_m,
            "n_turnover_days": n_turnover_days,
            "source": "stock_daily",
        }


active_pool_rank_service = ActivePoolRankService()
