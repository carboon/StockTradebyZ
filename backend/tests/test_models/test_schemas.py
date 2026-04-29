"""
Pydantic Schema Tests
~~~~~~~~~~~~~~~~~~~~~
数据模型(Schemas)的单元测试
"""
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    # 配置相关
    ConfigItem,
    ConfigUpdate,
    ConfigResponse,
    TushareVerifyRequest,
    TushareVerifyResponse,
    # 股票相关
    StockInfo,
    StockResponse,
    # 候选股票
    CandidateItem,
    CandidatesResponse,
    # 分析结果
    AnalysisItem,
    AnalysisResultResponse,
    # 单股诊断
    B1CheckItem,
    DiagnosisHistoryResponse,
    DiagnosisRequest,
    DiagnosisResponse,
    # 重点观察
    WatchlistItem,
    WatchlistAddRequest,
    WatchlistUpdateRequest,
    WatchlistAnalysisItem,
    WatchlistResponse,
    # 任务调度
    TaskCreateRequest,
    TaskItem,
    TaskResponse,
    TaskListResponse,
    # 数据更新状态
    DataStatusResponse,
    UpdateStartRequest,
    # K线数据
    KLineDataRequest,
    KLineDataPoint,
    KLineResponse,
)


# ============================================
# 配置相关模型测试
# ============================================

@pytest.mark.unit
def test_config_item_valid():
    """
    测试ConfigItem模型的有效数据验证

    验证ConfigItem模型能够正确接受完整的配置项数据。
    """
    data = {
        "key": "tushare_token",
        "value": "test_token_123",
        "description": "Tushare API令牌"
    }

    config = ConfigItem(**data)

    assert config.key == "tushare_token"
    assert config.value == "test_token_123"
    assert config.description == "Tushare API令牌"


@pytest.mark.unit
def test_config_item_minimal():
    """
    测试ConfigItem模型的最小字段验证

    验证ConfigItem模型只需要必填字段(key, value)就能创建，
    description是可选的。
    """
    data = {
        "key": "test_key",
        "value": "test_value"
    }

    config = ConfigItem(**data)

    assert config.key == "test_key"
    assert config.value == "test_value"
    assert config.description is None


@pytest.mark.unit
def test_config_update_valid():
    """
    测试ConfigUpdate模型验证

    验证ConfigUpdate模型正确接受key和value字段。
    """
    data = {
        "key": "test_key",
        "value": "new_value"
    }

    config_update = ConfigUpdate(**data)

    assert config_update.key == "test_key"
    assert config_update.value == "new_value"


@pytest.mark.unit
def test_config_response_valid():
    """
    测试ConfigResponse模型验证

    验证ConfigResponse模型正确接受配置列表。
    """
    data = {
        "configs": [
            {"key": "key1", "value": "value1", "description": "desc1"},
            {"key": "key2", "value": "value2"}
        ]
    }

    config_response = ConfigResponse(**data)

    assert len(config_response.configs) == 2
    assert config_response.configs[0].key == "key1"
    assert config_response.configs[0].description == "desc1"
    assert config_response.configs[1].description is None


@pytest.mark.unit
def test_tushare_verify_request_valid():
    """
    测试TushareVerifyRequest模型验证

    验证TushareVerifyRequest正确接受token字段。
    """
    data = {"token": "test_token_12345"}
    request = TushareVerifyRequest(**data)

    assert request.token == "test_token_12345"


@pytest.mark.unit
def test_tushare_verify_response_valid():
    """
    测试TushareVerifyResponse模型验证

    验证TushareVerifyResponse正确接受valid和message字段。
    """
    data = {
        "valid": True,
        "message": "Token验证成功"
    }
    response = TushareVerifyResponse(**data)

    assert response.valid is True
    assert response.message == "Token验证成功"


@pytest.mark.unit
def test_tushare_verify_response_invalid():
    """
    测试TushareVerifyResponse模型无效Token场景

    验证TushareVerifyResponse可以表示验证失败的场景。
    """
    data = {
        "valid": False,
        "message": "Token无效或已过期"
    }
    response = TushareVerifyResponse(**data)

    assert response.valid is False
    assert response.message == "Token无效或已过期"


