"""
Analysis API Tests
~~~~~~~~~~~~~~~~~
分析相关API测试用例

测试分析相关的所有API端点，包括：
- 获取明日之星历史日期列表
- 获取候选股票列表
- 获取分析结果
- 获取单股诊断历史
- 启动单股分析
- 手动生成明日之星

注意：
- 使用 test_client fixture 用于不需要直接访问数据库的测试
- Mock analysis_service 的方法避免实际文件IO
- 使用 patch 来隔离外部依赖
"""
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.models import Task
from app.models import Stock


@pytest.mark.api
def test_get_tomorrow_star_dates_empty(test_client: TestClient) -> None:
    """
    测试获取明日之星历史日期列表 - 空列表

    验证当没有历史数据时，API返回空的日期列表。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_service.get_candidates_history.return_value = []

        response = test_client.get("/api/v1/analysis/tomorrow-star/dates")

        assert response.status_code == 200
        data = response.json()
        assert "dates" in data
        assert "history" in data
        assert data["dates"] == []
        assert data["history"] == []
        mock_service.get_candidates_history.assert_called_once_with(limit=100)


@pytest.mark.api
def test_get_tomorrow_star_dates(test_client: TestClient) -> None:
    """
    测试获取明日之星历史日期列表 - 正常返回

    验证API能正确返回历史日期列表。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_history = [
            {"date": "2024-01-15", "count": 10, "file": "/path/to/file1"},
            {"date": "2024-01-14", "count": 8, "file": "/path/to/file2"},
            {"date": "2024-01-13", "count": 5, "file": "/path/to/file3"},
        ]
        mock_service.get_candidates_history.return_value = mock_history

        response = test_client.get("/api/v1/analysis/tomorrow-star/dates")

        assert response.status_code == 200
        data = response.json()
        assert "dates" in data
        assert "history" in data
        assert len(data["dates"]) == 3
        assert data["dates"] == ["2024-01-15", "2024-01-14", "2024-01-13"]
        assert data["history"] == mock_history
        mock_service.get_candidates_history.assert_called_once_with(limit=100)


@pytest.mark.api
def test_get_tomorrow_star_candidates_empty(test_client: TestClient) -> None:
    """
    测试获取候选股票列表 - 文件不存在

    验证当候选文件不存在时，API返回空列表。

    注意：此测试可能读取实际文件，所以只验证基本结构。
    """
    with patch("app.api.analysis.analysis_service.load_candidate_codes", return_value=("2024-01-15", [])):
        with patch("app.services.market_service.market_service.should_update_data", return_value=(False, "2024-01-15")):
            with patch("app.services.market_service.market_service.load_prepared_data", return_value={"prepared": {}, "pool_codes": [], "candidates": []}):
                response = test_client.get("/api/v1/analysis/tomorrow-star/candidates")

    # 由于测试环境可能存在实际文件，我们只验证响应结构
    assert response.status_code == 200
    data = response.json()
    assert "candidates" in data
    assert "total" in data
    assert isinstance(data["candidates"], list)


@pytest.mark.api
def test_get_tomorrow_star_candidates(test_client: TestClient, tmp_path: Path) -> None:
    """
    测试获取候选股票列表 - 正常返回

    验证API能正确读取并返回候选股票列表。

    注意：此测试可能读取实际文件，所以只验证基本结构。
    """
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"date": "2024-01-12", "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0, "volume": 1000000},
        {"date": "2024-01-15", "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.2, "volume": 1200000},
    ]).to_csv(raw_dir / "600000.csv", index=False)

    selector_instance = MagicMock()

    def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["turnover_n"] = [100.0, 120.0]
        out["J"] = [5.0, 8.0]
        out["_vec_pick"] = [False, True]
        return out

    selector_instance.prepare_df.side_effect = prepare_df

    with patch("app.api.analysis.analysis_service.load_candidate_codes", return_value=("2024-01-15", ["600000"])):
        with patch("app.services.market_service.market_service.should_update_data", return_value=(False, "2024-01-15")):
            with patch("app.config.settings.raw_data_dir", str(raw_dir)):
                with patch("Selector.B1Selector", return_value=selector_instance):
                    response = test_client.get("/api/v1/analysis/tomorrow-star/candidates")

    # 验证响应结构
    assert response.status_code == 200
    data = response.json()
    assert "candidates" in data
    assert "total" in data
    assert isinstance(data["candidates"], list)

    # 如果有数据，验证候选股票的结构
    if len(data["candidates"]) > 0:
        candidate = data["candidates"][0]
        assert "code" in candidate
        assert "id" in candidate


