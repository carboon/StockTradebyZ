"""
Tasks API Tests
~~~~~~~~~~~~~~~
任务调度API测试用例

测试任务调度相关的所有API端点，包括：
- 获取数据更新状态
- 启动全量更新
- 获取任务列表
- 获取任务详情
- 取消任务

注意：
- 使用 test_client fixture 用于不需要直接访问数据库的测试
- 使用 test_client_with_db fixture 用于需要同时访问客户端和数据库的测试
- Mock task_service 和 tushare_service 以避免实际执行任务
"""
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.models import Task
from app.time_utils import utc_now


def _close_scheduled_task(coro):
    coro.close()
    return None


@pytest.mark.api
def test_get_data_update_status(test_client: TestClient) -> None:
    """
    测试获取数据更新状态

    Mock TushareService.check_data_status()方法，验证API能正确返回数据状态信息。
    包括原始数据、候选数据、分析数据和K线数据的状态。
    """
    mock_status = {
        "raw_data": {"exists": True, "count": 5000, "latest_date": 1705305600.0},  # timestamp
        "candidates": {"exists": True, "count": 50, "latest_date": "2024-01-15"},
        "analysis": {"exists": True, "count": 100, "latest_date": "2024-01-15"},
        "kline": {"exists": True, "count": 500, "latest_date": None},
    }

    with patch("app.api.tasks.TushareService") as mock_service_class:
        mock_service = MagicMock()
        mock_service.check_data_status.return_value = mock_status
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/v1/tasks/status")

        assert response.status_code == 200
        data = response.json()

        # 验证返回的数据结构
        assert "raw_data" in data
        assert "candidates" in data
        assert "analysis" in data
        assert "kline" in data

        # 验证原始数据状态（包含格式化后的日期）
        assert data["raw_data"]["exists"] is True
        assert data["raw_data"]["count"] == 5000
        assert "latest_date" in data["raw_data"]

        # 验证候选数据状态
        assert data["candidates"]["exists"] is True
        assert data["candidates"]["count"] == 50
        assert data["candidates"]["latest_date"] == "2024-01-15"

        # 验证分析数据状态
        assert data["analysis"]["exists"] is True
        assert data["analysis"]["count"] == 100

        # 验证K线数据状态
        assert data["kline"]["exists"] is True
        assert data["kline"]["count"] == 500


@pytest.mark.api
def test_get_data_update_status_no_logs(test_client: TestClient) -> None:
    """
    测试获取数据更新状态 - 无数据情况

    Mock TushareService.check_data_status()方法返回空数据状态，
    验证API能正确处理并返回所有字段为False的响应。
    """
    mock_empty_status = {
        "raw_data": {"exists": False, "count": 0, "latest_date": None},
        "candidates": {"exists": False, "count": 0, "latest_date": None},
        "analysis": {"exists": False, "count": 0, "latest_date": None},
        "kline": {"exists": False, "count": 0, "latest_date": None},
    }

    with patch("app.api.tasks.TushareService") as mock_service_class:
        mock_service = MagicMock()
        mock_service.check_data_status.return_value = mock_empty_status
        mock_service_class.return_value = mock_service

        response = test_client.get("/api/v1/tasks/status")

        assert response.status_code == 200
        data = response.json()

        # 验证所有数据类型都不存在
        assert data["raw_data"]["exists"] is False
        assert data["raw_data"]["count"] == 0
        assert data["candidates"]["exists"] is False
        assert data["analysis"]["exists"] is False
        assert data["kline"]["exists"] is False


