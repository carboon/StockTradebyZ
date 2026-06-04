"""
Pydantic Schemas
~~~~~~~~~~~~~~~~
API 请求和响应数据模型
"""
from datetime import date as date_class
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ==================== 配置相关 ====================
class ConfigItem(BaseModel):
    """配置项"""
    key: str
    value: str
    description: Optional[str] = None


class ConfigUpdate(BaseModel):
    """更新配置"""
    key: str
    value: str


class ConfigResponse(BaseModel):
    """配置响应"""
    configs: List[ConfigItem]


class TushareVerifyRequest(BaseModel):
    """Tushare Token 验证请求"""
    token: str


class TushareVerifyResponse(BaseModel):
    """Tushare Token 验证响应"""
    valid: bool
    message: str


# ==================== 股票相关 ====================
class StockInfo(BaseModel):
    """股票基本信息"""
    code: str
    name: Optional[str] = None
    market: Optional[str] = None
    industry: Optional[str] = None


class StockResponse(BaseModel):
    """股票响应"""
    code: str
    name: Optional[str] = None
    market: Optional[str] = None
    industry: Optional[str] = None
    exists: bool


class StockSearchItem(BaseModel):
    """股票搜索结果项"""
    code: str
    name: Optional[str] = None
    market: Optional[str] = None
    industry: Optional[str] = None


class StockSearchResponse(BaseModel):
    """股票搜索响应"""
    items: List[StockSearchItem]
    total: int


class RiskFlagSummary(BaseModel):
    """风险标的识别结果"""
    level: Optional[str] = None
    score: Optional[float] = None
    heat_score: Optional[float] = None
    confirmation_score: Optional[float] = None
    narrative_score: Optional[float] = None
    recent_limit_up_days: Optional[int] = None
    recent_runup_pct: Optional[float] = None
    sector_breadth: Optional[float] = None
    sector_avg_change_pct: Optional[float] = None
    isolated_spike: Optional[bool] = None
    reversal_risk: bool = False
    tags: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    matched_themes: List[str] = Field(default_factory=list)
    summary: Optional[str] = None


class RiskRegimeSummary(BaseModel):
    """市场级过热转弱预警摘要"""
    level: Optional[str] = None
    score: Optional[float] = None
    heat_score: Optional[float] = None
    failure_score: Optional[float] = None
    breadth_score: Optional[float] = None
    triggered: bool = False
    risk_count: int = 0
    total_count: int = 0
    risk_ratio: Optional[float] = None
    high_risk_count: int = 0
    reversal_risk_count: int = 0
    isolated_spike_ratio: Optional[float] = None
    b1_pass_ratio: Optional[float] = None
    trend_start_ratio: Optional[float] = None
    failure_ratio: Optional[float] = None
    risk_trend: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    ai_confirmed_level: Optional[str] = None
    ai_confidence: Optional[float] = None
    ai_stance: Optional[str] = None
    ai_evidence_strength: Optional[str] = None
    ai_review: Optional[Dict[str, Any]] = None


# ==================== 候选股票 ====================
class CandidateItem(BaseModel):
    """候选股票项"""
    id: int
    pick_date: date_class
    code: str
    name: Optional[str] = None
    industry: Optional[str] = None
    sector_names: List[str] = Field(default_factory=list)
    strategy: Optional[str] = None
    open_price: Optional[float] = None
    close_price: Optional[float] = None
    change_pct: Optional[float] = None
    turnover: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    active_pool_rank: Optional[int] = None
    b1_passed: Optional[bool] = None
    kdj_j: Optional[float] = None
    consecutive_days: int = 1


class CandidatesResponse(BaseModel):
    """候选列表响应"""
    pick_date: Optional[date_class] = None
    candidates: List[CandidateItem]
    total: int
    # 只读模式状态字段
    status: Optional[str] = None  # "ok" | "not_ready" | "market_regime_blocked"
    message: Optional[str] = None
    has_running_task: Optional[bool] = None
    running_task_id: Optional[int] = None
    # 市场环境阻断时的额外信息
    market_regime_info: Optional[Dict[str, Any]] = None

    class Config:
        # 忽略额外字段（兼容旧代码）
        extra = "ignore"


class CurrentHotCandidateItem(BaseModel):
    """当前热盘股票池项"""
    id: int
    pick_date: date_class
    code: str
    name: Optional[str] = None
    sector_names: List[str] = Field(default_factory=list)
    board_group: Optional[str] = None
    open_price: Optional[float] = None
    close_price: Optional[float] = None
    change_pct: Optional[float] = None
    turnover: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    active_pool_rank: Optional[int] = None
    b1_passed: Optional[bool] = None
    kdj_j: Optional[float] = None
    verdict: Optional[str] = None
    total_score: Optional[float] = None
    signal_type: Optional[str] = None
    comment: Optional[str] = None
    pb: Optional[float] = None
    netprofit_yoy: Optional[float] = None
    roe: Optional[float] = None
    risk_flag: Optional[RiskFlagSummary] = None
    consecutive_days: int = 1
    price_streak_days: Optional[int] = None
    price_position_pct: Optional[float] = None


class CurrentHotCandidatesResponse(BaseModel):
    """当前热盘股票池响应"""
    pick_date: Optional[date_class] = None
    candidates: List[CurrentHotCandidateItem]
    total: int
    risk_regime: Optional[RiskRegimeSummary] = None


# ==================== 价值洼地 ====================
class ValueLowlandEvidence(BaseModel):
    title: str = ""
    url: str = ""
    summary: str = ""
    published_at: Optional[str] = None
    source: Optional[str] = None


class ValueLowlandCompanyProfile(BaseModel):
    ownership_type: str = "unknown"
    controller: Optional[str] = None
    main_business: Optional[str] = None
    business_focus_score: float = 0
    scarcity_score: float = 0
    cycle_type: str = "other"
    unique_assets: List[str] = Field(default_factory=list)
    evidence: List[ValueLowlandEvidence] = Field(default_factory=list)
    confidence: float = 0
    risk_notes: List[str] = Field(default_factory=list)
    cached: bool = False
    expires_at: Optional[datetime] = None


class ValueLowlandScoreBreakdown(BaseModel):
    ownership_score: float = 0
    low_valuation_score: float = 0
    financial_improvement_score: float = 0
    cycle_elasticity_score: float = 0
    business_focus_score: float = 0
    scarcity_score: float = 0
    risk_penalty: float = 0


class ValueLowlandCandidate(BaseModel):
    rank: int = 0
    code: str
    ts_code: str
    name: Optional[str] = None
    market: Optional[str] = None
    industry: Optional[str] = None
    close: Optional[float] = None
    trade_date: Optional[date_class] = None
    total_mv: Optional[float] = None
    circ_mv: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    low_position_ratio: Optional[float] = None
    drawdown_from_high_pct: Optional[float] = None
    roe: Optional[float] = None
    netprofit_yoy: Optional[float] = None
    rev_yoy: Optional[float] = None
    grossprofit_margin: Optional[float] = None
    score: float = 0
    score_breakdown: ValueLowlandScoreBreakdown = Field(default_factory=ValueLowlandScoreBreakdown)
    tags: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    risk_notes: List[str] = Field(default_factory=list)
    profile: ValueLowlandCompanyProfile = Field(default_factory=ValueLowlandCompanyProfile)


