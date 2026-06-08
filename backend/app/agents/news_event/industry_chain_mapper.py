"""Industry chain mapper - maps events to A-share sectors and stocks."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .schemas import IndustryChainNode

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_PATH = Path(__file__).parent.parent.parent.parent.parent / "data" / "knowledge" / "industry_chains.json"

SUPPLEMENTAL_KNOWLEDGE: dict[str, Any] = {
    "港口航运": {
        "chains": [
            {
                "sector": "港口航运",
                "nodes": ["港口装卸", "集装箱运输", "国际航线", "外贸物流", "多式联运"],
                "a_share_mapping": [
                    {
                        "code": "002040.SZ",
                        "name": "南京港",
                        "relation": "南京区域港口运营",
                        "strength": "strong",
                        "reason": "新闻涉及南京港新增国际航线，区域港口吞吐和外贸物流弹性更直接",
                    },
                    {
                        "code": "600018.SH",
                        "name": "上港集团",
                        "relation": "港口集装箱枢纽",
                        "strength": "medium",
                        "reason": "长三角港口龙头，国际航线和外贸箱量变化具备行业映射意义",
                    },
                    {
                        "code": "601018.SH",
                        "name": "宁波港",
                        "relation": "外贸港口",
                        "strength": "medium",
                        "reason": "沿海外贸港口龙头，受益外贸航线和港口吞吐改善预期",
                    },
                    {
                        "code": "601919.SH",
                        "name": "中远海控",
                        "relation": "集装箱航运",
                        "strength": "medium",
                        "reason": "国际航线、外贸货量和运价变化与集运景气相关",
                    },
                ],
            },
            {
                "sector": "物流运输",
                "nodes": ["货运代理", "工程设备运输", "跨境物流", "港口集疏运"],
                "a_share_mapping": [
                    {
                        "code": "603128.SH",
                        "name": "华贸物流",
                        "relation": "跨境综合物流",
                        "strength": "medium",
                        "reason": "跨境物流服务商，国际航线和货运需求改善具备映射",
                    },
                    {
                        "code": "601598.SH",
                        "name": "中国外运",
                        "relation": "综合物流",
                        "strength": "medium",
                        "reason": "央企综合物流平台，外贸物流链条相关",
                    },
                ],
            },
        ],
    },
    "南京港": {
        "chains": [
            {
                "sector": "港口航运",
                "nodes": ["南京港", "国际航线", "外贸物流", "工程设备运输"],
                "a_share_mapping": [
                    {
                        "code": "002040.SZ",
                        "name": "南京港",
                        "relation": "新闻直接相关港口",
                        "strength": "strong",
                        "reason": "新闻直接提及南京港新增直航美国休斯敦航线",
                    },
                    {
                        "code": "601598.SH",
                        "name": "中国外运",
                        "relation": "外贸物流",
                        "strength": "medium",
                        "reason": "外贸物流链条相关，需结合实际业务承运关系确认",
                    },
                    {
                        "code": "603128.SH",
                        "name": "华贸物流",
                        "relation": "跨境物流",
                        "strength": "medium",
                        "reason": "跨境物流链条相关，受益逻辑需后续订单验证",
                    },
                ],
            },
        ],
    },
}


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
        self._merge_supplemental_knowledge()
        self._loaded = True

    def _merge_supplemental_knowledge(self) -> None:
        for key, entry in SUPPLEMENTAL_KNOWLEDGE.items():
            self._knowledge.setdefault(key, entry)

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
