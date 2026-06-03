"""
Current hot pool service.
"""
from __future__ import annotations

import json
import logging
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
    DailyB1Check,
    DailyB1CheckDetail,
    Stock,
    StockActivePoolRank,
    StockDaily,
    StockFinancial,
    Task,
)
from app.services.analysis_service import analysis_service
from app.services.cycle_stock_pool import DEFAULT_CYCLE_STOCK_POOL
from app.services.daily_data_service import DailyDataService
from app.services.risk_regime_ai_service import RiskRegimeAIService
from app.services.risk_regime_service import RiskRegimeService
from app.services.sector_analysis_config import (
    resolve_sector_analysis_catalog,
    resolve_sector_stock_pool,
)
from app.services.speculative_risk_service import SpeculativeRiskService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now
from app.utils.tushare_rate_limit import acquire_tushare_slot


logger = logging.getLogger(__name__)


@dataclass
class CurrentHotPoolEntry:
    code: str
    name: str
    primary_sector: str
    sector_names: list[str] = field(default_factory=list)
    board_group: str = "other"


class CurrentHotService:
    """当前热盘服务。"""

    CONFIG_KEY = "cycle_stock_pool"
    LEGACY_CONFIG_KEY = "current_hot_pool"
    SECTOR_ANALYSIS_CATALOG_KEY = "sector_analysis_catalog"
    SECTOR_ANALYSIS_POOL_KEY = "sector_analysis_pool"
    DEFAULT_REVIEWER = "quant"
    DEFAULT_SOURCE = "current_hot"
    DEFAULT_WINDOW_SIZE = 120
    MIN_HISTORY_DAYS = 60
    HISTORY_LOOKBACK_DAYS = 420
    ACTIVE_TASK_TYPES = ("full_update", "incremental_update", "tomorrow_star", "recent_120_rebuild")
    NEGATIVE_STRENGTH_FLAGS = ("下跌逐步上量", "异常放量阴线")

    def __init__(self, db: Session):
        self.db = db
        self.tushare_service = TushareService()
        self._prefilter = None

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
    def _sort_active_pool_rank(value: Optional[int]) -> int:
        return int(value) if value is not None else 999999

    @staticmethod
    def _normalize_pullback_negative_flags(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split("|") if item.strip()]
        return []

    @staticmethod
    def _extract_prefilter_fields(details_json: Any) -> tuple[Optional[bool], Optional[str], list[str]]:
        if not isinstance(details_json, dict):
            return None, None, []

        prefilter = details_json.get("prefilter")
        if not isinstance(prefilter, dict):
            return None, None, []

        passed_raw = prefilter.get("passed")
        passed = passed_raw if isinstance(passed_raw, bool) else None

        summary_raw = prefilter.get("summary")
        summary = str(summary_raw).strip() if isinstance(summary_raw, str) and summary_raw.strip() else None

        blocked_by_raw = prefilter.get("blocked_by")
        if isinstance(blocked_by_raw, list):
            blocked_by = [str(item).strip() for item in blocked_by_raw if str(item).strip()]
        elif blocked_by_raw:
            blocked_text = str(blocked_by_raw).strip()
            blocked_by = [blocked_text] if blocked_text else []
        else:
            blocked_by = []

        return passed, summary, blocked_by

    @staticmethod
    def _is_generic_sector_name(value: Optional[str]) -> bool:
        return str(value or "").strip() in {"", "当前热盘", "周期性股票", "热力股票池", "当前热盘AI标的"}

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

    @staticmethod
    def _normalize_sector_label(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        for token in (" ", "\t", "\n", "_", "-", "/"):
            normalized = normalized.replace(token, "")
        return normalized

    def _get_prefilter(self):
        if self._prefilter is None:
            self._prefilter = analysis_service._build_prefilter()
        return self._prefilter

    def _load_text_config(self, key: str) -> Optional[str]:
        value = self.db.query(Config.value).filter(Config.key == key).scalar()
        text = str(value or "").strip()
        return text or None

    def _load_sector_analysis_catalog(self) -> dict[str, Any]:
        return resolve_sector_analysis_catalog(self._load_text_config(self.SECTOR_ANALYSIS_CATALOG_KEY))

    def _load_sector_analysis_pool(self) -> dict[str, list[dict[str, str]]]:
        return resolve_sector_stock_pool(
            self._load_text_config(self.SECTOR_ANALYSIS_POOL_KEY),
            self._load_text_config(self.CONFIG_KEY) or self._load_text_config(self.LEGACY_CONFIG_KEY),
        )

    def _load_pool_config(self) -> dict[str, dict[str, str]]:
        def normalize_pool_config(payload: Any) -> dict[str, dict[str, str]]:
            if not isinstance(payload, dict) or not payload:
                return DEFAULT_CYCLE_STOCK_POOL

            # 兼容扁平结构：{ "600000": "浦发银行" }
            if all(isinstance(key, str) and str(key).isdigit() for key in payload.keys()):
                return {
                    "周期性股票": {
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
                    normalized[str(sector_name or "周期性股票")] = sector_items
            return normalized or DEFAULT_CYCLE_STOCK_POOL

        row = self.db.query(Config).filter(Config.key == self.CONFIG_KEY).first()
        if row is None:
            row = self.db.query(Config).filter(Config.key == self.LEGACY_CONFIG_KEY).first()
        if row and row.value:
            try:
                payload = json.loads(row.value)
                return normalize_pool_config(payload)
            except Exception:
                pass
        return DEFAULT_CYCLE_STOCK_POOL

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

    def _fetch_daily_basic_metrics(self, trade_date: date, codes: list[str]) -> dict[str, dict[str, Any]]:
        normalized_codes = {str(code or "").zfill(6) for code in codes if str(code or "").strip()}
        if not normalized_codes or not self.tushare_service.token:
            return {}
        try:
            acquire_tushare_slot("daily_basic")
            frame = self.tushare_service.pro.daily_basic(
                trade_date=trade_date.strftime("%Y%m%d"),
                fields="ts_code,trade_date,pb",
            )
        except Exception as exc:
            logger.warning("[current-hot] daily_basic metrics fetch failed for %s: %s", trade_date, exc)
            return {}
        if frame is None or frame.empty:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for _, row in frame.iterrows():
            ts_code = str(row.get("ts_code") or "")
            code = ts_code.split(".", 1)[0].zfill(6)
            if code in normalized_codes:
                result[code] = {"pb": self._safe_float(row.get("pb"))}
        return result

    def _load_financial_metrics(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        normalized_codes = [str(code or "").zfill(6) for code in codes if str(code or "").strip()]
        if not normalized_codes:
            return {}
        rows = (
            self.db.query(StockFinancial)
            .filter(StockFinancial.code.in_(normalized_codes))
            .all()
        )
        return {
            str(row.code).zfill(6): {
                "netprofit_yoy": self._safe_float(row.netprofit_yoy),
                "roe": self._safe_float(row.roe),
            }
            for row in rows
        }

    @staticmethod
    def _merge_market_financial_metrics(
        item: dict[str, Any],
        *,
        daily_basic_metrics: dict[str, dict[str, Any]],
        financial_metrics: dict[str, dict[str, Any]],
    ) -> None:
        code = str(item.get("code") or "").zfill(6)
        daily_basic = daily_basic_metrics.get(code, {})
        financial = financial_metrics.get(code, {})
        item["pb"] = daily_basic.get("pb")
        item["netprofit_yoy"] = financial.get("netprofit_yoy")
        item["roe"] = financial.get("roe")

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
            return ["周期性股票"]

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

    def _build_sector_aliases(self, sector: dict[str, Any]) -> set[str]:
        aliases = {
            self._normalize_sector_label(sector.get("key")),
            self._normalize_sector_label(sector.get("name")),
        }
        for field_name in ("policyFocus", "focusTracks", "industryHints"):
            for value in sector.get(field_name) or []:
                alias = self._normalize_sector_label(value)
                if alias:
                    aliases.add(alias)
        return {value for value in aliases if value}

    def _resolve_sector_keys_for_row(
        self,
        code: str,
        sector_names: list[str],
        *,
        code_to_sector_keys: dict[str, set[str]],
        sector_aliases: dict[str, set[str]],
    ) -> list[str]:
        mapped = code_to_sector_keys.get(code)
        if mapped:
            return sorted(mapped)

        normalized_names = {
            self._normalize_sector_label(name)
            for name in sector_names
            if self._normalize_sector_label(name)
        }
        if not normalized_names:
            return []

        matches = [
            sector_key
            for sector_key, aliases in sector_aliases.items()
            if normalized_names & aliases
        ]
        return sorted(set(matches))

    @staticmethod
    def _limit_up_threshold(code: str) -> float:
        normalized = str(code or "").zfill(6)
        if normalized.startswith(("688", "689", "300")):
            return 19.6
        if normalized.startswith(("430", "8", "920")):
            return 29.6
        return 9.6

    def _load_recent_trade_metrics(
        self,
        codes: list[str],
        target_date: date,
        *,
        window_size: int = 5,
    ) -> dict[str, dict[str, Any]]:
        normalized_codes = [str(code or "").zfill(6) for code in codes if str(code or "").strip()]
        if not normalized_codes:
            return {}

        required_points = window_size + 1
        recent_dates = [
            row[0]
            for row in (
                self.db.query(StockDaily.trade_date)
                .distinct()
                .filter(StockDaily.trade_date <= target_date)
                .order_by(StockDaily.trade_date.desc())
                .limit(required_points)
                .all()
            )
            if row and row[0]
        ]
        if not recent_dates:
            return {}

        rows = (
            self.db.query(StockDaily.code, StockDaily.trade_date, StockDaily.close)
            .filter(
                StockDaily.code.in_(normalized_codes),
                StockDaily.trade_date.in_(recent_dates),
            )
            .order_by(StockDaily.code.asc(), StockDaily.trade_date.desc())
            .all()
        )

        grouped: dict[str, list[tuple[date, float]]] = {}
        for code, trade_date, close in rows:
            bucket = grouped.setdefault(str(code).zfill(6), [])
            if len(bucket) >= required_points:
                continue
            if trade_date is None or close is None:
                continue
            bucket.append((trade_date, float(close)))

        metrics: dict[str, dict[str, Any]] = {}
        for code, points_desc in grouped.items():
            points = list(reversed(points_desc))
            recent_limit_up_days = 0
            for (_, previous_close), (_, close_price) in zip(points, points[1:]):
                if previous_close in (None, 0) or close_price is None:
                    continue
                change_pct = (close_price - previous_close) / previous_close * 100
                if change_pct >= self._limit_up_threshold(code):
                    recent_limit_up_days += 1

            recent_runup_pct = None
            if len(points) >= 2 and points[0][1] not in (None, 0):
                recent_runup_pct = (points[-1][1] - points[0][1]) / points[0][1] * 100

            metrics[code] = {
                "recent_limit_up_days": recent_limit_up_days,
                "recent_runup_pct": recent_runup_pct,
            }
        return metrics

    def _build_sector_story_context(self, items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        sector_members: dict[str, list[tuple[str, float]]] = {}
        for item in items:
            code = str(item.get("code") or "").zfill(6)
            change_pct = self._safe_float(item.get("change_pct"))
            if change_pct is None:
                continue
            for sector_name in item.get("sector_names") or []:
                sector = str(sector_name or "").strip()
                if not sector or self._is_generic_sector_name(sector):
                    continue
                sector_members.setdefault(sector, []).append((code, change_pct))

        context_by_code: dict[str, dict[str, Any]] = {}
        for item in items:
            code = str(item.get("code") or "").zfill(6)
            change_pct = self._safe_float(item.get("change_pct"))
            if change_pct is None:
                continue

            best_context: dict[str, Any] | None = None
            best_score = float("-inf")
            for sector_name in item.get("sector_names") or []:
                sector = str(sector_name or "").strip()
                peer_changes = [
                    member_change
                    for member_code, member_change in (sector_members.get(sector) or [])
                    if member_code != code
                ]
                if not peer_changes:
                    continue
                avg_change = sum(peer_changes) / len(peer_changes)
                breadth = sum(1 for value in peer_changes if value >= 2.0) / len(peer_changes)
                divergence = change_pct - avg_change
                isolated_spike = bool(
                    change_pct >= 5.0
                    and divergence >= 4.0
                    and (breadth <= 0.45 or avg_change <= 2.0)
                )
                ranking_score = divergence - breadth * 5.0 + (12.0 if isolated_spike else 0.0)
                if best_context is None or ranking_score > best_score:
                    best_score = ranking_score
                    best_context = {
                        "sector_focus_name": sector,
                        "sector_avg_change_pct": avg_change,
                        "sector_breadth": breadth,
                        "isolated_spike": isolated_spike,
                    }

            if best_context is not None:
                context_by_code[code] = best_context
        return context_by_code

    def _build_sector_story_context_by_sector_name(
        self,
        items: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        normalized_items: list[dict[str, Any]] = []
        for item in items:
            sector_names = self._resolve_sector_names(
                item.get("sector_names") if isinstance(item.get("sector_names"), list) else [],
                industry=item.get("industry"),
            )
            normalized_items.append({**item, "sector_names": sector_names})
        return self._build_sector_story_context(normalized_items)

    def _build_sector_metrics(
        self,
        *,
        sector: dict[str, Any],
        rows: list[dict[str, Any]],
        pool_count: int,
    ) -> dict[str, Any]:
        tracked_count = len(rows)
        b1_count = sum(1 for item in rows if item.get("b1_passed") is True)
        trend_start_count = sum(1 for item in rows if item.get("signal_type") == "trend_start")
        pass_count = sum(1 for item in rows if item.get("verdict") == "PASS")
        high_score_count = sum(1 for item in rows if isinstance(item.get("total_score"), (int, float)) and float(item["total_score"]) >= 5.0)
        negative_flag_count = sum(
            1
            for item in rows
            if set(item.get("negative_flags") or []) & set(self.NEGATIVE_STRENGTH_FLAGS)
        )
        active_top20_count = sum(
            1
            for item in rows
            if isinstance(item.get("active_pool_rank"), int) and item["active_pool_rank"] <= 20
        )
        active_top50_count = sum(
            1
            for item in rows
            if isinstance(item.get("active_pool_rank"), int) and item["active_pool_rank"] <= 50
        )

        scores = [float(item["total_score"]) for item in rows if isinstance(item.get("total_score"), (int, float))]
        changes = [float(item["change_pct"]) for item in rows if isinstance(item.get("change_pct"), (int, float))]
        ranks = [int(item["active_pool_rank"]) for item in rows if isinstance(item.get("active_pool_rank"), int)]

        avg_score = round(sum(scores) / len(scores), 4) if scores else None
        avg_change_pct = round(sum(changes) / len(changes), 4) if changes else None
        best_active_pool_rank = min(ranks) if ranks else None
        pool_hit_ratio = round(tracked_count / pool_count, 4) if pool_count > 0 else 0.0

        strength_score = round(
            pool_hit_ratio * 3.0
            + b1_count * 2.0
            + trend_start_count * 4.0
            + pass_count * 3.0
            + high_score_count * 1.5
            + (avg_score or 0.0) * 1.2
            + active_top20_count * 1.2
            + active_top50_count * 0.4
            + max(avg_change_pct or 0.0, 0.0) * 0.3
            - negative_flag_count * 2.0,
            4,
        )

        leaders = sorted(
            rows,
            key=lambda item: (
                self._signal_sort_priority(item.get("signal_type")),
                0 if item.get("b1_passed") is True else 1,
                self._sort_score_desc(item.get("total_score")),
                self._sort_active_pool_rank(item.get("active_pool_rank")),
                item.get("code") or "",
            ),
        )[:3]

        return {
            "sector_key": str(sector.get("key") or ""),
            "sector_name": str(sector.get("name") or ""),
            "description": str(sector.get("description") or ""),
            "policy_focus": [str(item) for item in sector.get("policyFocus") or [] if str(item).strip()],
            "focus_tracks": [str(item) for item in sector.get("focusTracks") or [] if str(item).strip()],
            "pool_count": pool_count,
            "tracked_count": tracked_count,
            "pool_hit_ratio": pool_hit_ratio,
            "b1_count": b1_count,
            "trend_start_count": trend_start_count,
            "pass_count": pass_count,
            "high_score_count": high_score_count,
            "negative_flag_count": negative_flag_count,
            "active_top20_count": active_top20_count,
            "active_top50_count": active_top50_count,
            "avg_score": avg_score,
            "avg_change_pct": avg_change_pct,
            "best_active_pool_rank": best_active_pool_rank,
            "strength_score": strength_score,
            "leaders": [
                {
                    "code": str(item.get("code") or ""),
                    "name": item.get("name"),
                    "total_score": item.get("total_score"),
                    "signal_type": item.get("signal_type"),
                    "verdict": item.get("verdict"),
                    "active_pool_rank": item.get("active_pool_rank"),
                }
                for item in leaders
            ],
        }

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
            "b1_signal_type": None,
            "comment": reason,
            "details_json": {
                "comment": reason,
                "b1_signal_type": None,
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
            selector = analysis_service._build_hybrid_b1_selector()
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

            b1_result = selector.check_b1(prepared, code)
            b1_passed = bool(b1_result.get("b1_passed", False))
            b1_signal_type = b1_result.get("b1_signal_type")
            score_result = analysis_service._quant_review_for_date(code, frame.copy(), trade_date.isoformat())
            prefilter_state: dict[str, Any] | None = None
            try:
                prefilter_state = self._get_prefilter().evaluate(
                    code=code,
                    pick_date=trade_date.isoformat(),
                    price_df=frame.copy(),
                )
            except Exception as exc:
                logger.warning("[current-hot] prefilter evaluate failed for %s %s: %s", code, trade_date, exc)
            return {
                "code": code,
                "trade_date": trade_date,
                "open_price": open_price,
                "close_price": close_price,
                "change_pct": change_pct,
                "turnover": None,
                "turnover_rate": self._safe_float(last_price_row.get("turnover_rate")),
                "volume_ratio": self._safe_float(last_price_row.get("volume_ratio")),
                "b1_passed": b1_passed,
                "kdj_j": self._safe_float(last_row.get("J")),
                "zx_long_pos": bool(last_row["zxdq"] > last_row["zxdkx"]) if pd.notna(last_row.get("zxdq")) and pd.notna(last_row.get("zxdkx")) else None,
                "weekly_ma_aligned": bool(last_row["wma_bull"]) if pd.notna(last_row.get("wma_bull")) else None,
                "volume_healthy": analysis_service._calculate_volume_health(prepared),
                "score": score_result.get("score"),
                "verdict": score_result.get("verdict"),
                "signal_type": score_result.get("signal_type"),
                "b1_signal_type": b1_signal_type,
                "comment": score_result.get("comment"),
                "details_json": {
                    "comment": score_result.get("comment"),
                    "b1_signal_type": b1_signal_type,
                    "scores": score_result.get("scores") or {},
                    "signal_reasoning": score_result.get("signal_reasoning"),
                    "trend_reasoning": score_result.get("trend_reasoning"),
                    "position_reasoning": score_result.get("position_reasoning"),
                    "volume_reasoning": score_result.get("volume_reasoning"),
                    "abnormal_move_reasoning": score_result.get("abnormal_move_reasoning"),
                    "prefilter": prefilter_state,
                    "pullback_quality": score_result.get("pullback_quality"),
                    "pullback_negative_flags": score_result.get("pullback_negative_flags") or [],
                    "pullback_has_abnormal_bear_bar": score_result.get("pullback_has_abnormal_bear_bar"),
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
        self._refresh_run_summary_counts(run)
        run.consecutive_candidate_count = int(
            self.db.query(func.count(CurrentHotCandidate.id))
            .filter(
                CurrentHotCandidate.pick_date == run.pick_date,
                CurrentHotCandidate.consecutive_days >= 2,
            )
            .scalar()
            or 0
        )

    def _refresh_run_summary_counts(self, run: CurrentHotRun) -> None:
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

    @staticmethod
    def recalculate_consecutive_metrics(db: Session, *, commit: bool = True) -> dict[str, int]:
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
        return {
            "candidate_rows": int(db.query(func.count(CurrentHotCandidate.id)).scalar() or 0),
            "run_rows": int(db.query(func.count(CurrentHotRun.id)).scalar() or 0),
            "days_with_consecutive_candidates": int(
                db.query(func.count(func.distinct(CurrentHotCandidate.pick_date)))
                .filter(CurrentHotCandidate.consecutive_days >= 2)
                .scalar()
                or 0
            ),
        }

    def generate_for_trade_date(
        self,
        trade_date: Optional[str | date] = None,
        reviewer: str = DEFAULT_REVIEWER,
        *,
        backfill_missing_history: bool = True,
        recalculate_consecutive: bool = True,
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

            if recalculate_consecutive:
                self.recalculate_consecutive_metrics(self.db, commit=False)
            run = self._get_or_create_run(target_trade_date, reviewer=reviewer, status="success")
            run.finished_at = utc_now()
            run.error_message = None
            if recalculate_consecutive:
                self._refresh_run_counts(run)
            else:
                self._refresh_run_summary_counts(run)
                run.consecutive_candidate_count = 0
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

    def load_candidates(
        self,
        pick_date: Optional[str] = None,
        limit: int = 3000,
        *,
        include_risk_regime: bool = False,
        include_risk_flags: bool = False,
    ) -> dict[str, Any]:
        target_date = self._normalize_trade_date(pick_date) or self.get_latest_pick_date()
        if target_date is None:
            return {"pick_date": None, "candidates": [], "total": 0}

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
                CurrentHotCandidate,
                CurrentHotAnalysisResult,
                Stock.name,
                Stock.industry,
                active_rank_sq.c.active_pool_rank,
            )
            .outerjoin(
                CurrentHotAnalysisResult,
                (CurrentHotAnalysisResult.pick_date == CurrentHotCandidate.pick_date)
                & (CurrentHotAnalysisResult.code == CurrentHotCandidate.code)
                & (CurrentHotAnalysisResult.reviewer == self.DEFAULT_REVIEWER),
            )
            .outerjoin(Stock, CurrentHotCandidate.code == Stock.code)
            .outerjoin(
                active_rank_sq,
                (active_rank_sq.c.trade_date == CurrentHotCandidate.pick_date)
                & (active_rank_sq.c.code == CurrentHotCandidate.code),
            )
            .filter(CurrentHotCandidate.pick_date == target_date)
            .all()
        )
        codes = [str(row.code).zfill(6) for row, *_ in rows]
        daily_basic_metrics = self._fetch_daily_basic_metrics(target_date, codes)
        financial_metrics = self._load_financial_metrics(codes)
        items: list[dict[str, Any]] = []
        item_context_by_code: dict[str, dict[str, Any]] = {}
        for row, analysis, stock_name, stock_industry, active_pool_rank in rows:
            sector_names = self._resolve_sector_names(row.sector_names_json, industry=stock_industry)
            prefilter_passed, _prefilter_summary, _prefilter_blocked_by = self._extract_prefilter_fields(
                analysis.details_json if analysis else None
            )
            pullback_negative_flags = self._normalize_pullback_negative_flags(
                analysis.details_json.get("pullback_negative_flags")
                if analysis and isinstance(analysis.details_json, dict)
                else None
            )
            item = {
                "id": row.id,
                "pick_date": target_date,
                "code": row.code,
                "name": stock_name,
                "sector_names": sector_names,
                "board_group": row.board_group,
                "open_price": row.open_price,
                "close_price": row.close_price,
                "change_pct": row.change_pct,
                "turnover": row.turnover,
                "turnover_rate": row.turnover_rate if row.turnover_rate is not None else (analysis.turnover_rate if analysis else None),
                "volume_ratio": row.volume_ratio if row.volume_ratio is not None else (analysis.volume_ratio if analysis else None),
                "active_pool_rank": int(active_pool_rank) if active_pool_rank is not None else None,
                "b1_passed": row.b1_passed if row.b1_passed is not None else (analysis.b1_passed if analysis else None),
                "kdj_j": row.kdj_j,
                "verdict": analysis.verdict if analysis else None,
                "total_score": analysis.total_score if analysis else None,
                "signal_type": analysis.signal_type if analysis else None,
                "comment": analysis.comment if analysis else None,
                "consecutive_days": int(row.consecutive_days or 1),
            }
            self._merge_market_financial_metrics(
                item,
                daily_basic_metrics=daily_basic_metrics,
                financial_metrics=financial_metrics,
            )
            items.append(item)
            item_context_by_code[item["code"]] = {
                "industry": stock_industry,
                "prefilter_passed": prefilter_passed,
                "pullback_negative_flags": pullback_negative_flags,
            }

        recent_trade_metrics = self._load_recent_trade_metrics([item["code"] for item in items], target_date)
        sector_story_context = self._build_sector_story_context(items)
        if include_risk_flags or include_risk_regime:
            risk_service = SpeculativeRiskService(self.db)
            for item in items:
                item_context = item_context_by_code.get(item["code"], {})
                recent_metrics = recent_trade_metrics.get(item["code"], {})
                sector_context = sector_story_context.get(item["code"], {})
                item["risk_flag"] = risk_service.evaluate(
                    code=item["code"],
                    name=item.get("name"),
                    industry=item_context.get("industry"),
                    sector_names=item.get("sector_names") or [],
                    change_pct=item.get("change_pct"),
                    turnover_rate=item.get("turnover_rate"),
                    volume_ratio=item.get("volume_ratio"),
                    active_pool_rank=item.get("active_pool_rank"),
                    b1_passed=item.get("b1_passed"),
                    verdict=item.get("verdict"),
                    total_score=item.get("total_score"),
                    signal_type=item.get("signal_type"),
                    prefilter_passed=item_context.get("prefilter_passed"),
                    pullback_negative_flags=item_context.get("pullback_negative_flags") or [],
                    recent_limit_up_days=recent_metrics.get("recent_limit_up_days"),
                    recent_runup_pct=recent_metrics.get("recent_runup_pct"),
                    sector_breadth=sector_context.get("sector_breadth"),
                    sector_avg_change_pct=sector_context.get("sector_avg_change_pct"),
                    isolated_spike=sector_context.get("isolated_spike"),
                    sector_focus_name=sector_context.get("sector_focus_name"),
                )
        items.sort(
            key=lambda item: (
                self._signal_sort_priority(item.get("signal_type")),
                0 if item.get("b1_passed") is True else 1,
                self._sort_score_desc(item.get("total_score")),
                self._sort_active_pool_rank(item.get("active_pool_rank")),
                item["code"],
            )
        )
        payload = {
            "pick_date": target_date,
            "candidates": items[:limit],
            "total": len(items),
        }
        if include_risk_regime:
            payload["risk_regime"] = self.build_risk_regime(target_date=target_date, items=items)
        return payload

    def get_results(
        self,
        pick_date: Optional[str] = None,
        *,
        include_risk_regime: bool = False,
        include_risk_flags: bool = False,
    ) -> dict[str, Any]:
        target_date = self._normalize_trade_date(pick_date) or self.get_latest_pick_date()
        if target_date is None:
            return {"pick_date": None, "results": [], "total": 0, "min_score_threshold": 4.0}

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
                CurrentHotAnalysisResult,
                CurrentHotCandidate,
                Stock.name,
                Stock.industry,
                active_rank_sq.c.active_pool_rank,
            )
            .outerjoin(
                CurrentHotCandidate,
                (CurrentHotCandidate.pick_date == CurrentHotAnalysisResult.pick_date)
                & (CurrentHotCandidate.code == CurrentHotAnalysisResult.code),
            )
            .outerjoin(Stock, CurrentHotAnalysisResult.code == Stock.code)
            .outerjoin(
                active_rank_sq,
                (active_rank_sq.c.trade_date == CurrentHotAnalysisResult.pick_date)
                & (active_rank_sq.c.code == CurrentHotAnalysisResult.code),
            )
            .filter(CurrentHotAnalysisResult.pick_date == target_date)
            .all()
        )
        codes = [str(result.code).zfill(6) for result, *_ in rows]
        daily_basic_metrics = self._fetch_daily_basic_metrics(target_date, codes)
        financial_metrics = self._load_financial_metrics(codes)
        items = []
        item_context_by_code: dict[str, dict[str, Any]] = {}
        for result, candidate, stock_name, stock_industry, active_pool_rank in rows:
            prefilter_passed, prefilter_summary, prefilter_blocked_by = self._extract_prefilter_fields(result.details_json)
            sector_names = self._resolve_sector_names(candidate.sector_names_json if candidate else [], industry=stock_industry)
            pullback_negative_flags = self._normalize_pullback_negative_flags(
                result.details_json.get("pullback_negative_flags")
                if isinstance(result.details_json, dict)
                else None
            )
            item = {
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
                "change_pct": candidate.change_pct if candidate else None,
                "turnover_rate": result.turnover_rate if result.turnover_rate is not None else (candidate.turnover_rate if candidate else None),
                "volume_ratio": result.volume_ratio if result.volume_ratio is not None else (candidate.volume_ratio if candidate else None),
                "active_pool_rank": int(active_pool_rank) if active_pool_rank is not None else None,
                "sector_names": sector_names,
                "board_group": candidate.board_group if candidate else self.get_board_group(result.code),
                "prefilter_passed": prefilter_passed,
                "prefilter_summary": prefilter_summary,
                "prefilter_blocked_by": prefilter_blocked_by,
                "pullback_quality": (
                    result.details_json.get("pullback_quality")
                    if isinstance(result.details_json, dict)
                    else None
                ),
                "pullback_negative_flags": pullback_negative_flags,
            }
            self._merge_market_financial_metrics(
                item,
                daily_basic_metrics=daily_basic_metrics,
                financial_metrics=financial_metrics,
            )
            items.append(item)
            item_context_by_code[item["code"]] = {
                "industry": stock_industry,
                "pullback_negative_flags": pullback_negative_flags,
                "prefilter_passed": prefilter_passed,
            }

        recent_trade_metrics = self._load_recent_trade_metrics([item["code"] for item in items], target_date)
        sector_story_context = self._build_sector_story_context(items)
        if include_risk_flags or include_risk_regime:
            risk_service = SpeculativeRiskService(self.db)
            for item in items:
                item_context = item_context_by_code.get(item["code"], {})
                recent_metrics = recent_trade_metrics.get(item["code"], {})
                sector_context = sector_story_context.get(item["code"], {})
                item["risk_flag"] = risk_service.evaluate(
                    code=item["code"],
                    name=item.get("name"),
                    industry=item_context.get("industry"),
                    sector_names=item.get("sector_names") or [],
                    change_pct=item.get("change_pct"),
                    turnover_rate=item.get("turnover_rate"),
                    volume_ratio=item.get("volume_ratio"),
                    active_pool_rank=item.get("active_pool_rank"),
                    b1_passed=item.get("b1_passed"),
                    verdict=item.get("verdict"),
                    total_score=item.get("total_score"),
                    signal_type=item.get("signal_type"),
                    prefilter_passed=item_context.get("prefilter_passed"),
                    pullback_negative_flags=item_context.get("pullback_negative_flags") or [],
                    recent_limit_up_days=recent_metrics.get("recent_limit_up_days"),
                    recent_runup_pct=recent_metrics.get("recent_runup_pct"),
                    sector_breadth=sector_context.get("sector_breadth"),
                    sector_avg_change_pct=sector_context.get("sector_avg_change_pct"),
                    isolated_spike=sector_context.get("isolated_spike"),
                    sector_focus_name=sector_context.get("sector_focus_name"),
                )
        items.sort(
            key=lambda item: (
                self._signal_sort_priority(item.get("signal_type")),
                0 if item.get("b1_passed") is True else 1,
                self._sort_score_desc(item.get("total_score")),
                self._sort_active_pool_rank(item.get("active_pool_rank")),
                item["code"],
            )
        )
        payload = {
            "pick_date": target_date,
            "results": items,
            "total": len(items),
            "min_score_threshold": 4.0,
        }
        if include_risk_regime:
            payload["risk_regime"] = self.build_risk_regime(target_date=target_date, items=items)
        return payload

    def get_sector_analysis(self, window_size: int = DEFAULT_WINDOW_SIZE, top_n: int = 5) -> dict[str, Any]:
        catalog = self._load_sector_analysis_catalog()
        sector_pool = self._load_sector_analysis_pool()
        sectors = list(catalog.get("sectors") or [])

        pool_by_sector: dict[str, list[dict[str, str]]] = {
            str(sector.get("key") or ""): list(sector_pool.get(str(sector.get("key") or ""), []))
            for sector in sectors
            if str(sector.get("key") or "").strip()
        }
        code_to_sector_keys: dict[str, set[str]] = {}
        for sector_key, items in pool_by_sector.items():
            for item in items:
                code = str(item.get("code") or "").zfill(6)
                if not code or code == "000000":
                    continue
                code_to_sector_keys.setdefault(code, set()).add(sector_key)

        sector_aliases = {
            str(sector.get("key") or ""): self._build_sector_aliases(sector)
            for sector in sectors
            if str(sector.get("key") or "").strip()
        }

        target_dates = self.get_recent_trade_dates(window_size)
        chronological_dates = list(reversed(target_dates))
        latest_date = target_dates[0] if target_dates else None
        previous_date = target_dates[1] if len(target_dates) > 1 else None

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
                    CurrentHotCandidate,
                    CurrentHotAnalysisResult,
                    Stock.name,
                    Stock.industry,
                    active_rank_sq.c.active_pool_rank,
                )
                .outerjoin(
                    CurrentHotAnalysisResult,
                    (CurrentHotAnalysisResult.pick_date == CurrentHotCandidate.pick_date)
                    & (CurrentHotAnalysisResult.code == CurrentHotCandidate.code)
                    & (CurrentHotAnalysisResult.reviewer == self.DEFAULT_REVIEWER),
                )
                .outerjoin(Stock, CurrentHotCandidate.code == Stock.code)
                .outerjoin(
                    active_rank_sq,
                    (active_rank_sq.c.trade_date == CurrentHotCandidate.pick_date)
                    & (active_rank_sq.c.code == CurrentHotCandidate.code),
                )
                .filter(CurrentHotCandidate.pick_date.in_(target_dates))
                .all()
            )

            for candidate, result, stock_name, stock_industry, active_pool_rank in rows:
                sector_names = self._resolve_sector_names(candidate.sector_names_json, industry=stock_industry)
                sector_keys = self._resolve_sector_keys_for_row(
                    candidate.code,
                    sector_names,
                    code_to_sector_keys=code_to_sector_keys,
                    sector_aliases=sector_aliases,
                )
                if not sector_keys:
                    continue

                details_json = result.details_json if result and isinstance(result.details_json, dict) else {}
                row_payload = {
                    "code": candidate.code,
                    "name": stock_name,
                    "change_pct": candidate.change_pct,
                    "total_score": result.total_score if result else None,
                    "signal_type": result.signal_type if result else None,
                    "verdict": result.verdict if result else None,
                    "b1_passed": candidate.b1_passed if candidate.b1_passed is not None else (result.b1_passed if result else None),
                    "active_pool_rank": int(active_pool_rank) if active_pool_rank is not None else None,
                    "negative_flags": self._normalize_pullback_negative_flags(details_json.get("pullback_negative_flags")),
                }
                pick_date_text = candidate.pick_date.isoformat()
                if pick_date_text not in date_sector_rows:
                    continue
                for sector_key in sector_keys:
                    if sector_key in date_sector_rows[pick_date_text]:
                        date_sector_rows[pick_date_text][sector_key].append(row_payload)

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
                metrics = self._build_sector_metrics(
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
                        **self._build_sector_metrics(
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
        top_sector_keys = [str(item.get("sector_key") or "") for item in latest_sectors[:top_count] if str(item.get("sector_key") or "").strip()]

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

    def build_risk_regime(
        self,
        *,
        target_date: date,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        del items
        market_items = self._load_market_risk_sample(target_date)
        previous_date = (
            self.db.query(StockDaily.trade_date)
            .filter(StockDaily.trade_date < target_date)
            .order_by(StockDaily.trade_date.desc())
            .limit(1)
            .scalar()
        )
        previous_items: list[dict[str, Any]] = self._load_market_risk_sample(previous_date) if previous_date else []

        regime = RiskRegimeService().evaluate(items=market_items, previous_items=previous_items)
        ai_review = RiskRegimeAIService(self.db).confirm_market_regime(
            pick_date=target_date,
            items=market_items,
            base_regime=regime,
        )
        regime["ai_review"] = ai_review
        if ai_review and isinstance(ai_review.get("result"), dict):
            ai_result = ai_review["result"]
            regime["ai_confirmed_level"] = ai_result.get("confirmed_level")
            regime["ai_confidence"] = ai_result.get("confidence")
            regime["ai_stance"] = ai_result.get("stance")
            regime["ai_evidence_strength"] = ai_result.get("evidence_strength")
            if str(ai_result.get("summary") or "").strip():
                regime["summary"] = str(ai_result.get("summary")).strip()
        return regime

    def _load_market_risk_sample(self, trade_date: Optional[date], *, top_m: int = 200, lookback_window: int = 5) -> list[dict[str, Any]]:
        if trade_date is None:
            return []

        rank_rows = (
            self.db.query(
                StockActivePoolRank.code,
                StockActivePoolRank.active_pool_rank,
                Stock.name,
                Stock.industry,
            )
            .outerjoin(Stock, Stock.code == StockActivePoolRank.code)
            .filter(
                StockActivePoolRank.trade_date == trade_date,
                StockActivePoolRank.top_m == 3000,
                StockActivePoolRank.n_turnover_days == 43,
                StockActivePoolRank.active_pool_rank <= top_m,
            )
            .order_by(StockActivePoolRank.active_pool_rank.asc(), StockActivePoolRank.code.asc())
            .all()
        )
        if not rank_rows:
            return []

        codes = [str(code).zfill(6) for code, *_ in rank_rows]
        rank_map = {str(code).zfill(6): int(active_pool_rank) for code, active_pool_rank, *_ in rank_rows}
        stock_meta = {
            str(code).zfill(6): {
                "name": name,
                "industry": industry,
            }
            for code, _rank, name, industry in rank_rows
        }

        previous_trade_date = (
            self.db.query(StockDaily.trade_date)
            .filter(StockDaily.trade_date < trade_date)
            .order_by(StockDaily.trade_date.desc())
            .limit(1)
            .scalar()
        )

        b1_rows = (
            self.db.query(
                DailyB1Check,
                DailyB1CheckDetail,
            )
            .outerjoin(
                DailyB1CheckDetail,
                (DailyB1CheckDetail.code == DailyB1Check.code)
                & (DailyB1CheckDetail.check_date == DailyB1Check.check_date),
            )
            .filter(
                DailyB1Check.check_date == trade_date,
                DailyB1Check.code.in_(codes),
            )
            .all()
        )
        b1_map = {
            str(check.code).zfill(6): (check, detail)
            for check, detail in b1_rows
        }

        daily_rows = (
            self.db.query(
                StockDaily.code,
                StockDaily.trade_date,
                StockDaily.open,
                StockDaily.close,
                StockDaily.turnover_rate,
                StockDaily.volume_ratio,
            )
            .filter(
                StockDaily.trade_date == trade_date,
                StockDaily.code.in_(codes),
            )
            .all()
        )
        daily_map = {
            str(code).zfill(6): {
                "trade_date": trade_date_value,
                "open_price": self._safe_float(open_price),
                "close_price": self._safe_float(close_price),
                "turnover_rate": self._safe_float(turnover_rate),
                "volume_ratio": self._safe_float(volume_ratio),
            }
            for code, trade_date_value, open_price, close_price, turnover_rate, volume_ratio in daily_rows
        }

        previous_close_map: dict[str, float] = {}
        if previous_trade_date is not None:
            previous_daily_rows = (
                self.db.query(StockDaily.code, StockDaily.close)
                .filter(
                    StockDaily.trade_date == previous_trade_date,
                    StockDaily.code.in_(codes),
                )
                .all()
            )
            previous_close_map = {
                str(code).zfill(6): float(close_price)
                for code, close_price in previous_daily_rows
                if close_price is not None
            }

        recent_trade_metrics = self._load_recent_trade_metrics(codes, trade_date, window_size=lookback_window)
        sample_items: list[dict[str, Any]] = []
        for code in codes:
            stock_info = stock_meta.get(code, {})
            check_pair = b1_map.get(code)
            daily_info = daily_map.get(code, {})
            check = check_pair[0] if check_pair else None
            detail = check_pair[1] if check_pair else None
            detail_rules = detail.rules_json if detail and isinstance(detail.rules_json, dict) else {}
            detail_score = detail.score_details_json if detail and isinstance(detail.score_details_json, dict) else {}
            detail_details = detail.details_json if detail and isinstance(detail.details_json, dict) else {}
            close_price = daily_info.get("close_price")
            previous_close = previous_close_map.get(code)
            change_pct = self._safe_float(getattr(check, "change_pct", None))
            if change_pct is None and previous_close not in (None, 0) and close_price is not None:
                change_pct = (close_price - previous_close) / previous_close * 100

            item = {
                "code": code,
                "name": stock_info.get("name"),
                "industry": stock_info.get("industry"),
                "sector_names": [str(stock_info.get("industry")).strip()] if str(stock_info.get("industry") or "").strip() else [],
                "change_pct": change_pct if change_pct is not None else getattr(check, "change_pct", None),
                "turnover_rate": getattr(check, "turnover_rate", None) if check and getattr(check, "turnover_rate", None) is not None else daily_info.get("turnover_rate"),
                "volume_ratio": getattr(check, "volume_ratio", None) if check and getattr(check, "volume_ratio", None) is not None else daily_info.get("volume_ratio"),
                "active_pool_rank": rank_map.get(code),
                "b1_passed": getattr(check, "b1_passed", None),
                "signal_type": detail_score.get("signal_type"),
                "verdict": detail_score.get("verdict"),
                "total_score": getattr(check, "score", None),
                "prefilter_passed": detail_rules.get("prefilter_passed"),
                "pullback_negative_flags": detail_details.get("pullback_negative_flags") or [],
            }
            sample_items.append(item)

        sector_story_context = self._build_sector_story_context_by_sector_name(sample_items)
        risk_service = SpeculativeRiskService(self.db)
        for item in sample_items:
            code = str(item.get("code") or "").zfill(6)
            item["risk_flag"] = risk_service.evaluate(
                code=code,
                name=item.get("name"),
                industry=item.get("industry"),
                sector_names=item.get("sector_names") or [],
                change_pct=item.get("change_pct"),
                turnover_rate=item.get("turnover_rate"),
                volume_ratio=item.get("volume_ratio"),
                active_pool_rank=item.get("active_pool_rank"),
                b1_passed=item.get("b1_passed"),
                verdict=item.get("verdict"),
                total_score=item.get("total_score"),
                signal_type=item.get("signal_type"),
                prefilter_passed=item.get("prefilter_passed"),
                pullback_negative_flags=item.get("pullback_negative_flags") or [],
                recent_limit_up_days=recent_trade_metrics.get(code, {}).get("recent_limit_up_days"),
                recent_runup_pct=recent_trade_metrics.get(code, {}).get("recent_runup_pct"),
                sector_breadth=sector_story_context.get(code, {}).get("sector_breadth"),
                sector_avg_change_pct=sector_story_context.get(code, {}).get("sector_avg_change_pct"),
                isolated_spike=sector_story_context.get(code, {}).get("isolated_spike"),
                sector_focus_name=sector_story_context.get(code, {}).get("sector_focus_name"),
            )
        return sample_items

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
        if target_dates:
            logger.info(
                "[current-hot] window rebuild start: window_size=%s total_dates=%s force=%s backfill_missing_history=%s",
                window_size,
                len(target_dates),
                force,
                backfill_missing_history,
            )
        for index, pick_date in enumerate(target_dates, start=1):
            pick_date_text = pick_date.isoformat()
            item = status_map.get(pick_date_text)
            if not force and item and item.get("status") == "success":
                logger.info(
                    "[current-hot] skip %s (%s/%s) already success",
                    pick_date_text,
                    index,
                    len(target_dates),
                )
                continue

            logger.info(
                "[current-hot] rebuilding %s (%s/%s)",
                pick_date_text,
                index,
                len(target_dates),
            )
            result = self.generate_for_trade_date(
                pick_date,
                reviewer=reviewer,
                backfill_missing_history=backfill_missing_history,
                recalculate_consecutive=False,
            )
            if result.get("status") == "ok":
                rebuilt_dates.append(pick_date_text)
                logger.info(
                    "[current-hot] rebuilt %s generated=%s skipped=%s",
                    pick_date_text,
                    result.get("generated_count", 0),
                    result.get("skipped_count", 0),
                )
            else:
                failed_dates.append(pick_date_text)
                logger.warning(
                    "[current-hot] rebuild failed %s: %s",
                    pick_date_text,
                    result.get("message"),
                )

        if rebuilt_dates:
            logger.info("[current-hot] recalculating consecutive metrics once for %s rebuilt dates", len(rebuilt_dates))
            self.recalculate_consecutive_metrics(self.db, commit=False)
        prune_result = self.prune_window(window_size)
        return {
            "window_size": window_size,
            "target_dates": [value.isoformat() for value in reversed(target_dates)],
            "rebuilt_dates": rebuilt_dates,
            "failed_dates": failed_dates,
            "pruned_dates": prune_result.get("deleted_dates", []),
            "summary": self.get_dates(window_size),
        }