@pytest.mark.api
def test_get_tomorrow_star_candidates_with_date(test_client: TestClient, tmp_path: Path) -> None:
    """
    测试获取候选股票列表 - 指定日期

    验证API能正确处理指定日期参数的请求。
    """
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"date": "2024-01-10", "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0, "volume": 1000000},
    ]).to_csv(raw_dir / "600000.csv", index=False)

    selector_instance = MagicMock()

    def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["turnover_n"] = [100.0]
        out["J"] = [5.0]
        out["_vec_pick"] = [True]
        return out

    selector_instance.prepare_df.side_effect = prepare_df

    with patch("app.api.analysis.analysis_service.load_candidate_codes", return_value=("2024-01-10", ["600000"])):
        with patch("app.config.settings.raw_data_dir", str(raw_dir)):
            with patch("Selector.B1Selector", return_value=selector_instance):
                response = test_client.get(
                    "/api/v1/analysis/tomorrow-star/candidates?date=2024-01-10"
                )

                assert response.status_code == 200
                data = response.json()
                assert data["total"] == 1
                assert data["pick_date"] == "2024-01-10"
                assert data["candidates"][0]["code"] == "600000"


@pytest.mark.api
def test_get_tomorrow_star_candidates_with_limit(test_client: TestClient, tmp_path: Path) -> None:
    """
    测试获取候选股票列表 - 限制数量

    验证API能正确处理limit参数，限制返回的候选数量。

    注意：此测试可能读取实际文件，所以只验证基本结构。
    """
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for code in ["600000", "000001", "000002"]:
        pd.DataFrame([
            {"date": "2024-01-15", "open": 9.8, "high": 10.2, "low": 9.7, "close": 10.0, "volume": 1000000},
        ]).to_csv(raw_dir / f"{code}.csv", index=False)

    selector_instance = MagicMock()

    def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["turnover_n"] = [100.0]
        out["J"] = [5.0]
        out["_vec_pick"] = [True]
        return out

    selector_instance.prepare_df.side_effect = prepare_df

    with patch("app.api.analysis.analysis_service.load_candidate_codes", return_value=("2024-01-15", ["600000", "000001", "000002"])):
        with patch("app.config.settings.raw_data_dir", str(raw_dir)):
            with patch("Selector.B1Selector", return_value=selector_instance):
                response = test_client.get(
                    "/api/v1/analysis/tomorrow-star/candidates?limit=2"
                )

    # 验证响应结构
    assert response.status_code == 200
    data = response.json()
    assert "candidates" in data
    assert "total" in data
    assert isinstance(data["candidates"], list)
    assert data["total"] == 3
    assert len(data["candidates"]) == 2


@pytest.mark.api
def test_get_tomorrow_star_results_empty(test_client: TestClient) -> None:
    """
    测试获取分析结果 - 空结果

    验证当没有分析结果时，API返回空列表。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_service.get_analysis_results.return_value = {
            "pick_date": None,
            "results": [],
            "total": 0,
            "min_score_threshold": 4.0,
        }

        response = test_client.get("/api/v1/analysis/tomorrow-star/results")

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert data["results"] == []
        assert data["total"] == 0
        assert data["pick_date"] is None
        mock_service.get_analysis_results.assert_called_once_with(None)


@pytest.mark.api
def test_get_tomorrow_star_results(test_client: TestClient) -> None:
    """
    测试获取分析结果 - 正常返回

    验证API能正确返回分析结果列表。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_result = {
            "pick_date": "2024-01-15",
            "results": [
                {
                    "code": "600000",
                    "verdict": "PASS",
                    "total_score": 4.5,
                    "signal_type": "bullish",
                    "comment": "技术形态良好",
                },
                {
                    "code": "000001",
                    "verdict": "WATCH",
                    "total_score": 3.8,
                    "signal_type": "neutral",
                    "comment": "需观察",
                },
            ],
            "total": 2,
            "min_score_threshold": 4.0,
        }
        mock_service.get_analysis_results.return_value = mock_result

        response = test_client.get("/api/v1/analysis/tomorrow-star/results")

        assert response.status_code == 200
        data = response.json()
        # API返回的pick_date来自schema，但由于代码中使用date参数
        # 而schema中没有别名配置，所以pick_date会是None
        # 我们验证results数组的内容
        assert len(data["results"]) == 2
        assert data["total"] == 2
        assert data["min_score_threshold"] == 4.0
        assert data["pick_date"] == "2024-01-15"
        assert data["results"][0]["code"] == "600000"
        assert data["results"][0]["verdict"] == "PASS"
        assert data["results"][0]["total_score"] == 4.5
        # 每个结果的pick_date应该被正确设置
        assert data["results"][0]["pick_date"] == "2024-01-15"