# ============================================
# 股票相关模型测试
# ============================================

@pytest.mark.unit
def test_stock_info_full():
    """
    测试StockInfo模型的完整数据验证

    验证StockInfo模型能正确接受包含所有字段的股票信息。
    """
    data = {
        "code": "600000",
        "name": "浦发银行",
        "market": "SH",
        "industry": "银行"
    }

    stock = StockInfo(**data)

    assert stock.code == "600000"
    assert stock.name == "浦发银行"
    assert stock.market == "SH"
    assert stock.industry == "银行"


@pytest.mark.unit
def test_stock_info_minimal():
    """
    测试StockInfo模型的最小字段验证

    验证StockInfo模型只需要code字段就能创建。
    """
    data = {"code": "600000"}

    stock = StockInfo(**data)

    assert stock.code == "600000"
    assert stock.name is None
    assert stock.market is None
    assert stock.industry is None


@pytest.mark.unit
def test_stock_response_valid():
    """
    测试StockResponse模型验证

    验证StockResponse模型正确表示股票查询响应。
    """
    data = {
        "code": "600000",
        "name": "浦发银行",
        "market": "SH",
        "industry": "银行",
        "exists": True
    }

    response = StockResponse(**data)

    assert response.code == "600000"
    assert response.exists is True
    assert response.name == "浦发银行"


@pytest.mark.unit
def test_stock_response_not_exists():
    """
    测试StockResponse模型不存在的股票

    验证StockResponse可以表示股票不存在的场景。
    """
    data = {
        "code": "999999",
        "exists": False
    }

    response = StockResponse(**data)

    assert response.code == "999999"
    assert response.exists is False
    assert response.name is None


# ============================================
# 候选股票模型测试
# ============================================

@pytest.mark.unit
def test_candidate_item_full():
    """
    测试CandidateItem模型的完整数据验证

    验证CandidateItem模型能正确接受包含所有字段的候选股票数据。
    """
    data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000",
        "strategy": "b1",
        "close_price": 10.5,
        "turnover": 1000000,
        "b1_passed": True,
        "kdj_j": 85.5
    }

    candidate = CandidateItem(**data)

    assert candidate.id == 1
    assert candidate.pick_date == date(2024, 1, 15)
    assert candidate.code == "600000"
    assert candidate.strategy == "b1"
    assert candidate.close_price == 10.5
    assert candidate.turnover == 1000000
    assert candidate.b1_passed is True
    assert candidate.kdj_j == 85.5


@pytest.mark.unit
def test_candidate_item_minimal():
    """
    测试CandidateItem模型的最小字段验证

    验证CandidateItem模型只需要必填字段就能创建。
    """
    data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000"
    }

    candidate = CandidateItem(**data)

    assert candidate.id == 1
    assert candidate.pick_date == date(2024, 1, 15)
    assert candidate.code == "600000"
    assert candidate.strategy is None
    assert candidate.close_price is None


@pytest.mark.unit
def test_candidate_response_valid():
    """
    测试CandidatesResponse模型验证

    验证CandidatesResponse模型正确表示候选股票列表响应。
    """
    data = {
        "pick_date": date(2024, 1, 15),
        "candidates": [
            {
                "id": 1,
                "pick_date": date(2024, 1, 15),
                "code": "600000"
            },
            {
                "id": 2,
                "pick_date": date(2024, 1, 15),
                "code": "000001"
            }
        ],
        "total": 2
    }

    response = CandidatesResponse(**data)

    assert response.pick_date == date(2024, 1, 15)
    assert len(response.candidates) == 2
    assert response.total == 2
    assert response.candidates[0].code == "600000"


@pytest.mark.unit
def test_candidate_response_without_pick_date():
    """
    测试CandidatesResponse模型不包含pick_date的场景

    验证pick_date是可选的。
    """
    data = {
        "candidates": [
            {
                "id": 1,
                "pick_date": date(2024, 1, 15),
                "code": "600000"
            }
        ],
        "total": 1
    }

    response = CandidatesResponse(**data)

    assert response.pick_date is None
    assert response.total == 1


