"""Evidence ranker - scores and classifies evidence by source reliability."""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

from .schemas import Evidence, EvidenceLevel, SearchResult

logger = logging.getLogger(__name__)

SOURCE_LEVEL_MAP: dict[str, EvidenceLevel] = {
    "sse.com.cn": EvidenceLevel.A,
    "szse.cn": EvidenceLevel.A,
    "csrc.gov.cn": EvidenceLevel.A,
    "pbc.gov.cn": EvidenceLevel.A,
    "ndrc.gov.cn": EvidenceLevel.A,
    "most.gov.cn": EvidenceLevel.A,
    "cls.cn": EvidenceLevel.B,
    "stcn.com": EvidenceLevel.B,
    "cnstock.com": EvidenceLevel.B,
    "cs.com.cn": EvidenceLevel.B,
    "eastmoney.com": EvidenceLevel.B,
    "10jqka.com.cn": EvidenceLevel.B,
    "sina.com.cn": EvidenceLevel.C,
    "163.com": EvidenceLevel.C,
    "sohu.com": EvidenceLevel.C,
    "qq.com": EvidenceLevel.C,
    "ifeng.com": EvidenceLevel.C,
    "wallstreetcn.com": EvidenceLevel.B,
    "jin10.com": EvidenceLevel.B,
    "xueqiu.com": EvidenceLevel.D,
    "guba.com.cn": EvidenceLevel.D,
    "taoguba.com.cn": EvidenceLevel.D,
}

LEVEL_SCORE_MAP: dict[EvidenceLevel, float] = {
    EvidenceLevel.A: 0.95,
    EvidenceLevel.B: 0.75,
    EvidenceLevel.C: 0.50,
    EvidenceLevel.D: 0.20,
}


class EvidenceRanker:
    """证据评分器 - 根据来源、时效性、重复度给证据打分。"""

    def rank(self, results: list[SearchResult],
             published_at: Optional[str] = None) -> list[Evidence]:
        evidence_list: list[Evidence] = []
        seen_fingerprints: set[str] = set()

        for i, result in enumerate(results):
            source_level = self._classify_source(result.source, result.url)
            level_score = LEVEL_SCORE_MAP.get(source_level, 0.3)

            fingerprint = self._fingerprint(result)
            is_duplicate = fingerprint in seen_fingerprints
            if fingerprint:
                seen_fingerprints.add(fingerprint)

            confidence = level_score
            if is_duplicate:
                confidence *= 0.3

            evidence = Evidence(
                id=f"ev_{i + 1:03d}",
                title=result.title,
                url=result.url,
                source=result.source,
                source_level=source_level,
                published_at=result.published_at,
                summary=result.summary,
                key_points=[],
                provider=result.provider,
                confidence=round(confidence, 2),
            )
            evidence_list.append(evidence)

        evidence_list.sort(key=lambda e: e.confidence, reverse=True)
        return evidence_list

    @staticmethod
    def _classify_source(source: str, url: str) -> EvidenceLevel:
        combined = f"{source} {url}".lower()

        for domain, level in SOURCE_LEVEL_MAP.items():
            if domain in combined:
                return level

        if re.search(r"(公告|交易所|证监会|央行|发改委|工信部)", combined):
            return EvidenceLevel.A
        if re.search(r"(财联社|证券时报|上证报|中国证券报|第一财经|21世纪|界面|澎湃)", combined):
            return EvidenceLevel.B
        if re.search(r"(自媒体|论坛|股吧|雪球|微博|微信|公众号|知乎)", combined):
            return EvidenceLevel.D

        return EvidenceLevel.C

    @staticmethod
    def _fingerprint(result: SearchResult) -> str:
        text = f"{result.title[:80]}{result.summary[:120]}"
        return hashlib.md5(text.encode()).hexdigest()


evidence_ranker = EvidenceRanker()