class ValueLowlandResponse(BaseModel):
    generated_at: datetime
    trade_date: Optional[date_class] = None
    source: str = "local_db+tushare+bocha+deepseek"
    total: int = 0
    enriched_count: int = 0
    message: Optional[str] = None
    total_rank: List[ValueLowlandCandidate] = Field(default_factory=list)
    soe_lowland: List[ValueLowlandCandidate] = Field(default_factory=list)
    cycle_resource: List[ValueLowlandCandidate] = Field(default_factory=list)
    earnings_reversal: List[ValueLowlandCandidate] = Field(default_factory=list)
    insufficient_evidence: List[ValueLowlandCandidate] = Field(default_factory=list)


class ValueLowlandRunStatus(BaseModel):
    id: Optional[int] = None
    status: str = "idle"
    limit: int = 100
    enrich: bool = True
    force_refresh: bool = False
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


# ==================== 分析结果 ====================
class AnalysisItem(BaseModel):
    """分析结果项"""
    id: int
    pick_date: date_class
    code: str
    name: Optional[str] = None
    reviewer: Optional[str] = None
    verdict: Optional[str] = None  # PASS/WATCH/FAIL
    total_score: Optional[float] = None
    signal_type: Optional[str] = None
    comment: Optional[str] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    active_pool_rank: Optional[int] = None
    tomorrow_star_pass: Optional[bool] = None
    prefilter_passed: Optional[bool] = None
    prefilter_summary: Optional[str] = None
    prefilter_blocked_by: Optional[List[str]] = None
    pullback_quality: Optional[str] = None
    pullback_negative_flags: Optional[List[str]] = None


class AnalysisResultResponse(BaseModel):
    """分析结果响应"""
    pick_date: Optional[date_class] = None
    results: List[AnalysisItem]
    total: int
    min_score_threshold: float
    # 市场环境阻断时的额外信息
    status: Optional[str] = None  # "ok" | "market_regime_blocked"
    message: Optional[str] = None
    market_regime_info: Optional[Dict[str, Any]] = None

    class Config:
        extra = "ignore"


class CurrentHotAnalysisItem(BaseModel):
    """当前热盘分析结果项"""
    id: int
    pick_date: date_class
    code: str
    name: Optional[str] = None
    sector_names: List[str] = Field(default_factory=list)
    board_group: Optional[str] = None
    reviewer: Optional[str] = None
    b1_passed: Optional[bool] = None
    verdict: Optional[str] = None
    total_score: Optional[float] = None
    signal_type: Optional[str] = None
    comment: Optional[str] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    active_pool_rank: Optional[int] = None
    prefilter_passed: Optional[bool] = None
    prefilter_summary: Optional[str] = None
    prefilter_blocked_by: Optional[List[str]] = None
    pb: Optional[float] = None
    netprofit_yoy: Optional[float] = None
    roe: Optional[float] = None
    pullback_quality: Optional[str] = None
    pullback_negative_flags: Optional[List[str]] = None
    risk_flag: Optional[RiskFlagSummary] = None
    price_streak_days: Optional[int] = None
    price_position_pct: Optional[float] = None


class CurrentHotAnalysisResultResponse(BaseModel):
    """当前热盘分析结果响应"""
    pick_date: Optional[date_class] = None
    results: List[CurrentHotAnalysisItem]
    total: int
    min_score_threshold: float
    risk_regime: Optional[RiskRegimeSummary] = None


class IntradayAnalysisItem(BaseModel):
    """中盘分析快照项"""
    id: int
    trade_date: date_class
    code: str
    name: Optional[str] = None
    source_pick_date: date_class
    snapshot_time: datetime
    open_price: Optional[float] = None
    midday_price: Optional[float] = None
    close_price: Optional[float] = None
    latest_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    change_pct: Optional[float] = None
    latest_change_pct: Optional[float] = None
    turnover: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    active_pool_rank: Optional[int] = None
    b1_passed: Optional[bool] = None
    score: Optional[float] = None
    verdict: Optional[str] = None
    signal_type: Optional[str] = None
    kdj_j: Optional[float] = None
    zx_long_pos: Optional[bool] = None
    weekly_ma_aligned: Optional[bool] = None
    volume_healthy: Optional[bool] = None
    midday_time: Optional[str] = None
    analysis_basis: Optional[str] = None
    previous_analysis: Optional[Dict[str, Any]] = None
    benchmark_name: Optional[str] = None
    benchmark_change_pct: Optional[float] = None
    relative_market_status: Optional[str] = None
    relative_market_strength_pct: Optional[float] = None
    manager_note: Optional[str] = None
    exit_plan: Optional[Dict[str, Any]] = None


class IntradayAnalysisResponse(BaseModel):
    """中盘分析数据响应"""
    trade_date: date_class
    source_pick_date: Optional[date_class] = None
    snapshot_time: Optional[datetime] = None
    window_open: bool
    has_data: bool
    status: str
    message: Optional[str] = None
    market_overview: Optional[Dict[str, Any]] = None
    items: List[IntradayAnalysisItem]
    total: int = 0


class IntradayAnalysisGenerateResponse(BaseModel):
    """中盘分析手动生成响应"""
    trade_date: date_class
    source_pick_date: Optional[date_class] = None
    snapshot_time: Optional[datetime] = None
    window_open: bool
    has_data: bool
    status: str
    message: Optional[str] = None
    generated_count: int = 0
    skipped_count: int = 0


class IntradayAnalysisPrefetchResponse(BaseModel):
    """中盘分析分时原始数据预下载响应"""
    trade_date: date_class
    source_pick_date: Optional[date_class] = None
    snapshot_time: Optional[datetime] = None
    window_open: bool
    has_data: bool
    status: str
    message: Optional[str] = None
    requested_count: int = 0
    ready_count: int = 0
    missing_count: int = 0
    midday_ready_count: int = 0
    cached_count: int = 0
    downloaded_count: int = 0


class CurrentHotIntradayAnalysisItem(BaseModel):
    """当前热盘中盘分析快照项"""
    id: int
    trade_date: date_class
    code: str
    name: Optional[str] = None
    source_pick_date: date_class
    snapshot_time: datetime
    sector_names: List[str] = Field(default_factory=list)
    board_group: Optional[str] = None
    open_price: Optional[float] = None
    midday_price: Optional[float] = None
    close_price: Optional[float] = None
    latest_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    change_pct: Optional[float] = None
    latest_change_pct: Optional[float] = None
    turnover: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    active_pool_rank: Optional[int] = None
    b1_passed: Optional[bool] = None
    score: Optional[float] = None
    verdict: Optional[str] = None
    signal_type: Optional[str] = None
    kdj_j: Optional[float] = None
    zx_long_pos: Optional[bool] = None
    weekly_ma_aligned: Optional[bool] = None
    volume_healthy: Optional[bool] = None
    midday_time: Optional[str] = None
    analysis_basis: Optional[str] = None
    previous_analysis: Optional[Dict[str, Any]] = None
    benchmark_name: Optional[str] = None
    benchmark_change_pct: Optional[float] = None
    relative_market_status: Optional[str] = None
    relative_market_strength_pct: Optional[float] = None
    manager_note: Optional[str] = None
    exit_plan: Optional[Dict[str, Any]] = None


