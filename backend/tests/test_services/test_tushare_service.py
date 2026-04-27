"""
Tushare Service Tests
~~~~~~~~~~~~~~~~~~~~~
Tushare 服务测试用例
"""
import json
import os
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.tushare_service import TushareService


# ============================================
# Test Fixtures
# ============================================

@pytest.fixture
def tushare_service():
    """
    Tushare服务fixture

    提供一个带有测试token的TushareService实例。
    """
    return TushareService(token="test_token_123456")


@pytest.fixture
def mock_daily_df():
    """
    Mock日线数据DataFrame

    提供一个模拟的日线数据DataFrame，包含标准字段。
    """
    return pd.DataFrame({
        "ts_code": ["000001.SZ"],
        "trade_date": ["20240115"],
        "open": [10.5],
        "high": [10.8],
        "low": [10.4],
        "close": [10.7],
        "vol": [1000000],
        "amount": [10700000.0]
    })


@pytest.fixture
def mock_stock_list_df():
    """
    Mock股票列表DataFrame

    提供一个模拟的股票列表DataFrame。
    """
    return pd.DataFrame({
        "ts_code": ["000001.SZ", "600000.SH", "000858.SZ"],
        "symbol": ["000001", "600000", "000858"],
        "name": ["平安银行", "浦发银行", "五粮液"],
        "area": ["深圳", "上海", "四川"],
        "industry": ["银行", "银行", "白酒"],
        "market": ["主板", "主板", "主板"]
    })


@pytest.fixture
def mock_stock_csv_df():
    """
    Mock本地CSV股票数据DataFrame

    提供一个模拟的从本地CSV加载的股票数据DataFrame。
    """
    return pd.DataFrame({
        "Date": ["2024-01-10", "2024-01-11", "2024-01-12"],
        "Open": [10.0, 10.2, 10.5],
        "High": [10.3, 10.5, 10.8],
        "Low": [9.9, 10.1, 10.4],
        "Close": [10.2, 10.4, 10.7],
        "Volume": [1000000, 1200000, 1500000],
    })


@pytest.fixture
def temp_data_dir(tmp_path):
    """
    临时数据目录fixture

    创建一个临时数据目录结构，包含raw、candidates、review、kline子目录。
    """
    raw_dir = tmp_path / "raw"
    candidates_dir = tmp_path / "candidates"
    review_dir = tmp_path / "review"
    kline_dir = tmp_path / "kline"

    raw_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    kline_dir.mkdir(parents=True, exist_ok=True)

    # 创建测试CSV文件
    test_csv = raw_dir / "000001.csv"
    test_csv.write_text("Date,Open,High,Low,Close,Volume\n2024-01-10,10.0,10.3,9.9,10.2,1000000\n")

    # 创建测试候选JSON文件
    candidates_json = candidates_dir / "candidates_latest.json"
    candidates_json.write_text(json.dumps({"pick_date": "2024-01-15", "count": 5}))

    # 创建测试分析目录
    analysis_dir = review_dir / "2024-01-15"
    analysis_dir.mkdir(exist_ok=True)

    # 创建测试K线图文件
    kline_file = kline_dir / "000001.jpg"
    kline_file.write_text("fake_image_data")

    return tmp_path


# ============================================
# Token验证测试
# ============================================

@pytest.mark.service
def test_validate_token_success(tushare_service, mock_daily_df):
    """
    测试Token验证成功

    当Tushare API返回有效数据时，verify_token应返回成功。
    """
    with patch("tushare.pro_api") as mock_pro_api:
        mock_pro = MagicMock()
        mock_pro.daily.return_value = mock_daily_df
        mock_pro_api.return_value = mock_pro

        result, message = tushare_service.verify_token()

        assert result is True
        assert message == "Token 验证成功"
        mock_pro.daily.assert_called_once_with(ts_code="000001.SZ", limit=1)


@pytest.mark.service
def test_validate_token_failure(tushare_service):
    """
    测试Token验证失败

    当Tushare API返回空DataFrame时，verify_token应返回失败。
    """
    with patch("tushare.pro_api") as mock_pro_api:
        mock_pro = MagicMock()
        mock_pro.daily.return_value = pd.DataFrame()  # 空DataFrame
        mock_pro_api.return_value = mock_pro

        result, message = tushare_service.verify_token()

        assert result is False
        assert message == "Token 无效"


