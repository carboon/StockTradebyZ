"""
Sector analysis service.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    SectorAnalysisCandidate,
    SectorAnalysisResult,
    SectorAnalysisRun,
    Stock,
    StockActivePoolRank,
)
from app.services.current_hot_service import CurrentHotPoolEntry, CurrentHotService
from app.services.sector_analysis_config import (
    resolve_sector_analysis_catalog,
    resolve_sector_stock_pool,
)
from app.time_utils import utc_now


logger = logging.getLogger(__name__)


@dataclass
class SectorPoolEntry:
    sector_key: str
    sector_name: str
    code: str
    name: str
    board_group: str


class SectorAnalysisService:
    """板块分析独立更新与查询服务。"""

    DEFAULT_REVIEWER = "quant"
    DEFAULT_SOURCE = "sector_analysis"
    DEFAULT_WINDOW_SIZE = 120

    def __init__(self, db: Session):
        self.db = db
        self.current_hot_service = CurrentHotService(db)

    def _load_catalog(self) -> dict[str, Any]:
        raw_value = self.current_hot_service._load_text_config(CurrentHotService.SECTOR_ANALYSIS_CATALOG_KEY)
        return resolve_sector_analysis_catalog(raw_value)

    def _load_pool(self) -> dict[str, list[dict[str, str]]]:
        return resolve_sector_stock_pool(
            self.current_hot_service._load_text_config(CurrentHotService.SECTOR_ANALYSIS_POOL_KEY),
            self.current_hot_service._load_text_config(CurrentHotService.CONFIG_KEY),
        )

    def _build_sector_entry_map(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, list[SectorPoolEntry]], dict[str, list[str]], list[CurrentHotPoolEntry]]:
        catalog = self._load_catalog()
        pool = self._load_pool()
        sectors = list(catalog.get("sectors") or [])
        entries_by_sector: dict[str, list[SectorPoolEntry]] = {}
        code_to_sector_names: dict[str, list[str]] = defaultdict(list)
        code_to_name: dict[str, str] = {}

        for sector in sectors:
            sector_key = str(sector.get("key") or "").strip()
            sector_name = str(sector.get("name") or "").strip()
            if not sector_key or not sector_name:
                continue

            bucket_entries: list[SectorPoolEntry] = []
            seen_codes: set[str] = set()
            for item in pool.get(sector_key, []):
                code = str(item.get("code") or "").zfill(6)
                if not code or code == "000000" or code in seen_codes:
                    continue
                seen_codes.add(code)
                stock_name = str(item.get("name") or code).strip() or code
                bucket_entries.append(
                    SectorPoolEntry(
                        sector_key=sector_key,
                        sector_name=sector_name,
                        code=code,
                        name=stock_name,
                        board_group=self.current_hot_service.get_board_group(code),
                    )
                )
                if sector_name not in code_to_sector_names[code]:
                    code_to_sector_names[code].append(sector_name)
                code_to_name.setdefault(code, stock_name)
            entries_by_sector[sector_key] = bucket_entries

        unique_entries = [
            CurrentHotPoolEntry(
                code=code,
                name=code_to_name.get(code, code),
                primary_sector=sector_names[0],
                sector_names=list(sector_names),
                board_group=self.current_hot_service.get_board_group(code),
            )
            for code, sector_names in sorted(code_to_sector_names.items())
        ]
        return sectors, entries_by_sector, {code: list(names) for code, names in code_to_sector_names.items()}, unique_entries

    def _get_or_create_run(
        self,
        pick_date: date,
        sector_key: str,
        *,
        reviewer: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> SectorAnalysisRun:
        run = (
            self.db.query(SectorAnalysisRun)
            .filter(
                SectorAnalysisRun.pick_date == pick_date,
                SectorAnalysisRun.sector_key == sector_key,
            )
            .first()
        )
        if run is None:
            run = SectorAnalysisRun(pick_date=pick_date, sector_key=sector_key)
            self.db.add(run)
        run.reviewer = reviewer
        run.source = self.DEFAULT_SOURCE
        run.status = status
        run.error_message = error_message
        return run

    def get_recent_pick_dates(self, window_size: int = DEFAULT_WINDOW_SIZE) -> list[date]:
        rows = (
            self.db.query(SectorAnalysisRun.pick_date)
            .filter(SectorAnalysisRun.status == "success")
            .distinct()
            .order_by(SectorAnalysisRun.pick_date.desc())
            .limit(window_size)
            .all()
        )
        dates = [pick_date for pick_date, in rows if pick_date]
        if dates:
            return dates
        rows = (
            self.db.query(SectorAnalysisCandidate.pick_date)
            .distinct()
            .order_by(SectorAnalysisCandidate.pick_date.desc())
            .limit(window_size)
            .all()
        )
        return [pick_date for pick_date, in rows if pick_date]

    def get_latest_pick_date(self) -> Optional[date]:
        return (
            self.db.query(SectorAnalysisRun.pick_date)
            .filter(SectorAnalysisRun.status == "success")
            .order_by(SectorAnalysisRun.pick_date.desc())
            .limit(1)
            .scalar()
        )

    def generate_for_trade_date(
        self,
        trade_date: Optional[str | date] = None,
        reviewer: str = DEFAULT_REVIEWER,
        *,
        backfill_missing_history: bool = True,
    ) -> dict[str, Any]:
        target_trade_date = self.current_hot_service._normalize_trade_date(trade_date) or self.current_hot_service.get_latest_trade_date()
        if target_trade_date is None:
            return {
                "trade_date": None,
                "status": "missing_trade_date",
                "message": "未找到可用交易日",
                "generated_count": 0,
                "skipped_count": 0,
            }

        sectors, entries_by_sector, code_to_sector_names, unique_entries = self._build_sector_entry_map()
        active_sectors = [sector for sector in sectors if str(sector.get("key") or "").strip()]
        if not active_sectors or not unique_entries:
            return {
                "trade_date": target_trade_date,
                "status": "empty_pool",
                "message": "板块分析股票池为空",
                "generated_count": 0,
                "skipped_count": 0,
            }

        started_at = utc_now()
        for sector in active_sectors:
            sector_key = str(sector.get("key") or "").strip()
            run = self._get_or_create_run(target_trade_date, sector_key, reviewer=reviewer, status="running")
            run.started_at = started_at
            run.finished_at = None
        self.db.commit()

        generated_count = 0
        skipped_count = 0
        per_sector_stats: dict[str, dict[str, int]] = defaultdict(lambda: {
            "candidate_count": 0,
            "analysis_count": 0,
            "trend_start_count": 0,
            "b1_count": 0,
            "generated_count": 0,
            "skipped_count": 0,
        })

        try:
            self.current_hot_service._ensure_stocks_exist(unique_entries)
            unique_entries = self.current_hot_service._enrich_pool_entries_with_stock_industry(unique_entries)
            self.current_hot_service._ensure_history_window(
                unique_entries,
                target_trade_date,
                backfill_missing_history=backfill_missing_history,
            )

            self.db.query(SectorAnalysisCandidate).filter(
                SectorAnalysisCandidate.pick_date == target_trade_date
            ).delete(synchronize_session=False)
            self.db.query(SectorAnalysisResult).filter(
                SectorAnalysisResult.pick_date == target_trade_date
            ).delete(synchronize_session=False)
            self.db.query(SectorAnalysisRun).filter(
                SectorAnalysisRun.pick_date == target_trade_date
            ).delete(synchronize_session=False)
            self.db.flush()

            snapshot_by_code: dict[str, dict[str, Any]] = {}
            for entry in unique_entries:
                snapshot_by_code[entry.code] = self.current_hot_service.build_trade_snapshot(entry.code, target_trade_date)

            candidate_rows: list[SectorAnalysisCandidate] = []
            analysis_rows: list[SectorAnalysisResult] = []
            for sector in active_sectors:
                sector_key = str(sector.get("key") or "").strip()
                for entry in entries_by_sector.get(sector_key, []):
                    payload = snapshot_by_code.get(entry.code) or {}
                    sector_stats = per_sector_stats[sector_key]
                    sector_stats["candidate_count"] += 1
                    sector_stats["analysis_count"] += 1
                    if payload.get("signal_type") == "trend_start":
                        sector_stats["trend_start_count"] += 1
                    if payload.get("b1_passed") is True:
                        sector_stats["b1_count"] += 1

                    if payload.get("close_price") is None:
                        skipped_count += 1
                        sector_stats["skipped_count"] += 1
                    else:
                        generated_count += 1
                        sector_stats["generated_count"] += 1

                    candidate_rows.append(
                        SectorAnalysisCandidate(
                            pick_date=target_trade_date,
                            sector_key=sector_key,
                            code=entry.code,
                            sector_names_json=code_to_sector_names.get(entry.code, [entry.sector_name]),
                            board_group=entry.board_group,
                            open_price=payload.get("open_price"),
                            close_price=payload.get("close_price"),
                            change_pct=payload.get("change_pct"),
                            turnover=payload.get("turnover"),
                            turnover_rate=payload.get("turnover_rate"),
                            volume_ratio=payload.get("volume_ratio"),
                            b1_passed=payload.get("b1_passed"),
                            kdj_j=payload.get("kdj_j"),
                        )
                    )
                    analysis_rows.append(
                        SectorAnalysisResult(
                            pick_date=target_trade_date,
                            sector_key=sector_key,
                            code=entry.code,
                            reviewer=reviewer,
                            b1_passed=payload.get("b1_passed"),
                            verdict=payload.get("verdict"),
                            total_score=payload.get("score"),
                            signal_type=payload.get("signal_type"),
                            comment=payload.get("comment"),
                            turnover_rate=payload.get("turnover_rate"),
                            volume_ratio=payload.get("volume_ratio"),
                            details_json=payload.get("details_json"),
                        )
                    )

            if candidate_rows:
                self.db.add_all(candidate_rows)
            if analysis_rows:
                self.db.add_all(analysis_rows)
            self.db.flush()

            finished_at = utc_now()
            for sector in active_sectors:
                sector_key = str(sector.get("key") or "").strip()
                sector_stats = per_sector_stats[sector_key]
                run = self._get_or_create_run(target_trade_date, sector_key, reviewer=reviewer, status="success")
                run.started_at = started_at
                run.finished_at = finished_at
                run.error_message = None
                run.candidate_count = int(sector_stats["candidate_count"])
                run.analysis_count = int(sector_stats["analysis_count"])
                run.trend_start_count = int(sector_stats["trend_start_count"])
                run.b1_count = int(sector_stats["b1_count"])

            self.db.commit()
            return {
                "trade_date": target_trade_date,
                "status": "ok",
                "message": None,
                "generated_count": generated_count,
                "skipped_count": skipped_count,
                "sector_count": len(active_sectors),
                "sectors": [
                    {
                        "sector_key": str(sector.get("key") or ""),
                        **per_sector_stats[str(sector.get("key") or "")],
                    }
                    for sector in active_sectors
                ],
            }
        except Exception as exc:
            self.db.rollback()
            finished_at = utc_now()
            for sector in active_sectors:
                sector_key = str(sector.get("key") or "").strip()
                run = self._get_or_create_run(
                    target_trade_date,
                    sector_key,
                    reviewer=reviewer,
                    status="failed",
                    error_message=str(exc),
                )
                run.started_at = started_at
                run.finished_at = finished_at
            self.db.commit()
            return {
                "trade_date": target_trade_date,
                "status": "failed",
                "message": str(exc),
                "generated_count": generated_count,
                "skipped_count": skipped_count,
                "sector_count": len(active_sectors),
            }

    def get_sector_analysis(self, window_size: int = DEFAULT_WINDOW_SIZE, top_n: int = 5) -> dict[str, Any]:
        catalog = self._load_catalog()
        sector_pool = self._load_pool()
        sectors = list(catalog.get("sectors") or [])
        target_dates = self.get_recent_pick_dates(window_size)
        chronological_dates = list(reversed(target_dates))
        latest_date = target_dates[0] if target_dates else None
        previous_date = target_dates[1] if len(target_dates) > 1 else None

        pool_by_sector = {
            str(sector.get("key") or ""): list(sector_pool.get(str(sector.get("key") or ""), []))
            for sector in sectors
            if str(sector.get("key") or "").strip()
        }
        date_sector_rows: dict[str, dict[str, list[dict[str, Any]]]] = {
            trade_date.isoformat(): {str(sector.get("key") or ""): [] for sector in sectors}
            for trade_date in target_dates
        }

        if target_dates:
            active_rank_sq = (
                self.db.query(
                    StockActivePoolRank.trade_date.label("trade_date"),
                    StockActivePoolRank.code.label("code"),
                    func.min(StockActivePoolRank.active_pool_rank).label("active_pool_rank"),
                )
                .filter(StockActivePoolRank.trade_date.in_(target_dates))
                .group_by(StockActivePoolRank.trade_date, StockActivePoolRank.code)
                .subquery()
            )
            rows = (
                self.db.query(
                    SectorAnalysisCandidate,
                    SectorAnalysisResult,
                    Stock.name,
                    active_rank_sq.c.active_pool_rank,
                )
                .outerjoin(
                    SectorAnalysisResult,
                    (SectorAnalysisResult.pick_date == SectorAnalysisCandidate.pick_date)
                    & (SectorAnalysisResult.sector_key == SectorAnalysisCandidate.sector_key)
                    & (SectorAnalysisResult.code == SectorAnalysisCandidate.code)
                    & (SectorAnalysisResult.reviewer == self.DEFAULT_REVIEWER),
                )
                .outerjoin(Stock, SectorAnalysisCandidate.code == Stock.code)
                .outerjoin(
                    active_rank_sq,
                    (active_rank_sq.c.trade_date == SectorAnalysisCandidate.pick_date)
                    & (active_rank_sq.c.code == SectorAnalysisCandidate.code),
                )
                .filter(SectorAnalysisCandidate.pick_date.in_(target_dates))
                .all()
            )

            for candidate, result, stock_name, active_pool_rank in rows:
                pick_date_text = candidate.pick_date.isoformat()
                if pick_date_text not in date_sector_rows:
                    continue
                if candidate.sector_key not in date_sector_rows[pick_date_text]:
                    continue
                details_json = result.details_json if result and isinstance(result.details_json, dict) else {}
                date_sector_rows[pick_date_text][candidate.sector_key].append(
                    {
                        "code": candidate.code,
                        "name": stock_name,
                        "change_pct": candidate.change_pct,
                        "total_score": result.total_score if result else None,
                        "signal_type": result.signal_type if result else None,
                        "verdict": result.verdict if result else None,
                        "b1_passed": candidate.b1_passed if candidate.b1_passed is not None else (result.b1_passed if result else None),
                        "active_pool_rank": int(active_pool_rank) if active_pool_rank is not None else None,
                        "negative_flags": self.current_hot_service._normalize_pullback_negative_flags(details_json.get("pullback_negative_flags")),
                    }
                )

        ranked_by_date: dict[str, list[dict[str, Any]]] = {}
        history_by_sector: dict[str, list[dict[str, Any]]] = {
            str(sector.get("key") or ""): []
            for sector in sectors
            if str(sector.get("key") or "").strip()
        }

        for trade_date in chronological_dates:
            trade_date_text = trade_date.isoformat()
            metrics_for_date: list[dict[str, Any]] = []
            for sector in sectors:
                sector_key = str(sector.get("key") or "").strip()
                if not sector_key:
                    continue
                metrics = self.current_hot_service._build_sector_metrics(
                    sector=sector,
                    rows=date_sector_rows.get(trade_date_text, {}).get(sector_key, []),
                    pool_count=len(pool_by_sector.get(sector_key, [])),
                )
                metrics["_sector_order"] = int(sector.get("order") or 9999)
                metrics_for_date.append(metrics)

            metrics_for_date.sort(
                key=lambda item: (
                    -float(item.get("strength_score") or 0.0),
                    -int(item.get("trend_start_count") or 0),
                    -int(item.get("pass_count") or 0),
                    -float(item.get("avg_score") or -9999.0),
                    int(item.get("_sector_order") or 9999),
                    str(item.get("sector_key") or ""),
                )
            )
            for index, item in enumerate(metrics_for_date, start=1):
                item["rank"] = index
                history_by_sector[str(item.get("sector_key") or "")].append(
                    {
                        "date": trade_date_text,
                        "rank": index,
                        "strength_score": item.get("strength_score"),
                        "tracked_count": item.get("tracked_count"),
                        "b1_count": item.get("b1_count"),
                        "trend_start_count": item.get("trend_start_count"),
                        "pass_count": item.get("pass_count"),
                        "high_score_count": item.get("high_score_count"),
                        "negative_flag_count": item.get("negative_flag_count"),
                        "avg_score": item.get("avg_score"),
                        "avg_change_pct": item.get("avg_change_pct"),
                    }
                )
                item.pop("_sector_order", None)
            ranked_by_date[trade_date_text] = metrics_for_date

        latest_ranked = ranked_by_date.get(latest_date.isoformat(), []) if latest_date else []
        previous_rank_map = {
            str(item.get("sector_key") or ""): item
            for item in (ranked_by_date.get(previous_date.isoformat(), []) if previous_date else [])
        }

        latest_sectors: list[dict[str, Any]] = []
        if latest_ranked:
            for item in latest_ranked:
                previous_item = previous_rank_map.get(str(item.get("sector_key") or ""))
                latest_sectors.append(
                    {
                        **item,
                        "previous_rank": int(previous_item["rank"]) if previous_item and isinstance(previous_item.get("rank"), int) else None,
                        "rank_change": (
                            int(previous_item["rank"]) - int(item["rank"])
                            if previous_item and isinstance(previous_item.get("rank"), int) and isinstance(item.get("rank"), int)
                            else None
                        ),
                    }
                )
        else:
            for sector in sectors:
                sector_key = str(sector.get("key") or "").strip()
                if not sector_key:
                    continue
                latest_sectors.append(
                    {
                        **self.current_hot_service._build_sector_metrics(
                            sector=sector,
                            rows=[],
                            pool_count=len(pool_by_sector.get(sector_key, [])),
                        ),
                        "rank": None,
                        "previous_rank": None,
                        "rank_change": None,
                    }
                )

        top_count = max(1, min(int(top_n or 5), len(latest_sectors) or 1))
        top_sector_keys = [
            str(item.get("sector_key") or "")
            for item in latest_sectors[:top_count]
            if str(item.get("sector_key") or "").strip()
        ]
        return {
            "latest_date": latest_date,
            "previous_date": previous_date,
            "window_size": int(window_size),
            "dates": [trade_date.isoformat() for trade_date in chronological_dates],
            "top_sector_keys": top_sector_keys,
            "sectors": latest_sectors,
            "history": [
                {
                    "sector_key": str(sector.get("key") or ""),
                    "sector_name": str(sector.get("name") or ""),
                    "points": history_by_sector.get(str(sector.get("key") or ""), []),
                }
                for sector in sectors
                if str(sector.get("key") or "").strip()
            ],
        }

    def get_sector_date_rows(
        self,
        *,
        sector_key: str,
        pick_date: Optional[str] = None,
        reviewer: str = DEFAULT_REVIEWER,
    ) -> dict[str, Any]:
        normalized_sector_key = str(sector_key or "").strip()
        if not normalized_sector_key:
            return {"sector_key": "", "pick_date": None, "rows": [], "total": 0}

        target_date = self.current_hot_service._normalize_trade_date(pick_date) or self.get_latest_pick_date()
        if target_date is None:
            return {"sector_key": normalized_sector_key, "pick_date": None, "rows": [], "total": 0}

        active_rank_sq = (
            self.db.query(
                StockActivePoolRank.trade_date.label("trade_date"),
                StockActivePoolRank.code.label("code"),
                func.min(StockActivePoolRank.active_pool_rank).label("active_pool_rank"),
            )
            .filter(StockActivePoolRank.trade_date == target_date)
            .group_by(StockActivePoolRank.trade_date, StockActivePoolRank.code)
            .subquery()
        )
        rows = (
            self.db.query(
                SectorAnalysisCandidate,
                SectorAnalysisResult,
                Stock.name,
                Stock.industry,
                active_rank_sq.c.active_pool_rank,
            )
            .outerjoin(
                SectorAnalysisResult,
                (SectorAnalysisResult.pick_date == SectorAnalysisCandidate.pick_date)
                & (SectorAnalysisResult.sector_key == SectorAnalysisCandidate.sector_key)
                & (SectorAnalysisResult.code == SectorAnalysisCandidate.code)
                & (SectorAnalysisResult.reviewer == reviewer),
            )
            .outerjoin(Stock, SectorAnalysisCandidate.code == Stock.code)
            .outerjoin(
                active_rank_sq,
                (active_rank_sq.c.trade_date == SectorAnalysisCandidate.pick_date)
                & (active_rank_sq.c.code == SectorAnalysisCandidate.code),
            )
            .filter(
                SectorAnalysisCandidate.pick_date == target_date,
                SectorAnalysisCandidate.sector_key == normalized_sector_key,
            )
            .all()
        )

        items: list[dict[str, Any]] = []
        for candidate, result, stock_name, stock_industry, active_pool_rank in rows:
            details_json = result.details_json if result and isinstance(result.details_json, dict) else {}
            prefilter_passed, prefilter_summary, prefilter_blocked_by = self.current_hot_service._extract_prefilter_fields(details_json)
            items.append(
                {
                    "id": candidate.id,
                    "pick_date": target_date,
                    "sector_key": normalized_sector_key,
                    "code": candidate.code,
                    "name": stock_name,
                    "sector_names": self.current_hot_service._resolve_sector_names(candidate.sector_names_json, industry=stock_industry),
                    "board_group": candidate.board_group,
                    "open_price": candidate.open_price,
                    "close_price": candidate.close_price,
                    "change_pct": candidate.change_pct,
                    "turnover": candidate.turnover,
                    "turnover_rate": candidate.turnover_rate if candidate.turnover_rate is not None else (result.turnover_rate if result else None),
                    "volume_ratio": candidate.volume_ratio if candidate.volume_ratio is not None else (result.volume_ratio if result else None),
                    "active_pool_rank": int(active_pool_rank) if active_pool_rank is not None else None,
                    "b1_passed": candidate.b1_passed if candidate.b1_passed is not None else (result.b1_passed if result else None),
                    "kdj_j": candidate.kdj_j,
                    "verdict": result.verdict if result else None,
                    "total_score": result.total_score if result else None,
                    "signal_type": result.signal_type if result else None,
                    "comment": result.comment if result else None,
                    "prefilter_passed": prefilter_passed,
                    "prefilter_summary": prefilter_summary,
                    "prefilter_blocked_by": prefilter_blocked_by,
                    "pullback_quality": details_json.get("pullback_quality") if isinstance(details_json, dict) else None,
                    "pullback_negative_flags": self.current_hot_service._normalize_pullback_negative_flags(details_json.get("pullback_negative_flags")),
                }
            )

        items.sort(
            key=lambda item: (
                self.current_hot_service._signal_sort_priority(item.get("signal_type")),
                0 if item.get("b1_passed") is True else 1,
                self.current_hot_service._sort_score_desc(item.get("total_score")),
                self.current_hot_service._sort_active_pool_rank(item.get("active_pool_rank")),
                item["code"],
            )
        )
        return {
            "sector_key": normalized_sector_key,
            "pick_date": target_date,
            "rows": items,
            "total": len(items),
        }

    def prune_window(self, window_size: int = DEFAULT_WINDOW_SIZE) -> dict[str, Any]:
        keep_dates = self.current_hot_service.get_recent_trade_dates(window_size)
        if not keep_dates:
            return {"deleted_dates": []}

        keep_set = set(keep_dates)
        deleted_dates = [
            row.pick_date.isoformat()
            for row in self.db.query(SectorAnalysisRun)
            .filter(~SectorAnalysisRun.pick_date.in_(keep_set))
            .order_by(SectorAnalysisRun.pick_date.asc())
            .all()
        ]
        self.db.query(SectorAnalysisResult).filter(~SectorAnalysisResult.pick_date.in_(keep_set)).delete(synchronize_session=False)
        self.db.query(SectorAnalysisCandidate).filter(~SectorAnalysisCandidate.pick_date.in_(keep_set)).delete(synchronize_session=False)
        self.db.query(SectorAnalysisRun).filter(~SectorAnalysisRun.pick_date.in_(keep_set)).delete(synchronize_session=False)
        self.db.flush()
        return {"deleted_dates": deleted_dates}

    def ensure_window(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        *,
        reviewer: str = DEFAULT_REVIEWER,
        force: bool = False,
        backfill_missing_history: bool = True,
    ) -> dict[str, Any]:
        target_dates = list(reversed(self.current_hot_service.get_recent_trade_dates(window_size)))
        sectors, _, _, _ = self._build_sector_entry_map()
        expected_sector_keys = {str(sector.get("key") or "") for sector in sectors if str(sector.get("key") or "").strip()}

        ready_dates: set[str] = set()
        if expected_sector_keys:
            rows = (
                self.db.query(SectorAnalysisRun.pick_date, SectorAnalysisRun.sector_key, SectorAnalysisRun.status)
                .filter(SectorAnalysisRun.pick_date.in_(target_dates))
                .all()
            )
            per_date_status: dict[str, dict[str, str]] = defaultdict(dict)
            for pick_date, sector_key, status in rows:
                if pick_date and sector_key:
                    per_date_status[pick_date.isoformat()][str(sector_key)] = str(status or "")
            ready_dates = {
                pick_date
                for pick_date, status_map in per_date_status.items()
                if expected_sector_keys.issubset(set(status_map.keys()))
                and all(status_map.get(sector_key) == "success" for sector_key in expected_sector_keys)
            }

        rebuilt_dates: list[str] = []
        failed_dates: list[str] = []
        for index, pick_date in enumerate(target_dates, start=1):
            pick_date_text = pick_date.isoformat()
            if not force and pick_date_text in ready_dates:
                logger.info("[sector-analysis] skip %s (%s/%s) already success", pick_date_text, index, len(target_dates))
                continue

            logger.info("[sector-analysis] rebuilding %s (%s/%s)", pick_date_text, index, len(target_dates))
            result = self.generate_for_trade_date(
                pick_date,
                reviewer=reviewer,
                backfill_missing_history=backfill_missing_history,
            )
            if result.get("status") == "ok":
                rebuilt_dates.append(pick_date_text)
            else:
                failed_dates.append(pick_date_text)
                logger.warning("[sector-analysis] rebuild failed %s: %s", pick_date_text, result.get("message"))

        prune_result = self.prune_window(window_size)
        self.db.commit()
        return {
            "window_size": window_size,
            "target_dates": [value.isoformat() for value in reversed(target_dates)],
            "rebuilt_dates": rebuilt_dates,
            "failed_dates": failed_dates,
            "pruned_dates": prune_result.get("deleted_dates", []),
            "summary": self.get_sector_analysis(window_size=window_size, top_n=5),
        }