@pytest.mark.api
def test_start_full_update_success(test_client_with_db: Any) -> None:
    """
    测试启动全量更新 - 成功场景

    使用测试数据库创建任务后，验证接口返回新任务信息。
    """
    with patch("app.api.tasks.TushareService") as mock_service_class, \
            patch("app.services.task_service.asyncio.create_task", side_effect=_close_scheduled_task) as mock_create_task, \
            patch("app.main.manager", MagicMock()):
        mock_service = MagicMock()
        mock_service.verify_token.return_value = (True, "ok")
        mock_service_class.return_value = mock_service

        response = test_client_with_db.post(
            "/api/v1/tasks/start",
            json={
                "reviewer": "quant",
                "skip_fetch": False,
                "start_from": 1,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["task"]["id"] > 0
    assert data["task"]["task_type"] == "full_update"
    assert data["task"]["status"] == "pending"
    assert data["task"]["params_json"]["reviewer"] == "quant"
    assert data["task"]["params_json"]["skip_fetch"] is False
    assert data["task"]["params_json"]["start_from"] == 1
    assert data["ws_url"] == f"/ws/tasks/{data['task']['id']}"
    mock_create_task.assert_called_once()


@pytest.mark.api
def test_start_full_update_default_params(test_client_with_db: Any) -> None:
    """
    测试启动全量更新 - 使用默认参数

    验证不传递参数时，API能处理请求并使用默认值。
    """
    with patch("app.api.tasks.TushareService") as mock_service_class, \
            patch("app.services.task_service.asyncio.create_task", side_effect=_close_scheduled_task) as mock_create_task, \
            patch("app.main.manager", MagicMock()):
        mock_service = MagicMock()
        mock_service.verify_token.return_value = (True, "ok")
        mock_service_class.return_value = mock_service

        response = test_client_with_db.post(
            "/api/v1/tasks/start",
            json={},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["task"]["id"] > 0
    assert data["task"]["params_json"]["reviewer"] == "quant"
    assert data["task"]["params_json"]["skip_fetch"] is False
    assert data["task"]["params_json"]["start_from"] == 1
    mock_create_task.assert_called_once()


@pytest.mark.api
def test_start_full_update_with_params(test_client_with_db: Any) -> None:
    """
    测试启动全量更新 - 自定义参数

    验证能正确传递自定义参数（reviewer, skip_fetch, start_from）。
    """
    with patch("app.api.tasks.TushareService") as mock_service_class, \
            patch("app.services.task_service.asyncio.create_task", side_effect=_close_scheduled_task) as mock_create_task, \
            patch("app.main.manager", MagicMock()):
        mock_service = MagicMock()
        mock_service.verify_token.return_value = (True, "ok")
        mock_service_class.return_value = mock_service

        response = test_client_with_db.post(
            "/api/v1/tasks/start",
            json={
                "reviewer": "glm",
                "skip_fetch": True,
                "start_from": 3
            }
        )

    assert response.status_code == 200
    data = response.json()
    assert data["task"]["id"] > 0
    assert data["task"]["params_json"]["reviewer"] == "glm"
    assert data["task"]["params_json"]["skip_fetch"] is True
    assert data["task"]["params_json"]["start_from"] == 3
    mock_create_task.assert_called_once()


@pytest.mark.api
def test_start_full_update_returns_existing_running_task(test_client_with_db: Any) -> None:
    """
    测试重复启动全量更新时直接返回已有任务
    """
    existing_task = Task(
        task_type="full_update",
        status="running",
        progress=42,
        params_json={"reviewer": "quant"},
        started_at=utc_now(),
        created_at=utc_now(),
    )
    test_client_with_db.db.add(existing_task)
    test_client_with_db.db.commit()
    test_client_with_db.db.refresh(existing_task)

    with patch("app.api.tasks.TushareService") as mock_service_class, \
            patch("app.api.tasks.TaskService.create_task", new=AsyncMock()) as mock_create_task, \
            patch("app.main.manager", MagicMock()):
        response = test_client_with_db.post(
            "/api/v1/tasks/start",
            json={"reviewer": "glm", "skip_fetch": True, "start_from": 3},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["task"]["id"] == existing_task.id
    assert data["task"]["status"] == "running"
    assert data["ws_url"] == f"/ws/tasks/{existing_task.id}"
    mock_service_class.assert_not_called()
    mock_create_task.assert_not_awaited()


@pytest.mark.api
def test_get_tasks_empty(test_client_with_db: Any) -> None:
    """
    测试获取任务列表 - 空列表

    验证在数据库中没有任务时，API返回空列表。
    """
    response = test_client_with_db.get("/api/v1/tasks/")

    assert response.status_code == 200
    data = response.json()

    assert "tasks" in data
    assert isinstance(data["tasks"], list)
    assert len(data["tasks"]) == 0
    assert data["total"] == 0


@pytest.mark.api
def test_get_task_diagnostics(test_client_with_db: Any) -> None:
    now = utc_now()
    running_task = Task(
        task_type="full_update",
        status="running",
        progress=25,
        created_at=now,
        started_at=now,
    )
    failed_task = Task(
        task_type="full_update",
        status="failed",
        progress=80,
        error_message="network timeout",
        created_at=now,
        completed_at=now,
    )
    test_client_with_db.db.add_all([running_task, failed_task])
    test_client_with_db.db.commit()

    with patch("app.api.tasks.TushareService") as mock_service_class:
        mock_service = MagicMock()
        mock_service.check_data_status.return_value = {
            "raw_data": {"exists": True, "count": 3200, "latest_date": "2025-04-25"},
            "candidates": {"exists": False, "count": 0, "latest_date": None},
            "analysis": {"exists": False, "count": 0, "latest_date": None},
            "kline": {"exists": True, "count": 500, "latest_date": "2025-04-25"},
        }
        mock_service_class.return_value = mock_service

        response = test_client_with_db.get("/api/v1/tasks/diagnostics")

    assert response.status_code == 200
    data = response.json()
    assert len(data["checks"]) >= 4
    assert data["running_tasks"][0]["status"] == "running"
    assert data["latest_failed_task"]["status"] == "failed"
    assert data["data_status"]["raw_data"]["exists"] is True


@pytest.mark.api
def test_get_tasks(test_client_with_db: Any) -> None:
    """
    测试获取任务列表

    在数据库中创建多个任务，验证API能正确返回任务列表。
    验证任务按创建时间倒序排列。
    """
    # 创建多个任务
    now = utc_now()
    tasks = [
        Task(
            task_type="full_update",
            status="completed",
            progress=100,
            params_json={"reviewer": "quant"},
            result_json={"success": True},
            created_at=now
        ),
        Task(
            task_type="single_analysis",
            status="running",
            progress=50,
            params_json={"code": "600000"},
            created_at=now
        ),
        Task(
            task_type="tomorrow_star",
            status="pending",
            progress=0,
            created_at=now
        ),
    ]

    for task in tasks:
        test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    response = test_client_with_db.get("/api/v1/tasks/")

    assert response.status_code == 200
    data = response.json()

    assert "tasks" in data
    assert isinstance(data["tasks"], list)
    assert len(data["tasks"]) == 3
    assert data["total"] == 3

    # 验证任务结构
    for task_data in data["tasks"]:
        assert "id" in task_data
        assert "task_type" in task_data
        assert "status" in task_data
        assert "progress" in task_data
        assert "created_at" in task_data


@pytest.mark.api
def test_get_tasks_with_status_filter(test_client_with_db: Any) -> None:
    """
    测试获取任务列表 - 按状态筛选

    创建不同状态的任务，验证status参数能正确筛选任务。
    """
    now = utc_now()
    tasks = [
        Task(task_type="full_update", status="pending", progress=0, created_at=now),
        Task(task_type="full_update", status="running", progress=30, created_at=now),
        Task(task_type="full_update", status="completed", progress=100, created_at=now),
        Task(task_type="full_update", status="failed", progress=0, error_message="Error", created_at=now),
    ]

    for task in tasks:
        test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    # 测试筛选pending状态
    response_pending = test_client_with_db.get("/api/v1/tasks/?status=pending")
    assert response_pending.status_code == 200
    data_pending = response_pending.json()
    assert len(data_pending["tasks"]) == 1
    assert data_pending["tasks"][0]["status"] == "pending"
    assert data_pending["total"] == 1

    # 测试筛选completed状态
    response_completed = test_client_with_db.get("/api/v1/tasks/?status=completed")
    assert response_completed.status_code == 200
    data_completed = response_completed.json()
    assert len(data_completed["tasks"]) == 1
    assert data_completed["tasks"][0]["status"] == "completed"

    # 测试筛选不存在的状态
    response_empty = test_client_with_db.get("/api/v1/tasks/?status=cancelled")
    assert response_empty.status_code == 200
    data_empty = response_empty.json()
    assert len(data_empty["tasks"]) == 0

    response_multi = test_client_with_db.get("/api/v1/tasks/?status=completed,failed")
    assert response_multi.status_code == 200
    data_multi = response_multi.json()
    assert len(data_multi["tasks"]) == 2


@pytest.mark.api
def test_get_tasks_with_limit(test_client_with_db: Any) -> None:
    """
    测试获取任务列表 - 限制返回数量

    创建多个任务，验证limit参数能正确限制返回的任务数量。
    """
    now = utc_now()
    for i in range(5):
        task = Task(
            task_type="full_update",
            status="pending",
            progress=0,
            created_at=now
        )
        test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    # 测试limit=2
    response = test_client_with_db.get("/api/v1/tasks/?limit=2")
    assert response.status_code == 200
    data = response.json()
    # 任务列表应该只返回2条（受limit限制）
    assert len(data["tasks"]) == 2
    # total应该反映所有符合条件的任务总数，不受limit影响
    assert data["total"] == 5


@pytest.mark.api
def test_get_task_detail_success(test_client_with_db: Any) -> None:
    """
    测试获取任务详情 - 成功场景

    创建一个任务，验证API能正确返回任务的完整详情。
    """
    now = utc_now()
    task = Task(
        task_type="single_analysis",
        status="completed",
        progress=100,
        params_json={"code": "600000", "reviewer": "quant"},
        result_json={"verdict": "PASS", "score": 85},
        started_at=now,
        completed_at=now,
        created_at=now
    )
    test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    response = test_client_with_db.get(f"/api/v1/tasks/{task.id}")

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == task.id
    assert data["task_type"] == "single_analysis"
    assert data["status"] == "completed"
    assert data["progress"] == 100
    assert data["params_json"]["code"] == "600000"
    assert data["result_json"]["verdict"] == "PASS"
    assert "started_at" in data
    assert "completed_at" in data
    assert "created_at" in data


@pytest.mark.api
def test_get_task_detail_not_found(test_client: TestClient) -> None:
    """
    测试获取任务详情 - 任务不存在

    请求一个不存在的任务ID，验证API返回404错误。
    """
    response = test_client.get("/api/v1/tasks/99999")

    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "任务不存在" in data["detail"]


@pytest.mark.api
def test_get_task_detail_with_error(test_client_with_db: Any) -> None:
    """
    测试获取任务详情 - 包含错误信息

    创建一个失败的任务，验证API能正确返回错误信息。
    """
    now = utc_now()
    task = Task(
        task_type="full_update",
        status="failed",
        progress=45,
        error_message="网络连接失败",
        started_at=now,
        completed_at=now,
        created_at=now
    )
    test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    response = test_client_with_db.get(f"/api/v1/tasks/{task.id}")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "failed"
    assert data["error_message"] == "网络连接失败"
    assert data["progress"] == 45


@pytest.mark.api
def test_cancel_task_success(test_client_with_db: Any) -> None:
    """
    测试取消任务 - 成功场景

    创建一个运行中的任务，Mock TaskService.cancel_task()返回True，
    验证任务状态被更新为cancelled。
    """
    now = utc_now()
    task = Task(
        task_type="full_update",
        status="running",
        progress=30,
        started_at=now,
        created_at=now
    )
    test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    with patch("app.api.tasks.TaskService") as mock_service_class:
        mock_service = MagicMock()
        mock_service.cancel_task = AsyncMock(return_value=True)
        mock_service_class.return_value = mock_service

        response = test_client_with_db.post(f"/api/v1/tasks/{task.id}/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["message"] == "任务已取消"

        # 验证数据库中任务状态被更新
        test_client_with_db.db.rollback()
        updated_task = test_client_with_db.db.query(Task).filter(Task.id == task.id).first()
        assert updated_task.status == "cancelled"


@pytest.mark.api
def test_cancel_task_not_found(test_client: TestClient) -> None:
    """
    测试取消任务 - 任务不存在

    Mock TaskService.cancel_task()返回False，验证API返回错误状态。
    """
    with patch("app.api.tasks.TaskService") as mock_service_class:
        mock_service = MagicMock()
        mock_service.cancel_task = AsyncMock(return_value=False)
        mock_service_class.return_value = mock_service

        response = test_client.post("/api/v1/tasks/99999/cancel")

        assert response.status_code == 200  # 端点返回200但状态为error
        data = response.json()
        assert data["status"] == "error"
        assert "无法取消" in data["message"]


@pytest.mark.api
def test_cancel_task_already_completed(test_client_with_db: Any) -> None:
    """
    测试取消任务 - 任务已完成

    创建一个已完成的任务，Mock cancel_task返回False，
    验证API能正确处理（已完成的任务无法取消）。
    """
    now = utc_now()
    task = Task(
        task_type="full_update",
        status="completed",
        progress=100,
        completed_at=now,
        created_at=now
    )
    test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    with patch("app.api.tasks.TaskService") as mock_service_class:
        mock_service = MagicMock()
        # 已完成的任务不在running_tasks中，cancel_task返回False
        mock_service.cancel_task = AsyncMock(return_value=False)
        mock_service_class.return_value = mock_service

        response = test_client_with_db.post(f"/api/v1/tasks/{task.id}/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"

        # 验证任务状态未被修改
        test_client_with_db.db.rollback()
        unchanged_task = test_client_with_db.db.query(Task).filter(Task.id == task.id).first()
        assert unchanged_task.status == "completed"


@pytest.mark.api
def test_cancel_task_failed(test_client_with_db: Any) -> None:
    """
    测试取消任务 - 任务已失败

    创建一个失败的任务，验证取消操作的处理。
    """
    now = utc_now()
    task = Task(
        task_type="full_update",
        status="failed",
        progress=0,
        error_message="执行失败",
        completed_at=now,
        created_at=now
    )
    test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    with patch("app.api.tasks.TaskService") as mock_service_class:
        mock_service = MagicMock()
        mock_service.cancel_task = AsyncMock(return_value=False)
        mock_service_class.return_value = mock_service

        response = test_client_with_db.post(f"/api/v1/tasks/{task.id}/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"


@pytest.mark.api
def test_get_task_with_cancelled_status(test_client_with_db: Any) -> None:
    """
    测试获取已取消任务详情

    创建一个已取消的任务，验证API能正确返回取消状态。
    """
    now = utc_now()
    task = Task(
        task_type="full_update",
        status="cancelled",
        progress=50,
        started_at=now,
        completed_at=now,
        created_at=now
    )
    test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    response = test_client_with_db.get(f"/api/v1/tasks/{task.id}")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "cancelled"
    assert data["progress"] == 50
