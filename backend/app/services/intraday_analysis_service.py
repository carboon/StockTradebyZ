"""
Intraday Analysis Service
~~~~~~~~~~~~~~~~~~~~~~~~~
中盘分析快照服务。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
import logging
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AnalysisResult, Candidate, DailyB1Check, DailyB1CheckDetail, IntradayAnalysisSnapshot, Stock, StockActivePoolRank, StockDaily
from app.services.analysis_service import analysis_service
from app.services.exit_plan_service import ExitPlanService
from app.services.tushare_service import TushareService


ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


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

    EASTMONEY_TRENDS_URL = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
    EASTMONEY_UT = "fa5fd1943c7b386f172d6893dbfba10b"
    TENCENT_MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query"
    MARKET_MINUTES_PER_DAY = 240
    WINDOW_START = time(11, 30)
    WINDOW_END = time(15, 0)
    MIDDAY_CUTOFF = "11:30:00"
    MARKET_BENCHMARKS = (
        {"name": "中证500", "ts_code": "000905.SH"},
        {"name": "创业板指", "ts_code": "399006.SZ"},
        {"name": "上证指数", "ts_code": "000001.SH"},
    )
    MARKET_OVERVIEW_FALLBACK = {
        "summary": "暂无大盘中盘总览",
        "market_bias": "中性",
        "benchmark_name": None,
        "benchmark_change_pct": None,
        "items": [],
    }
    INTRADAY_RAW_SOURCE = "eastmoney"
    INTRADAY_SOURCE_PRIORITY = ("eastmoney", "tencent", "tushare_rt_min")

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
            message = "普通用户仅可在 11:30-15:00 查看中盘分析"
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
                logger.warning("获取实时行情失败: %s", ",".join(normalized_ts_codes), exc_info=True)
                return pd.DataFrame()
        except Exception:
            logger.warning("获取实时行情失败: %s", ",".join(normalized_ts_codes), exc_info=True)
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

    def _to_eastmoney_secid(self, code: str) -> str:
        normalized = str(code or "").strip().upper()
        if "." not in normalized:
            normalized = self._with_suffix(normalized)
        code_part, market_part = normalized.split(".", 1)
        market_id = "1" if market_part == "SH" else "0"
        return f"{market_id}.{code_part}"

    def _fetch_eastmoney_trends(self, code: str) -> pd.DataFrame:
        ts_code = str(code or "").strip().upper()
        if "." not in ts_code:
            ts_code = self._with_suffix(ts_code)

        params = {
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ut": self.EASTMONEY_UT,
            "secid": self._to_eastmoney_secid(ts_code),
            "ndays": 1,
            "iscr": 0,
            "iscca": 0,
        }
        request = Request(
            f"{self.EASTMONEY_TRENDS_URL}?{urlencode(params)}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                )
            },
        )

        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            logger.warning("东方财富分时数据获取失败: %s", ts_code, exc_info=True)
            return pd.DataFrame()

        data = payload.get("data") if isinstance(payload, dict) else None
        trends = data.get("trends") if isinstance(data, dict) else None
        if not isinstance(trends, list) or not trends:
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        pre_close = self._to_float(data.get("preClose")) if isinstance(data, dict) else None
        code_part = ts_code.split(".")[0].zfill(6)
        for item in trends:
            parts = str(item).split(",")
            if len(parts) < 7:
                continue
            rows.append(
                {
                    "ts_code": ts_code,
                    "normalized_ts_code": ts_code,
                    "code": code_part,
                    "trade_time": parts[0],
                    "time": parts[0],
                    "open": self._to_float(parts[1]),
                    "close": self._to_float(parts[2]),
                    "high": self._to_float(parts[3]),
                    "low": self._to_float(parts[4]),
                    "vol": self._to_float(parts[5]),
                    "amount": self._to_float(parts[6]),
                    "avg_price": self._to_float(parts[7]) if len(parts) > 7 else None,
                    "pre_close": pre_close,
                }
            )

        return pd.DataFrame(rows)

    def _to_tencent_symbol(self, code: str) -> str:
        normalized = str(code or "").strip().upper()
        if "." not in normalized:
            normalized = self._with_suffix(normalized)
        code_part, market_part = normalized.split(".", 1)
        market_prefix = {
            "SH": "sh",
            "SZ": "sz",
            "BJ": "bj",
        }.get(market_part, "sz")
        return f"{market_prefix}{code_part}"

    def _fetch_tencent_minute_trends(self, code: str) -> pd.DataFrame:
        ts_code = str(code or "").strip().upper()
        if "." not in ts_code:
            ts_code = self._with_suffix(ts_code)

        symbol = self._to_tencent_symbol(ts_code)
        request = Request(
            f"{self.TENCENT_MINUTE_URL}?{urlencode({'code': symbol})}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Referer": "https://gu.qq.com/",
            },
        )

        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            logger.warning("腾讯分时数据获取失败: %s", ts_code, exc_info=True)
            return pd.DataFrame()

        payload_data = payload.get("data") if isinstance(payload, dict) else None
        symbol_data = payload_data.get(symbol) if isinstance(payload_data, dict) else None
        minute_data = symbol_data.get("data") if isinstance(symbol_data, dict) else None
        rows_data = minute_data.get("data") if isinstance(minute_data, dict) else None
        if not isinstance(rows_data, list) or not rows_data:
            return pd.DataFrame()

        trade_date_text = str(minute_data.get("date") or "").strip() if isinstance(minute_data, dict) else ""
        qt_data = symbol_data.get("qt") if isinstance(symbol_data, dict) else None
        qt_values = qt_data.get(symbol) if isinstance(qt_data, dict) else None
        pre_close = self._to_float(qt_values[4]) if isinstance(qt_values, list) and len(qt_values) > 4 else None
        day_open = self._to_float(qt_values[5]) if isinstance(qt_values, list) and len(qt_values) > 5 else None
        day_high = self._to_float(qt_values[33]) if isinstance(qt_values, list) and len(qt_values) > 33 else None
        day_low = self._to_float(qt_values[34]) if isinstance(qt_values, list) and len(qt_values) > 34 else None
        code_part = ts_code.split(".")[0].zfill(6)

        rows: list[dict[str, Any]] = []
        prev_cum_vol: Optional[float] = None
        prev_cum_amount: Optional[float] = None
        for item in rows_data:
            parts = str(item).split()
            if len(parts) < 3:
                continue
            hhmm = str(parts[0]).strip()
            close_price = self._to_float(parts[1])
            cum_vol = self._to_float(parts[2])
            cum_amount = self._to_float(parts[3]) if len(parts) > 3 else None
            volume = cum_vol if prev_cum_vol is None or cum_vol is None else max(cum_vol - prev_cum_vol, 0.0)
            amount = cum_amount if prev_cum_amount is None or cum_amount is None else max(cum_amount - prev_cum_amount, 0.0)
            if cum_vol is not None:
                prev_cum_vol = cum_vol
            if cum_amount is not None:
                prev_cum_amount = cum_amount

            if len(trade_date_text) == 8 and hhmm.isdigit() and len(hhmm) == 4:
                trade_time = (
                    f"{trade_date_text[:4]}-{trade_date_text[4:6]}-{trade_date_text[6:8]} "
                    f"{hhmm[:2]}:{hhmm[2:4]}:00"
                )
            else:
                trade_time = hhmm

            rows.append(
                {
                    "ts_code": ts_code,
                    "normalized_ts_code": ts_code,
                    "code": code_part,
                    "trade_time": trade_time,
                    "time": trade_time,
                    "open": day_open if day_open is not None else close_price,
                    "close": close_price,
                    "high": day_high if day_high is not None else close_price,
                    "low": day_low if day_low is not None else close_price,
                    "vol": volume,
                    "amount": amount,
                    "cum_vol": cum_vol,
                    "cum_amount": cum_amount,
                    "pre_close": pre_close,
                }
            )

        return pd.DataFrame(rows)

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    @staticmethod
    def _resolve_intraday_raw_dir() -> Path:
        raw_dir = Path(settings.intraday_raw_data_dir)
        if raw_dir.is_absolute():
            return raw_dir
        return Path(__file__).resolve().parent.parent.parent.parent / raw_dir

    def _intraday_raw_path(self, trade_date: date, ts_code: str, *, source: Optional[str] = None) -> Path:
        normalized_ts_code = self._with_suffix(ts_code)
        return (
            self._resolve_intraday_raw_dir()
            / trade_date.isoformat()
            / (source or self.INTRADAY_RAW_SOURCE)
            / f"{normalized_ts_code}.json"
        )

    def _read_intraday_raw(self, trade_date: date, ts_code: str, *, source: Optional[str] = None) -> pd.DataFrame:
        candidate_sources = (source,) if source else self.INTRADAY_SOURCE_PRIORITY
        for candidate_source in candidate_sources:
            path = self._intraday_raw_path(trade_date, ts_code, source=candidate_source)
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("读取盘中原始数据失败: %s", path, exc_info=True)
                continue

            rows = payload.get("rows") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or not rows:
                continue

            frame = pd.DataFrame(rows)
            if frame.empty:
                continue
            frame.columns = [str(col).lower() for col in frame.columns]
            if "ts_code" not in frame.columns:
                frame["ts_code"] = self._with_suffix(ts_code)
            frame["normalized_ts_code"] = frame.get("normalized_ts_code", frame["ts_code"]).astype(str).str.upper()
            frame["code"] = frame.get("code", frame["ts_code"].astype(str).str.split(".").str[0]).astype(str).str.zfill(6)
            return frame
        return pd.DataFrame()

    def _write_intraday_raw(
        self,
        trade_date: date,
        ts_code: str,
        minute_df: pd.DataFrame,
        *,
        source: Optional[str] = None,
    ) -> None:
        if minute_df is None or minute_df.empty:
            return
        path = self._intraday_raw_path(trade_date, ts_code, source=source)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = minute_df.copy()
        frame.columns = [str(col).lower() for col in frame.columns]
        payload = {
            "trade_date": trade_date.isoformat(),
            "ts_code": self._with_suffix(ts_code),
            "source": source or self.INTRADAY_RAW_SOURCE,
            "saved_at": self.now_shanghai().isoformat(),
            "rows": frame.to_dict(orient="records"),
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, default=self._json_default),
            encoding="utf-8",
        )

    def _fetch_intraday_raw_once(self, trade_date: date, ts_code: str) -> pd.DataFrame:
        cached = self._read_intraday_raw(trade_date, ts_code)
        if trade_date != self.get_trade_date():
            return cached

        eastmoney_df = self._fetch_eastmoney_trends(ts_code)
        if eastmoney_df is not None and not eastmoney_df.empty:
            self._write_intraday_raw(trade_date, ts_code, eastmoney_df, source="eastmoney")
            return eastmoney_df

        tencent_df = self._fetch_tencent_minute_trends(ts_code)
        if tencent_df is not None and not tencent_df.empty:
            self._write_intraday_raw(trade_date, ts_code, tencent_df, source="tencent")
            return tencent_df

        try:
            df = self.tushare_service.pro.rt_min(ts_code=self._with_suffix(ts_code), freq="1MIN")
        except Exception:
            return cached
        if df is None or df.empty:
            return cached
        normalized = df.copy()
        normalized.columns = [str(col).lower() for col in normalized.columns]
        normalized["ts_code"] = normalized.get("ts_code", self._with_suffix(ts_code))
        normalized["normalized_ts_code"] = normalized["ts_code"].astype(str).str.upper()
        normalized["code"] = normalized["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
        self._write_intraday_raw(trade_date, ts_code, normalized, source="tushare_rt_min")
        return normalized

    def _has_midday_row(self, minute_df: pd.DataFrame, *, code: Optional[str] = None) -> bool:
        if minute_df is None or minute_df.empty:
            return False
        subset = minute_df
        if code is not None and "code" in subset.columns:
            subset = subset[subset["code"].astype(str).str.zfill(6) == str(code).zfill(6)].copy()
        if subset.empty:
            return False

        time_column = next((col for col in ("trade_time", "time") if col in subset.columns), None)
        if time_column is None:
            return False
        normalized_times = subset[time_column].map(self._normalize_time_text)
        return bool((normalized_times == self.MIDDAY_CUTOFF).any())

    def _fetch_minute_quotes(self, codes: list[str], *, trade_date: Optional[date] = None) -> pd.DataFrame:
        if not codes:
            return pd.DataFrame()

        target_trade_date = trade_date or self.get_trade_date()
        ts_codes = [self._with_suffix(code) for code in codes]
        frames: list[pd.DataFrame] = []

        for ts_code in ts_codes:
            frame = self._fetch_intraday_raw_once(target_trade_date, ts_code)
            if frame is not None and not frame.empty:
                frames.append(frame)

        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _prefetch_intraday_raw_data(
        self,
        *,
        trade_date: date,
        codes: list[str],
        include_market_benchmarks: bool = True,
    ) -> dict[str, Any]:
        current_trade_date = self.get_trade_date()
        requested_ts_codes = [self._with_suffix(code) for code in codes]
        if include_market_benchmarks:
            requested_ts_codes.extend(benchmark["ts_code"] for benchmark in self.MARKET_BENCHMARKS)

        normalized_ts_codes: list[str] = []
        seen: set[str] = set()
        for ts_code in requested_ts_codes:
            normalized_ts_code = self._with_suffix(ts_code)
            if normalized_ts_code in seen:
                continue
            normalized_ts_codes.append(normalized_ts_code)
            seen.add(normalized_ts_code)

        requested_count = len(normalized_ts_codes)
        ready_count = 0
        missing_count = 0
        midday_ready_count = 0
        cached_count = 0
        downloaded_count = 0

        for ts_code in normalized_ts_codes:
            cached_before = not self._read_intraday_raw(trade_date, ts_code).empty
            frame = self._fetch_intraday_raw_once(trade_date, ts_code)
            if frame is None or frame.empty:
                missing_count += 1
                continue

            ready_count += 1
            if cached_before:
                cached_count += 1
            elif trade_date == current_trade_date:
                downloaded_count += 1

            if self._has_midday_row(frame, code=ts_code.split(".")[0]):
                midday_ready_count += 1

        if requested_count == 0:
            status = "empty"
            message = "无可预下载的分时标的"
        elif ready_count == 0:
            status = "fetch_failed"
            message = "分时数据预下载失败"
        elif missing_count == 0:
            status = "ok"
            message = f"已准备 {ready_count}/{requested_count} 份分时数据，其中 {midday_ready_count} 份含 11:30 行情"
        else:
            status = "partial"
            message = (
                f"已准备 {ready_count}/{requested_count} 份分时数据，"
                f"仍缺失 {missing_count} 份，其中 {midday_ready_count} 份含 11:30 行情"
            )

        return {
            "trade_date": trade_date,
            "window_open": self.is_window_open(),
            "status": status,
            "message": message,
            "requested_count": requested_count,
            "ready_count": ready_count,
            "missing_count": missing_count,
            "midday_ready_count": midday_ready_count,
            "cached_count": cached_count,
            "downloaded_count": downloaded_count,
        }

    def prefetch_snapshot_data(self, *, trade_date: Optional[date] = None) -> dict[str, Any]:
        target_trade_date = trade_date or self.get_trade_date()
        source_pick_date = self._get_source_pick_date(target_trade_date)
        snapshot_time = self._get_latest_snapshot_time(target_trade_date)
        has_data = snapshot_time is not None

        if source_pick_date is None:
            return {
                "trade_date": target_trade_date,
                "source_pick_date": None,
                "snapshot_time": snapshot_time,
                "window_open": self.is_window_open(),
                "has_data": has_data,
                "status": "missing_source",
                "message": "未找到前一交易日候选股，无法预下载中盘分时数据",
                "requested_count": 0,
                "ready_count": 0,
                "missing_count": 0,
                "midday_ready_count": 0,
                "cached_count": 0,
                "downloaded_count": 0,
            }

        candidates = self._get_candidates(source_pick_date)
        if not candidates:
            return {
                "trade_date": target_trade_date,
                "source_pick_date": source_pick_date,
                "snapshot_time": snapshot_time,
                "window_open": self.is_window_open(),
                "has_data": has_data,
                "status": "missing_source",
                "message": "前一交易日无候选股数据，无法预下载中盘分时数据",
                "requested_count": 0,
                "ready_count": 0,
                "missing_count": 0,
                "midday_ready_count": 0,
                "cached_count": 0,
                "downloaded_count": 0,
            }

        payload = self._prefetch_intraday_raw_data(
            trade_date=target_trade_date,
            codes=[candidate.code.zfill(6) for candidate in candidates],
            include_market_benchmarks=True,
        )
        payload["source_pick_date"] = source_pick_date
        payload["snapshot_time"] = snapshot_time
        payload["has_data"] = has_data
        return payload

    def _build_realtime_quotes_from_minute_df(self, minute_df: pd.DataFrame) -> pd.DataFrame:
        if minute_df is None or minute_df.empty or "code" not in minute_df.columns:
            return pd.DataFrame()

        frames: list[dict[str, Any]] = []
        working = minute_df.copy()
        time_column = "trade_time" if "trade_time" in working.columns else ("time" if "time" in working.columns else None)
        if time_column is None:
            return pd.DataFrame()

        working["_sort_time"] = pd.to_datetime(working[time_column], errors="coerce")
        for code, subset in working.groupby("code", dropna=False):
            group = subset.sort_values("_sort_time").dropna(subset=["close"]).copy()
            if group.empty:
                continue
            first_row = group.iloc[0]
            last_row = group.iloc[-1]
            frames.append(
                {
                    "ts_code": str(first_row.get("ts_code") or self._with_suffix(str(code))).upper(),
                    "normalized_ts_code": str(first_row.get("normalized_ts_code") or first_row.get("ts_code") or self._with_suffix(str(code))).upper(),
                    "code": str(code).zfill(6),
                    "open": self._to_float(first_row.get("open")),
                    "close": self._to_float(last_row.get("close")),
                    "high": self._to_float(pd.to_numeric(group["high"], errors="coerce").max()) if "high" in group.columns else None,
                    "low": self._to_float(pd.to_numeric(group["low"], errors="coerce").min()) if "low" in group.columns else None,
                    "vol": self._to_float(pd.to_numeric(group["vol"], errors="coerce").sum()) if "vol" in group.columns else None,
                    "amount": self._to_float(pd.to_numeric(group["amount"], errors="coerce").sum()) if "amount" in group.columns else None,
                    "trade_time": last_row.get(time_column),
                    "elapsed_ratio": min(max(len(group) / float(self.MARKET_MINUTES_PER_DAY), 1 / float(self.MARKET_MINUTES_PER_DAY)), 1.0),
                    "pre_close": self._to_float(first_row.get("pre_close")),
                }
            )

        return pd.DataFrame(frames)

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
        target_row = exact.iloc[-1] if not exact.empty else subset.iloc[-1]
        return self._to_float(target_row.get(price_column)), target_row.get("_normalized_time")

    def _filter_minute_df_by_cutoff(
        self,
        minute_df: pd.DataFrame,
        *,
        cutoff_time_text: Optional[str] = None,
    ) -> pd.DataFrame:
        if minute_df is None or minute_df.empty or not cutoff_time_text:
            return minute_df

        time_column = "trade_time" if "trade_time" in minute_df.columns else ("time" if "time" in minute_df.columns else None)
        if time_column is None:
            return minute_df

        normalized_cutoff = self._normalize_time_text(cutoff_time_text)
        working = minute_df.copy()
        working["_normalized_time"] = working[time_column].map(self._normalize_time_text)
        working = working[working["_normalized_time"] <= normalized_cutoff].copy()
        return working.drop(columns=["_normalized_time"], errors="ignore")

    def _fetch_market_overview(
        self,
        trade_date: date,
        realtime_quotes: Optional[pd.DataFrame] = None,
        cutoff_time_text: Optional[str] = None,
    ) -> dict[str, Any]:
        overview_items: list[dict[str, Any]] = []
        chosen: Optional[dict[str, Any]] = None
        quote_lookup: dict[str, pd.Series] = {}

        if realtime_quotes is not None and not realtime_quotes.empty:
            normalized_quotes = realtime_quotes.copy()
            if "normalized_ts_code" not in normalized_quotes.columns and "ts_code" in normalized_quotes.columns:
                normalized_quotes["normalized_ts_code"] = normalized_quotes["ts_code"].astype(str).str.upper()
            for _, row in normalized_quotes.iterrows():
                ts_code = str(row.get("normalized_ts_code") or "").strip().upper()
                if ts_code:
                    quote_lookup[ts_code] = row

        for benchmark in self.MARKET_BENCHMARKS:
            ts_code = benchmark["ts_code"]
            try:
                daily_df = self.tushare_service.pro.index_daily(
                    ts_code=ts_code,
                    start_date=(trade_date - timedelta(days=40)).strftime("%Y%m%d"),
                    end_date=trade_date.strftime("%Y%m%d"),
                )
            except Exception:
                daily_df = None
            daily = pd.DataFrame()
            if daily_df is not None and not daily_df.empty:
                daily = daily_df.copy()
                daily.columns = [str(col).lower() for col in daily.columns]
                if "trade_date" in daily.columns:
                    daily["date"] = pd.to_datetime(daily["trade_date"], format="%Y%m%d", errors="coerce")
                elif "date" in daily.columns:
                    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
                for col in ("close", "vol", "amount"):
                    if col in daily.columns:
                        daily[col] = pd.to_numeric(daily[col], errors="coerce")
                if "date" in daily.columns:
                    daily = daily.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)

            rt_row: Optional[pd.Series] = quote_lookup.get(ts_code.upper())
            if rt_row is None:
                benchmark_minute_df = self._fetch_intraday_raw_once(trade_date, ts_code)
                benchmark_minute_df = self._filter_minute_df_by_cutoff(
                    benchmark_minute_df,
                    cutoff_time_text=cutoff_time_text,
                )
                if not benchmark_minute_df.empty:
                    benchmark_quotes = self._build_realtime_quotes_from_minute_df(benchmark_minute_df)
                    matched = benchmark_quotes[
                        benchmark_quotes["normalized_ts_code"].astype(str).str.upper() == ts_code.upper()
                    ]
                    if not matched.empty:
                        rt_row = matched.iloc[-1]
            if rt_row is None and realtime_quotes is None and cutoff_time_text is None:
                single_quote = self._fetch_realtime_quotes_by_ts_codes([ts_code])
                if not single_quote.empty:
                    matched = single_quote[
                        single_quote["normalized_ts_code"].astype(str).str.upper() == ts_code.upper()
                    ]
                    if not matched.empty:
                        rt_row = matched.iloc[-1]
            if rt_row is None:
                continue

            latest_price = self._to_float(rt_row.get("close"))
            open_price = self._to_float(rt_row.get("open"))
            latest_vol = self._to_float(rt_row.get("vol"))
            elapsed_ratio = self._to_float(rt_row.get("elapsed_ratio"))
            prev_close = self._to_float(daily.iloc[-1]["close"]) if not daily.empty else self._to_float(rt_row.get("pre_close"))
            if not daily.empty and len(daily) >= 2 and daily.iloc[-1]["date"].date() >= trade_date:
                prev_close = self._to_float(daily.iloc[-2]["close"])
            if latest_price in (None,) or prev_close in (None, 0):
                continue

            ma5 = (
                pd.concat([daily["close"], pd.Series([latest_price])], ignore_index=True).tail(5).mean()
                if not daily.empty and "close" in daily.columns
                else None
            )
            avg5_volume = pd.to_numeric(daily["vol"], errors="coerce").dropna().tail(5).mean() if not daily.empty and "vol" in daily.columns else None
            change_pct = (latest_price - prev_close) / prev_close * 100
            volume_ratio_5d = None
            projected_volume = latest_vol
            if projected_volume is not None and elapsed_ratio not in (None, 0):
                projected_volume = projected_volume / max(elapsed_ratio, 0.05)
            if projected_volume is not None and pd.notna(avg5_volume) and avg5_volume not in (None, 0):
                volume_ratio_5d = projected_volume / float(avg5_volume)

            trend = "上涨"
            if change_pct < -0.3:
                trend = "下跌"
            elif abs(change_pct) <= 0.3:
                trend = "震荡"
            volume_state = "量能平稳"
            if volume_ratio_5d is not None:
                if volume_ratio_5d >= 1.15 and change_pct < 0:
                    volume_state = "放量下跌"
                elif volume_ratio_5d >= 1.15 and change_pct > 0:
                    volume_state = "放量上涨"
                elif volume_ratio_5d <= 0.85 and change_pct > 0:
                    volume_state = "缩量上涨"
                elif volume_ratio_5d <= 0.85 and change_pct < 0:
                    volume_state = "缩量下跌"

            above_ma5 = bool(latest_price >= float(ma5)) if ma5 is not None and pd.notna(ma5) else None
            item = {
                "name": benchmark["name"],
                "ts_code": ts_code,
                "latest_price": latest_price,
                "open_price": open_price,
                "change_pct": round(change_pct, 2),
                "volume_ratio_5d": round(volume_ratio_5d, 2) if volume_ratio_5d is not None else None,
                "ma5": round(float(ma5), 2) if pd.notna(ma5) else None,
                "above_ma5": above_ma5,
                "trend": trend,
                "volume_state": volume_state,
                "summary": f"{benchmark['name']} {trend}，{volume_state}，{'站上' if above_ma5 else '跌破'}5日线" if above_ma5 is not None else f"{benchmark['name']} {trend}，{volume_state}",
            }
            overview_items.append(item)
            if chosen is None:
                chosen = item

        market_bias = "中性"
        if chosen:
            if chosen.get("change_pct", 0) > 0 and chosen.get("above_ma5"):
                market_bias = "偏强"
            elif chosen.get("change_pct", 0) < 0 and chosen.get("above_ma5") is False:
                market_bias = "偏弱"

        if not chosen:
            return dict(self.MARKET_OVERVIEW_FALLBACK)
        return {
            "summary": chosen.get("summary") if chosen else "暂无大盘中盘总览",
            "market_bias": market_bias,
            "benchmark_name": chosen.get("name") if chosen else None,
            "benchmark_change_pct": chosen.get("change_pct") if chosen else None,
            "items": overview_items,
        }

    @staticmethod
    def _build_market_overview_from_details(details_json: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not isinstance(details_json, dict):
            return None
        overview = details_json.get("market_overview")
        if isinstance(overview, dict):
            return overview

        benchmark_name = details_json.get("benchmark_name")
        benchmark_change_pct = details_json.get("benchmark_change_pct")
        if benchmark_name is None and benchmark_change_pct is None:
            return None
        return {
            "summary": f"{benchmark_name} 中盘参考" if benchmark_name else "暂无大盘中盘总览",
            "market_bias": "中性",
            "benchmark_name": benchmark_name,
            "benchmark_change_pct": benchmark_change_pct,
            "items": [],
        }

    @classmethod
    def _extract_market_overview_from_rows(cls, rows: list[Any]) -> Optional[dict[str, Any]]:
        for row in rows:
            overview = cls._build_market_overview_from_details(getattr(row, "details_json", None))
            if overview is not None:
                return overview
        return dict(cls.MARKET_OVERVIEW_FALLBACK)

    def _get_previous_analysis(self, code: str, source_pick_date: date) -> dict[str, Any]:
        analysis_row = (
            self.db.query(AnalysisResult)
            .filter(AnalysisResult.pick_date == source_pick_date, AnalysisResult.code == code)
            .order_by(AnalysisResult.total_score.desc().nullslast(), AnalysisResult.id.asc())
            .first()
        )
        b1_row = (
            self.db.query(DailyB1Check, DailyB1CheckDetail)
            .outerjoin(
                DailyB1CheckDetail,
                (DailyB1CheckDetail.code == DailyB1Check.code)
                & (DailyB1CheckDetail.check_date == DailyB1Check.check_date),
            )
            .filter(DailyB1Check.code == code, DailyB1Check.check_date == source_pick_date)
            .first()
        )

        b1_check = b1_row[0] if b1_row else None
        detail = b1_row[1] if b1_row else None
        score_details = detail.score_details_json if detail and isinstance(detail.score_details_json, dict) else {}
        fallback_metrics = self._get_market_metric_fallback(code, source_pick_date)

        result = {
            "pick_date": source_pick_date.isoformat(),
            "verdict": analysis_row.verdict if analysis_row else score_details.get("verdict"),
            "score": analysis_row.total_score if analysis_row else b1_check.score if b1_check else None,
            "signal_type": analysis_row.signal_type if analysis_row else score_details.get("signal_type"),
            "comment": analysis_row.comment if analysis_row else score_details.get("comment"),
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
        return result

    def _get_market_metric_fallback(self, code: str, reference_date: date) -> dict[str, Any]:
        daily_row = (
            self.db.query(StockDaily.trade_date, StockDaily.turnover_rate, StockDaily.volume_ratio)
            .filter(
                StockDaily.code == str(code).zfill(6),
                StockDaily.trade_date <= reference_date,
            )
            .order_by(StockDaily.trade_date.desc())
            .first()
        )
        active_rank_row = (
            self.db.query(StockActivePoolRank.trade_date, StockActivePoolRank.active_pool_rank)
            .filter(
                StockActivePoolRank.code == str(code).zfill(6),
                StockActivePoolRank.trade_date <= reference_date,
            )
            .order_by(StockActivePoolRank.trade_date.desc(), StockActivePoolRank.active_pool_rank.asc())
            .first()
        )
        return {
            "metrics_trade_date": daily_row[0] if daily_row else (active_rank_row[0] if active_rank_row else None),
            "turnover_rate": daily_row[1] if daily_row and daily_row[1] is not None else None,
            "volume_ratio": daily_row[2] if daily_row and daily_row[2] is not None else None,
            "active_pool_rank": active_rank_row[1] if active_rank_row and active_rank_row[1] is not None else None,
        }

    def _build_relative_market_status(
        self,
        *,
        latest_change_pct: Optional[float],
        benchmark_change_pct: Optional[float],
        market_bias: Optional[str],
    ) -> tuple[Optional[str], Optional[float], Optional[str]]:
        if latest_change_pct is None or benchmark_change_pct is None:
            return None, None, None

        excess = latest_change_pct - benchmark_change_pct
        if excess >= 2:
            status = "显著强于大盘"
        elif excess >= 0.5:
            status = "强于大盘"
        elif excess <= -2:
            status = "显著弱于大盘"
        elif excess <= -0.5:
            status = "弱于大盘"
        else:
            status = "与大盘同步"

        if market_bias == "偏弱" and excess > 0:
            note = "弱市中仍有相对强度，适合重点跟踪，但不宜追高。"
        elif market_bias == "偏弱":
            note = "市场偏弱且个股未跑赢指数，更应先控回撤。"
        elif market_bias == "偏强" and excess > 0:
            note = "顺风环境下继续跑赢大盘，适合按计划做持有或分批兑现。"
        else:
            note = "大盘没有明确顺风，操作上以兑现节奏和风险线为先。"
        return status, round(excess, 2), note

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
        return f"昨日复核为{previous_verdict}/{previous_signal}；当前相对大盘{relative_text}，大盘环境{market_text}。私募执行视角建议以“{action_label}”为主，{reason or '优先围绕结构线和仓位节奏处理。'}"

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
        minute_df: pd.DataFrame,
        snapshot_time: datetime,
        market_overview: dict[str, Any],
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
            entry_price=entry_price,
            current_price=close_price,
            entry_date=source_pick_date,
            verdict=score_result.get("verdict"),
            signal_type=score_result.get("signal_type"),
            is_intraday=True,
        )
        previous_analysis = self._get_previous_analysis(code, source_pick_date)
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
        turnover_rate = previous_analysis.get("turnover_rate")
        volume_ratio = previous_analysis.get("volume_ratio")
        active_pool_rank = previous_analysis.get("active_pool_rank")

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
                "analysis_basis": "基于前一交易日候选 + 当日11:30分时快照 + 当前实时价综合判断",
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
        minute_df = self._fetch_minute_quotes(code_list, trade_date=target_trade_date)
        minute_df = self._filter_minute_df_by_cutoff(minute_df, cutoff_time_text=cutoff_time_text)
        quotes = self._build_realtime_quotes_from_minute_df(minute_df)
        if quotes.empty and cutoff_time_text is None:
            quotes = self._fetch_realtime_quotes(code_list)
        stock_quotes = quotes
        if stock_quotes.empty:
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
        market_overview = self._fetch_market_overview(
            target_trade_date,
            realtime_quotes=stock_quotes,
            cutoff_time_text=cutoff_time_text,
        )

        quote_map = {
            str(row["normalized_ts_code"]).strip().upper(): row
            for _, row in stock_quotes.iterrows()
        }
        snapshot_time = self.now_shanghai()
        generated_count = 0
        skipped_count = 0

        self.db.query(IntradayAnalysisSnapshot).filter(
            IntradayAnalysisSnapshot.trade_date == target_trade_date
        ).delete(synchronize_session=False)

        for code in code_list:
            quote_row = quote_map.get(self._with_suffix(code).upper())
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
                minute_df=minute_df,
                snapshot_time=snapshot_time,
                market_overview=market_overview,
            )
            if snapshot is None:
                skipped_count += 1
                continue

            stock = self.db.query(Stock).filter(Stock.code == code).first()
            if stock is None:
                stock = Stock(code=code)
                self.db.add(stock)
                self.db.flush()

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
                "midday_price": (row.details_json or {}).get("midday_price"),
                "close_price": row.close_price,
                "latest_price": row.close_price,
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
            "market_overview": self._extract_market_overview_from_rows(rows),
            "items": items,
            "total": len(items),
        }
