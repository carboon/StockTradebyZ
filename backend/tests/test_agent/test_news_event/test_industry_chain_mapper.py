"""Tests for IndustryChainMapper."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.agents.news_event.industry_chain_mapper import IndustryChainMapper


class TestIndustryChainMapper:
    def setup_method(self):
        self.mapper = IndustryChainMapper()

    def test_map_known_entity(self):
        chains = self.mapper.map_entities(["英伟达"])
        assert len(chains) > 0
        sectors = [c.sector for c in chains]
        assert "AI算力" in sectors

    def test_map_semiconductor(self):
        chains = self.mapper.map_entities(["半导体"])
        assert len(chains) > 0
        sectors = [c.sector for c in chains]
        assert any("芯片" in s or "半导体" in s for s in sectors)

    def test_map_tesla(self):
        chains = self.mapper.map_entities(["特斯拉"])
        assert len(chains) > 0
        sectors = [c.sector for c in chains]
        assert "新能源汽车" in sectors

    def test_get_stocks_for_sectors(self):
        stocks = self.mapper.get_stocks_for_sectors(["AI算力"])
        assert len(stocks) > 0
        codes = [s["code"] for s in stocks]
        assert "300308.SZ" in codes

    def test_map_unknown_entity(self):
        chains = self.mapper.map_entities(["不存在的公司"])
        assert len(chains) == 0
