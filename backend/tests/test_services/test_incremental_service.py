"""
测试区间增量更新服务

测试场景：
1. 模拟数据库落后 3 天的场景
2. 验证系统能识别缺口区间
3. 验证区间行情增量补齐
4. 验证明日之星结果补齐
5. 验证 Top5 诊断与历史补齐
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

# 添加项目根目录到路径
ROOT = Path(__file__).parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.incremental_service import (
    IncrementalFillService,
    FillStatus,
    GapInfo,
    get_incremental_fill_service,
)


class TestGapInfo:
    """测试缺口信息模型"""

    def test_no_gap(self):
        """测试无缺口情况"""
        gap = GapInfo(
            latest_local_date="2026-05-03",
            latest_trade_date="2026-05-03",
            missing_dates=[],
        )
        assert not gap.has_gap
        assert gap.gap_days == 0
        assert gap.gap_start is None
        assert gap.gap_end is None

    def test_with_gap(self):
        """测试有缺口情况"""
        gap = GapInfo(
            latest_local_date="2026-04-28",
            latest_trade_date="2026-05-03",
            missing_dates=["2026-04-29", "2026-04-30", "2026-05-03"],
        )
        assert gap.has_gap
        assert gap.gap_days == 3
        assert gap.gap_start == "2026-04-29"
        assert gap.gap_end == "2026-05-03"


class TestFillStatus:
    """测试补齐状态模型"""

    def test_in_progress(self):
        """测试进行中状态"""
        status = FillStatus(
            stage="kline_fill",
            status="in_progress",
            total=10,
            completed=5,
            failed=1,
            message="处理中",
        )
        assert status.progress_pct == 50

    def test_completed(self):
        """测试完成状态"""
        status = FillStatus(
            stage="kline_fill",
            status="completed",
            total=10,
            completed=10,
            failed=0,
            message="完成",
        )
        assert status.progress_pct == 100

    def test_to_dict(self):
        """测试转换为字典"""
        status = FillStatus(
            stage="kline_fill",
            status="in_progress",
            total=10,
            completed=5,
            failed=1,
            message="处理中",
            details={"current": "2026-05-03"},
        )
        d = status.to_dict()
        assert d["stage"] == "kline_fill"
        assert d["progress_pct"] == 50
        assert d["details"]["current"] == "2026-05-03"


class TestIncrementalFillService:
    """测试区间增量更新服务"""

    @pytest.fixture
    def service(self):
        """创建服务实例"""
        return IncrementalFillService()

    @pytest.fixture
    def mock_db(self):
        """模拟数据库"""
        db = Mock()
        return db

    def test_get_gap_info_no_data(self, service):
        """测试无数据时的缺口识别"""
        # 注意：此测试会连接真实数据库，所以不是真正的无数据场景
        # 我们主要验证方法可以正常调用
        gap = service.get_gap_info()

        # 验证返回的是 GapInfo 对象
        assert isinstance(gap, GapInfo)
        # 验证缺失日期是列表
        assert isinstance(gap.missing_dates, list)

    def test_detect_gap_status(self, service):
        """测试缺口状态检测"""
        with patch.object(service, 'get_gap_info') as mock_gap:
            mock_gap.return_value = GapInfo(
                latest_local_date="2026-04-28",
                latest_trade_date="2026-05-03",
                missing_dates=["2026-04-29", "2026-04-30", "2026-05-03"],
            )

            status = service.detect_gap_status()

            assert status["has_gap"] is True
            assert status["gap_days"] == 3
            assert status["gap_start"] == "2026-04-29"
            assert status["gap_end"] == "2026-05-03"
            assert len(status["missing_dates"]) == 3

    def test_get_missing_trade_dates(self, service):
        """测试获取缺失交易日"""
        # 模拟交易日历
        mock_trade_cal_df = MagicMock()
        mock_trade_cal_df.__iter__ = Mock(return_value=iter([
            {"cal_date": "20260501", "is_open": 0},  # 非交易日
            {"cal_date": "20260502", "is_open": 1},  # 交易日
            {"cal_date": "20260503", "is_open": 1},  # 交易日
        ]))

        with patch('tushare.pro_api') as mock_pro:
            mock_ts = Mock()
            mock_ts.pro = Mock()
            mock_ts.pro.trade_cal.return_value = mock_trade_cal_df
            mock_pro.return_value = mock_ts

            dates = service._get_missing_trade_dates("2026-04-30", "2026-05-03")

            # 验证返回的是交易日列表
            assert isinstance(dates, list)

    def test_fill_kline_data_no_gap(self, service):
        """测试无缺口时的行情补齐"""
        with patch.object(service, 'get_gap_info') as mock_gap:
            mock_gap.return_value = GapInfo(
                latest_local_date="2026-05-03",
                latest_trade_date="2026-05-03",
                missing_dates=[],
            )

            result = service.fill_kline_data()

            assert result.status == "completed"
            assert result.total == 0
            assert "无需补齐" in result.message

    def test_fill_tomorrow_star_no_gap(self, service):
        """测试无缺口时的明日之星补齐"""
        with patch.object(service, '_get_existing_tomorrow_star_dates') as mock_dates:
            mock_dates.return_value = ["2026-05-03"]

            with patch.object(service, 'get_gap_info') as mock_gap:
                mock_gap.return_value = GapInfo(
                    latest_local_date="2026-05-03",
                    latest_trade_date="2026-05-03",
                    missing_dates=[],
                )

                result = service.fill_tomorrow_star_results()

                assert result.status == "completed"
                assert "已是最新" in result.message

    def test_fill_top5_diagnosis_no_gap(self, service):
        """测试无缺口时的 Top5 诊断补齐"""
        with patch.object(service, 'get_gap_info') as mock_gap:
            mock_gap.return_value = GapInfo(
                latest_local_date="2026-05-03",
                latest_trade_date="2026-05-03",
                missing_dates=[],
            )

            result = service.fill_top5_diagnosis_and_history()

            assert result.status == "completed"
            assert "已是最新" in result.message

    def test_get_fill_summary(self, service):
        """测试获取补齐总览"""
        with patch.object(service, 'detect_gap_status') as mock_gap:
            mock_gap.return_value = {
                "has_gap": False,
                "gap_days": 0,
                "latest_local_date": "2026-05-03",
                "latest_trade_date": "2026-05-03",
            }

            with patch.object(service, '_get_existing_tomorrow_star_dates') as mock_dates:
                mock_dates.return_value = ["2026-05-03"]

                with patch('pathlib.Path.exists', return_value=True):
                    with patch('pathlib.Path.glob', return_value=[]):
                        summary = service.get_fill_summary()

                        assert "gap" in summary
                        assert "tomorrow_star" in summary
                        assert "history" in summary
                        assert "can_fill" in summary
                        assert "recommended_action" in summary

    def test_get_recommended_action(self, service):
        """测试推荐操作"""
        # 无缺口
        action = service._get_recommended_action(
            {"has_gap": False, "gap_days": 0},
            "2026-05-03",
        )
        assert "无需补齐" in action or "已是最新" in action

        # 小缺口
        action = service._get_recommended_action(
            {"has_gap": True, "gap_days": 3},
            "2026-04-30",
        )
        assert "增量更新" in action

        # 大缺口
        action = service._get_recommended_action(
            {"has_gap": True, "gap_days": 60},
            "2026-03-01",
        )
        assert "全量初始化" in action


class TestIntegrationScenarios:
    """集成测试场景"""

    def test_scenario_3_day_gap(self):
        """测试场景：数据库落后 3 天"""
        service = IncrementalFillService()

        with patch.object(service, 'get_gap_info') as mock_gap:
            # 模拟落后 3 个交易日
            mock_gap.return_value = GapInfo(
                latest_local_date="2026-04-28",
                latest_trade_date="2026-05-03",
                missing_dates=["2026-04-29", "2026-04-30", "2026-05-03"],
            )

            # 1. 检测缺口
            gap_status = service.detect_gap_status()
            assert gap_status["has_gap"] is True
            assert gap_status["gap_days"] == 3

            # 2. 获取推荐操作
            with patch.object(service, '_get_existing_tomorrow_star_dates') as mock_dates:
                mock_dates.return_value = ["2026-04-28"]
                summary = service.get_fill_summary()
                assert summary["can_fill"] is True
                assert "增量更新" in summary["recommended_action"]


class TestServiceSingleton:
    """测试服务单例"""

    def test_get_service(self):
        """测试获取服务实例"""
        service1 = get_incremental_fill_service()
        service2 = get_incremental_fill_service()
        assert service1 is service2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
