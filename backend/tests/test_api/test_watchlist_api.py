"""
Watchlist API Tests
~~~~~~~~~~~~~~~~~~~
观察列表API测试用例

测试观察列表相关的所有API端点，包括：
- 获取观察列表
- 添加到观察列表
- 更新观察项
- 删除观察项
- 获取观察股票分析历史
- 获取观察股票K线图数据
- 边界条件和错误处理

注意：
- 使用 test_client_with_db fixture 进行需要数据库访问的API测试
- 使用 sample_stock_data fixture 创建测试用的股票数据
- Mock analysis_service 的方法避免外部依赖
"""
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.models import Stock, Watchlist, WatchlistAnalysis


# ========================================================================
# Helper Functions
# ========================================================================

def create_watchlist_item(
    db,
    code: str,
    reason: str = None,
    entry_price: float = None,
    position_ratio: float = None,
    priority: int = 0,
    is_active: bool = True
) -> Watchlist:
    """
    创建观察列表项的辅助函数

    Args:
        db: 数据库会话
        code: 股票代码
        reason: 添加原因
        priority: 优先级
        is_active: 是否活跃

    Returns:
        创建的Watchlist对象
    """
    item = Watchlist(
        code=code,
        add_reason=reason,
        entry_price=entry_price,
        position_ratio=position_ratio,
        priority=priority,
        is_active=is_active
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


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

    dates = [datetime.now() - pd.Timedelta(days=i) for i in range(days, 0, -1)]

    data = []
    close_price = base_price

    for dt in dates:
        open_price = close_price * (1 + random.uniform(-0.02, 0.02))
        high_price = max(open_price, close_price) * (1 + random.uniform(0, 0.03))
        low_price = min(open_price, close_price) * (1 - random.uniform(0, 0.03))
        close_price = close_price * (1 + random.uniform(-0.03, 0.03))
        volume = random.uniform(1000000, 50000000)

        data.append({
            "date": dt,
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
# 获取观察列表API测试 (GET /api/v1/watchlist/)
# ========================================================================

@pytest.mark.api
def test_get_watchlist_empty(test_client_with_db) -> None:
    """
    测试获取观察列表 - 空列表

    验证当数据库中没有观察项时，
    API能正确返回空的观察列表。
    """
    response = test_client_with_db.get("/api/v1/watchlist/")

    assert response.status_code == 200
    data = response.json()

    assert "items" in data
    assert "total" in data
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.api
def test_get_watchlist(test_client_with_db, sample_stock_data) -> None:
    """
    测试获取观察列表 - 有数据

    验证当数据库中存在观察项时，
    API能正确返回完整的观察列表，
    包括股票名称等信息。
    """
    # 先创建股票数据
    for stock_info in sample_stock_data[:3]:
        stock = Stock(**stock_info)
        test_client_with_db.db.add(stock)
    test_client_with_db.db.commit()

    # 创建观察项
    create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        reason="技术面强势",
        priority=1
    )
    create_watchlist_item(
        test_client_with_db.db,
        code="000001",
        reason="突破平台",
        priority=2
    )
    # 创建一个非活跃的观察项（不应该出现在列表中）
    create_watchlist_item(
        test_client_with_db.db,
        code="600036",
        reason="已取消",
        priority=0,
        is_active=False
    )

    response = test_client_with_db.get("/api/v1/watchlist/")

    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 2
    assert len(data["items"]) == 2

    # 验证第一个观察项
    item1 = next((i for i in data["items"] if i["code"] == "600000"), None)
    assert item1 is not None
    assert item1["name"] == "浦发银行"
    assert item1["add_reason"] == "技术面强势"
    assert item1["priority"] == 1
    assert item1["is_active"] is True
    assert "id" in item1
    assert "added_at" in item1

    # 验证第二个观察项
    item2 = next((i for i in data["items"] if i["code"] == "000001"), None)
    assert item2 is not None
    assert item2["name"] == "平安银行"
    assert item2["add_reason"] == "突破平台"


@pytest.mark.api
def test_get_watchlist_stock_name_null(test_client_with_db) -> None:
    """
    测试获取观察列表 - 股票名称为空

    验证当股票不存在于stocks表时，
    观察项的name字段为None。
    """
    # 创建观察项但不创建对应的股票记录
    create_watchlist_item(
        test_client_with_db.db,
        code="999999",
        reason="测试股票"
    )

    response = test_client_with_db.get("/api/v1/watchlist/")

    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 1
    assert data["items"][0]["code"] == "999999"
    assert data["items"][0]["name"] is None


# ========================================================================
# 添加到观察列表API测试 (POST /api/v1/watchlist/)
# ========================================================================

@pytest.mark.api
def test_add_to_watchlist_success(test_client_with_db, sample_stock_data) -> None:
    """
    测试添加到观察列表 - 成功

    验证能够成功添加新的观察项到列表中，
    并且返回完整的观察项信息。
    """
    # 创建股票数据
    stock = Stock(**sample_stock_data[0])
    test_client_with_db.db.add(stock)
    test_client_with_db.db.commit()

    request_data = {
        "code": "600000",
        "reason": "B1策略通过",
        "priority": 1
    }

    response = test_client_with_db.post("/api/v1/watchlist/", json=request_data)

    assert response.status_code == 200
    data = response.json()

    assert data["code"] == "600000"
    assert data["name"] == "浦发银行"
    assert data["add_reason"] == "B1策略通过"
    assert data["priority"] == 1
    assert data["is_active"] is True
    assert "id" in data
    assert "added_at" in data

    # 验证数据库中确实创建了记录
    test_client_with_db.db.rollback()
    watchlist_item = test_client_with_db.db.query(Watchlist).filter(
        Watchlist.code == "600000"
    ).first()
    assert watchlist_item is not None
    assert watchlist_item.add_reason == "B1策略通过"


@pytest.mark.api
def test_add_to_watchlist_duplicate(test_client_with_db, sample_stock_data) -> None:
    """
    测试添加到观察列表 - 重复项

    验证当添加已存在的股票代码时，
    API会更新现有记录而不是创建新记录。
    """
    # 创建股票和观察项
    stock = Stock(**sample_stock_data[0])
    test_client_with_db.db.add(stock)

    existing_item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        reason="原始原因",
        priority=1,
        is_active=False  # 设为非活跃
    )
    original_id = existing_item.id

    # 再次添加同一个代码
    request_data = {
        "code": "600000",
        "reason": "更新原因",
        "priority": 2
    }

    response = test_client_with_db.post("/api/v1/watchlist/", json=request_data)

    assert response.status_code == 200
    data = response.json()

    # 应该更新现有记录而不是创建新的
    assert data["id"] == original_id
    assert data["add_reason"] == "更新原因"
    assert data["priority"] == 2
    assert data["is_active"] is True  # 应该被重新激活

    # 验证数据库中只有一条记录
    test_client_with_db.db.rollback()
    count = test_client_with_db.db.query(Watchlist).filter(
        Watchlist.code == "600000"
    ).count()
    assert count == 1


@pytest.mark.api
def test_add_to_watchlist_invalid_code(test_client_with_db) -> None:
    """
    测试添加到观察列表 - 无效股票代码

    验证当添加不存在的股票代码时，
    API仍能成功创建观察项，但name字段为None。
    """
    request_data = {
        "code": "999999",
        "reason": "测试股票",
        "priority": 0
    }

    response = test_client_with_db.post("/api/v1/watchlist/", json=request_data)

    assert response.status_code == 200
    data = response.json()

    assert data["code"] == "999999"
    assert data["name"] is None
    assert data["add_reason"] == "测试股票"

    # 验证数据库中创建了记录
    test_client_with_db.db.rollback()
    watchlist_item = test_client_with_db.db.query(Watchlist).filter(
        Watchlist.code == "999999"
    ).first()
    assert watchlist_item is not None


@pytest.mark.api
def test_add_to_watchlist_code_padding(test_client_with_db, sample_stock_data) -> None:
    """
    测试添加到观察列表 - 代码自动补零

    验证当传入不足6位的股票代码时，
    API能自动补零并正确处理。
    """
    # 创建股票（使用6位代码）
    stock = Stock(code="000001", name="平安银行", market="SZ", industry="银行")
    test_client_with_db.db.add(stock)
    test_client_with_db.db.commit()

    # 使用不足6位的代码
    request_data = {
        "code": "1",
        "reason": "测试补零"
    }

    response = test_client_with_db.post("/api/v1/watchlist/", json=request_data)

    assert response.status_code == 200
    data = response.json()

    assert data["code"] == "000001"
    assert data["name"] == "平安银行"


@pytest.mark.api
def test_add_to_watchlist_default_values(test_client_with_db) -> None:
    """
    测试添加到观察列表 - 默认值

    验证当不提供可选参数时，
    API使用正确的默认值。
    """
    request_data = {
        "code": "600000"
    }

    response = test_client_with_db.post("/api/v1/watchlist/", json=request_data)

    assert response.status_code == 200
    data = response.json()

    assert data["code"] == "600000"
    assert data["add_reason"] is None
    assert data["priority"] == 0  # 默认优先级
    assert data["is_active"] is True  # 默认活跃


# ========================================================================
# 更新观察项API测试 (PUT /api/v1/watchlist/{item_id})
# ========================================================================

@pytest.mark.api
def test_update_watchlist_item_success(test_client_with_db) -> None:
    """
    测试更新观察项 - 成功

    验证能够成功更新观察项的各个字段。
    """
    # 创建观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        reason="原始原因",
        priority=1
    )

    request_data = {
        "reason": "更新后的原因",
        "entry_price": 12.3,
        "position_ratio": 0.4,
        "priority": 5,
        "is_active": False
    }

    response = test_client_with_db.put(
        f"/api/v1/watchlist/{item.id}",
        json=request_data
    )

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == item.id
    assert data["code"] == "600000"
    assert data["add_reason"] == "更新后的原因"
    assert data["entry_price"] == 12.3
    assert data["position_ratio"] == 0.4
    assert data["priority"] == 5
    assert data["is_active"] is False

    # 验证数据库中的更新
    test_client_with_db.db.rollback()
    updated_item = test_client_with_db.db.query(Watchlist).filter(
        Watchlist.id == item.id
    ).first()
    assert updated_item.add_reason == "更新后的原因"
    assert updated_item.entry_price == 12.3
    assert updated_item.position_ratio == 0.4
    assert updated_item.priority == 5
    assert updated_item.is_active is False


