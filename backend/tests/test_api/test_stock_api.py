"""
Stock API Tests
~~~~~~~~~~~~~~~
股票数据API测试用例

测试股票数据相关的所有API端点，包括：
- 获取股票基本信息
- 获取K线数据（日K、周K）
- K线均线计算（MA5、MA10、MA20、MA60）
- 边界条件和错误处理

注意：
- 使用 test_client fixture 进行API测试
- Mock analysis_service 返回测试数据
- K线数据Mock 60-100行来验证均线计算
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.models import Stock


# ========================================================================
# Helper Functions
# ========================================================================

def generate_kline_data(days: int = 100, base_price: float = 10.0) -> pd.DataFrame:
    """
    生成模拟K线数据

    Args:
        days: 生成数据的天数
        base_price: 基础价格

    Returns:
        包含K线数据的DataFrame
    """
    import random

    dates = [datetime.now() - timedelta(days=i) for i in range(days, 0, -1)]

    data = []
    close_price = base_price

    for date in dates:
        # 模拟价格波动
        open_price = close_price * (1 + random.uniform(-0.02, 0.02))
        high_price = max(open_price, close_price) * (1 + random.uniform(0, 0.03))
        low_price = min(open_price, close_price) * (1 - random.uniform(0, 0.03))
        close_price = close_price * (1 + random.uniform(-0.03, 0.03))
        volume = random.uniform(1000000, 50000000)

        data.append({
            "date": date,
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "vol": round(volume, 2),
        })

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    return df


# ========================================================================
# Fixtures
# ========================================================================

@pytest.fixture(scope="function")
def sample_kline_data() -> pd.DataFrame:
    """
    示例K线数据 fixture

    生成80天的K线数据，用于测试均线计算。
    """
    return generate_kline_data(days=80, base_price=10.0)


@pytest.fixture(scope="function")
def minimal_kline_data() -> pd.DataFrame:
    """
    最小K线数据 fixture

    生成30天的K线数据，用于测试数据不足的情况。
    """
    return generate_kline_data(days=30, base_price=10.0)


# ========================================================================
# 股票信息API测试 (GET /api/v1/stock/{code})
# ========================================================================

@pytest.mark.api
def test_get_stock_info_success(test_client_with_db) -> None:
    """
    测试获取股票基本信息 - 成功场景

    验证当股票存在于数据库时，API能正确返回完整的股票信息，
    包括代码、名称、市场、行业等字段。
    """
    # 先在数据库中创建测试股票
    stock = Stock(
        code="600000",
        name="浦发银行",
        market="SH",
        industry="银行"
    )
    test_client_with_db.db.add(stock)
    test_client_with_db.db.commit()

    # 获取股票信息
    response = test_client_with_db.get("/api/v1/stock/600000")

    assert response.status_code == 200
    data = response.json()

    assert data["code"] == "600000"
    assert data["name"] == "浦发银行"
    assert data["market"] == "SH"
    assert data["industry"] == "银行"
    assert data["exists"] is True


@pytest.mark.api
def test_get_stock_info_not_found(test_client: TestClient) -> None:
    """
    测试获取不存在的股票

    验证当股票代码不存在于数据库时，
    API仍能正常返回，但exists字段为False。
    """
    # Mock CSV文件不存在
    with patch("app.api.stock.Path") as mock_path:
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path.return_value.__truediv__.return_value = mock_path_instance

        response = test_client.get("/api/v1/stock/999999")

        assert response.status_code == 200
        data = response.json()

        assert data["code"] == "999999"
        assert data["exists"] is False
        assert data["name"] is None
        assert data["market"] is None
        assert data["industry"] is None


@pytest.mark.api
def test_get_stock_info_invalid_code(test_client: TestClient) -> None:
    """
    测试无效股票代码处理

    验证当传入非数字或格式不正确的股票代码时，
    API能正确处理并返回适当的响应。
    """
    # 测试包含字母的代码（zfill处理后会保留字母）
    with patch("app.api.stock.Path") as mock_path:
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path.return_value.__truediv__.return_value = mock_path_instance

        response = test_client.get("/api/v1/stock/ABC123")

        # API应该能处理这种格式
        assert response.status_code == 200
        data = response.json()
        assert data["exists"] is False


@pytest.mark.api
def test_get_stock_info_code_padding(test_client_with_db) -> None:
    """
    测试股票代码自动补零

    验证当传入不足6位的股票代码时，
    API能自动补零并正确返回股票信息。
    """
    # 创建6位代码的股票
    stock = Stock(
        code="000001",
        name="平安银行",
        market="SZ",
        industry="银行"
    )
    test_client_with_db.db.add(stock)
    test_client_with_db.db.commit()

    # 使用不足6位的代码查询
    response = test_client_with_db.get("/api/v1/stock/1")

    assert response.status_code == 200
    data = response.json()

    assert data["code"] == "000001"
    assert data["name"] == "平安银行"
    assert data["exists"] is True


@pytest.mark.api
def test_get_stock_info_fallback_sync_from_tushare(test_client_with_db) -> None:
    """
    测试获取股票信息时从 Tushare 兜底同步名称
    """
    with patch("app.api.stock.TushareService") as mock_service_cls:
        mock_service = MagicMock()
        mock_service.sync_stock_to_db.return_value = Stock(
            code="600519",
            name="贵州茅台",
            market="SH",
            industry="酿酒",
        )
        mock_service_cls.return_value = mock_service

        response = test_client_with_db.get("/api/v1/stock/600519")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "600519"
        assert data["name"] == "贵州茅台"
        assert data["market"] == "SH"
        assert data["industry"] == "酿酒"


# ========================================================================
# 股票搜索API测试 (GET /api/v1/stock/search)
# ========================================================================

@pytest.mark.api
def test_search_stocks_by_name_from_db(test_client_with_db) -> None:
    """
    测试按名称模糊搜索股票 - 优先命中数据库
    """
    test_client_with_db.db.add_all([
        Stock(code="600000", name="浦发银行", market="SH", industry="银行"),
        Stock(code="600519", name="贵州茅台", market="SH", industry="酿酒"),
    ])
    test_client_with_db.db.commit()

    response = test_client_with_db.get("/api/v1/stock/search?q=浦发")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert data["items"][0]["code"] == "600000"
    assert data["items"][0]["name"] == "浦发银行"


@pytest.mark.api
def test_search_stocks_fallback_to_tushare(test_client: TestClient) -> None:
    """
    测试搜索股票时从 Tushare 列表兜底返回结果
    """
    lookup = pd.DataFrame([
        {
            "ts_code": "600519.SH",
            "symbol": "600519",
            "name": "贵州茅台",
            "industry": "酿酒",
            "market": "主板",
        }
    ])

    with patch("app.api.stock.TushareService.get_stock_list", return_value=lookup):
        response = test_client.get("/api/v1/stock/search?q=茅台&limit=1")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["code"] == "600519"
    assert data["items"][0]["name"] == "贵州茅台"
    assert data["items"][0]["market"] == "SH"


# ========================================================================
# K线数据API测试 (POST /api/v1/stock/kline)
# ========================================================================

@pytest.mark.api
def test_get_kline_daily(test_client: TestClient, sample_kline_data: pd.DataFrame) -> None:
    """
    测试获取日K线数据

    验证API能正确返回日K线数据，
    包含日期、开盘价、最高价、最低价、收盘价和成交量。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        mock_analysis.load_stock_data.return_value = sample_kline_data

        request_data = {
            "code": "600000",
            "days": 30,
            "include_weekly": False
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["code"] == "600000"
        assert "daily" in data
        assert len(data["daily"]) == 30

        # 验证第一条数据结构
        first_day = data["daily"][0]
        assert "date" in first_day
        assert "open" in first_day
        assert "high" in first_day
        assert "low" in first_day
        assert "close" in first_day
        assert "volume" in first_day
        assert isinstance(first_day["open"], float)
        assert isinstance(first_day["close"], float)


@pytest.mark.api
def test_get_kline_weekly(test_client: TestClient, sample_kline_data: pd.DataFrame) -> None:
    """
    测试获取周K线数据

    验证当include_weekly为True时，
    API能正确计算并返回周K线数据。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        mock_analysis.load_stock_data.return_value = sample_kline_data

        request_data = {
            "code": "600000",
            "days": 60,
            "include_weekly": True
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["code"] == "600000"
        assert "daily" in data
        assert "weekly" in data
        assert data["weekly"] is not None
        assert len(data["weekly"]) > 0

        # 验证周线数据结构
        first_week = data["weekly"][0]
        assert "date" in first_week
        assert "open" in first_week
        assert "high" in first_week
        assert "low" in first_week
        assert "close" in first_week
        assert "volume" in first_week


@pytest.mark.api
def test_get_kline_with_ma(test_client: TestClient, sample_kline_data: pd.DataFrame) -> None:
    """
    测试获取带均线的K线数据

    验证K线数据中包含MA5、MA10、MA20、MA60均线，
    并且均线值在数据充足时正确计算。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        mock_analysis.load_stock_data.return_value = sample_kline_data

        request_data = {
            "code": "600000",
            "days": 70,
            "include_weekly": False
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 200
        data = response.json()

        daily = data["daily"]
        assert len(daily) == 70

        # 验证均线字段存在
        first_day = daily[0]
        assert "ma5" in first_day
        assert "ma10" in first_day
        assert "ma20" in first_day
        assert "ma60" in first_day

        # 前几天的均线可能为None（数据不足）
        # 但随着数据充足，均线应该有值
        ma_values_found = False
        for day in daily:
            if day["ma5"] is not None:
                ma_values_found = True
                assert isinstance(day["ma5"], float)
                break
        assert ma_values_found, "应该有至少一条数据包含MA5值"

        # 验证最后一条数据（数据充足）应该有所有均线值
        last_day = daily[-1]
        # MA5应该有值（需要5天数据）
        assert last_day["ma5"] is not None
        # MA60可能为None（如果总数据不足60天均线计算周期）
        # 但由于我们返回70天数据，且原始数据有80天，MA60应该有值
        assert last_day["ma60"] is not None


@pytest.mark.api
def test_get_kline_date_range(test_client: TestClient, sample_kline_data: pd.DataFrame) -> None:
    """
    测试指定天数获取K线数据

    验证days参数能正确控制返回的数据条数。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        mock_analysis.load_stock_data.return_value = sample_kline_data

        # 测试获取最近10天
        request_data = {
            "code": "600000",
            "days": 10,
            "include_weekly": False
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert len(data["daily"]) == 10

        # 测试获取默认天数（120天）
        request_data = {
            "code": "600000",
            "include_weekly": False
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 200
        data = response.json()

        # 原始数据只有80天，所以最多返回80天
        assert len(data["daily"]) == 80


@pytest.mark.api
def test_get_kline_empty_data(test_client: TestClient) -> None:
    """
    测试空数据情况

    验证当股票数据不存在时，
    API返回404错误和适当的错误信息。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        # Mock返回空DataFrame
        mock_analysis.load_stock_data.return_value = pd.DataFrame()

        request_data = {
            "code": "999999",
            "days": 30,
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 404
        data = response.json()

        assert "detail" in data
        assert "999999" in data["detail"]


@pytest.mark.api
def test_get_kline_no_data_file(test_client: TestClient) -> None:
    """
    测试数据文件不存在情况

    验证当load_stock_data返回None时，
    API返回404错误。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        mock_analysis.load_stock_data.return_value = None

        request_data = {
            "code": "888888",
            "days": 30,
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 404


@pytest.mark.api
def test_get_kline_invalid_params(test_client: TestClient) -> None:
    """
    测试无效参数处理

    验证当传入无效参数时，
    API能正确处理并返回适当的错误信息。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        mock_analysis.load_stock_data.return_value = generate_kline_data(days=50)

        # 测试负数days
        request_data = {
            "code": "600000",
            "days": -10,
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        # 负数days应该返回数据但不截取（tail(-10)返回所有数据）
        # 或者根据实现返回所有数据
        assert response.status_code == 200

        # 测试缺少必需字段
        response = test_client.post(
            "/api/v1/stock/kline",
            json={"include_weekly": True}  # 缺少code
        )

        # 应该返回422验证错误
        assert response.status_code == 422


@pytest.mark.api
def test_get_kline_service_error(test_client_with_db) -> None:
    """
    测试服务异常处理

    验证当analysis_service抛出异常时，
    API能正确处理并返回适当的错误信息。
    使用test_client_with_db以避免TestClient的startup事件问题。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        # Mock服务抛出异常
        mock_analysis.load_stock_data.side_effect = ValueError("数据加载失败")

        request_data = {
            "code": "600000",
            "days": 30,
        }

        response = test_client_with_db.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 500
        assert "数据加载失败" in response.json()["detail"]


@pytest.mark.api
def test_get_kline_ma_null_handling(test_client: TestClient, minimal_kline_data: pd.DataFrame) -> None:
    """
    测试均线空值处理

    验证当数据不足以计算某条均线时，
    该均线字段应为None而不是错误值。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        mock_analysis.load_stock_data.return_value = minimal_kline_data

        request_data = {
            "code": "600000",
            "days": 30,
            "include_weekly": False
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 200
        data = response.json()

        daily = data["daily"]

        # 前几天的MA20应该为None（数据不足20天）
        early_day = daily[0]
        assert early_day["ma20"] is None
        assert early_day["ma60"] is None

        # MA5在5天后应该有值
        fifth_day = daily[4]
        assert fifth_day["ma5"] is not None


@pytest.mark.api
def test_get_kline_weekly_ma_calculation(test_client: TestClient, sample_kline_data: pd.DataFrame) -> None:
    """
    测试周K线均线计算

    验证周K线数据中MA5和MA10均线能正确计算。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        mock_analysis.load_stock_data.return_value = sample_kline_data

        request_data = {
            "code": "600000",
            "days": 80,
            "include_weekly": True
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["weekly"] is not None
        weekly = data["weekly"]

        # 验证周线均线字段
        if len(weekly) > 0:
            first_week = weekly[0]
            assert "ma5" in first_week
            assert "ma10" in first_week

            # 周线数据的前几周MA可能为None
            # 检查是否有周线数据包含MA值
            ma_found = any(w["ma5"] is not None for w in weekly)
            # 由于有80天数据，应该有足够周数据计算MA5
            assert ma_found


@pytest.mark.api
def test_get_kline_code_padding(test_client: TestClient, sample_kline_data: pd.DataFrame) -> None:
    """
    测试K线API代码自动补零

    验证当传入不足6位的股票代码时，
    API能自动补零并正确加载数据。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        # 验证load_stock_data被调用时使用了补零后的代码
        mock_analysis.load_stock_data.return_value = sample_kline_data

        request_data = {
            "code": "1",  # 传入不足6位的代码
            "days": 30,
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 200
        data = response.json()

        assert data["code"] == "000001"
        # 验证服务被正确调用
        mock_analysis.load_stock_data.assert_called_once_with("000001")


@pytest.mark.api
def test_get_kline_zero_days(test_client: TestClient, sample_kline_data: pd.DataFrame) -> None:
    """
    测试days=0时的行为

    验证当days=0时，API返回所有可用数据。
    """
    with patch("app.api.stock.analysis_service") as mock_analysis:
        mock_analysis.load_stock_data.return_value = sample_kline_data

        request_data = {
            "code": "600000",
            "days": 0,  # 0表示不限制
            "include_weekly": False
        }

        response = test_client.post("/api/v1/stock/kline", json=request_data)

        assert response.status_code == 200
        data = response.json()

        # days=0时应该返回所有数据（80条）
        assert len(data["daily"]) == 80