# ============================================
# 分析结果模型测试
# ============================================

@pytest.mark.unit
def test_analysis_item_full():
    """
    测试AnalysisItem模型的完整数据验证

    验证AnalysisItem模型能正确接受包含所有字段的分析结果数据。
    """
    data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000",
        "reviewer": "quant",
        "verdict": "PASS",
        "total_score": 85.5,
        "signal_type": "买入信号",
        "comment": "技术面表现良好"
    }

    analysis = AnalysisItem(**data)

    assert analysis.id == 1
    assert analysis.pick_date == date(2024, 1, 15)
    assert analysis.code == "600000"
    assert analysis.reviewer == "quant"
    assert analysis.verdict == "PASS"
    assert analysis.total_score == 85.5
    assert analysis.signal_type == "买入信号"
    assert analysis.comment == "技术面表现良好"


@pytest.mark.unit
def test_analysis_item_minimal():
    """
    测试AnalysisItem模型的最小字段验证

    验证AnalysisItem模型只需要必填字段就能创建。
    """
    data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000"
    }

    analysis = AnalysisItem(**data)

    assert analysis.id == 1
    assert analysis.pick_date == date(2024, 1, 15)
    assert analysis.code == "600000"
    assert analysis.reviewer is None
    assert analysis.verdict is None


@pytest.mark.unit
def test_analysis_result_response_valid():
    """
    测试AnalysisResultResponse模型验证

    验证AnalysisResultResponse模型正确表示分析结果响应。
    """
    data = {
        "pick_date": date(2024, 1, 15),
        "results": [
            {
                "id": 1,
                "pick_date": date(2024, 1, 15),
                "code": "600000",
                "verdict": "PASS",
                "total_score": 85.5
            }
        ],
        "total": 1,
        "min_score_threshold": 60.0
    }

    response = AnalysisResultResponse(**data)

    assert response.pick_date == date(2024, 1, 15)
    assert len(response.results) == 1
    assert response.total == 1
    assert response.min_score_threshold == 60.0
    assert response.results[0].verdict == "PASS"


@pytest.mark.unit
def test_analysis_result_verdict_values():
    """
    测试AnalysisItem模型verdict字段的合法值

    验证verdict字段可以是PASS/WATCH/FAIL中的任意值。
    """
    base_data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000"
    }

    for verdict in ["PASS", "WATCH", "FAIL"]:
        data = {**base_data, "verdict": verdict}
        analysis = AnalysisItem(**data)
        assert analysis.verdict == verdict


# ============================================
# 观察列表模型测试
# ============================================

@pytest.mark.unit
def test_watchlist_item_response():
    """
    测试WatchlistItem模型验证

    验证WatchlistItem模型正确表示观察列表项。
    """
    data = {
        "id": 1,
        "code": "600000",
        "name": "浦发银行",
        "add_reason": "技术面表现良好",
        "entry_price": 12.35,
        "position_ratio": 0.3,
        "priority": 5,
        "is_active": True,
        "added_at": datetime(2024, 1, 15, 10, 30, 0)
    }

    item = WatchlistItem(**data)

    assert item.id == 1
    assert item.code == "600000"
    assert item.name == "浦发银行"
    assert item.add_reason == "技术面表现良好"
    assert item.entry_price == 12.35
    assert item.position_ratio == 0.3
    assert item.priority == 5
    assert item.is_active is True
    assert item.added_at == datetime(2024, 1, 15, 10, 30, 0)


@pytest.mark.unit
def test_watchlist_create_request_default_priority():
    """
    测试WatchlistAddRequest模型默认优先级

    验证WatchlistAddRequest模型的priority默认值为0。
    """
    data = {
        "code": "600000",
        "entry_price": 12.35,
        "position_ratio": 0.3,
    }

    request = WatchlistAddRequest(**data)

    assert request.code == "600000"
    assert request.reason is None
    assert request.entry_price == 12.35
    assert request.position_ratio == 0.3
    assert request.priority == 0


