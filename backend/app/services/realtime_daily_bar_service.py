"""Realtime daily bar helpers built from public quote endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
import re
import time as time_module
from typing import Any
from zoneinfo import ZoneInfo

import requests


ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RealtimeDailyBar:
    code: str
    trade_date: date
    open: float | None
    close: float | None
    high: float | None
    low: float | None
    volume: float | None
    amount: float | None
    turnover_rate: float | None
    volume_ratio: float | None
    total_mv: float | None
    circ_mv: float | None
    source: str
    quote_time: str


class RealtimeDailyBarService:
    """Fetch same-day A-share daily bars from Tencent quote endpoint."""

    TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
    TENCENT_BATCH_SIZE = 80
    TENCENT_BATCH_INTERVAL_SECONDS = 0.15
    TENCENT_BATCH_RETRIES = 3
    TENCENT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Referer": "https://stockapp.finance.qq.com/",
    }

    def now_shanghai(self) -> datetime:
        return datetime.now(ASIA_SHANGHAI)

    def get_today(self) -> date:
        return self.now_shanghai().date()

    def fetch_bars(self, codes: list[str] | set[str], *, trade_date: date | None = None) -> dict[str, RealtimeDailyBar]:
        target_date = trade_date or self.get_today()
        target_codes = {str(code or "").zfill(6) for code in codes if str(code or "").strip()}
        symbols = [self._to_tencent_symbol(code) for code in sorted(target_codes)]
        symbols = [symbol for symbol in symbols if symbol is not None]
        if len(symbols) != len(target_codes):
            logger.warning("腾讯实时日K存在无法识别市场前缀的股票 target=%s symbols=%s", len(target_codes), len(symbols))
            return {}

        expected_trade_date = target_date.strftime("%Y%m%d")
        result: dict[str, RealtimeDailyBar] = {}
        for start in range(0, len(symbols), self.TENCENT_BATCH_SIZE):
            batch = symbols[start : start + self.TENCENT_BATCH_SIZE]
            text = self._fetch_tencent_batch(batch)
            if text is None:
                logger.warning("腾讯实时日K批次抓取失败 start=%s size=%s fetched=%s", start, len(batch), len(result))
                return {}
            for symbol, body in re.findall(r'v_([^=]+)="(.*?)";', text, flags=re.S):
                if "pv_none_match" in symbol:
                    continue
                bar = self._parse_tencent_quote(body, expected_trade_date=expected_trade_date, target_date=target_date)
                if bar is not None and bar.code in target_codes:
                    result[bar.code] = bar
            if start + self.TENCENT_BATCH_SIZE < len(symbols):
                time_module.sleep(self.TENCENT_BATCH_INTERVAL_SECONDS)

        if set(result) != target_codes:
            missing = sorted(target_codes - set(result))
            logger.warning("腾讯实时日K返回不完整 expected=%s returned=%s missing_sample=%s", len(target_codes), len(result), missing[:10])
            return {}
        return result

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
        logger.warning("获取腾讯实时日K失败 symbols=%s attempts=%s error=%s", len(symbols), self.TENCENT_BATCH_RETRIES, last_error, exc_info=True)
        return None

    def _parse_tencent_quote(self, body: str, *, expected_trade_date: str, target_date: date) -> RealtimeDailyBar | None:
        parts = body.split("~")
        if len(parts) < 50:
            return None
        code = str(parts[2] or "").zfill(6)
        quote_time = parts[30] if len(parts) > 30 else ""
        if not code.isdigit() or len(code) != 6 or not quote_time.startswith(expected_trade_date):
            return None
        total_mv_yi = self._to_float(parts[44] if len(parts) > 44 else None)
        circ_mv_yi = self._to_float(parts[45] if len(parts) > 45 else None)
        return RealtimeDailyBar(
            code=code,
            trade_date=target_date,
            open=self._to_float(parts[5] if len(parts) > 5 else None),
            close=self._to_float(parts[3] if len(parts) > 3 else None),
            high=self._to_float(parts[33] if len(parts) > 33 else None),
            low=self._to_float(parts[34] if len(parts) > 34 else None),
            volume=self._to_float(parts[36] if len(parts) > 36 else None),
            amount=self._to_float(parts[37] if len(parts) > 37 else None),
            turnover_rate=self._to_float(parts[38] if len(parts) > 38 else None),
            volume_ratio=self._to_float(parts[49] if len(parts) > 49 else None),
            total_mv=total_mv_yi * 100_000_000 if total_mv_yi is not None else None,
            circ_mv=circ_mv_yi * 100_000_000 if circ_mv_yi is not None else None,
            source="tencent_quote",
            quote_time=quote_time,
        )

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

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return None if parsed != parsed else parsed
