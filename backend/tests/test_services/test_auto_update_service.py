from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.models import Config, Task
from app.services.auto_update_service import (
    AUTO_DAILY_UPDATE_ENABLED_KEY,
    AUTO_DAILY_UPDATE_TIME_KEY,
    AutoDailyUpdateScheduler,
    normalize_time_config,
    parse_bool_config,
)


def test_parse_bool_config() -> None:
    assert parse_bool_config("true") is True
    assert parse_bool_config("YES") is True
    assert parse_bool_config("0") is False
    assert parse_bool_config("") is False


def test_normalize_time_config() -> None:
    assert normalize_time_config("7:5") == "07:05"
    assert normalize_time_config("16:30") == "16:30"
    assert normalize_time_config("99:99") == "16:30"


@pytest.mark.asyncio
async def test_scheduler_starts_auto_daily_batch_task(test_db, monkeypatch) -> None:
    import app.services.auto_update_service as auto_update_module

    test_db.add(Config(key=AUTO_DAILY_UPDATE_ENABLED_KEY, value="true"))
    test_db.add(Config(key=AUTO_DAILY_UPDATE_TIME_KEY, value="16:30"))
    test_db.commit()

    freshness = SimpleNamespace(
        latest_trade_date="2026-05-19",
        needs_update=True,
        reason="数据库最新日期落后于 2026-05-19",
    )
    monkeypatch.setattr(
        auto_update_module.BackgroundLatestTradeDayUpdateService,
        "assess_freshness",
        lambda self: freshness,
    )
    monkeypatch.setattr(
        auto_update_module.TushareService,
        "is_trade_date_data_ready",
        lambda self, trade_date: True,
    )

    captured: dict[str, object] = {}

    async def fake_create_task(self, task_type: str, params: dict) -> dict:
        captured["task_type"] = task_type
        captured["params"] = params
        return {"task_id": 88, "existing": False}

    monkeypatch.setattr(auto_update_module.TaskService, "create_task", fake_create_task)

    scheduler = AutoDailyUpdateScheduler(session_factory=lambda: test_db)
    outcome = await scheduler.run_once(datetime(2026, 5, 19, 16, 31, tzinfo=ZoneInfo("Asia/Shanghai")))

    assert outcome["action"] == "started"
    assert captured["task_type"] == auto_update_module.TaskService.DAILY_BATCH_UPDATE_TASK_TYPE
    assert captured["params"] == {
        "trade_date": "2026-05-19",
        "source": "auto_daily_update",
        "trigger_source": "auto",
        "scheduled_time": "16:30",
    }


@pytest.mark.asyncio
async def test_scheduler_sets_retry_when_tushare_data_not_ready(test_db, monkeypatch) -> None:
    import app.services.auto_update_service as auto_update_module

    test_db.add(Config(key=AUTO_DAILY_UPDATE_ENABLED_KEY, value="true"))
    test_db.add(Config(key=AUTO_DAILY_UPDATE_TIME_KEY, value="16:30"))
    test_db.commit()

    freshness = SimpleNamespace(
        latest_trade_date="2026-05-19",
        needs_update=True,
        reason="数据库最新日期落后于 2026-05-19",
    )
    monkeypatch.setattr(
        auto_update_module.BackgroundLatestTradeDayUpdateService,
        "assess_freshness",
        lambda self: freshness,
    )
    monkeypatch.setattr(
        auto_update_module.TushareService,
        "is_trade_date_data_ready",
        lambda self, trade_date: False,
    )

    async def unexpected_create_task(self, task_type: str, params: dict) -> dict:
        raise AssertionError("should not create task before Tushare data is ready")

    monkeypatch.setattr(auto_update_module.TaskService, "create_task", unexpected_create_task)

    scheduler = AutoDailyUpdateScheduler(session_factory=lambda: test_db)
    outcome = await scheduler.run_once(datetime(2026, 5, 19, 16, 31, tzinfo=ZoneInfo("Asia/Shanghai")))

    assert outcome["action"] == "retry_scheduled"
    assert outcome["trade_date"] == "2026-05-19"
    assert scheduler._retry_trade_date == "2026-05-19"
    assert scheduler._next_retry_at is not None


@pytest.mark.asyncio
async def test_scheduler_restarts_after_completed_auto_task_when_latest_metrics_still_incomplete(test_db, monkeypatch) -> None:
    import app.services.auto_update_service as auto_update_module

    test_db.add(Config(key=AUTO_DAILY_UPDATE_ENABLED_KEY, value="true"))
    test_db.add(Config(key=AUTO_DAILY_UPDATE_TIME_KEY, value="16:30"))
    test_db.add(
        Task(
            task_type=auto_update_module.TaskService.DAILY_BATCH_UPDATE_TASK_TYPE,
            trigger_source="auto",
            status="completed",
            task_stage="daily_batch_completed",
            params_json={"trade_date": "2026-05-19"},
            progress=100,
            summary="按交易日批量刷新 / trade_date=2026-05-19",
        )
    )
    test_db.commit()

    freshness = SimpleNamespace(
        latest_trade_date="2026-05-19",
        needs_update=True,
        reason="数据库最新日期指标不完整",
    )
    monkeypatch.setattr(
        auto_update_module.BackgroundLatestTradeDayUpdateService,
        "assess_freshness",
        lambda self: freshness,
    )
    monkeypatch.setattr(
        auto_update_module.TushareService,
        "is_trade_date_data_ready",
        lambda self, trade_date: True,
    )

    captured: dict[str, object] = {}

    async def fake_create_task(self, task_type: str, params: dict) -> dict:
        captured["task_type"] = task_type
        captured["params"] = params
        return {"task_id": 99, "existing": False}

    monkeypatch.setattr(auto_update_module.TaskService, "create_task", fake_create_task)

    scheduler = AutoDailyUpdateScheduler(session_factory=lambda: test_db)
    outcome = await scheduler.run_once(datetime(2026, 5, 19, 17, 45, tzinfo=ZoneInfo("Asia/Shanghai")))

    assert outcome["action"] == "started"
    assert outcome["task_id"] == 99
    assert captured["task_type"] == auto_update_module.TaskService.DAILY_BATCH_UPDATE_TASK_TYPE
    assert captured["params"] == {
        "trade_date": "2026-05-19",
        "source": "auto_daily_update",
        "trigger_source": "auto",
        "scheduled_time": "16:30",
    }