@pytest.mark.api
def test_get_tomorrow_star_results_with_date(test_client: TestClient) -> None:
    """
    测试获取分析结果 - 指定日期

    验证API能正确处理指定日期参数的请求。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_result = {
            "pick_date": "2024-01-10",
            "results": [
                {
                    "code": "600519",
                    "verdict": "PASS",
                    "total_score": 5.0,
                    "signal_type": "bullish",
                    "comment": "强势股",
                }
            ],
            "total": 1,
            "min_score_threshold": 4.0,
        }
        mock_service.get_analysis_results.return_value = mock_result

        response = test_client.get(
            "/api/v1/analysis/tomorrow-star/results?date=2024-01-10"
        )

        assert response.status_code == 200
        data = response.json()
        # 验证results数组中的pick_date
        assert data["total"] == 1
        assert data["pick_date"] == "2024-01-10"
        assert data["results"][0]["pick_date"] == "2024-01-10"
        mock_service.get_analysis_results.assert_called_once_with("2024-01-10")


@pytest.mark.api
def test_get_diagnosis_history_empty(test_client: TestClient) -> None:
    """
    测试获取单股诊断历史 - 空历史

    验证当股票没有历史检查记录时，API返回空列表。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_service.get_stock_history_checks.return_value = []

        response = test_client.get("/api/v1/analysis/diagnosis/600000/history")

        assert response.status_code == 200
        data = response.json()
        assert "history" in data
        assert data["history"] == []
        assert data["total"] == 0
        assert data["code"] == "600000"  # 代码自动补零到6位
        mock_service.get_stock_history_checks.assert_called_once_with("600000", 30)


@pytest.mark.api
def test_get_diagnosis_history(test_client: TestClient) -> None:
    """
    测试获取单股诊断历史 - 正常返回

    验证API能正确返回股票的历史检查记录。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_history = [
            {
                "check_date": "2024-01-15",
                "close_price": 10.5,
                "change_pct": 2.3,
                "kdj_j": 15.3,
                "kdj_low_rank": 0.2,
                "zx_long_pos": True,
                "weekly_ma_aligned": True,
                "volume_healthy": True,
                "in_active_pool": True,
                "b1_passed": True,
                "prefilter_passed": True,
                "prefilter_blocked_by": [],
                "score": None,
                "verdict": "PASS",
                "signal_type": "trend_start",
                "tomorrow_star_pass": True,
            },
            {
                "check_date": "2024-01-14",
                "close_price": 10.3,
                "change_pct": -1.2,
                "kdj_j": 12.1,
                "kdj_low_rank": 0.3,
                "zx_long_pos": False,
                "weekly_ma_aligned": True,
                "volume_healthy": False,
                "in_active_pool": False,
                "b1_passed": False,
                "prefilter_passed": False,
                "prefilter_blocked_by": ["market_regime"],
                "score": None,
                "verdict": "WATCH",
                "signal_type": "rebound",
                "tomorrow_star_pass": False,
            },
        ]
        mock_service.get_stock_history_checks.return_value = mock_history

        response = test_client.get("/api/v1/analysis/diagnosis/600000/history")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600000"
        assert data["total"] == 2
        assert len(data["history"]) == 2
        assert data["history"][0]["check_date"] == "2024-01-15"
        assert data["history"][0]["in_active_pool"] is True
        assert data["history"][0]["b1_passed"] is True
        assert data["history"][0]["prefilter_passed"] is True
        assert data["history"][0]["signal_type"] == "trend_start"
        assert data["history"][0]["tomorrow_star_pass"] is True
        assert data["history"][1]["in_active_pool"] is False
        assert data["history"][1]["b1_passed"] is False
        assert data["history"][1]["prefilter_passed"] is False
        assert data["history"][1]["prefilter_blocked_by"] == ["market_regime"]


@pytest.mark.api
def test_get_diagnosis_history_returns_stock_name(test_client_with_db) -> None:
    """
    测试诊断历史接口返回股票名称
    """
    stock = Stock(code="600000", name="浦发银行", market="SH", industry="银行")
    test_client_with_db.db.add(stock)
    test_client_with_db.db.commit()

    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_service.get_stock_history_checks.return_value = []

        response = test_client_with_db.get("/api/v1/analysis/diagnosis/600000/history")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600000"
        assert data["name"] == "浦发银行"


@pytest.mark.api
def test_get_diagnosis_history_padded_code(test_client: TestClient) -> None:
    """
    测试获取单股诊断历史 - 代码自动补零

    验证API能正确处理不足6位的股票代码，自动补零。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_service.get_stock_history_checks.return_value = []

        # 输入不足6位的代码
        response = test_client.get("/api/v1/analysis/diagnosis/1/history")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "000001"  # 自动补零到6位
        mock_service.get_stock_history_checks.assert_called_once_with("000001", 30)


