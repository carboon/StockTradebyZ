"""
Background Latest Trade Day Update Service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
为命令行后台任务提供独立的最新交易日更新编排：
1. 判断最新交易日、数据库、CSV 的最新时间
2. 按交易日批量抓取并入库/同步 CSV
3. 重建该交易日明日之星结果
4. 输出阶段日志与耗时统计
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select

from app.api.cache_decorators import build_freshness_cache_key
from app.cache import cache
from app.config import settings
from app.database import SessionLocal
from app.models import StockDaily, TomorrowStarRun
from app.services.analysis_service import analysis_service
from app.services.background_update_exceptions import RetryableBackgroundUpdateError
from app.services.daily_batch_update_service import DailyBatchUpdateService
from app.services.market_service import MarketService
from app.services.tomorrow_star_window_service import maintain_tomorrow_star_for_trade_date
from app.services.tushare_service import TushareService
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


@dataclass
class TradeDayFreshnessStatus:
    latest_trade_date: Optional[str]
    latest_db_date: Optional[str]
    latest_csv_date: Optional[str]
    latest_candidate_date: Optional[str]
    latest_result_date: Optional[str]
    target_trade_date: Optional[str]
    db_needs_update: bool
    csv_needs_update: bool
    candidate_needs_update: bool
    result_needs_update: bool
    needs_market_update: bool
    needs_tomorrow_star_rebuild: bool
    needs_update: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "latest_trade_date": self.latest_trade_date,
            "latest_db_date": self.latest_db_date,
            "latest_csv_date": self.latest_csv_date,
            "latest_candidate_date": self.latest_candidate_date,
            "latest_result_date": self.latest_result_date,
            "target_trade_date": self.target_trade_date,
            "db_needs_update": self.db_needs_update,
            "csv_needs_update": self.csv_needs_update,
            "candidate_needs_update": self.candidate_needs_update,
            "result_needs_update": self.result_needs_update,
            "needs_market_update": self.needs_market_update,
            "needs_tomorrow_star_rebuild": self.needs_tomorrow_star_rebuild,
            "needs_update": self.needs_update,
            "reason": self.reason,
        }


@dataclass
class StageTimingRecorder:
    starts: dict[str, float] = field(default_factory=dict)
    durations: dict[str, float] = field(default_factory=dict)
    current_stage: Optional[str] = None

    def start(self, stage: str) -> None:
        now = time.perf_counter()
        if self.current_stage and self.current_stage != stage:
            self.finish(self.current_stage)
        self.current_stage = stage
        self.starts[stage] = now

    def finish(self, stage: str) -> float:
        started_at = self.starts.get(stage)
        if started_at is None:
            return float(self.durations.get(stage, 0.0) or 0.0)
        elapsed = max(0.0, time.perf_counter() - started_at)
        self.durations[stage] = round(elapsed, 3)
        if self.current_stage == stage:
            self.current_stage = None
        return self.durations[stage]

    def finish_current(self) -> None:
        if self.current_stage:
            self.finish(self.current_stage)


class DailyBatchProgressLogger:
    """记录按交易日批量更新的阶段切换与耗时。"""

    def __init__(self, run_logger: logging.Logger):
        self.logger = run_logger
        self.timings = StageTimingRecorder()
        self._last_stage: Optional[str] = None

    def __call__(self, payload: dict[str, Any]) -> None:
        stage = str(payload.get("stage") or "unknown")
        message = str(payload.get("message") or stage)
        now_text = datetime.now().isoformat(timespec="seconds")

        if stage != self._last_stage:
            if self._last_stage:
                elapsed = self.timings.finish(self._last_stage)
                self.logger.info(
                    "[%s] 阶段完成 stage=%s elapsed=%.3fs",
                    now_text,
                    self._last_stage,
                    elapsed,
                )
            self.timings.start(stage)
            self.logger.info("[%s] 阶段开始 stage=%s message=%s", now_text, stage, message)
            self._last_stage = stage
            return

        self.logger.info("[%s] 进度 stage=%s message=%s", now_text, stage, message)

    def finish(self) -> dict[str, float]:
        if self._last_stage:
            elapsed = self.timings.finish(self._last_stage)
            self.logger.info(
                "[%s] 阶段完成 stage=%s elapsed=%.3fs",
                datetime.now().isoformat(timespec="seconds"),
                self._last_stage,
                elapsed,
            )
            self._last_stage = None
        return dict(self.timings.durations)


class BackgroundLatestTradeDayUpdateService:
    """独立后台最新交易日更新服务。"""

    DEFAULT_REVIEWER = "quant"
    DEFAULT_WINDOW_SIZE = 180
    BEIJING_TZ = ZoneInfo("Asia/Shanghai")
    RETRY_START_HOUR = 16
    RETRY_START_MINUTE = 30

    def __init__(
        self,
        *,
        token: Optional[str] = None,
        log: Optional[logging.Logger] = None,
    ):
        self.token = token
        self.log = log or logger

    @staticmethod
    def _invalidate_runtime_caches() -> None:
        cache.delete(build_freshness_cache_key())
        cache.delete_prefix("candidates:")
        cache.delete_prefix("analysis_results:")
        TushareService.clear_data_status_cache()

    @staticmethod
    def _push_market_state(payload: dict[str, Any]) -> None:
        MarketService.update_progress(payload)

    @classmethod
    def _is_retry_window_open(cls, now: Optional[datetime] = None) -> bool:
        current = now.astimezone(cls.BEIJING_TZ) if now else datetime.now(cls.BEIJING_TZ)
        return (current.hour, current.minute) >= (cls.RETRY_START_HOUR, cls.RETRY_START_MINUTE)

    def _ensure_latest_trade_date_ready_for_retry(self, latest_trade_date: Optional[str]) -> None:
        if not latest_trade_date or not self._is_retry_window_open():
            return

        tushare_service = TushareService(token=self.token)
        if tushare_service.is_trade_date_data_ready(latest_trade_date):
            return

        raise RetryableBackgroundUpdateError(
            f"{latest_trade_date} 交易日数据在 Tushare 尚未就绪，将由 systemd 在 10 分钟后重试"
        )

    @staticmethod
    def _read_latest_date_from_csv(csv_path: Path) -> Optional[str]:
        try:
            with open(csv_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                file_size = f.tell()
                if file_size <= 0:
                    return None

                chunk_size = min(4096, file_size)
                f.seek(-chunk_size, os.SEEK_END)
                tail = f.read(chunk_size).decode("utf-8", errors="ignore")

            lines = [line for line in tail.splitlines() if line.strip()]
            if len(lines) < 2:
                return None
            value = lines[-1].split(",", 1)[0].strip()
            return value[:10] if value else None
        except Exception:
            return None

    def get_latest_csv_date(self) -> Optional[str]:
        raw_dir = Path(settings.raw_data_dir)
        if not raw_dir.exists():
            return None

        latest_date: Optional[str] = None
        for csv_path in raw_dir.glob("*.csv"):
            csv_latest = self._read_latest_date_from_csv(csv_path)
            if csv_latest and (latest_date is None or csv_latest > latest_date):
                latest_date = csv_latest
        return latest_date

    @staticmethod
    def get_latest_db_date() -> Optional[str]:
        with SessionLocal() as db:
            latest = db.execute(select(func.max(StockDaily.trade_date))).scalar()
            return latest.isoformat() if latest else None

    def assess_freshness(self, target_trade_date: Optional[str] = None) -> TradeDayFreshnessStatus:
        normalized_target = target_trade_date.strip() if target_trade_date else None
        market_service = MarketService(token=self.token)
        latest_trade_date = normalized_target or market_service.get_latest_trade_date()
        latest_db_date = self.get_latest_db_date()
        latest_csv_date = self.get_latest_csv_date()
        latest_candidate_date = analysis_service.get_latest_candidate_date()
        latest_result_date = analysis_service.get_latest_result_date()

        db_needs_update = bool(latest_trade_date and (not latest_db_date or latest_db_date < latest_trade_date))
        csv_needs_update = bool(latest_trade_date and (not latest_csv_date or latest_csv_date < latest_trade_date))
        candidate_needs_update = bool(
            latest_trade_date and (not latest_candidate_date or latest_candidate_date < latest_trade_date)
        )
        result_needs_update = bool(
            latest_trade_date and (not latest_result_date or latest_result_date < latest_trade_date)
        )
        needs_market_update = db_needs_update or csv_needs_update
        needs_tomorrow_star_rebuild = candidate_needs_update or result_needs_update
        needs_update = bool(normalized_target) or needs_market_update or needs_tomorrow_star_rebuild

        if not latest_trade_date:
            reason = "无法获取最新交易日"
        elif normalized_target:
            reason = f"强制执行指定交易日 {latest_trade_date}"
        elif needs_update:
            reasons: list[str] = []
            if db_needs_update:
                reasons.append(f"数据库最新日期 {latest_db_date or '-'} 落后于 {latest_trade_date}")
            if csv_needs_update:
                reasons.append(f"CSV 最新日期 {latest_csv_date or '-'} 落后于 {latest_trade_date}")
            if candidate_needs_update:
                reasons.append(f"候选最新日期 {latest_candidate_date or '-'} 落后于 {latest_trade_date}")
            if result_needs_update:
                reasons.append(f"分析结果最新日期 {latest_result_date or '-'} 落后于 {latest_trade_date}")
            reason = "；".join(reasons)
        else:
            reason = f"数据库与 CSV 已经是最新交易日 {latest_trade_date}"

        return TradeDayFreshnessStatus(
            latest_trade_date=latest_trade_date,
            latest_db_date=latest_db_date,
            latest_csv_date=latest_csv_date,
            latest_candidate_date=latest_candidate_date,
            latest_result_date=latest_result_date,
            target_trade_date=latest_trade_date,
            db_needs_update=db_needs_update,
            csv_needs_update=csv_needs_update,
            candidate_needs_update=candidate_needs_update,
            result_needs_update=result_needs_update,
            needs_market_update=needs_market_update,
            needs_tomorrow_star_rebuild=needs_tomorrow_star_rebuild,
            needs_update=needs_update,
            reason=reason,
        )

    @staticmethod
    def _load_tomorrow_star_run_stats(trade_date: str) -> dict[str, int]:
        with SessionLocal() as db:
            run = (
                db.query(TomorrowStarRun)
                .filter(TomorrowStarRun.pick_date == datetime.fromisoformat(trade_date).date())
                .first()
            )
            if run is None:
                return {
                    "candidate_count": 0,
                    "analysis_count": 0,
                    "trend_start_count": 0,
                    "consecutive_candidate_count": 0,
                }
            return {
                "candidate_count": int(run.candidate_count or 0),
                "analysis_count": int(run.analysis_count or 0),
                "trend_start_count": int(run.trend_start_count or 0),
                "consecutive_candidate_count": int(run.consecutive_candidate_count or 0),
            }

    def run(
        self,
        *,
        target_trade_date: Optional[str] = None,
        reviewer: str = DEFAULT_REVIEWER,
        window_size: int = DEFAULT_WINDOW_SIZE,
        force: bool = False,
    ) -> dict[str, Any]:
        total_started_at = time.perf_counter()
        freshness_started_at = time.perf_counter()
        MarketService.start_update()
        try:
            freshness = self.assess_freshness(target_trade_date=target_trade_date)
            freshness_elapsed = round(max(0.0, time.perf_counter() - freshness_started_at), 3)
            self._ensure_latest_trade_date_ready_for_retry(freshness.latest_trade_date)

            self.log.info("最新性检查: %s", freshness.reason)
            self.log.info(
                "最新性详情 latest_trade_date=%s latest_db_date=%s latest_csv_date=%s needs_update=%s",
                freshness.latest_trade_date,
                freshness.latest_db_date,
                freshness.latest_csv_date,
                freshness.needs_update,
            )

            if not freshness.target_trade_date:
                raise RuntimeError("无法确定目标交易日")

            if not force and not freshness.needs_update:
                total_elapsed = round(max(0.0, time.perf_counter() - total_started_at), 3)
                message = freshness.reason
                MarketService.finish_update(message)
                self._invalidate_runtime_caches()
                return {
                    "success": True,
                    "skipped": True,
                    "message": message,
                    "freshness": freshness.to_dict(),
                    "timings": {
                        "freshness_check": freshness_elapsed,
                        "total": total_elapsed,
                    },
                }

            trade_date = freshness.target_trade_date
            progress_logger = DailyBatchProgressLogger(self.log)

            def progress_callback(payload: dict[str, Any]) -> None:
                progress_logger(payload)
                stage = str(payload.get("stage") or "daily_batch_prepare")
                progress = int(payload.get("progress", payload.get("percent", 0)) or 0)
                self._push_market_state(
                    {
                        "task_type": "daily_batch_update",
                        "mode": "daily_batch",
                        "target_trade_date": trade_date,
                        "stage_label": "按交易日批量刷新",
                        **payload,
                        "stage": stage,
                        "progress": progress,
                    }
                )

            batch_result: dict[str, Any] | None = None
            batch_timings: dict[str, float] = {}
            if freshness.needs_market_update or force:
                self.log.info("开始按交易日批量更新 trade_date=%s", trade_date)
                with DailyBatchUpdateService(token=self.token) as batch_service:
                    batch_result = batch_service.update_trade_date(
                        trade_date,
                        source="background_cli",
                        progress_callback=progress_callback,
                    )
                batch_timings = progress_logger.finish()

                if not batch_result.get("ok"):
                    raise RuntimeError(str(batch_result.get("message") or f"{trade_date} 行情更新失败"))

                self.log.info(
                    "行情更新完成 trade_date=%s record_count=%s stock_count=%s db_stock_count=%s",
                    trade_date,
                    batch_result.get("record_count"),
                    batch_result.get("stock_count"),
                    batch_result.get("db_stock_count"),
                )
            else:
                self.log.info("跳过行情更新，直接重建明日之星 trade_date=%s", trade_date)

            tomorrow_started_at = time.perf_counter()
            self.log.info("开始重建明日之星 trade_date=%s reviewer=%s", trade_date, reviewer)
            self._push_market_state(
                {
                    "task_type": "daily_batch_update",
                    "mode": "daily_batch",
                    "target_trade_date": trade_date,
                    "stage_label": "按交易日批量刷新",
                    "stage": "daily_batch_rebuild_star",
                    "progress": 90,
                    "current": 1,
                    "total": 1,
                    "current_code": trade_date,
                    "message": f"重建 {trade_date} 明日之星候选与分析",
                }
            )
            tomorrow_result = maintain_tomorrow_star_for_trade_date(
                trade_date,
                reviewer=reviewer,
                source="background_cli",
                window_size=window_size,
            )
            tomorrow_elapsed = round(max(0.0, time.perf_counter() - tomorrow_started_at), 3)

            build_result = tomorrow_result.get("build") or {}
            if not build_result.get("success"):
                raise RuntimeError(
                    str(build_result.get("error") or build_result.get("status") or f"{trade_date} 明日之星重建失败")
                )

            tomorrow_stats = self._load_tomorrow_star_run_stats(trade_date)
            self.log.info(
                "明日之星完成 trade_date=%s candidate_count=%s analysis_count=%s trend_start_count=%s consecutive_candidate_count=%s elapsed=%.3fs",
                trade_date,
                tomorrow_stats["candidate_count"],
                tomorrow_stats["analysis_count"],
                tomorrow_stats["trend_start_count"],
                tomorrow_stats["consecutive_candidate_count"],
                tomorrow_elapsed,
            )

            latest_trade_date = freshness.latest_trade_date or trade_date
            if latest_trade_date:
                MarketService(token=self.token).update_cache(latest_trade_date)

            total_elapsed = round(max(0.0, time.perf_counter() - total_started_at), 3)
            timings = {
                "freshness_check": freshness_elapsed,
                **batch_timings,
                "tomorrow_star_rebuild": tomorrow_elapsed,
                "total": total_elapsed,
            }

            self.log.info("阶段耗时汇总: %s", timings)
            message = f"{trade_date} 更新完成"
            MarketService.finish_update(message)
            self._invalidate_runtime_caches()

            return {
                "success": True,
                "skipped": False,
                "message": message,
                "trade_date": trade_date,
                "freshness": freshness.to_dict(),
                "batch_result": batch_result,
                "tomorrow_star_result": tomorrow_result,
                "tomorrow_star_stats": tomorrow_stats,
                "timings": timings,
            }
        except Exception as exc:
            MarketService.fail_update(str(exc))
            self._invalidate_runtime_caches()
            raise
