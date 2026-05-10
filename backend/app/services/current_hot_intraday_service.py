"""
Current hot intraday snapshot service.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session

from app.models import CurrentHotIntradaySnapshot, Stock
from app.services.analysis_service import analysis_service
from app.services.current_hot_service import CurrentHotService
from app.services.exit_plan_service import ExitPlanService
from app.services.tushare_service import TushareService


ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")


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

    WINDOW_START = time(12, 0)
    WINDOW_END = time(15, 0)

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
            message = "普通用户仅可在 12:00-15:00 查看当前热盘中盘分析"
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

        ts_codes = [self._with_suffix(code) for code in codes]
        try:
            df = self.tushare_service.pro.rt_k(ts_code=",".join(ts_codes))
        except TypeError:
            df = self.tushare_service.pro.rt_k(ts_code=ts_codes)

        if df is None or df.empty:
            return pd.DataFrame()

        normalized = df.copy()
        normalized.columns = [str(col).lower() for col in normalized.columns]
        if "ts_code" not in normalized.columns:
            return pd.DataFrame()
        normalized["code"] = normalized["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
        return normalized

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
        snapshot_time: datetime,
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
        prev_close = self._to_float(frame.iloc[-2]["close"]) if len(frame) >= 2 else None
        change_pct = None
        if close_price is not None and prev_close not in (None, 0):
            change_pct = (close_price - prev_close) / prev_close * 100
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
            "change_pct": change_pct,
            "turnover": None,
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
                "exit_plan": exit_plan,
            },
        }

    def generate_snapshot(self, *, trade_date: Optional[date] = None) -> dict[str, Any]:
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
        quotes = self._fetch_realtime_quotes(code_list)
        if quotes.empty:
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

        quote_map = {str(row["code"]).zfill(6): row for _, row in quotes.iterrows()}
        snapshot_time = self.now_shanghai()
        generated_count = 0
        skipped_count = 0

        self.db.query(CurrentHotIntradaySnapshot).filter(
            CurrentHotIntradaySnapshot.trade_date == target_trade_date
        ).delete(synchronize_session=False)

        for entry in entries:
            quote_row = quote_map.get(entry.code)
            if quote_row is None:
                skipped_count += 1
                continue

            payload = self._compute_snapshot(
                code=entry.code,
                trade_date=target_trade_date,
                sector_names=entry.sector_names,
                board_group=entry.board_group,
                quote_row=quote_row,
                snapshot_time=snapshot_time,
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
            "generated_count": generated_count,
            "skipped_count": skipped_count,
            "has_data": generated_count > 0,
            "window_open": self.is_window_open(),
        }

    def get_snapshot_payload(self, *, trade_date: Optional[date] = None, is_admin: bool = False) -> dict[str, Any]:
        status = self.get_status(trade_date=trade_date, is_admin=is_admin)
        if not is_admin and (not status.window_open or not status.has_data):
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
                "close_price": row.close_price,
                "high_price": row.high_price,
                "low_price": row.low_price,
                "volume": row.volume,
                "amount": row.amount,
                "change_pct": row.change_pct,
                "turnover": row.turnover,
                "b1_passed": row.b1_passed,
                "score": row.score,
                "verdict": row.verdict,
                "signal_type": row.signal_type,
                "kdj_j": row.kdj_j,
                "zx_long_pos": row.zx_long_pos,
                "weekly_ma_aligned": row.weekly_ma_aligned,
                "volume_healthy": row.volume_healthy,
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
            "items": items,
            "total": len(items),
        }
