"""
Current hot pool service.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Config,
    CurrentHotAnalysisResult,
    CurrentHotCandidate,
    CurrentHotRun,
    Stock,
    StockDaily,
    Task,
)
from app.services.analysis_service import analysis_service
from app.services.current_hot_pool import DEFAULT_CURRENT_HOT_POOL
from app.services.daily_data_service import DailyDataService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now


@dataclass
class CurrentHotPoolEntry:
    code: str
    name: str
    primary_sector: str
    sector_names: list[str] = field(default_factory=list)
    board_group: str = "other"


class CurrentHotService:
    """当前热盘服务。"""

    CONFIG_KEY = "current_hot_pool"
    DEFAULT_REVIEWER = "quant"
    DEFAULT_SOURCE = "current_hot"
    DEFAULT_WINDOW_SIZE = 120
    MIN_HISTORY_DAYS = 60
    HISTORY_LOOKBACK_DAYS = 420
    ACTIVE_TASK_TYPES = ("full_update", "incremental_update", "tomorrow_star", "recent_120_rebuild")

    def __init__(self, db: Session):
        self.db = db
        self.tushare_service = TushareService()

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _sort_score_desc(value: Optional[float]) -> float:
        return -(value if value is not None else -9999.0)

    @staticmethod
    def _signal_sort_priority(signal_type: Optional[str]) -> int:
        return 0 if signal_type == "trend_start" else 1

    @staticmethod
    def _is_generic_sector_name(value: Optional[str]) -> bool:
        return str(value or "").strip() in {"", "当前热盘", "热力股票池", "当前热盘AI标的"}

    @staticmethod
    def get_board_group(code: str) -> str:
        normalized = str(code or "").zfill(6)
        return "kechuang" if normalized.startswith(("688", "689")) else "other"

    @staticmethod
    def get_market(code: str) -> str:
        normalized = str(code or "").zfill(6)
        if normalized.startswith(("600", "601", "603", "605", "688", "689")):
            return "SH"
        if normalized.startswith(("430", "8", "920")):
            return "BJ"
        return "SZ"

    @staticmethod
    def _normalize_trade_date(value: Optional[str | date]) -> Optional[date]:
        if value is None:
            return None
        if isinstance(value, date):
            return value
        text = str(value).strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None

    def _load_pool_config(self) -> dict[str, dict[str, str]]:
        def normalize_pool_config(payload: Any) -> dict[str, dict[str, str]]:
            if not isinstance(payload, dict) or not payload:
                return DEFAULT_CURRENT_HOT_POOL

            # 兼容扁平结构：{ "600000": "浦发银行" }
            if all(isinstance(key, str) and str(key).isdigit() for key in payload.keys()):
                return {
                    "当前热盘": {
                        str(name or code): str(code).zfill(6)
                        for code, name in payload.items()
                        if str(code or "").strip()
                    }
                }

            normalized: dict[str, dict[str, str]] = {}
            for sector_name, items in payload.items():
                if not isinstance(items, dict):
                    continue
                sector_items: dict[str, str] = {}
                for raw_name, raw_code in items.items():
                    if str(raw_name or "").isdigit():
                        code = str(raw_name).zfill(6)
                        name = str(raw_code or code)
                    else:
                        code = str(raw_code or "").zfill(6)
                        name = str(raw_name or code)
                    if code and code != "000000":
                        sector_items[name] = code
                if sector_items:
                    normalized[str(sector_name or "当前热盘")] = sector_items
            return normalized or DEFAULT_CURRENT_HOT_POOL

        row = self.db.query(Config).filter(Config.key == self.CONFIG_KEY).first()
        if row and row.value:
            try:
                payload = json.loads(row.value)
                return normalize_pool_config(payload)
            except Exception:
                pass
        return DEFAULT_CURRENT_HOT_POOL

    def _stock_industry_by_code(self, codes: list[str]) -> dict[str, str]:
        normalized_codes = [str(code or "").zfill(6) for code in codes if str(code or "").strip()]
        if not normalized_codes:
            return {}
        rows = (
            self.db.query(Stock.code, Stock.industry)
            .filter(Stock.code.in_(normalized_codes))
            .all()
        )
        return {
            str(code).zfill(6): str(industry).strip()
            for code, industry in rows
            if str(industry or "").strip() and not self._is_generic_sector_name(str(industry).strip())
        }

    def _resolve_sector_names(
        self,
        sector_names: Optional[list[str]],
        *,
        industry: Optional[str] = None,
    ) -> list[str]:
        names = [
            str(item).strip()
            for item in (sector_names or [])
            if str(item or "").strip() and not self._is_generic_sector_name(str(item).strip())
        ]
        if names:
            return names
        industry_name = str(industry or "").strip()
        if industry_name and not self._is_generic_sector_name(industry_name) and industry_name not in names:
            names.append(industry_name)
            return names
        return ["当前热盘"]

    def _enrich_pool_entries_with_stock_industry(self, entries: list[CurrentHotPoolEntry]) -> list[CurrentHotPoolEntry]:
        industry_by_code = self._stock_industry_by_code([entry.code for entry in entries])
        for entry in entries:
            industry = industry_by_code.get(entry.code)
            entry.sector_names = self._resolve_sector_names(entry.sector_names, industry=industry)
            if self._is_generic_sector_name(entry.primary_sector) and entry.sector_names:
                entry.primary_sector = entry.sector_names[0]
        return entries

    def get_pool_entries(self) -> list[CurrentHotPoolEntry]:
        merged: dict[str, CurrentHotPoolEntry] = {}
        for sector_name, items in self._load_pool_config().items():
            if not isinstance(items, dict):
                continue
            for stock_name, raw_code in items.items():
                code = str(raw_code or "").zfill(6)
                if not code or code == "000000":
                    continue
                entry = merged.get(code)
                if entry is None:
                    merged[code] = CurrentHotPoolEntry(
                        code=code,
                        name=str(stock_name or code),
                        primary_sector=str(sector_name),
                        sector_names=[str(sector_name)],
                        board_group=self.get_board_group(code),
                    )
                    continue
                if stock_name and (not entry.name or entry.name == entry.code):
                    entry.name = str(stock_name)
                if sector_name not in entry.sector_names:
                    entry.sector_names.append(str(sector_name))
        return self._enrich_pool_entries_with_stock_industry(list(merged.values()))

    def get_latest_trade_date(self) -> Optional[date]:
        return (
            self.db.query(StockDaily.trade_date)
            .order_by(StockDaily.trade_date.desc())
            .limit(1)
            .scalar()
        )

    def get_latest_pick_date(self) -> Optional[date]:
        return (
            self.db.query(CurrentHotRun.pick_date)
            .order_by(CurrentHotRun.pick_date.desc())
            .limit(1)
            .scalar()
        )

    def _ensure_stocks_exist(self, entries: list[CurrentHotPoolEntry]) -> None:
        if not entries:
            return
        codes = [entry.code for entry in entries]
        try:
            self.tushare_service.sync_stock_names_to_db(self.db, codes)
        except Exception:
            pass

        existing_codes = {
            code for code, in self.db.query(Stock.code).filter(Stock.code.in_(codes)).all()
        }
        for entry in entries:
            if entry.code in existing_codes:
                stock = self.db.query(Stock).filter(Stock.code == entry.code).first()
                if stock and not stock.name and entry.name:
                    stock.name = entry.name
                continue
            self.db.add(
                Stock(
                    code=entry.code,
                    name=entry.name,
                    market=self.get_market(entry.code),
                    industry=entry.primary_sector,
                )
            )
        self.db.flush()

    def load_stock_frame(self, code: str, trade_date: date, days: int = 365) -> pd.DataFrame:
        rows = (
            self.db.query(StockDaily)
            .filter(
                StockDaily.code == code,
                StockDaily.trade_date <= trade_date,
            )
            .order_by(StockDaily.trade_date.desc(), StockDaily.id.desc())
            .limit(days)
            .all()
        )
        if not rows:
            return pd.DataFrame()
        ordered_rows = list(reversed(rows))
        return pd.DataFrame(
            [
                {
                    "date": row.trade_date,
                    "open": self._safe_float(row.open),
                    "close": self._safe_float(row.close),
                    "high": self._safe_float(row.high),
                    "low": self._safe_float(row.low),
                    "volume": self._safe_float(row.volume),
                    "turnover_rate": self._safe_float(row.turnover_rate),
                    "volume_ratio": self._safe_float(row.volume_ratio),
                }
                for row in ordered_rows
            ]
        )

    def _persist_history_frame(self, code: str, frame: Optional[pd.DataFrame]) -> int:
        if frame is None or frame.empty:
            return 0

        normalized_code = str(code or "").zfill(6)
        records: list[tuple[date, float, float, float, float, float, Optional[float], Optional[float]]] = []
        for _, row in frame.iterrows():
            raw_trade_date = row.get("trade_date")
            trade_date = self._normalize_trade_date(raw_trade_date)
            if trade_date is None:
                continue
            try:
                records.append(
                    (
                        trade_date,
                        float(row["open"]),
                        float(row["close"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["volume"]),
                        self._safe_float(row.get("turnover_rate")),
                        self._safe_float(row.get("volume_ratio")),
                    )
                )
            except (TypeError, ValueError, KeyError):
                continue

        if not records:
            return 0

        trade_dates = [trade_date for trade_date, *_ in records]
        existing_rows = {
            row.trade_date: row
            for row in self.db.query(StockDaily)
            .filter(
                StockDaily.code == normalized_code,
                StockDaily.trade_date.in_(trade_dates),
            )
            .all()
        }

        persisted = 0
        for trade_date, open_price, close_price, high_price, low_price, volume, turnover_rate, volume_ratio in records:
            existing = existing_rows.get(trade_date)
            if existing is None:
                self.db.add(
                    StockDaily(
                        code=normalized_code,
                        trade_date=trade_date,
                        open=open_price,
                        close=close_price,
                        high=high_price,
                        low=low_price,
                        volume=volume,
                        turnover_rate=turnover_rate,
                        volume_ratio=volume_ratio,
                    )
                )
            else:
                existing.open = open_price
                existing.close = close_price
                existing.high = high_price
                existing.low = low_price
                existing.volume = volume
                existing.turnover_rate = turnover_rate
                existing.volume_ratio = volume_ratio
            persisted += 1

        self.db.flush()
        return persisted

    def _ensure_history_window(
        self,
        entries: list[CurrentHotPoolEntry],
        trade_date: date,
        *,
        min_days: int = MIN_HISTORY_DAYS,
        backfill_missing_history: bool = True,
    ) -> dict[str, list[str]]:
        start_date = (trade_date - timedelta(days=self.HISTORY_LOOKBACK_DAYS)).isoformat()
        end_date = trade_date.isoformat()
        daily_service: Optional[DailyDataService] = None
        backfilled_codes: list[str] = []
        insufficient_codes: list[str] = []

        for entry in entries:
            current_frame = self.load_stock_frame(entry.code, trade_date, days=min_days)
            if len(current_frame) >= min_days:
                continue
            if not backfill_missing_history:
                insufficient_codes.append(entry.code)
                continue

            if daily_service is None:
                daily_service = DailyDataService(token=self.tushare_service.token)
            fetched = daily_service.fetch_daily_data(entry.code, start_date=start_date, end_date=end_date)
            self._persist_history_frame(entry.code, fetched)

            refreshed_frame = self.load_stock_frame(entry.code, trade_date, days=min_days)
            if len(refreshed_frame) >= min_days:
                backfilled_codes.append(entry.code)
            else:
                insufficient_codes.append(entry.code)

        return {
            "backfilled_codes": backfilled_codes,
            "insufficient_codes": insufficient_codes,
        }

    def get_recent_trade_dates(self, window_size: int = DEFAULT_WINDOW_SIZE) -> list[date]:
        rows = (
            self.db.query(StockDaily.trade_date)
            .distinct()
            .order_by(StockDaily.trade_date.desc())
            .limit(window_size)
            .all()
        )
        return [trade_date for trade_date, in rows if trade_date]

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
        run: Optional[CurrentHotRun],
        *,
        candidate_count: int,
        analysis_count: int,
        has_active_task: bool,
    ) -> str:
        if run is None:
            return "success" if candidate_count > 0 and analysis_count > 0 else "missing"

        status = str(run.status or "").strip().lower() or "missing"
        if status == "success":
            return "success"
        if status in {"running", "pending"}:
            if candidate_count > 0 and analysis_count > 0:
                return "success"
            if not has_active_task:
                return "missing"
        return status

    def _build_fallback_snapshot(
        self,
        *,
        code: str,
        trade_date: date,
        reason: str,
        frame: Optional[pd.DataFrame] = None,
    ) -> dict[str, Any]:
        last_row = frame.iloc[-1] if frame is not None and not frame.empty else None
        open_price = self._safe_float(last_row.get("open")) if last_row is not None else None
        close_price = self._safe_float(last_row.get("close")) if last_row is not None else None
        change_pct = None
        if open_price not in (None, 0) and close_price is not None:
            change_pct = (close_price - open_price) / open_price * 100
        turnover_rate = self._safe_float(last_row.get("turnover_rate")) if last_row is not None else None
        volume_ratio = self._safe_float(last_row.get("volume_ratio")) if last_row is not None else None
        return {
            "code": code,
            "trade_date": trade_date,
            "open_price": open_price,
            "close_price": close_price,
            "change_pct": change_pct,
            "turnover": None,
            "turnover_rate": turnover_rate,
            "volume_ratio": volume_ratio,
            "b1_passed": False if frame is not None and not frame.empty else None,
            "kdj_j": None,
            "zx_long_pos": None,
            "weekly_ma_aligned": None,
            "volume_healthy": None,
            "score": None,
            "verdict": "FAIL" if frame is not None and not frame.empty else None,
            "signal_type": None,
            "comment": reason,
            "details_json": {
                "comment": reason,
                "scores": {},
                "signal_reasoning": None,
                "trend_reasoning": None,
                "position_reasoning": None,
                "volume_reasoning": None,
                "abnormal_move_reasoning": None,
                "turnover_rate": turnover_rate,
                "volume_ratio": volume_ratio,
            },
        }

    def build_trade_snapshot(self, code: str, trade_date: date) -> dict[str, Any]:
        frame = self.load_stock_frame(code, trade_date, days=365)
        if frame.empty or len(frame) < 60:
            return self._build_fallback_snapshot(
                code=code,
                trade_date=trade_date,
                reason="历史数据不足",
                frame=frame,
            )

        try:
            selector = analysis_service._build_b1_selector()
            prepared = selector.prepare_df(frame.copy())
            if prepared.empty:
                return self._build_fallback_snapshot(
                    code=code,
                    trade_date=trade_date,
                    reason="指标计算失败",
                    frame=frame,
                )

            last_row = prepared.iloc[-1]
            last_price_row = frame.iloc[-1]
            open_price = self._safe_float(last_price_row.get("open"))
            close_price = self._safe_float(last_price_row.get("close"))
            change_pct = None
            if open_price not in (None, 0) and close_price is not None:
                change_pct = (close_price - open_price) / open_price * 100

            score_result = analysis_service._quant_review_for_date(code, frame.copy(), trade_date.isoformat())
            return {
                "code": code,
                "trade_date": trade_date,
                "open_price": open_price,
                "close_price": close_price,
                "change_pct": change_pct,
                "turnover": None,
                "turnover_rate": self._safe_float(last_price_row.get("turnover_rate")),
                "volume_ratio": self._safe_float(last_price_row.get("volume_ratio")),
                "b1_passed": bool(last_row.get("_vec_pick", False)) if pd.notna(last_row.get("_vec_pick")) else False,
                "kdj_j": self._safe_float(last_row.get("J")),
                "zx_long_pos": bool(last_row["zxdq"] > last_row["zxdkx"]) if pd.notna(last_row.get("zxdq")) and pd.notna(last_row.get("zxdkx")) else None,
                "weekly_ma_aligned": bool(last_row["wma_bull"]) if pd.notna(last_row.get("wma_bull")) else None,
                "volume_healthy": analysis_service._calculate_volume_health(prepared),
                "score": score_result.get("score"),
                "verdict": score_result.get("verdict"),
                "signal_type": score_result.get("signal_type"),
                "comment": score_result.get("comment"),
                "details_json": {
                    "comment": score_result.get("comment"),
                    "scores": score_result.get("scores") or {},
                    "signal_reasoning": score_result.get("signal_reasoning"),
                    "trend_reasoning": score_result.get("trend_reasoning"),
                    "position_reasoning": score_result.get("position_reasoning"),
                    "volume_reasoning": score_result.get("volume_reasoning"),
                    "abnormal_move_reasoning": score_result.get("abnormal_move_reasoning"),
                    "zx_long_pos": bool(last_row["zxdq"] > last_row["zxdkx"]) if pd.notna(last_row.get("zxdq")) and pd.notna(last_row.get("zxdkx")) else None,
                    "weekly_ma_aligned": bool(last_row["wma_bull"]) if pd.notna(last_row.get("wma_bull")) else None,
                    "volume_healthy": analysis_service._calculate_volume_health(prepared),
                    "turnover_rate": self._safe_float(last_price_row.get("turnover_rate")),
                    "volume_ratio": self._safe_float(last_price_row.get("volume_ratio")),
                },
            }
        except Exception as exc:
            return self._build_fallback_snapshot(
                code=code,
                trade_date=trade_date,
                reason=f"分析失败: {exc}",
                frame=frame,
            )

    def _get_or_create_run(
        self,
        pick_date: date,
        *,
        reviewer: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> CurrentHotRun:
        run = self.db.query(CurrentHotRun).filter(CurrentHotRun.pick_date == pick_date).first()
        if run is None:
            run = CurrentHotRun(pick_date=pick_date)
            self.db.add(run)
        run.reviewer = reviewer
        run.source = self.DEFAULT_SOURCE
        run.status = status
        run.error_message = error_message
        return run

    def _refresh_run_counts(self, run: CurrentHotRun) -> None:
        pick_date = run.pick_date
        run.candidate_count = int(
            self.db.query(func.count(CurrentHotCandidate.id))
            .filter(CurrentHotCandidate.pick_date == pick_date)
            .scalar()
            or 0
        )
        run.analysis_count = int(
            self.db.query(func.count(CurrentHotAnalysisResult.id))
            .filter(CurrentHotAnalysisResult.pick_date == pick_date)
            .scalar()
            or 0
        )
        run.trend_start_count = int(
            self.db.query(func.count(CurrentHotAnalysisResult.id))
            .filter(
                CurrentHotAnalysisResult.pick_date == pick_date,
                CurrentHotAnalysisResult.signal_type == "trend_start",
            )
            .scalar()
            or 0
        )
        run.consecutive_candidate_count = int(
            self.db.query(func.count(CurrentHotCandidate.id))
            .filter(
                CurrentHotCandidate.pick_date == pick_date,
                CurrentHotCandidate.consecutive_days >= 2,
            )
            .scalar()
            or 0
        )

    @staticmethod
    def recalculate_consecutive_metrics(db: Session, *, commit: bool = True) -> None:
        pick_dates = [
            value
            for value, in db.query(CurrentHotCandidate.pick_date)
            .distinct()
            .order_by(CurrentHotCandidate.pick_date.asc())
            .all()
        ]
        previous_pick_date_map = {
            pick_dates[index]: pick_dates[index - 1]
            for index in range(1, len(pick_dates))
        }
        rows = (
            db.query(CurrentHotCandidate)
            .order_by(CurrentHotCandidate.code.asc(), CurrentHotCandidate.pick_date.asc(), CurrentHotCandidate.id.asc())
            .all()
        )

        last_seen_date_by_code: dict[str, date] = {}
        last_streak_by_code: dict[str, int] = {}
        consecutive_count_by_date: dict[date, int] = {}
        for row in rows:
            expected_previous_date = previous_pick_date_map.get(row.pick_date)
            previous_seen_date = last_seen_date_by_code.get(row.code)
            if expected_previous_date and previous_seen_date == expected_previous_date:
                row.consecutive_days = last_streak_by_code.get(row.code, 0) + 1
            else:
                row.consecutive_days = 1
            last_seen_date_by_code[row.code] = row.pick_date
            last_streak_by_code[row.code] = row.consecutive_days
            if row.consecutive_days >= 2:
                consecutive_count_by_date[row.pick_date] = int(consecutive_count_by_date.get(row.pick_date, 0) or 0) + 1

        for run in db.query(CurrentHotRun).all():
            run.consecutive_candidate_count = int(consecutive_count_by_date.get(run.pick_date, 0) or 0)

        if commit:
            db.commit()
        else:
            db.flush()

    def generate_for_trade_date(
        self,
        trade_date: Optional[str | date] = None,
        reviewer: str = DEFAULT_REVIEWER,
        *,
        backfill_missing_history: bool = True,
    ) -> dict[str, Any]:
        target_trade_date = self._normalize_trade_date(trade_date) or self.get_latest_trade_date()
        if target_trade_date is None:
            return {
                "trade_date": None,
                "status": "missing_trade_date",
                "message": "未找到可用交易日",
                "generated_count": 0,
                "skipped_count": 0,
            }

        entries = self.get_pool_entries()
        if not entries:
            return {
                "trade_date": target_trade_date,
                "status": "empty_pool",
                "message": "当前热盘配置为空",
                "generated_count": 0,
                "skipped_count": 0,
            }

        generated_count = 0
        skipped_count = 0
        started_at = utc_now()
        run = self._get_or_create_run(target_trade_date, reviewer=reviewer, status="running")
        run.started_at = started_at
        run.finished_at = None
        self.db.commit()

        try:
            self._ensure_stocks_exist(entries)
            entries = self._enrich_pool_entries_with_stock_industry(entries)
            self._ensure_history_window(
                entries,
                target_trade_date,
                backfill_missing_history=backfill_missing_history,
            )
            self.db.query(CurrentHotCandidate).filter(
                CurrentHotCandidate.pick_date == target_trade_date
            ).delete(synchronize_session=False)
            self.db.query(CurrentHotAnalysisResult).filter(
                CurrentHotAnalysisResult.pick_date == target_trade_date
            ).delete(synchronize_session=False)

            candidate_rows: list[CurrentHotCandidate] = []
            analysis_rows: list[CurrentHotAnalysisResult] = []
            for entry in entries:
                payload = self.build_trade_snapshot(entry.code, target_trade_date)
                if payload.get("close_price") is None:
                    skipped_count += 1
                else:
                    generated_count += 1

                candidate_rows.append(
                    CurrentHotCandidate(
                        pick_date=target_trade_date,
                        code=entry.code,
                        sector_names_json=entry.sector_names,
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
                    CurrentHotAnalysisResult(
                        pick_date=target_trade_date,
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

            self.recalculate_consecutive_metrics(self.db, commit=False)
            run = self._get_or_create_run(target_trade_date, reviewer=reviewer, status="success")
            run.finished_at = utc_now()
            run.error_message = None
            self._refresh_run_counts(run)
            self.db.commit()
            return {
                "trade_date": target_trade_date,
                "status": "ok",
                "message": None,
                "generated_count": generated_count,
                "skipped_count": skipped_count,
            }
        except Exception as exc:
            self.db.rollback()
            failed_run = self._get_or_create_run(target_trade_date, reviewer=reviewer, status="failed", error_message=str(exc))
            failed_run.finished_at = utc_now()
            self.db.commit()
            return {
                "trade_date": target_trade_date,
                "status": "failed",
                "message": str(exc),
                "generated_count": generated_count,
                "skipped_count": skipped_count,
            }

    def get_dates(self, window_size: int = DEFAULT_WINDOW_SIZE) -> dict[str, Any]:
        target_dates = self.get_recent_trade_dates(window_size)
        if not target_dates:
            return {"dates": [], "history": [], "latest_date": None}

        run_map = {
            row.pick_date: row
            for row in self.db.query(CurrentHotRun)
            .filter(CurrentHotRun.pick_date.in_(target_dates))
            .all()
        }
        candidate_counts = {
            pick_date: int(count or 0)
            for pick_date, count in self.db.query(
                CurrentHotCandidate.pick_date,
                func.count(CurrentHotCandidate.id),
            )
            .filter(CurrentHotCandidate.pick_date.in_(target_dates))
            .group_by(CurrentHotCandidate.pick_date)
            .all()
        }
        analysis_counts = {
            pick_date: int(count or 0)
            for pick_date, count in self.db.query(
                CurrentHotAnalysisResult.pick_date,
                func.count(CurrentHotAnalysisResult.id),
            )
            .filter(CurrentHotAnalysisResult.pick_date.in_(target_dates))
            .group_by(CurrentHotAnalysisResult.pick_date)
            .all()
        }
        trend_counts = {
            pick_date: int(count or 0)
            for pick_date, count in self.db.query(
                CurrentHotAnalysisResult.pick_date,
                func.count(CurrentHotAnalysisResult.id),
            )
            .filter(
                CurrentHotAnalysisResult.pick_date.in_(target_dates),
                CurrentHotAnalysisResult.signal_type == "trend_start",
            )
            .group_by(CurrentHotAnalysisResult.pick_date)
            .all()
        }
        b1_pass_counts = {
            pick_date: int(count or 0)
            for pick_date, count in self.db.query(
                CurrentHotCandidate.pick_date,
                func.count(CurrentHotCandidate.id),
            )
            .filter(
                CurrentHotCandidate.pick_date.in_(target_dates),
                CurrentHotCandidate.b1_passed.is_(True),
            )
            .group_by(CurrentHotCandidate.pick_date)
            .all()
        }
        consecutive_counts = {
            pick_date: int(count or 0)
            for pick_date, count in self.db.query(
                CurrentHotCandidate.pick_date,
                func.count(CurrentHotCandidate.id),
            )
            .filter(
                CurrentHotCandidate.pick_date.in_(target_dates),
                CurrentHotCandidate.consecutive_days >= 2,
            )
            .group_by(CurrentHotCandidate.pick_date)
            .all()
        }

        has_active_task = self._has_active_generation_task()
        latest_date = target_dates[0].isoformat()
        history = []
        for pick_date in target_dates:
            run = run_map.get(pick_date)
            candidate_count = candidate_counts.get(pick_date, 0)
            analysis_count = analysis_counts.get(pick_date, 0)
            trend_start_count = trend_counts.get(pick_date, 0)
            b1_pass_count = b1_pass_counts.get(pick_date, 0)
            consecutive_candidate_count = consecutive_counts.get(pick_date, 0)
            history.append(
                {
                    "pick_date": pick_date.isoformat(),
                    "date": pick_date.isoformat(),
                    "trend_start_count": trend_start_count,
                    "b1_pass_count": b1_pass_count,
                    "pass_count": trend_start_count,
                    "consecutive_candidate_count": consecutive_candidate_count,
                    "candidate_count": candidate_count,
                    "analysis_count": analysis_count,
                    "status": self._resolve_display_status(
                        run,
                        candidate_count=candidate_count,
                        analysis_count=analysis_count,
                        has_active_task=has_active_task,
                    ),
                    "error_message": run.error_message if run else None,
                    "is_latest": pick_date.isoformat() == latest_date,
                }
            )
        return {
            "dates": [item["date"] for item in history],
            "history": history,
            "latest_date": latest_date,
        }

    def load_candidates(self, pick_date: Optional[str] = None, limit: int = 200) -> dict[str, Any]:
        target_date = self._normalize_trade_date(pick_date) or self.get_latest_pick_date()
        if target_date is None:
            return {"pick_date": None, "candidates": [], "total": 0}

        rows = (
            self.db.query(CurrentHotCandidate, CurrentHotAnalysisResult, Stock.name, Stock.industry)
            .outerjoin(
                CurrentHotAnalysisResult,
                (CurrentHotAnalysisResult.pick_date == CurrentHotCandidate.pick_date)
                & (CurrentHotAnalysisResult.code == CurrentHotCandidate.code)
                & (CurrentHotAnalysisResult.reviewer == self.DEFAULT_REVIEWER),
            )
            .outerjoin(Stock, CurrentHotCandidate.code == Stock.code)
            .filter(CurrentHotCandidate.pick_date == target_date)
            .all()
        )
        items = [
            {
                "id": row.id,
                "pick_date": target_date,
                "code": row.code,
                "name": stock_name,
                "sector_names": self._resolve_sector_names(row.sector_names_json, industry=stock_industry),
                "board_group": row.board_group,
                "open_price": row.open_price,
                "close_price": row.close_price,
                "change_pct": row.change_pct,
                "turnover": row.turnover,
                "turnover_rate": row.turnover_rate if row.turnover_rate is not None else (analysis.turnover_rate if analysis else None),
                "volume_ratio": row.volume_ratio if row.volume_ratio is not None else (analysis.volume_ratio if analysis else None),
                "b1_passed": row.b1_passed if row.b1_passed is not None else (analysis.b1_passed if analysis else None),
                "kdj_j": row.kdj_j,
                "verdict": analysis.verdict if analysis else None,
                "total_score": analysis.total_score if analysis else None,
                "signal_type": analysis.signal_type if analysis else None,
                "comment": analysis.comment if analysis else None,
                "consecutive_days": int(row.consecutive_days or 1),
            }
            for row, analysis, stock_name, stock_industry in rows
        ]
        items.sort(
            key=lambda item: (
                self._signal_sort_priority(item.get("signal_type")),
                0 if item.get("b1_passed") is True else 1,
                self._sort_score_desc(item.get("total_score")),
                item["code"],
            )
        )
        return {
            "pick_date": target_date,
            "candidates": items[:limit],
            "total": len(items),
        }

    def get_results(self, pick_date: Optional[str] = None) -> dict[str, Any]:
        target_date = self._normalize_trade_date(pick_date) or self.get_latest_pick_date()
        if target_date is None:
            return {"pick_date": None, "results": [], "total": 0, "min_score_threshold": 4.0}

        rows = (
            self.db.query(CurrentHotAnalysisResult, CurrentHotCandidate, Stock.name, Stock.industry)
            .outerjoin(
                CurrentHotCandidate,
                (CurrentHotCandidate.pick_date == CurrentHotAnalysisResult.pick_date)
                & (CurrentHotCandidate.code == CurrentHotAnalysisResult.code),
            )
            .outerjoin(Stock, CurrentHotAnalysisResult.code == Stock.code)
            .filter(CurrentHotAnalysisResult.pick_date == target_date)
            .all()
        )
        items = [
            {
                "id": result.id,
                "pick_date": target_date,
                "code": result.code,
                "name": stock_name,
                "reviewer": result.reviewer,
                "b1_passed": result.b1_passed,
                "verdict": result.verdict,
                "total_score": result.total_score,
                "signal_type": result.signal_type,
                "comment": result.comment,
                "turnover_rate": result.turnover_rate if result.turnover_rate is not None else (candidate.turnover_rate if candidate else None),
                "volume_ratio": result.volume_ratio if result.volume_ratio is not None else (candidate.volume_ratio if candidate else None),
                "sector_names": self._resolve_sector_names(candidate.sector_names_json if candidate else [], industry=stock_industry),
                "board_group": candidate.board_group if candidate else self.get_board_group(result.code),
            }
            for result, candidate, stock_name, stock_industry in rows
        ]
        items.sort(
            key=lambda item: (
                0 if item.get("b1_passed") is True else 1,
                self._signal_sort_priority(item.get("signal_type")),
                self._sort_score_desc(item.get("total_score")),
                item["code"],
            )
        )
        return {
            "pick_date": target_date,
            "results": items,
            "total": len(items),
            "min_score_threshold": 4.0,
        }

    def prune_window(self, window_size: int = DEFAULT_WINDOW_SIZE) -> dict[str, Any]:
        keep_dates = self.get_recent_trade_dates(window_size)
        if not keep_dates:
            return {"deleted_dates": []}

        keep_set = set(keep_dates)
        deleted_dates = [
            row.pick_date.isoformat()
            for row in self.db.query(CurrentHotRun)
            .filter(~CurrentHotRun.pick_date.in_(keep_set))
            .order_by(CurrentHotRun.pick_date.asc())
            .all()
        ]

        self.db.query(CurrentHotCandidate).filter(~CurrentHotCandidate.pick_date.in_(keep_set)).delete(synchronize_session=False)
        self.db.query(CurrentHotAnalysisResult).filter(~CurrentHotAnalysisResult.pick_date.in_(keep_set)).delete(synchronize_session=False)
        self.db.query(CurrentHotRun).filter(~CurrentHotRun.pick_date.in_(keep_set)).delete(synchronize_session=False)
        self.db.commit()
        return {"deleted_dates": deleted_dates}

    def ensure_window(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        *,
        reviewer: str = DEFAULT_REVIEWER,
        force: bool = False,
        backfill_missing_history: bool = True,
    ) -> dict[str, Any]:
        target_dates = list(reversed(self.get_recent_trade_dates(window_size)))
        rebuilt_dates: list[str] = []
        failed_dates: list[str] = []

        status_map = {item["pick_date"]: item for item in self.get_dates(window_size).get("history", [])}
        for pick_date in target_dates:
            pick_date_text = pick_date.isoformat()
            item = status_map.get(pick_date_text)
            if not force and item and item.get("status") == "success":
                continue

            result = self.generate_for_trade_date(
                pick_date,
                reviewer=reviewer,
                backfill_missing_history=backfill_missing_history,
            )
            if result.get("status") == "ok":
                rebuilt_dates.append(pick_date_text)
            else:
                failed_dates.append(pick_date_text)

        prune_result = self.prune_window(window_size)
        return {
            "window_size": window_size,
            "target_dates": [value.isoformat() for value in reversed(target_dates)],
            "rebuilt_dates": rebuilt_dates,
            "failed_dates": failed_dates,
            "pruned_dates": prune_result.get("deleted_dates", []),
            "summary": self.get_dates(window_size),
        }