@pytest.mark.api
def test_update_watchlist_item_partial_update(test_client_with_db) -> None:
    """
    测试更新观察项 - 部分更新

    验证能够只更新部分字段而不影响其他字段。
    """
    # 创建观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        reason="原始原因",
        priority=1
    )

    # 只更新priority
    request_data = {
        "priority": 10
    }

    response = test_client_with_db.put(
        f"/api/v1/watchlist/{item.id}",
        json=request_data
    )

    assert response.status_code == 200
    data = response.json()

    assert data["priority"] == 10
    assert data["add_reason"] == "原始原因"  # 未更新
    assert data["is_active"] is True  # 未更新


@pytest.mark.api
def test_update_watchlist_item_allows_clearing_nullable_fields(test_client_with_db) -> None:
    """
    测试更新观察项时允许清空可空字段

    验证前端传入null时，买入成本、仓位和备注能够被真正清空。
    """
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        reason="原始原因",
        entry_price=12.6,
        position_ratio=0.35,
        priority=1,
    )

    request_data = {
        "reason": None,
        "entry_price": None,
        "position_ratio": None,
    }

    response = test_client_with_db.put(
        f"/api/v1/watchlist/{item.id}",
        json=request_data
    )

    assert response.status_code == 200
    data = response.json()
    assert data["add_reason"] is None
    assert data["entry_price"] is None
    assert data["position_ratio"] is None

    test_client_with_db.db.rollback()
    updated_item = test_client_with_db.db.query(Watchlist).filter(
        Watchlist.id == item.id
    ).first()
    assert updated_item.add_reason is None
    assert updated_item.entry_price is None
    assert updated_item.position_ratio is None