@pytest.mark.unit
def test_watchlist_create_request_with_reason():
    """
    测试WatchlistAddRequest模型带原因

    验证WatchlistAddRequest模型可以包含添加原因。
    """
    data = {
        "code": "600000",
        "reason": "突破重要阻力位",
        "entry_price": 18.8,
        "position_ratio": 0.5,
        "priority": 3
    }

    request = WatchlistAddRequest(**data)

    assert request.code == "600000"
    assert request.reason == "突破重要阻力位"
    assert request.entry_price == 18.8
    assert request.position_ratio == 0.5
    assert request.priority == 3


@pytest.mark.unit
def test_watchlist_update_request_partial():
    """
    测试WatchlistUpdateRequest模型部分更新

    验证WatchlistUpdateRequest模型可以进行部分字段更新。
    """
    # 只更新priority
    data = {"priority": 5}
    request = WatchlistUpdateRequest(**data)

    assert request.priority == 5
    assert request.reason is None
    assert request.is_active is None

    # 只更新is_active
    data = {"is_active": False}
    request = WatchlistUpdateRequest(**data)

    assert request.is_active is False
    assert request.reason is None
    assert request.priority is None

    data = {"entry_price": None, "position_ratio": None}
    request = WatchlistUpdateRequest(**data)

    assert request.entry_price is None
    assert request.position_ratio is None


@pytest.mark.unit
def test_watchlist_response_valid():
    """
    测试WatchlistResponse模型验证

    验证WatchlistResponse模型正确表示观察列表响应。
    """
    data = {
        "items": [
            {
                "id": 1,
                "code": "600000",
                "name": "浦发银行",
                "priority": 5,
                "is_active": True,
                "added_at": datetime(2024, 1, 15, 10, 30, 0)
            }
        ],
        "total": 1
    }

    response = WatchlistResponse(**data)

    assert len(response.items) == 1
    assert response.total == 1
    assert response.items[0].code == "600000"


# ============================================
# 任务模型测试
# ============================================

@pytest.mark.unit
def test_task_response():
    """
    测试TaskResponse模型验证

    验证TaskResponse模型正确表示任务响应。
    """
    data = {
        "task": {
            "id": 1,
            "task_type": "full_update",
            "status": "running",
            "progress": 50,
            "params_json": {"reviewer": "quant"},
            "result_json": None,
            "error_message": None,
            "started_at": datetime(2024, 1, 15, 10, 0, 0),
            "completed_at": None,
            "created_at": datetime(2024, 1, 15, 9, 55, 0)
        },
        "ws_url": "ws://localhost:8000/ws/tasks/1"
    }

    response = TaskResponse(**data)

    assert response.task.id == 1
    assert response.task.task_type == "full_update"
    assert response.task.status == "running"
    assert response.task.progress == 50
    assert response.ws_url == "ws://localhost:8000/ws/tasks/1"


@pytest.mark.unit
def test_task_create_request():
    """
    测试TaskCreateRequest模型验证

    验证TaskCreateRequest模型正确接受任务创建参数。
    """
    data = {
        "task_type": "single_analysis",
        "params": {"code": "600000"}
    }

    request = TaskCreateRequest(**data)

    assert request.task_type == "single_analysis"
    assert request.params == {"code": "600000"}


@pytest.mark.unit
def test_task_create_request_without_params():
    """
    测试TaskCreateRequest模型不包含params

    验证params是可选的。
    """
    data = {"task_type": "full_update"}

    request = TaskCreateRequest(**data)

    assert request.task_type == "full_update"
    assert request.params is None


@pytest.mark.unit
def test_task_item_full():
    """
    测试TaskItem模型的完整数据验证

    验证TaskItem模型能正确接受包含所有字段的任务数据。
    """
    data = {
        "id": 1,
        "task_type": "full_update",
        "status": "completed",
        "progress": 100,
        "params_json": {"skip_fetch": False},
        "result_json": {"candidates_count": 10},
        "error_message": None,
        "started_at": datetime(2024, 1, 15, 10, 0, 0),
        "completed_at": datetime(2024, 1, 15, 10, 30, 0),
        "created_at": datetime(2024, 1, 15, 9, 55, 0)
    }

    task = TaskItem(**data)

    assert task.id == 1
    assert task.status == "completed"
    assert task.progress == 100