class CurrentHotIntradayAnalysisResponse(BaseModel):
    """当前热盘中盘分析数据响应"""
    trade_date: date_class
    source_pick_date: Optional[date_class] = None
    snapshot_time: Optional[datetime] = None
    window_open: bool
    has_data: bool
    status: str
    message: Optional[str] = None
    market_overview: Optional[Dict[str, Any]] = None
    items: List[CurrentHotIntradayAnalysisItem]
    total: int = 0


class CurrentHotIntradayAnalysisGenerateResponse(BaseModel):
    """当前热盘中盘分析手动生成响应"""
    trade_date: date_class
    source_pick_date: Optional[date_class] = None
    snapshot_time: Optional[datetime] = None
    window_open: bool
    has_data: bool
    status: str
    message: Optional[str] = None
    generated_count: int = 0
    skipped_count: int = 0


class CurrentHotIntradayAnalysisPrefetchResponse(BaseModel):
    """当前热盘中盘分时原始数据预下载响应"""
    trade_date: date_class
    source_pick_date: Optional[date_class] = None
    snapshot_time: Optional[datetime] = None
    window_open: bool
    has_data: bool
    status: str
    message: Optional[str] = None
    requested_count: int = 0
    ready_count: int = 0
    missing_count: int = 0
    midday_ready_count: int = 0
    cached_count: int = 0
    downloaded_count: int = 0


class ClosingSectorFlowItem(BaseModel):
    """收盘分析板块资金流项"""
    sector_name: str
    net_mf_amount: float


class ClosingMarketOverview(BaseModel):
    """收盘分析大盘概览"""
    trend: str
    trade_date: Optional[date_class] = None
    previous_trade_date: Optional[date_class] = None
    avg_change_pct: Optional[float] = None
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    total_count: int = 0
    summary: Optional[str] = None


class ClosingSectorFlow(BaseModel):
    """收盘分析板块资金流"""
    source: Optional[str] = None
    source_trade_date: Optional[date_class] = None
    is_fallback: bool = False
    inflow_top3: List[ClosingSectorFlowItem] = Field(default_factory=list)
    outflow_top3: List[ClosingSectorFlowItem] = Field(default_factory=list)


class ClosingHotTopicItem(BaseModel):
    """收盘分析热点关键词"""
    keyword: str
    category: Optional[str] = None
    heat: Optional[float] = None
    reason: Optional[str] = None
    related_sectors: List[str] = Field(default_factory=list)
    related_companies: List[str] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)


class ClosingHotTopics(BaseModel):
    """近三天市场热点"""
    source: Optional[str] = None
    window_days: int = 3
    start_date: Optional[date_class] = None
    end_date: Optional[date_class] = None
    search_queries: List[str] = Field(default_factory=list)
    keywords: List[ClosingHotTopicItem] = Field(default_factory=list)
    summary: Optional[str] = None
    confidence: Optional[float] = None
    evidence: List[Dict[str, Any]] = Field(default_factory=list)


class NewsBoardRelatedStock(BaseModel):
    """消息板块关联股票"""
    code: str
    name: str
    sentiment: str = "neutral"
    reason: str = ""


class NewsBoardItem(BaseModel):
    """24H 消息板块条目"""
    id: str
    title: str
    summary: str = ""
    category: str
    source: str
    event_time: Optional[datetime] = None
    eventTime: Optional[datetime] = None
    published_at: Optional[datetime] = None
    publishedAt: Optional[datetime] = None
    ingested_at: Optional[datetime] = None
    ingestedAt: Optional[datetime] = None
    impact: str = "medium"
    region: Optional[str] = None
    url: Optional[str] = None
    source_url: Optional[str] = None
    sourceUrl: Optional[str] = None
    source_level: str = "media"
    sourceLevel: str = "media"
    source_type: Optional[str] = None
    related_stocks: List[NewsBoardRelatedStock] = Field(default_factory=list)
    relatedStocks: List[NewsBoardRelatedStock] = Field(default_factory=list)


class NewsBoardSourceStatus(BaseModel):
    """消息板块来源状态"""
    name: str
    source_key: str
    available: bool
    item_count: int = 0
    description: Optional[str] = None


class NewsBoardItemsResponse(BaseModel):
    """24H 消息板块列表响应"""
    window_hours: int = 24
    generated_at: datetime
    items: List[NewsBoardItem] = Field(default_factory=list)
    sources: List[NewsBoardSourceStatus] = Field(default_factory=list)
    duplicate_count: int = 0
    message: Optional[str] = None


class NewsBoardAnalyzeRequest(BaseModel):
    """消息板块 AI 分析请求"""
    news_id: Optional[str] = None
    title: str
    summary: str = ""
    category: Optional[str] = None


class NewsBoardAnalyzeResponse(BaseModel):
    """消息板块 AI 分析响应"""
    summary: str
    stocks: List[NewsBoardRelatedStock] = Field(default_factory=list)


class ClosingCandidateMoveItem(BaseModel):
    """收盘分析候选股涨跌项"""
    code: str
    name: Optional[str] = None
    sector_names: List[str] = Field(default_factory=list)
    base_close: Optional[float] = None
    latest_close: Optional[float] = None
    change_pct: float
    source_pick_date: date_class


class ClosingCandidateMoveBucket(BaseModel):
    """收盘分析候选股回看分组"""
    label: str
    source_pick_date: date_class
    rising: List[ClosingCandidateMoveItem] = Field(default_factory=list)
    falling: List[ClosingCandidateMoveItem] = Field(default_factory=list)


class ClosingTomorrowPredictionItem(BaseModel):
    """收盘分析明日预测项"""
    rank: Optional[int] = None
    code: str
    name: Optional[str] = None
    sector_names: List[str] = Field(default_factory=list)
    b1_score: Optional[float] = None
    b1_passed: Optional[bool] = None
    b1_comment: Optional[str] = None
    signal_type: Optional[str] = None
    verdict: Optional[str] = None
    close_price: Optional[float] = None
    change_pct: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    sector_net_mf_amount: Optional[float] = None
    sector_3d_net_mf_amount: Optional[float] = None
    is_industry_leader: Optional[bool] = None
    market_cap: Optional[float] = None
    financial_performance: Optional[Dict[str, Any]] = None
    institutional_rating: Optional[Dict[str, Any]] = None
    tomorrow_star_pass: Optional[bool] = None
    is_star_rejected: Optional[bool] = None
    topic_relevance_score: Optional[float] = None
    matched_hot_topics: List[str] = Field(default_factory=list)
    local_score: Optional[float] = None
    local_reasons: List[str] = Field(default_factory=list)
    ai_score: Optional[float] = None
    bullish_news: List[str] = Field(default_factory=list)
    negative_news: List[str] = Field(default_factory=list)
    ai_comment: Optional[str] = None
    decision_reason: Optional[str] = None


class ClosingTomorrowPrediction(BaseModel):
    """收盘分析明日预测"""
    trade_date: Optional[date_class] = None
    status: Optional[str] = None
    message: Optional[str] = None
    preselected: List[ClosingTomorrowPredictionItem] = Field(default_factory=list)
    selected: List[ClosingTomorrowPredictionItem] = Field(default_factory=list)
    sector_flow_history: List[Dict[str, Any]] = Field(default_factory=list)
    hot_topics: Optional[ClosingHotTopics] = None
    ai: Optional[Dict[str, Any]] = None