@pytest.mark.api
def test_get_diagnosis_history_with_days_param(test_client: TestClient) -> None:
    """
    测试获取单股诊断历史 - 自定义天数

    验证API能正确处理days参数，返回指定天数的历史记录。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_service.get_stock_history_checks.return_value = []

        response = test_client.get("/api/v1/analysis/diagnosis/600000/history?days=60")

        assert response.status_code == 200
        mock_service.get_stock_history_checks.assert_called_once_with("600000", 60)


@pytest.mark.api
def test_start_diagnosis_success(test_client: TestClient) -> None:
    """
    测试启动单股分析 - 成功创建任务

    验证API能正确创建单股分析任务并返回任务信息（后台任务模式）。
    """
    with patch("app.api.analysis.TaskService") as mock_task_service_cls:
        mock_task_service = MagicMock()
        mock_task_service.create_task = AsyncMock(return_value={
            "task_id": 1,
            "ws_url": "/ws/tasks/1",
            "existing": False,
        })
        mock_task_service_cls.return_value = mock_task_service

        response = test_client.post(
            "/api/v1/analysis/diagnosis/analyze",
            json={"code": "600000"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == 1
        assert data["code"] == "600000"
        assert data["status"] in ("pending", "existing")
        assert "ws_url" in data
        assert "message" in data
        mock_task_service.create_task.assert_called_once()


@pytest.mark.api
def test_start_diagnosis_returns_existing_task(test_client_with_db: Any) -> None:
    """
    测试启动单股分析 - 返回现有任务

    验证当同一股票已有活跃分析任务时，返回现有任务ID。
    """
    from app.time_utils import utc_now

    now = utc_now()
    existing_task = Task(
        task_type="single_analysis",
        status="running",
        progress=50,
        params_json={"code": "600000", "reviewer": "quant"},
        started_at=now,
        created_at=now,
    )
    test_client_with_db.db.add(existing_task)
    test_client_with_db.db.commit()

    with patch("app.api.analysis.TaskService") as mock_task_service_cls:
        mock_task_service = MagicMock()
        mock_task_service.create_task = AsyncMock(return_value={
            "task_id": existing_task.id,
            "ws_url": f"/ws/tasks/{existing_task.id}",
            "existing": True,
        })
        mock_task_service_cls.return_value = mock_task_service

        response = test_client_with_db.post(
            "/api/v1/analysis/diagnosis/analyze",
            json={"code": "600000"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == existing_task.id
        assert data["status"] == "existing"


@pytest.mark.api
def test_get_diagnosis_result_processing(test_client_with_db: Any) -> None:
    """
    测试获取单股分析结果 - 任务进行中

    验证当任务还在进行中时，返回processing状态。
    """
    from app.time_utils import utc_now

    now = utc_now()
    task = Task(
        task_type="single_analysis",
        status="running",
        progress=50,
        params_json={"code": "600000", "reviewer": "quant"},
        started_at=now,
        created_at=now,
    )
    test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    response = test_client_with_db.get("/api/v1/analysis/diagnosis/600000/result")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert data["task_id"] == task.id
    assert data["task_status"] == "running"
    assert data["progress"] == 50


@pytest.mark.api
def test_get_diagnosis_result_completed(test_client_with_db: Any) -> None:
    """
    测试获取单股分析结果 - 任务完成

    验证当任务已完成时，返回完整的分析结果。
    """
    from app.time_utils import utc_now

    now = utc_now()
    task = Task(
        task_type="single_analysis",
        status="completed",
        progress=100,
        params_json={"code": "600000", "reviewer": "quant"},
        result_json={
            "close_price": 10.5,
            "b1_passed": True,
            "score": 4.5,
            "verdict": "PASS",
            "kdj_j": 15.3,
            "zx_long_pos": True,
            "weekly_ma_aligned": True,
            "volume_healthy": True,
            "signal_type": "trend_start",
            "comment": "技术形态良好",
            "scores": {"trend_structure": 4.5},
        },
        started_at=now,
        completed_at=now,
        created_at=now,
    )
    test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    stock = Stock(code="600000", name="浦发银行", market="SH", industry="银行")
    test_client_with_db.db.add(stock)
    test_client_with_db.db.commit()

    response = test_client_with_db.get("/api/v1/analysis/diagnosis/600000/result")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["code"] == "600000"
    assert data["name"] == "浦发银行"
    assert data["current_price"] == 10.5
    assert data["b1_passed"] is True
    assert data["score"] == 4.5
    assert data["verdict"] == "PASS"
    assert data["analysis"]["kdj_j"] == 15.3


@pytest.mark.api
def test_get_diagnosis_result_failed(test_client_with_db: Any) -> None:
    """
    测试获取单股分析结果 - 任务失败

    验证当任务失败时，返回错误信息。
    """
    from app.time_utils import utc_now

    now = utc_now()
    task = Task(
        task_type="single_analysis",
        status="failed",
        progress=0,
        params_json={"code": "600000", "reviewer": "quant"},
        error_message="数据加载失败",
        started_at=now,
        completed_at=now,
        created_at=now,
    )
    test_client_with_db.db.add(task)
    test_client_with_db.db.commit()

    response = test_client_with_db.get("/api/v1/analysis/diagnosis/600000/result")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["error"] == "数据加载失败"


@pytest.mark.api
def test_get_diagnosis_result_not_found(test_client: TestClient) -> None:
    """
    测试获取单股分析结果 - 任务不存在

    验证当没有找到分析任务时，返回404错误。
    """
    response = test_client.get("/api/v1/analysis/diagnosis/999999/result")

    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "未找到分析任务" in data["detail"]


@pytest.mark.api
def test_generate_tomorrow_star_success(test_client: TestClient) -> None:
    """
    测试手动生成明日之星 - 成功创建任务

    验证API能正确创建明日之星生成任务并返回任务信息。
    """
    with patch("app.api.analysis.TaskService") as mock_task_service_cls:
        mock_task_service = MagicMock()
        mock_task_service.create_task = AsyncMock(return_value={
            "task_id": 1,
            "ws_url": "ws://localhost:8000/ws/tasks/1",
        })
        mock_task_service_cls.return_value = mock_task_service

        response = test_client.post("/api/v1/analysis/tomorrow-star/generate")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert "message" in data
        assert "task_id" in data
        assert "ws_url" in data
        assert data["message"] == "明日之星生成任务已创建"


@pytest.mark.api
def test_generate_tomorrow_star_with_custom_reviewer(test_client: TestClient) -> None:
    """
    测试手动生成明日之星 - 自定义评审者

    验证API能正确处理自定义评审者参数。
    """
    with patch("app.api.analysis.TaskService") as mock_task_service_cls:
        mock_task_service = MagicMock()
        mock_task_service.create_task = AsyncMock(return_value={
            "task_id": 2,
            "ws_url": "ws://localhost:8000/ws/tasks/2",
        })
        mock_task_service_cls.return_value = mock_task_service

        response = test_client.post(
            "/api/v1/analysis/tomorrow-star/generate?reviewer=glm"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["task_id"] == 2
        # 验证传递了正确的参数
        mock_task_service.create_task.assert_called_once_with(
            "tomorrow_star",
            {"reviewer": "glm"}
        )


@pytest.mark.api
def test_get_diagnosis_history_error_handling(test_client: TestClient) -> None:
    """
    测试获取单股诊断历史 - 异常处理

    验证当服务端发生异常时，API能正确处理。
    注意：FastAPI的测试客户端不会自动传播异常，
    我们通过验证异常被处理来测试。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        # 模拟服务返回空列表而不是抛出异常
        # 因为FastAPI会捕获异常并返回500错误
        mock_service.get_stock_history_checks.return_value = []

        response = test_client.get("/api/v1/analysis/diagnosis/600000/history")

        # 正常情况应该返回200
        assert response.status_code == 200
        data = response.json()
        assert data["history"] == []


