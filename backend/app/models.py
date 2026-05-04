"""
SQLAlchemy Database Models
~~~~~~~~~~~~~~~~~~~~~~~~~~~
数据库表模型定义
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.time_utils import utc_now


class Config(Base):
    """配置表"""
    __tablename__ = "configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Stock(Base):
    """股票基本信息表"""
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    market: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # SH/SZ
    industry: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Candidate(Base):
    """候选股票表 (明日之星)"""
    __tablename__ = "candidates"
    __table_args__ = (
        UniqueConstraint("pick_date", "code", name="uq_candidates_pick_date_code"),
        Index("ix_candidates_pick_date_code", "pick_date", "code"),
        Index("ix_candidates_pick_date_id", "pick_date", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # b1/brick
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    b1_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    kdj_j: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AnalysisResult(Base):
    """分析结果表"""
    __tablename__ = "analysis_results"
    __table_args__ = (
        UniqueConstraint("pick_date", "code", "reviewer", name="uq_analysis_results_pick_date_code_reviewer"),
        Index("ix_analysis_results_pick_date_code", "pick_date", "code"),
        Index("ix_analysis_results_pick_date_signal_type", "pick_date", "signal_type"),
        Index("ix_analysis_results_pick_date_reviewer", "pick_date", "reviewer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # quant/glm/qwen/gemini
    verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # PASS/WATCH/FAIL
    total_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    signal_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TomorrowStarRun(Base):
    """明日之星按交易日的构建状态表"""
    __tablename__ = "tomorrow_star_runs"
    __table_args__ = (
        UniqueConstraint("pick_date", name="uq_tomorrow_star_runs_pick_date"),
        Index("ix_tomorrow_star_runs_status_pick_date", "status", "pick_date"),
        Index("ix_tomorrow_star_runs_finished_at", "finished_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analysis_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trend_start_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewer: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    strategy_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    window_size: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class DailyB1Check(Base):
    """每日B1检查表 (单股诊断历史)"""
    __tablename__ = "daily_b1_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    check_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    kdj_j: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    kdj_low_rank: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zx_long_pos: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    weekly_ma_aligned: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    volume_healthy: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    b1_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Watchlist(Base):
    """重点观察表"""
    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "code", name="uq_watchlist_user_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    add_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StockAnalysis(Base):
    """公共分析结果表（共享分析结果，支持多用户复用）"""
    __tablename__ = "stock_analysis"
    __table_args__ = (
        UniqueConstraint("code", "trade_date", "analysis_type", "strategy_version", name="uq_stock_analysis_unique"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    trade_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    analysis_type: Mapped[str] = mapped_column(String(20), nullable=False, default="daily_b1")  # daily_b1/brick etc.
    strategy_version: Mapped[str] = mapped_column(String(10), nullable=False, default="v1")

    # 公共分析结果字段
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # PASS/WATCH/FAIL
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    signal_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # trend_start/distribution_risk
    b1_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    kdj_j: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zx_long_pos: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    weekly_ma_aligned: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    volume_healthy: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # 详细分析数据（JSON）
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 元数据
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class WatchlistAnalysis(Base):
    """观察股票分析历史表（已废弃，保留用于兼容历史数据）
    新逻辑使用 StockAnalysis 表存储公共结果，通过 watchlist 表的用户配置动态拼装
    """
    __tablename__ = "watchlist_analysis"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "analysis_date", name="uq_watchlist_analysis_watchlist_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(Integer, ForeignKey("watchlist.id"), nullable=False, index=True)
    analysis_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trend_outlook: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # bullish/bearish/neutral
    buy_action: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    hold_action: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    buy_recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hold_recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    support_level: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    resistance_level: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Task(Base):
    """后台任务表"""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)  # full_update/single_analysis
    trigger_source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/running/completed/failed
    task_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    params_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    progress_meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    @classmethod
    def filter_by_code(cls, code: str):
        """构建过滤 params_json 中 code 字段的查询条件。

        Args:
            code: 股票代码

        Returns:
            可用于 filter() 的查询表达式
        """
        # SQLAlchemy 2.x 中使用 as_string() 替代 astext
        return cls.params_json["code"].as_string() == code


class TaskLog(Base):
    """任务日志表"""
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    log_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class DataUpdateLog(Base):
    """数据更新记录表"""
    __tablename__ = "data_update_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    update_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    raw_data_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    candidates_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    analysis_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")  # admin / user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_quota: Mapped[int] = mapped_column(Integer, default=1000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ApiKey(Base):
    """API Key 表"""
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UsageLog(Base):
    """API 调用日志表"""
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    api_key_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class AuditLog(Base):
    """审计日志表"""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class StockDaily(Base):
    """股票日线行情表（K线数据入库）"""
    __tablename__ = "stock_daily"
    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uq_stock_daily_code_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    trade_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
