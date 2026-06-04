"""Tests for MarketRealizationAnalyzer."""
from __future__ import annotations

import pytest

from app.agents.news_event.market_realization_analyzer import MarketRealizationAnalyzer
from app.agents.news_event.schemas import RealizationStatus


class TestMarketRealizationAnalyzer:
    def setup_method(self):
        self.analyzer = MarketRealizationAnalyzer()

    def test_no_stock_codes(self):
        results = self.analyzer.analyze([], None, None)
        assert len(results) == 0

    def test_no_db(self):
        results = self.analyzer.analyze(["000725.SZ"], None, None)
        assert len(results) == 0

    def test_limit_up_detection(self):
        class MockDaily:
            def __init__(self, close, pre_close, vol):
                self.close = close
                self.pre_close = pre_close
                self.vol = vol

        dailies = [
            MockDaily(11.0, 10.0, 100),   # today: +10% = limit up
            MockDaily(10.0, 10.5, 90),    # -4.8%
            MockDaily(10.5, 10.3, 88),    # +1.9%
            MockDaily(10.3, 10.1, 85),    # +2.0%
            MockDaily(10.1, 10.0, 82),    # +1.0%
            MockDaily(10.0, 9.9, 80),     # +1.0%
        ]
        result = MarketRealizationAnalyzer._compute_realization(
            "000725.SZ", "京东方A", dailies, None,
        )
        assert result.limit_up is True
        assert result.moved_before_news is True

    def test_likely_priced_in(self):
        class MockDaily:
            def __init__(self, close, vol):
                self.close = close
                self.pre_close = close * 0.98
                self.vol = vol

        dailies = [
            MockDaily(12.0, 100),  # current
            MockDaily(11.5, 90),
            MockDaily(10.8, 88),
            MockDaily(10.2, 85),
            MockDaily(10.0, 82),
            MockDaily(9.5, 80),    # 5 days ago: 9.5 -> 12.0 = +26.3%
        ]
        result = MarketRealizationAnalyzer._compute_realization(
            "000725.SZ", "京东方A", dailies, None,
        )
        assert result.realization_status in (
            RealizationStatus.LIKELY_PRICED_IN,
            RealizationStatus.PARTIALLY_REALIZED,
        )
