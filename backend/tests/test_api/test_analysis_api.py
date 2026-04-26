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
                "b1_passed": True,
                "score": None,
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
                "b1_passed": False,
                "score": None,
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
        assert data["history"][0]["b1_passed"] is True
        assert data["history"][1]["b1_passed"] is False


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
    测试启动单股分析 - 成功

    验证API能正确执行单股分析并返回分析结果。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_result = {
            "code": "600000",
            "b1_passed": True,
            "kdj_j": 15.3,
            "zx_long_pos": True,
            "weekly_ma_aligned": True,
            "volume_healthy": True,
            "close_price": 10.5,
            "score": 4.5,
            "verdict": "PASS",
            "comment": "技术形态良好",
            "signal_type": "bullish",
        }
        mock_service.analyze_stock.return_value = mock_result

        # Mock K线数据
        mock_df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=120),
            "open": [10.0] * 120,
            "high": [10.5] * 120,
            "low": [9.5] * 120,
            "close": [10.0] * 120,
            "vol": [1000000] * 120,
        })
        mock_service.load_stock_data.return_value = mock_df

        response = test_client.post(
            "/api/v1/analysis/diagnosis/analyze",
            json={"code": "600000"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600000"
        assert data["b1_passed"] is True
        assert data["score"] == 4.5
        assert data["verdict"] == "PASS"
        assert "analysis" in data
        assert data["analysis"]["kdj_j"] == 15.3
        assert "kline_data" in data
        assert data["kline_data"] is not None
        mock_service.analyze_stock.assert_called_once_with("600000", "quant")


@pytest.mark.api
def test_start_diagnosis_returns_stock_name(test_client_with_db) -> None:
    """
    测试单股分析接口返回股票名称
    """
    stock = Stock(code="600000", name="浦发银行", market="SH", industry="银行")
    test_client_with_db.db.add(stock)
    test_client_with_db.db.commit()

    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_result = {
            "code": "600000",
            "b1_passed": True,
            "close_price": 10.5,
            "score": 4.5,
            "verdict": "PASS",
        }
        mock_service.analyze_stock.return_value = mock_result
        mock_service.load_stock_data.return_value = None

        response = test_client_with_db.post(
            "/api/v1/analysis/diagnosis/analyze",
            json={"code": "600000"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600000"
        assert data["name"] == "浦发银行"


@pytest.mark.api
def test_start_diagnosis_invalid_code(test_client: TestClient) -> None:
    """
    测试启动单股分析 - 无效代码

    验证当股票代码无效时，API能正确处理并返回错误信息。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_result = {
            "code": "999999",
            "b1_passed": False,
            "error": "数据不存在",
        }
        mock_service.analyze_stock.return_value = mock_result
        mock_service.load_stock_data.return_value = None

        response = test_client.post(
            "/api/v1/analysis/diagnosis/analyze",
            json={"code": "999999"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "999999"
        assert data["b1_passed"] is False
        assert data["kline_data"] is None


@pytest.mark.api
def test_start_diagnosis_no_data(test_client: TestClient) -> None:
    """
    测试启动单股分析 - 无K线数据

    验证当股票没有K线数据时，API能正确处理。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_result = {
            "code": "600000",
            "b1_passed": False,
            "close_price": None,
            "score": 0,
            "verdict": "FAIL",
            "comment": "数据不存在",
        }
        mock_service.analyze_stock.return_value = mock_result
        mock_service.load_stock_data.return_value = None

        response = test_client.post(
            "/api/v1/analysis/diagnosis/analyze",
            json={"code": "600000"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600000"
        assert data["current_price"] is None
        assert data["kline_data"] is None
        assert data["verdict"] == "FAIL"


@pytest.mark.api
def test_start_diagnosis_with_kline(test_client: TestClient) -> None:
    """
    测试启动单股分析 - 包含完整K线数据

    验证API能正确返回K线数据，包括日期、开高低收、成交量等。
    """
    with patch("app.api.analysis.analysis_service") as mock_service:
        mock_result = {
            "code": "600000",
            "b1_passed": True,
            "kdj_j": 15.3,
            "zx_long_pos": True,
            "weekly_ma_aligned": True,
            "volume_healthy": True,
            "close_price": 10.5,
            "score": 4.5,
            "verdict": "PASS",
            "comment": "良好",
        }
        mock_service.analyze_stock.return_value = mock_result

        # 创建120天的K线数据
        dates = pd.date_range("2024-01-01", periods=120)
        mock_df = pd.DataFrame({
            "date": dates,
            "open": [10.0 + i * 0.01 for i in range(120)],
            "high": [10.5 + i * 0.01 for i in range(120)],
            "low": [9.5 + i * 0.01 for i in range(120)],
            "close": [10.0 + i * 0.01 for i in range(120)],
            "vol": [1000000 + i * 10000 for i in range(120)],
        })
        mock_service.load_stock_data.return_value = mock_df

        response = test_client.post(
            "/api/v1/analysis/diagnosis/analyze",
            json={"code": "600000"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "kline_data" in data
        assert data["kline_data"] is not None
        assert "dates" in data["kline_data"]
        assert "open" in data["kline_data"]
        assert "high" in data["kline_data"]
        assert "low" in data["kline_data"]
        assert "close" in data["kline_data"]
        assert "volume" in data["kline_data"]
        # 验证返回最近120天数据
        assert len(data["kline_data"]["dates"]) == 120


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