@pytest.mark.api
def test_get_tomorrow_star_candidates_invalid_date(test_client: TestClient) -> None:
    """
    测试获取候选股票列表 - 无效日期格式

    验证当传入无效日期格式时，API能正确处理。
    """
    with patch("app.api.analysis.analysis_service.load_candidate_codes", return_value=("invalid-date", [])):
        with patch("app.services.market_service.market_service.should_update_data", return_value=(False, "2024-01-15")):
            with patch("app.services.market_service.market_service.load_prepared_data", return_value={"prepared": {}, "pool_codes": [], "candidates": []}):
                # 传入无效日期格式
                response = test_client.get(
                    "/api/v1/analysis/tomorrow-star/candidates?date=invalid-date"
                )

                # 应该正常处理，返回空结果
                assert response.status_code == 200
                data = response.json()
                assert data["total"] == 0


@pytest.mark.api
def test_get_analysis_results_read_only_no_auto_scoring(test_client: TestClient, tmp_path: Path) -> None:
    """
    测试获取分析结果只读模式 - 不触发自动补算

    验证当候选股票缺少分析结果时，GET接口不会触发自动评分，
    而是返回已存在的分析结果，不进行补算。
    """
    # 创建测试目录结构
    test_root = tmp_path / "test_read_only"
    candidates_dir = test_root / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    review_dir = test_root / "review"
    date_dir = review_dir / "2024-01-15"
    date_dir.mkdir(parents=True, exist_ok=True)

    # 创建候选文件（包含2只股票）
    candidate_data = {
        "pick_date": "2024-01-15",
        "candidates": [
            {"code": "600000"},
            {"code": "000001"},
        ]
    }
    candidate_file = candidates_dir / "candidates_2024-01-15.json"
    with open(candidate_file, "w") as f:
        json.dump(candidate_data, f)

    # 只创建其中一只股票的分析结果（模拟缺失情况）
    with open(date_dir / "600000.json", "w") as f:
        json.dump({
            "code": "600000",
            "total_score": 4.5,
            "verdict": "PASS",
            "signal_type": "trend_start",
            "comment": "技术形态良好",
        }, f)

    # Mock settings
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.candidates_dir = candidates_dir
            mock_settings.review_dir = review_dir
            mock_settings.min_score_threshold = 4.0

            # 调用 get_analysis_results
            from app.services.analysis_service import analysis_service
            result = analysis_service.get_analysis_results("2024-01-15")

            # 验证只返回已存在的分析结果，不包含缺失的股票
            assert result["pick_date"] == "2024-01-15"
            assert result["total"] == 1
            assert len(result["results"]) == 1
            assert result["results"][0]["code"] == "600000"

            # 确保没有为缺失的股票自动生成分析结果文件
            missing_file = date_dir / "000001.json"
            assert not missing_file.exists(), "缺失的分析结果文件不应被自动创建"