class ClosingAnalysisStatusResponse(BaseModel):
    latest_data_date: Optional[date_class] = None
    report_trade_date: Optional[date_class] = None
    has_report: bool = False
    can_generate: bool = False
    running_task_id: Optional[int] = None
    running_task_status: Optional[str] = None
    status: str
    message: str


class ClosingAnalysisReportResponse(BaseModel):
    id: Optional[int] = None
    has_report: bool = False
    generated: bool = False
    status: Optional[str] = None
    message: Optional[str] = None
    trade_date: Optional[date_class] = None
    source_data_date: Optional[date_class] = None
    generated_at: Optional[datetime] = None
    force_generated: bool = False
    task_id: Optional[int] = None
    ws_url: Optional[str] = None
    task_status: Optional[str] = None
    existing_task: Optional[bool] = None
    market: Optional[ClosingMarketOverview] = None
    sector_flow: Optional[ClosingSectorFlow] = None
    hot_topics: Optional[ClosingHotTopics] = None
    candidate_buckets: List[ClosingCandidateMoveBucket] = Field(default_factory=list)
    tomorrow_prediction: Optional[ClosingTomorrowPrediction] = None


class TomorrowStarHistoryItem(BaseModel):
    """明日之星历史窗口项"""
    pick_date: date_class
    date: str
    count: int = 0
    pass_count: int = 0
    candidate_count: int = 0
    analysis_count: int = 0
    trend_start_count: int = 0
    consecutive_candidate_count: int = 0
    tomorrow_star_count: int = 0
    status: str = "missing"
    error_message: Optional[str] = None
    is_latest: bool = False
    market_regime_blocked: bool = False
    market_regime_info: Optional[Dict[str, Any]] = None


class TomorrowStarDatesResponse(BaseModel):
    """明日之星历史日期列表响应"""
    dates: List[str]
    history: List[TomorrowStarHistoryItem]
    window_status: Optional["TomorrowStarWindowStatusResponse"] = None


class TomorrowStarWindowStatusResponse(BaseModel):
    """明日之星滚动窗口状态响应"""
    window_size: int
    latest_date: Optional[date_class] = None
    ready_count: int = 0
    missing_count: int = 0
    running_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    has_running_task: bool = False
    running_task_id: Optional[int] = None
    items: List[TomorrowStarHistoryItem]
    history: List[TomorrowStarHistoryItem]


class TomorrowStarAggregateResponse(BaseModel):
    """明日之星聚合接口响应 - 一次返回首屏所需全部数据"""
    # 日期窗口信息
    dates: List[str]
    history: List[TomorrowStarHistoryItem]
    window_status: Optional[TomorrowStarWindowStatusResponse] = None

    # 最新候选数据
    candidates: Optional[CandidatesResponse] = None

    # 最新分析结果
    results: Optional[AnalysisResultResponse] = None

    # 新鲜度状态
    freshness: Optional[Dict[str, Any]] = None
    generated_at: Optional[datetime] = None
    cache_hit: bool = False


class CurrentHotHistoryItem(BaseModel):
    """当前热盘历史项"""
    pick_date: date_class
    date: str
    candidate_count: int = 0
    analysis_count: int = 0
    trend_start_count: int = 0
    b1_pass_count: int = 0
    consecutive_candidate_count: int = 0
    pass_count: int = 0
    status: str = "missing"
    error_message: Optional[str] = None
    is_latest: bool = False


class CurrentHotDatesResponse(BaseModel):
    """当前热盘历史日期响应"""
    dates: List[str]
    history: List[CurrentHotHistoryItem]
    latest_date: Optional[date_class] = None


class CurrentHotSectorLeaderItem(BaseModel):
    """板块强度排序中的领涨股摘要"""
    code: str
    name: Optional[str] = None
    total_score: Optional[float] = None
    signal_type: Optional[str] = None
    verdict: Optional[str] = None
    active_pool_rank: Optional[int] = None


class CurrentHotSectorHistoryPoint(BaseModel):
    """板块历史轮动点"""
    date: str
    rank: int
    strength_score: float = 0.0
    tracked_count: int = 0
    b1_count: int = 0
    trend_start_count: int = 0
    pass_count: int = 0
    high_score_count: int = 0
    negative_flag_count: int = 0
    avg_score: Optional[float] = None
    avg_change_pct: Optional[float] = None


class CurrentHotSectorSummaryItem(BaseModel):
    """最新交易日的板块强弱摘要"""
    sector_key: str
    sector_name: str
    description: str
    policy_focus: List[str] = Field(default_factory=list)
    focus_tracks: List[str] = Field(default_factory=list)
    rank: Optional[int] = None
    previous_rank: Optional[int] = None
    rank_change: Optional[int] = None
    pool_count: int = 0
    tracked_count: int = 0
    pool_hit_ratio: float = 0.0
    b1_count: int = 0
    trend_start_count: int = 0
    pass_count: int = 0
    high_score_count: int = 0
    negative_flag_count: int = 0
    active_top20_count: int = 0
    active_top50_count: int = 0
    avg_score: Optional[float] = None
    avg_change_pct: Optional[float] = None
    best_active_pool_rank: Optional[int] = None
    strength_score: float = 0.0
    leaders: List[CurrentHotSectorLeaderItem] = Field(default_factory=list)


class CurrentHotSectorHistorySeries(BaseModel):
    """单个板块的轮动历史序列"""
    sector_key: str
    sector_name: str
    points: List[CurrentHotSectorHistoryPoint] = Field(default_factory=list)


class CurrentHotSectorAnalysisResponse(BaseModel):
    """当前热盘板块强弱与历史轮动响应"""
    latest_date: Optional[date_class] = None
    previous_date: Optional[date_class] = None
    window_size: int = 0
    dates: List[str] = Field(default_factory=list)
    top_sector_keys: List[str] = Field(default_factory=list)
    sectors: List[CurrentHotSectorSummaryItem] = Field(default_factory=list)
    history: List[CurrentHotSectorHistorySeries] = Field(default_factory=list)


class SectorAnalysisRowItem(BaseModel):
    """板块分析单日个股行"""
    id: int
    pick_date: date_class
    sector_key: str
    code: str
    name: Optional[str] = None
    sector_names: List[str] = Field(default_factory=list)
    board_group: Optional[str] = None
    open_price: Optional[float] = None
    close_price: Optional[float] = None
    change_pct: Optional[float] = None
    turnover: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    active_pool_rank: Optional[int] = None
    b1_passed: Optional[bool] = None
    kdj_j: Optional[float] = None
    verdict: Optional[str] = None
    total_score: Optional[float] = None
    signal_type: Optional[str] = None
    comment: Optional[str] = None
    prefilter_passed: Optional[bool] = None
    prefilter_summary: Optional[str] = None
    prefilter_blocked_by: Optional[List[str]] = None
    pullback_quality: Optional[str] = None
    pullback_negative_flags: Optional[List[str]] = None


class SectorAnalysisRowsResponse(BaseModel):
    """板块分析单日个股列表响应"""
    sector_key: str
    pick_date: Optional[date_class] = None
    rows: List[SectorAnalysisRowItem] = Field(default_factory=list)
    total: int = 0