@pytest.mark.api
def test_update_watchlist_item_not_found(test_client_with_db) -> None:
    """
    测试更新观察项 - 不存在

    验证当更新的观察项不存在时，
    API返回404错误。
    """
    request_data = {
        "reason": "测试"
    }

    response = test_client_with_db.put(
        "/api/v1/watchlist/99999",
        json=request_data
    )

    assert response.status_code == 404
    data = response.json()

    assert "detail" in data
    assert "不存在" in data["detail"]


@pytest.mark.api
def test_update_watchlist_item_empty_body(test_client_with_db) -> None:
    """
    测试更新观察项 - 空请求体

    验证当请求体为空时，
    观察项保持不变。
    """
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        reason="原始原因",
        priority=1
    )

    request_data = {}

    response = test_client_with_db.put(
        f"/api/v1/watchlist/{item.id}",
        json=request_data
    )

    assert response.status_code == 200
    data = response.json()

    # 所有字段应保持不变
    assert data["add_reason"] == "原始原因"
    assert data["priority"] == 1
    assert data["is_active"] is True


# ========================================================================
# 删除观察项API测试 (DELETE /api/v1/watchlist/{item_id})
# ========================================================================

@pytest.mark.api
def test_delete_watchlist_item_success(test_client_with_db) -> None:
    """
    测试删除观察项 - 成功

    验证能够成功软删除观察项（is_active设为False）。
    """
    # 创建观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        reason="待删除"
    )

    response = test_client_with_db.delete(f"/api/v1/watchlist/{item.id}")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert data["message"] == "已删除"

    # 验证数据库中的软删除
    test_client_with_db.db.rollback()
    deleted_item = test_client_with_db.db.query(Watchlist).filter(
        Watchlist.id == item.id
    ).first()
    assert deleted_item is not None  # 记录仍然存在
    assert deleted_item.is_active is False  # 但被标记为非活跃