@pytest.mark.service
def test_validate_token_exception(tushare_service):
    """
    测试Token验证异常

    当Tushare API抛出异常时，verify_token应捕获异常并返回失败。
    """
    with patch("tushare.pro_api") as mock_pro_api:
        mock_pro = MagicMock()
        mock_pro.daily.side_effect = Exception("网络错误")
        mock_pro_api.return_value = mock_pro

        result, message = tushare_service.verify_token()

        assert result is False
        assert "验证失败" in message
        assert "网络错误" in message


# ============================================
# 股票列表测试
# ============================================

@pytest.mark.service
def test_get_stock_list(tushare_service, mock_stock_list_df):
    """
    测试获取股票列表

    应该成功调用Tushare API获取股票列表数据。
    """
    with patch("tushare.pro_api") as mock_pro_api:
        mock_pro = MagicMock()
        mock_pro.stock_basic.return_value = mock_stock_list_df
        mock_pro_api.return_value = mock_pro

        result = tushare_service.get_stock_list()

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert "000001.SZ" in result["ts_code"].values
        mock_pro.stock_basic.assert_called_once_with(
            exchange='',
            list_status='L',
            fields='ts_code,symbol,name,area,industry,market'
        )


@pytest.mark.service
def test_get_stock_list_cached(tushare_service, mock_stock_list_df):
    """
    测试获取股票列表（缓存）

    多次调用get_stock_list应该复用同一个pro实例。
    """
    with patch("tushare.pro_api") as mock_pro_api:
        mock_pro = MagicMock()
        mock_pro.stock_basic.return_value = mock_stock_list_df
        mock_pro_api.return_value = mock_pro

        # 第一次调用
        result1 = tushare_service.get_stock_list()
        # 第二次调用
        result2 = tushare_service.get_stock_list()

        assert result1.equals(result2)
        # pro_api应该只被调用一次（因为pro属性被缓存）
        mock_pro_api.assert_called_once()


@pytest.mark.service
def test_find_stock_by_code(tushare_service, mock_stock_list_df):
    """
    测试通过6位代码查找股票名称
    """
    with patch.object(tushare_service, "get_stock_list", return_value=mock_stock_list_df):
        result = tushare_service.find_stock_by_code("000001")

    assert result is not None
    assert result["code"] == "000001"
    assert result["name"] == mock_stock_list_df.iloc[0]["name"]


# ============================================
# K线数据测试
# ============================================

@pytest.mark.service
def test_get_kline_data(tushare_service, mock_daily_df):
    """
    测试获取K线数据

    应该成功调用Tushare API获取指定股票的日线数据。
    """
    with patch("tushare.pro_api") as mock_pro_api:
        mock_pro = MagicMock()
        mock_pro.daily.return_value = mock_daily_df
        mock_pro_api.return_value = mock_pro

        result = tushare_service.get_daily_data(
            ts_code="000001.SZ",
            start_date="20240101",
            end_date="20240131"
        )

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        assert result.iloc[0]["ts_code"] == "000001.SZ"
        mock_pro.daily.assert_called_once_with(
            ts_code="000001.SZ",
            start_date="20240101",
            end_date="20240131"
        )


# ============================================
# 数据状态检查测试
# ============================================

@pytest.mark.service
def test_check_local_data_status(tushare_service, temp_data_dir):
    """
    测试检查本地数据状态

    当本地存在数据文件时，check_data_status应正确返回各项状态。
    """
    # temp_data_dir已经包含了完整的数据目录结构
    with patch("app.services.tushare_service.ROOT", temp_data_dir.parent):
        with patch("app.config.settings") as mock_settings:
            mock_settings.data_dir = temp_data_dir

            status = tushare_service.check_data_status()

            assert status["raw_data"]["exists"] is True
            assert status["raw_data"]["count"] > 0
            assert status["candidates"]["exists"] is True
            assert status["analysis"]["exists"] is True
            assert status["kline"]["exists"] is True