# ==================== 单股诊断 ====================
class B1CheckItem(BaseModel):
    """B1检查项

    注意：check_date 是交易日日期，数据为该交易日收盘后的检查结果。
    """
    check_date: date_class
    close_price: Optional[float] = None
    change_pct: Optional[float] = None
    kdj_j: Optional[float] = None
    kdj_low_rank: Optional[float] = None
    zx_long_pos: Optional[bool] = None
    weekly_ma_aligned: Optional[bool] = None
    volume_healthy: Optional[bool] = None
    active_pool_rank: Optional[int] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    in_active_pool: Optional[bool] = None
    b1_passed: Optional[bool] = None
    b1_signal_type: Optional[str] = None
    prefilter_passed: Optional[bool] = None
    prefilter_blocked_by: Optional[List[str]] = None
    score: Optional[float] = None
    verdict: Optional[str] = None
    signal_type: Optional[str] = None
    tomorrow_star_pass: Optional[bool] = None
    notes: Optional[str] = None
    detail_ready: bool = False
    detail_version: Optional[str] = None
    detail_updated_at: Optional[datetime] = None


class DailyB1CheckDetailPayload(BaseModel):
    """单日诊断详情内容"""
    score_details: Optional[Dict[str, Any]] = None
    rules: Optional[Dict[str, Any]] = None
    details: Optional[Dict[str, Any]] = None


class DiagnosisHistoryDetailResponse(BaseModel):
    """单股诊断某日详情响应"""
    code: str
    check_date: date_class
    status: str
    detail_ready: bool = False
    detail_version: Optional[str] = None
    strategy_version: Optional[str] = None
    rule_version: Optional[str] = None
    detail_updated_at: Optional[datetime] = None
    payload: DailyB1CheckDetailPayload = Field(default_factory=DailyB1CheckDetailPayload)


class DiagnosisHistoryResponse(BaseModel):
    """诊断历史响应"""
    code: str
    name: Optional[str] = None
    history: List[B1CheckItem]
    total: int
    page: int = 1
    page_size: int = 10
    trend_start_dates: List[date_class] = Field(default_factory=list)
    tomorrow_star_dates: List[date_class] = Field(default_factory=list)
    # 只读模式状态字段
    data_ready: bool = True  # True=有历史数据, False=暂无历史数据（未生成）
    message: Optional[str] = None


class DiagnosisRequest(BaseModel):
    """单股诊断请求"""
    code: str


class DiagnosisResponse(BaseModel):
    """诊断响应"""
    code: str
    name: Optional[str] = None
    current_price: Optional[float] = None
    b1_passed: Optional[bool] = None
    score: Optional[float] = None
    verdict: Optional[str] = None
    analysis: Dict[str, Any]
    risk_regime: Optional[RiskRegimeSummary] = None
    kline_data: Optional[Dict[str, Any]] = None


class StockAiAnalysisResponse(BaseModel):
    """单股 AI 分析响应"""
    code: str
    name: Optional[str] = None
    provider: str
    model: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)


# ==================== 重点观察 ====================
class WatchlistAnalysisResult(BaseModel):
    """公共分析结果（拼装到观察列表中）"""
    trade_date: Optional[str] = None
    close_price: Optional[float] = None
    verdict: Optional[str] = None
    score: Optional[float] = None
    signal_type: Optional[str] = None
    b1_passed: Optional[bool] = None
    kdj_j: Optional[float] = None
    zx_long_pos: Optional[bool] = None
    weekly_ma_aligned: Optional[bool] = None
    volume_healthy: Optional[bool] = None


class WatchlistDerivedData(BaseModel):
    """派生数据（基于公共结果 + 用户配置计算）"""
    pnl: Optional[float] = None
    trend_outlook: Optional[str] = None
    buy_action: Optional[str] = None
    hold_action: Optional[str] = None
    risk_level: Optional[str] = None
    recommendation: Optional[str] = None
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    exit_plan: Optional[Dict[str, Any]] = None


class WatchlistLightItem(BaseModel):
    """观察列表轻量项（仅基础信息，不做重计算）"""
    id: int
    code: str
    name: Optional[str] = None
    add_reason: Optional[str] = None
    entry_price: Optional[float] = None
    entry_date: Optional[date_class] = None
    position_ratio: Optional[float] = None
    priority: int
    is_active: bool
    added_at: datetime


class WatchlistLightResponse(BaseModel):
    """观察列表轻量响应（支持分页）"""
    items: List[WatchlistLightItem]
    total: int
    page: int
    page_size: int


class WatchlistItem(BaseModel):
    """观察列表项（阶段2：支持公共结果拼装）"""
    id: int
    code: str
    name: Optional[str] = None
    add_reason: Optional[str] = None
    entry_price: Optional[float] = None
    entry_date: Optional[date_class] = None
    position_ratio: Optional[float] = None
    priority: int
    is_active: bool
    added_at: datetime
    # 阶段2新增：公共分析结果和派生数据
    analysis: Optional[WatchlistAnalysisResult] = None
    derived: Optional[WatchlistDerivedData] = None

    class Config:
        extra = "allow"  # 允许额外字段以保持兼容性


class WatchlistAddRequest(BaseModel):
    """添加到观察列表"""
    code: str
    reason: Optional[str] = None
    entry_price: Optional[float] = None
    entry_date: Optional[date_class] = None
    position_ratio: Optional[float] = None
    priority: int = 0


class WatchlistUpdateRequest(BaseModel):
    """更新观察项"""
    reason: Optional[str] = None
    entry_price: Optional[float] = None
    entry_date: Optional[date_class] = None
    position_ratio: Optional[float] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class WatchlistAnalysisItem(BaseModel):
    """观察分析项"""
    id: int
    watchlist_id: int
    analysis_date: date_class
    close_price: Optional[float] = None
    verdict: Optional[str] = None
    score: Optional[float] = None
    trend_outlook: Optional[str] = None
    buy_action: Optional[str] = None
    hold_action: Optional[str] = None
    risk_level: Optional[str] = None
    buy_recommendation: Optional[str] = None
    hold_recommendation: Optional[str] = None
    risk_recommendation: Optional[str] = None
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    exit_plan: Optional[Dict[str, Any]] = None
    recommendation: Optional[str] = None


class WatchlistResponse(BaseModel):
    """观察列表响应"""
    items: List[WatchlistItem]
    total: int


class WatchlistDetailResponse(BaseModel):
    """观察项详情响应（完整分析结果）"""
    id: int
    code: str
    name: Optional[str] = None
    add_reason: Optional[str] = None
    entry_price: Optional[float] = None
    entry_date: Optional[date_class] = None
    position_ratio: Optional[float] = None
    priority: int
    is_active: bool
    added_at: datetime
    analysis: Optional[WatchlistAnalysisResult] = None
    derived: Optional[WatchlistDerivedData] = None


# ==================== 任务调度 ====================
class TaskCreateRequest(BaseModel):
    """创建任务请求"""
    task_type: str  # full_update/single_analysis/tomorrow_star
    params: Optional[Dict[str, Any]] = None


class TaskItem(BaseModel):
    """任务项"""
    id: int
    task_type: str
    trigger_source: str
    status: str
    task_stage: Optional[str] = None
    progress: int
    params_json: Optional[Dict[str, Any]] = None
    progress_meta_json: Optional[Dict[str, Any]] = None
    result_json: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    summary: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class TaskLogItem(BaseModel):
    """任务日志项"""
    id: int
    task_id: int
    log_time: datetime
    level: str
    stage: Optional[str] = None
    message: str