@pytest.mark.api
def test_delete_watchlist_item_not_found(test_client_with_db) -> None:
    """
    测试删除观察项 - 不存在

    验证当删除不存在的观察项时，
    API返回404错误。
    """
    response = test_client_with_db.delete("/api/v1/watchlist/99999")

    assert response.status_code == 404
    data = response.json()

    assert "detail" in data
    assert "不存在" in data["detail"]


@pytest.mark.api
def test_delete_watchlist_item_already_deleted(test_client_with_db) -> None:
    """
    测试删除观察项 - 已删除

    验证删除已标记为非活跃的观察项时，
    API仍能正常处理。
    """
    # 创建非活跃的观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        is_active=False
    )

    response = test_client_with_db.delete(f"/api/v1/watchlist/{item.id}")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"


# ========================================================================
# 获取观察股票分析历史API测试 (GET /api/v1/watchlist/{item_id}/analysis)
# ========================================================================

@pytest.mark.api
def test_get_watchlist_analysis_empty(test_client_with_db) -> None:
    """
    测试获取观察股票分析历史 - 空记录

    验证当观察股票没有分析历史时，
    API返回空的分析列表。
    """
    # 创建观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        entry_price=9.7,
        position_ratio=0.25,
    )

    response = test_client_with_db.get(f"/api/v1/watchlist/{item.id}/analysis")

    assert response.status_code == 200
    data = response.json()

    assert data["code"] == "600000"
    assert "analyses" in data
    assert data["total"] == 0
    assert data["analyses"] == []


