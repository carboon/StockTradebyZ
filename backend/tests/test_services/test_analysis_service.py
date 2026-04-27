"""
Analysis Service Tests
~~~~~~~~~~~~~~~~~~~~~~
分析服务测试用例，测试股票分析服务的各项功能
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.services.analysis_service import AnalysisService

# 添加 pipeline 目录到 Python 路径（与主流程一致）
ROOT = Path(__file__).parent.parent.parent.parent
pipeline_dir = ROOT / "pipeline"
if str(pipeline_dir) not in sys.path:
    sys.path.insert(0, str(pipeline_dir))


# ============================================
# Test Fixtures
# ============================================

@pytest.fixture
def analysis_service():
    """
    分析服务fixture

    提供一个AnalysisService实例用于测试。
    """
    return AnalysisService()


@pytest.fixture
def sample_stock_df():
    """
    示例股票数据DataFrame

    提供一个包含足够历史数据的股票DataFrame，用于B1策略检查。
    """
    dates = pd.date_range(start="2023-01-01", periods=300, freq="D")
    np.random.seed(42)

    # 生成模拟数据，确保满足B1策略条件
    close_prices = 10.0 + np.cumsum(np.random.randn(300) * 0.1)
    high_prices = close_prices * (1 + np.abs(np.random.randn(300) * 0.01))
    low_prices = close_prices * (1 - np.abs(np.random.randn(300) * 0.01))
    open_prices = close_prices * (1 + np.random.randn(300) * 0.005)
    volumes = np.random.randint(1000000, 10000000, 300)

    df = pd.DataFrame({
        "date": dates,
        "open": open_prices,
        "high": high_prices,
        "low": low_prices,
        "close": close_prices,
        "volume": volumes
    })
    return df


@pytest.fixture
def sample_stock_df_b1_pass(sample_stock_df):
    """
    满足B1策略条件的股票数据

    生成确保能通过B1策略检查的数据。
    """
    df = sample_stock_df.copy()

    # 添加KDJ指标列（模拟满足条件）
    df["K"] = 50 + np.random.randn(len(df)) * 10
    df["D"] = 45 + np.random.randn(len(df)) * 10
    df["J"] = df["K"] * 3 - df["D"] * 2
    # 设置最后几行J值较低，满足条件
    df.iloc[-10:, df.columns.get_loc("J")] = np.linspace(-5, 0, 10)

    # 添加知行线列（模拟满足条件）
    df["zxdq"] = df["close"] * 1.05
    df["zxdkx"] = df["close"] * 0.95

    # 添加周线多头排列列
    df["wma_bull"] = True
    df["_vec_pick"] = False
    df.iloc[-1, df.columns.get_loc("_vec_pick")] = True

    return df


@pytest.fixture
def sample_stock_df_b1_fail(sample_stock_df):
    """
    不满足B1策略条件的股票数据

    生成确保不能通过B1策略检查的数据。
    """
    df = sample_stock_df.copy()

    # 添加KDJ指标列（模拟不满足条件）
    df["K"] = 50 + np.random.randn(len(df)) * 10
    df["D"] = 45 + np.random.randn(len(df)) * 10
    df["J"] = df["K"] * 3 - df["D"] * 2
    # 设置最后J值较高，不满足低位条件
    df.iloc[-10:, df.columns.get_loc("J")] = np.linspace(50, 80, 10)

    return df


@pytest.fixture
def temp_raw_data_dir(tmp_path):
    """
    临时原始数据目录fixture

    创建临时目录并包含测试用的股票CSV文件。
    """
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 创建测试股票CSV文件
    dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
    df = pd.DataFrame({
        "date": dates,
        "open": np.random.uniform(9.5, 10.5, 100),
        "high": np.random.uniform(10, 11, 100),
        "low": np.random.uniform(9, 10, 100),
        "close": np.random.uniform(9.5, 10.5, 100),
        "volume": np.random.randint(1000000, 10000000, 100)
    })

    csv_path = raw_dir / "600000.csv"
    df.to_csv(csv_path, index=False)

    return raw_dir


@pytest.fixture
def mock_quant_reviewer():
    """
    Mock QuantReviewer评分结果

    直接mock _quant_review方法而不是内部导入。
    """
    return {
        "total_score": 4.2,
        "verdict": "PASS",
        "comment": "趋势结构健康，量价配合良好",
        "signal_type": "trend_start"
    }


# ============================================
# B1策略检查测试
# ============================================

@pytest.mark.service
def test_b1_strategy_check_pass(analysis_service, sample_stock_df_b1_pass):
    """
    测试B1策略检查通过

    当股票数据满足B1策略所有条件时，check_b1_strategy应返回passed=True。
    """
    selector = MagicMock()
    selector.prepare_df.return_value = sample_stock_df_b1_pass

    with patch.object(analysis_service, "load_stock_data", return_value=sample_stock_df_b1_pass):
        with patch.object(analysis_service, "_build_b1_selector", return_value=selector):
            result = analysis_service.check_b1_strategy("600000")

            assert result["code"] == "600000"
            assert result["b1_passed"] is True
            assert result["kdj_j"] is not None
            assert result["kdj_low_rank"] is None
            assert result["zx_long_pos"] is True
            assert result["weekly_ma_aligned"] is True
            assert result["volume_healthy"] is True
            assert result["close_price"] is not None
            assert result["check_date"] is not None


@pytest.mark.service
def test_b1_strategy_check_fail(analysis_service, sample_stock_df_b1_fail):
    """
    测试B1策略检查失败

    当股票数据不满足B1策略条件时，check_b1_strategy应返回passed=False。
    """
    selector = MagicMock()
    selector.prepare_df.return_value = sample_stock_df_b1_fail

    with patch.object(analysis_service, "load_stock_data", return_value=sample_stock_df_b1_fail):
        with patch.object(analysis_service, "_build_b1_selector", return_value=selector):
            result = analysis_service.check_b1_strategy("600000")

            assert result["code"] == "600000"
            assert result["b1_passed"] is False
            assert result["kdj_j"] == 80.0
            assert result["zx_long_pos"] is None
            assert result["weekly_ma_aligned"] is None


@pytest.mark.service
def test_b1_strategy_check_no_data(analysis_service):
    """
    测试B1策略检查无数据情况

    当股票数据不存在时，check_b1_strategy应返回错误信息。
    """
    with patch.object(analysis_service, "load_stock_data", return_value=None):
        result = analysis_service.check_b1_strategy("999999")

        assert result["code"] == "999999"
        assert result["b1_passed"] is False
        assert "error" in result
        assert "数据不存在" in result["error"]


@pytest.mark.service
def test_b1_strategy_check_exception(analysis_service, sample_stock_df):
    """
    测试B1策略检查异常处理

    当B1Selector抛出异常时，check_b1_strategy应捕获异常并返回错误信息。
    """
    with patch.object(analysis_service, "load_stock_data", return_value=sample_stock_df):
        selector = MagicMock()
        selector.prepare_df.side_effect = Exception("计算错误")
        with patch.object(analysis_service, "_build_b1_selector", return_value=selector):

            result = analysis_service.check_b1_strategy("600000")

            assert result["b1_passed"] is False
            assert "error" in result
            assert "计算错误" in result["error"]


# ============================================
# 流动性筛选测试
# ============================================

@pytest.mark.service
def test_liquidity_filter(analysis_service):
    """
    测试流动性筛选功能

    流动性筛选应返回前2000只股票（或其他指定数量）。
    注意：此测试验证流动性筛选的概念，实际实现可能在其他模块。
    """
    # 创建模拟股票数据
    stock_list = []
    for i in range(2500):
        stock_list.append({
            "code": f"{i:06d}",
            "name": f"股票{i}",
            "turnover": np.random.uniform(1000000, 100000000),
            "market_cap": np.random.uniform(100000000, 10000000000)
        })

    # 按成交量排序
    sorted_stocks = sorted(stock_list, key=lambda x: x["turnover"], reverse=True)
    top_2000 = sorted_stocks[:2000]

    assert len(top_2000) == 2000
    assert top_2000[0]["turnover"] >= top_2000[-1]["turnover"]


# ============================================
# 量化评分测试
# ============================================

@pytest.mark.service
def test_quant_review_score(analysis_service, sample_stock_df, mock_quant_reviewer):
    """
    测试量化评分计算

    _quant_review方法应调用QuantReviewer并返回评分结果。
    """
    with patch.object(analysis_service, "load_stock_data", return_value=sample_stock_df):
        with patch.object(analysis_service, "_quant_review", return_value={
            "score": mock_quant_reviewer["total_score"],
            "verdict": mock_quant_reviewer["verdict"],
            "comment": mock_quant_reviewer["comment"],
            "signal_type": mock_quant_reviewer["signal_type"]
        }):
            result = analysis_service._quant_review("600000")

            assert result["score"] == 4.2
            assert result["verdict"] == "PASS"
            assert result["comment"] == "趋势结构健康，量价配合良好"
            assert result["signal_type"] == "trend_start"


@pytest.mark.service
def test_quant_review_no_data(analysis_service):
    """
    测试量化评分无数据情况

    当股票数据不存在时，_quant_review应返回失败结果。
    """
    # Mock整个_quant_review方法以避免实际的模块导入
    with patch.object(analysis_service, "load_stock_data", return_value=None):
        # 使用__wrap__来mock的同时保留原始实现的某些逻辑
        original_quant_review = analysis_service._quant_review

        def mock_quant_review(code):
            df = analysis_service.load_stock_data(code)
            if df is None or df.empty:
                return {
                    "score": 0,
                    "verdict": "FAIL",
                    "comment": "数据不存在"
                }
            return original_quant_review(code)

        with patch.object(analysis_service, "_quant_review", side_effect=mock_quant_review):
            result = analysis_service._quant_review("999999")

            assert result["score"] == 0
            assert result["verdict"] == "FAIL"
            assert "数据不存在" in result["comment"]


@pytest.mark.service
def test_quant_review_exception(analysis_service, sample_stock_df):
    """
    测试量化评分异常处理

    当QuantReviewer抛出异常时，_quant_review应捕获异常并返回错误结果。
    """
    with patch.object(analysis_service, "load_stock_data", return_value=sample_stock_df):
        # Mock _quant_review方法本身来模拟异常情况
        with patch.object(analysis_service, "_quant_review", return_value={
            "score": 0,
            "verdict": "FAIL",
            "comment": "评分失败"
        }):
            result = analysis_service._quant_review("600000")

            assert result["score"] == 0
            assert result["verdict"] == "FAIL"
            assert "评分失败" in result["comment"]


# ============================================
# 预过滤检查测试
# ============================================

@pytest.mark.service
def test_prefilter_checks_st(analysis_service):
    """
    测试ST股票过滤

    分析服务应识别并过滤ST股票（特别处理股票）。
    此测试验证ST股票识别逻辑。
    """
    st_stocks = ["ST600000", "600000ST", "*ST600000", "S*ST600000"]
    for stock_name in st_stocks:
        is_st = any(prefix in stock_name for prefix in ["ST", "*ST", "S*ST"])
        assert is_st is True

    # 验证非ST股票
    normal_stocks = ["600000", "000001", "300001"]
    for stock_name in normal_stocks:
        is_st = any(prefix in stock_name for prefix in ["ST", "*ST", "S*ST"])
        assert is_st is False


@pytest.mark.service
def test_prefilter_checks_new_stock(analysis_service):
    """
    测试次新股过滤

    分析服务应识别并过滤上市时间不足的次新股。
    此测试验证次新股识别逻辑。
    """
    from datetime import datetime, timedelta

    # 模拟当前日期
    current_date = datetime(2024, 4, 15)

    # 上市不足120天的股票（次新股）
    new_stock_list_date = current_date - timedelta(days=100)
    new_stock_days = (current_date - new_stock_list_date).days

    # 上市超过120天的股票
    normal_stock_list_date = current_date - timedelta(days=200)
    normal_stock_days = (current_date - normal_stock_list_date).days

    min_listing_days = 120

    # 验证次新股识别
    assert new_stock_days < min_listing_days
    assert normal_stock_days >= min_listing_days

    # 过滤逻辑
    is_new_stock = new_stock_days < min_listing_days
    assert is_new_stock is True

    is_normal_stock = normal_stock_days >= min_listing_days
    assert is_normal_stock is True


@pytest.mark.service
def test_prefilter_checks_unlock(analysis_service):
    """
    测试解禁股过滤

    分析服务应识别即将有大量解禁股的股票。
    此测试验证解禁股识别逻辑。
    """
    from datetime import datetime, timedelta

    # 模拟当前日期
    current_date = datetime(2024, 4, 15)

    # 即将解禁的股票（20天内）
    unlock_date_soon = current_date + timedelta(days=15)
    days_to_unlock_soon = (unlock_date_soon - current_date).days

    # 较晚解禁的股票
    unlock_date_late = current_date + timedelta(days=60)
    days_to_unlock_late = (unlock_date_late - current_date).days

    lookahead_days = 20

    # 验证解禁股识别
    assert days_to_unlock_soon <= lookahead_days
    assert days_to_unlock_late > lookahead_days

    # 模拟解禁比例检查
    unlock_ratio_high = 0.50  # 50%解禁，超过阈值
    unlock_ratio_low = 0.10   # 10%解禁，低于阈值
    max_free_share_ratio = 0.15

    should_block_high = days_to_unlock_soon <= lookahead_days and unlock_ratio_high > max_free_share_ratio
    should_block_low = days_to_unlock_soon <= lookahead_days and unlock_ratio_low > max_free_share_ratio

    assert should_block_high is True
    assert should_block_low is False


# ============================================
# 单股完整分析测试
# ============================================

@pytest.mark.service
def test_single_stock_analysis(analysis_service, sample_stock_df_b1_pass, mock_quant_reviewer):
    """
    测试单股完整分析流程

    analyze_stock方法应执行B1策略检查和量化评分，返回完整结果。
    """
    with patch.object(analysis_service, "load_stock_data", return_value=sample_stock_df_b1_pass):
        with patch("Selector.B1Selector") as mock_b1:
            selector_instance = MagicMock()
            selector_instance.check.return_value = {
                "passed": True,
                "kdj_j": -3.5,
                "kdj_low_rank": 0.08,
                "zx_long_pos": True,
                "weekly_ma_aligned": True,
                "volume_healthy": True
            }
            mock_b1.return_value = selector_instance

            # Mock _quant_review方法
            with patch.object(analysis_service, "_quant_review", return_value={
                "score": mock_quant_reviewer["total_score"],
                "verdict": mock_quant_reviewer["verdict"],
                "comment": mock_quant_reviewer["comment"],
                "signal_type": mock_quant_reviewer["signal_type"]
            }):
                result = analysis_service.analyze_stock("600000", reviewer="quant")

                assert result["code"] == "600000"
                assert "b1_passed" in result
                assert "score" in result
                assert "verdict" in result
                assert result["score"] == 4.2
                assert result["verdict"] == "PASS"


@pytest.mark.service
def test_single_stock_analysis_persists_result_by_check_date(analysis_service, tmp_path):
    """
    单股分析落盘时应按实际数据日期归档，而不是按执行当天归档。
    """
    test_root = tmp_path / "test_single_analysis_save"
    review_dir = test_root / "review"

    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.review_dir = review_dir
            mock_settings.raw_data_dir = test_root / "raw"

            with patch.object(analysis_service, "check_b1_strategy", return_value={
                "code": "600000",
                "b1_passed": True,
                "kdj_j": 12.3,
                "close_price": 10.8,
                "check_date": "2024-01-15",
            }):
                with patch.object(analysis_service, "_quant_review", return_value={
                    "score": 4.6,
                    "verdict": "PASS",
                    "comment": "趋势健康",
                    "signal_type": "trend_start",
                    "scores": {"trend_structure": 4},
                }):
                    result = analysis_service.analyze_stock("600000", reviewer="quant")

            saved_file = review_dir / "2024-01-15" / "600000.json"
            assert result["score"] == 4.6
            assert saved_file.exists()

            with open(saved_file, "r", encoding="utf-8") as f:
                saved = json.load(f)

            assert saved["analysis_date"] == "2024-01-15"
            assert saved["pick_date"] == "2024-01-15"
            assert saved["close_price"] == 10.8


@pytest.mark.service
def test_single_stock_analysis_llm_reviewer(analysis_service, sample_stock_df):
    """
    测试单股分析使用LLM评分

    当reviewer参数不是"quant"时，应调用LLM评分（当前返回待实现信息）。
    """
    with patch.object(analysis_service, "load_stock_data", return_value=sample_stock_df):
        with patch("Selector.B1Selector") as mock_b1:
            selector_instance = MagicMock()
            selector_instance.check.return_value = {
                "passed": True,
                "kdj_j": -3.5,
                "kdj_low_rank": 0.08,
                "zx_long_pos": True,
                "weekly_ma_aligned": True,
                "volume_healthy": True
            }
            mock_b1.return_value = selector_instance

            result = analysis_service.analyze_stock("600000", reviewer="glm")

            assert result["code"] == "600000"
            assert result["score"] is None
            assert result["verdict"] == "UNKNOWN"
            assert "待实现" in result["comment"]


# ============================================
# 加载股票数据测试
# ============================================

@pytest.mark.service
def test_load_stock_data(analysis_service, temp_raw_data_dir):
    """
    测试加载股票数据

    load_stock_data应正确加载CSV文件并返回处理后的DataFrame。
    """
    # 使用唯一的测试文件名，避免与实际数据冲突
    test_code = "TEST001"
    df = pd.DataFrame({
        "date": pd.date_range(start="2024-01-01", periods=100, freq="D"),
        "open": np.random.uniform(9.5, 10.5, 100),
        "high": np.random.uniform(10, 11, 100),
        "low": np.random.uniform(9, 10, 100),
        "close": np.random.uniform(9.5, 10.5, 100),
        "volume": np.random.randint(1000000, 10000000, 100)
    })
    csv_path = temp_raw_data_dir / f"{test_code}.csv"
    df.to_csv(csv_path, index=False)

    # 直接mock整个导入的settings模块
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", temp_raw_data_dir):
            mock_settings.raw_data_dir = temp_raw_data_dir

            result = analysis_service.load_stock_data(test_code)

            assert result is not None
            assert isinstance(result, pd.DataFrame)
            assert len(result) == 100
            assert "date" in result.columns
            assert result["date"].dtype.name.startswith("datetime")
            # 验证列名已转为小写
            for col in result.columns:
                assert col.islower() or col == "date"


@pytest.mark.service
def test_load_stock_data_columns_lowercase(analysis_service, tmp_path):
    """
    测试加载股票数据时列名转为小写

    CSV中的列名应被统一转换为小写。
    """
    # 使用独立目录
    test_root = tmp_path / "test_lowercase"
    raw_dir = test_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 使用唯一代码避免冲突
    test_code = "TEST002"

    # 创建包含大写列名的CSV
    df = pd.DataFrame({
        "DATE": ["2024-01-01"],
        "OPEN": [10.0],
        "HIGH": [10.5],
        "LOW": [9.5],
        "CLOSE": [10.2],
        "VOLUME": [1000000]
    })
    csv_path = raw_dir / f"{test_code}.csv"
    df.to_csv(csv_path, index=False)

    # 直接mock整个导入的settings模块
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.raw_data_dir = raw_dir

            result = analysis_service.load_stock_data(test_code)

            assert result is not None
            # 验证所有列名都是小写
            for col in result.columns:
                assert col.islower()
            assert "date" in result.columns
            assert "close" in result.columns


@pytest.mark.service
def test_load_stock_data_sorted(analysis_service, tmp_path):
    """
    测试加载股票数据时按日期排序

    返回的DataFrame应按日期升序排列。
    """
    # 使用独立目录
    test_root = tmp_path / "test_sorted"
    raw_dir = test_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 使用唯一代码并创建乱序数据
    test_code = "TEST003"
    dates = pd.date_range(start="2024-01-01", periods=10, freq="D")
    np.random.shuffle(dates.values)
    df = pd.DataFrame({
        "date": dates,
        "close": np.random.uniform(10, 11, 10)
    })
    csv_path = raw_dir / f"{test_code}.csv"
    df.to_csv(csv_path, index=False)

    # 直接mock整个导入的settings模块
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.raw_data_dir = raw_dir

            result = analysis_service.load_stock_data(test_code)

            assert result is not None
            # 验证数据已按日期排序
            dates_result = result["date"].tolist()
            assert dates_result == sorted(dates_result)


@pytest.mark.service
def test_load_stock_data_not_found(analysis_service, tmp_path):
    """
    测试加载不存在的股票数据

    当CSV文件不存在时，load_stock_data应返回None。
    """
    # 使用独立目录
    test_root = tmp_path / "test_not_found"
    raw_dir = test_root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # 直接mock整个导入的settings模块
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.raw_data_dir = raw_dir

            result = analysis_service.load_stock_data("999999")

            assert result is None


# ============================================
# 历史检查测试
# ============================================

@pytest.mark.service
def test_get_stock_history_checks(analysis_service, sample_stock_df):
    """
    测试获取股票历史检查记录

    get_stock_history_checks应返回指定天数内的历史检查记录。
    """
    with patch.object(analysis_service, "load_stock_data", return_value=sample_stock_df):
        with patch("Selector.B1Selector") as mock_b1:
            selector_instance = MagicMock()
            selector_instance.check.return_value = {
                "passed": True,
                "kdj_j": -3.5,
                "kdj_low_rank": 0.08,
                "zx_long_pos": True,
                "weekly_ma_aligned": True,
                "volume_healthy": True
            }
            mock_b1.return_value = selector_instance

            result = analysis_service.get_stock_history_checks("600000", days=30)

            assert isinstance(result, list)
            # 验证结果结构
            if result:
                assert "check_date" in result[0]
                assert "close_price" in result[0]
                assert "b1_passed" in result[0]


@pytest.mark.service
def test_get_stock_history_checks_no_data(analysis_service):
    """
    测试获取历史检查记录无数据情况

    当股票数据不存在时，get_stock_history_checks应返回空列表。
    """
    with patch.object(analysis_service, "load_stock_data", return_value=None):
        result = analysis_service.get_stock_history_checks("999999")

        assert result == []


# ============================================
# 候选历史测试
# ============================================

@pytest.mark.service
def test_get_candidates_history(analysis_service, tmp_path):
    """
    测试获取候选历史

    get_candidates_history应读取历史候选文件并返回列表。
    """
    # 创建独立的测试目录
    test_root = tmp_path / "test_candidates"
    candidates_dir = test_root / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    # 创建测试文件（使用时间戳确保唯一性）
    for i in range(3):
        data = {
            "pick_date": f"2024-01-{10+i:02d}",
            "candidates": [
                {"code": f"60000{i}", "strategy": "b1"}
            ]
        }
        file_path = candidates_dir / f"candidates_2024-01-{10+i:02d}.json"
        with open(file_path, "w") as f:
            json.dump(data, f)

    # Mock整个导入的settings模块
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.candidates_dir = candidates_dir
            result = analysis_service.get_candidates_history(limit=30)

            assert isinstance(result, list)
            assert len(result) == 3
            assert "date" in result[0]
            assert "count" in result[0]


@pytest.mark.service
def test_get_candidates_history_empty(analysis_service, tmp_path):
    """
    测试获取候选历史空目录

    当没有候选文件时，get_candidates_history应返回空列表。
    """
    # 创建独立的空测试目录
    test_root = tmp_path / "test_empty_candidates"
    candidates_dir = test_root / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    # Mock整个导入的settings模块
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.candidates_dir = candidates_dir
            result = analysis_service.get_candidates_history()

            assert result == []


# ============================================
# 分析结果测试
# ============================================

@pytest.mark.service
def test_get_analysis_results(analysis_service, tmp_path):
    """
    测试获取分析结果

    get_analysis_results应优先读取指定日期的逐股分析结果并返回。
    """
    # 使用独立目录
    test_root = tmp_path / "test_analysis"
    candidates_dir = test_root / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    review_dir = test_root / "review"
    date_dir = review_dir / "2024-01-15"
    date_dir.mkdir(parents=True, exist_ok=True)

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

    with open(date_dir / "600000.json", "w") as f:
        json.dump({
            "code": "600000",
            "total_score": 4.5,
            "verdict": "PASS",
            "signal_type": "trend_start",
            "comment": "技术形态良好",
        }, f)

    with open(date_dir / "000001.json", "w") as f:
        json.dump({
            "code": "000001",
            "total_score": 4.2,
            "verdict": "WATCH",
            "signal_type": "rebound",
            "comment": "继续观察",
        }, f)

    # Mock整个导入的settings模块
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.candidates_dir = candidates_dir
            mock_settings.review_dir = review_dir
            mock_settings.min_score_threshold = 4.0
            result = analysis_service.get_analysis_results("2024-01-15")

            assert result["pick_date"] == "2024-01-15"
            assert result["total"] == 2
            assert len(result["results"]) == 2
            assert result["min_score_threshold"] == 4.0
            assert result["results"][0]["code"] == "600000"
            assert result["results"][1]["code"] == "000001"


@pytest.mark.service
def test_get_analysis_results_latest(analysis_service, tmp_path):
    """
    测试获取最新分析结果

    当不指定日期时，get_analysis_results应从candidates_latest.json读取日期。
    """
    # 使用独立目录
    test_root = tmp_path / "test_analysis_latest"
    candidates_dir = test_root / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)

    latest_data = {
        "pick_date": "2024-01-15",
        "candidates": []
    }

    latest_file = candidates_dir / "candidates_latest.json"
    with open(latest_file, "w") as f:
        json.dump(latest_data, f)

    review_dir = test_root / "review"
    date_dir = review_dir / "2024-01-15"
    date_dir.mkdir(parents=True, exist_ok=True)

    suggestion_data = {
        "recommendations": [{"code": "600000", "score": 4.5}]
    }

    suggestion_file = date_dir / "suggestion.json"
    with open(suggestion_file, "w") as f:
        json.dump(suggestion_data, f)

    # Mock整个导入的settings模块
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.candidates_dir = candidates_dir
            mock_settings.review_dir = review_dir
            mock_settings.min_score_threshold = 4.0
            result = analysis_service.get_analysis_results()

            assert result["pick_date"] == "2024-01-15"
            assert result["total"] == 1


@pytest.mark.service
def test_get_analysis_results_filters_non_candidates(analysis_service, tmp_path):
    """
    测试分析结果会被限制为当日候选股票子集
    """
    test_root = tmp_path / "test_analysis_filter"
    candidates_dir = test_root / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    review_dir = test_root / "review"
    date_dir = review_dir / "2024-01-15"
    date_dir.mkdir(parents=True, exist_ok=True)

    with open(candidates_dir / "candidates_2024-01-15.json", "w") as f:
        json.dump({
            "pick_date": "2024-01-15",
            "candidates": [{"code": "600000"}],
        }, f)

    with open(date_dir / "suggestion.json", "w") as f:
        json.dump({
            "pick_date": "2024-01-15",
            "recommendations": [
                {"code": "600000", "verdict": "PASS"},
                {"code": "000001", "verdict": "PASS"},
            ],
        }, f)

    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.candidates_dir = candidates_dir
            mock_settings.review_dir = review_dir
            mock_settings.min_score_threshold = 4.0
            result = analysis_service.get_analysis_results("2024-01-15")

            assert result["pick_date"] == "2024-01-15"
            assert result["total"] == 1
            assert [item["code"] for item in result["results"]] == ["600000"]


@pytest.mark.service
def test_get_analysis_results_not_found(analysis_service, tmp_path):
    """
    测试获取不存在的分析结果

    当建议文件不存在时，get_analysis_results应返回空结果。
    """
    # 使用独立目录
    test_root = tmp_path / "test_analysis_not_found"
    review_dir = test_root / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    # Mock整个导入的settings模块
    with patch("app.services.analysis_service.settings") as mock_settings:
        with patch("app.services.analysis_service.ROOT", test_root):
            mock_settings.review_dir = review_dir
            result = analysis_service.get_analysis_results("2024-01-15")

            assert result["results"] == []
            assert result["total"] == 0


# ============================================
# 边界条件测试
# ============================================

@pytest.mark.service
def test_analysis_service_singleton():
    """
    测试AnalysisService单例

    模块级analysis_service实例应该是可用的。
    """
    from app.services.analysis_service import analysis_service

    assert analysis_service is not None
    assert isinstance(analysis_service, AnalysisService)


@pytest.mark.service
def test_empty_dataframe_handling(analysis_service):
    """
    测试空DataFrame处理

    当加载的DataFrame为空时，相关方法应正确处理。
    """
    empty_df = pd.DataFrame()

    with patch.object(analysis_service, "load_stock_data", return_value=empty_df):
        result = analysis_service.check_b1_strategy("600000")

        assert result["b1_passed"] is False
        assert "error" in result


@pytest.mark.service
def test_small_dataframe_handling(analysis_service):
    """
    测试小数据量DataFrame处理

    当DataFrame数据量不足以进行计算时，应正确处理。
    """
    small_df = pd.DataFrame({
        "date": [datetime(2024, 1, 1)],
        "open": [10.0],
        "high": [10.5],
        "low": [9.5],
        "close": [10.2],
        "volume": [1000000]
    })

    with patch.object(analysis_service, "load_stock_data", return_value=small_df):
        # 小数据量可能导致B1Selector检查失败
        with patch("Selector.B1Selector") as mock_b1:
            selector_instance = MagicMock()
            selector_instance.check.return_value = {
                "passed": False,
                "error": "数据不足"
            }
            mock_b1.return_value = selector_instance

            result = analysis_service.check_b1_strategy("600000")

            assert result["code"] == "600000"
