"""Tests for SearchOrchestrator."""
from __future__ import annotations

import pytest

from app.agents.news_event.search_orchestrator import SearchOrchestrator
from app.agents.news_event.schemas import SearchResult


class TestSearchOrchestrator:
    def setup_method(self):
        self.orchestrator = SearchOrchestrator()

    def test_generate_initial_queries(self):
        queries = self.orchestrator.generate_initial_queries(
            title="英伟达发布新一代AI芯片",
            core_entity="英伟达",
            keyword="AI芯片",
        )
        assert len(queries) > 0
        assert any("英伟达" in q or "AI芯片" in q for q in queries)

    def test_deduplicate_removes_duplicate_urls(self):
        results = [
            SearchResult(title="A", url="http://example.com/1", summary="test", provider="test"),
            SearchResult(title="A", url="http://example.com/1", summary="test", provider="test"),
            SearchResult(title="B", url="http://example.com/2", summary="test", provider="test"),
        ]
        deduped = self.orchestrator.deduplicate(results)
        assert len(deduped) == 2

    def test_deduplicate_removes_duplicate_titles(self):
        results = [
            SearchResult(title="Same", url="http://example.com/1", summary="test", provider="test"),
            SearchResult(title="Same", url="http://example.com/2", summary="test", provider="test"),
        ]
        deduped = self.orchestrator.deduplicate(results)
        assert len(deduped) == 1