@pytest.mark.api
def test_get_watchlist_analysis(test_client_with_db) -> None:
    """
    测试获取观察股票分析历史 - 有数据

    验证API能正确返回观察股票的分析历史记录，
    且按日期倒序排列。
    """
    # 创建观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000"
    )

    # 创建分析历史记录
    analyses = [
        WatchlistAnalysis(
            watchlist_id=item.id,
            analysis_date=date(2024, 1, 15),
            close_price=10.5,
            verdict="PASS",
            score=4.5,
            trend_outlook="bullish",
            buy_action="buy",
            hold_action="add_on_pullback",
            risk_level="low",
            buy_recommendation="可试仓，不追高。",
            hold_recommendation="可继续持有，强势突破再小幅加仓。",
            risk_recommendation="关注回踩支撑是否有效。",
            support_level=10.0,
            resistance_level=11.0,
            recommendation="建议买入",
            notes="技术面强势"
        ),
        WatchlistAnalysis(
            watchlist_id=item.id,
            analysis_date=date(2024, 1, 10),
            close_price=10.2,
            verdict="WATCH",
            score=3.5,
            trend_outlook="neutral",
            recommendation="观察等待"
        ),
        WatchlistAnalysis(
            watchlist_id=item.id,
            analysis_date=date(2024, 1, 5),
            close_price=9.8,
            verdict="FAIL",
            score=2.0,
            trend_outlook="bearish"
        ),
    ]
    for analysis in analyses:
        test_client_with_db.db.add(analysis)
    test_client_with_db.db.commit()

    response = test_client_with_db.get(f"/api/v1/watchlist/{item.id}/analysis")

    assert response.status_code == 200
    data = response.json()

    assert data["code"] == "600000"
    assert data["total"] == 3
    assert len(data["analyses"]) == 3

    # 验证按日期倒序排列（最新的在前）
    assert data["analyses"][0]["analysis_date"] == "2024-01-15"
    assert data["analyses"][1]["analysis_date"] == "2024-01-10"
    assert data["analyses"][2]["analysis_date"] == "2024-01-05"

    # 验证第一条记录的完整字段
    first_analysis = data["analyses"][0]
    assert first_analysis["watchlist_id"] == item.id
    assert first_analysis["close_price"] == 10.5
    assert first_analysis["verdict"] == "PASS"
    assert first_analysis["score"] == 4.5
    assert first_analysis["trend_outlook"] == "bullish"
    assert first_analysis["buy_action"] == "buy"
    assert first_analysis["hold_action"] == "add_on_pullback"
    assert first_analysis["risk_level"] == "low"
    assert first_analysis["buy_recommendation"] == "可试仓，不追高。"
    assert first_analysis["hold_recommendation"] == "可继续持有，强势突破再小幅加仓。"
    assert first_analysis["risk_recommendation"] == "关注回踩支撑是否有效。"
    assert first_analysis["support_level"] == 10.0
    assert first_analysis["resistance_level"] == 11.0
    assert first_analysis["recommendation"] == "建议买入"


@pytest.mark.api
def test_get_watchlist_analysis_limit(test_client_with_db) -> None:
    """
    测试获取观察股票分析历史 - 数量限制

    验证API只返回最近30条分析记录。
    """
    # 创建观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        entry_price=9.7,
        position_ratio=0.25,
    )

    # 创建35条分析记录（超过30条限制）
    for i in range(35):
        analysis = WatchlistAnalysis(
            watchlist_id=item.id,
            analysis_date=date(2024, 1, 1) + pd.Timedelta(days=i),
            close_price=10.0 + i * 0.1,
            verdict="PASS"
        )
        test_client_with_db.db.add(analysis)
    test_client_with_db.db.commit()

    response = test_client_with_db.get(f"/api/v1/watchlist/{item.id}/analysis")

    assert response.status_code == 200
    data = response.json()

    # 应该只返回30条
    assert data["total"] == 30
    assert len(data["analyses"]) == 30