@pytest.mark.unit
def test_task_status_values():
    """
    测试TaskItem模型status字段的合法值

    验证status字段可以是pending/running/completed/failed中的任意值。
    """
    base_data = {
        "id": 1,
        "task_type": "full_update",
        "progress": 0,
        "created_at": datetime(2024, 1, 15, 10, 0, 0)
    }

    for status in ["pending", "running", "completed", "failed"]:
        data = {**base_data, "status": status}
        task = TaskItem(**data)
        assert task.status == status


@pytest.mark.unit
def test_task_list_response():
    """
    测试TaskListResponse模型验证

    验证TaskListResponse模型正确表示任务列表响应。
    """
    data = {
        "tasks": [
            {
                "id": 1,
                "task_type": "full_update",
                "status": "completed",
                "progress": 100,
                "created_at": datetime(2024, 1, 15, 10, 0, 0)
            },
            {
                "id": 2,
                "task_type": "single_analysis",
                "status": "pending",
                "progress": 0,
                "created_at": datetime(2024, 1, 15, 11, 0, 0)
            }
        ],
        "total": 2
    }

    response = TaskListResponse(**data)

    assert len(response.tasks) == 2
    assert response.total == 2


# ============================================
# K线数据模型测试
# ============================================

@pytest.mark.unit
def test_kline_request_default_values():
    """
    测试KLineDataRequest模型默认值验证

    验证KLineDataRequest模型的默认值: days=120, include_weekly=True
    """
    data = {"code": "600000"}

    request = KLineDataRequest(**data)

    assert request.code == "600000"
    assert request.days == 120
    assert request.include_weekly is True


@pytest.mark.unit
def test_kline_request_custom_values():
    """
    测试KLineDataRequest模型自定义值验证

    验证KLineDataRequest模型可以接受自定义的days和include_weekly值。
    """
    data = {
        "code": "600000",
        "days": 60,
        "include_weekly": False
    }

    request = KLineDataRequest(**data)

    assert request.code == "600000"
    assert request.days == 60
    assert request.include_weekly is False


@pytest.mark.unit
def test_kline_data_point_full():
    """
    测试KLineDataPoint模型的完整数据验证

    验证KLineDataPoint模型能正确接受包含所有字段的K线数据。
    """
    data = {
        "date": "2024-01-15",
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.3,
        "volume": 1000000,
        "ma5": 10.1,
        "ma10": 10.0,
        "ma20": 9.9,
        "ma60": 9.8
    }

    point = KLineDataPoint(**data)

    assert point.date == "2024-01-15"
    assert point.open == 10.0
    assert point.high == 10.5
    assert point.low == 9.8
    assert point.close == 10.3
    assert point.volume == 1000000
    assert point.ma5 == 10.1
    assert point.ma10 == 10.0
    assert point.ma20 == 9.9
    assert point.ma60 == 9.8


@pytest.mark.unit
def test_kline_data_point_minimal():
    """
    测试KLineDataPoint模型的最小字段验证

    验证KLineDataPoint模型只需要必填字段就能创建，MA指标是可选的。
    """
    data = {
        "date": "2024-01-15",
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.3,
        "volume": 1000000
    }

    point = KLineDataPoint(**data)

    assert point.date == "2024-01-15"
    assert point.open == 10.0
    assert point.ma5 is None
    assert point.ma10 is None


@pytest.mark.unit
def test_kline_response_with_weekly():
    """
    测试KLineResponse模型包含周线数据

    验证KLineResponse模型可以同时包含日线和周线数据。
    """
    data = {
        "code": "600000",
        "name": "浦发银行",
        "daily": [
            {
                "date": "2024-01-15",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.3,
                "volume": 1000000
            }
        ],
        "weekly": [
            {
                "date": "2024-01-12",
                "open": 9.8,
                "high": 10.5,
                "low": 9.5,
                "close": 10.2,
                "volume": 5000000
            }
        ],
        "indicators": {"kdj": {"j": 85.5}}
    }

    response = KLineResponse(**data)

    assert response.code == "600000"
    assert response.name == "浦发银行"
    assert len(response.daily) == 1
    assert len(response.weekly) == 1
    assert response.indicators == {"kdj": {"j": 85.5}}


