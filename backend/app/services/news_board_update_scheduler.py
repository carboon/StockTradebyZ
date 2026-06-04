"""News board background update scheduler.

Polls every N seconds (default 300 = 5 min) and runs one update cycle,
using a Redis lock to ensure only one worker executes at a time.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from app.config import settings
from app.services.news_board_cache_service import NewsBoardCacheService

logger = logging.getLogger(__name__)

_DISABLE_ENV = os.environ.get("DISABLE_NEWS_BOARD_SCHEDULER", "").strip().lower()
_DISABLED_FLAG = _DISABLE_ENV in {"1", "true", "yes", "on"}


class NewsBoardUpdateScheduler:
    """Background task that periodically refreshes the news board cache."""

    def __init__(self) -> None:
        self._task: asyncio.Task[Any] | None = None
        self._service = NewsBoardCacheService()
        self._interval = settings.news_board_update_interval_seconds

    def start(self) -> None:
        """Start the scheduler loop. No-op if already running or disabled."""
        if self._task is not None:
            return
        if settings.disable_news_board_scheduler or _DISABLED_FLAG:
            logger.info("NewsBoardUpdateScheduler 已通过配置禁用")
            return
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NewsBoardUpdateScheduler 已启动，间隔 %d 秒", self._interval)

    async def stop(self) -> None:
        """Cancel the background loop and wait for graceful shutdown."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("NewsBoardUpdateScheduler 已停止")

    async def run_once(self) -> dict[str, Any]:
        """Execute one update cycle synchronously. Blocks the caller."""
        return await asyncio.to_thread(self._service.update_once)

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("NewsBoardUpdateScheduler 更新异常，下一轮继续")
