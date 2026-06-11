"""Late-session stock screening service."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import logging
import re
import time as time_module
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import LateSessionScreenResult, LateSessionScreenRun, Stock, StockDaily, Watchlist
from app.services.intraday_analysis_service import IntradayAnalysisService
from app.time_utils import utc_now


ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LateSessionStatus:
    trade_date: date
    snapshot_time: Optional[datetime]
    window_open: bool
    has_data: bool
    status: str
    message: Optional[str]


class LateSessionScreenService:
    """筛选 14:30 后强势但未明显追高的短线候选。"""

    WINDOW_START = time(14, 30)
    WINDOW_END = time(15, 0)
    CHANGE_MIN = 3.0
    CHANGE_MAX = 5.0
    VOLUME_RATIO_MIN = 1.0
    TURNOVER_MIN = 5.0
    TURNOVER_MAX = 10.0
    EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    EASTMONEY_FIELDS = "f2,f3,f5,f6,f8,f10,f12,f14,f20,f21"
    EASTMONEY_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    EASTMONEY_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    CIRC_MV_MIN = 5_000_000_000.0
    CIRC_MV_MAX = 20_000_000_000.0
    INTRADAY_DETAIL_LIMIT = 120
    REFRESH_COOLDOWN_SECONDS = 60
    EASTMONEY_PAGE_SIZE = 100
    EASTMONEY_PAGE_INTERVAL_SECONDS = 0.15
    EASTMONEY_BATCH_PAGES = 10
    EASTMONEY_BATCH_INTERVAL_SECONDS = 2.0
    EASTMONEY_PAGE_RETRIES = 5
    EASTMONEY_FULL_FETCH_ATTEMPTS = 2
    TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
    TENCENT_BATCH_SIZE = 80
    TENCENT_BATCH_INTERVAL_SECONDS = 0.15
    TENCENT_BATCH_RETRIES = 3
    TENCENT_HEADERS = {
        "User-Agent": EASTMONEY_HEADERS["User-Agent"],
        "Referer": "https://stockapp.finance.qq.com/",
    }

    def __init__(self, db: Session):
        self.db = db
        self.intraday_service = IntradayAnalysisService(db)

    def now_shanghai(self) -> datetime:
        return datetime.now(ASIA_SHANGHAI)

    def get_trade_date(self) -> date:
        return self.now_shanghai().date()

    def is_window_open(self, now: Optional[datetime] = None) -> bool:
        current = now or self.now_shanghai()
        current_time = current.timetz().replace(tzinfo=None)
        return self.WINDOW_START <= current_time <= self.WINDOW_END

    def get_status(self, *, trade_date: Optional[date] = None, is_admin: bool = False) -> LateSessionStatus:
        target_trade_date = trade_date or self.get_trade_date()
        run = self._get_run(target_trade_date)
        window_open = self.is_window_open()
        has_data = run is not None and run.status in {"ready", "empty"}
        if has_data:
            status = "ok" if run and run.final_count > 0 else "empty"
            message = run.message
        else:
            status = "not_generated" if is_admin else "not_ready"
            message = "今日尾盘筛选尚未生成"
        return LateSessionStatus(
            trade_date=target_trade_date,
            snapshot_time=run.snapshot_time if run else None,
            window_open=window_open,
            has_data=has_data,
            status=status,
            message=message,
        )

    def generate(self, *, user_id: int | None, is_admin: bool, force: bool = False) -> dict[str, Any]:
        target_trade_date = self.get_trade_date()
        existing = self._get_run(target_trade_date)
        if existing and not force:
            return self.get_payload(trade_date=target_trade_date, is_admin=is_admin, message="展示已生成的尾盘筛选快照")
        if existing and force and self._is_in_refresh_cooldown(existing):
            return self.get_payload(
                trade_date=target_trade_date,
                is_admin=is_admin,
                message="刷新过于频繁，请 1 分钟后再试",
            )

        latest_daily_date = self._latest_daily_date_before_or_on(target_trade_date)
        if latest_daily_date is None:
            return self._empty_action_payload(target_trade_date, status="no_data", message="暂无日线数据，无法筛选")

        daily_rows = self._load_latest_daily_rows(latest_daily_date)
        if not daily_rows:
            return self._empty_action_payload(target_trade_date, status="no_data", message="最新交易日无股票日线数据")

        codes = [code for code, _stock, _daily in daily_rows]
        quotes = self._fetch_realtime_quotes(codes)
        if quotes.empty:
            if existing:
                return self.get_payload(
                    trade_date=target_trade_date,
                    is_admin=is_admin,
                    message="实时行情抓取失败，本次未覆盖旧快照",
                )
            return self._empty_action_payload(target_trade_date, status="fetch_failed", message="实时行情抓取失败或无返回数据")

        quote_map = {str(row["code"]).zfill(6): row for _, row in quotes.iterrows() if row.get("code") is not None}
        benchmark_change_pct = self._fetch_benchmark_change_pct(target_trade_date)
        snapshot_time = self.now_shanghai()
        results: list[dict[str, Any]] = []
        hard_pass_codes: list[str] = []

        for code, stock, daily in daily_rows:
            quote_row = quote_map.get(code)
            if quote_row is None:
                continue
            item = self._build_base_result(
                code=code,
                stock=stock,
                daily=daily,
                quote_row=quote_row,
                latest_daily_date=latest_daily_date,
                benchmark_change_pct=benchmark_change_pct,
            )
            results.append(item)
            if item["hard_pass"]:
                hard_pass_codes.append(code)

        detail_codes = hard_pass_codes[: self.INTRADAY_DETAIL_LIMIT]
        minute_df = self.intraday_service._fetch_minute_quotes(detail_codes, trade_date=target_trade_date) if detail_codes else pd.DataFrame()
        history_map = self._load_history_map(detail_codes, target_trade_date=target_trade_date)
        for item in results:
            if not item["hard_pass"] or item["code"] not in detail_codes:
                continue
            detail = self._score_detail(
                item=item,
                history_df=history_map.get(item["code"]),
                minute_df=minute_df,
                benchmark_change_pct=benchmark_change_pct,
            )
            item.update(detail)

        self._persist_run(
            trade_date=target_trade_date,
            snapshot_time=snapshot_time,
            results=results,
            benchmark_change_pct=benchmark_change_pct,
            user_id=user_id,
            force=force,
        )
        return self.get_payload(trade_date=target_trade_date, is_admin=is_admin, message="尾盘筛选已生成")

    def get_payload(self, *, trade_date: Optional[date] = None, is_admin: bool = False, message: Optional[str] = None) -> dict[str, Any]:
        status = self.get_status(trade_date=trade_date, is_admin=is_admin)
        run = self._get_run(status.trade_date)
        if run is None:
            return {
                "trade_date": status.trade_date,
                "snapshot_time": status.snapshot_time,
                "window_open": status.window_open,
                "has_data": status.has_data,
                "status": status.status,
                "message": message or status.message,
                "funnel": [],
                "market_overview": None,
                "items": [],
                "total": 0,
                "final_count": 0,
            }

        rows = (
            self.db.query(LateSessionScreenResult)
            .filter(LateSessionScreenResult.run_id == run.id)
            .order_by(
                LateSessionScreenResult.final_pass.desc(),
                LateSessionScreenResult.final_score.desc().nullslast(),
                LateSessionScreenResult.change_pct.desc().nullslast(),
                LateSessionScreenResult.code.asc(),
            )
            .all()
        )
        items = [self._row_to_item(row) for row in rows]
        return {
            "trade_date": run.trade_date,
            "snapshot_time": run.snapshot_time,
            "window_open": status.window_open,
            "has_data": True,
            "status": status.status,
            "message": message or status.message,
            "funnel": run.funnel_json or [],
            "market_overview": run.market_overview_json,
            "items": items,
            "total": len(items),
            "final_count": run.final_count,
        }

    def add_watchlist(self, *, user_id: int, codes: list[str]) -> dict[str, Any]:
        normalized_codes = []
        seen = set()
        for code in codes:
            normalized = str(code or "").strip().upper().split(".", 1)[0].zfill(6)
            if normalized.isdigit() and len(normalized) == 6 and normalized not in seen:
                normalized_codes.append(normalized)
                seen.add(normalized)
        if not normalized_codes:
            return {"added_count": 0, "skipped_count": 0, "items": []}

        stocks = {
            row.code: row
            for row in self.db.query(Stock).filter(Stock.code.in_(normalized_codes)).all()
        }
        existing = {
            row.code: row
            for row in self.db.query(Watchlist)
            .filter(Watchlist.user_id == user_id, Watchlist.code.in_(normalized_codes))
            .all()
        }
        added_count = 0
        skipped_count = 0
        items = []
        for code in normalized_codes:
            if code not in stocks:
                skipped_count += 1
                items.append({"code": code, "status": "missing_stock"})
                continue
            watch = existing.get(code)
            if watch is not None:
                if not watch.is_active:
                    watch.is_active = True
                    watch.add_reason = "尾盘筛选通过"
                    watch.entry_date = self.get_trade_date()
                    added_count += 1
                    items.append({"code": code, "status": "reactivated"})
                else:
                    skipped_count += 1
                    items.append({"code": code, "status": "exists"})
                continue
            self.db.add(
                Watchlist(
                    user_id=user_id,
                    code=code,
                    add_reason="尾盘筛选通过",
                    priority=0,
                    entry_date=self.get_trade_date(),
                    is_active=True,
                )
            )
            added_count += 1
            items.append({"code": code, "status": "added"})
        self.db.commit()
        return {"added_count": added_count, "skipped_count": skipped_count, "items": items}

    def _get_run(self, trade_date: date) -> LateSessionScreenRun | None:
        return self.db.query(LateSessionScreenRun).filter(LateSessionScreenRun.trade_date == trade_date).first()

    def _is_in_refresh_cooldown(self, run: LateSessionScreenRun) -> bool:
        snapshot_time = run.snapshot_time
        if snapshot_time is None:
            return False
        current = self.now_shanghai()
        if snapshot_time.tzinfo is None:
            snapshot_time = snapshot_time.replace(tzinfo=current.tzinfo)
        elapsed = (current - snapshot_time).total_seconds()
        return elapsed < self.REFRESH_COOLDOWN_SECONDS

    def _latest_daily_date_before_or_on(self, trade_date: date) -> date | None:
        return (
            self.db.query(func.max(StockDaily.trade_date))
            .filter(StockDaily.trade_date <= trade_date)
            .scalar()
        )

    def _load_latest_daily_rows(self, trade_date: date) -> list[tuple[str, Stock, StockDaily]]:
        rows = (
            self.db.query(Stock, StockDaily)
            .join(StockDaily, StockDaily.code == Stock.code)
            .filter(StockDaily.trade_date == trade_date)
            .order_by(Stock.code.asc())
            .all()
        )
        return [(stock.code.zfill(6), stock, daily) for stock, daily in rows]

    def _fetch_realtime_quotes(self, codes: list[str]) -> pd.DataFrame:
        target_codes = {str(code).zfill(6) for code in codes}
        if not target_codes:
            return pd.DataFrame()

        for attempt in range(1, self.EASTMONEY_FULL_FETCH_ATTEMPTS + 1):
            frame = self._fetch_realtime_quotes_once(target_codes, full_attempt=attempt)
            if not frame.empty:
                return frame
            if attempt < self.EASTMONEY_FULL_FETCH_ATTEMPTS:
                logger.warning("东方财富实时行情整轮抓取失败，准备重试 attempt=%s", attempt)
                time_module.sleep(1.0)
        logger.warning("东方财富实时行情完整抓取失败，切换腾讯备用源")
        return self._fetch_tencent_realtime_quotes(target_codes)

    def _fetch_realtime_quotes_once(self, target_codes: set[str], *, full_attempt: int) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        page = 1
        page_size = self.EASTMONEY_PAGE_SIZE
        total = None
        while True:
            params = {
                "pn": page,
                "pz": page_size,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f3",
                "fs": self.EASTMONEY_FS,
                "fields": self.EASTMONEY_FIELDS,
            }
            payload = self._fetch_eastmoney_page(params=params, page=page)
            if payload is None:
                logger.warning(
                    "获取东方财富实时行情失败，本次分页不完整 full_attempt=%s page=%s fetched=%s total=%s",
                    full_attempt,
                    page,
                    len(rows),
                    total,
                )
                return pd.DataFrame()

            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                logger.warning("东方财富实时行情返回结构异常 full_attempt=%s page=%s", full_attempt, page)
                return pd.DataFrame()
            if total is None:
                total = int(data.get("total") or 0)
            diff = data.get("diff")
            if not isinstance(diff, list) or not diff:
                if total and page * page_size < total:
                    logger.warning("东方财富实时行情提前返回空页 full_attempt=%s page=%s total=%s", full_attempt, page, total)
                    return pd.DataFrame()
                break

            for item in diff:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("f12") or "").zfill(6)
                if code not in target_codes:
                    continue
                rows.append(
                    {
                        "code": code,
                        "name": item.get("f14"),
                        "close": self._to_float(item.get("f2")),
                        "pct_chg": self._to_float(item.get("f3")),
                        "volume": self._to_float(item.get("f5")),
                        "amount": self._to_float(item.get("f6")),
                        "turnover_rate": self._to_float(item.get("f8")),
                        "volume_ratio": self._to_float(item.get("f10")),
                        "total_mv": self._to_float(item.get("f20")),
                        "circ_mv": self._to_float(item.get("f21")),
                        "source": "eastmoney_clist",
                    }
                )

            if page * page_size >= total:
                break
            page += 1
            if (page - 1) % self.EASTMONEY_BATCH_PAGES == 0:
                logger.info(
                    "东方财富实时行情分批等待 full_attempt=%s completed_pages=%s total=%s fetched=%s",
                    full_attempt,
                    page - 1,
                    total,
                    len(rows),
                )
                time_module.sleep(self.EASTMONEY_BATCH_INTERVAL_SECONDS)
            else:
                time_module.sleep(self.EASTMONEY_PAGE_INTERVAL_SECONDS)

        return pd.DataFrame(rows)

    def _fetch_eastmoney_page(self, *, params: dict[str, Any], page: int) -> dict[str, Any] | None:
        last_error: Exception | None = None
        for attempt in range(1, self.EASTMONEY_PAGE_RETRIES + 1):
            try:
                response = requests.get(
                    self.EASTMONEY_CLIST_URL,
                    params=params,
                    headers=self.EASTMONEY_HEADERS,
                    timeout=10,
                )
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else None
            except Exception as exc:
                last_error = exc
                if attempt < self.EASTMONEY_PAGE_RETRIES:
                    time_module.sleep(0.5 * attempt)
        logger.warning(
            "获取东方财富实时行情失败 page=%s attempts=%s error=%s",
            page,
            self.EASTMONEY_PAGE_RETRIES,
            last_error,
            exc_info=True,
        )
        return None

    def _fetch_tencent_realtime_quotes(self, target_codes: set[str]) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        symbols = [self._to_tencent_symbol(code) for code in sorted(target_codes)]
        symbols = [symbol for symbol in symbols if symbol is not None]
        if len(symbols) != len(target_codes):
            logger.warning("腾讯实时行情存在无法识别市场前缀的股票 target=%s symbols=%s", len(target_codes), len(symbols))
            return pd.DataFrame()

        expected_trade_date = self.get_trade_date().strftime("%Y%m%d")
        for start in range(0, len(symbols), self.TENCENT_BATCH_SIZE):
            batch = symbols[start : start + self.TENCENT_BATCH_SIZE]
            text = self._fetch_tencent_batch(batch)
            if text is None:
                logger.warning("腾讯实时行情批次抓取失败 start=%s size=%s fetched=%s", start, len(batch), len(rows))
                return pd.DataFrame()
            for symbol, body in re.findall(r'v_([^=]+)="(.*?)";', text, flags=re.S):
                if "pv_none_match" in symbol:
                    continue
                row = self._parse_tencent_quote(body, expected_trade_date=expected_trade_date)
                if row is not None and row["code"] in target_codes:
                    rows.append(row)
            if start + self.TENCENT_BATCH_SIZE < len(symbols):
                time_module.sleep(self.TENCENT_BATCH_INTERVAL_SECONDS)

        frame = pd.DataFrame(rows)
        if frame.empty:
            return pd.DataFrame()
        frame = frame.drop_duplicates(subset=["code"], keep="last")
        returned_codes = {str(code).zfill(6) for code in frame["code"].tolist()}
        missing_codes = target_codes - returned_codes
        if missing_codes:
            logger.warning("腾讯实时行情返回不完整 expected=%s returned=%s missing_sample=%s", len(target_codes), len(returned_codes), sorted(missing_codes)[:10])
            return pd.DataFrame()
        return frame

    def _fetch_tencent_batch(self, symbols: list[str]) -> str | None:
        last_error: Exception | None = None
        url = self.TENCENT_QUOTE_URL + ",".join(symbols)
        for attempt in range(1, self.TENCENT_BATCH_RETRIES + 1):
            try:
                response = requests.get(url, headers=self.TENCENT_HEADERS, timeout=10)
                response.raise_for_status()
                response.encoding = "gbk"
                return response.text
            except Exception as exc:
                last_error = exc
                if attempt < self.TENCENT_BATCH_RETRIES:
                    time_module.sleep(0.5 * attempt)
        logger.warning("获取腾讯实时行情失败 symbols=%s attempts=%s error=%s", len(symbols), self.TENCENT_BATCH_RETRIES, last_error, exc_info=True)
        return None

    def _parse_tencent_quote(self, body: str, *, expected_trade_date: str) -> dict[str, Any] | None:
        parts = body.split("~")
        if len(parts) < 50:
            return None
        code = str(parts[2] or "").zfill(6)
        quote_time = parts[30] if len(parts) > 30 else ""
        if not code.isdigit() or len(code) != 6 or not quote_time.startswith(expected_trade_date):
            return None
        total_mv_yi = self._to_float(parts[44] if len(parts) > 44 else None)
        circ_mv_yi = self._to_float(parts[45] if len(parts) > 45 else None)
        return {
            "code": code,
            "name": parts[1] if len(parts) > 1 else None,
            "close": self._to_float(parts[3]),
            "pre_close": self._to_float(parts[4]),
            "pct_chg": self._to_float(parts[32] if len(parts) > 32 else None),
            "volume": self._to_float(parts[36] if len(parts) > 36 else None),
            "amount": self._to_float(parts[37] if len(parts) > 37 else None),
            "turnover_rate": self._to_float(parts[38] if len(parts) > 38 else None),
            "volume_ratio": self._to_float(parts[49] if len(parts) > 49 else None),
            "total_mv": total_mv_yi * 100_000_000 if total_mv_yi is not None else None,
            "circ_mv": circ_mv_yi * 100_000_000 if circ_mv_yi is not None else None,
            "quote_time": quote_time,
            "source": "tencent_quote",
        }

    @staticmethod
    def _to_tencent_symbol(code: str) -> str | None:
        normalized = str(code).zfill(6)
        if normalized.startswith("6"):
            return f"sh{normalized}"
        if normalized.startswith(("0", "3")):
            return f"sz{normalized}"
        if normalized.startswith(("4", "8", "9")):
            return f"bj{normalized}"
        return None

    def _fetch_benchmark_change_pct(self, trade_date: date) -> float | None:
        minute_df = self.intraday_service._fetch_intraday_raw_once(trade_date, "000001.SH")
        quote = self.intraday_service._build_realtime_quotes_from_minute_df(minute_df)
        if quote.empty:
            quote = self.intraday_service._fetch_realtime_quotes_by_ts_codes(["000001.SH"])
        if quote.empty:
            return None
        row = quote.iloc[0]
        return self._calc_change_pct(self._to_float(row.get("close")), self._to_float(row.get("pre_close")))

    def _build_base_result(
        self,
        *,
        code: str,
        stock: Stock,
        daily: StockDaily,
        quote_row: pd.Series,
        latest_daily_date: date,
        benchmark_change_pct: float | None,
    ) -> dict[str, Any]:
        latest_price = self._to_float(quote_row.get("close"))
        pre_close = self._to_float(quote_row.get("pre_close")) or self._to_float(daily.close)
        change_pct = self._to_float(quote_row.get("pct_chg")) or self._calc_change_pct(latest_price, pre_close)
        volume = self._normalize_volume(self._to_float(quote_row.get("vol") or quote_row.get("volume")), daily)
        volume_ratio = self._first_float(quote_row, "volume_ratio", "vol_ratio", "量比")
        turnover_rate = self._first_float(quote_row, "turnover_rate", "turnover", "换手率")
        circ_mv = self._first_float(quote_row, "circ_mv", "float_mv", "circulating_market_cap", "流通市值")
        hard_checks = {
            "change_pct": change_pct is not None and self.CHANGE_MIN <= change_pct <= self.CHANGE_MAX,
            "volume_ratio": volume_ratio is not None and volume_ratio >= self.VOLUME_RATIO_MIN,
            "turnover_rate": turnover_rate is not None and self.TURNOVER_MIN <= turnover_rate <= self.TURNOVER_MAX,
            "circ_mv": circ_mv is not None and self.CIRC_MV_MIN <= circ_mv <= self.CIRC_MV_MAX,
        }
        reject_reason = self._first_reject_reason(hard_checks)
        hard_pass = all(hard_checks.values())
        return {
            "code": code,
            "name": stock.name,
            "industry": stock.industry,
            "latest_price": latest_price,
            "change_pct": change_pct,
            "volume_ratio": volume_ratio,
            "turnover_rate": turnover_rate,
            "circ_mv": circ_mv,
            "volume": volume,
            "amount": self._to_float(quote_row.get("amount")),
            "hard_pass": hard_pass,
            "final_pass": False,
            "final_score": 0.0 if hard_pass else None,
            "reject_reason": None if hard_pass else reject_reason,
            "volume_pattern": None,
            "ma_pattern": None,
            "intraday_pattern": None,
            "hot_topics": [stock.industry] if stock.industry else [],
            "details": {
                "latest_daily_date": latest_daily_date.isoformat(),
                "metric_source": quote_row.get("source") or "realtime_only",
                "benchmark_name": "上证指数",
                "benchmark_change_pct": benchmark_change_pct,
                "hard_checks": hard_checks,
            },
        }

    def _load_history_map(self, codes: list[str], *, target_trade_date: date) -> dict[str, pd.DataFrame]:
        if not codes:
            return {}
        rows = (
            self.db.query(StockDaily)
            .filter(StockDaily.code.in_(codes), StockDaily.trade_date <= target_trade_date)
            .order_by(StockDaily.code.asc(), StockDaily.trade_date.asc())
            .all()
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row.code.zfill(6), []).append(
                {
                    "date": row.trade_date,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                }
            )
        return {code: pd.DataFrame(items) for code, items in grouped.items()}

    def _score_detail(self, *, item: dict[str, Any], history_df: pd.DataFrame | None, minute_df: pd.DataFrame, benchmark_change_pct: float | None) -> dict[str, Any]:
        score = 50.0
        details = dict(item.get("details") or {})

        volume_pattern, volume_score = self._score_volume_pattern(history_df)
        ma_pattern, ma_score = self._score_ma_pattern(history_df, item.get("latest_price"))
        intraday_pattern, intraday_score, intraday_details = self._score_intraday_pattern(item["code"], minute_df, benchmark_change_pct, item.get("change_pct"))
        topic_score = 5.0 if item.get("industry") else 0.0
        score += volume_score + ma_score + intraday_score + topic_score
        final_pass = score >= 70.0 and volume_score >= 8.0 and ma_score >= 8.0 and intraday_score >= 8.0

        details.update(
            {
                "volume_score": volume_score,
                "ma_score": ma_score,
                "intraday_score": intraday_score,
                "topic_score": topic_score,
                "intraday": intraday_details,
            }
        )
        return {
            "final_score": round(score, 2),
            "final_pass": final_pass,
            "reject_reason": None if final_pass else "评分未达标",
            "volume_pattern": volume_pattern,
            "ma_pattern": ma_pattern,
            "intraday_pattern": intraday_pattern,
            "details": details,
        }

    def _score_volume_pattern(self, history_df: pd.DataFrame | None) -> tuple[str, float]:
        if history_df is None or history_df.empty or "volume" not in history_df.columns or len(history_df) < 6:
            return "unknown", 0.0
        volumes = pd.to_numeric(history_df["volume"], errors="coerce").dropna().tail(6).tolist()
        if len(volumes) < 6:
            return "unknown", 0.0
        last3 = volumes[-3:]
        prev3 = volumes[:3]
        if last3[0] <= last3[1] <= last3[2] and sum(last3) / 3 > sum(prev3) / 3:
            return "step_up", 15.0
        if sum(last3) / 3 > sum(prev3) / 3 * 1.15 and max(last3) / max(min(last3), 1.0) <= 1.8:
            return "expanding", 12.0
        return "unstable", 3.0

    def _score_ma_pattern(self, history_df: pd.DataFrame | None, latest_price: float | None) -> tuple[str, float]:
        if history_df is None or history_df.empty or latest_price is None or len(history_df) < 60:
            return "unknown", 0.0
        closes = pd.to_numeric(history_df["close"], errors="coerce").dropna().tolist()
        if len(closes) < 60:
            return "unknown", 0.0
        closes[-1] = float(latest_price)
        series = pd.Series(closes)
        ma5 = float(series.tail(5).mean())
        ma10 = float(series.tail(10).mean())
        ma20 = float(series.tail(20).mean())
        ma60 = float(series.tail(60).mean())
        ma60_prev = float(series.iloc[-61:-1].mean()) if len(series) >= 61 else ma60
        above_all = latest_price >= max(ma5, ma10, ma20, ma60)
        if above_all and ma5 >= ma10 >= ma20 and ma60 >= ma60_prev:
            return "bullish_alignment", 20.0
        if latest_price >= ma5 and latest_price >= ma10 and ma5 >= ma20:
            return "short_bullish", 14.0
        if latest_price < ma20 or latest_price < ma60:
            return "below_key_ma", 0.0
        return "neutral", 8.0

    def _score_intraday_pattern(
        self,
        code: str,
        minute_df: pd.DataFrame,
        benchmark_change_pct: float | None,
        change_pct: float | None,
    ) -> tuple[str, float, dict[str, Any]]:
        details = {
            "relative_market_strength_pct": None,
            "new_high_after_1430": None,
            "above_intraday_avg": None,
        }
        score = 0.0
        if change_pct is not None and benchmark_change_pct is not None:
            excess = change_pct - benchmark_change_pct
            details["relative_market_strength_pct"] = round(excess, 2)
            if excess > 0:
                score += 8.0
            if excess >= 2.0:
                score += 4.0

        stock_df = minute_df[minute_df["code"].astype(str).str.zfill(6) == code] if minute_df is not None and not minute_df.empty and "code" in minute_df.columns else pd.DataFrame()
        if stock_df.empty:
            return ("relative_strong" if score >= 8 else "unknown"), score, details
        time_column = "trade_time" if "trade_time" in stock_df.columns else ("time" if "time" in stock_df.columns else None)
        if time_column is None or "close" not in stock_df.columns:
            return ("relative_strong" if score >= 8 else "unknown"), score, details
        work = stock_df.copy()
        work["_time"] = pd.to_datetime(work[time_column], errors="coerce")
        work["_close"] = pd.to_numeric(work["close"], errors="coerce")
        work = work.dropna(subset=["_time", "_close"]).sort_values("_time")
        if work.empty:
            return ("relative_strong" if score >= 8 else "unknown"), score, details
        cutoff = time(14, 30)
        before = work[work["_time"].dt.time < cutoff]
        after = work[work["_time"].dt.time >= cutoff]
        if not before.empty and not after.empty:
            new_high = float(after["_close"].max()) >= float(before["_close"].max())
            details["new_high_after_1430"] = new_high
            if new_high:
                score += 7.0
        avg_price = float(work["_close"].mean())
        latest = float(work.iloc[-1]["_close"])
        above_avg = latest >= avg_price
        details["above_intraday_avg"] = above_avg
        if above_avg:
            score += 5.0
        pattern = "strong_new_high" if score >= 16 else ("relative_strong" if score >= 8 else "weak_intraday")
        return pattern, score, details

    def _persist_run(
        self,
        *,
        trade_date: date,
        snapshot_time: datetime,
        results: list[dict[str, Any]],
        benchmark_change_pct: float | None,
        user_id: int | None,
        force: bool,
    ) -> None:
        old = self._get_run(trade_date)
        if old is not None:
            self.db.query(LateSessionScreenResult).filter(LateSessionScreenResult.run_id == old.id).delete(synchronize_session=False)
            run = old
            run.snapshot_time = snapshot_time
            run.generated_by_user_id = user_id
            run.force_generated = force
            run.updated_at = utc_now()
        else:
            run = LateSessionScreenRun(
                trade_date=trade_date,
                snapshot_time=snapshot_time,
                generated_by_user_id=user_id,
                force_generated=force,
            )
            self.db.add(run)
            self.db.flush()

        final_count = sum(1 for item in results if item.get("final_pass"))
        hard_count = sum(1 for item in results if item.get("hard_pass"))
        run.status = "ready" if final_count > 0 else "empty"
        run.message = None if final_count > 0 else "尾盘筛选未得到最终标的"
        run.total_count = len(results)
        run.candidate_count = hard_count
        run.final_count = final_count
        run.funnel_json = self._build_funnel(results)
        run.market_overview_json = {"benchmark_name": "上证指数", "benchmark_change_pct": benchmark_change_pct}

        for item in results:
            self.db.add(
                LateSessionScreenResult(
                    run_id=run.id,
                    trade_date=trade_date,
                    code=item["code"],
                    name=item.get("name"),
                    industry=item.get("industry"),
                    latest_price=item.get("latest_price"),
                    change_pct=item.get("change_pct"),
                    volume_ratio=item.get("volume_ratio"),
                    turnover_rate=item.get("turnover_rate"),
                    circ_mv=item.get("circ_mv"),
                    volume=item.get("volume"),
                    amount=item.get("amount"),
                    final_score=item.get("final_score"),
                    final_pass=bool(item.get("final_pass")),
                    hard_pass=bool(item.get("hard_pass")),
                    reject_reason=item.get("reject_reason"),
                    volume_pattern=item.get("volume_pattern"),
                    ma_pattern=item.get("ma_pattern"),
                    intraday_pattern=item.get("intraday_pattern"),
                    hot_topics_json=item.get("hot_topics") or [],
                    details_json=item.get("details") or {},
                )
            )
        self.db.commit()

    def _build_funnel(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        checks = [
            ("涨幅 3%-5%", "change_pct"),
            ("量比 >= 1", "volume_ratio"),
            ("换手率 5%-10%", "turnover_rate"),
            ("流通市值 50-200 亿", "circ_mv"),
        ]
        remaining = list(results)
        funnel = [{"key": "realtime", "label": "实时行情", "count": len(remaining)}]
        for label, key in checks:
            remaining = [item for item in remaining if (item.get("details") or {}).get("hard_checks", {}).get(key)]
            funnel.append({"key": key, "label": label, "count": len(remaining)})
        funnel.append({"key": "scored", "label": "量能/均线/分时评分", "count": sum(1 for item in results if item.get("final_pass"))})
        return funnel

    def _row_to_item(self, row: LateSessionScreenResult) -> dict[str, Any]:
        return {
            "id": row.id,
            "trade_date": row.trade_date,
            "code": row.code,
            "name": row.name,
            "industry": row.industry,
            "latest_price": row.latest_price,
            "change_pct": row.change_pct,
            "volume_ratio": row.volume_ratio,
            "turnover_rate": row.turnover_rate,
            "circ_mv": row.circ_mv,
            "volume": row.volume,
            "amount": row.amount,
            "final_score": row.final_score,
            "final_pass": row.final_pass,
            "hard_pass": row.hard_pass,
            "reject_reason": row.reject_reason,
            "volume_pattern": row.volume_pattern,
            "ma_pattern": row.ma_pattern,
            "intraday_pattern": row.intraday_pattern,
            "hot_topics": row.hot_topics_json or [],
            "details": row.details_json or {},
        }

    def _empty_action_payload(self, trade_date: date, *, status: str, message: str) -> dict[str, Any]:
        return {
            "trade_date": trade_date,
            "snapshot_time": None,
            "window_open": self.is_window_open(),
            "has_data": False,
            "status": status,
            "message": message,
            "funnel": [],
            "market_overview": None,
            "items": [],
            "total": 0,
            "final_count": 0,
        }

    @staticmethod
    def _calc_change_pct(value: float | None, base: float | None) -> float | None:
        if value is None or base is None or base <= 0:
            return None
        return (value - base) / base * 100.0

    @staticmethod
    def _normalize_volume(volume: float | None, daily: StockDaily) -> float | None:
        if volume is None:
            return None
        daily_volume = float(daily.volume or 0)
        if daily_volume > 0 and volume > daily_volume * 20:
            return volume / 100.0
        return volume

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if pd.isna(parsed):
            return None
        return parsed

    def _first_float(self, row: pd.Series, *keys: str) -> float | None:
        for key in keys:
            value = self._to_float(row.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _first_reject_reason(checks: dict[str, bool]) -> str:
        labels = {
            "change_pct": "涨幅不在 3%-5%",
            "volume_ratio": "量比小于 1 或缺失",
            "turnover_rate": "换手率不在 5%-10%",
            "circ_mv": "流通市值不在 50-200 亿",
        }
        for key, passed in checks.items():
            if not passed:
                return labels[key]
        return "未通过"
