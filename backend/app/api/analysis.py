"""
Analysis API
~~~~~~~~~~~~
分析相关 API (明日之星、单股诊断)

阶段5改造：长任务统一通过TaskService管理，不再使用BackgroundTasks。
"""
import json
import os
import math
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.cache_decorators import (
    build_candidates_cache_key,
    build_freshness_cache_key,
)
from app.api.deps import require_user
from app.api.rate_limit import single_analysis_rate_limit, history_generation_rate_limit
from app.api.tasks import _cleanup_stale_active_tasks, _raise_initialization_in_progress
from app.cache import cache
from app.database import get_db
from app.models import Candidate, AnalysisResult, DailyB1Check, DailyB1CheckDetail, Stock, Task
from app.services.analysis_service import analysis_service
from app.services.task_service import TaskService
from app.services.tomorrow_star_window_service import TomorrowStarWindowService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now
from app.schemas import (
    CandidatesResponse,
    CandidateItem,
    AnalysisResultResponse,
    AnalysisItem,
    TomorrowStarDatesResponse,
    TomorrowStarHistoryItem,
    TomorrowStarWindowStatusResponse,
    DiagnosisHistoryResponse,
    DiagnosisHistoryDetailResponse,
    B1CheckItem,
    DiagnosisRequest,
    DiagnosisResponse,
)

router = APIRouter()

ROOT = Path(__file__).parent.parent.parent.parent


def _safe_json_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def ensure_tushare_ready() -> None:
    service = TushareService()
    valid, message = service.verify_token()
    if not valid:
        raise HTTPException(status_code=503, detail=f"Tushare 未就绪: {message}")