@pytest.mark.unit
def test_kline_response_without_weekly():
    """
    测试KLineResponse模型不包含周线数据

    验证weekly和indicators是可选的。
    """
    data = {
        "code": "600000",
        "daily": [
            {
                "date": "2024-01-15",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.3,
                "volume": 1000000
            }
        ]
    }

    response = KLineResponse(**data)

    assert response.code == "600000"
    assert len(response.daily) == 1
    assert response.weekly is None
    assert response.indicators is None


# ============================================
# 数据更新状态模型测试
# ============================================

@pytest.mark.unit
def test_data_status_response():
    """
    测试DataStatusResponse模型验证

    验证DataStatusResponse模型正确表示数据更新状态。
    """
    data = {
        "raw_data": {"exists": True, "count": 5000, "latest_date": "2024-01-15"},
        "candidates": {"exists": True, "count": 10, "latest_date": "2024-01-15"},
        "analysis": {"exists": True, "count": 10, "latest_date": "2024-01-15"},
        "kline": {"exists": True, "count": 100, "latest_date": "2024-01-15"}
    }

    response = DataStatusResponse(**data)

    assert response.raw_data["exists"] is True
    assert response.raw_data["count"] == 5000
    assert response.candidates["count"] == 10
    assert response.analysis["count"] == 10
    assert response.kline["count"] == 100


@pytest.mark.unit
def test_update_start_request_default_values():
    """
    测试UpdateStartRequest模型默认值验证

    验证UpdateStartRequest模型的默认值。
    """
    data = {}

    request = UpdateStartRequest(**data)

    assert request.reviewer == "quant"
    assert request.skip_fetch is False
    assert request.start_from == 1


@pytest.mark.unit
def test_update_start_request_custom_values():
    """
    测试UpdateStartRequest模型自定义值验证

    验证UpdateStartRequest模型可以接受自定义值。
    """
    data = {
        "reviewer": "glm",
        "skip_fetch": True,
        "start_from": 5
    }

    request = UpdateStartRequest(**data)

    assert request.reviewer == "glm"
    assert request.skip_fetch is True
    assert request.start_from == 5


# ============================================
# 单股诊断模型测试
# ============================================

@pytest.mark.unit
def test_b1_check_item_full():
    """
    测试B1CheckItem模型的完整数据验证

    验证B1CheckItem模型能正确接受包含所有字段的诊断数据。
    """
    data = {
        "check_date": date(2024, 1, 15),
        "close_price": 10.5,
        "change_pct": 2.5,
        "kdj_j": 85.5,
        "kdj_low_rank": 0.1,
        "zx_long_pos": True,
        "weekly_ma_aligned": True,
        "volume_healthy": True,
        "in_active_pool": True,
        "b1_passed": True,
        "prefilter_passed": True,
        "prefilter_blocked_by": [],
        "score": 85.0,
        "verdict": "PASS",
        "signal_type": "trend_start",
        "tomorrow_star_pass": True,
        "notes": "技术面表现良好"
    }

    check = B1CheckItem(**data)

    assert check.check_date == date(2024, 1, 15)
    assert check.close_price == 10.5
    assert check.change_pct == 2.5
    assert check.in_active_pool is True
    assert check.b1_passed is True
    assert check.prefilter_passed is True
    assert check.prefilter_blocked_by == []
    assert check.score == 85.0
    assert check.tomorrow_star_pass is True


@pytest.mark.unit
def test_diagnosis_request_valid():
    """
    测试DiagnosisRequest模型验证

    验证DiagnosisRequest模型正确接受股票代码。
    """
    data = {"code": "600000"}

    request = DiagnosisRequest(**data)

    assert request.code == "600000"


