"""Tests for EntityResolver."""
from __future__ import annotations

import pytest

from app.agents.news_event.entity_resolver import EntityResolver
from app.agents.news_event.schemas import EntityType


class TestEntityResolver:
    def setup_method(self):
        self.resolver = EntityResolver()

    def test_resolve_overseas_company(self):
        entities = self.resolver.resolve(
            "英伟达发布新一代AI芯片",
            [],
            db=None,
        )
        names = [e.name for e in entities]
        assert "NVIDIA" in names
        for e in entities:
            if e.name == "NVIDIA":
                assert e.is_overseas is True
                assert e.matched_code == "NVDA"

    def test_resolve_multiple_overseas(self):
        entities = self.resolver.resolve(
            "苹果和特斯拉都发布了新产品",
            [],
            db=None,
        )
        names = [e.name for e in entities]
        assert "Apple" in names
        assert "Tesla" in names

    def test_resolve_no_match(self):
        entities = self.resolver.resolve(
            "今天的天气很晴朗",
            [],
            db=None,
        )
        assert len(entities) == 0

    def test_resolve_entity_type(self):
        entities = self.resolver.resolve(
            "微软发布财报",
            [],
            db=None,
        )
        for e in entities:
            assert e.entity_type == EntityType.COMPANY_ENTITY

    def test_resolve_port_shipping_industry(self):
        entities = self.resolver.resolve(
            "南京港新增美国休斯敦直航航线，带动港口航运和外贸物流",
            [],
            db=None,
        )
        industry_names = [
            e.name for e in entities
            if e.entity_type == EntityType.INDUSTRY_ENTITY
        ]
        assert "南京港" in industry_names
        assert "港口航运" in industry_names
