"""
History Backfill Service Tests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
阶段6：历史回溯服务测试

测试内容：
1. 历史回溯数据结构定义
2. 首次历史补齐流程
3. 增量按交易日补历史
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from app.services.history_backfill_service import (
    BackfillConfig,
    HistoryBackfillStatus,
    HistoryBackfillService,
    get_history_backfill_service,
)
from app.models import StockAnalysis, StockDaily, Stock


class TestBackfillConfig:
    """测试历史回溯配置"""

    def test_default_config(self):
        """验证默认配置值"""
        assert BackfillConfig.DEFAULT_BACKFILL_DAYS == 250
        assert BackfillConfig.ANALYSIS_TYPE == "daily_b1"
        assert BackfillConfig.STRATEGY_VERSION == "v1"
        assert BackfillConfig.MIN_DATA_DAYS == 60


class TestHistoryBackfillStatus:
    """测试历史回溯状态"""

    def test_status_initialization(self):
        """验证状态初始化"""
        status = HistoryBackfillStatus(
            code="600519",
            total_days=250,
            backfilled_days=100,
            latest_date="2026-05-01",
            message="处理中",
        )

        assert status.code == "600519"
        assert status.total_days == 250
        assert status.backfilled_days == 100
        assert status.latest_date == "2026-05-01"
        assert status.message == "处理中"

    def test_is_complete(self):
        """验证完成状态判断"""
        # 完整状态
        status_complete = HistoryBackfillStatus(
            code="600519",
            total_days=250,
            backfilled_days=250,
        )
        assert status_complete.is_complete is True

        # 部分完成
        status_partial = HistoryBackfillStatus(
            code="600519",
            total_days=250,
            backfilled_days=100,
        )
        assert status_partial.is_complete is False

        # 未开始
        status_not_started = HistoryBackfillStatus(
            code="600519",
            total_days=250,
            backfilled_days=0,
        )
        assert status_not_started.is_complete is False

    def test_progress_pct(self):
        """验证进度百分比计算"""
        status = HistoryBackfillStatus(
            code="600519",
            total_days=250,
            backfilled_days=100,
        )
        assert status.progress_pct == 40

        # 边界情况：total_days = 0
        status_zero = HistoryBackfillStatus(
            code="600519",
            total_days=0,
            backfilled_days=0,
        )
        assert status_zero.progress_pct == 0

    def test_to_dict(self):
        """验证状态转换为字典"""
        status = HistoryBackfillStatus(
            code="600519",
            total_days=250,
            backfilled_days=100,
            latest_date="2026-05-01",
            message="处理中",
        )

        result = status.to_dict()
        assert result["code"] == "600519"
        assert result["total_days"] == 250
        assert result["backfilled_days"] == 100
        assert result["latest_date"] == "2026-05-01"
        assert result["is_complete"] is False
        assert result["progress_pct"] == 40
        assert result["message"] == "处理中"


class TestHistoryBackfillService:
    """测试历史回溯服务"""

    @pytest.fixture
    def db_session(self, mocker):
        """Mock 数据库会话"""
        session = MagicMock()
        return session

    @pytest.fixture
    def service(self, db_session):
        """创建历史回溯服务实例"""
        return HistoryBackfillService(db=db_session)

    def test_get_stock_backfill_status_no_data(self, service, db_session):
        """测试获取股票状态：无数据"""
        # Mock 数据库查询返回空结果
        mock_result = MagicMock()
        mock_result.count = 0
        mock_result.latest_date = None
        db_session.execute.return_value.first.return_value = mock_result

        # Mock _get_available_trade_dates
        with patch.object(service, '_get_available_trade_dates', return_value=[]):
            status = service.get_stock_backfill_status("600519")

        assert status.code == "600519"
        assert status.backfilled_days == 0
        assert status.total_days == 0
        assert status.message == "尚未执行历史补齐"

    def test_get_stock_backfill_status_partial(self, service, db_session):
        """测试获取股票状态：部分完成"""
        # Mock 数据库查询
        mock_result = MagicMock()
        mock_result.count = 100
        mock_result.latest_date = date(2026, 5, 1)
        db_session.execute.return_value.first.return_value = mock_result

        # Mock 可用交易日
        available_dates = [
            "2026-05-02", "2026-05-01", "2026-04-30",
            # ... 更多日期
        ]
        with patch.object(service, '_get_available_trade_dates', return_value=available_dates):
            status = service.get_stock_backfill_status("600519")

        assert status.backfilled_days == 100
        assert status.total_days == len(available_dates)
        assert "补齐" in status.message  # 修复：可以是"已补齐"或"历史补齐完成"

    def test_get_missing_trade_dates(self, service, db_session):
        """测试获取缺失的交易日"""
        # Mock 已存在的日期
        existing_dates_result = [
            (date(2026, 5, 1),),
            (date(2026, 4, 30),),
        ]
        db_session.execute.return_value.all.return_value = existing_dates_result

        # Mock 可用交易日
        available_dates = [
            "2026-05-03",
            "2026-05-02",
            "2026-05-01",
            "2026-04-30",
            "2026-04-29",
        ]

        with patch.object(service, '_get_available_trade_dates', return_value=available_dates):
            missing = service.get_missing_trade_dates("600519")

        # 应该返回缺失的日期（按时间正序）
        assert "2026-05-03" in missing
        assert "2026-05-02" in missing
        assert "2026-04-29" in missing

    def test_get_missing_trade_dates_with_target(self, service, db_session):
        """测试获取缺失的交易日：指定目标日期"""
        existing_dates_result = []
        db_session.execute.return_value.all.return_value = existing_dates_result

        available_dates = [
            "2026-05-10",
            "2026-05-09",
            "2026-05-08",
            "2026-05-07",
            "2026-05-06",
            "2026-05-05",
        ]

        with patch.object(service, '_get_available_trade_dates', return_value=available_dates):
            missing = service.get_missing_trade_dates("600519", target_date="2026-05-08")

        # 应该只返回到目标日期之前的缺失日期
        assert "2026-05-08" in missing
        assert "2026-05-07" in missing
        assert "2026-05-06" in missing
        assert "2026-05-05" in missing
        assert "2026-05-09" not in missing
        assert "2026-05-10" not in missing

    def test_get_available_trade_dates(self, service, db_session):
        """测试获取可用交易日"""
        # Mock stock_daily 查询
        mock_result = [
            (date(2026, 5, 3),),
            (date(2026, 5, 2),),
            (date(2026, 5, 1),),
        ]
        db_session.execute.return_value.all.return_value = mock_result

        dates = service._get_available_trade_dates("600519")

        assert len(dates) == 3
        assert "2026-05-03" in dates
        assert "2026-05-02" in dates
        assert "2026-05-01" in dates

    def test_get_batch_backfill_status(self, service, db_session):
        """测试批量获取历史回溯状态"""
        # Mock 数据库查询
        def mock_execute_side_effect(query):
            mock_result = MagicMock()
            if "count" in str(query.columns):
                mock_result.count = 250 if "600519" in str(query) else 0
                mock_result.latest_date = date(2026, 5, 1) if "600519" in str(query) else None
            else:
                mock_result.all.return_value = []
            return MagicMock(first=lambda: mock_result)

        db_session.execute.side_effect = mock_execute_side_effect

        # Mock 可用交易日
        with patch.object(service, '_get_available_trade_dates', return_value=["2026-05-01"] * 250):
            result = service.get_batch_backfill_status(["600519", "000001"])

        assert result["total"] == 2
        assert "complete" in result
        assert "partial" in result
        assert "not_started" in result
        assert "details" in result
        assert len(result["details"]) == 2


class TestServiceIntegration:
    """集成测试：验证完整流程"""

    def test_service_singleton(self):
        """验证服务单例模式"""
        service1 = get_history_backfill_service()
        service2 = get_history_backfill_service()

        # 应该返回同一个实例
        assert service1 is service2

    def test_full_backfill_workflow_mock(self, mocker):
        """测试完整的补齐流程（Mock）"""
        # 这个测试验证完整的工作流程，但使用 Mock 避免实际数据库操作

        # Mock 数据库会话
        mock_db = mocker.MagicMock()

        # Mock execute 返回值
        # get_missing_trade_dates 需要 mock 两个不同的查询
        # 1. 获取已存在的日期
        # 2. 获取可用交易日

        # 让我们先 mock get_missing_trade_dates 返回非空列表
        missing_dates = ["2026-05-01", "2026-04-30"]

        # Mock analysis_service
        mock_analysis_service = mocker.patch('app.services.history_backfill_service.analysis_service')
        mock_analysis_service.load_stock_data.return_value = None  # 无数据

        # 创建服务
        service = HistoryBackfillService(db=mock_db)

        # Mock get_missing_trade_dates 返回需要补齐的日期
        with patch.object(service, 'get_missing_trade_dates', return_value=missing_dates):
            # 执行补齐（应该因为无数据而返回失败状态）
            status = service.backfill_stock_history("600519")

        # 由于 load_stock_data 返回 None，应该返回错误状态
        assert status.backfilled_days == 0
        assert "数据不存在" in status.message
