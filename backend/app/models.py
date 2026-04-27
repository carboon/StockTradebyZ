"""
SQLAlchemy Database Models
~~~~~~~~~~~~~~~~~~~~~~~~~~~
数据库表模型定义
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, JSON, UniqueConstraint
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, unique=True)
    add_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    position_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WatchlistAnalysis(Base):
    """观察股票分析历史表"""
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
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
