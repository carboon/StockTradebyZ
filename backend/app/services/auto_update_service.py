"""Automatic daily update scheduling and configuration helpers."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import Config, Task
from app.services.background_update_service import BackgroundLatestTradeDayUpdateService
from app.services.task_service import TaskService
from app.services.tushare_service import TushareService

AUTO_DAILY_UPDATE_ENABLED_KEY = "auto_daily_update_enabled"
AUTO_DAILY_UPDATE_TIME_KEY = "auto_daily_update_time"
DEFAULT_AUTO_DAILY_UPDATE_TIME = "16:30"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
AUTO_UPDATE_CHECK_INTERVAL_SECONDS = 60
AUTO_UPDATE_RETRY_DELAY_MINUTES = 10
AUTO_UPDATE_ACTIVE_TASK_TYPES = (
    TaskService.DAILY_BATCH_UPDATE_TASK_TYPE,
    TaskService.INCREMENTAL_UPDATE_TASK_TYPE,
    "full_update",
    TaskService.RECENT_120_REBUILD_TASK_TYPE,
)
AUTO_UPDATE_LOG_DIR = Path(settings.logs_dir) / "auto-update"
AUTO_UPDATE_LOG_FILE = AUTO_UPDATE_LOG_DIR / "auto-update.log"


def _build_auto_update_logger() -> logging.Logger:
    AUTO_UPDATE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("app.auto_update")
    logger.setLevel(logging.INFO)
    logger.propagate = True

    target_filename = str(AUTO_UPDATE_LOG_FILE)
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == target_filename:
            return logger

    handler = logging.FileHandler(AUTO_UPDATE_LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


AUTO_UPDATE_LOGGER = _build_auto_update_logger()


@dataclass(frozen=True)
class AutoUpdateSettings:
    enabled: bool
    scheduled_time: str


def parse_bool_config(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def normalize_time_config(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_AUTO_DAILY_UPDATE_TIME

    parts = text.split(":")
    if len(parts) != 2:
        return DEFAULT_AUTO_DAILY_UPDATE_TIME

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return DEFAULT_AUTO_DAILY_UPDATE_TIME

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return DEFAULT_AUTO_DAILY_UPDATE_TIME
    return f"{hour:02d}:{minute:02d}"


def normalize_auto_update_config_value(key: str, value: Any) -> str:
    normalized_key = str(key or "").strip().lower()
    if normalized_key == AUTO_DAILY_UPDATE_ENABLED_KEY:
        return "true" if parse_bool_config(value) else "false"
    if normalized_key == AUTO_DAILY_UPDATE_TIME_KEY:
        return normalize_time_config(value)
    return str(value or "")


def get_config_default_value(key: str) -> str:
    normalized_key = str(key or "").strip().lower()
    if normalized_key == AUTO_DAILY_UPDATE_ENABLED_KEY:
        return "false"
    if normalized_key == AUTO_DAILY_UPDATE_TIME_KEY:
        return DEFAULT_AUTO_DAILY_UPDATE_TIME
    return ""


def load_auto_update_settings(db: Session) -> AutoUpdateSettings:
    rows = (
        db.query(Config.key, Config.value)
        .filter(Config.key.in_([AUTO_DAILY_UPDATE_ENABLED_KEY, AUTO_DAILY_UPDATE_TIME_KEY]))
        .all()
    )
    values = {str(key): str(value) for key, value in rows if key}
    return AutoUpdateSettings(
        enabled=parse_bool_config(values.get(AUTO_DAILY_UPDATE_ENABLED_KEY, get_config_default_value(AUTO_DAILY_UPDATE_ENABLED_KEY))),
        scheduled_time=normalize_time_config(values.get(AUTO_DAILY_UPDATE_TIME_KEY, get_config_default_value(AUTO_DAILY_UPDATE_TIME_KEY))),
    )


class AutoDailyUpdateScheduler:
    """Application-level daily update scheduler."""

    def __init__(
        self,
        *,
        manager: Any = None,
        session_factory=SessionLocal,
        log: Optional[logging.Logger] = None,
    ) -> None:
        self.manager = manager
        self._session_factory = session_factory
        self.log = log or AUTO_UPDATE_LOGGER
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._next_retry_at: datetime | None = None
        self._retry_trade_date: str | None = None
        self._last_outcome_signature: str | None = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="auto-daily-update-scheduler")

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._stop_event = None

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log.exception("自动更新调度执行失败: %s", exc)

            if self._stop_event is None:
                return
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=AUTO_UPDATE_CHECK_INTERVAL_SECONDS,
                )
                return
            except asyncio.TimeoutError:
                continue

    async def run_once(self, now: Optional[datetime] = None) -> dict[str, Any]:
        current = now.astimezone(BEIJING_TZ) if now else datetime.now(BEIJING_TZ)
        db = self._session_factory()
        try:
            settings_obj = load_auto_update_settings(db)
            if not settings_obj.enabled:
                self._clear_retry()
                return self._finalize_outcome({
                    "action": "disabled",
                    "enabled": False,
                    "scheduled_time": settings_obj.scheduled_time,
                })

            if self._has_blocking_active_task(db):
                return self._finalize_outcome({
                    "action": "busy",
                    "enabled": True,
                    "scheduled_time": settings_obj.scheduled_time,
                })

            freshness = BackgroundLatestTradeDayUpdateService(log=self.log).assess_freshness()
            latest_trade_date = str(freshness.latest_trade_date or "")
            today_text = current.date().isoformat()
            if not latest_trade_date or latest_trade_date != today_text:
                if self._retry_trade_date and self._retry_trade_date != today_text:
                    self._clear_retry()
                return self._finalize_outcome({
                    "action": "not_trade_day",
                    "enabled": True,
                    "scheduled_time": settings_obj.scheduled_time,
                    "latest_trade_date": latest_trade_date or None,
                })

            scheduled_at = self._scheduled_datetime(current.date(), settings_obj.scheduled_time)
            retry_due = bool(
                self._retry_trade_date == today_text
                and self._next_retry_at is not None
                and current >= self._next_retry_at
            )
            if current < scheduled_at and not retry_due:
                return self._finalize_outcome({
                    "action": "waiting",
                    "enabled": True,
                    "scheduled_time": settings_obj.scheduled_time,
                    "scheduled_at": scheduled_at.isoformat(),
                })

            if not freshness.needs_update:
                self._clear_retry()
                return self._finalize_outcome({
                    "action": "up_to_date",
                    "enabled": True,
                    "scheduled_time": settings_obj.scheduled_time,
                    "trade_date": today_text,
                    "reason": freshness.reason,
                })

            if not TushareService().is_trade_date_data_ready(today_text):
                retry_at = current + timedelta(minutes=AUTO_UPDATE_RETRY_DELAY_MINUTES)
                self._retry_trade_date = today_text
                self._next_retry_at = retry_at
                return self._finalize_outcome({
                    "action": "retry_scheduled",
                    "enabled": True,
                    "scheduled_time": settings_obj.scheduled_time,
                    "trade_date": today_text,
                    "retry_at": retry_at.isoformat(),
                })

            task_service = TaskService(db, manager=self.manager)
            result = await task_service.create_task(
                TaskService.DAILY_BATCH_UPDATE_TASK_TYPE,
                {
                    "trade_date": today_text,
                    "source": "auto_daily_update",
                    "trigger_source": "auto",
                    "scheduled_time": settings_obj.scheduled_time,
                },
            )
            self._clear_retry()
            return self._finalize_outcome({
                "action": "started",
                "enabled": True,
                "scheduled_time": settings_obj.scheduled_time,
                "trade_date": today_text,
                "task_id": result.get("task_id"),
                "existing": bool(result.get("existing")),
            })
        finally:
            db.close()

    def _scheduled_datetime(self, target_date: date, schedule_text: str) -> datetime:
        normalized = normalize_time_config(schedule_text)
        hour, minute = [int(part) for part in normalized.split(":")]
        return datetime.combine(target_date, time(hour=hour, minute=minute), tzinfo=BEIJING_TZ)

    def _has_blocking_active_task(self, db: Session) -> bool:
        task = (
            db.query(Task.id)
            .filter(
                Task.task_type.in_(AUTO_UPDATE_ACTIVE_TASK_TYPES),
                Task.status.in_(["pending", "running"]),
            )
            .order_by(Task.created_at.desc(), Task.id.desc())
            .first()
        )
        return task is not None

    def _clear_retry(self) -> None:
        self._retry_trade_date = None
        self._next_retry_at = None

    def _finalize_outcome(self, outcome: dict[str, Any]) -> dict[str, Any]:
        signature = "|".join(
            str(outcome.get(key))
            for key in ("action", "trade_date", "task_id", "task_status", "retry_at", "reason")
        )
        if signature != self._last_outcome_signature:
            action = str(outcome.get("action") or "")
            if action in {"started", "retry_scheduled", "up_to_date", "busy"}:
                self.log.info("自动更新调度结果: %s", outcome)
            self._last_outcome_signature = signature
        return outcome
