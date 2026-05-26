"""
SQLAlchemy Database Models
~~~~~~~~~~~~~~~~~~~~~~~~~~~
数据库表模型定义
"""
from datetime import date, datetime
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
    consecutive_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
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
    consecutive_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewer: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    strategy_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    window_size: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class IntradayAnalysisSnapshot(Base):
    """中盘分析当日快照表"""
    __tablename__ = "intraday_analysis_snapshots"
    __table_args__ = (
        UniqueConstraint("trade_date", "code", name="uq_intraday_analysis_snapshots_trade_date_code"),
        Index("ix_intraday_analysis_snapshots_trade_date_code", "trade_date", "code"),
        Index("ix_intraday_analysis_snapshots_source_pick_date", "source_pick_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    source_pick_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    b1_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    signal_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    kdj_j: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zx_long_pos: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    weekly_ma_aligned: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    volume_healthy: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ClosingAnalysisReport(Base):
    """收盘分析日报。"""
    __tablename__ = "closing_analysis_reports"
    __table_args__ = (
        UniqueConstraint("trade_date", name="uq_closing_analysis_reports_trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source_data_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    force_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CurrentHotRun(Base):
    """当前热盘按交易日的构建状态表"""
    __tablename__ = "current_hot_runs"
    __table_args__ = (
        UniqueConstraint("pick_date", name="uq_current_hot_runs_pick_date"),
        Index("ix_current_hot_runs_status_pick_date", "status", "pick_date"),
        Index("ix_current_hot_runs_finished_at", "finished_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analysis_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trend_start_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewer: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CurrentHotCandidate(Base):
    """当前热盘股票池表"""
    __tablename__ = "current_hot_candidates"
    __table_args__ = (
        UniqueConstraint("pick_date", "code", name="uq_current_hot_candidates_pick_date_code"),
        Index("ix_current_hot_candidates_pick_date_code", "pick_date", "code"),
        Index("ix_current_hot_candidates_pick_date_board", "pick_date", "board_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    sector_names_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    board_group: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    open_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    b1_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    kdj_j: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    consecutive_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CurrentHotAnalysisResult(Base):
    """当前热盘分析结果表"""
    __tablename__ = "current_hot_analysis_results"
    __table_args__ = (
        UniqueConstraint("pick_date", "code", "reviewer", name="uq_current_hot_analysis_results_pick_date_code_reviewer"),
        Index("ix_current_hot_analysis_results_pick_date_code", "pick_date", "code"),
        Index("ix_current_hot_analysis_results_pick_date_signal_type", "pick_date", "signal_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    b1_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    total_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    signal_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    turnover_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CurrentHotIntradaySnapshot(Base):
    """当前热盘中盘分析快照表"""
    __tablename__ = "current_hot_intraday_snapshots"
    __table_args__ = (
        UniqueConstraint("trade_date", "code", name="uq_current_hot_intraday_snapshots_trade_date_code"),
        Index("ix_current_hot_intraday_snapshots_trade_date_code", "trade_date", "code"),
        Index("ix_current_hot_intraday_snapshots_board_group", "trade_date", "board_group"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    source_pick_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sector_names_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    board_group: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    open_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    high_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    low_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    b1_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    signal_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    kdj_j: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    zx_long_pos: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    weekly_ma_aligned: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    volume_healthy: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class SectorAnalysisRun(Base):
    """板块分析按交易日与板块的构建状态表"""
    __tablename__ = "sector_analysis_runs"
    __table_args__ = (
        UniqueConstraint("pick_date", "sector_key", name="uq_sector_analysis_runs_pick_date_sector"),
        Index("ix_sector_analysis_runs_status_pick_date", "status", "pick_date"),
        Index("ix_sector_analysis_runs_pick_date_sector", "pick_date", "sector_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    sector_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    analysis_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trend_start_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    b1_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewer: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class SectorAnalysisCandidate(Base):
    """板块分析候选表"""
    __tablename__ = "sector_analysis_candidates"
    __table_args__ = (
        UniqueConstraint("pick_date", "sector_key", "code", name="uq_sector_analysis_candidates_pick_date_sector_code"),
        Index("ix_sector_analysis_candidates_pick_date_sector", "pick_date", "sector_key"),
        Index("ix_sector_analysis_candidates_pick_date_code", "pick_date", "code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    sector_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    sector_names_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    board_group: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    open_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    change_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    b1_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    kdj_j: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SectorAnalysisResult(Base):
    """板块分析评分结果表"""
    __tablename__ = "sector_analysis_results"
    __table_args__ = (
        UniqueConstraint(
            "pick_date",
            "sector_key",
            "code",
            "reviewer",
            name="uq_sector_analysis_results_pick_date_sector_code_reviewer",
        ),
        Index("ix_sector_analysis_results_pick_date_sector", "pick_date", "sector_key"),
        Index("ix_sector_analysis_results_pick_date_code", "pick_date", "code"),
        Index("ix_sector_analysis_results_pick_date_signal_type", "pick_date", "signal_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pick_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    sector_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    reviewer: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    b1_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    total_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    signal_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    turnover_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CustomConcept(Base):
    """自定义概念定义表"""
    __tablename__ = "custom_concepts"
    __table_args__ = (
        UniqueConstraint("name", name="uq_custom_concepts_name"),
        Index("ix_custom_concepts_status_updated_at", "status", "updated_at"),
        Index("ix_custom_concepts_last_refreshed_at", "last_refreshed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chain_hint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    source_config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CustomConceptAlias(Base):
    """自定义概念别名表"""
    __tablename__ = "custom_concept_aliases"
    __table_args__ = (
        UniqueConstraint("concept_id", "alias", name="uq_custom_concept_aliases_concept_alias"),
        Index("ix_custom_concept_aliases_alias", "alias"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_id: Mapped[int] = mapped_column(Integer, ForeignKey("custom_concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CustomConceptRelatedSector(Base):
    """自定义概念关联官方板块表"""
    __tablename__ = "custom_concept_related_sectors"
    __table_args__ = (
        UniqueConstraint(
            "concept_id",
            "sector_name",
            "sector_source",
            name="uq_custom_concept_related_sectors_concept_name_source",
        ),
        Index("ix_custom_concept_related_sectors_sector_name", "sector_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_id: Mapped[int] = mapped_column(Integer, ForeignKey("custom_concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    sector_source: Mapped[str] = mapped_column(String(32), nullable=False, default="tushare_concept")
    sector_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sector_name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CustomConceptRun(Base):
    """自定义概念 AI 汇聚运行记录表"""
    __tablename__ = "custom_concept_runs"
    __table_args__ = (
        Index("ix_custom_concept_runs_concept_created_at", "concept_id", "created_at"),
        Index("ix_custom_concept_runs_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_id: Mapped[int] = mapped_column(Integer, ForeignKey("custom_concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_context_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class CustomConceptStockTag(Base):
    """自定义概念股票标签表"""
    __tablename__ = "custom_concept_stock_tags"
    __table_args__ = (
        UniqueConstraint("concept_id", "stock_code", name="uq_custom_concept_stock_tags_concept_code"),
        Index("ix_custom_concept_stock_tags_code", "stock_code"),
        Index("ix_custom_concept_stock_tags_chain_position", "concept_id", "chain_position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_id: Mapped[int] = mapped_column(Integer, ForeignKey("custom_concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("custom_concept_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    stock_code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    chain_position: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    role_tags_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")
    is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ConceptMemoryEntry(Base):
    """概念记忆库条目表"""
    __tablename__ = "concept_memory_entries"
    __table_args__ = (
        Index("ix_concept_memory_entries_keyword_updated_at", "keyword", "updated_at"),
        Index("ix_concept_memory_entries_status_updated_at", "status", "updated_at"),
        Index("ix_concept_memory_entries_source_type", "source_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tags_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    related_stock_codes_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ConceptMemoryRun(Base):
    """概念记忆库运行记录表"""
    __tablename__ = "concept_memory_runs"
    __table_args__ = (
        Index("ix_concept_memory_runs_entry_created_at", "entry_id", "created_at"),
        Index("ix_concept_memory_runs_run_type_created_at", "run_type", "created_at"),
        Index("ix_concept_memory_runs_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("concept_memory_entries.id", ondelete="CASCADE"), nullable=True, index=True)
    run_type: Mapped[str] = mapped_column(String(20), nullable=False, default="query")
    query_text: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    input_context_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_news_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class DailyB1Check(Base):
    """每日B1检查表 (单股诊断历史)"""
    __tablename__ = "daily_b1_checks"
    __table_args__ = (
        UniqueConstraint("code", "check_date", name="uq_daily_b1_checks_code_check_date"),
        Index("ix_daily_b1_checks_code_check_date", "code", "check_date"),
        Index("ix_daily_b1_checks_check_date_code", "check_date", "code"),
        Index("ix_daily_b1_checks_signal_type", "b1_signal_type"),
    )

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
    b1_signal_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # old_b1/原始B1/回踩黄线B/回踩超级B
    active_pool_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    turnover_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DailyB1CheckDetail(Base):
    """每日B1检查详情表（持久化规则与评分明细）"""
    __tablename__ = "daily_b1_check_details"
    __table_args__ = (
        UniqueConstraint("code", "check_date", name="uq_daily_b1_check_details_code_check_date"),
        Index("ix_daily_b1_check_details_code_check_date", "code", "check_date"),
        Index("ix_daily_b1_check_details_status_check_date", "status", "check_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    check_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready", index=True)
    detail_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    strategy_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    rule_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    score_details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    rules_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


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
    entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
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
    steps_completed: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=dict)  # 步骤完成状态: {"resetting": true, "fetch_data": false, ...}
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


class RawDataBatch(Base):
    """原始数据批次表

    记录一次按交易日或按区间的抓取批次，供任务中心和状态页读取。
    """
    __tablename__ = "raw_data_batches"
    __table_args__ = (
        Index("ix_raw_data_batches_status_trade_date", "status", "trade_date"),
        Index("ix_raw_data_batches_batch_type_created_at", "batch_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_type: Mapped[str] = mapped_column(String(32), nullable=False, default="daily")
    trade_date: Mapped[Optional[datetime]] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class RawDataManifest(Base):
    """原始数据清单表

    按交易日维护最新的抓取和入库状态，避免接口频繁扫描文件系统。
    """
    __tablename__ = "raw_data_manifest"
    __table_args__ = (
        UniqueConstraint("trade_date", name="uq_raw_data_manifest_trade_date"),
        Index("ix_raw_data_manifest_status_trade_date", "status", "trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    batch_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("raw_data_batches.id"), nullable=True, index=True)
    storage_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db_stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    loaded_to_db_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


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
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
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


class UserSession(Base):
    """用户登录会话表"""
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_id_login_at", "user_id", "login_at"),
        Index("ix_user_sessions_login_at", "login_at"),
        Index("ix_user_sessions_last_activity_at", "last_activity_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    logout_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


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
    turnover_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    turnover_rate_f: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    free_share: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    circ_mv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buy_sm_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sell_sm_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buy_md_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sell_md_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buy_lg_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sell_lg_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buy_elg_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sell_elg_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    net_mf_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StockActivePoolRank(Base):
    """每日活跃池排名因子表。

    该表是 stock_daily 的派生结果，供单股诊断、历史回放等在线接口直接读取，
    避免在用户请求中读取全市场 CSV 并临时重算活跃池。
    """
    __tablename__ = "stock_active_pool_ranks"
    __table_args__ = (
        UniqueConstraint(
            "trade_date",
            "code",
            "top_m",
            "n_turnover_days",
            name="uq_stock_active_pool_ranks_date_code_params",
        ),
        Index("ix_stock_active_pool_ranks_date_rank", "trade_date", "top_m", "n_turnover_days", "active_pool_rank"),
        Index("ix_stock_active_pool_ranks_code_date", "code", "trade_date"),
        Index("ix_stock_active_pool_ranks_code_date_params", "code", "trade_date", "top_m", "n_turnover_days"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), ForeignKey("stocks.code"), nullable=False, index=True)
    top_m: Mapped[int] = mapped_column(Integer, nullable=False, default=3000)
    n_turnover_days: Mapped[int] = mapped_column(Integer, nullable=False, default=43)
    turnover_n: Mapped[float] = mapped_column(Float, nullable=False)
    active_pool_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    in_active_pool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AdminSummaryMetadata(Base):
    """管理员总览元数据缓存表"""
    __tablename__ = "admin_summary_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, comment="缓存的JSON数据")
    version: Mapped[int] = mapped_column(Integer, default=1, comment="版本号，用于乐观锁")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, comment="更新时间")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="过期时间")
