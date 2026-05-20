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


# ==================== 候选股票 ====================
class CandidateItem(BaseModel):
    """候选股票项"""
    id: int
    pick_date: date_class
    code: str
    name: Optional[str] = None
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
    consecutive_days: int = 1


class CurrentHotCandidatesResponse(BaseModel):
    """当前热盘股票池响应"""
    pick_date: Optional[date_class] = None
    candidates: List[CurrentHotCandidateItem]
    total: int


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
    pullback_quality: Optional[str] = None
    pullback_negative_flags: Optional[List[str]] = None


class CurrentHotAnalysisResultResponse(BaseModel):
    """当前热盘分析结果响应"""
    pick_date: Optional[date_class] = None
    results: List[CurrentHotAnalysisItem]
    total: int
    min_score_threshold: float


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
    kline_data: Optional[Dict[str, Any]] = None


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


class UserListItem(BaseModel):
    """用户列表项（管理员用）"""
    id: int
    username: str
    display_name: str | None
    role: str
    is_active: bool
    daily_quota: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
