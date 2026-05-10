"""
Intraday Analysis Service
~~~~~~~~~~~~~~~~~~~~~~~~~
中盘分析快照服务。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session

from app.models import Candidate, IntradayAnalysisSnapshot, Stock, StockDaily
from app.services.analysis_service import analysis_service
from app.services.exit_plan_service import ExitPlanService
from app.services.tushare_service import TushareService


ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass
class IntradayStatus:
    trade_date: date
    source_pick_date: Optional[date]
    snapshot_time: Optional[datetime]
    window_open: bool
    has_data: bool
    status: str
    message: Optional[str]


class IntradayAnalysisService:
    """中盘分析服务。"""

    WINDOW_START = time(12, 0)
    WINDOW_END = time(15, 0)

    def __init__(self, db: Session):
        self.db = db
        self.tushare_service = TushareService()
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
        code6 = normalized.zfill(6)
        if code6.startswith(("600", "601", "603", "605", "688", "689")):
            suffix = "SH"
        elif code6.startswith(("430", "8", "920")):
            suffix = "BJ"
        else:
            suffix = "SZ"
        return f"{code6}.{suffix}"

    def _get_previous_trade_date(self, trade_date: date) -> Optional[date]:
        rows = (
            self.db.query(StockDaily.trade_date)
            .distinct()
            .filter(StockDaily.trade_date < trade_date)
            .order_by(StockDaily.trade_date.desc())
            .limit(1)
            .all()
        )
        return rows[0][0] if rows else None

    def _get_source_pick_date(self, trade_date: date) -> Optional[date]:
        previous_trade_date = self._get_previous_trade_date(trade_date)
        if previous_trade_date is None:
            return None
        source_pick_date = (
            self.db.query(Candidate.pick_date)
            .filter(Candidate.pick_date == previous_trade_date)
            .limit(1)
            .scalar()
        )
        return source_pick_date

    def _get_candidates(self, source_pick_date: date) -> list[Candidate]:
        return (
            self.db.query(Candidate)
            .filter(Candidate.pick_date == source_pick_date)
            .order_by(Candidate.code.asc(), Candidate.id.asc())
            .all()
        )

    def _get_snapshot_rows(self, trade_date: date) -> list[IntradayAnalysisSnapshot]:
        return (
            self.db.query(IntradayAnalysisSnapshot)
            .filter(IntradayAnalysisSnapshot.trade_date == trade_date)
            .order_by(
                IntradayAnalysisSnapshot.score.desc().nullslast(),
                IntradayAnalysisSnapshot.id.asc(),
            )
            .all()
        )

    def _get_latest_snapshot_time(self, trade_date: date) -> Optional[datetime]:
        return (
            self.db.query(IntradayAnalysisSnapshot.snapshot_time)
            .filter(IntradayAnalysisSnapshot.trade_date == trade_date)
            .order_by(IntradayAnalysisSnapshot.snapshot_time.desc(), IntradayAnalysisSnapshot.id.desc())
            .limit(1)
            .scalar()
        )

    def get_status(self, *, trade_date: Optional[date] = None, is_admin: bool = False) -> IntradayStatus:
        target_trade_date = trade_date or self.get_trade_date()
        snapshot_time = self._get_latest_snapshot_time(target_trade_date)
        source_pick_date = self._get_source_pick_date(target_trade_date)
        window_open = self.is_window_open()
        has_data = snapshot_time is not None

        if has_data:
            status = "ok"
            message = None
        elif is_admin:
            status = "not_generated"
            message = "尚未生成中盘分析快照"
        elif not window_open:
            status = "window_closed"
            message = "普通用户仅可在 12:00-15:00 查看中盘分析"
        else:
            status = "not_ready"
            message = "今日中盘分析快照尚未生成"

        return IntradayStatus(
            trade_date=target_trade_date,
            source_pick_date=source_pick_date,
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

        snapshot_row = {
            "date": pd.Timestamp(trade_date),
            "open": self._to_float(quote_row.get("open")),
            "close": self._to_float(quote_row.get("close")),
            "high": self._to_float(quote_row.get("high")),
            "low": self._to_float(quote_row.get("low")),
            "volume": self._normalize_intraday_volume(history_df, quote_row),
            "amount": self._to_float(quote_row.get("amount")),
        }
        snapshot_df = pd.DataFrame([snapshot_row])
        merged = pd.concat([df, snapshot_df], ignore_index=True)
        merged = merged.drop_duplicates(subset=["date"], keep="last")
        merged = merged.sort_values("date").reset_index(drop=True)
        merged["change_pct"] = merged["close"].pct_change() * 100
        return merged

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result

    def _normalize_intraday_volume(self, history_df: pd.DataFrame, quote_row: pd.Series) -> Optional[float]:
        """Normalize Tushare rt_k volume before appending the temporary intraday candle."""
        volume = self._to_float(quote_row.get("vol"))
        if volume is None or history_df is None or history_df.empty or "volume" not in history_df.columns:
            return volume
        avg20 = pd.to_numeric(history_df["volume"], errors="coerce").dropna().tail(20).mean()
        if pd.notna(avg20) and avg20 > 0 and volume > avg20 * 20:
            return volume / 100.0
        return volume

    def _compute_snapshot(
        self,
        *,
        code: str,
        trade_date: date,
        source_pick_date: date,
        entry_price: Optional[float],
        quote_row: pd.Series,
        snapshot_time: datetime,
    ) -> Optional[dict[str, Any]]:
        history_df = analysis_service.load_stock_data(code, days=365)
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
        score_result = analysis_service._quant_review_for_date(
            code,
            frame.copy(),
            trade_date.isoformat(),
        )
        close_price = self._to_float(quote_row.get("close"))
        prev_close = self._to_float(frame.iloc[-2]["close"]) if len(frame) >= 2 else None
        change_pct = None
        if close_price is not None and prev_close not in (None, 0):
            change_pct = (close_price - prev_close) / prev_close * 100
        exit_plan = self.exit_plan_service.build_exit_plan(
            code=code,
            history_df=frame,
            entry_price=entry_price,
            current_price=close_price,
            entry_date=source_pick_date,
            verdict=score_result.get("verdict"),
            signal_type=score_result.get("signal_type"),
            is_intraday=True,
        )

        return {
            "trade_date": trade_date,
            "code": code,
            "source_pick_date": source_pick_date,
            "snapshot_time": snapshot_time,
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
        source_pick_date = self._get_source_pick_date(target_trade_date)
        if source_pick_date is None:
            return {
                "trade_date": target_trade_date,
                "source_pick_date": None,
                "snapshot_time": None,
                "status": "missing_source",
                "message": "未找到前一交易日候选股",
                "generated_count": 0,
                "skipped_count": 0,
                "has_data": False,
                "window_open": self.is_window_open(),
            }

        candidates = self._get_candidates(source_pick_date)
        if not candidates:
            return {
                "trade_date": target_trade_date,
                "source_pick_date": source_pick_date,
                "snapshot_time": None,
                "status": "missing_source",
                "message": "前一交易日无候选股数据",
                "generated_count": 0,
                "skipped_count": 0,
                "has_data": False,
                "window_open": self.is_window_open(),
            }

        code_list = [candidate.code.zfill(6) for candidate in candidates]
        quotes = self._fetch_realtime_quotes(code_list)
        if quotes.empty:
            return {
                "trade_date": target_trade_date,
                "source_pick_date": source_pick_date,
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

        for code in code_list:
            quote_row = quote_map.get(code)
            if quote_row is None:
                skipped_count += 1
                continue
            candidate = next((item for item in candidates if item.code.zfill(6) == code), None)

            snapshot = self._compute_snapshot(
                code=code,
                trade_date=target_trade_date,
                source_pick_date=source_pick_date,
                entry_price=candidate.close_price if candidate else None,
                quote_row=quote_row,
                snapshot_time=snapshot_time,
            )
            if snapshot is None:
                skipped_count += 1
                continue

            stock = self.db.query(Stock).filter(Stock.code == code).first()
            if stock is None:
                stock = Stock(code=code)
                self.db.add(stock)
                self.db.flush()

            row = (
                self.db.query(IntradayAnalysisSnapshot)
                .filter(
                    IntradayAnalysisSnapshot.trade_date == target_trade_date,
                    IntradayAnalysisSnapshot.code == code,
                )
                .first()
            )
            if row is None:
                row = IntradayAnalysisSnapshot(
                    trade_date=target_trade_date,
                    code=code,
                    source_pick_date=source_pick_date,
                    snapshot_time=snapshot_time,
                )
                self.db.add(row)

            for key, value in snapshot.items():
                setattr(row, key, value)
            generated_count += 1

        self.db.commit()

        latest_snapshot_time = self._get_latest_snapshot_time(target_trade_date)
        return {
            "trade_date": target_trade_date,
            "source_pick_date": source_pick_date,
            "snapshot_time": latest_snapshot_time,
            "status": "ok" if generated_count > 0 else "empty",
            "message": None if generated_count > 0 else "未生成任何中盘分析快照",
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
            row.code: row.name
            for row in self.db.query(Stock.code, Stock.name)
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