@pytest.mark.unit
def test_diagnosis_response_valid():
    """
    测试DiagnosisResponse模型验证

    验证DiagnosisResponse模型正确表示诊断响应。
    """
    data = {
        "code": "600000",
        "name": "浦发银行",
        "current_price": 10.5,
        "b1_passed": True,
        "score": 85.0,
        "verdict": "PASS",
        "analysis": {
            "kdj": {"j": 85.5, "k": 80.0, "d": 75.0},
            "ma_aligned": True
        },
        "kline_data": {
            "daily": [
                {
                    "date": "2024-01-15",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.3,
                    "volume": 1000000
                }
            ]
        }
    }

    response = DiagnosisResponse(**data)

    assert response.code == "600000"
    assert response.name == "浦发银行"
    assert response.b1_passed is True
    assert response.score == 85.0
    assert response.verdict == "PASS"
    assert response.analysis["kdj"]["j"] == 85.5
    assert response.kline_data is not None


@pytest.mark.unit
def test_diagnosis_history_response():
    """
    测试DiagnosisHistoryResponse模型验证

    验证DiagnosisHistoryResponse模型正确表示诊断历史响应。
    """
    data = {
        "code": "600000",
        "name": "浦发银行",
        "history": [
            {
                "check_date": date(2024, 1, 15),
                "close_price": 10.5,
                "b1_passed": True,
                "score": 85.0
            },
            {
                "check_date": date(2024, 1, 14),
                "close_price": 10.2,
                "b1_passed": False,
                "score": 45.0
            }
        ],
        "total": 2
    }

    response = DiagnosisHistoryResponse(**data)

    assert response.code == "600000"
    assert response.name == "浦发银行"
    assert len(response.history) == 2
    assert response.total == 2


@pytest.mark.unit
def test_watchlist_analysis_item():
    """
    测试WatchlistAnalysisItem模型验证

    验证WatchlistAnalysisItem模型正确表示观察分析项。
    """
    data = {
        "id": 1,
        "watchlist_id": 1,
        "analysis_date": date(2024, 1, 15),
        "close_price": 10.5,
        "verdict": "PASS",
        "score": 85.0,
        "trend_outlook": "bullish",
        "buy_action": "buy",
        "hold_action": "add_on_pullback",
        "risk_level": "low",
        "buy_recommendation": "可试仓，不追高。",
        "hold_recommendation": "可继续持有，强势突破再小幅加仓。",
        "risk_recommendation": "关注回踩支撑是否有效。",
        "support_level": 9.8,
        "resistance_level": 11.0,
        "recommendation": "建议买入"
    }

    item = WatchlistAnalysisItem(**data)

    assert item.id == 1
    assert item.watchlist_id == 1
    assert item.analysis_date == date(2024, 1, 15)
    assert item.verdict == "PASS"
    assert item.trend_outlook == "bullish"
    assert item.buy_action == "buy"
    assert item.hold_action == "add_on_pullback"
    assert item.risk_level == "low"
    assert item.buy_recommendation == "可试仓，不追高。"
    assert item.hold_recommendation == "可继续持有，强势突破再小幅加仓。"
    assert item.risk_recommendation == "关注回踩支撑是否有效。"


# ============================================
# 数据验证测试
# ============================================

@pytest.mark.unit
def test_date_parsing():
    """
    测试日期解析验证

    验证模型能正确解析date类型的字段。
    """
    # 使用date对象
    data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000"
    }

    candidate = CandidateItem(**data)

    assert candidate.pick_date == date(2024, 1, 15)


@pytest.mark.unit
def test_datetime_parsing():
    """
    测试日期时间解析验证

    验证模型能正确解析datetime类型的字段。
    """
    now = datetime(2024, 1, 15, 10, 30, 0)
    data = {
        "id": 1,
        "code": "600000",
        "priority": 5,
        "is_active": True,
        "added_at": now
    }

    item = WatchlistItem(**data)

    assert item.added_at == now


# ============================================
# 边界条件测试
# ============================================

