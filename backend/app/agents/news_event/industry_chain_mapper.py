"""Industry chain mapper - maps events to A-share sectors and stocks."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .schemas import IndustryChainNode

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_PATH = Path(__file__).parent.parent.parent.parent.parent / "data" / "knowledge" / "industry_chains.json"


class IndustryChainMapper:
    """产业链映射器 - 根据事件实体匹配产业链节点和 A 股标的。"""

    def __init__(self) -> None:
        self._knowledge: dict[str, Any] = {}
        self._loaded = False

    @property
    def knowledge(self) -> dict[str, Any]:
        if not self._loaded:
            self._load_knowledge()
        return self._knowledge

    def _load_knowledge(self) -> None:
        try:
            if KNOWLEDGE_BASE_PATH.exists():
                with open(KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
                    self._knowledge = json.load(f)
            else:
                logger.info("产业链知识库文件不存在: %s", KNOWLEDGE_BASE_PATH)
                self._knowledge = {}
        except Exception as exc:
            logger.warning("加载产业链知识库失败: %s", exc)
            self._knowledge = {}
        self._loaded = True

    def map_entities(self, entity_names: list[str],
                     keywords: list[str] | None = None) -> list[IndustryChainNode]:
        chains: list[IndustryChainNode] = []
        seen_sectors: set[str] = set()

        search_terms = list(entity_names)
        if keywords:
            search_terms.extend(keywords)

        for entity_name in search_terms:
            entity_lower = entity_name.lower()
            for key, entry in self.knowledge.items():
                key_lower = key.lower()
                if key_lower not in entity_lower and entity_lower not in key_lower:
                    continue

                for chain in entry.get("chains", []):
                    if not isinstance(chain, dict):
                        continue
                    sector = chain.get("sector", "")
                    if sector and sector not in seen_sectors:
                        seen_sectors.add(sector)
                        chains.append(IndustryChainNode(
                            sector=sector,
                            nodes=chain.get("nodes", []),
                            a_share_mapping=chain.get("a_share_mapping", []),
                        ))

        return chains

    def get_stocks_for_sectors(self, sectors: list[str]) -> list[dict[str, Any]]:
        stocks: list[dict[str, Any]] = []
        seen_codes: set[str] = set()

        for key, entry in self.knowledge.items():
            for chain in entry.get("chains", []):
                if not isinstance(chain, dict):
                    continue
                if chain.get("sector") not in sectors:
                    continue
                for stock in chain.get("a_share_mapping", []):
                    if not isinstance(stock, dict):
                        continue
                    code = stock.get("code", "")
                    if code and code not in seen_codes:
                        seen_codes.add(code)
                        stocks.append(stock)

        return stocks


industry_chain_mapper = IndustryChainMapper()