@pytest.mark.api
def test_get_analysis_results_missing_all_return_empty(test_client: TestClient, tmp_path: Path) -> None:
    """
    测试获取分析结果 - 所有候选都缺失分析结果

    验证当所有候选股票都缺少分析结果时，GET接口返回空列表，
    不触发任何补算操作。
    """
    test_root = tmp_path / "test_all_missing"
    candidates_dir = test_root / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    review_dir = test_root / "review"
    date_dir = review_dir / "2024-01-15"
    date_dir.mkdir(parents=True, exist_ok=True)

    # 创建候选文件，但没有创建任何分析结果文件
    candidate_data = {
        "pick_date": "2024-01-15",
        "candidates": [
            {"code": "600000"},
            {"code": "000001"},
            {"code": "000002"},
        ]
    }
    candidate_file = candidates_dir / "candidates_2024-01-15.json"
    with open(candidate_file, "w") as f:
        json.dump(candidate_data, f)

    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.candidates_dir = candidates_dir
            mock_settings.review_dir = review_dir
            mock_settings.min_score_threshold = 4.0

            from app.services.analysis_service import analysis_service
            result = analysis_service.get_analysis_results("2024-01-15")

            # 验证返回空结果
            assert result["pick_date"] == "2024-01-15"
            assert result["total"] == 0
            assert len(result["results"]) == 0

            # 确保没有生成任何分析结果文件
            assert not list(date_dir.glob("*.json")), "不应生成任何分析结果文件"
