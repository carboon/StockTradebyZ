"""Tests for EventClassifier."""
from __future__ import annotations

import pytest

from app.agents.news_event.event_classifier import EventClassifier
from app.agents.news_event.schemas import EventType, MarketScope


class TestEventClassifier:
    def setup_method(self):
        self.classifier = EventClassifier()

    def test_empty_text(self):
        result = self.classifier.classify("", "")
        assert result.analyzable is False
        assert result.event_type == EventType.NOT_ANALYZABLE

    def test_domestic_company(self):
        result = self.classifier.classify(
            "京东方A发布2025年一季度财报，净利润同比增长30%",
            "公司公告业绩预增",
            category="company",
            source="证券时报",
        )
        assert result.event_type == EventType.DOMESTIC_COMPANY
        assert result.market_scope == MarketScope.DOMESTIC
        assert result.analyzable is True

    def test_domestic_industry(self):
        result = self.classifier.classify(
            "工信部发布新能源汽车产业发展规划",
            "政策支持新能源汽车产业链自主可控",
            category="policy",
            source="新华社",
        )
        assert result.event_type == EventType.DOMESTIC_INDUSTRY
        assert result.market_scope == MarketScope.DOMESTIC
        assert result.analyzable is True

    def test_overseas_company(self):
        result = self.classifier.classify(
            "英伟达发布新一代AI芯片Blackwell，性能提升4倍",
            "英伟达CEO黄仁勋在GTC大会上发布最新Blackwell GPU",
            category="tech",
            source="华尔街见闻",
        )
        assert result.event_type == EventType.OVERSEAS_COMPANY
        assert result.market_scope == MarketScope.OVERSEAS
        assert result.mapping_required is True

    def test_geopolitical_broad_stopped(self):
        result = self.classifier.classify(
            "中美高层举行战略对话，就双边关系交换意见",
            "双方同意保持沟通渠道畅通",
            category="diplomacy",
            source="新华社",
        )
        assert result.event_type == EventType.GEOPOLITICAL_BROAD
        assert result.analyzable is False
        assert result.mapping_required is False

    def test_macro_policy(self):
        result = self.classifier.classify(
            "央行宣布下调存款准备金率0.5个百分点",
            "释放长期流动性约1万亿元",
        )
        assert result.event_type == EventType.MACRO_POLICY
        assert result.market_scope == MarketScope.DOMESTIC

    def test_not_analyzable(self):
        result = self.classifier.classify(
            "今天天气很好",
            "适合出门",
        )
        assert result.analyzable is False
