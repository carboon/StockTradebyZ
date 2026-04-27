"""
Test Utility Functions
~~~~~~~~~~~~~~~~~~~~~~
测试工具函数，提供便捷的测试数据创建方法
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    AnalysisResult,
    Candidate,
    DailyB1Check,
    DataUpdateLog,
    Stock,
    Task,
    Watchlist,
    WatchlistAnalysis,
)


def create_test_stock(
    db: Session,
    code: str,
    name: Optional[str] = None,
    market: Optional[str] = "SH",
    industry: Optional[str] = "测试行业",
    commit: bool = True,
) -> Stock:
    """
    创建测试股票数据

    Args:
        db: 数据库会话
        code: 股票代码
        name: 股票名称，默认为 "测试{code}"
        market: 市场代码 (SH/SZ)，默认为 "SH"
        industry: 行业，默认为 "测试行业"
        commit: 是否提交到数据库，默认为 True

    Returns:
        创建的 Stock 对象
    """
    if name is None:
        name = f"测试{code}"

    stock = Stock(
        code=code,
        name=name,
        market=market,
        industry=industry,
    )
    db.add(stock)
    if commit:
        db.commit()
        db.refresh(stock)

    return stock


def create_test_candidate(
    db: Session,
    code: str,
    pick_date: date,
    strategy: Optional[str] = "b1",
    close_price: Optional[float] = 10.5,
    turnover: Optional[float] = 5.2,
    b1_passed: Optional[bool] = True,
    kdj_j: Optional[float] = 15.5,
    commit: bool = True,
) -> Candidate:
    """
    创建测试候选股票数据

    Args:
        db: 数据库会话
        code: 股票代码
        pick_date: 选股日期
        strategy: 策略名称 (b1/brick)，默认为 "b1"
        close_price: 收盘价，默认为 10.5
        turnover: 换手率，默认为 5.2
        b1_passed: B1筛选是否通过，默认为 True
        kdj_j: KDJ指标J值，默认为 15.5
        commit: 是否提交到数据库，默认为 True

    Returns:
        创建的 Candidate 对象
    """
    # 确保股票存在
    stock = db.query(Stock).filter(Stock.code == code).first()
    if stock is None:
        create_test_stock(db, code, commit=False)

    candidate = Candidate(
        pick_date=pick_date,
        code=code,
        strategy=strategy,
        close_price=close_price,
        turnover=turnover,
        b1_passed=b1_passed,
        kdj_j=kdj_j,
    )
    db.add(candidate)
    if commit:
        db.commit()
        db.refresh(candidate)

    return candidate


def create_test_analysis_result(
    db: Session,
    code: str,
    pick_date: date,
    reviewer: Optional[str] = "quant",
    verdict: Optional[str] = "PASS",
    total_score: Optional[float] = 8.5,
    signal_type: Optional[str] = "突破",
    comment: Optional[str] = "测试分析结果",
    details_json: Optional[dict] = None,
    commit: bool = True,
) -> AnalysisResult:
    """
    创建测试分析结果数据

    Args:
        db: 数据库会话
        code: 股票代码
        pick_date: 选股日期
        reviewer: 分析者 (quant/glm/qwen/gemini)，默认为 "quant"
        verdict: 分析结论 (PASS/WATCH/FAIL)，默认为 "PASS"
        total_score: 总分，默认为 8.5
        signal_type: 信号类型，默认为 "突破"
        comment: 评论，默认为 "测试分析结果"
        details_json: 详细信息 JSON，默认为 None
        commit: 是否提交到数据库，默认为 True

    Returns:
        创建的 AnalysisResult 对象
    """
    # 确保股票和候选记录存在
    stock = db.query(Stock).filter(Stock.code == code).first()
    if stock is None:
        create_test_stock(db, code, commit=False)

    candidate = db.query(Candidate).filter(
        Candidate.code == code,
        Candidate.pick_date == pick_date,
    ).first()
    if candidate is None:
        create_test_candidate(db, code, pick_date, commit=False)

    if details_json is None:
        details_json = {
            "score_breakdown": {
                "trend": 8.0,
                "volume": 9.0,
                "technical": 8.5,
            }
        }

    analysis_result = AnalysisResult(
        pick_date=pick_date,
        code=code,
        reviewer=reviewer,
        verdict=verdict,
        total_score=total_score,
        signal_type=signal_type,
        comment=comment,
        details_json=details_json,
    )
    db.add(analysis_result)
    if commit:
        db.commit()
        db.refresh(analysis_result)

    return analysis_result


def create_test_watchlist_item(
    db: Session,
    code: str,
    add_reason: Optional[str] = "测试原因",
    entry_price: Optional[float] = None,
    position_ratio: Optional[float] = None,
    priority: int = 0,
    is_active: bool = True,
    commit: bool = True,
) -> Watchlist:
    """
    创建测试观察项数据

    Args:
        db: 数据库会话
        code: 股票代码
        add_reason: 添加原因，默认为 "测试原因"
        priority: 优先级，默认为 0
        is_active: 是否激活，默认为 True
        commit: 是否提交到数据库，默认为 True

    Returns:
        创建的 Watchlist 对象
    """
    # 确保股票存在
    stock = db.query(Stock).filter(Stock.code == code).first()
    if stock is None:
        create_test_stock(db, code, commit=False)

    watchlist_item = Watchlist(
        code=code,
        add_reason=add_reason,
        entry_price=entry_price,
        position_ratio=position_ratio,
        priority=priority,
        is_active=is_active,
    )
    db.add(watchlist_item)
    if commit:
        db.commit()
        db.refresh(watchlist_item)

    return watchlist_item


def create_test_daily_b1_check(
    db: Session,
    code: str,
    check_date: date,
    close_price: Optional[float] = 10.5,
    change_pct: Optional[float] = 2.5,
    kdj_j: Optional[float] = 15.5,
    kdj_low_rank: Optional[float] = 10.0,
    zx_long_pos: Optional[bool] = True,
    weekly_ma_aligned: Optional[bool] = True,
    volume_healthy: Optional[bool] = True,
    b1_passed: Optional[bool] = True,
    score: Optional[float] = 85.0,
    notes: Optional[str] = "测试检查记录",
    commit: bool = True,
) -> DailyB1Check:
    """
    创建测试每日B1检查数据

    Args:
        db: 数据库会话
        code: 股票代码
        check_date: 检查日期
        close_price: 收盘价
        change_pct: 涨跌幅百分比
        kdj_j: KDJ指标J值
        kdj_low_rank: KDJ低位排名
        zx_long_pos: 中信长线仓位
        weekly_ma_aligned: 周线均线是否对齐
        volume_healthy: 成交量是否健康
        b1_passed: B1筛选是否通过
        score: 得分
        notes: 备注
        commit: 是否提交到数据库

    Returns:
        创建的 DailyB1Check 对象
    """
    # 确保股票存在
    stock = db.query(Stock).filter(Stock.code == code).first()
    if stock is None:
        create_test_stock(db, code, commit=False)

    check = DailyB1Check(
        code=code,
        check_date=check_date,
        close_price=close_price,
        change_pct=change_pct,
        kdj_j=kdj_j,
        kdj_low_rank=kdj_low_rank,
        zx_long_pos=zx_long_pos,
        weekly_ma_aligned=weekly_ma_aligned,
        volume_healthy=volume_healthy,
        b1_passed=b1_passed,
        score=score,
        notes=notes,
    )
    db.add(check)
    if commit:
        db.commit()
        db.refresh(check)

    return check


def create_test_task(
    db: Session,
    task_type: str = "full_update",
    status: str = "pending",
    params_json: Optional[dict] = None,
    progress: int = 0,
    result_json: Optional[dict] = None,
    error_message: Optional[str] = None,
    commit: bool = True,
) -> Task:
    """
    创建测试后台任务数据

    Args:
        db: 数据库会话
        task_type: 任务类型 (full_update/single_analysis)
        status: 任务状态 (pending/running/completed/failed)
        params_json: 参数 JSON
        progress: 进度 0-100
        result_json: 结果 JSON
        error_message: 错误信息
        commit: 是否提交到数据库

    Returns:
        创建的 Task 对象
    """
    if params_json is None:
        params_json = {}

    task = Task(
        task_type=task_type,
        status=status,
        params_json=params_json,
        progress=progress,
        result_json=result_json,
        error_message=error_message,
    )
    db.add(task)
    if commit:
        db.commit()
        db.refresh(task)

    return task


def create_test_data_update_log(
    db: Session,
    update_date: date,
    raw_data_count: Optional[int] = 100,
    candidates_count: Optional[int] = 10,
    analysis_count: Optional[int] = 5,
    status: Optional[str] = "completed",
    duration_seconds: Optional[int] = 300,
    notes: Optional[str] = "测试更新日志",
    commit: bool = True,
) -> DataUpdateLog:
    """
    创建测试数据更新记录

    Args:
        db: 数据库会话
        update_date: 更新日期
        raw_data_count: 原始数据数量
        candidates_count: 候选股票数量
        analysis_count: 分析数量
        status: 状态
        duration_seconds: 耗时（秒）
        notes: 备注
        commit: 是否提交到数据库

    Returns:
        创建的 DataUpdateLog 对象
    """
    log = DataUpdateLog(
        update_date=update_date,
        raw_data_count=raw_data_count,
        candidates_count=candidates_count,
        analysis_count=analysis_count,
        status=status,
        duration_seconds=duration_seconds,
        notes=notes,
    )
    db.add(log)
    if commit:
        db.commit()
        db.refresh(log)

    return log
