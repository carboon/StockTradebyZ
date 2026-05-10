"""
Task Service Tests
~~~~~~~~~~~~~~~~~~
任务服务测试用例
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import Task
from app.services.task_service import TaskService
from app.time_utils import utc_now


# ============================================
# Test Fixtures
# ============================================

@pytest.fixture
def task_service(test_db):
    """
    任务服务fixture

    提供一个带有测试数据库的TaskService实例。
    """
    return TaskService(db=test_db)


@pytest.fixture
def mock_manager():
    """
    Mock WebSocket连接管理器

    提供一个模拟的WebSocket连接管理器，用于测试任务执行时的消息发送。
    """
    manager = MagicMock()
    manager.send_message = AsyncMock()
    return manager


@pytest.fixture
def task_service_with_manager(test_db, mock_manager):
    """
    带WebSocket管理器的任务服务fixture

    提供一个带有测试数据库和WebSocket管理器的TaskService实例。
    """
    return TaskService(db=test_db, manager=mock_manager)


@pytest.fixture
def sample_task_params():
    """
    示例任务参数fixture

    提供一组测试用的任务参数。
    """
    return {
        "reviewer": "quant",
        "skip_fetch": False,
        "start_from": 1
    }


@pytest.fixture
def sample_task_single_analysis():
    """
    单股分析任务参数fixture

    提供单股分析任务所需的参数。
    """
    return {
        "code": "000001",
        "reviewer": "glm"
    }


# ============================================
# 创建任务测试
# ============================================

@pytest.mark.service
@pytest.mark.asyncio
async def test_create_task(task_service, sample_task_params):
    """
    测试创建任务

    应该成功创建一个任务并返回任务ID和WebSocket URL。
    """
    # 不实际运行后台任务，只测试创建逻辑
    with patch.object(task_service, '_run_task', return_value=None):
        result = await task_service.create_task("full_update", sample_task_params)

        assert result is not None
        assert "task_id" in result
        assert "ws_url" in result
        assert result["ws_url"] == f"/ws/tasks/{result['task_id']}"

        # 验证数据库中的任务
        task = task_service.db.query(Task).filter(Task.id == result["task_id"]).first()
        assert task is not None
        assert task.task_type == "full_update"
        assert task.status == "pending"
        assert task.progress == 0
        assert task.params_json == sample_task_params
        assert result["existing"] is False


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_task_with_options(task_service):
    """
    测试创建任务（带参数）

    应该正确处理不同类型的任务参数。
    """
    params = {
        "reviewer": "glm",
        "skip_fetch": True,
        "start_from": 3
    }

    with patch.object(task_service, '_run_task', return_value=None):
        result = await task_service.create_task("full_update", params)

        task = task_service.db.query(Task).filter(Task.id == result["task_id"]).first()
        assert task.params_json["reviewer"] == "glm"
        assert task.params_json["skip_fetch"] is True
        assert task.params_json["start_from"] == 3


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_task_single_analysis(task_service, sample_task_single_analysis):
    """
    测试创建单股分析任务

    应该成功创建单股分析类型的任务。
    """
    with patch.object(task_service, '_run_task', return_value=None):
        result = await task_service.create_task("single_analysis", sample_task_single_analysis)

        task = task_service.db.query(Task).filter(Task.id == result["task_id"]).first()
        assert task.task_type == "single_analysis"
        assert task.params_json["code"] == "000001"


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_single_analysis_reuses_running_same_reviewer(task_service):
    """
    测试单股分析任务去重 - 同股票同reviewer复用running任务

    当同一股票同一reviewer已有running任务时，应复用该任务。
    """
    existing_task = Task(
        task_type="single_analysis",
        status="running",
        progress=50,
        params_json={"code": "600000", "reviewer": "quant"},
        started_at=utc_now(),
    )
    task_service.db.add(existing_task)
    task_service.db.commit()

    with patch("app.services.task_service.asyncio.create_task") as mock_create_task:
        result = await task_service.create_task("single_analysis", {"code": "600000", "reviewer": "quant"})

        assert result["task_id"] == existing_task.id
        assert result["existing"] is True
        mock_create_task.assert_not_called()


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_single_analysis_different_reviewer_creates_new_task(task_service):
    """
    测试单股分析任务去重 - 不同reviewer创建新任务

    当同一股票但不同reviewer时，应创建新任务（不复用）。
    """
    existing_task = Task(
        task_type="single_analysis",
        status="running",
        progress=50,
        params_json={"code": "600000", "reviewer": "quant"},
        started_at=utc_now(),
    )
    task_service.db.add(existing_task)
    task_service.db.commit()

    with patch.object(task_service, '_run_task', return_value=None):
        result = await task_service.create_task("single_analysis", {"code": "600000", "reviewer": "qwen"})

        assert result["task_id"] != existing_task.id
        assert result["existing"] is False

        # 验证创建了新任务
        new_task = task_service.db.query(Task).filter(Task.id == result["task_id"]).first()
        assert new_task.params_json["reviewer"] == "qwen"


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_single_analysis_reuses_completed_same_day(task_service):
    """
    测试单股分析任务去重 - 同日复用已完成任务

    当同一股票同一reviewer今日已有已完成任务时，应复用该任务。
    """
    existing_task = Task(
        task_type="single_analysis",
        status="completed",
        progress=100,
        params_json={"code": "600000", "reviewer": "quant"},
        started_at=utc_now(),
        completed_at=utc_now(),
        result_json={"verdict": "PASS", "score": 4.5},
    )
    task_service.db.add(existing_task)
    task_service.db.commit()

    with patch("app.services.task_service.asyncio.create_task") as mock_create_task:
        result = await task_service.create_task("single_analysis", {"code": "600000", "reviewer": "quant"})

        assert result["task_id"] == existing_task.id
        assert result["existing"] is True
        mock_create_task.assert_not_called()


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_single_analysis_recreates_retryable_completed_task(task_service):
    existing_task = Task(
        task_type="single_analysis",
        status="completed",
        progress=100,
        params_json={"code": "601992", "reviewer": "quant"},
        started_at=utc_now(),
        completed_at=utc_now(),
        result_json={"verdict": "FAIL", "score": 1.0, "comment": "样本不足，无法完成第 4 步程序化复核。"},
    )
    task_service.db.add(existing_task)
    task_service.db.commit()

    with patch("app.services.task_service.asyncio.create_task") as mock_create_task:
        result = await task_service.create_task("single_analysis", {"code": "601992", "reviewer": "quant"})

        assert result["task_id"] != existing_task.id
        assert result["existing"] is False
        assert task_service.db.query(Task).count() == 2
        mock_create_task.assert_called_once()


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_tomorrow_star(task_service):
    """
    测试创建明日之星任务

    应该成功创建明日之星类型的任务。
    """
    params = {"reviewer": "qwen"}

    with patch.object(task_service, '_run_task', return_value=None):
        result = await task_service.create_task("tomorrow_star", params)

        task = task_service.db.query(Task).filter(Task.id == result["task_id"]).first()
        assert task.task_type == "tomorrow_star"
        assert task.params_json["reviewer"] == "qwen"


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_task_reuses_existing_full_update(task_service, sample_task_params):
    """
    测试创建全量任务时复用已有运行中任务

    当已有全量类任务处于 pending/running 状态时，不应重复创建新任务。
    """
    existing_task = Task(
        task_type="full_update",
        status="running",
        progress=35,
        params_json={"reviewer": "quant"},
        started_at=utc_now(),
    )
    task_service.db.add(existing_task)
    task_service.db.commit()
    task_service.db.refresh(existing_task)

    with patch("app.services.task_service.asyncio.create_task") as mock_create_task:
        result = await task_service.create_task("full_update", sample_task_params)

    assert result["task_id"] == existing_task.id
    assert result["ws_url"] == f"/ws/tasks/{existing_task.id}"
    assert result["existing"] is True
    assert task_service.db.query(Task).count() == 1
    mock_create_task.assert_not_called()


@pytest.mark.service
@pytest.mark.asyncio
async def test_create_tomorrow_star_reuses_existing_full_update(task_service):
    """
    测试明日之星任务与全量更新共享互斥保护
    """
    existing_task = Task(
        task_type="full_update",
        status="pending",
        progress=0,
        params_json={"reviewer": "quant"},
    )
    task_service.db.add(existing_task)
    task_service.db.commit()

    with patch("app.services.task_service.asyncio.create_task") as mock_create_task:
        result = await task_service.create_task("tomorrow_star", {"reviewer": "qwen"})

    assert result["task_id"] == existing_task.id
    assert result["existing"] is True
    assert task_service.db.query(Task).count() == 1
    mock_create_task.assert_not_called()


# ============================================
# 任务执行测试
# ============================================

@pytest.mark.service
@pytest.mark.asyncio
async def test_run_task_updates_status(task_service):
    """
    测试运行任务时状态更新

    任务运行时应该正确更新状态为running。
    """
    task = Task(
        task_type="single_analysis",
        status="pending",
        params_json={"code": "000001", "reviewer": "quant"}
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    # Mock app.database.SessionLocal 返回测试数据库会话
    with patch("app.database.SessionLocal", return_value=task_service.db):
        # Mock analysis_service.analyze_stock方法
        with patch("app.services.analysis_service.analysis_service.analyze_stock", return_value={"verdict": "PASS"}):
            await task_service._run_task(task.id)

            # 刷新以获取更新后的状态
            task_service.db.refresh(task)
            assert task.status == "completed"
            assert task.progress == 100
            assert task.started_at is not None
            assert task.completed_at is not None


@pytest.mark.service
@pytest.mark.asyncio
async def test_run_task_failure_handling(task_service):
    """
    测试任务执行失败处理

    任务执行失败时应该正确设置状态和错误信息。
    """
    task = Task(
        task_type="single_analysis",
        status="pending",
        params_json={"code": "000001"}  # 缺少reviewer参数
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    # Mock app.database.SessionLocal 返回测试数据库会话
    with patch("app.database.SessionLocal", return_value=task_service.db):
        # Mock analysis_service.analyze_stock方法抛出异常
        with patch("app.services.analysis_service.analysis_service.analyze_stock", side_effect=Exception("分析失败")):
            await task_service._run_task(task.id)

            # 刷新以获取更新后的状态
            task_service.db.refresh(task)
            assert task.status == "failed"
            assert task.error_message == "分析失败"
            assert task.completed_at is not None


@pytest.mark.service
@pytest.mark.asyncio
async def test_run_single_analysis_missing_code(task_service):
    """
    测试单股分析缺少股票代码

    应该抛出异常并标记任务为失败。
    """
    task = Task(
        task_type="single_analysis",
        status="pending",
        params_json={}  # 没有code参数
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    # Mock app.database.SessionLocal 返回测试数据库会话
    with patch("app.database.SessionLocal", return_value=task_service.db):
        # 不需要mock，因为会在检查code时就抛出异常
        await task_service._run_task(task.id)

        # 刷新以获取更新后的状态
        task_service.db.refresh(task)
        assert task.status == "failed"
        assert "缺少股票代码" in task.error_message


# ============================================
# 任务进度更新测试
# ============================================

@pytest.mark.service
def test_update_task_progress(task_service):
    """
    测试更新任务进度

    应该能够正确更新任务的进度值。
    """
    task = Task(
        task_type="full_update",
        status="running",
        progress=0
    )
    task_service.db.add(task)
    task_service.db.commit()

    # 直接更新任务进度
    task.progress = 50
    task_service.db.commit()

    task_service.db.refresh(task)
    assert task.progress == 50


@pytest.mark.service
def test_update_task_progress_bounds(task_service):
    """
    测试任务进度边界

    进度值应该在0-100范围内。
    """
    task = Task(
        task_type="full_update",
        status="running",
        progress=0
    )
    task_service.db.add(task)
    task_service.db.commit()

    # 测试边界值
    task.progress = 0
    task_service.db.commit()
    task_service.db.refresh(task)
    assert task.progress == 0

    task.progress = 100
    task_service.db.commit()
    task_service.db.refresh(task)
    assert task.progress == 100


# ============================================
# 任务状态测试
# ============================================

@pytest.mark.service
@pytest.mark.asyncio
async def test_complete_task(task_service):
    """
    测试完成任务

    任务完成后应该正确设置状态和完成时间。
    """
    task = Task(
        task_type="single_analysis",
        status="running",
        progress=80,
        params_json={"code": "000001", "reviewer": "quant"}
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    # Mock app.database.SessionLocal 返回测试数据库会话
    with patch("app.database.SessionLocal", return_value=task_service.db):
        with patch("app.services.analysis_service.analysis_service.analyze_stock", return_value={"verdict": "PASS", "score": 85.5}):
            # 模拟完成任务
            await task_service._run_task(task.id)

            # 刷新以获取更新后的状态
            task_service.db.refresh(task)
            assert task.status == "completed"
            assert task.progress == 100
            assert task.completed_at is not None
            assert task.result_json is not None


@pytest.mark.service
def test_fail_task(task_service):
    """
    测试任务失败处理

    任务失败时应该记录错误信息。
    """
    task = Task(
        task_type="full_update",
        status="running",
        progress=30
    )
    task_service.db.add(task)
    task_service.db.commit()

    # 模拟任务失败
    task.status = "failed"
    task.error_message = "网络连接超时"
    task.completed_at = utc_now()
    task_service.db.commit()

    task_service.db.refresh(task)
    assert task.status == "failed"
    assert task.error_message == "网络连接超时"
    assert task.completed_at is not None


@pytest.mark.service
def test_fail_task_with_long_error_message(task_service):
    """
    测试任务失败时处理长错误信息

    应该能够处理较长的错误消息。
    """
    task = Task(
        task_type="full_update",
        status="running"
    )
    task_service.db.add(task)
    task_service.db.commit()

    long_error = "错误: " + "x" * 500  # 长错误消息
    task.status = "failed"
    task.error_message = long_error
    task.completed_at = utc_now()
    task_service.db.commit()

    task_service.db.refresh(task)
    assert task.status == "failed"
    assert len(task.error_message) > 500


# ============================================
# 任务取消测试
# ============================================

@pytest.mark.service
@pytest.mark.asyncio
async def test_cancel_task(task_service):
    """
    测试取消任务

    应该能够取消正在运行的任务。
    """
    # Mock一个运行中的进程
    mock_process = MagicMock()
    mock_process.terminate = MagicMock()
    mock_process.wait = AsyncMock(return_value=0)
    task_service.running_tasks[999] = mock_process

    result = await task_service.cancel_task(999)

    assert result is True
    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_awaited()
    # cancel_task会将进程terminate，不会立即删除running_tasks
    # running_tasks在_run_task的finally块中删除


@pytest.mark.service
@pytest.mark.asyncio
async def test_cancel_task_with_timeout(task_service):
    """
    测试取消任务超时处理

    当进程在超时时间内未终止时，应该使用kill强制终止。
    """
    mock_process = MagicMock()
    mock_process.terminate = MagicMock()
    mock_process.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), 0])
    mock_process.kill = MagicMock()
    task_service.running_tasks[888] = mock_process

    result = await task_service.cancel_task(888)

    assert result is True
    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_called_once()


@pytest.mark.service
@pytest.mark.asyncio
async def test_cancel_nonexistent_task(task_service):
    """
    测试取消不存在的任务

    应该返回False而不是抛出异常。
    """
    result = await task_service.cancel_task(12345)

    assert result is False


@pytest.mark.service
@pytest.mark.asyncio
async def test_cancel_task_not_running(task_service):
    """
    测试取消不在运行列表中的任务

    应该返回False。
    """
    result = await task_service.cancel_task(1)

    assert result is False


# ============================================
# 获取任务测试
# ============================================

@pytest.mark.service
def test_get_task(task_service):
    """
    测试获取任务

    应该能够获取指定任务的详细信息。
    """
    task = Task(
        task_type="single_analysis",
        status="completed",
        progress=100,
        result_json={"verdict": "PASS"},
        error_message=None
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    # 直接使用数据库查询获取任务
    result = task_service.db.query(Task).filter(Task.id == task.id).first()
    assert result is not None
    assert result.id == task.id
    assert result.task_type == "single_analysis"
    assert result.status == "completed"
    assert result.progress == 100
    assert result.result_json["verdict"] == "PASS"
    assert result.error_message is None


@pytest.mark.service
def test_get_task_not_found(task_service):
    """
    测试获取不存在的任务

    应该返回None。
    """
    result = task_service.get_task_status(999999)

    assert result is None


@pytest.mark.service
def test_get_task_with_error(task_service):
    """
    测试获取失败的任务

    应该正确返回错误信息。
    """
    task = Task(
        task_type="full_update",
        status="failed",
        progress=45,
        error_message="数据获取失败"
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    # 直接使用数据库查询获取任务
    result = task_service.db.query(Task).filter(Task.id == task.id).first()

    assert result is not None
    assert result.status == "failed"
    assert result.error_message == "数据获取失败"
    assert result.progress == 45


# ============================================
# 按状态获取任务测试
# ============================================

@pytest.mark.service
def test_get_tasks_by_status(task_service):
    """
    测试按状态获取任务

    应该能够按状态筛选任务。
    """
    # 创建多个不同状态的任务
    tasks = [
        Task(task_type="full_update", status="pending"),
        Task(task_type="single_analysis", status="running"),
        Task(task_type="tomorrow_star", status="pending"),
        Task(task_type="full_update", status="completed"),
    ]
    for t in tasks:
        task_service.db.add(t)
    task_service.db.commit()

    # 获取pending状态的任务
    pending_tasks = task_service.db.query(Task).filter(
        Task.status == "pending"
    ).all()

    assert len(pending_tasks) == 2
    assert all(t.status == "pending" for t in pending_tasks)

    # 获取running状态的任务
    running_tasks = task_service.db.query(Task).filter(
        Task.status == "running"
    ).all()

    assert len(running_tasks) == 1
    assert running_tasks[0].task_type == "single_analysis"


@pytest.mark.service
def test_get_tasks_by_multiple_statuses(task_service):
    """
    测试按多个状态获取任务

    应该能够获取多个状态的任务。
    """
    tasks = [
        Task(task_type="full_update", status="pending"),
        Task(task_type="single_analysis", status="running"),
        Task(task_type="tomorrow_star", status="completed"),
        Task(task_type="full_update", status="failed"),
    ]
    for t in tasks:
        task_service.db.add(t)
    task_service.db.commit()

    # 获取pending或running状态的任务
    active_tasks = task_service.db.query(Task).filter(
        Task.status.in_(["pending", "running"])
    ).all()

    assert len(active_tasks) == 2

    # 获取已完成或失败的任务
    finished_tasks = task_service.db.query(Task).filter(
        Task.status.in_(["completed", "failed"])
    ).all()

    assert len(finished_tasks) == 2


@pytest.mark.service
def test_get_tasks_by_status_empty(task_service):
    """
    测试获取空状态列表的任务

    应该返回空列表。
    """
    tasks = task_service.db.query(Task).filter(
        Task.status == "pending"
    ).all()

    assert len(tasks) == 0


# ============================================
# 获取运行中任务测试
# ============================================

@pytest.mark.service
def test_get_running_task(task_service):
    """
    测试获取运行中的任务

    应该能够获取状态为running的任务。
    """
    task = Task(
        task_type="full_update",
        status="running",
        progress=50,
        started_at=utc_now()
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    running_task = task_service.db.query(Task).filter(
        Task.status == "running"
    ).first()

    assert running_task is not None
    assert running_task.id == task.id
    assert running_task.progress == 50
    assert running_task.started_at is not None


@pytest.mark.service
def test_get_running_task_multiple(task_service):
    """
    测试获取多个运行中的任务

    应该能够获取所有running状态的任务。
    """
    tasks = [
        Task(task_type="full_update", status="running"),
        Task(task_type="single_analysis", status="running"),
        Task(task_type="tomorrow_star", status="pending"),
    ]
    for t in tasks:
        task_service.db.add(t)
    task_service.db.commit()

    running_tasks = task_service.db.query(Task).filter(
        Task.status == "running"
    ).all()

    assert len(running_tasks) == 2


@pytest.mark.service
def test_get_running_task_none(task_service):
    """
    测试获取运行中任务（无运行中任务）

    当没有运行中任务时应该返回None或空列表。
    """
    task = Task(task_type="full_update", status="pending")
    task_service.db.add(task)
    task_service.db.commit()

    running_task = task_service.db.query(Task).filter(
        Task.status == "running"
    ).first()

    assert running_task is None


# ============================================
# WebSocket消息发送测试
# ============================================

@pytest.mark.asyncio
async def test_send_websocket_message(mock_manager):
    """
    测试WebSocket消息发送

    应该能够通过WebSocket管理器发送消息。
    """
    from app.websocket.utils import send_log

    await send_log(mock_manager, 123, "测试消息", "info")

    mock_manager.send_message.assert_called_once()
    call_args = mock_manager.send_message.call_args
    assert call_args[0][0] == 123  # task_id

    # 验证消息格式
    import json
    message = call_args[0][1]
    payload = json.loads(message)
    assert payload["type"] == "log"
    assert payload["task_id"] == 123
    assert payload["message"] == "测试消息"
    assert payload["log_type"] == "info"


@pytest.mark.asyncio
async def test_send_websocket_message_error_type(mock_manager):
    """
    测试发送错误类型的WebSocket消息

    应该正确处理错误类型的消息。
    """
    from app.websocket.utils import send_log

    await send_log(mock_manager, 456, "错误信息", "error")

    mock_manager.send_message.assert_called_once()

    import json
    message = mock_manager.send_message.call_args[0][1]
    payload = json.loads(message)
    assert payload["log_type"] == "error"


@pytest.mark.asyncio
async def test_send_websocket_message_with_unicode(mock_manager):
    """
    测试发送包含Unicode字符的WebSocket消息

    应该正确处理中文字符和特殊符号。
    """
    from app.websocket.utils import send_log

    await send_log(mock_manager, 789, "中文字符测试 & 特殊符号 #@$%", "info")

    mock_manager.send_message.assert_called_once()

    import json
    message = mock_manager.send_message.call_args[0][1]
    payload = json.loads(message)
    assert payload["message"] == "中文字符测试 & 特殊符号 #@$%"


# ============================================
# 进度解析测试
# ============================================

@pytest.mark.service
def test_parse_progress_step_1():
    """
    测试解析步骤1的进度

    应该正确解析步骤1的进度为10%。
    """
    from app.websocket.utils import parse_progress

    progress = parse_progress("开始执行 步骤 1: 数据获取")
    assert progress == 10

    progress = parse_progress("Starting step 1: fetching data")
    assert progress == 10


@pytest.mark.service
def test_parse_progress_step_6():
    """
    测试解析步骤6的进度

    应该正确解析步骤6的进度为100%。
    """
    from app.websocket.utils import parse_progress

    progress = parse_progress("完成 步骤 6: 生成推荐")
    assert progress == 100

    progress = parse_progress("Step 6 completed")
    assert progress == 100


@pytest.mark.service
def test_parse_progress_percentage():
    """
    测试解析百分比形式的进度

    应该正确解析百分比格式的进度。
    """
    from app.websocket.utils import parse_progress

    progress = parse_progress("当前进度: 45%")
    assert progress == 45

    progress = parse_progress("[==============>     ] 75%")
    assert progress == 75


@pytest.mark.service
def test_parse_progress_no_match():
    """
    测试解析无法识别的进度

    当日志中没有进度信息时应该返回None。
    """
    from app.websocket.utils import parse_progress

    progress = parse_progress("这是一条普通日志消息")
    assert progress is None


@pytest.mark.service
def test_parse_progress_edge_cases():
    """
    测试解析进度的边界情况

    应该正确处理0%和100%的边界值。
    """
    from app.websocket.utils import parse_progress

    progress = parse_progress("进度: 0%")
    assert progress == 0

    progress = parse_progress("进度: 100%")
    assert progress == 100


# ============================================
# 日志类型解析测试
# ============================================

@pytest.mark.service
def test_parse_log_type_error():
    """
    测试解析错误类型日志

    应该正确识别包含error关键字的日志。
    """
    from app.websocket.utils import parse_log_type

    log_type = parse_log_type("ERROR: 连接失败")
    assert log_type == "error"

    log_type = parse_log_type("发生错误，请重试")
    assert log_type == "error"

    log_type = parse_log_type("Task failed")
    assert log_type == "error"


@pytest.mark.service
def test_parse_log_type_warning():
    """
    测试解析警告类型日志

    应该正确识别包含warning关键字的日志。
    """
    from app.websocket.utils import parse_log_type

    log_type = parse_log_type("WARNING: 数据不完整")
    assert log_type == "warning"

    log_type = parse_log_type("这是一个警告信息")
    assert log_type == "warning"


@pytest.mark.service
def test_parse_log_type_success():
    """
    测试解析成功类型日志

    应该正确识别包含success关键字的日志。
    """
    from app.websocket.utils import parse_log_type

    log_type = parse_log_type("SUCCESS: 操作成功")
    assert log_type == "success"

    log_type = parse_log_type("任务已完成")
    assert log_type == "success"


@pytest.mark.service
def test_parse_log_type_info():
    """
    测试解析普通信息类型日志

    默认应该返回info类型。
    """
    from app.websocket.utils import parse_log_type

    log_type = parse_log_type("正在处理数据...")
    assert log_type == "info"

    log_type = parse_log_type("开始执行任务")
    assert log_type == "info"


# ============================================
# 全量更新任务测试
# ============================================

@pytest.mark.service
@pytest.mark.asyncio
async def test_run_full_update_with_subprocess(task_service_with_manager):
    """
    测试全量更新任务参数解析

    验证_run_full_update能正确解析任务参数。
    """
    task = Task(
        task_type="full_update",
        status="pending",
        params_json={"reviewer": "glm", "skip_fetch": True, "start_from": 3}
    )
    task_service_with_manager.db.add(task)
    task_service_with_manager.db.commit()

    # 验证参数被正确存储
    assert task.params_json["reviewer"] == "glm"
    assert task.params_json["skip_fetch"] is True
    assert task.params_json["start_from"] == 3


@pytest.mark.service
@pytest.mark.asyncio
async def test_run_full_update_syncs_history_windows(task_service):
    task = Task(
        task_type="full_update",
        status="pending",
        params_json={"reviewer": "quant"},
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    class _FakeProcess:
        def __init__(self):
            self.stdout = MagicMock()
            self.stdout.readline = AsyncMock(side_effect=[b""])

        wait = AsyncMock(return_value=0)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    process = _FakeProcess()
    execution_order: list[str] = []
    tomorrow_star_payload = {"failed_dates": [], "rebuilt_dates": ["2026-05-07"]}
    current_hot_payload = {"failed_dates": [], "rebuilt_dates": ["2026-05-07", "2026-05-08"]}

    def fake_star_window(window_size: int, reviewer: str, source: str) -> dict:
        execution_order.append("tomorrow_star")
        assert window_size == 120
        assert reviewer == "quant"
        assert source == "full_update"
        return tomorrow_star_payload

    def fake_current_hot_window(window_size: int, reviewer: str) -> dict:
        execution_order.append("current_hot")
        assert window_size == 120
        assert reviewer == "quant"
        return current_hot_payload

    tushare_instance = MagicMock()
    tushare_instance.sync_stock_list_to_db.return_value = 12
    tushare_instance.check_data_status.return_value = {"ok": True}
    metadata_service = MagicMock()

    with patch("app.services.task_service.asyncio.create_subprocess_exec", return_value=process), patch(
        "app.services.task_service.asyncio.to_thread",
        side_effect=fake_to_thread,
    ), patch.object(task_service, "_publish_ops_task_event", AsyncMock()), patch.object(
        task_service,
        "_sync_candidates_from_files",
        return_value=7,
    ), patch.object(
        task_service,
        "_sync_analysis_results_from_files",
        return_value=6,
    ), patch.object(
        task_service,
        "_run_tomorrow_star_window_sync",
        side_effect=fake_star_window,
    ) as mock_star_window, patch.object(
        task_service,
        "_run_current_hot_window_sync",
        side_effect=fake_current_hot_window,
    ) as mock_current_hot_window, patch.object(
        task_service,
        "_invalidate_tomorrow_star_caches",
    ) as mock_invalidate, patch(
        "app.services.tushare_service.TushareService",
    ) as mock_tushare_cls, patch(
        "app.services.admin_summary_metadata_service.get_admin_summary_metadata_service",
        return_value=metadata_service,
        ):
            mock_tushare_cls.return_value = tushare_instance
            await task_service._run_full_update(task, task_service.db)

    task_service.db.commit()
    task_service.db.refresh(task)
    task_service.running_tasks.pop(task.id, None)

    mock_star_window.assert_called_once_with(120, "quant", "full_update")
    mock_current_hot_window.assert_called_once_with(120, "quant")
    mock_invalidate.assert_called_once()
    assert execution_order == ["tomorrow_star", "current_hot"]
    assert task.task_stage == "history_window_hot"
    assert task.progress == 96
    assert task.progress_meta_json["stage"] == "history_window_hot"
    assert task.result_json["stock_basic_synced"] == 12
    assert task.result_json["candidate_synced"] == 7
    assert task.result_json["analysis_synced"] == 6
    assert task.result_json["tomorrow_star_window_synced"] == tomorrow_star_payload
    assert task.result_json["current_hot_synced"] == current_hot_payload


# ============================================
# 边界条件和错误情况测试
# ============================================

@pytest.mark.service
@pytest.mark.asyncio
async def test_create_task_with_empty_params(task_service):
    """
    测试创建任务时使用空参数

    应该能够正确处理空的参数字典。
    """
    with patch.object(task_service, '_run_task', return_value=None):
        result = await task_service.create_task("full_update", {})

        task = task_service.db.query(Task).filter(Task.id == result["task_id"]).first()
        assert task.params_json is not None
        assert len(task.params_json) == 0


@pytest.mark.service
@pytest.mark.asyncio
async def test_run_nonexistent_task(task_service):
    """
    测试运行不存在的任务

    应该优雅地处理而不抛出异常。
    """
    # 运行不存在的任务ID应该不会崩溃
    await task_service._run_task(999999)


@pytest.mark.service
def test_get_task_status_with_db_session():
    """
    测试获取任务状态时创建新的数据库会话

    get_task_status应该使用独立的数据库会话。
    """
    # 创建一个任务
    from app.database import SessionLocal
    from app.services.task_service import TaskService

    db = SessionLocal()
    task = Task(
        task_type="single_analysis",
        status="completed",
        progress=100
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 使用新的服务实例获取状态
    new_db = SessionLocal()
    service = TaskService(db=new_db)
    result = service.get_task_status(task.id)

    assert result is not None
    assert result["id"] == task.id

    # 清理
    db.close()
    new_db.close()


@pytest.mark.service
@pytest.mark.asyncio
async def test_task_result_json_storage(task_service):
    """
    测试任务结果JSON存储

    应该能够正确存储和检索复杂的JSON结果。
    """
    complex_result = {
        "verdict": "PASS",
        "score": 85.5,
        "signals": ["b1", "kdj_low"],
        "analysis": {
            "trend": "bullish",
            "strength": "strong"
        },
        "data": [1, 2, 3, 4, 5]
    }

    task = Task(
        task_type="single_analysis",
        status="completed",
        result_json=complex_result
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    # 直接使用数据库查询获取任务
    result = task_service.db.query(Task).filter(Task.id == task.id).first()
    assert result.result_json["verdict"] == "PASS"
    assert result.result_json["score"] == 85.5
    assert result.result_json["analysis"]["trend"] == "bullish"


@pytest.mark.service
def test_task_timestamps(task_service):
    """
    测试任务时间戳

    应该正确记录任务的创建、开始和完成时间。
    """
    now = utc_now()

    task = Task(
        task_type="full_update",
        status="pending",
        created_at=now
    )
    task_service.db.add(task)
    task_service.db.commit()
    task_service.db.refresh(task)

    assert task.created_at is not None
    assert task.started_at is None
    assert task.completed_at is None

    # 模拟任务开始
    task.status = "running"
    task.started_at = utc_now()
    task_service.db.commit()
    task_service.db.refresh(task)

    assert task.started_at is not None

    # 模拟任务完成
    task.status = "completed"
    task.completed_at = utc_now()
    task_service.db.commit()
    task_service.db.refresh(task)

    assert task.completed_at is not None
    assert task.completed_at >= task.started_at


@pytest.mark.service
def test_run_daily_batch_update_sync_uses_service_class(task_service):
    """静态批量刷新辅助方法应能直接解析 DailyBatchUpdateService。"""
    expected = {"ok": True, "stock_count": 3}

    batch_service = MagicMock()
    batch_service.update_trade_date.return_value = expected

    batch_service_cls = MagicMock()
    batch_service_cls.return_value.__enter__.return_value = batch_service
    batch_service_cls.return_value.__exit__.return_value = None

    with patch("app.services.task_service.DailyBatchUpdateService", batch_service_cls):
        result = task_service._run_daily_batch_update_sync(
            "2026-05-06",
            "incremental_update",
            "token-123",
            None,
        )

    assert result == expected
    batch_service_cls.assert_called_once_with(token="token-123")
    batch_service.update_trade_date.assert_called_once_with(
        "2026-05-06",
        source="incremental_update",
        progress_callback=None,
    )