@router.get("/tomorrow-star/dates", response_model=TomorrowStarDatesResponse)
async def get_tomorrow_star_dates(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> TomorrowStarDatesResponse:
    """获取明日之星历史日期列表"""
    summary = TomorrowStarWindowService(db).get_window_status(window_size=180)
    history_items = [
        TomorrowStarHistoryItem(
            pick_date=datetime.strptime(item["pick_date"], "%Y-%m-%d").date(),
            date=item["date"],
            count=int(item.get("count", 0) or 0),
            pass_count=int(item.get("pass_count", 0) or 0),
            candidate_count=int(item.get("candidate_count", 0) or 0),
            analysis_count=int(item.get("analysis_count", 0) or 0),
            trend_start_count=int(item.get("trend_start_count", 0) or 0),
            status=item.get("status") or "missing",
            error_message=item.get("error_message"),
            is_latest=bool(item.get("is_latest")),
        )
        for item in summary.items
    ]
    return TomorrowStarDatesResponse(
        dates=[item.date for item in history_items],
        history=history_items,
        window_status=TomorrowStarWindowStatusResponse(
            window_size=summary.window_size,
            latest_date=datetime.strptime(summary.latest_date, "%Y-%m-%d").date() if summary.latest_date else None,
            ready_count=summary.ready_count,
            missing_count=summary.missing_count,
            running_count=summary.running_count,
            failed_count=summary.failed_count,
            pending_count=summary.pending_count,
            has_running_task=False,
            running_task_id=None,
            items=history_items,
            history=history_items,
        ),
    )


@router.get("/tomorrow-star/window-status", response_model=TomorrowStarWindowStatusResponse)
async def get_tomorrow_star_window_status(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> TomorrowStarWindowStatusResponse:
    summary = TomorrowStarWindowService(db).get_window_status(window_size=180)
    history_items = [
        TomorrowStarHistoryItem(
            pick_date=datetime.strptime(item["pick_date"], "%Y-%m-%d").date(),
            date=item["date"],
            count=int(item.get("count", 0) or 0),
            pass_count=int(item.get("pass_count", 0) or 0),
            candidate_count=int(item.get("candidate_count", 0) or 0),
            analysis_count=int(item.get("analysis_count", 0) or 0),
            trend_start_count=int(item.get("trend_start_count", 0) or 0),
            status=item.get("status") or "missing",
            error_message=item.get("error_message"),
            is_latest=bool(item.get("is_latest")),
        )
        for item in summary.items
    ]
    return TomorrowStarWindowStatusResponse(
        window_size=summary.window_size,
        latest_date=datetime.strptime(summary.latest_date, "%Y-%m-%d").date() if summary.latest_date else None,
        ready_count=summary.ready_count,
        missing_count=summary.missing_count,
        running_count=summary.running_count,
        failed_count=summary.failed_count,
        pending_count=summary.pending_count,
        has_running_task=False,
        running_task_id=None,
        items=history_items,
        history=history_items,
    )


@router.get("/tomorrow-star/freshness")
async def get_tomorrow_star_freshness(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """获取明日之星数据新鲜度状态。"""
    from app.services.market_service import market_service, MarketService

    _cleanup_stale_active_tasks(db)

    cache_key = build_freshness_cache_key()
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    latest_trade_date = market_service.get_latest_trade_date() if market_service.token else None
    latest_trade_data_ready = (
        TushareService().is_trade_date_data_ready(latest_trade_date)
        if latest_trade_date and market_service.token
        else None
    )
    local_latest_date = market_service.get_local_latest_date()
    latest_candidate_date = analysis_service.get_latest_candidate_date()
    latest_result_date = analysis_service.get_latest_result_date()

    running_task = (
        db.query(Task)
        .filter(
            Task.task_type.in_(["tomorrow_star", "full_update"]),
            Task.status.in_(["pending", "running"]),
        )
        .order_by(Task.created_at.desc())
        .first()
    )

    # 获取增量更新状态
    incremental_state = MarketService.get_update_state()

    needs_update = bool(
        latest_trade_date and (
            local_latest_date != latest_trade_date
            or latest_candidate_date != latest_trade_date
            or latest_result_date != latest_trade_date
        )
    )

    freshness_version = "|".join([
        str(latest_trade_date or ""),
        str(local_latest_date or ""),
        str(latest_candidate_date or ""),
        str(latest_result_date or ""),
        str(latest_trade_data_ready),
        str(running_task.id if running_task else ""),
        str(running_task.status if running_task else ""),
        str(incremental_state.get("running", False)),
        str(incremental_state.get("progress", 0)),
    ])

    result = {
        "latest_trade_date": latest_trade_date,
        "latest_trade_data_ready": latest_trade_data_ready,
        "local_latest_date": local_latest_date,
        "latest_candidate_date": latest_candidate_date,
        "latest_result_date": latest_result_date,
        "needs_update": needs_update,
        "freshness_version": freshness_version,
        "running_task_id": running_task.id if running_task else None,
        "running_task_status": running_task.status if running_task else None,
        "incremental_update": {
            "status": incremental_state.get("status", "idle"),
            "running": incremental_state.get("running", False),
            "progress": incremental_state.get("progress", 0),
            "current": incremental_state.get("current", 0),
            "total": incremental_state.get("total", 0),
            "current_code": incremental_state.get("current_code"),
            "updated_count": incremental_state.get("updated_count", 0),
            "skipped_count": incremental_state.get("skipped_count", 0),
            "failed_count": incremental_state.get("failed_count", 0),
            "started_at": incremental_state.get("started_at"),
            "completed_at": incremental_state.get("completed_at"),
            "eta_seconds": incremental_state.get("eta_seconds"),
            "elapsed_seconds": incremental_state.get("elapsed_seconds", 0),
            "resume_supported": incremental_state.get("resume_supported", True),
            "initial_completed": incremental_state.get("initial_completed", 0),
            "completed_in_run": incremental_state.get("completed_in_run", 0),
            "checkpoint_path": incremental_state.get("checkpoint_path"),
            "last_error": incremental_state.get("last_error"),
            "message": incremental_state.get("message", ""),
        },
    }
    cache.set(cache_key, result, ttl=60)
    return result


@router.get("/tomorrow-star/candidates", response_model=CandidatesResponse)
async def get_candidates(
    date: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CandidatesResponse:
    """获取候选股票列表（只读数据库持久化结果）"""
    from app.services.candidate_service import CandidateService
    import pandas as pd

    requested_date = analysis_service._normalize_pick_date(date)
    cache_key = build_candidates_cache_key(requested_date, limit)
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return CandidatesResponse(**cached_result)

    try:
        persisted_pick_date, persisted_candidates = CandidateService(db).load_candidates(requested_date, limit=limit)
        if persisted_candidates:
            try:
                response_pick_date = pd.Timestamp(persisted_pick_date).date() if persisted_pick_date else None
            except Exception:
                response_pick_date = None

            items = []
            for i, c in enumerate(persisted_candidates[:limit]):
                items.append(
                    CandidateItem(
                        id=i,
                        pick_date=response_pick_date,
                        code=c["code"],
                        name=c.get("name"),
                        strategy=c.get("strategy") or "b1",
                        open_price=c.get("open"),
                        close_price=c.get("close"),
                        change_pct=c.get("change_pct"),
                        turnover=float(c["turnover_n"]) if c.get("turnover_n") is not None else None,
                        b1_passed=c.get("b1_passed"),
                        kdj_j=c.get("kdj_j"),
                    )
                )

            response = CandidatesResponse(
                pick_date=response_pick_date,
                candidates=items,
                total=len(persisted_candidates),
                status="ok",
                message=None,
            )
            cache.set(cache_key, response.model_dump(mode="json"), ttl=180)
            return response

        running_task = (
            db.query(Task)
            .filter(
                Task.task_type.in_(["tomorrow_star", "full_update"]),
                Task.status.in_(["pending", "running"]),
            )
            .order_by(Task.created_at.desc())
            .first()
        )
        response = CandidatesResponse(
            pick_date=pd.Timestamp(requested_date).date() if requested_date else None,
            candidates=[],
            total=0,
            status="not_ready",
            message="候选数据尚未生成，请稍后再试",
            has_running_task=running_task is not None,
            running_task_id=running_task.id if running_task else None,
        )
        cache.set(cache_key, response.model_dump(mode="json"), ttl=30)
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取候选数据失败: {str(e)}")


@router.get("/tomorrow-star/results", response_model=AnalysisResultResponse)
async def get_analysis_results(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> AnalysisResultResponse:
    """获取指定日期的分析结果"""
    normalized_date = analysis_service._normalize_pick_date(date)
    target_date = None
    if normalized_date:
        try:
            target_date = datetime.strptime(normalized_date, "%Y-%m-%d").date()
        except ValueError:
            target_date = None

    if target_date is None:
        latest_pick_date = (
            db.query(AnalysisResult.pick_date)
            .order_by(AnalysisResult.pick_date.desc())
            .limit(1)
            .scalar()
        )
        target_date = latest_pick_date

    if target_date is None:
        return AnalysisResultResponse(
            pick_date=None,
            results=[],
            total=0,
            min_score_threshold=4.0,
        )

    rows = (
        db.query(AnalysisResult)
        .filter(AnalysisResult.pick_date == target_date)
        .order_by(
            AnalysisResult.total_score.desc().nullslast(),
            AnalysisResult.id.asc(),
        )
        .all()
    )

    items = [
        AnalysisItem(
            id=row.id,
            pick_date=target_date,
            code=row.code,
            reviewer=row.reviewer,
            verdict=row.verdict,
            total_score=_safe_json_float(row.total_score),
            signal_type=row.signal_type,
            comment=row.comment,
        )
        for row in rows
    ]

    return AnalysisResultResponse(
        pick_date=target_date,
        results=items,
        total=len(items),
        min_score_threshold=4.0,
    )


@router.get("/diagnosis/{code}/history", response_model=DiagnosisHistoryResponse)
async def get_diagnosis_history(
    code: str,
    days: int = 180,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> DiagnosisHistoryResponse:
    """获取单股诊断历史（只读模式）

    只返回已生成的历史数据，不触发后台生成任务。
    如果历史数据不存在，返回 data_ready=False 状态。
    """
    code = code.zfill(6)
    history = analysis_service.get_stock_history_checks(code, days)
    stock = db.query(Stock).filter(Stock.code == code).first()
    if stock is None:
        try:
            stock = TushareService().sync_stock_to_db(db, code)
        except Exception:
            stock = None

    return DiagnosisHistoryResponse(
        code=code,
        name=stock.name if stock else None,
        history=[B1CheckItem.model_validate(h) for h in history],
        total=len(history),
        data_ready=len(history) > 0,
        message="暂无历史数据，请先执行历史数据生成任务" if len(history) == 0 else None,
    )


@router.post("/diagnosis/{code}/generate-history")
async def generate_diagnosis_history(
    code: str,
    days: int = Query(default=180, description="生成最近N个交易日的历史数据"),
    clean: bool = Query(default=True, description="是否先清理旧数据"),
    _rate_limit: None = Depends(history_generation_rate_limit),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """重新刷新单股诊断历史数据（后台任务模式）

    阶段5改造：
    - 通过任务系统统一管理长任务，不再使用 BackgroundTasks
    - 添加限流约束（2次/小时）
    - 返回任务信息，前端可通过任务ID追踪进度
    """
    from app.main import manager

    ensure_tushare_ready()
    code = code.zfill(6)

    # 创建历史生成任务（阶段5：统一通过任务系统）
    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)
    result = await task_service.create_task(
        "generate_history",
        {
            "code": code,
            "days": days,
            "clean": clean,
            "reviewer": "quant",
            "trigger_source": "manual"
        }
    )

    return {
        "task_id": result["task_id"],
        "code": code,
        "status": "pending" if not result.get("existing") else "existing",
        "ws_url": result["ws_url"],
        "message": "历史数据生成任务已创建" if not result.get("existing") else "正在初始化，请等待",
    }


@router.get("/diagnosis/{code}/history-status")
async def get_history_status(
    code: str,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """获取历史数据生成状态"""
    code = code.zfill(6)
    running_task = (
        db.query(Task)
        .filter(
            Task.task_type == "generate_history",
            Task.filter_by_code(code),
            Task.status.in_(["pending", "running"]),
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
        .first()
    )
    count = db.query(DailyB1Check).filter(DailyB1Check.code == code).count()
    latest_detail = (
        db.query(DailyB1CheckDetail)
        .filter(DailyB1CheckDetail.code == code)
        .order_by(DailyB1CheckDetail.updated_at.desc(), DailyB1CheckDetail.id.desc())
        .first()
    )
    return {
        "exists": count > 0,
        "generating": running_task is not None,
        "count": count,
        "total": min(180, count) if count else 0,
        "generated_at": latest_detail.updated_at.isoformat() if latest_detail and latest_detail.updated_at else None,
    }


@router.get("/diagnosis/{code}/history/{check_date}", response_model=DiagnosisHistoryDetailResponse)
async def get_diagnosis_history_detail(
    code: str,
    check_date: str,
    user=Depends(require_user),
) -> DiagnosisHistoryDetailResponse:
    detail = analysis_service.get_history_detail(code, check_date)
    if detail is None:
        raise HTTPException(status_code=404, detail="未找到该交易日的诊断详情")
    return DiagnosisHistoryDetailResponse.model_validate(detail)


@router.post("/diagnosis/{code}/history/{check_date}/detail")
async def generate_diagnosis_history_detail(
    code: str,
    check_date: str,
    force: bool = Query(default=False, description="是否强制重新生成"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    from app.main import manager

    existing = analysis_service.get_history_detail(code, check_date)
    if existing and existing.get("detail_ready") and not force:
        return {
            "status": "ready",
            "code": code.zfill(6),
            "check_date": check_date,
            "message": "已存在详情，直接读取",
        }

    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)
    result = await task_service.create_task(
        "generate_history_detail",
        {
            "code": code.zfill(6),
            "check_date": check_date,
            "force": force,
            "reviewer": "quant",
            "trigger_source": "manual",
        },
    )
    return {
        "task_id": result["task_id"],
        "code": code.zfill(6),
        "check_date": check_date,
        "status": "pending" if not result.get("existing") else "existing",
        "ws_url": result["ws_url"],
        "message": "诊断详情生成任务已创建" if not result.get("existing") else "正在初始化，请等待",
    }


@router.post("/diagnosis/analyze")
async def analyze_stock(
    request: DiagnosisRequest,
    _rate_limit: None = Depends(single_analysis_rate_limit),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """启动单股分析（后台任务模式）

    阶段5改造：
    - 通过任务系统统一管理
    - 添加限流约束（10次/分钟）
    - 返回任务信息，前端可通过任务ID轮询或通过WebSocket获取分析结果
    """
    from app.main import manager

    ensure_tushare_ready()
    code = request.code.zfill(6)

    # 创建后台分析任务
    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)
    result = await task_service.create_task(
        "single_analysis",
        {"code": code, "reviewer": "quant", "trigger_source": "manual"}
    )

    return {
        "task_id": result["task_id"],
        "code": code,
        "status": "pending" if not result.get("existing") else "existing",
        "ws_url": result["ws_url"],
        "message": "分析任务已创建" if not result.get("existing") else "正在初始化，请等待",
    }


@router.get("/diagnosis/{code}/result")
async def get_analysis_result(code: str, db: Session = Depends(get_db), user=Depends(require_user)) -> dict:
    """获取单股分析结果

    从最新的single_analysis任务中获取分析结果。
    如果任务已完成，返回完整结果；如果任务进行中，返回任务状态。
    """
    from datetime import timedelta
    from app.models import Task

    code = code.zfill(6)

    # 查找最近的单股分析任务
    cutoff_time = utc_now() - timedelta(hours=24)
    task = (
        db.query(Task)
        .filter(
            Task.task_type == "single_analysis",
            Task.filter_by_code(code),
            Task.created_at >= cutoff_time,
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
        .first()
    )

    if not task:
        raise HTTPException(status_code=404, detail="未找到分析任务")

    # 获取股票信息
    stock = db.query(Stock).filter(Stock.code == code).first()
    if stock is None:
        try:
            stock = TushareService().sync_stock_to_db(db, code)
        except Exception:
            stock = None

    # 如果任务还在进行中，返回状态
    if task.status in ("pending", "running"):
        return {
            "code": code,
            "name": stock.name if stock else None,
            "status": "processing",
            "task_status": task.status,
            "task_id": task.id,
            "progress": task.progress,
            "progress_meta": task.progress_meta_json,
        }

    # 如果任务失败，返回错误
    if task.status == "failed":
        return {
            "code": code,
            "name": stock.name if stock else None,
            "status": "failed",
            "task_id": task.id,
            "error": task.error_message,
        }

    # 任务已完成，返回结果
    # 只读模式：不触发实时计算补全缺失字段
    result_json = task.result_json or {}

    return {
        "code": code,
        "name": stock.name if stock else None,
        "status": "completed",
        "task_id": task.id,
        "current_price": result_json.get("close_price"),
        "b1_passed": result_json.get("b1_passed"),
        "score": result_json.get("score"),
        "verdict": result_json.get("verdict"),
        "analysis": {
            "kdj_j": result_json.get("kdj_j"),
            "zx_long_pos": result_json.get("zx_long_pos"),
            "weekly_ma_aligned": result_json.get("weekly_ma_aligned"),
            "volume_healthy": result_json.get("volume_healthy"),
            "scores": result_json.get("scores"),
            "trend_reasoning": result_json.get("trend_reasoning"),
            "position_reasoning": result_json.get("position_reasoning"),
            "volume_reasoning": result_json.get("volume_reasoning"),
            "abnormal_move_reasoning": result_json.get("abnormal_move_reasoning"),
            "signal_type": result_json.get("signal_type"),
            "signal_reasoning": result_json.get("signal_reasoning"),
            "comment": result_json.get("comment"),
        },
    }


@router.post("/tomorrow-star/generate")
async def generate_tomorrow_star(
    reviewer: str = Query(default="quant", description="评审者类型"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """手动生成明日之星"""
    ensure_tushare_ready()
    task_service = TaskService(db)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)

    result = await task_service.create_task(
        "tomorrow_star",
        {"reviewer": reviewer}
    )

    return {
        "status": "pending",
        "message": "明日之星生成任务已创建",
        "task_id": result["task_id"],
        "ws_url": result["ws_url"],
    }