class TaskLogListResponse(BaseModel):
    """任务日志列表"""
    task_id: int
    logs: List[TaskLogItem]
    total: int


class TaskResponse(BaseModel):
    """任务响应"""
    task: TaskItem
    ws_url: str


class TaskListResponse(BaseModel):
    """任务列表响应"""
    tasks: List[TaskItem]
    total: int


class TaskOverviewCard(BaseModel):
    key: str
    label: str
    value: str
    status: str = "info"
    meta: Optional[str] = None


class TaskAlertItem(BaseModel):
    level: str
    title: str
    message: str


class TaskOverviewResponse(BaseModel):
    cards: List[TaskOverviewCard]
    alerts: List[TaskAlertItem]


class TaskRunningResponse(BaseModel):
    tasks: List[TaskItem]
    total: int


class TaskEnvironmentSection(BaseModel):
    key: str
    label: str
    items: Dict[str, Any]


class TaskEnvironmentResponse(BaseModel):
    sections: List[TaskEnvironmentSection]


class TaskDiagnosticCheck(BaseModel):
    key: str
    label: str
    status: str
    summary: str
    action: Optional[str] = None


class TaskDiagnosticsResponse(BaseModel):
    generated_at: str
    checks: List[TaskDiagnosticCheck]
    running_tasks: List[TaskItem]
    latest_failed_task: Optional[TaskItem] = None
    latest_completed_task: Optional[TaskItem] = None
    environment: List[TaskEnvironmentSection]
    data_status: Dict[str, Any]


# ==================== 数据更新状态 ====================
class DataStatusResponse(BaseModel):
    """数据状态响应"""
    raw_data: Dict[str, Any]  # {exists: bool, stock_count: int, raw_record_count: int, latest_date: str}
    candidates: Dict[str, Any]  # {exists: bool, count: int, latest_date: str}
    analysis: Dict[str, Any]  # {exists: bool, count: int, latest_date: str}
    kline: Dict[str, Any]  # {exists: bool, count: int, latest_date: str}


class UpdateStartRequest(BaseModel):
    """启动更新请求"""
    reviewer: str = "quant"
    skip_fetch: bool = False
    start_from: int = 1
    reset_derived_state: bool = False


class TaskResumeInfo(BaseModel):
    """任务恢复信息（断点续传）"""
    task_id: int
    can_resume: bool
    completed_steps: List[str]
    completed_step_labels: List[str]
    next_step: Optional[str] = None
    next_step_label: Optional[str] = None
    start_from: int
    total_steps: int
    progress_percent: int


# ==================== K线数据 ====================
class KLineDataRequest(BaseModel):
    """K线数据请求"""
    code: str
    days: int = 120
    include_weekly: bool = True
    compact: bool = False


