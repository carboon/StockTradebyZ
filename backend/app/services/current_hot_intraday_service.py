"""
Current hot intraday snapshot service.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import logging
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session

from app.models import CurrentHotIntradaySnapshot, DailyB1Check, DailyB1CheckDetail, Stock
from app.services.analysis_service import analysis_service
from app.services.current_hot_service import CurrentHotService
from app.services.exit_plan_service import ExitPlanService
from app.services.intraday_analysis_service import IntradayAnalysisService
from app.services.tushare_service import TushareService


ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


@dataclass
class CurrentHotIntradayStatus:
    trade_date: date
    source_pick_date: Optional[date]
    snapshot_time: Optional[datetime]
    window_open: bool
    has_data: bool
    status: str
    message: Optional[str]


class CurrentHotIntradayAnalysisService:
    """当前热盘中盘分析服务。"""

    WINDOW_START = time(11, 30)
    WINDOW_END = time(15, 0)
    MIDDAY_CUTOFF = "11:30:00"

    def __init__(self, db: Session):
        self.db = db
        self.tushare_service = TushareService()
        self.current_hot_service = CurrentHotService(db)
        self.exit_plan_service = ExitPlanService()

    def now_shanghai(self) -> datetime:
        return datetime.now(ASIA_SHANGHAI)

    def is_window_open(self, now: Optional[datetime] = None) -> bool:
        current = now or self.now_shanghai()
        current_time = current.timetz().replace(tzinfo=None)
        return self.WINDOW_START <= current_time <= self.WINDOW_END

    def get_trade_date(self, now: Optional[datetime] = None) -> date:
        current = now or self.now_shanghai()
        return current.date()

    def _with_suffix(self, code: str) -> str:
        normalized = str(code or "").strip().upper()
        if "." in normalized:
            return normalized
        return f"{normalized.zfill(6)}.{CurrentHotService.get_market(normalized)}"

    @staticmethod
    def _sort_score_desc(value: Optional[float]) -> float:
        return -(value if value is not None else -9999.0)

    def _get_snapshot_rows(self, trade_date: date) -> list[CurrentHotIntradaySnapshot]:
        rows = (
            self.db.query(CurrentHotIntradaySnapshot)
            .filter(CurrentHotIntradaySnapshot.trade_date == trade_date)
            .all()
        )
        return sorted(
            rows,
            key=lambda row: (
                0 if row.b1_passed is True else 1,
                self._sort_score_desc(row.score),
                row.code,
            ),
        )

    def _get_latest_snapshot_time(self, trade_date: date) -> Optional[datetime]:
        return (
            self.db.query(CurrentHotIntradaySnapshot.snapshot_time)
            .filter(CurrentHotIntradaySnapshot.trade_date == trade_date)
            .order_by(CurrentHotIntradaySnapshot.snapshot_time.desc(), CurrentHotIntradaySnapshot.id.desc())
            .limit(1)
            .scalar()
        )

    def get_status(self, *, trade_date: Optional[date] = None, is_admin: bool = False) -> CurrentHotIntradayStatus:
        target_trade_date = trade_date or self.get_trade_date()
        snapshot_time = self._get_latest_snapshot_time(target_trade_date)
        window_open = self.is_window_open()
        has_data = snapshot_time is not None

        if has_data:
            status = "ok"
            message = None
        elif is_admin:
            status = "not_generated"
            message = "尚未生成当前热盘中盘分析快照"
        elif not window_open:
            status = "window_closed"
            message = "普通用户仅可在 11:30-15:00 查看当前热盘中盘分析"
        else:
            status = "not_ready"
            message = "今日当前热盘中盘分析快照尚未生成"

        return CurrentHotIntradayStatus(
            trade_date=target_trade_date,
            source_pick_date=target_trade_date,
            snapshot_time=snapshot_time,
            window_open=window_open,
            has_data=has_data,
            status=status,
            message=message,
        )

    def _fetch_realtime_quotes(self, codes: list[str]) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame()
        return self._fetch_realtime_quotes_by_ts_codes([self._with_suffix(code) for code in codes])

    def _fetch_realtime_quotes_by_ts_codes(self, ts_codes: list[str]) -> pd.DataFrame:
        normalized_ts_codes: list[str] = []
        seen: set[str] = set()
        for ts_code in ts_codes:
            normalized_ts_code = str(ts_code or "").strip().upper()
            if not normalized_ts_code or normalized_ts_code in seen:
                continue
            normalized_ts_codes.append(normalized_ts_code)
            seen.add(normalized_ts_code)
        if not normalized_ts_codes:
            return pd.DataFrame()

        try:
            df = self.tushare_service.pro.rt_k(ts_code=",".join(normalized_ts_codes))
        except TypeError:
            try:
                df = self.tushare_service.pro.rt_k(ts_code=normalized_ts_codes)
            except Exception:
                logger.warning("获取当前热盘实时行情失败: %s", ",".join(normalized_ts_codes), exc_info=True)
                return pd.DataFrame()
        except Exception:
            logger.warning("获取当前热盘实时行情失败: %s", ",".join(normalized_ts_codes), exc_info=True)
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        normalized = df.copy()
        normalized.columns = [str(col).lower() for col in normalized.columns]
        if "ts_code" not in normalized.columns:
            return pd.DataFrame()
        normalized["ts_code"] = normalized["ts_code"].astype(str).str.upper()
        normalized["normalized_ts_code"] = normalized["ts_code"]
        normalized["code"] = normalized["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
        return normalized

    def _fetch_minute_quotes(self, codes: list[str], *, trade_date: Optional[date] = None) -> pd.DataFrame:
        return IntradayAnalysisService(self.db)._fetch_minute_quotes(
            codes,
            trade_date=trade_date or self.get_trade_date(),
        )

    @staticmethod
    def _normalize_time_text(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if " " in text:
            text = text.split(" ")[-1]
        if len(text) == 5:
            return f"{text}:00"
        return text

    def _extract_midday_price(self, minute_df: pd.DataFrame, code: str) -> tuple[Optional[float], Optional[str]]:
        if minute_df is None or minute_df.empty:
            return None, None
        subset = minute_df[minute_df["code"].astype(str).str.zfill(6) == str(code).zfill(6)].copy()
        if subset.empty:
            return None, None
        time_column = next((col for col in ("trade_time", "time") if col in subset.columns), None)
        price_column = "close" if "close" in subset.columns else ("price" if "price" in subset.columns else None)
        if time_column is None or price_column is None:
            return None, None
        subset["_normalized_time"] = subset[time_column].map(self._normalize_time_text)
        exact = subset[subset["_normalized_time"] == self.MIDDAY_CUTOFF]
        row = exact.iloc[-1] if not exact.empty else subset.iloc[-1]
        return self._to_float(row.get(price_column)), row.get("_normalized_time")

    def _get_previous_analysis(self, code: str, trade_date: date) -> dict[str, Any]:
        row = (
            self.db.query(DailyB1Check, DailyB1CheckDetail)
            .outerjoin(
                DailyB1CheckDetail,
                (DailyB1CheckDetail.code == DailyB1Check.code)
                & (DailyB1CheckDetail.check_date == DailyB1Check.check_date),
            )
            .filter(DailyB1Check.code == code, DailyB1Check.check_date == trade_date)
            .first()
        )
        b1_check = row[0] if row else None
        detail = row[1] if row else None
        score_details = detail.score_details_json if detail and isinstance(detail.score_details_json, dict) else {}
        fallback_metrics = IntradayAnalysisService(self.db)._get_market_metric_fallback(code, trade_date)
        return {
            "pick_date": trade_date.isoformat(),
            "verdict": score_details.get("verdict"),
            "score": b1_check.score if b1_check else None,
            "signal_type": score_details.get("signal_type"),
            "comment": score_details.get("comment"),
            "b1_passed": b1_check.b1_passed if b1_check else None,
            "active_pool_rank": (
                b1_check.active_pool_rank
                if b1_check and b1_check.active_pool_rank is not None
                else fallback_metrics.get("active_pool_rank")
            ),
            "turnover_rate": (
                b1_check.turnover_rate
                if b1_check and b1_check.turnover_rate is not None
                else fallback_metrics.get("turnover_rate")
            ),
            "volume_ratio": (
                b1_check.volume_ratio
                if b1_check and b1_check.volume_ratio is not None
                else fallback_metrics.get("volume_ratio")
            ),
        }

    def _build_pool_metric_map(self, trade_date: date) -> dict[str, dict[str, Any]]:
        payload = self.current_hot_service.get_results(trade_date.isoformat())
        return {
            str(item.get("code", "")).zfill(6): item
            for item in payload.get("results", [])
            if item.get("code")
        }

    def _build_relative_market_status(
        self,
        *,
        latest_change_pct: Optional[float],
        benchmark_change_pct: Optional[float],
        market_bias: Optional[str],
    ) -> tuple[Optional[str], Optional[float], Optional[str]]:
        return IntradayAnalysisService(self.db)._build_relative_market_status(
            latest_change_pct=latest_change_pct,
            benchmark_change_pct=benchmark_change_pct,
            market_bias=market_bias,
        )

    def _build_manager_note(
        self,
        *,
        previous_analysis: dict[str, Any],
        exit_plan: dict[str, Any],
        relative_market_status: Optional[str],
        market_bias: Optional[str],
    ) -> str:
        previous_verdict = previous_analysis.get("verdict") or "未知"
        previous_signal = previous_analysis.get("signal_type") or "未知信号"
        action_label = exit_plan.get("action_label") or "执行风控"
        reason = str(exit_plan.get("reason") or "").strip()
        relative_text = relative_market_status or "强弱未明"
        market_text = market_bias or "中性"
        return f"当前热盘基础复核为{previous_verdict}/{previous_signal}；相对大盘{relative_text}，大盘环境{market_text}。资金管理上优先“{action_label}”，{reason or '先守结构线，再看是否继续强化。'}"

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _normalize_intraday_volume(self, history_df: pd.DataFrame, quote_row: pd.Series) -> Optional[float]:
        """Normalize Tushare rt_k volume before appending the temporary intraday candle."""
        volume = self._to_float(quote_row.get("vol"))
        if volume is None or history_df is None or history_df.empty or "volume" not in history_df.columns:
            return volume
        avg20 = pd.to_numeric(history_df["volume"], errors="coerce").dropna().tail(20).mean()
        if pd.notna(avg20) and avg20 > 0 and volume > avg20 * 20:
            return volume / 100.0
        return volume

    def _build_snapshot_frame(
        self,
        *,
        history_df: pd.DataFrame,
        trade_date: date,
        quote_row: pd.Series,
    ) -> pd.DataFrame:
        df = history_df.copy()
        if df.empty:
            return df

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

        snapshot_df = pd.DataFrame(
            [
                {
                    "date": pd.Timestamp(trade_date),
                    "open": self._to_float(quote_row.get("open")),
                    "close": self._to_float(quote_row.get("close")),
                    "high": self._to_float(quote_row.get("high")),
                    "low": self._to_float(quote_row.get("low")),
                    "volume": self._normalize_intraday_volume(history_df, quote_row),
                }
            ]
        )
        merged = pd.concat([df, snapshot_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=["date"], keep="last")
        merged = merged.sort_values("date").reset_index(drop=True)
        return merged

    def _compute_snapshot(
        self,
        *,
        code: str,
        trade_date: date,
        sector_names: list[str],
        board_group: str,
        quote_row: pd.Series,
        minute_df: pd.DataFrame,
        snapshot_time: datetime,
        market_overview: dict[str, Any],
        pool_metric_map: dict[str, dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        history_df = self.current_hot_service.load_stock_frame(code, trade_date, days=365)
        if history_df is None or history_df.empty:
            return None

        frame = self._build_snapshot_frame(history_df=history_df, trade_date=trade_date, quote_row=quote_row)
        if frame.empty or len(frame) < 60:
            return None

        selector = analysis_service._build_b1_selector()
        prepared = selector.prepare_df(frame.copy())
        if prepared.empty:
            return None

        last_row = prepared.iloc[-1]
        score_result = analysis_service._quant_review_for_date(code, frame.copy(), trade_date.isoformat())
        close_price = self._to_float(quote_row.get("close"))
        midday_price, midday_time = self._extract_midday_price(minute_df, code)
        prev_close = self._to_float(frame.iloc[-2]["close"]) if len(frame) >= 2 else None
        change_pct = None
        if close_price is not None and prev_close not in (None, 0):
            change_pct = (close_price - prev_close) / prev_close * 100
        midday_change_pct = None
        if midday_price is not None and prev_close not in (None, 0):
            midday_change_pct = (midday_price - prev_close) / prev_close * 100
        exit_plan = self.exit_plan_service.build_exit_plan(
            code=code,
            history_df=frame,
            entry_price=None,
            current_price=close_price,
            entry_date=trade_date,
            verdict=score_result.get("verdict"),
            signal_type=score_result.get("signal_type"),
            is_intraday=True,
        )
        previous_analysis = self._get_previous_analysis(code, trade_date)
        pool_item = pool_metric_map.get(str(code).zfill(6))
        benchmark_change_pct = market_overview.get("benchmark_change_pct")
        relative_market_status, relative_market_strength_pct, benchmark_note = self._build_relative_market_status(
            latest_change_pct=change_pct,
            benchmark_change_pct=benchmark_change_pct,
            market_bias=market_overview.get("market_bias"),
        )
        manager_note = self._build_manager_note(
            previous_analysis=previous_analysis,
            exit_plan=exit_plan,
            relative_market_status=relative_market_status,
            market_bias=market_overview.get("market_bias"),
        )
        pool_turnover_rate = self._to_float(pool_item.get("turnover_rate")) if pool_item else None
        pool_volume_ratio = self._to_float(pool_item.get("volume_ratio")) if pool_item else None
        pool_active_pool_rank = pool_item.get("active_pool_rank") if pool_item else None
        turnover_rate = pool_turnover_rate if pool_turnover_rate is not None else previous_analysis.get("turnover_rate")
        volume_ratio = pool_volume_ratio if pool_volume_ratio is not None else previous_analysis.get("volume_ratio")
        active_pool_rank = pool_active_pool_rank if pool_active_pool_rank is not None else previous_analysis.get("active_pool_rank")

        return {
            "trade_date": trade_date,
            "code": code,
            "source_pick_date": trade_date,
            "snapshot_time": snapshot_time,
            "sector_names_json": sector_names,
            "board_group": board_group,
            "open_price": self._to_float(quote_row.get("open")),
            "close_price": close_price,
            "high_price": self._to_float(quote_row.get("high")),
            "low_price": self._to_float(quote_row.get("low")),
            "volume": self._normalize_intraday_volume(history_df, quote_row),
            "amount": self._to_float(quote_row.get("amount")),
            "change_pct": midday_change_pct if midday_change_pct is not None else change_pct,
            "turnover": None,
            "turnover_rate": turnover_rate,
            "volume_ratio": volume_ratio,
            "active_pool_rank": active_pool_rank,
            "b1_passed": bool(last_row["_vec_pick"]) if pd.notna(last_row.get("_vec_pick")) else False,
            "score": score_result.get("score"),
            "verdict": score_result.get("verdict"),
            "signal_type": score_result.get("signal_type"),
            "kdj_j": self._to_float(last_row.get("J")),
            "zx_long_pos": bool(last_row["zxdq"] > last_row["zxdkx"]) if pd.notna(last_row.get("zxdq")) and pd.notna(last_row.get("zxdkx")) else None,
            "weekly_ma_aligned": bool(last_row["wma_bull"]) if pd.notna(last_row.get("wma_bull")) else None,
            "volume_healthy": analysis_service._calculate_volume_health(prepared),
            "details_json": {
                "comment": score_result.get("comment"),
                "signal_reasoning": score_result.get("signal_reasoning"),
                "scores": score_result.get("scores") or {},
                "trend_reasoning": score_result.get("trend_reasoning"),
                "position_reasoning": score_result.get("position_reasoning"),
                "volume_reasoning": score_result.get("volume_reasoning"),
                "abnormal_move_reasoning": score_result.get("abnormal_move_reasoning"),
                "quote_trade_time": quote_row.get("trade_time"),
                "midday_price": midday_price,
                "latest_price": close_price,
                "latest_change_pct": change_pct,
                "midday_time": midday_time,
                "analysis_basis": "基于当前热盘池 + 当日11:30分时快照 + 当前实时价综合判断",
                "previous_analysis": previous_analysis,
                "turnover_rate": turnover_rate,
                "volume_ratio": volume_ratio,
                "active_pool_rank": active_pool_rank,
                "benchmark_name": market_overview.get("benchmark_name"),
                "benchmark_change_pct": benchmark_change_pct,
                "relative_market_status": relative_market_status,
                "relative_market_strength_pct": relative_market_strength_pct,
                "manager_note": manager_note if benchmark_note is None else f"{manager_note} {benchmark_note}",
                "market_overview": market_overview,
                "exit_plan": exit_plan,
            },
        }

    def generate_snapshot(
        self,
        *,
        trade_date: Optional[date] = None,
        cutoff_time_text: Optional[str] = None,
    ) -> dict[str, Any]:
        target_trade_date = trade_date or self.get_trade_date()
        entries = self.current_hot_service.get_pool_entries()
        if not entries:
            return {
                "trade_date": target_trade_date,
                "source_pick_date": target_trade_date,
                "snapshot_time": None,
                "status": "empty_pool",
                "message": "当前热盘配置为空",
                "generated_count": 0,
                "skipped_count": 0,
                "has_data": False,
                "window_open": self.is_window_open(),
            }

        self.current_hot_service._ensure_stocks_exist(entries)
        code_list = [entry.code for entry in entries]
        minute_df = self._fetch_minute_quotes(code_list, trade_date=target_trade_date)
        intraday_service = IntradayAnalysisService(self.db)
        minute_df = intraday_service._filter_minute_df_by_cutoff(
            minute_df,
            cutoff_time_text=cutoff_time_text,
        )
        quotes = intraday_service._build_realtime_quotes_from_minute_df(minute_df)
        if quotes.empty and cutoff_time_text is None:
            quotes = self._fetch_realtime_quotes(code_list)
        stock_quotes = quotes
        if stock_quotes.empty:
            return {
                "trade_date": target_trade_date,
                "source_pick_date": target_trade_date,
                "snapshot_time": None,
                "status": "fetch_failed",
                "message": "实时行情抓取失败或无返回数据",
                "generated_count": 0,
                "skipped_count": len(code_list),
                "has_data": False,
                "window_open": self.is_window_open(),
            }
        market_overview = intraday_service._fetch_market_overview(
            target_trade_date,
            realtime_quotes=stock_quotes,
            cutoff_time_text=cutoff_time_text,
        )

        quote_map = {
            str(row["normalized_ts_code"]).strip().upper(): row
            for _, row in stock_quotes.iterrows()
        }
        pool_metric_map = self._build_pool_metric_map(target_trade_date)
        snapshot_time = self.now_shanghai()
        generated_count = 0
        skipped_count = 0

        self.db.query(CurrentHotIntradaySnapshot).filter(
            CurrentHotIntradaySnapshot.trade_date == target_trade_date
        ).delete(synchronize_session=False)

        for entry in entries:
            quote_row = quote_map.get(self._with_suffix(entry.code).upper())
            if quote_row is None:
                skipped_count += 1
                continue

            payload = self._compute_snapshot(
                code=entry.code,
                trade_date=target_trade_date,
                sector_names=entry.sector_names,
                board_group=entry.board_group,
                quote_row=quote_row,
                minute_df=minute_df,
                snapshot_time=snapshot_time,
                market_overview=market_overview,
                pool_metric_map=pool_metric_map,
            )
            if payload is None:
                skipped_count += 1
                continue

            row = (
                self.db.query(CurrentHotIntradaySnapshot)
                .filter(
                    CurrentHotIntradaySnapshot.trade_date == target_trade_date,
                    CurrentHotIntradaySnapshot.code == entry.code,
                )
                .first()
            )
            if row is None:
                row = CurrentHotIntradaySnapshot(
                    trade_date=target_trade_date,
                    code=entry.code,
                    source_pick_date=target_trade_date,
                    snapshot_time=snapshot_time,
                )
                self.db.add(row)
            for key, value in payload.items():
                setattr(row, key, value)
            generated_count += 1

        self.db.commit()
        latest_snapshot_time = self._get_latest_snapshot_time(target_trade_date)
        return {
            "trade_date": target_trade_date,
            "source_pick_date": target_trade_date,
            "snapshot_time": latest_snapshot_time,
            "status": "ok" if generated_count > 0 else "empty",
            "message": None if generated_count > 0 else "未生成任何当前热盘中盘分析快照",
            "market_overview": market_overview,
            "generated_count": generated_count,
            "skipped_count": skipped_count,
            "has_data": generated_count > 0,
            "window_open": self.is_window_open(),
        }

    def get_snapshot_payload(self, *, trade_date: Optional[date] = None, is_admin: bool = False) -> dict[str, Any]:
        status = self.get_status(trade_date=trade_date, is_admin=is_admin)
        if not is_admin and not status.has_data:
            return {
                "trade_date": status.trade_date,
                "source_pick_date": status.source_pick_date,
                "snapshot_time": status.snapshot_time,
                "window_open": status.window_open,
                "has_data": status.has_data,
                "status": status.status,
                "message": status.message,
                "items": [],
                "total": 0,
            }

        rows = self._get_snapshot_rows(status.trade_date) if status.has_data else []
        stock_names = {
            code: name
            for code, name in self.db.query(Stock.code, Stock.name)
            .filter(Stock.code.in_([item.code for item in rows]))
            .all()
        } if rows else {}

        items = [
            {
                "id": row.id,
                "trade_date": row.trade_date,
                "code": row.code,
                "name": stock_names.get(row.code),
                "source_pick_date": row.source_pick_date,
                "snapshot_time": row.snapshot_time,
                "sector_names": row.sector_names_json or [],
                "board_group": row.board_group,
                "open_price": row.open_price,
                "midday_price": (row.details_json or {}).get("midday_price"),
                "close_price": row.close_price,
                "latest_price": (row.details_json or {}).get("latest_price", row.close_price),
                "high_price": row.high_price,
                "low_price": row.low_price,
                "volume": row.volume,
                "amount": row.amount,
                "change_pct": row.change_pct,
                "latest_change_pct": (row.details_json or {}).get("latest_change_pct", row.change_pct),
                "turnover": row.turnover,
                "turnover_rate": (row.details_json or {}).get("turnover_rate"),
                "volume_ratio": (row.details_json or {}).get("volume_ratio"),
                "active_pool_rank": (row.details_json or {}).get("active_pool_rank"),
                "b1_passed": row.b1_passed,
                "score": row.score,
                "verdict": row.verdict,
                "signal_type": row.signal_type,
                "kdj_j": row.kdj_j,
                "zx_long_pos": row.zx_long_pos,
                "weekly_ma_aligned": row.weekly_ma_aligned,
                "volume_healthy": row.volume_healthy,
                "midday_time": (row.details_json or {}).get("midday_time"),
                "analysis_basis": (row.details_json or {}).get("analysis_basis"),
                "previous_analysis": (row.details_json or {}).get("previous_analysis"),
                "benchmark_name": (row.details_json or {}).get("benchmark_name"),
                "benchmark_change_pct": (row.details_json or {}).get("benchmark_change_pct"),
                "relative_market_status": (row.details_json or {}).get("relative_market_status"),
                "relative_market_strength_pct": (row.details_json or {}).get("relative_market_strength_pct"),
                "manager_note": (row.details_json or {}).get("manager_note"),
                "exit_plan": (row.details_json or {}).get("exit_plan"),
            }
            for row in rows
        ]

        return {
            "trade_date": status.trade_date,
            "source_pick_date": status.source_pick_date,
            "snapshot_time": status.snapshot_time,
            "window_open": status.window_open,
            "has_data": status.has_data,
            "status": status.status,
            "message": status.message,
            "market_overview": IntradayAnalysisService._extract_market_overview_from_rows(rows),
            "items": items,
            "total": len(items),
        }

    def prefetch_snapshot_data(self, *, trade_date: Optional[date] = None) -> dict[str, Any]:
        target_trade_date = trade_date or self.get_trade_date()
        snapshot_time = self._get_latest_snapshot_time(target_trade_date)
        has_data = snapshot_time is not None
        entries = self.current_hot_service.get_pool_entries()
        if not entries:
            return {
                "trade_date": target_trade_date,
                "source_pick_date": target_trade_date,
                "snapshot_time": snapshot_time,
                "window_open": self.is_window_open(),
                "has_data": has_data,
                "status": "empty_pool",
                "message": "当前热盘配置为空，无法预下载中盘分时数据",
                "requested_count": 0,
                "ready_count": 0,
                "missing_count": 0,
                "midday_ready_count": 0,
                "cached_count": 0,
                "downloaded_count": 0,
            }

        payload = IntradayAnalysisService(self.db)._prefetch_intraday_raw_data(
            trade_date=target_trade_date,
            codes=[entry.code for entry in entries],
            include_market_benchmarks=True,
        )
        payload["source_pick_date"] = target_trade_date
        payload["snapshot_time"] = snapshot_time
        payload["has_data"] = has_data
        payload["window_open"] = self.is_window_open()
        return payload
