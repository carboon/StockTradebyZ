"""
Current Hot Aggregate Service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
聚合首屏数据服务，将 history / candidates / results / sectors 合并为一次查询，
通过 Redis/内存缓存避免重复计算。

设计要点：
1. 单一缓存键缓存整份聚合快照，TTL = 120 秒。
2. 旧接口 (dates, candidates, results, sectors) 保持不变，
   但标记 deprecated —— 前端迁移后可逐步下线。
3. 当 generate 接口成功写入新数据时，主动清除缓存。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.cache import cache
from app.services.current_hot_service import CurrentHotService

logger = logging.getLogger(__name__)

_AGGREGATE_CACHE_KEY = "current_hot:aggregate:v1"
_AGGREGATE_CACHE_TTL = 120  # seconds


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


class CurrentHotAggregateService:
    """聚合首屏数据查询 + 缓存。"""

    def __init__(self, db: Session):
        self.db = db
        self._svc = CurrentHotService(db)

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def get_aggregate(
        self,
        *,
        pick_date: Optional[str] = None,
        candidates_limit: int = 200,
        sector_window_size: int = CurrentHotService.DEFAULT_WINDOW_SIZE,
        sector_top_n: int = 5,
        include_sectors: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """返回聚合首屏数据。

        Parameters
        ----------
        pick_date : str | None
            目标交易日。None 表示最新。
        candidates_limit : int
            candidates / results 的切片上限。
        sector_window_size : int
            板块分析回看窗口。
        sector_top_n : int
            板块 top N。
        include_sectors : bool
            是否包含板块分析（较重）。
        force_refresh : bool
            是否跳过缓存强制刷新。
        """
        # 短路：指定了 pick_date 则不走全局缓存（用户翻历史时数据不同）
        cache_key = _AGGREGATE_CACHE_KEY
        if pick_date:
            cache_key = f"{_AGGREGATE_CACHE_KEY}:{pick_date}"

        if not force_refresh and not pick_date:
            cached = cache.get(cache_key)
            if cached is not None:
                cached["cache_hit"] = True
                return cached

        payload = self._build_aggregate(
            pick_date=pick_date,
            candidates_limit=candidates_limit,
            sector_window_size=sector_window_size,
            sector_top_n=sector_top_n,
            include_sectors=include_sectors,
        )
        payload["generated_at"] = _now_iso()
        payload["cache_hit"] = False

        # 只缓存"最新交易日"聚合；指定日期的暂不缓存以避免膨胀
        if not pick_date:
            try:
                cache.set(cache_key, payload, ttl=_AGGREGATE_CACHE_TTL)
            except Exception:
                logger.warning("aggregate cache set failed", exc_info=True)

        return payload

    # ------------------------------------------------------------------
    # cache invalidation
    # ------------------------------------------------------------------

    @staticmethod
    def invalidate_cache() -> None:
        """清除聚合缓存（在 generate 成功后调用）。"""
        try:
            cache.delete_prefix(_AGGREGATE_CACHE_KEY)
        except Exception:
            logger.warning("aggregate cache invalidation failed", exc_info=True)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _build_aggregate(
        self,
        *,
        pick_date: Optional[str],
        candidates_limit: int,
        sector_window_size: int,
        sector_top_n: int,
        include_sectors: bool,
    ) -> dict[str, Any]:
        """实际查询并拼装聚合数据。"""
        t0 = time.monotonic()

        # 1) history / dates
        dates_payload = self._svc.get_dates(window_size=sector_window_size)

        # 2) candidates (含 risk_flag + risk_regime)
        candidates_payload = self._svc.load_candidates(
            pick_date, limit=candidates_limit, include_risk_regime=True,
        )

        # 3) results (含 risk_flag + risk_regime)
        results_payload = self._svc.get_results(
            pick_date, include_risk_regime=True,
        )

        # 4) sectors (较重，可选)
        sectors_payload: dict[str, Any] = {}
        if include_sectors:
            sectors_payload = self._svc.get_sector_analysis(
                window_size=sector_window_size, top_n=sector_top_n,
            )

        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
        logger.info(
            "[current-hot-aggregate] build completed in %sms  candidates=%s results=%s",
            elapsed_ms,
            candidates_payload.get("total", 0),
            results_payload.get("total", 0),
        )

        # ---- normalize to flat response ----
        return {
            # history
            "dates": dates_payload.get("dates", []),
            "history": dates_payload.get("history", []),
            "latest_date": dates_payload.get("latest_date"),
            # candidates
            "candidates": candidates_payload.get("candidates", []),
            "candidates_total": candidates_payload.get("total", 0),
            # results
            "results": results_payload.get("results", []),
            "results_total": results_payload.get("total", 0),
            "min_score_threshold": results_payload.get("min_score_threshold", 4.0),
            # sectors
            "sectors": sectors_payload.get("sectors", []),
            "sector_top_keys": sectors_payload.get("top_sector_keys", []),
            "sector_dates": sectors_payload.get("dates", []),
            "sector_history": sectors_payload.get("history", []),
            "sector_latest_date": sectors_payload.get("latest_date"),
            "sector_previous_date": sectors_payload.get("previous_date"),
            "sector_window_size": sectors_payload.get("window_size", 0),
            # risk regime (from candidates)
            "risk_regime": candidates_payload.get("risk_regime"),
            # meta
            "pick_date": candidates_payload.get("pick_date"),
        }