class KLineDataPoint(BaseModel):
    """K线数据点"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover_rate: Optional[float] = None
    turnover_rate_f: Optional[float] = None
    volume_ratio: Optional[float] = None
    free_share: Optional[float] = None
    circ_mv: Optional[float] = None
    buy_sm_amount: Optional[float] = None
    sell_sm_amount: Optional[float] = None
    buy_md_amount: Optional[float] = None
    sell_md_amount: Optional[float] = None
    buy_lg_amount: Optional[float] = None
    sell_lg_amount: Optional[float] = None
    buy_elg_amount: Optional[float] = None
    sell_elg_amount: Optional[float] = None
    net_mf_amount: Optional[float] = None
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None


class KLineResponse(BaseModel):
    """K线数据响应"""
    code: str
    name: Optional[str] = None
    daily: List[KLineDataPoint]
    weekly: Optional[List[KLineDataPoint]] = None
    indicators: Optional[Dict[str, Any]] = None


# =====================
# 认证相关 Schema
# =====================


class UserRegister(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    display_name: str | None = Field(None, max_length=100, description="显示名称")
    admin_wechat: str = Field(..., min_length=1, max_length=50, description="管理员微信验证答案")


class UserLogin(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class RegisterValidationPromptResponse(BaseModel):
    """注册验证问题响应"""
    question: str


class TokenResponse(BaseModel):
    """登录成功响应"""
    access_token: str
    token_type: str = "bearer"
    user: "UserInfo"


class UserInfo(BaseModel):
    """用户信息"""
    id: int
    username: str
    display_name: str | None
    role: str
    is_active: bool
    daily_quota: int
    is_online: bool = False
    last_login_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreate(BaseModel):
    """创建 API Key 请求"""
    name: str | None = Field(None, max_length=100, description="API Key 名称")


class ApiKeyResponse(BaseModel):
    """API Key 列表项"""
    id: int
    key_prefix: str
    name: str | None
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreateResponse(BaseModel):
    """创建 API Key 响应（仅创建时返回完整 key）"""
    id: int
    key: str
    key_prefix: str
    name: str | None


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=100, description="新密码")


class AdminUserUpdate(BaseModel):
    """管理员更新用户请求"""
    is_active: bool | None = None
    daily_quota: int | None = None
    role: str | None = None


class UsageStatsItem(BaseModel):
    """单日用量统计"""
    date: str
    total_calls: int
    endpoints: dict[str, int]


class UsageStatsResponse(BaseModel):
    """用量统计响应"""
    stats: list[UsageStatsItem]
    total_calls: int


class HourlyVisitStats(BaseModel):
    """小时访问统计"""
    hour: int
    count: int


class DailyVisitFrequency(BaseModel):
    """单日访问频率统计"""
    date: str
    total_calls: int
    hourly_stats: list[HourlyVisitStats]
    peak_hour: int | None = None
    peak_hour_count: int = 0


class VisitFrequencyResponse(BaseModel):
    """访问频率统计响应（最近10天）"""
    stats: list[DailyVisitFrequency]
    total_calls: int
    average_calls_per_day: float
    period_days: int = 10


class HeartbeatResponse(BaseModel):
    """心跳响应"""
    is_online: bool
    last_activity_at: datetime | None = None
    session_id: int | None = None
    message: str = "OK"


class CsvImportResult(BaseModel):
    """CSV 导入结果"""
    total_rows: int
    inserted_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    errors: list[str] = Field(default_factory=list)


class UserListItem(BaseModel):
    """用户列表项（管理员用）"""
    id: int
    username: str
    display_name: str | None
    role: str
    is_active: bool
    daily_quota: int
    created_at: datetime
    last_login_at: datetime | None = None
    is_online: bool = False
    recent_visit_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class UserSessionItem(BaseModel):
    """用户会话项"""
    id: int
    user_id: int
    login_at: datetime
    last_activity_at: datetime
    logout_at: datetime | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserSessionListResponse(BaseModel):
    """用户会话列表响应"""
    sessions: list[UserSessionItem]
    total: int


# ==================== 区间增量更新 ====================
class IncrementalFillStatus(BaseModel):
    """区间增量补齐状态"""
    stage: str  # gap_detection | kline_fill | tomorrow_star | top5_diagnosis | history_fill
    status: str  # pending | in_progress | completed | failed | partial
    total: int
    completed: int
    failed: int
    progress_pct: int
    message: str
    details: dict[str, Any] | None = None


class IncrementalGapInfo(BaseModel):
    """数据缺口信息"""
    has_gap: bool
    latest_local_date: str | None
    latest_trade_date: str | None
    gap_days: int
    gap_start: str | None
    gap_end: str | None
    missing_dates: list[str]


class IncrementalFillSummary(BaseModel):
    """区间增量更新总览"""
    gap: IncrementalGapInfo
    tomorrow_star: dict[str, Any]
    history: dict[str, Any]
    can_fill: bool
    recommended_action: str


class IncrementalFillAllResponse(BaseModel):
    """一键补齐响应"""
    success: bool
    results: dict[str, dict[str, Any]]
    summary: dict[str, int]


# ==================== 管理员总览摘要 ====================
class AdminSummaryCard(BaseModel):
    """总览卡片项"""
    key: str
    label: str
    value: str
    status: str = "info"  # success | warning | danger | info
    meta: str | None = None
    action_label: str | None = None
    action_route: str | None = None


class AdminSummaryTaskInfo(BaseModel):
    """任务信息"""
    id: int | None
    task_type: str | None
    status: str
    stage_label: str | None
    progress: int
    summary: str | None
    task_stage: str | None = None
    progress_meta_json: Dict[str, Any] | None = None


class AdminSummaryDataGap(BaseModel):
    """数据缺口信息"""
    has_gap: bool
    gap_days: int | None
    latest_local_date: str | None
    latest_trade_date: str | None


class AdminPipelineStageSummary(BaseModel):
    """总览中的单阶段摘要"""
    key: str
    label: str
    status: str = "info"
    ready: bool
    value: str
    meta: str | None = None
    detail: str | None = None


class AdminSummaryResponse(BaseModel):
    """管理员总览摘要响应"""
    # 今日状态
    today_status: list[AdminSummaryCard]
    # 三段式生产状态
    pipeline_status: list[AdminPipelineStageSummary]
    # 数据生产状态
    data_production: dict[str, str | int | bool | None]
    # 数据缺口
    data_gap: AdminSummaryDataGap
    # 当前任务
    current_task: AdminSummaryTaskInfo | None
    # 最近任务结果
    latest_task: Dict[str, Any] | None
    # 缺口天数
    gap_days: int
    # 当前任务状态
    task_status: str  # idle | running | failed | completed
    # 最近一次任务结果摘要
    latest_task_summary: str | None
    # 最新交易日信息
    latest_trade_date: str | None
    latest_db_date: str | None
    latest_candidate_date: str | None
    latest_analysis_date: str | None
    # 系统就绪状态
    system_ready: bool
    # 待处理事项
    pending_actions: list[dict[str, str]]


# ==================== 历史信号收益率分析 ====================
class SignalReturnTimelinePoint(BaseModel):
    """收益率时间序列点"""
    trade_date: date_class
    close_price: Optional[float] = None
    return_pct: Optional[float] = None
    benchmark_close: Optional[float] = None
    benchmark_return_pct: Optional[float] = None


class SignalReturnEventPoint(BaseModel):
    """收益率关键事件点"""
    key: str
    label: str
    trade_date: date_class
    price: Optional[float] = None
    return_pct: Optional[float] = None
    benchmark_return_pct: Optional[float] = None


class SignalReturnBenchmark(BaseModel):
    """收益率对照基准"""
    name: str
    ts_code: str
    base_date: date_class
    base_close: Optional[float] = None


class SignalReturnItem(BaseModel):
    """单个股票的收益率数据"""
    code: str
    name: Optional[str] = None
    pick_date: date_class  # 信号日期
    buy_date: date_class  # 买入日期（下一个交易日）
    buy_price: Optional[float] = None  # 买入价格（开盘价）
    day5_return: Optional[float] = None  # 5日收益率
    day10_return: Optional[float] = None  # 10日收益率
    day15_return: Optional[float] = None  # 15日收益率
    current_return: Optional[float] = None  # 至今收益率
    max_return: Optional[float] = None  # 最大收益率
    max_return_date: Optional[date_class] = None  # 最大收益率日期
    max_loss: Optional[float] = None  # 最大亏损（负值表示亏损）
    max_loss_date: Optional[date_class] = None  # 最大亏损日期
    fail_return: Optional[float] = None  # 转fail后次日开盘价卖出的收益率
    fail_date: Optional[date_class] = None  # 转fail的日期
    fail_sell_date: Optional[date_class] = None  # 实际卖出日期（fail次日）
    current_price: Optional[float] = None  # 当前价格
    timeline: List[SignalReturnTimelinePoint] = Field(default_factory=list)
    events: List[SignalReturnEventPoint] = Field(default_factory=list)


class SignalReturnAnalysisResponse(BaseModel):
    """历史信号收益率分析响应"""
    pick_date: date_class  # 信号日期
    signal_type: str  # "trend_start" | "tomorrow_star"
    signal_label: str  # "启动" | "明日之星"
    source: str  # "tomorrow_star" | "current_hot"
    benchmark: Optional[SignalReturnBenchmark] = None
    stocks: List[SignalReturnItem]
    total: int
    avg_day5_return: Optional[float] = None
    avg_day10_return: Optional[float] = None
    avg_day15_return: Optional[float] = None
    avg_current_return: Optional[float] = None


# ==================== 概念板块相关 ====================
class CurrentHotAggregateResponse(BaseModel):
    """当前热盘聚合首屏响应，一次返回前端所需全部数据。"""
    # 历史摘要
    dates: List[str] = Field(default_factory=list)
    history: List[CurrentHotHistoryItem] = Field(default_factory=list)
    latest_date: Optional[date_class] = None
    # 候选列表
    candidates: List[CurrentHotCandidateItem] = Field(default_factory=list)
    candidates_total: int = 0
    # 分析结果
    results: List[CurrentHotAnalysisItem] = Field(default_factory=list)
    results_total: int = 0
    min_score_threshold: float = 4.0
    # 板块分析
    sectors: List[CurrentHotSectorSummaryItem] = Field(default_factory=list)
    sector_top_keys: List[str] = Field(default_factory=list)
    sector_dates: List[str] = Field(default_factory=list)
    sector_history: List[CurrentHotSectorHistorySeries] = Field(default_factory=list)
    sector_latest_date: Optional[date_class] = None
    sector_previous_date: Optional[date_class] = None
    sector_window_size: int = 0
    # 风险环境
    risk_regime: Optional[RiskRegimeSummary] = None
    # 元信息
    pick_date: Optional[date_class] = None
    generated_at: Optional[str] = None
    cache_hit: bool = False


class ConceptInfo(BaseModel):
    """概念板块信息"""
    concept_code: str
    concept_name: str
    concept_type: Optional[str] = None
    start_date: Optional[str] = None


class ConceptsResponse(BaseModel):
    """概念板块列表响应"""
    concepts: List[ConceptInfo]
    total: int


class StockConceptItem(BaseModel):
    """股票概念板块项"""
    ts_code: str
    code: str
    concepts: List[str] = Field(default_factory=list)


class StockConceptsResponse(BaseModel):
    """股票概念板块响应"""
    stocks: Dict[str, List[str]]  # code -> concepts
    total: int


class ConceptMembersResponse(BaseModel):
    """概念板块成分股响应"""
    concept_code: str
    concept_name: Optional[str] = None
    members: List[Dict[str, Any]]
    total: int


class CustomConceptRunItem(BaseModel):
    """自定义概念运行记录"""
    id: int
    status: str
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_version: str
    candidate_count: int = 0
    matched_stock_count: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


class OfficialConceptMatchItem(BaseModel):
    """召回命中的官方概念板块"""
    concept_code: str
    concept_name: str
    score: int
    matched_terms: List[str] = Field(default_factory=list)


class CustomConceptUpsertRequest(BaseModel):
    """创建或更新自定义概念"""
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = None
    chain_hint: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    related_sectors: List[str] = Field(default_factory=list)
    status: str = "draft"


class CustomConceptSummaryItem(BaseModel):
    """自定义概念摘要"""
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    chain_hint: Optional[str] = None
    status: str
    prompt_version: str
    aliases: List[str] = Field(default_factory=list)
    related_sectors: List[str] = Field(default_factory=list)
    tag_count: int = 0
    last_refreshed_at: Optional[datetime] = None
    updated_at: datetime
    latest_run: Optional[CustomConceptRunItem] = None


class CustomConceptListResponse(BaseModel):
    """自定义概念列表"""
    concepts: List[CustomConceptSummaryItem]
    total: int


class CustomConceptDetailResponse(CustomConceptSummaryItem):
    """自定义概念详情"""
    recent_runs: List[CustomConceptRunItem] = Field(default_factory=list)


class CustomConceptStockTagItem(BaseModel):
    """自定义概念股票标签"""
    stock_code: str
    stock_name: Optional[str] = None
    industry: Optional[str] = None
    relevance_score: Optional[float] = None
    confidence: Optional[float] = None
    chain_position: str
    role_tags: List[str] = Field(default_factory=list)
    reason: Optional[str] = None
    matched_source_concepts: List[str] = Field(default_factory=list)
    updated_at: datetime


class CustomConceptStockTagsResponse(BaseModel):
    """自定义概念股票标签列表"""
    concept_id: int
    concept_name: str
    stocks: List[CustomConceptStockTagItem]
    total: int


class StockCustomConceptItem(BaseModel):
    """单只股票关联的自定义概念"""
    concept_id: int
    concept_name: str
    concept_display_name: str
    relevance_score: Optional[float] = None
    confidence: Optional[float] = None
    chain_position: str
    role_tags: List[str] = Field(default_factory=list)
    reason: Optional[str] = None
    updated_at: datetime


class StockCustomConceptsResponse(BaseModel):
    """单只股票关联的自定义概念列表"""
    code: str
    concepts: List[StockCustomConceptItem]
    total: int


class CustomConceptRefreshResponse(BaseModel):
    """自定义概念刷新结果"""
    concept_id: int
    concept_name: str
    run: CustomConceptRunItem
    official_matches: List[OfficialConceptMatchItem] = Field(default_factory=list)
    stocks_saved: int = 0
    concept_summary: Optional[str] = None
    industry_chain_definition: Optional[str] = None


class CandidateConceptMatchRequestItem(BaseModel):
    """候选股票概念匹配输入项"""
    code: str
    name: Optional[str] = None
    industry: Optional[str] = None
    sector_names: List[str] = Field(default_factory=list)
    signal_type: Optional[str] = None
    total_score: Optional[float] = None
    comment: Optional[str] = None


class CandidateConceptMatchRequest(BaseModel):
    """候选股票概念匹配请求"""
    query: str
    candidates: List[CandidateConceptMatchRequestItem] = Field(default_factory=list)
    force_refresh: bool = False
    async_refresh: bool = False


class CandidateConceptMatchItem(BaseModel):
    """候选股票概念匹配结果"""
    code: str
    name: Optional[str] = None
    industry: Optional[str] = None
    relevance_score: Optional[float] = None
    confidence: Optional[float] = None
    chain_position: str
    role_tags: List[str] = Field(default_factory=list)
    reason: Optional[str] = None


class CandidateConceptMatchResponse(BaseModel):
    """候选股票概念匹配响应"""
    query: str
    concept_id: int
    concept_name: str
    cache_hit: bool = False
    source: str
    data_updated_at: Optional[datetime] = None
    refresh_scheduled: bool = False
    total_candidates: int
    matched_count: int
    matches: List[CandidateConceptMatchItem] = Field(default_factory=list)


class ConceptQuerySuggestionItem(BaseModel):
    """概念检索历史联想项"""
    query: str
    label: str
    source: str
    updated_at: Optional[datetime] = None


class ConceptQuerySuggestionsResponse(BaseModel):
    """概念检索历史联想响应"""
    items: List[ConceptQuerySuggestionItem] = Field(default_factory=list)
    total: int


class ConceptMemoryEntryItem(BaseModel):
    """概念记忆库条目"""
    id: int
    keyword: str
    title: str
    content: str
    category: Optional[str] = None
    source_type: str
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    status: str
    priority: int
    is_fixed: bool
    tags: List[str] = Field(default_factory=list)
    related_stock_codes: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    prompt_version: Optional[str] = None
    last_refreshed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ConceptMemoryRunItem(BaseModel):
    """概念记忆库运行记录"""
    id: int
    entry_id: Optional[int] = None
    run_type: str
    query_text: Optional[str] = None
    status: str
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    matched_entry_count: int = 0
    matched_news_count: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


class ConceptMemoryUpsertRequest(BaseModel):
    """概念记忆库条目保存请求"""
    keyword: str
    title: str
    content: str
    category: Optional[str] = None
    source_type: str = "manual"
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    status: str = "draft"
    priority: int = 0
    is_fixed: bool = False
    tags: List[str] = Field(default_factory=list)
    related_stock_codes: List[str] = Field(default_factory=list)


class ConceptMemoryListResponse(BaseModel):
    """概念记忆库列表响应"""
    entries: List[ConceptMemoryEntryItem] = Field(default_factory=list)
    total: int = 0
    stats: Dict[str, Any] = Field(default_factory=dict)


class ConceptMemoryDetailResponse(ConceptMemoryEntryItem):
    """概念记忆库详情响应"""
    recent_runs: List[ConceptMemoryRunItem] = Field(default_factory=list)


class ConceptMemoryRefreshResponse(BaseModel):
    """概念记忆库刷新响应"""
    entry_id: int
    keyword: str
    run: ConceptMemoryRunItem
    matched_news_count: int = 0
    matched_official_concepts: List[dict[str, Any]] = Field(default_factory=list)
    matched_memory_entries: List[dict[str, Any]] = Field(default_factory=list)
    ai_summary: Optional[str] = None
    ai_keywords: List[str] = Field(default_factory=list)
    ai_related_stock_codes: List[str] = Field(default_factory=list)


class ConceptMemoryComposeRequest(BaseModel):
    """概念记忆库上下文组装请求"""
    query: str
    use_ai: bool = True
    force_refresh: bool = False
    max_entries: int = 8
    max_news: int = 10


class ConceptMemoryComposeResponse(BaseModel):
    """概念记忆库上下文组装响应"""
    query: str
    cache_hit: bool = False
    source: str
    context_text: str
    matched_entries: List[ConceptMemoryEntryItem] = Field(default_factory=list)
    matched_news: List[Dict[str, Any]] = Field(default_factory=list)
    matched_official_concepts: List[Dict[str, Any]] = Field(default_factory=list)
    ai_result: Optional[Dict[str, Any]] = None
    run: Optional[ConceptMemoryRunItem] = None