@pytest.mark.unit
def test_none_values_handling():
    """
    测试None值处理验证

    验证Optional字段能正确处理None值。
    """
    data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000",
        "strategy": None,
        "close_price": None,
        "turnover": None,
        "b1_passed": None,
        "kdj_j": None
    }

    candidate = CandidateItem(**data)

    assert candidate.strategy is None
    assert candidate.close_price is None
    assert candidate.turnover is None
    assert candidate.b1_passed is None
    assert candidate.kdj_j is None


@pytest.mark.unit
def test_boundary_values():
    """
    测试边界值验证

    验证数值型字段能正确处理边界值。
    """
    # 测试0值
    data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000",
        "close_price": 0.01,  # 最小股价
        "turnover": 0.0
    }

    candidate = CandidateItem(**data)

    assert candidate.close_price == 0.01
    assert candidate.turnover == 0.0

    # 测试大数值
    data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000",
        "turnover": 999999999999.99
    }

    candidate = CandidateItem(**data)

    assert candidate.turnover == 999999999999.99


@pytest.mark.unit
def test_negative_progress_rejection():
    """
    测试负数进度值处理

    在实际应用中，任务进度不应为负数。
    """
    # 注意：Pydantic默认不验证数值范围，这里测试实际行为
    data = {
        "id": 1,
        "task_type": "full_update",
        "status": "running",
        "progress": -10,  # 负数进度
        "created_at": datetime(2024, 1, 15, 10, 0, 0)
    }

    task = TaskItem(**data)
    assert task.progress == -10  # Pydantic会接受这个值


@pytest.mark.unit
def test_score_boundary_values():
    """
    测试分数边界值

    验证分数字段能正确处理0-100的边界值。
    """
    data = {
        "id": 1,
        "pick_date": date(2024, 1, 15),
        "code": "600000",
        "total_score": 0.0
    }

    analysis = AnalysisItem(**data)
    assert analysis.total_score == 0.0

    data["total_score"] = 100.0
    analysis = AnalysisItem(**data)
    assert analysis.total_score == 100.0


@pytest.mark.unit
def test_empty_list_handling():
    """
    测试空列表处理

    验证模型能正确处理空列表。
    """
    data = {
        "configs": []
    }

    response = ConfigResponse(**data)
    assert len(response.configs) == 0

    data = {
        "candidates": [],
        "total": 0
    }

    response = CandidatesResponse(**data)
    assert len(response.candidates) == 0
    assert response.total == 0


# ============================================
# JSON序列化测试
# ============================================

@pytest.mark.unit
def test_model_serialization():
    """
    测试模型序列化

    验证Pydantic模型能正确序列化为JSON。
    """
    data = {
        "key": "test_key",
        "value": "test_value",
        "description": "test description"
    }

    config = ConfigItem(**data)

    # 测试model_dump()方法
    serialized = config.model_dump()
    assert serialized["key"] == "test_key"
    assert serialized["value"] == "test_value"
    assert serialized["description"] == "test description"

    # 测试model_dump_json()方法
    json_str = config.model_dump_json()
    assert "test_key" in json_str
    assert "test_value" in json_str


@pytest.mark.unit
def test_model_with_dict_field():
    """
    测试包含字典字段的模型

    验证包含Dict字段的模型能正确处理。
    """
    data = {
        "code": "600000",
        "name": "浦发银行",
        "b1_passed": True,
        "score": 85.0,
        "verdict": "PASS",
        "analysis": {
            "kdj": {"j": 85.5},
            "ma": {"aligned": True}
        }
    }

    response = DiagnosisResponse(**data)

    assert response.analysis["kdj"]["j"] == 85.5
    assert response.analysis["ma"]["aligned"] is True


@pytest.mark.unit
def test_nested_models():
    """
    测试嵌套模型

    验证包含嵌套模型的响应能正确处理。
    """
    data = {
        "pick_date": date(2024, 1, 15),
        "results": [
            {
                "id": 1,
                "pick_date": date(2024, 1, 15),
                "code": "600000",
                "verdict": "PASS"
            }
        ],
        "total": 1,
        "min_score_threshold": 60.0
    }

    response = AnalysisResultResponse(**data)

    assert isinstance(response.results, list)
    assert isinstance(response.results[0], AnalysisItem)
    assert response.results[0].verdict == "PASS"
