"""News Event Analysis Agent schemas."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    READY = "ready"
    NEED_MORE_DATA = "need_more_data"
    STOPPED = "stopped"
    FAILED = "failed"
    RUNNING = "running"


class EventType(str, Enum):
    DOMESTIC_COMPANY = "domestic_company"
    DOMESTIC_INDUSTRY = "domestic_industry"
    OVERSEAS_COMPANY = "overseas_company"
    OVERSEAS_INDUSTRY = "overseas_industry"
    MACRO_POLICY = "macro_policy"
    GEOPOLITICAL_BROAD = "geopolitical_broad"
    MARKET_MOVEMENT = "market_movement"
    UNVERIFIABLE_RUMOR = "unverifiable_rumor"
    NOT_ANALYZABLE = "not_analyzable"


class MarketScope(str, Enum):
    DOMESTIC = "domestic"
    OVERSEAS = "overseas"
    BOTH = "both"
    NONE = "none"


class EvidenceLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class RealizationStatus(str, Enum):
    NOT_REALIZED = "not_realized"
    PARTIALLY_REALIZED = "partially_realized"
    LIKELY_PRICED_IN = "likely_priced_in"
    MOVED_BEFORE_NEWS = "moved_before_news"
    INSUFFICIENT_MARKET_DATA = "insufficient_market_data"


class MappingStrength(str, Enum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


class EntityType(str, Enum):
    COMPANY_ENTITY = "company_entity"
    STOCK_ENTITY = "stock_entity"
    INDUSTRY_ENTITY = "industry_entity"
    TECHNOLOGY_ENTITY = "technology_entity"
    POLICY_ENTITY = "policy_entity"
    COMMODITY_ENTITY = "commodity_entity"
    COUNTRY_REGION_ENTITY = "country_region_entity"


class SearchResult(BaseModel):
    title: str
    url: str
    summary: str = ""
    source: str = ""
    published_at: Optional[str] = None
    provider: str = "searxng"
    score: float = 0.0


class EventClassification(BaseModel):
    event_type: EventType
    market_scope: MarketScope
    analyzable: bool
    mapping_required: bool
    reason: str


class Evidence(BaseModel):
    id: str = ""
    title: str = ""
    url: str = ""
    source: str = ""
    source_level: EvidenceLevel = EvidenceLevel.C
    published_at: Optional[str] = None
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    provider: str = "searxng"
    confidence: float = 0.5


class ResolvedEntity(BaseModel):
    entity_type: EntityType
    name: str
    matched_code: Optional[str] = None
    matched_name: Optional[str] = None
    is_overseas: bool = False
    confidence: float = 0.5


class IndustryChainNode(BaseModel):
    sector: str = ""
    nodes: list[str] = Field(default_factory=list)
    a_share_mapping: list[dict[str, Any]] = Field(default_factory=list)


class StockRealization(BaseModel):
    code: str = ""
    name: str = ""
    change_1d: Optional[float] = None
    change_3d: Optional[float] = None
    change_5d: Optional[float] = None
    change_20d: Optional[float] = None
    limit_up: bool = False
    volume_ratio: Optional[float] = None
    moved_before_news: bool = False
    realization_status: RealizationStatus = RealizationStatus.INSUFFICIENT_MARKET_DATA
    reason: str = ""


class RelatedStock(BaseModel):
    code: str = ""
    name: str = ""
    relation: str = ""
    mapping_strength: MappingStrength = MappingStrength.WEAK
    reason: str = ""


class ImpactPath(BaseModel):
    description: str = ""
    confidence: float = 0.0


class RoundRecord(BaseModel):
    round_num: int = 0
    queries: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    status: AgentStatus = AgentStatus.RUNNING


class AnalysisResult(BaseModel):
    status: AgentStatus
    task_id: str = ""
    event_type: Optional[str] = None
    confidence: Optional[float] = None
    event_summary: str = ""
    core_facts: list[str] = Field(default_factory=list)
    impact_path: list[ImpactPath] = Field(default_factory=list)
    direct_sectors: list[str] = Field(default_factory=list)
    indirect_sectors: list[str] = Field(default_factory=list)
    related_stocks: list[RelatedStock] = Field(default_factory=list)
    market_realization: list[StockRealization] = Field(default_factory=list)
    market_sentiment: Optional[dict[str, Any]] = None
    upstream_downstream: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    watch_points: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    rounds: list[RoundRecord] = Field(default_factory=list)
    reason: str = ""


class AnalyzeDetailRequest(BaseModel):
    news_id: str = ""
    title: str
    summary: str = ""
    category: str = ""
    source: str = ""
    published_at: Optional[str] = None
    event_time: Optional[str] = None
    url: Optional[str] = None


class LLMRoundOutput(BaseModel):
    status: AgentStatus
    reason: str = ""
    search_queries: list[str] = Field(default_factory=list)
