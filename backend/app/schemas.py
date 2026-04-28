"""
Pydantic Schemas
~~~~~~~~~~~~~~~~
API 请求和响应数据模型
"""
from datetime import date as date_class
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


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
    b1_passed: Optional[bool] = None
    kdj_j: Optional[float] = None


class CandidatesResponse(BaseModel):
    """候选列表响应"""
    pick_date: Optional[date_class] = None
    candidates: List[CandidateItem]
    total: int


# ==================== 分析结果 ====================
class AnalysisItem(BaseModel):
    """分析结果项"""
    id: int
    pick_date: date_class
    code: str
    reviewer: Optional[str] = None
    verdict: Optional[str] = None  # PASS/WATCH/FAIL
    total_score: Optional[float] = None
    signal_type: Optional[str] = None
    comment: Optional[str] = None


class AnalysisResultResponse(BaseModel):
    """分析结果响应"""
    pick_date: Optional[date_class] = None
    results: List[AnalysisItem]
    total: int
    min_score_threshold: float


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
    b1_passed: Optional[bool] = None
    score: Optional[float] = None
    verdict: Optional[str] = None
    signal_type: Optional[str] = None
    notes: Optional[str] = None


class DiagnosisHistoryResponse(BaseModel):
    """诊断历史响应"""
    code: str
    name: Optional[str] = None
    history: List[B1CheckItem]
    total: int


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
class WatchlistItem(BaseModel):
    """观察列表项"""
    id: int
    code: str
    name: Optional[str] = None
    add_reason: Optional[str] = None
    entry_price: Optional[float] = None
    position_ratio: Optional[float] = None
    priority: int
    is_active: bool
    added_at: datetime


class WatchlistAddRequest(BaseModel):
    """添加到观察列表"""
    code: str
    reason: Optional[str] = None
    entry_price: Optional[float] = None
    position_ratio: Optional[float] = None
    priority: int = 0


class WatchlistUpdateRequest(BaseModel):
    """更新观察项"""
    reason: Optional[str] = None
    entry_price: Optional[float] = None
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
    raw_data: Dict[str, Any]  # {exists: bool, count: int, latest_date: str}
    candidates: Dict[str, Any]  # {exists: bool, count: int, latest_date: str}
    analysis: Dict[str, Any]  # {exists: bool, count: int, latest_date: str}
    kline: Dict[str, Any]  # {exists: bool, count: int, latest_date: str}


class UpdateStartRequest(BaseModel):
    """启动更新请求"""
    reviewer: str = "quant"
    skip_fetch: bool = False
    start_from: int = 1


# ==================== K线数据 ====================
class KLineDataRequest(BaseModel):
    """K线数据请求"""
    code: str
    days: int = 120
    include_weekly: bool = True


class KLineDataPoint(BaseModel):
    """K线数据点"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
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