@pytest.mark.api
def test_get_watchlist_analysis_item_not_found(test_client_with_db) -> None:
    """
    测试获取观察股票分析历史 - 观察项不存在

    验证当观察项不存在时，
    API返回404错误。
    """
    response = test_client_with_db.get("/api/v1/watchlist/99999/analysis")

    assert response.status_code == 404
    data = response.json()

    assert "detail" in data
    assert "不存在" in data["detail"]


@pytest.mark.api
def test_get_watchlist_analysis_other_watchlist_items(test_client_with_db) -> None:
    """
    测试获取观察股票分析历史 - 隔离性

    验证每个观察项只返回自己的分析记录，
    不会混入其他观察项的分析记录。
    """
    # 创建两个观察项
    item1 = create_watchlist_item(
        test_client_with_db.db,
        code="600000"
    )
    item2 = create_watchlist_item(
        test_client_with_db.db,
        code="000001"
    )

    # 为第一个观察项添加分析记录
    analysis1 = WatchlistAnalysis(
        watchlist_id=item1.id,
        analysis_date=date(2024, 1, 15),
        verdict="PASS"
    )
    test_client_with_db.db.add(analysis1)

    # 为第二个观察项添加分析记录
    analysis2 = WatchlistAnalysis(
        watchlist_id=item2.id,
        analysis_date=date(2024, 1, 15),
        verdict="WATCH"
    )
    test_client_with_db.db.add(analysis2)
    test_client_with_db.db.commit()

    # 获取第一个观察项的分析
    response = test_client_with_db.get(f"/api/v1/watchlist/{item1.id}/analysis")

    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 1
    assert data["analyses"][0]["verdict"] == "PASS"


@pytest.mark.api
def test_analyze_watchlist_item_success(test_client_with_db) -> None:
    """
    测试立即分析重点观察股票
    """
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        entry_price=9.7,
        position_ratio=0.25,
    )

    mock_df = pd.DataFrame([
        {"date": "2024-01-10", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000000},
        {"date": "2024-01-11", "open": 10.2, "high": 10.8, "low": 10.0, "close": 10.6, "volume": 1200000},
    ])

    with patch("app.api.watchlist.analysis_service") as mock_service:
        mock_service.analyze_stock.return_value = {
            "close_price": 10.6,
            "verdict": "PASS",
            "score": 4.3,
            "signal_type": "trend_start",
            "comment": "结构良好",
        }
        mock_service.load_stock_data.return_value = mock_df

        response = test_client_with_db.post(f"/api/v1/watchlist/{item.id}/analyze")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["code"] == "600000"
    assert data["analysis"]["analysis_date"] == "2024-01-11"
    assert data["analysis"]["verdict"] == "PASS"
    assert data["analysis"]["trend_outlook"] == "bullish"
    assert data["analysis"]["buy_action"] == "buy"
    assert data["analysis"]["hold_action"] == "hold"
    assert data["analysis"]["risk_level"] == "medium"
    assert data["analysis"]["buy_recommendation"] == "可试仓，不追高。"
    assert data["analysis"]["hold_recommendation"] == "继续持有，不追高加仓。"
    assert data["analysis"]["risk_recommendation"] == "关注回踩支撑是否有效。"
    assert data["analysis"]["recommendation"] == "当前仓位 25%。 继续持有，不追高；回踩企稳再加。"