@pytest.mark.service
def test_check_local_data_status_empty(tushare_service, tmp_path):
    """
    测试无本地数据时的状态检查

    当本地没有数据文件时，check_data_status应返回空状态。
    """
    # 创建空的目录结构
    empty_dir = tmp_path / "empty_data"
    empty_dir.mkdir(parents=True, exist_ok=True)

    with patch("app.services.tushare_service.ROOT", empty_dir):
        with patch("app.config.settings") as mock_settings:
            mock_settings.data_dir = empty_dir

            status = tushare_service.check_data_status()

            assert status["raw_data"]["exists"] is False
            assert status["raw_data"]["count"] == 0
            assert status["candidates"]["exists"] is False
            assert status["analysis"]["exists"] is False
            assert status["kline"]["exists"] is False


# ============================================
# 股票信息测试
# ============================================

@pytest.mark.service
def test_get_stock_info(tushare_service, mock_stock_csv_df, tmp_path):
    """
    测试获取股票信息

    从本地CSV文件成功加载股票数据。
    """
    # 创建测试CSV文件
    csv_path = tmp_path / "000001.csv"
    mock_stock_csv_df.to_csv(csv_path, index=False)

    with patch.object(tushare_service, "get_raw_data_path", return_value=csv_path):
        result = tushare_service.load_stock_data("000001")

        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 3
        assert "date" in result.columns  # 列名应转为小写
        assert result["date"].dtype.name.startswith("datetime")


@pytest.mark.service
def test_get_stock_info_not_found(tushare_service, tmp_path):
    """
    测试获取不存在的股票

    当本地CSV文件不存在时，load_stock_data应返回None。
    """
    non_existent_path = tmp_path / "999999.csv"

    with patch.object(tushare_service, "get_raw_data_path", return_value=non_existent_path):
        result = tushare_service.load_stock_data("999999")

        assert result is None


# ============================================
# 边界条件测试
# ============================================

@pytest.mark.service
def test_tushare_service_no_token():
    """
    测试无Token时初始化服务

    当没有提供Token且环境变量也没有Token时，服务应使用空字符串初始化。
    """
    with patch.dict("os.environ", {}, clear=True):
        service = TushareService()
        assert service.token == ""


@pytest.mark.service
def test_pro_property_no_token():
    """
    测试访问pro属性时Token未设置

    当Token未设置时，访问pro属性应抛出ValueError。
    """
    # 确保环境变量被清除
    original_token = os.environ.get("TUSHARE_TOKEN")
    os.environ.pop("TUSHARE_TOKEN", None)

    try:
        service = TushareService(token="")

        with pytest.raises(ValueError, match="Tushare Token 未设置"):
            _ = service.pro
    finally:
        # 恢复原始环境变量
        if original_token is not None:
            os.environ["TUSHARE_TOKEN"] = original_token


@pytest.mark.service
def test_get_raw_data_path(tushare_service, tmp_path):
    """
    测试获取原始数据文件路径

    get_raw_data_path应返回正确的文件路径。
    """
    with patch("app.config.settings") as mock_settings:
        mock_settings.raw_data_dir = tmp_path / "raw"

        path = tushare_service.get_raw_data_path("000001")

        assert isinstance(path, Path)
        assert path.name == "000001.csv"


@pytest.mark.service
def test_load_stock_data_columns_lowercased(tushare_service, tmp_path):
    """
    测试加载股票数据时列名转为小写

    从CSV文件加载数据后，所有列名应转为小写。
    """
    # 创建包含大写列名的CSV
    df = pd.DataFrame({
        "DATE": ["2024-01-10"],
        "OPEN": [10.0],
        "HIGH": [10.5],
        "LOW": [9.8],
        "CLOSE": [10.3],
    })
    csv_path = tmp_path / "test.csv"
    df.to_csv(csv_path, index=False)

    with patch.object(tushare_service, "get_raw_data_path", return_value=csv_path):
        result = tushare_service.load_stock_data("test")

        assert result is not None
        # 所有列名应该是小写
        for col in result.columns:
            assert col.islower()
        assert "date" in result.columns
