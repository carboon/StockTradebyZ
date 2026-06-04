"""Tests for EvidenceRanker."""
from __future__ import annotations

import pytest

from app.agents.news_event.evidence_ranker import EvidenceRanker
from app.agents.news_event.schemas import EvidenceLevel, SearchResult


class TestEvidenceRanker:
    def setup_method(self):
        self.ranker = EvidenceRanker()

    def test_classify_source_a_level(self):
        level = self.ranker._classify_source("证监会公告", "http://www.csrc.gov.cn/example")
        assert level == EvidenceLevel.A

    def test_classify_source_b_level(self):
        level = self.ranker._classify_source("财联社", "https://www.cls.cn/example")
        assert level == EvidenceLevel.B

    def test_classify_source_c_level(self):
        level = self.ranker._classify_source("新浪财经", "https://finance.sina.com.cn/example")
        assert level == EvidenceLevel.C

    def test_classify_source_d_level(self):
        level = self.ranker._classify_source("某网友", "https://xueqiu.com/example")
        assert level == EvidenceLevel.D

    def test_rank_orders_by_confidence(self):
        results = [
            SearchResult(
                title="证监会发布新规",
                url="http://www.csrc.gov.cn/1",
                summary="正式文件",
                source="证监会",
                provider="searxng",
                score=0.9,
            ),
            SearchResult(
                title="论坛讨论帖",
                url="https://guba.com.cn/1",
                summary="讨论内容",
                source="股吧",
                provider="searxng",
                score=0.1,
            ),
        ]
        evidence = self.ranker.rank(results)
        assert len(evidence) == 2
        assert evidence[0].source_level == EvidenceLevel.A
        assert evidence[0].confidence > evidence[1].confidence

    def test_rank_deduplication(self):
        results = [
            SearchResult(
                title="同一标题",
                url="http://example.com/1",
                summary="相同内容",
                source="test",
                provider="searxng",
            ),
            SearchResult(
                title="同一标题",
                url="http://example.com/1",
                summary="相同内容",
                source="test",
                provider="searxng",
            ),
        ]
        evidence = self.ranker.rank(results)
        assert evidence[1].confidence < evidence[0].confidence