@pytest.mark.api
def test_analyze_watchlist_item_updates_same_trade_day_record(test_client_with_db) -> None:
    """
    测试同一交易日立即分析会更新已有记录，不重复新增
    """
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        entry_price=10.5,
        position_ratio=0.8,
    )
    trade_date = date(2024, 1, 10)
    existing = WatchlistAnalysis(
        watchlist_id=item.id,
        analysis_date=trade_date,
        verdict="WATCH",
        score=3.5,
    )
    test_client_with_db.db.add(existing)
    test_client_with_db.db.commit()

    mock_df = pd.DataFrame([
        {"date": "2024-01-10", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000000},
    ])

    with patch("app.api.watchlist.analysis_service") as mock_service:
        mock_service.analyze_stock.return_value = {
            "close_price": 10.2,
            "verdict": "FAIL",
            "score": 2.8,
            "signal_type": "distribution_risk",
            "comment": "转弱",
        }
        mock_service.load_stock_data.return_value = mock_df

        response = test_client_with_db.post(f"/api/v1/watchlist/{item.id}/analyze")

    assert response.status_code == 200
    data = response.json()
    assert data["analysis"]["analysis_date"] == "2024-01-10"
    count = test_client_with_db.db.query(WatchlistAnalysis).filter(
        WatchlistAnalysis.watchlist_id == item.id,
        WatchlistAnalysis.analysis_date == trade_date,
    ).count()
    assert count == 1

    refreshed = test_client_with_db.db.query(WatchlistAnalysis).filter(
        WatchlistAnalysis.watchlist_id == item.id,
        WatchlistAnalysis.analysis_date == trade_date,
    ).first()
    assert refreshed.verdict == "FAIL"
    assert refreshed.trend_outlook == "bearish"
    assert refreshed.buy_action == "avoid"
    assert refreshed.hold_action == "trim"
    assert refreshed.risk_level == "high"
    assert refreshed.buy_recommendation == "暂不买入。"
    assert refreshed.hold_recommendation == "谨慎持有，优先减仓观察。"
    assert refreshed.risk_recommendation == "跌破支撑执行止损。"


@pytest.mark.api
def test_analyze_watchlist_item_prefers_check_date(test_client_with_db) -> None:
    """
    测试立即分析优先使用分析结果中的交易日
    """
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000",
        entry_price=10.0,
        position_ratio=0.3,
    )

    mock_df = pd.DataFrame([
        {"date": "2024-01-10", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000000},
        {"date": "2024-01-11", "open": 10.2, "high": 10.8, "low": 10.0, "close": 10.6, "volume": 1200000},
    ])

    with patch("app.api.watchlist.analysis_service") as mock_service:
        mock_service.analyze_stock.return_value = {
            "close_price": 10.6,
            "verdict": "PASS",
            "score": 4.1,
            "signal_type": "trend_start",
            "comment": "结构良好",
            "check_date": "2024-01-09",
        }
        mock_service.load_stock_data.return_value = mock_df

        response = test_client_with_db.post(f"/api/v1/watchlist/{item.id}/analyze")

    assert response.status_code == 200
    data = response.json()
    assert data["analysis"]["analysis_date"] == "2024-01-09"

    saved = test_client_with_db.db.query(WatchlistAnalysis).filter(
        WatchlistAnalysis.watchlist_id == item.id,
        WatchlistAnalysis.analysis_date == date(2024, 1, 9),
    ).first()
    assert saved is not None


@pytest.mark.api
def test_analyze_watchlist_item_not_found(test_client_with_db) -> None:
    """
    测试立即分析时观察项不存在
    """
    response = test_client_with_db.post("/api/v1/watchlist/99999/analyze")

    assert response.status_code == 404
    data = response.json()
    assert "不存在" in data["detail"]


# ========================================================================
# 获取观察股票K线图API测试 (GET /api/v1/watchlist/{item_id}/chart)
# ========================================================================

