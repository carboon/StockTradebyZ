"""Financial data service with local caching (monthly refresh cycle).

Stores Tushare fina_indicator results in stock_financials table.
Query-first strategy: check local DB, only fetch from Tushare if stale/missing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import StockFinancial
from app.services.tushare_service import TushareService
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS = 30  # 月度刷新


class FinancialDataService:
    """财务数据本地缓存服务。"""

    def __init__(self, db: Session, tushare_service: TushareService | None = None) -> None:
        self.db = db
        self.tushare = tushare_service or TushareService()

    def get_or_refresh(self, ts_codes: list[str]) -> dict[str, dict[str, Any]]:
        """查询优先：先查 stock_financials，缺失/过期的走 Tushare 刷新。

        Returns:
            {code_6digit: {roe, netprofit_yoy, rev_yoy, grossprofit_margin, end_date}}
        """
        if not ts_codes:
            return {}

        cutoff = utc_now() - timedelta(days=CACHE_TTL_DAYS)
        codes_6 = [self._to_code6(tc) for tc in ts_codes]

        # 1. 从本地缓存加载
        cached_rows = (
            self.db.query(StockFinancial)
            .filter(StockFinancial.code.in_(codes_6))
            .all()
        )
        cached_map: dict[str, StockFinancial] = {row.code: row for row in cached_rows}

        result: dict[str, dict[str, Any]] = {}
        stale_codes: list[str] = []

        for code6 in codes_6:
            row = cached_map.get(code6)
            if row and row.fetched_at and row.fetched_at >= cutoff:
                result[code6] = {
                    "roe": row.roe,
                    "netprofit_yoy": row.netprofit_yoy,
                    "rev_yoy": row.rev_yoy,
                    "grossprofit_margin": row.grossprofit_margin,
                    "end_date": row.end_date,
                }
            else:
                stale_codes.append(code6)

        if not stale_codes:
            logger.info("FinancialDataService: all %d codes served from cache", len(codes_6))
            return result

        # 2. 从 Tushare 获取缺失/过期数据
        tc_list = [f"{c}.SH" if c.startswith(("60", "68", "90")) else
                   f"{c}.SZ" if c.startswith(("00", "30", "20")) else
                   f"{c}.BJ" if c.startswith(("43", "83", "87", "92")) else
                   f"{c}.SZ"
                   for c in stale_codes]

        logger.info("FinancialDataService: fetching %d stale codes from Tushare", len(stale_codes))
        tushare_result = self.tushare.get_financial_indicators(tc_list)

        now = utc_now()
        for code6 in stale_codes:
            data = tushare_result.get(code6, {})
            result[code6] = data

            # 3. Upsert 到本地缓存
            row = cached_map.get(code6)
            if row is None:
                row = StockFinancial(code=code6)
                self.db.add(row)
            row.roe = self._safe_float(data.get("roe"))
            row.netprofit_yoy = self._safe_float(data.get("netprofit_yoy"))
            row.rev_yoy = self._safe_float(data.get("rev_yoy"))
            row.grossprofit_margin = self._safe_float(data.get("grossprofit_margin"))
            row.end_date = str(data.get("end_date") or "")[:10]
            row.fetched_at = now
            row.updated_at = now

        self.db.commit()
        logger.info("FinancialDataService: %d cached, %d refreshed from Tushare",
                     len(codes_6) - len(stale_codes), len(stale_codes))
        return result

    @staticmethod
    def _to_code6(ts_code: str) -> str:
        return str(ts_code).split(".")[0].zfill(6) if "." in str(ts_code) else str(ts_code).zfill(6)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            import math
            result = float(value)
            if math.isnan(result) or math.isinf(result):
                return None
            return result
        except (TypeError, ValueError):
            return None