@pytest.mark.api
def test_get_watchlist_chart(test_client_with_db) -> None:
    """
    测试获取观察股票K线图 - 成功

    验证API能正确返回观察股票的K线数据。
    """
    # 创建观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000"
    )

    # Mock K线数据
    mock_kline_data = generate_kline_data(days=100)

    with patch("app.api.stock.get_kline_data", new_callable=AsyncMock) as mock_get_kline:
        mock_get_kline.return_value = {
            "code": "600000",
            "name": "浦发银行",
            "daily": [
                {
                    "date": "2024-01-15",
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.8,
                    "close": 10.2,
                    "volume": 1000000,
                    "ma5": 10.1,
                    "ma10": 10.0,
                    "ma20": 9.9,
                    "ma60": 9.8
                }
            ],
            "weekly": None
        }

        response = test_client_with_db.get(f"/api/v1/watchlist/{item.id}/chart")

        assert response.status_code == 200
        data = response.json()

        assert data["code"] == "600000"
        assert "kline" in data
        assert data["kline"]["code"] == "600000"
        assert len(data["kline"]["daily"]) > 0
        assert data["latest_analysis"] is None


@pytest.mark.api
def test_get_watchlist_chart_with_weekly(test_client_with_db) -> None:
    """
    测试获取观察股票K线图 - 包含周线

    验证API能正确返回包含周线数据的K线数据。
    """
    # 创建观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000"
    )

    weekly_data = [
        {
            "date": "2024-01-15",
            "open": 10.0,
            "high": 10.8,
            "low": 9.5,
            "close": 10.5,
            "volume": 5000000,
            "ma5": 10.2,
            "ma10": 10.0
        }
    ]

    with patch("app.api.stock.get_kline_data", new_callable=AsyncMock) as mock_get_kline:
        mock_get_kline.return_value = {
            "code": "600000",
            "daily": [],
            "weekly": weekly_data
        }

        response = test_client_with_db.get(f"/api/v1/watchlist/{item.id}/chart")

        assert response.status_code == 200
        data = response.json()

        assert data["kline"]["weekly"] is not None
        assert len(data["kline"]["weekly"]) == 1


@pytest.mark.api
def test_get_watchlist_chart_item_not_found(test_client_with_db) -> None:
    """
    测试获取观察股票K线图 - 观察项不存在

    验证当观察项不存在时，
    API返回404错误。
    """
    response = test_client_with_db.get("/api/v1/watchlist/99999/chart")

    assert response.status_code == 404
    data = response.json()

    assert "detail" in data
    assert "不存在" in data["detail"]


@pytest.mark.api
def test_get_watchlist_chart_calls_stock_api(test_client_with_db) -> None:
    """
    测试获取观察股票K线图 - 调用股票API

    验证API正确调用了股票API的get_kline_data函数，
    并传递了正确的参数。
    """
    # 创建观察项
    item = create_watchlist_item(
        test_client_with_db.db,
        code="000001"  # 不足6位的代码
    )

    with patch("app.api.stock.get_kline_data", new_callable=AsyncMock) as mock_get_kline:
        mock_get_kline.return_value = {
            "code": "000001",
            "daily": [],
            "weekly": None
        }

        response = test_client_with_db.get(f"/api/v1/watchlist/{item.id}/chart")

        assert response.status_code == 200

        # 验证get_kline_data被调用且参数正确
        mock_get_kline.assert_called_once()
        call_args = mock_get_kline.call_args

        # 第一个参数是KLineDataRequest
        request = call_args[0][0]
        assert request.code == "000001"
        assert request.days == 120
        assert request.include_weekly is True


@pytest.mark.api
def test_get_watchlist_chart_default_params(test_client_with_db) -> None:
    """
    测试获取观察股票K线图 - 默认参数

    验证API使用默认参数调用get_kline_data：
    - days=120
    - include_weekly=True
    """
    item = create_watchlist_item(
        test_client_with_db.db,
        code="600000"
    )

    with patch("app.api.stock.get_kline_data", new_callable=AsyncMock) as mock_get_kline:
        mock_get_kline.return_value = {
            "code": "600000",
            "daily": [],
            "weekly": None
        }

        response = test_client_with_db.get(f"/api/v1/watchlist/{item.id}/chart")

        assert response.status_code == 200

        # 获取调用参数
        call_args = mock_get_kline.call_args
        request = call_args[0][0]

        assert request.days == 120
        assert request.include_weekly is True
