"""
Analysis API
~~~~~~~~~~~~
分析相关 API (明日之星、单股诊断)

阶段5改造：长任务统一通过TaskService管理，不再使用BackgroundTasks。
"""
import asyncio
import json
import logging
import os
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
import pandas as pd

from app.api.cache_decorators import (
    build_candidates_cache_key,
    build_freshness_cache_key,
    cached_tomorrow_star_dates,
    cached_current_hot_dates,
    build_tomorrow_star_dates_cache_key,
    build_current_hot_dates_cache_key,
)
from app.api.deps import get_admin_user, require_user
from app.api.rate_limit import single_analysis_rate_limit, history_generation_rate_limit
from app.api.tasks import _cleanup_stale_active_tasks, _raise_initialization_in_progress
from app.cache import cache
from app.config import settings
from app.database import get_db
from app.models import Candidate, AnalysisResult, DailyB1Check, DailyB1CheckDetail, Stock, StockDaily, Task, CurrentHotAnalysisResult, CurrentHotCandidate
from app.services.analysis_service import analysis_service
from app.services.current_hot_aggregate_service import CurrentHotAggregateService
from app.services.current_hot_intraday_service import CurrentHotIntradayAnalysisService
from app.services.current_hot_service import CurrentHotService
from app.services.closing_analysis_service import ClosingAnalysisService
from app.services.diagnosis_history_cache_service import diagnosis_history_cache_service
from app.services.hot_news_aggregator_service import HotNewsAggregatorService
from app.services.intraday_analysis_service import IntradayAnalysisService
from app.services.market_service import MarketService
from app.services.sector_analysis_service import SectorAnalysisService
from app.services.stock_ai_analysis_service import StockAiAnalysisService
# 风险识别服务已暂时屏蔽
# from app.services.speculative_risk_service import SpeculativeRiskService
from app.services.task_service import TaskService
from app.services.tomorrow_star_aggregate_service import TomorrowStarAggregateCache
from app.services.tomorrow_star_window_service import TomorrowStarWindowService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now
from app.schemas import (
    CandidatesResponse,
    CandidateItem,
    AnalysisResultResponse,
    AnalysisItem,
    CurrentHotAggregateResponse,
    CurrentHotCandidateItem,
    CurrentHotCandidatesResponse,
    CurrentHotAnalysisItem,
    CurrentHotAnalysisResultResponse,
    CurrentHotDatesResponse,
    CurrentHotHistoryItem,
    CurrentHotSectorHistorySeries,
    CurrentHotSectorSummaryItem,
    CurrentHotSectorAnalysisResponse,
    CurrentHotIntradayAnalysisGenerateResponse,
    CurrentHotIntradayAnalysisPrefetchResponse,
    CurrentHotIntradayAnalysisResponse,
    ClosingAnalysisReportResponse,
    ClosingAnalysisStatusResponse,
    ClosingHotTopics,
    SectorAnalysisRowsResponse,
    SectorAnalysisRowItem,
    TomorrowStarAggregateResponse,
    TomorrowStarDatesResponse,
    TomorrowStarHistoryItem,
    TomorrowStarWindowStatusResponse,
    IntradayAnalysisGenerateResponse,
    IntradayAnalysisPrefetchResponse,
    IntradayAnalysisResponse,
    DiagnosisHistoryResponse,
    DiagnosisHistoryDetailResponse,
    B1CheckItem,
    DiagnosisRequest,
    DiagnosisResponse,
    StockAiAnalysisResponse,
    SignalReturnAnalysisResponse,
    SignalReturnBenchmark,
    SignalReturnEventPoint,
    SignalReturnItem,
    SignalReturnTimelinePoint,
    ConceptsResponse,
    ConceptInfo,
    StockConceptsResponse,
    ConceptMembersResponse,
)
from pipeline.review_prefilter import TushareMetadataStore

logger = logging.getLogger(__name__)
router = APIRouter()
DIAGNOSIS_HISTORY_WINDOW_DAYS = analysis_service.HISTORY_WINDOW_DAYS
SIGNAL_RETURN_BENCHMARK = {
    "name": "上证指数",
    "ts_code": "000001.SH",
}
BLOCKED_ANALYSIS_TASK_TYPES = {
    TaskService.DAILY_BATCH_UPDATE_TASK_TYPE,
    TaskService.INCREMENTAL_UPDATE_TASK_TYPE,
    "full_update",
    TaskService.RECENT_120_REBUILD_TASK_TYPE,
}

ROOT = Path(__file__).parent.parent.parent.parent
_signal_return_benchmark_store: TushareMetadataStore | None = None
_history_generation_locks: dict[str, asyncio.Lock] = {}
_history_generation_active_counts: dict[str, int] = {}
_history_generation_state_lock = asyncio.Lock()


async def _get_history_generation_lock(code: str) -> asyncio.Lock:
    async with _history_generation_state_lock:
        lock = _history_generation_locks.get(code)
        if lock is None:
            lock = asyncio.Lock()
            _history_generation_locks[code] = lock
        return lock


async def _mark_history_generation_active(code: str) -> None:
    async with _history_generation_state_lock:
        _history_generation_active_counts[code] = _history_generation_active_counts.get(code, 0) + 1


async def _mark_history_generation_inactive(code: str) -> None:
    async with _history_generation_state_lock:
        count = _history_generation_active_counts.get(code, 0) - 1
        if count > 0:
            _history_generation_active_counts[code] = count
        else:
            _history_generation_active_counts.pop(code, None)


async def _is_history_generation_active(code: str) -> bool:
    async with _history_generation_state_lock:
        return _history_generation_active_counts.get(code, 0) > 0


async def _run_history_generation(code: str, func, *args, **kwargs) -> dict[str, Any]:
    lock = await _get_history_generation_lock(code)

    await _mark_history_generation_active(code)
    try:
        async with lock:
            return await asyncio.to_thread(func, *args, **kwargs)
    finally:
        await _mark_history_generation_inactive(code)


def _parse_date_or_none(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _safe_json_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _signal_sort_priority(signal_type: Optional[str]) -> int:
    return 0 if signal_type == "trend_start" else 1


def _sort_score_desc(value: Optional[float]) -> float:
    return -(value if value is not None else -9999.0)


def _extract_prefilter_fields(details_json: Optional[dict[str, Any]]) -> tuple[Optional[bool], Optional[str], Optional[list[str]]]:
    if not isinstance(details_json, dict):
        return None, None, None

    prefilter = details_json.get("prefilter")
    if not isinstance(prefilter, dict):
        return None, None, None

    passed_raw = prefilter.get("passed")
    passed = bool(passed_raw) if isinstance(passed_raw, bool) else None

    summary_raw = prefilter.get("summary")
    summary = str(summary_raw).strip() if isinstance(summary_raw, str) and summary_raw.strip() else None

    blocked_by_raw = prefilter.get("blocked_by")
    blocked_by = [str(item) for item in blocked_by_raw] if isinstance(blocked_by_raw, list) and blocked_by_raw else None
    return passed, summary, blocked_by


def _extract_pullback_fields(details_json: Optional[dict[str, Any]]) -> tuple[Optional[str], list[str]]:
    if not isinstance(details_json, dict):
        return None, []

    quality_raw = details_json.get("pullback_quality")
    quality = str(quality_raw).strip() if isinstance(quality_raw, str) and quality_raw.strip() else None

    flags_raw = details_json.get("pullback_negative_flags")
    if isinstance(flags_raw, list):
        flags = [str(item).strip() for item in flags_raw if str(item).strip()]
    elif isinstance(flags_raw, str):
        flags = [item.strip() for item in flags_raw.split("|") if item.strip()]
    else:
        flags = []
    return quality, flags


def _extract_tomorrow_star_pass(details_json: Optional[dict[str, Any]]) -> Optional[bool]:
    if not isinstance(details_json, dict):
        return None

    direct = details_json.get("tomorrow_star_pass")
    if isinstance(direct, bool):
        return direct

    rules = details_json.get("rules")
    if isinstance(rules, dict) and isinstance(rules.get("tomorrow_star_pass"), bool):
        return rules["tomorrow_star_pass"]

    details = details_json.get("details")
    if isinstance(details, dict) and isinstance(details.get("tomorrow_star_pass"), bool):
        return details["tomorrow_star_pass"]

    return None


def _extract_tomorrow_star_pass_from_detail(detail: Optional[DailyB1CheckDetail]) -> Optional[bool]:
    if detail is None or not isinstance(detail.rules_json, dict):
        return None
    value = detail.rules_json.get("tomorrow_star_pass")
    return value if isinstance(value, bool) else None


def _derive_analysis_tomorrow_star_pass(
    *,
    prefilter_passed: Optional[bool],
    verdict: Optional[str],
    signal_type: Optional[str],
) -> Optional[bool]:
    if prefilter_passed is None:
        return None
    return bool(prefilter_passed and verdict == "PASS" and signal_type == "trend_start")


def _get_latest_history_summary(db: Session, code: str) -> dict | None:
    latest_row = (
        db.query(DailyB1Check, DailyB1CheckDetail)
        .outerjoin(
            DailyB1CheckDetail,
            (DailyB1CheckDetail.code == DailyB1Check.code)
            & (DailyB1CheckDetail.check_date == DailyB1Check.check_date),
        )
        .filter(DailyB1Check.code == code)
        .order_by(DailyB1Check.check_date.desc(), DailyB1Check.id.desc())
        .first()
    )
    if not latest_row:
        return None

    item, detail = latest_row
    score_details = detail.score_details_json if detail else {}
    return {
        "check_date": item.check_date.isoformat() if item.check_date else None,
        "close_price": item.close_price,
        "b1_passed": item.b1_passed,
        "b1_signal_type": item.b1_signal_type,
        "score": item.score,
        "verdict": score_details.get("verdict"),
        "kdj_j": item.kdj_j,
        "zx_long_pos": item.zx_long_pos,
        "weekly_ma_aligned": item.weekly_ma_aligned,
        "volume_healthy": item.volume_healthy,
        "active_pool_rank": item.active_pool_rank,
        "turnover_rate": item.turnover_rate,
        "volume_ratio": item.volume_ratio,
        "in_active_pool": detail.rules_json.get("in_active_pool") if detail and isinstance(detail.rules_json, dict) else None,
        "signal_type": score_details.get("signal_type"),
    }


# 风险识别相关函数已暂时屏蔽
# def _build_diagnosis_risk_flag(...): ...
# def _build_diagnosis_risk_regime(...): ...


def ensure_tushare_ready() -> None:
    service = TushareService()
    valid, message = service.verify_token()
    if not valid:
        raise HTTPException(status_code=503, detail=f"Tushare 未就绪: {message}")


async def ensure_tushare_ready_async() -> None:
    service = TushareService()
    valid, message = await asyncio.to_thread(service.verify_token)
    if not valid:
        raise HTTPException(status_code=503, detail=f"Tushare 未就绪: {message}")


def ensure_tushare_ready_if_configured() -> None:
    service = TushareService()
    if not service.token:
        return
    valid, message = service.verify_token()
    if not valid:
        logger.warning("Tushare 已配置但当前不可用，盘中分析将走降级链路: %s", message)


async def ensure_tushare_ready_if_configured_async() -> None:
    service = TushareService()
    if not service.token:
        return
    valid, message = await asyncio.to_thread(service.verify_token)
    if not valid:
        logger.warning("Tushare 已配置但当前不可用，盘中分析将走降级链路: %s", message)


def ensure_analysis_read_available(db: Session) -> None:
    """分析类页面在关键数据更新期间进入只读拦截。"""
    update_state = MarketService.get_update_state()
    if update_state.get("running"):
        raise HTTPException(
            status_code=409,
            detail=f"更新数据中，请稍后访问。当前阶段：{update_state.get('stage_label') or update_state.get('message') or '数据刷新中'}",
        )

    active_task = (
        db.query(Task)
        .filter(
            Task.task_type.in_(list(BLOCKED_ANALYSIS_TASK_TYPES)),
            Task.status.in_(["pending", "running"]),
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
        .first()
    )
    if active_task is not None:
        raise HTTPException(
            status_code=409,
            detail="更新数据中，请稍后访问。",
        )


@router.get("/tomorrow-star/dates", response_model=TomorrowStarDatesResponse)
@cached_tomorrow_star_dates(ttl=180)
async def get_tomorrow_star_dates(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> TomorrowStarDatesResponse:
    """获取明日之星历史日期列表"""
    ensure_analysis_read_available(db)
    summary = TomorrowStarWindowService(db).get_window_status(window_size=TomorrowStarWindowService.DEFAULT_WINDOW_SIZE)
    history_items = [
        TomorrowStarHistoryItem(
            pick_date=datetime.strptime(item["pick_date"], "%Y-%m-%d").date(),
            date=item["date"],
            count=int(item.get("count", 0) or 0),
            pass_count=int(item.get("pass_count", 0) or 0),
            candidate_count=int(item.get("candidate_count", 0) or 0),
            analysis_count=int(item.get("analysis_count", 0) or 0),
            trend_start_count=int(item.get("trend_start_count", 0) or 0),
            consecutive_candidate_count=int(item.get("consecutive_candidate_count", 0) or 0),
            tomorrow_star_count=int(item.get("tomorrow_star_count", 0) or 0),
            status=item.get("status") or "missing",
            error_message=item.get("error_message"),
            is_latest=bool(item.get("is_latest")),
            market_regime_blocked=bool(item.get("market_regime_blocked")),
            market_regime_info=item.get("market_regime_info"),
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
def get_tomorrow_star_window_status(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> TomorrowStarWindowStatusResponse:
    summary = TomorrowStarWindowService(db).get_window_status(window_size=TomorrowStarWindowService.DEFAULT_WINDOW_SIZE)
    history_items = [
        TomorrowStarHistoryItem(
            pick_date=datetime.strptime(item["pick_date"], "%Y-%m-%d").date(),
            date=item["date"],
            count=int(item.get("count", 0) or 0),
            pass_count=int(item.get("pass_count", 0) or 0),
            candidate_count=int(item.get("candidate_count", 0) or 0),
            analysis_count=int(item.get("analysis_count", 0) or 0),
            trend_start_count=int(item.get("trend_start_count", 0) or 0),
            consecutive_candidate_count=int(item.get("consecutive_candidate_count", 0) or 0),
            tomorrow_star_count=int(item.get("tomorrow_star_count", 0) or 0),
            status=item.get("status") or "missing",
            error_message=item.get("error_message"),
            is_latest=bool(item.get("is_latest")),
            market_regime_blocked=bool(item.get("market_regime_blocked")),
            market_regime_info=item.get("market_regime_info"),
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
    ensure_analysis_read_available(db)
    from app.services.market_service import market_service, MarketService

    _cleanup_stale_active_tasks(db)

    cache_key = build_freshness_cache_key()
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    latest_stock_daily_date = db.query(func.max(StockDaily.trade_date)).scalar()
    local_latest_date = latest_stock_daily_date.isoformat() if latest_stock_daily_date else None
    if local_latest_date is None:
        local_latest_date = await asyncio.to_thread(market_service.get_local_latest_date)
    latest_candidate_date = await asyncio.to_thread(analysis_service.get_latest_candidate_date)
    latest_result_date = await asyncio.to_thread(analysis_service.get_latest_result_date)
    latest_trade_date = (
        market_service.get_cached_trade_date()
        or local_latest_date
        or latest_candidate_date
        or latest_result_date
    )
    latest_trade_data_ready = None
    latest_candidate_count = 0
    latest_result_count = 0

    if latest_candidate_date:
        try:
            latest_candidate_count = int(
                db.query(Candidate)
                .filter(Candidate.pick_date == datetime.strptime(latest_candidate_date, "%Y-%m-%d").date())
                .count()
            )
        except ValueError:
            latest_candidate_count = 0

    if latest_result_date:
        try:
            latest_result_count = int(
                db.query(AnalysisResult)
                .filter(AnalysisResult.pick_date == datetime.strptime(latest_result_date, "%Y-%m-%d").date())
                .count()
            )
        except ValueError:
            latest_result_count = 0

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
        str(latest_candidate_count),
        str(latest_result_date or ""),
        str(latest_result_count),
        str(latest_trade_data_ready),
        str(running_task.id if running_task else ""),
        str(running_task.status if running_task else ""),
        str(incremental_state.get("running", False)),
        str(incremental_state.get("progress", 0)),
    ])

    result = {
        "latest_trade_date": latest_trade_date,
        "latest_trade_data_ready": latest_trade_data_ready,
        "latest_trade_date_source": "local_cache",
        "local_latest_date": local_latest_date,
        "latest_candidate_date": latest_candidate_date,
        "latest_candidate_count": latest_candidate_count,
        "latest_result_date": latest_result_date,
        "latest_result_count": latest_result_count,
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


@router.get("/tomorrow-star/aggregate", response_model=TomorrowStarAggregateResponse)
def get_tomorrow_star_aggregate(
    candidate_limit: int = 3000,
    force_refresh: bool = Query(default=False, description="强制刷新缓存"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> TomorrowStarAggregateResponse:
    """
    聚合接口 - 一次返回首屏所需的全部数据。
    包含：日期窗口 + 最新候选 + 最新分析结果 + 新鲜度状态。
    """
    ensure_analysis_read_available(db)
    aggregate_cache = TomorrowStarAggregateCache(db)
    if not force_refresh:
        cached_payload = aggregate_cache.get(candidate_limit=candidate_limit)
        if cached_payload is not None:
            return TomorrowStarAggregateResponse(**cached_payload)

    # --- 1) 日期窗口 ---
    summary = TomorrowStarWindowService(db).get_window_status(window_size=TomorrowStarWindowService.DEFAULT_WINDOW_SIZE)
    history_items = [
        TomorrowStarHistoryItem(
            pick_date=datetime.strptime(item["pick_date"], "%Y-%m-%d").date(),
            date=item["date"],
            count=int(item.get("count", 0) or 0),
            pass_count=int(item.get("pass_count", 0) or 0),
            candidate_count=int(item.get("candidate_count", 0) or 0),
            analysis_count=int(item.get("analysis_count", 0) or 0),
            trend_start_count=int(item.get("trend_start_count", 0) or 0),
            consecutive_candidate_count=int(item.get("consecutive_candidate_count", 0) or 0),
            tomorrow_star_count=int(item.get("tomorrow_star_count", 0) or 0),
            status=item.get("status") or "missing",
            error_message=item.get("error_message"),
            is_latest=bool(item.get("is_latest")),
            market_regime_blocked=bool(item.get("market_regime_blocked")),
            market_regime_info=item.get("market_regime_info"),
        )
        for item in summary.items
    ]
    window_status_obj = TomorrowStarWindowStatusResponse(
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
    dates_data = {
        "dates": [item.date for item in history_items],
        "history": [item.model_dump(mode="json") for item in history_items],
        "window_status": window_status_obj.model_dump(mode="json"),
    }

    # --- 2) 最新候选 ---
    from app.services.candidate_service import CandidateService
    from app.models import TomorrowStarRun as _TSRun

    candidates_data = None
    try:
        normalized_date = analysis_service._normalize_pick_date(None)
        target_date = _parse_date_or_none(normalized_date)

        # 检查市场环境阻断
        if target_date:
            run = db.query(_TSRun).filter(_TSRun.pick_date == target_date).first()
            if run and run.meta_json and run.meta_json.get("market_regime_blocked"):
                regime_info = run.meta_json.get("market_regime_info", {})
                candidates_data = {
                    "pick_date": str(target_date),
                    "candidates": [],
                    "total": 0,
                    "status": "market_regime_blocked",
                    "message": f"市场环境不佳: {regime_info.get('summary', '未知原因')}",
                    "market_regime_info": {
                        "passed": regime_info.get("passed", False),
                        "summary": regime_info.get("summary", ""),
                        "details": regime_info.get("details", []),
                    },
                }

        if candidates_data is None:
            persisted_pick_date, persisted_candidates = CandidateService(db).load_candidates(normalized_date, limit=candidate_limit)
            if persisted_candidates:
                try:
                    response_pick_date = pd.Timestamp(persisted_pick_date).date() if persisted_pick_date else None
                except Exception:
                    response_pick_date = None
                cand_items = []
                for i, c in enumerate(persisted_candidates[:candidate_limit]):
                    cand_items.append(
                        CandidateItem(
                            id=i,
                            pick_date=response_pick_date,
                            code=c["code"],
                            name=c.get("name"),
                            industry=c.get("industry"),
                            strategy=c.get("strategy") or "b1",
                            open_price=c.get("open"),
                            close_price=c.get("close"),
                            change_pct=c.get("change_pct"),
                            turnover=float(c["turnover_n"]) if c.get("turnover_n") is not None else None,
                            turnover_rate=c.get("turnover_rate"),
                            volume_ratio=c.get("volume_ratio"),
                            active_pool_rank=c.get("active_pool_rank"),
                            b1_passed=c.get("b1_passed"),
                            kdj_j=c.get("kdj_j"),
                            consecutive_days=int(c.get("consecutive_days") or 1),
                        ).model_dump(mode="json")
                    )
                candidates_data = {
                    "pick_date": str(response_pick_date) if response_pick_date else None,
                    "candidates": cand_items,
                    "total": len(persisted_candidates),
                    "status": "ok",
                    "message": None,
                }
            else:
                # 没有候选数据时检查市场环境
                check_date = target_date
                mkt_regime_info = None
                if check_date:
                    run = db.query(_TSRun).filter(_TSRun.pick_date == check_date).first()
                    if run and run.meta_json and run.meta_json.get("market_regime_blocked"):
                        ri = run.meta_json.get("market_regime_info", {})
                        mkt_regime_info = {
                            "passed": ri.get("passed", False),
                            "summary": ri.get("summary", ""),
                            "details": ri.get("details", []),
                        }
                if mkt_regime_info:
                    candidates_data = {
                        "pick_date": str(check_date) if check_date else None,
                        "candidates": [],
                        "total": 0,
                        "status": "market_regime_blocked",
                        "message": f"市场环境不佳: {mkt_regime_info['summary']}",
                        "market_regime_info": mkt_regime_info,
                    }
                else:
                    agg_running_task = (
                        db.query(Task)
                        .filter(
                            Task.task_type.in_(["tomorrow_star", "full_update"]),
                            Task.status.in_(["pending", "running"]),
                        )
                        .order_by(Task.created_at.desc())
                        .first()
                    )
                    candidates_data = {
                        "pick_date": str(check_date) if check_date else None,
                        "candidates": [],
                        "total": 0,
                        "status": "not_ready",
                        "message": "候选数据尚未生成，请稍后再试",
                        "has_running_task": agg_running_task is not None,
                        "running_task_id": agg_running_task.id if agg_running_task else None,
                    }
    except Exception:
        import traceback
        traceback.print_exc()

    # --- 3) 最新分析结果 ---
    results_data = None
    try:
        results_target_date = None
        normalized_date = analysis_service._normalize_pick_date(None)
        if normalized_date:
            try:
                results_target_date = datetime.strptime(normalized_date, "%Y-%m-%d").date()
            except ValueError:
                results_target_date = None

        if results_target_date is None:
            latest_pick_date = (
                db.query(AnalysisResult.pick_date)
                .join(
                    Candidate,
                    and_(
                        Candidate.pick_date == AnalysisResult.pick_date,
                        Candidate.code == AnalysisResult.code,
                    ),
                )
                .order_by(AnalysisResult.pick_date.desc())
                .limit(1)
                .scalar()
            )
            results_target_date = latest_pick_date

        if results_target_date is not None:
            run = db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == results_target_date).first()
            if run and run.meta_json and run.meta_json.get("market_regime_blocked"):
                regime_info = run.meta_json.get("market_regime_info", {})
                results_data = {
                    "pick_date": str(results_target_date),
                    "results": [],
                    "total": 0,
                    "min_score_threshold": 4.0,
                    "status": "market_regime_blocked",
                    "message": f"市场环境不佳: {regime_info.get('summary', '未知原因')}",
                    "market_regime_info": {
                        "passed": regime_info.get("passed", False),
                        "summary": regime_info.get("summary", ""),
                        "details": regime_info.get("details", []),
                    },
                }
            else:
                rows = (
                    db.query(
                        AnalysisResult,
                        Stock.name,
                        DailyB1Check.turnover_rate.label("b1_turnover_rate"),
                        DailyB1Check.volume_ratio.label("b1_volume_ratio"),
                        StockDaily.turnover_rate.label("daily_turnover_rate"),
                        StockDaily.volume_ratio.label("daily_volume_ratio"),
                        DailyB1CheckDetail,
                    )
                    .join(
                        Candidate,
                        and_(
                            Candidate.pick_date == AnalysisResult.pick_date,
                            Candidate.code == AnalysisResult.code,
                        ),
                    )
                    .outerjoin(Stock, Stock.code == AnalysisResult.code)
                    .outerjoin(
                        DailyB1Check,
                        (DailyB1Check.code == AnalysisResult.code)
                        & (DailyB1Check.check_date == AnalysisResult.pick_date),
                    )
                    .outerjoin(
                        DailyB1CheckDetail,
                        (DailyB1CheckDetail.code == AnalysisResult.code)
                        & (DailyB1CheckDetail.check_date == AnalysisResult.pick_date),
                    )
                    .outerjoin(
                        StockDaily,
                        (StockDaily.code == AnalysisResult.code)
                        & (StockDaily.trade_date == AnalysisResult.pick_date),
                    )
                    .filter(AnalysisResult.pick_date == results_target_date)
                    .order_by(
                        AnalysisResult.total_score.desc().nullslast(),
                        AnalysisResult.id.asc(),
                    )
                    .all()
                )
                result_items = []
                for row, stock_name, b1_turnover_rate, b1_volume_ratio, daily_turnover_rate, daily_volume_ratio, detail in rows:
                    prefilter_passed, prefilter_summary, prefilter_blocked_by = _extract_prefilter_fields(row.details_json)
                    pullback_quality, pullback_negative_flags = _extract_pullback_fields(row.details_json)
                    details_turnover_rate = row.details_json.get("turnover_rate") if isinstance(row.details_json, dict) else None
                    details_volume_ratio = row.details_json.get("volume_ratio") if isinstance(row.details_json, dict) else None
                    tomorrow_star_pass = _extract_tomorrow_star_pass(row.details_json)
                    if tomorrow_star_pass is None:
                        tomorrow_star_pass = _extract_tomorrow_star_pass_from_detail(detail)
                    if tomorrow_star_pass is None:
                        tomorrow_star_pass = _derive_analysis_tomorrow_star_pass(
                            prefilter_passed=prefilter_passed,
                            verdict=row.verdict,
                            signal_type=row.signal_type,
                        )
                    result_items.append(
                        AnalysisItem(
                            id=row.id,
                            pick_date=results_target_date,
                            code=row.code,
                            name=stock_name,
                            reviewer=row.reviewer,
                            verdict=row.verdict,
                            total_score=_safe_json_float(row.total_score),
                            signal_type=row.signal_type,
                            comment=row.comment,
                            turnover_rate=(
                                _safe_json_float(details_turnover_rate)
                                if details_turnover_rate is not None
                                else (_safe_json_float(b1_turnover_rate) or _safe_json_float(daily_turnover_rate))
                            ),
                            volume_ratio=(
                                _safe_json_float(details_volume_ratio)
                                if details_volume_ratio is not None
                                else (_safe_json_float(b1_volume_ratio) or _safe_json_float(daily_volume_ratio))
                            ),
                            tomorrow_star_pass=tomorrow_star_pass,
                            prefilter_passed=prefilter_passed,
                            prefilter_summary=prefilter_summary,
                            prefilter_blocked_by=prefilter_blocked_by,
                            pullback_quality=pullback_quality,
                            pullback_negative_flags=pullback_negative_flags,
                        ).model_dump(mode="json")
                    )
                result_items.sort(
                    key=lambda item: (
                        _signal_sort_priority(item.get("signal_type")),
                        _sort_score_desc(item.get("total_score")),
                        item.get("code", ""),
                    )
                )
                results_data = {
                    "pick_date": str(results_target_date),
                    "results": result_items,
                    "total": len(result_items),
                    "min_score_threshold": 4.0,
                }
    except Exception:
        import traceback
        traceback.print_exc()

    # --- 4) 新鲜度状态 (精简版，直接内联计算) ---
    from app.services.market_service import market_service as _ms, MarketService as _MS
    _cleanup_stale_active_tasks(db)
    latest_trade_date = _ms.get_latest_trade_date() if _ms.token else None
    latest_trade_data_ready = (
        TushareService().is_trade_date_data_ready(latest_trade_date)
        if latest_trade_date and _ms.token
        else None
    )
    local_latest_date = _ms.get_local_latest_date()
    latest_candidate_date = analysis_service.get_latest_candidate_date()
    latest_result_date = analysis_service.get_latest_result_date()
    latest_candidate_count = 0
    latest_result_count = 0
    if latest_candidate_date:
        try:
            latest_candidate_count = int(
                db.query(Candidate)
                .filter(Candidate.pick_date == datetime.strptime(latest_candidate_date, "%Y-%m-%d").date())
                .count()
            )
        except ValueError:
            latest_candidate_count = 0
    if latest_result_date:
        try:
            latest_result_count = int(
                db.query(AnalysisResult)
                .filter(AnalysisResult.pick_date == datetime.strptime(latest_result_date, "%Y-%m-%d").date())
                .count()
            )
        except ValueError:
            latest_result_count = 0
    running_task = (
        db.query(Task)
        .filter(
            Task.task_type.in_(["tomorrow_star", "full_update"]),
            Task.status.in_(["pending", "running"]),
        )
        .order_by(Task.created_at.desc())
        .first()
    )
    incremental_state = _MS.get_update_state()
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
        str(latest_candidate_count),
        str(latest_result_date or ""),
        str(latest_result_count),
        str(latest_trade_data_ready),
        str(running_task.id if running_task else ""),
        str(running_task.status if running_task else ""),
        str(incremental_state.get("running", False)),
        str(incremental_state.get("progress", 0)),
    ])
    freshness_data = {
        "latest_trade_date": latest_trade_date,
        "latest_trade_data_ready": latest_trade_data_ready,
        "local_latest_date": local_latest_date,
        "latest_candidate_date": latest_candidate_date,
        "latest_candidate_count": latest_candidate_count,
        "latest_result_date": latest_result_date,
        "latest_result_count": latest_result_count,
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

    payload = {
        "dates": dates_data["dates"],
        "history": dates_data["history"],
        "window_status": dates_data["window_status"],
        "candidates": candidates_data,
        "results": results_data,
        "freshness": freshness_data,
        "generated_at": utc_now().isoformat(),
        "cache_hit": False,
    }
    expected_candidates_missing = (
        latest_candidate_count > 0
        and (
            not isinstance(candidates_data, dict)
            or (
                int(candidates_data.get("total") or 0) == 0
                and str(candidates_data.get("pick_date") or latest_candidate_date or "") == str(latest_candidate_date or "")
                and candidates_data.get("status") != "market_regime_blocked"
            )
        )
    )
    expected_results_missing = (
        latest_result_count > 0
        and (
            not isinstance(results_data, dict)
            or (
                int(results_data.get("total") or 0) == 0
                and str(results_data.get("pick_date") or latest_result_date or "") == str(latest_result_date or "")
                and results_data.get("status") != "market_regime_blocked"
            )
        )
    )
    if not expected_candidates_missing and not expected_results_missing:
        aggregate_cache.set(payload, candidate_limit=candidate_limit)
    return TomorrowStarAggregateResponse(**payload)


@router.get("/tomorrow-star/candidates", response_model=CandidatesResponse)
def get_candidates(
    date: Optional[str] = None,
    limit: int = 3000,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CandidatesResponse:
    """获取候选股票列表（只读数据库持久化结果）"""
    ensure_analysis_read_available(db)
    from app.services.candidate_service import CandidateService
    from app.models import TomorrowStarRun
    import pandas as pd

    requested_date = analysis_service._normalize_pick_date(date)
    cache_key = f"{build_candidates_cache_key(requested_date, limit)}:market-metrics-v5"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return CandidatesResponse(**cached_result)

    # 检查是否因市场环境被阻断
    target_date = _parse_date_or_none(requested_date)
    if target_date:
        run = db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == target_date).first()
        if run and run.meta_json and run.meta_json.get("market_regime_blocked"):
            regime_info = run.meta_json.get("market_regime_info", {})
            return CandidatesResponse(
                pick_date=target_date,
                candidates=[],
                total=0,
                status="market_regime_blocked",
                message=f"市场环境不佳: {regime_info.get('summary', '未知原因')}",
                market_regime_info={
                    "passed": regime_info.get("passed", False),
                    "summary": regime_info.get("summary", ""),
                    "details": regime_info.get("details", []),
                },
            )

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
                        industry=c.get("industry"),
                        sector_names=c.get("sector_names") or [],
                        strategy=c.get("strategy") or "b1",
                        open_price=c.get("open"),
                        close_price=c.get("close"),
                        change_pct=c.get("change_pct"),
                        turnover=float(c["turnover_n"]) if c.get("turnover_n") is not None else None,
                        turnover_rate=c.get("turnover_rate"),
                        volume_ratio=c.get("volume_ratio"),
                        active_pool_rank=c.get("active_pool_rank"),
                        b1_passed=c.get("b1_passed"),
                        kdj_j=c.get("kdj_j"),
                        consecutive_days=int(c.get("consecutive_days") or 1),
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

        # 没有持久化候选数据，检查是否因市场环境被阻断
        check_date = _parse_date_or_none(requested_date)

        market_regime_info = None
        if check_date:
            run = db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == check_date).first()
            if run and run.meta_json and run.meta_json.get("market_regime_blocked"):
                regime_info = run.meta_json.get("market_regime_info", {})
                market_regime_info = {
                    "passed": regime_info.get("passed", False),
                    "summary": regime_info.get("summary", ""),
                    "details": regime_info.get("details", []),
                }

        if market_regime_info:
            return CandidatesResponse(
                pick_date=check_date,
                candidates=[],
                total=0,
                status="market_regime_blocked",
                message=f"市场环境不佳: {market_regime_info['summary']}",
                market_regime_info=market_regime_info,
            )

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
            pick_date=check_date,
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
def get_analysis_results(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> AnalysisResultResponse:
    """获取指定日期的分析结果"""
    ensure_analysis_read_available(db)
    from app.models import TomorrowStarRun

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
            .join(
                Candidate,
                and_(
                    Candidate.pick_date == AnalysisResult.pick_date,
                    Candidate.code == AnalysisResult.code,
                ),
            )
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

    # 检查是否因市场环境被阻断
    run = db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date == target_date).first()
    if run and run.meta_json and run.meta_json.get("market_regime_blocked"):
        regime_info = run.meta_json.get("market_regime_info", {})
        return AnalysisResultResponse(
            pick_date=target_date,
            results=[],
            total=0,
            min_score_threshold=4.0,
            status="market_regime_blocked",
            message=f"市场环境不佳: {regime_info.get('summary', '未知原因')}",
            market_regime_info={
                "passed": regime_info.get("passed", False),
                "summary": regime_info.get("summary", ""),
                "details": regime_info.get("details", []),
            },
        )

    rows = (
        db.query(
            AnalysisResult,
            Stock.name,
            DailyB1Check.turnover_rate.label("b1_turnover_rate"),
            DailyB1Check.volume_ratio.label("b1_volume_ratio"),
            StockDaily.turnover_rate.label("daily_turnover_rate"),
            StockDaily.volume_ratio.label("daily_volume_ratio"),
            DailyB1CheckDetail,
        )
        .join(
            Candidate,
            and_(
                Candidate.pick_date == AnalysisResult.pick_date,
                Candidate.code == AnalysisResult.code,
            ),
        )
        .outerjoin(Stock, Stock.code == AnalysisResult.code)
        .outerjoin(
            DailyB1Check,
            (DailyB1Check.code == AnalysisResult.code)
            & (DailyB1Check.check_date == AnalysisResult.pick_date),
        )
        .outerjoin(
            DailyB1CheckDetail,
            (DailyB1CheckDetail.code == AnalysisResult.code)
            & (DailyB1CheckDetail.check_date == AnalysisResult.pick_date),
        )
        .outerjoin(
            StockDaily,
            (StockDaily.code == AnalysisResult.code)
            & (StockDaily.trade_date == AnalysisResult.pick_date),
        )
        .filter(AnalysisResult.pick_date == target_date)
        .order_by(
            AnalysisResult.total_score.desc().nullslast(),
            AnalysisResult.id.asc(),
        )
        .all()
    )

    items = []
    for row, stock_name, b1_turnover_rate, b1_volume_ratio, daily_turnover_rate, daily_volume_ratio, detail in rows:
        prefilter_passed, prefilter_summary, prefilter_blocked_by = _extract_prefilter_fields(row.details_json)
        pullback_quality, pullback_negative_flags = _extract_pullback_fields(row.details_json)
        details_turnover_rate = row.details_json.get("turnover_rate") if isinstance(row.details_json, dict) else None
        details_volume_ratio = row.details_json.get("volume_ratio") if isinstance(row.details_json, dict) else None
        tomorrow_star_pass = _extract_tomorrow_star_pass(row.details_json)
        if tomorrow_star_pass is None:
            tomorrow_star_pass = _extract_tomorrow_star_pass_from_detail(detail)
        if tomorrow_star_pass is None:
            tomorrow_star_pass = _derive_analysis_tomorrow_star_pass(
                prefilter_passed=prefilter_passed,
                verdict=row.verdict,
                signal_type=row.signal_type,
            )
        items.append(
            AnalysisItem(
                id=row.id,
                pick_date=target_date,
                code=row.code,
                name=stock_name,
                reviewer=row.reviewer,
                verdict=row.verdict,
                total_score=_safe_json_float(row.total_score),
                signal_type=row.signal_type,
                comment=row.comment,
                turnover_rate=(
                    _safe_json_float(details_turnover_rate)
                    if details_turnover_rate is not None
                    else (_safe_json_float(b1_turnover_rate) or _safe_json_float(daily_turnover_rate))
                ),
                volume_ratio=(
                    _safe_json_float(details_volume_ratio)
                    if details_volume_ratio is not None
                    else (_safe_json_float(b1_volume_ratio) or _safe_json_float(daily_volume_ratio))
                ),
                tomorrow_star_pass=tomorrow_star_pass,
                prefilter_passed=prefilter_passed,
                prefilter_summary=prefilter_summary,
                prefilter_blocked_by=prefilter_blocked_by,
                pullback_quality=pullback_quality,
                pullback_negative_flags=pullback_negative_flags,
            )
        )
    items.sort(
        key=lambda item: (
            _signal_sort_priority(item.signal_type),
            _sort_score_desc(item.total_score),
            item.code,
        )
    )

    return AnalysisResultResponse(
        pick_date=target_date,
        results=items,
        total=len(items),
        min_score_threshold=4.0,
    )


@router.get(
    "/current-hot/aggregate",
    response_model=CurrentHotAggregateResponse,
    summary="当前热盘聚合首屏接口（推荐）",
    description=(
        "一次请求返回首屏所需的全部数据：历史摘要 + 候选列表 + 分析结果 + 板块分析 + 风险环境。"
        "使用 Redis/内存缓存，TTL 120s。"
    ),
)
def get_current_hot_aggregate(
    date: Optional[str] = Query(default=None, description="交易日，不传则取最新"),
    candidates_limit: int = Query(default=3000, ge=1, le=3000, description="候选/分析结果条数上限"),
    sector_window_size: int = Query(default=CurrentHotService.DEFAULT_WINDOW_SIZE, ge=20, le=240, description="板块分析回看窗口"),
    sector_top_n: int = Query(default=5, ge=1, le=12, description="板块 Top N"),
    include_sectors: bool = Query(default=True, description="是否包含板块分析"),
    force_refresh: bool = Query(default=False, description="强制刷新缓存"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotAggregateResponse:
    """当前热盘聚合首屏接口 -- 替代分别请求 dates/candidates/results/sectors。"""
    ensure_analysis_read_available(db)
    payload = CurrentHotAggregateService(db).get_aggregate(
        pick_date=date,
        candidates_limit=candidates_limit,
        sector_window_size=sector_window_size,
        sector_top_n=sector_top_n,
        include_sectors=include_sectors,
        force_refresh=force_refresh,
    )

    # -- history items --
    history_items = [
        CurrentHotHistoryItem(
            pick_date=datetime.strptime(item["pick_date"], "%Y-%m-%d").date(),
            date=item["date"],
            candidate_count=int(item.get("candidate_count", 0) or 0),
            analysis_count=int(item.get("analysis_count", 0) or 0),
            trend_start_count=int(item.get("trend_start_count", 0) or 0),
            b1_pass_count=int(item.get("b1_pass_count", 0) or 0),
            consecutive_candidate_count=int(item.get("consecutive_candidate_count", 0) or 0),
            pass_count=int(item.get("pass_count", 0) or 0),
            status=item.get("status") or "missing",
            error_message=item.get("error_message"),
            is_latest=bool(item.get("is_latest")),
        )
        for item in payload.get("history", [])
    ]

    # -- candidate items --
    candidate_items = [
        CurrentHotCandidateItem(
            id=item["id"],
            pick_date=payload.get("pick_date"),
            code=item["code"],
            name=item.get("name"),
            sector_names=item.get("sector_names") or [],
            board_group=item.get("board_group"),
            open_price=item.get("open_price"),
            close_price=item.get("close_price"),
            change_pct=item.get("change_pct"),
            turnover=item.get("turnover"),
            turnover_rate=item.get("turnover_rate"),
            volume_ratio=item.get("volume_ratio"),
            active_pool_rank=item.get("active_pool_rank"),
            b1_passed=item.get("b1_passed"),
            kdj_j=item.get("kdj_j"),
            verdict=item.get("verdict"),
            total_score=item.get("total_score"),
            signal_type=item.get("signal_type"),
            comment=item.get("comment"),
            pb=item.get("pb"),
            netprofit_yoy=item.get("netprofit_yoy"),
            roe=item.get("roe"),
            risk_flag=item.get("risk_flag"),
            consecutive_days=int(item.get("consecutive_days") or 1),
        )
        for item in payload.get("candidates", [])
    ]

    # -- result items --
    result_items = [
        CurrentHotAnalysisItem(
            id=item["id"],
            pick_date=payload.get("pick_date"),
            code=item["code"],
            name=item.get("name"),
            sector_names=item.get("sector_names") or [],
            board_group=item.get("board_group"),
            reviewer=item.get("reviewer"),
            b1_passed=item.get("b1_passed"),
            verdict=item.get("verdict"),
            total_score=item.get("total_score"),
            signal_type=item.get("signal_type"),
            comment=item.get("comment"),
            turnover_rate=item.get("turnover_rate"),
            volume_ratio=item.get("volume_ratio"),
            active_pool_rank=item.get("active_pool_rank"),
            prefilter_passed=item.get("prefilter_passed"),
            prefilter_summary=item.get("prefilter_summary"),
            prefilter_blocked_by=item.get("prefilter_blocked_by"),
            pb=item.get("pb"),
            netprofit_yoy=item.get("netprofit_yoy"),
            roe=item.get("roe"),
            pullback_quality=item.get("pullback_quality"),
            pullback_negative_flags=item.get("pullback_negative_flags"),
            risk_flag=item.get("risk_flag"),
        )
        for item in payload.get("results", [])
    ]

    # -- sector items --
    sector_items = [
        CurrentHotSectorSummaryItem(**item)
        for item in payload.get("sectors", [])
    ]
    sector_history_items = [
        CurrentHotSectorHistorySeries(**item)
        for item in payload.get("sector_history", [])
    ]

    latest_date_raw = payload.get("latest_date")
    pick_date_raw = payload.get("pick_date")
    sector_latest_raw = payload.get("sector_latest_date")
    sector_previous_raw = payload.get("sector_previous_date")

    return CurrentHotAggregateResponse(
        dates=payload.get("dates", []),
        history=history_items,
        latest_date=datetime.strptime(latest_date_raw, "%Y-%m-%d").date() if latest_date_raw else None,
        candidates=candidate_items,
        candidates_total=int(payload.get("candidates_total", 0) or 0),
        results=result_items,
        results_total=int(payload.get("results_total", 0) or 0),
        min_score_threshold=float(payload.get("min_score_threshold", 4.0) or 4.0),
        sectors=sector_items,
        sector_top_keys=payload.get("sector_top_keys", []),
        sector_dates=payload.get("sector_dates", []),
        sector_history=sector_history_items,
        sector_latest_date=datetime.strptime(sector_latest_raw, "%Y-%m-%d").date() if isinstance(sector_latest_raw, str) else sector_latest_raw,
        sector_previous_date=datetime.strptime(sector_previous_raw, "%Y-%m-%d").date() if isinstance(sector_previous_raw, str) else sector_previous_raw,
        sector_window_size=int(payload.get("sector_window_size", 0) or 0),
        risk_regime=payload.get("risk_regime"),
        pick_date=datetime.strptime(str(pick_date_raw), "%Y-%m-%d").date() if pick_date_raw else None,
        generated_at=payload.get("generated_at"),
        cache_hit=bool(payload.get("cache_hit")),
    )


@router.get(
    "/current-hot/dates",
    response_model=CurrentHotDatesResponse,
    deprecated=True,
    description="已废弃：请使用 /current-hot/aggregate 一次获取全部数据。",
)
@cached_current_hot_dates(ttl=180)
async def get_current_hot_dates(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotDatesResponse:
    ensure_analysis_read_available(db)
    payload = CurrentHotService(db).get_dates(window_size=CurrentHotService.DEFAULT_WINDOW_SIZE)
    history_items = [
        CurrentHotHistoryItem(
            pick_date=datetime.strptime(item["pick_date"], "%Y-%m-%d").date(),
            date=item["date"],
            candidate_count=int(item.get("candidate_count", 0) or 0),
            analysis_count=int(item.get("analysis_count", 0) or 0),
            trend_start_count=int(item.get("trend_start_count", 0) or 0),
            b1_pass_count=int(item.get("b1_pass_count", 0) or 0),
            consecutive_candidate_count=int(item.get("consecutive_candidate_count", 0) or 0),
            pass_count=int(item.get("pass_count", 0) or 0),
            status=item.get("status") or "missing",
            error_message=item.get("error_message"),
            is_latest=bool(item.get("is_latest")),
        )
        for item in payload.get("history", [])
    ]
    latest_date = payload.get("latest_date")
    return CurrentHotDatesResponse(
        dates=payload.get("dates", []),
        history=history_items,
        latest_date=datetime.strptime(latest_date, "%Y-%m-%d").date() if latest_date else None,
    )


@router.get(
    "/current-hot/candidates",
    response_model=CurrentHotCandidatesResponse,
    deprecated=True,
    description="已废弃：请使用 /current-hot/aggregate 一次获取全部数据。",
)
def get_current_hot_candidates(
    date: Optional[str] = None,
    limit: int = 3000,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotCandidatesResponse:
    ensure_analysis_read_available(db)
    payload = CurrentHotService(db).load_candidates(date, limit=limit)
    pick_date = payload.get("pick_date")
    items = [
        CurrentHotCandidateItem(
            id=item["id"],
            pick_date=pick_date,
            code=item["code"],
            name=item.get("name"),
            sector_names=item.get("sector_names") or [],
            board_group=item.get("board_group"),
            open_price=item.get("open_price"),
            close_price=item.get("close_price"),
            change_pct=item.get("change_pct"),
            turnover=item.get("turnover"),
            turnover_rate=item.get("turnover_rate"),
            volume_ratio=item.get("volume_ratio"),
            active_pool_rank=item.get("active_pool_rank"),
            b1_passed=item.get("b1_passed"),
            kdj_j=item.get("kdj_j"),
            verdict=item.get("verdict"),
            total_score=item.get("total_score"),
            signal_type=item.get("signal_type"),
            comment=item.get("comment"),
            pb=item.get("pb"),
            netprofit_yoy=item.get("netprofit_yoy"),
            roe=item.get("roe"),
            # risk_flag=item.get("risk_flag"),  # 已屏蔽
            consecutive_days=int(item.get("consecutive_days") or 1),
        )
        for item in payload.get("candidates", [])
    ]
    return CurrentHotCandidatesResponse(
        pick_date=pick_date,
        candidates=items,
        total=int(payload.get("total", 0) or 0),
        # risk_regime=payload.get("risk_regime"),  # 已屏蔽
    )


@router.get(
    "/current-hot/results",
    response_model=CurrentHotAnalysisResultResponse,
    deprecated=True,
    description="已废弃：请使用 /current-hot/aggregate 一次获取全部数据。",
)
def get_current_hot_results(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotAnalysisResultResponse:
    ensure_analysis_read_available(db)
    payload = CurrentHotService(db).get_results(date)
    pick_date = payload.get("pick_date")
    items = [
        CurrentHotAnalysisItem(
            id=item["id"],
            pick_date=pick_date,
            code=item["code"],
            name=item.get("name"),
            sector_names=item.get("sector_names") or [],
            board_group=item.get("board_group"),
            reviewer=item.get("reviewer"),
            b1_passed=item.get("b1_passed"),
            verdict=item.get("verdict"),
            total_score=item.get("total_score"),
            signal_type=item.get("signal_type"),
            comment=item.get("comment"),
            turnover_rate=item.get("turnover_rate"),
            volume_ratio=item.get("volume_ratio"),
            active_pool_rank=item.get("active_pool_rank"),
            prefilter_passed=item.get("prefilter_passed"),
            prefilter_summary=item.get("prefilter_summary"),
            prefilter_blocked_by=item.get("prefilter_blocked_by"),
            pb=item.get("pb"),
            netprofit_yoy=item.get("netprofit_yoy"),
            roe=item.get("roe"),
            pullback_quality=item.get("pullback_quality"),
            pullback_negative_flags=item.get("pullback_negative_flags"),
            # risk_flag=item.get("risk_flag"),  # 已屏蔽
        )
        for item in payload.get("results", [])
    ]
    return CurrentHotAnalysisResultResponse(
        pick_date=pick_date,
        results=items,
        total=int(payload.get("total", 0) or 0),
        min_score_threshold=float(payload.get("min_score_threshold", 4.0) or 4.0),
        # risk_regime=payload.get("risk_regime"),  # 已屏蔽
    )


@router.get(
    "/current-hot/sectors",
    response_model=CurrentHotSectorAnalysisResponse,
    deprecated=True,
    description="已废弃：请使用 /current-hot/aggregate 一次获取全部数据。",
)
def get_current_hot_sector_analysis(
    window_size: int = Query(CurrentHotService.DEFAULT_WINDOW_SIZE, ge=20, le=240),
    top_n: int = Query(5, ge=1, le=12),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotSectorAnalysisResponse:
    ensure_analysis_read_available(db)
    payload = CurrentHotService(db).get_sector_analysis(window_size=window_size, top_n=top_n)
    return CurrentHotSectorAnalysisResponse(**payload)


@router.get("/sector-analysis/overview", response_model=CurrentHotSectorAnalysisResponse)
def get_sector_analysis_overview(
    window_size: int = Query(SectorAnalysisService.DEFAULT_WINDOW_SIZE, ge=20, le=240),
    top_n: int = Query(5, ge=1, le=12),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotSectorAnalysisResponse:
    ensure_analysis_read_available(db)
    payload = SectorAnalysisService(db).get_sector_analysis(window_size=window_size, top_n=top_n)
    return CurrentHotSectorAnalysisResponse(**payload)


@router.get("/sector-analysis/rows", response_model=SectorAnalysisRowsResponse)
def get_sector_analysis_rows(
    sector_key: str = Query(..., description="板块标识"),
    date: Optional[str] = Query(default=None, description="交易日"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> SectorAnalysisRowsResponse:
    ensure_analysis_read_available(db)
    payload = SectorAnalysisService(db).get_sector_date_rows(sector_key=sector_key, pick_date=date)
    return SectorAnalysisRowsResponse(
        sector_key=str(payload.get("sector_key") or ""),
        pick_date=payload.get("pick_date"),
        rows=[
            SectorAnalysisRowItem(
                id=int(item.get("id") or 0),
                pick_date=payload.get("pick_date"),
                sector_key=str(payload.get("sector_key") or ""),
                code=str(item.get("code") or ""),
                name=item.get("name"),
                sector_names=item.get("sector_names") or [],
                board_group=item.get("board_group"),
                open_price=item.get("open_price"),
                close_price=item.get("close_price"),
                change_pct=item.get("change_pct"),
                turnover=item.get("turnover"),
                turnover_rate=item.get("turnover_rate"),
                volume_ratio=item.get("volume_ratio"),
                active_pool_rank=item.get("active_pool_rank"),
                b1_passed=item.get("b1_passed"),
                kdj_j=item.get("kdj_j"),
                verdict=item.get("verdict"),
                total_score=item.get("total_score"),
                signal_type=item.get("signal_type"),
                comment=item.get("comment"),
                prefilter_passed=item.get("prefilter_passed"),
                prefilter_summary=item.get("prefilter_summary"),
                prefilter_blocked_by=item.get("prefilter_blocked_by"),
                pullback_quality=item.get("pullback_quality"),
                pullback_negative_flags=item.get("pullback_negative_flags"),
            )
            for item in payload.get("rows", [])
        ],
        total=int(payload.get("total", 0) or 0),
    )


@router.post("/current-hot/generate")
def generate_current_hot(
    date: Optional[str] = Query(default=None, description="交易日"),
    reviewer: str = Query(default="quant", description="评审者类型"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    ensure_tushare_ready()
    result = CurrentHotService(db).generate_for_trade_date(date, reviewer=reviewer)
    # generate 成功后清除聚合缓存，确保后续请求拿到最新数据
    if result.get("status") == "ok":
        CurrentHotAggregateService.invalidate_cache()
    return result


@router.get("/current-hot/intraday/status")
def get_current_hot_intraday_status(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    service = CurrentHotIntradayAnalysisService(db)
    status = service.get_status(is_admin=False)
    return {
        "trade_date": status.trade_date,
        "source_pick_date": status.source_pick_date,
        "snapshot_time": status.snapshot_time,
        "window_open": status.window_open,
        "has_data": status.has_data,
        "status": status.status,
        "message": status.message,
    }


@router.get("/current-hot/intraday/data", response_model=CurrentHotIntradayAnalysisResponse)
def get_current_hot_intraday_data(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotIntradayAnalysisResponse:
    service = CurrentHotIntradayAnalysisService(db)
    payload = service.get_snapshot_payload(is_admin=False)
    return CurrentHotIntradayAnalysisResponse(**payload)


@router.post("/current-hot/intraday/generate", response_model=CurrentHotIntradayAnalysisGenerateResponse)
async def generate_current_hot_intraday(
    date: Optional[str] = Query(default=None, description="交易日，格式 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> CurrentHotIntradayAnalysisGenerateResponse:
    await ensure_tushare_ready_if_configured_async()
    service = CurrentHotIntradayAnalysisService(db)
    parsed_date = _parse_date_or_none(date)
    if date and parsed_date is None:
        raise HTTPException(status_code=400, detail="交易日格式错误，应为 YYYY-MM-DD")
    payload = service.generate_snapshot(trade_date=parsed_date)
    return CurrentHotIntradayAnalysisGenerateResponse(**payload)


@router.post("/current-hot/intraday/prefetch", response_model=CurrentHotIntradayAnalysisPrefetchResponse)
async def prefetch_current_hot_intraday(
    date: Optional[str] = Query(default=None, description="交易日，格式 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> CurrentHotIntradayAnalysisPrefetchResponse:
    await ensure_tushare_ready_if_configured_async()
    service = CurrentHotIntradayAnalysisService(db)
    parsed_date = _parse_date_or_none(date)
    if date and parsed_date is None:
        raise HTTPException(status_code=400, detail="交易日格式错误，应为 YYYY-MM-DD")
    payload = service.prefetch_snapshot_data(trade_date=parsed_date)
    return CurrentHotIntradayAnalysisPrefetchResponse(**payload)


@router.get("/closing-report/status", response_model=ClosingAnalysisStatusResponse)
def get_closing_analysis_status(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ClosingAnalysisStatusResponse:
    status = ClosingAnalysisService(db).get_status()
    running_task = (
        db.query(Task)
        .filter(
            Task.task_type == TaskService.CLOSING_ANALYSIS_TASK_TYPE,
            Task.status.in_(["pending", "running"]),
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
        .first()
    )
    return ClosingAnalysisStatusResponse(
        latest_data_date=status.latest_data_date,
        report_trade_date=status.report_trade_date,
        has_report=status.has_report,
        can_generate=status.can_generate,
        running_task_id=running_task.id if running_task else None,
        running_task_status=running_task.status if running_task else None,
        status=status.status,
        message=status.message,
    )


@router.get("/closing-report", response_model=ClosingAnalysisReportResponse)
def get_closing_analysis_report(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ClosingAnalysisReportResponse:
    payload = ClosingAnalysisService(db).get_latest_report_payload()
    return ClosingAnalysisReportResponse(**payload)


@router.get("/hot-topics", response_model=ClosingHotTopics)
def get_market_hot_topics(
    trade_date: Optional[str] = Query(default=None, description="交易日，格式 YYYY-MM-DD；为空时使用最新本地日线日期，若无日线则使用今天"),
    window_days: int = Query(default=3, ge=1, le=7, description="热点回看天数"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ClosingHotTopics:
    parsed_date = _parse_date_or_none(trade_date)
    if trade_date and parsed_date is None:
        raise HTTPException(status_code=400, detail="交易日格式错误，应为 YYYY-MM-DD")

    target_date = parsed_date or db.query(func.max(StockDaily.trade_date)).scalar() or date.today()
    closing_service = ClosingAnalysisService(db)
    sector_flow = closing_service._build_sector_flow(target_date)
    payload = HotNewsAggregatorService(
        db,
        tushare_service=closing_service.tushare_service,
        deepseek_service=closing_service.deepseek_service,
    ).get_market_hot_topics(
        trade_date=target_date,
        window_days=window_days,
        limit=12,
        sector_flow=sector_flow,
    )
    return ClosingHotTopics(**payload)


@router.post("/closing-report/generate", response_model=ClosingAnalysisReportResponse)
async def generate_closing_analysis_report(
    force: bool = Query(default=False, description="管理员强制重算当日收盘分析"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ClosingAnalysisReportResponse:
    is_admin = getattr(user, "role", None) == "admin"
    closing_service = ClosingAnalysisService(db)
    status = closing_service.get_status()

    if status.latest_data_date is None:
        return ClosingAnalysisReportResponse(
            has_report=False,
            generated=False,
            status="no_data",
            message="暂无日线数据，无法生成收盘分析",
        )

    if status.has_report and not (is_admin and force):
        payload = closing_service.get_latest_report_payload()
        payload.update({
            "generated": False,
            "status": "ready",
            "message": "当日收盘分析已生成，无需重复生成",
        })
        return ClosingAnalysisReportResponse(**payload)

    params = {
        "trade_date": status.latest_data_date.isoformat(),
        "user_id": getattr(user, "id", None),
        "is_admin": is_admin,
        "force": bool(force and is_admin),
        "allow_recreate": bool(force and is_admin),
        "trigger_source": "manual",
    }
    task_service = TaskService(db)
    task_result = await task_service.create_task(TaskService.CLOSING_ANALYSIS_TASK_TYPE, params)
    latest_payload = closing_service.get_latest_report_payload()
    latest_payload.update({
        "generated": False,
        "status": "generating",
        "message": "收盘分析任务已提交，后台生成中",
        "task_id": task_result.get("task_id"),
        "ws_url": task_result.get("ws_url"),
        "task_status": "running",
        "existing_task": bool(task_result.get("existing")),
    })
    return ClosingAnalysisReportResponse(**latest_payload)


@router.get("/intraday/status")
def get_intraday_analysis_status(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    service = IntradayAnalysisService(db)
    status = service.get_status(is_admin=False)
    return {
        "trade_date": status.trade_date,
        "source_pick_date": status.source_pick_date,
        "snapshot_time": status.snapshot_time,
        "window_open": status.window_open,
        "has_data": status.has_data,
        "status": status.status,
        "message": status.message,
    }


@router.get("/intraday/data", response_model=IntradayAnalysisResponse)
def get_intraday_analysis_data(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> IntradayAnalysisResponse:
    service = IntradayAnalysisService(db)
    payload = service.get_snapshot_payload(is_admin=False)
    return IntradayAnalysisResponse(**payload)


@router.post("/intraday/generate", response_model=IntradayAnalysisGenerateResponse)
async def generate_intraday_analysis(
    date: Optional[str] = Query(default=None, description="交易日，格式 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> IntradayAnalysisGenerateResponse:
    await ensure_tushare_ready_if_configured_async()
    service = IntradayAnalysisService(db)
    parsed_date = _parse_date_or_none(date)
    if date and parsed_date is None:
        raise HTTPException(status_code=400, detail="交易日格式错误，应为 YYYY-MM-DD")
    payload = service.generate_snapshot(trade_date=parsed_date)
    return IntradayAnalysisGenerateResponse(**payload)


@router.post("/intraday/prefetch", response_model=IntradayAnalysisPrefetchResponse)
async def prefetch_intraday_analysis(
    date: Optional[str] = Query(default=None, description="交易日，格式 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> IntradayAnalysisPrefetchResponse:
    await ensure_tushare_ready_if_configured_async()
    service = IntradayAnalysisService(db)
    parsed_date = _parse_date_or_none(date)
    if date and parsed_date is None:
        raise HTTPException(status_code=400, detail="交易日格式错误，应为 YYYY-MM-DD")
    payload = service.prefetch_snapshot_data(trade_date=parsed_date)
    return IntradayAnalysisPrefetchResponse(**payload)


@router.get("/diagnosis/{code}/history", response_model=DiagnosisHistoryResponse)
async def get_diagnosis_history(
    code: str,
    days: int = DIAGNOSIS_HISTORY_WINDOW_DAYS,
    page: int = 1,
    page_size: int = 10,
    refresh: bool = Query(default=False, description="是否同步补齐当前页历史数据"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> DiagnosisHistoryResponse:
    """获取单股诊断历史，优先读取 Redis 缓存，缺失时回源并补齐缓存。"""
    code = code.zfill(6)
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), days, 50))
    days = max(1, min(int(days), DIAGNOSIS_HISTORY_WINDOW_DAYS))

    if refresh:
        result = await _run_history_generation(
            code,
            analysis_service.ensure_history_page,
            code,
            days=days,
            page=page,
            page_size=page_size,
            force=True,
        )
        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "刷新历史数据失败"))
        diagnosis_history_cache_service.invalidate(code)

    try:
        payload = diagnosis_history_cache_service.get_page(
            code,
            days=days,
            page=page,
            page_size=page_size,
            force=refresh,
            generate_if_missing=False,
        )
    except Exception as exc:
        logger.warning("诊断历史缓存读取失败，回退到只读 DB 查询: code=%s error=%s", code, exc)
        history, total = analysis_service.get_stock_history_checks(code, days, page, page_size)
        stock_name = db.query(Stock.name).filter(Stock.code == code).scalar()
        payload = {
            "code": code,
            "name": stock_name,
            "history": history,
            "total": total,
            "generated_count": len(history),
            "trend_start_dates": [
                str(item.get("check_date"))[:10]
                for item in history
                if item.get("signal_type") == "trend_start" and item.get("check_date")
            ],
            "tomorrow_star_dates": [
                str(item.get("check_date"))[:10]
                for item in history
                if item.get("tomorrow_star_pass") is True and item.get("check_date")
            ],
        }

    return DiagnosisHistoryResponse(
        code=code,
        name=payload.get("name"),
        history=[B1CheckItem.model_validate(h) for h in payload.get("history", [])],
        total=int(payload.get("total") or 0),
        page=page,
        page_size=page_size,
        trend_start_dates=payload.get("trend_start_dates") or [],
        tomorrow_star_dates=payload.get("tomorrow_star_dates") or [],
        data_ready=int(payload.get("generated_count") or len(payload.get("history", []))) > 0,
        message="暂无历史数据，请先执行历史数据生成任务"
        if int(payload.get("generated_count") or len(payload.get("history", []))) == 0
        else None,
    )


@router.post("/diagnosis/{code}/generate-history")
async def generate_diagnosis_history(
    code: str,
    days: int = Query(default=DIAGNOSIS_HISTORY_WINDOW_DAYS, description="生成最近N个交易日的历史数据"),
    page: int = Query(default=1, description="当前页码"),
    page_size: int = Query(default=10, description="当前页大小"),
    force: bool = Query(default=False, description="是否强制刷新当前页"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """同步刷新单股诊断历史数据，并更新 Redis 缓存。"""
    code = code.zfill(6)
    page = max(1, int(page))
    days = max(1, min(int(days), DIAGNOSIS_HISTORY_WINDOW_DAYS))
    page_size = max(1, min(int(page_size), days, 50))
    result = await _run_history_generation(
        code,
        analysis_service.ensure_history_page,
        code,
        days=days,
        page=page,
        page_size=page_size,
        force=force,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "刷新历史数据失败"))
    diagnosis_history_cache_service.invalidate(code)
    cached_payload = diagnosis_history_cache_service.ensure_cached(code, days=days, force=True, generate_if_missing=False)

    return {
        "code": code,
        "status": "updated" if result.get("updated") or result.get("generated_count") else "ready",
        "page": page,
        "page_size": page_size,
        "generated_count": result.get("generated_count", 0),
        "generated_dates": result.get("generated_dates", []),
        "latest_trade_date": result.get("latest_trade_date"),
        "latest_history_date": result.get("latest_history_date"),
        "total": cached_payload.get("total", 0),
        "message": "诊断历史数据已刷新" if result.get("updated") or result.get("generated_count") else "诊断历史数据已是最新",
    }


@router.get("/diagnosis/{code}/history-status")
async def get_history_status(
    code: str,
    days: int = DIAGNOSIS_HISTORY_WINDOW_DAYS,
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """获取历史数据生成状态"""
    code = code.zfill(6)
    page = max(1, int(page))
    days = max(1, min(int(days), DIAGNOSIS_HISTORY_WINDOW_DAYS))
    page_size = max(1, min(int(page_size), days, 50))
    refresh_status = analysis_service.get_history_refresh_status(
        code,
        days=days,
        page=page,
        page_size=page_size,
    )
    count = db.query(DailyB1Check).filter(DailyB1Check.code == code).count()
    latest_detail = (
        db.query(DailyB1CheckDetail)
        .filter(DailyB1CheckDetail.code == code)
        .order_by(DailyB1CheckDetail.updated_at.desc(), DailyB1CheckDetail.id.desc())
        .first()
    )
    generating = await _is_history_generation_active(code)
    return {
        "exists": count > 0,
        "generating": generating,
        "count": count,
        "total": refresh_status.get("total", 0),
        "page": page,
        "page_size": page_size,
        "needs_refresh": refresh_status.get("needs_refresh", False),
        "latest_trade_date": refresh_status.get("latest_trade_date"),
        "latest_history_date": refresh_status.get("latest_history_date"),
        "generated_at": latest_detail.updated_at.isoformat() if latest_detail and latest_detail.updated_at else None,
    }


@router.get("/diagnosis/{code}/history/{check_date}", response_model=DiagnosisHistoryDetailResponse)
def get_diagnosis_history_detail(
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

    code = request.code.zfill(6)

    # 创建后台分析任务
    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)
    result = await task_service.create_task(
        "single_analysis",
        {
            "code": code,
            "reviewer": "quant",
            "trigger_source": "manual",
            "allow_remote_fetch": getattr(user, "role", "") == "admin",
        },
    )

    return {
        "task_id": result["task_id"],
        "code": code,
        "status": "pending" if not result.get("existing") else "existing",
        "ws_url": result["ws_url"],
        "message": "分析任务已创建" if not result.get("existing") else "正在初始化，请等待",
    }


@router.get("/diagnosis/{code}/result")
def get_analysis_result(code: str, db: Session = Depends(get_db), user=Depends(require_user)) -> dict:
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

    # 获取股票信息，优先使用本地库，避免结果轮询时阻塞等待 Tushare。
    stock = db.query(Stock).filter(Stock.code == code).first()
    if stock is None and getattr(user, "role", "") == "admin":
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
    latest_history = _get_latest_history_summary(db, code)
    if latest_history:
        result_json = {
            **result_json,
            "check_date": latest_history.get("check_date") or result_json.get("check_date"),
            "analysis_date": latest_history.get("check_date") or result_json.get("analysis_date"),
            "close_price": latest_history.get("close_price"),
            "b1_passed": latest_history.get("b1_passed"),
            "score": latest_history.get("score"),
            "verdict": latest_history.get("verdict"),
            "kdj_j": latest_history.get("kdj_j"),
            "zx_long_pos": latest_history.get("zx_long_pos"),
            "weekly_ma_aligned": latest_history.get("weekly_ma_aligned"),
            "volume_healthy": latest_history.get("volume_healthy"),
            "active_pool_rank": latest_history.get("active_pool_rank"),
            "turnover_rate": latest_history.get("turnover_rate"),
            "volume_ratio": latest_history.get("volume_ratio"),
            "in_active_pool": latest_history.get("in_active_pool"),
            "signal_type": latest_history.get("signal_type"),
            "b1_signal_type": latest_history.get("b1_signal_type"),
        }

    # 风险识别功能已暂时屏蔽
    # risk_flag = _build_diagnosis_risk_flag(...)
    # risk_regime = _build_diagnosis_risk_regime(...)

    return {
        "code": code,
        "name": stock.name if stock else None,
        "status": "completed",
        "task_id": task.id,
        "current_price": result_json.get("close_price"),
        "b1_passed": result_json.get("b1_passed"),
        "score": result_json.get("score"),
        "verdict": result_json.get("verdict"),
        # "risk_regime": risk_regime,  # 已屏蔽
        "analysis": {
            "kdj_j": result_json.get("kdj_j"),
            "zx_long_pos": result_json.get("zx_long_pos"),
            "weekly_ma_aligned": result_json.get("weekly_ma_aligned"),
            "volume_healthy": result_json.get("volume_healthy"),
            "active_pool_rank": result_json.get("active_pool_rank"),
            "turnover_rate": result_json.get("turnover_rate"),
            "volume_ratio": result_json.get("volume_ratio"),
            "in_active_pool": result_json.get("in_active_pool"),
            "b1_signal_type": result_json.get("b1_signal_type"),
            "scores": result_json.get("scores"),
            "trend_reasoning": result_json.get("trend_reasoning"),
            "position_reasoning": result_json.get("position_reasoning"),
            "volume_reasoning": result_json.get("volume_reasoning"),
            "abnormal_move_reasoning": result_json.get("abnormal_move_reasoning"),
            "signal_type": result_json.get("signal_type"),
            "signal_reasoning": result_json.get("signal_reasoning"),
            "comment": result_json.get("comment"),
            # "risk_flag": risk_flag,  # 已屏蔽
        },
    }


@router.post("/diagnosis/{code}/ai-analysis", response_model=StockAiAnalysisResponse)
def analyze_stock_with_ai(
    code: str,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> StockAiAnalysisResponse:
    try:
        return StockAiAnalysisService(db).analyze(code)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tomorrow-star/generate")
async def generate_tomorrow_star(
    reviewer: str = Query(default="quant", description="评审者类型"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """手动生成明日之星"""
    await ensure_tushare_ready_async()
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


def _get_next_trade_date(db: Session, pick_date: date) -> Optional[date]:
    """获取下一个交易日"""
    next_date = db.query(StockDaily.trade_date).filter(
        StockDaily.trade_date > pick_date
    ).order_by(StockDaily.trade_date.asc()).first()
    return next_date[0] if next_date else None


def _get_trade_date_offset(db: Session, base_date: date, offset_days: int, code: Optional[str] = None) -> Optional[date]:
    """获取指定日期后N个交易日的日期

    Args:
        db: 数据库会话
        base_date: 基准日期
        offset_days: 偏移交易日数
        code: 股票代码（可选，如果指定则按该股票的交易日历计算）
    """
    query = db.query(StockDaily.trade_date).filter(
        StockDaily.trade_date > base_date
    )
    if code:
        query = query.filter(StockDaily.code == code)
    dates = query.order_by(StockDaily.trade_date.asc()).limit(offset_days).all()
    if len(dates) >= offset_days:
        return dates[offset_days - 1][0]
    return None


def _calculate_return(buy_price: float, current_price: float) -> float:
    """计算收益率"""
    if buy_price is None or current_price is None or buy_price == 0:
        return None
    return round((current_price - buy_price) / buy_price * 100, 2)


def _get_stock_open_price(db: Session, code: str, trade_date: date) -> Optional[float]:
    """获取股票在指定交易日的开盘价"""
    record = db.query(StockDaily.open).filter(
        StockDaily.code == code,
        StockDaily.trade_date == trade_date
    ).first()
    return record[0] if record else None


def _get_stock_close_price(db: Session, code: str, trade_date: date) -> Optional[float]:
    """获取股票在指定交易日的收盘价"""
    record = db.query(StockDaily.close).filter(
        StockDaily.code == code,
        StockDaily.trade_date == trade_date
    ).first()
    return record[0] if record else None


def _get_stock_prices_range(db: Session, code: str, start_date: date, end_date: date) -> List[tuple]:
    """获取股票在指定日期区间内的价格数据（日期，最高价，最低价，收盘价）"""
    records = db.query(
        StockDaily.trade_date,
        StockDaily.high,
        StockDaily.low,
        StockDaily.close
    ).filter(
        StockDaily.code == code,
        StockDaily.trade_date >= start_date,
        StockDaily.trade_date <= end_date
    ).order_by(StockDaily.trade_date.asc()).all()
    return records


def _get_stock_trade_dates_range(db: Session, code: str, start_date: date, end_date: date) -> List[date]:
    """获取股票在指定日期区间内的交易日列表。"""
    rows = db.query(
        StockDaily.trade_date
    ).filter(
        StockDaily.code == code,
        StockDaily.trade_date >= start_date,
        StockDaily.trade_date <= end_date
    ).order_by(StockDaily.trade_date.asc()).all()
    return [row[0] for row in rows if row and row[0]]


def _get_signal_return_benchmark_store() -> TushareMetadataStore | None:
    """获取历史收益分析使用的大盘基准缓存。"""
    global _signal_return_benchmark_store
    if _signal_return_benchmark_store is not None:
        return _signal_return_benchmark_store

    token = os.environ.get("TUSHARE_TOKEN") or getattr(settings, "tushare_token", "")
    if not token:
        return None

    try:
        _signal_return_benchmark_store = TushareMetadataStore(
            cache_dir=ROOT / "data" / "tushare_cache",
            token=token,
        )
    except Exception:
        logger.warning("初始化历史收益分析基准缓存失败", exc_info=True)
        _signal_return_benchmark_store = None
    return _signal_return_benchmark_store


def _build_signal_return_benchmark_series(
    start_date: date,
    end_date: date,
    *,
    allow_remote_fetch: bool = True,
) -> tuple[Optional[SignalReturnBenchmark], dict[date, tuple[Optional[float], Optional[float]]]]:
    """获取大盘基准曲线与按日期索引的收益率。"""
    if not allow_remote_fetch:
        return None, {}

    store = _get_signal_return_benchmark_store()
    if store is None:
        return None, {}

    try:
        frame = store.index_daily(
            SIGNAL_RETURN_BENCHMARK["ts_code"],
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d"),
        )
    except Exception:
        logger.warning("获取历史收益分析基准数据失败", exc_info=True)
        return None, {}

    if frame is None or frame.empty:
        return None, {}

    normalized = frame.copy()
    normalized.columns = [str(col).lower() for col in normalized.columns]
    if "trade_date" not in normalized.columns or "close" not in normalized.columns:
        return None, {}

    trade_dates = pd.to_datetime(
        normalized["trade_date"].astype(str).str.replace("-", "", regex=False).str.replace("/", "", regex=False),
        format="%Y%m%d",
        errors="coerce",
    )
    if trade_dates.isna().all():
        trade_dates = pd.to_datetime(normalized["trade_date"], errors="coerce")
    normalized["trade_date"] = trade_dates.dt.date
    normalized["close"] = pd.to_numeric(normalized["close"], errors="coerce")
    normalized = normalized.dropna(subset=["trade_date", "close"]).sort_values("trade_date").reset_index(drop=True)
    if normalized.empty:
        return None, {}

    base_rows = normalized[normalized["trade_date"] == start_date]
    if base_rows.empty:
        base_rows = normalized[normalized["trade_date"] <= start_date].tail(1)
    if base_rows.empty:
        base_rows = normalized.head(1)

    base_row = base_rows.iloc[0]
    base_close = float(base_row["close"])
    if not math.isfinite(base_close) or base_close == 0:
        return None, {}

    base_date = base_row["trade_date"]
    benchmark = SignalReturnBenchmark(
        name=SIGNAL_RETURN_BENCHMARK["name"],
        ts_code=SIGNAL_RETURN_BENCHMARK["ts_code"],
        base_date=base_date,
        base_close=round(base_close, 2),
    )

    benchmark_points: dict[date, tuple[Optional[float], Optional[float]]] = {}
    for row in normalized.itertuples(index=False):
        trade_date = getattr(row, "trade_date", None)
        close = getattr(row, "close", None)
        if not isinstance(trade_date, date):
            continue
        if close is None or not math.isfinite(float(close)):
            continue
        close_value = round(float(close), 2)
        benchmark_points[trade_date] = (
            close_value,
            _calculate_return(base_close, close_value),
        )

    return benchmark, benchmark_points


def _ensure_signal_return_history_ready(
    db: Session,
    code: str,
    *,
    buy_date: Optional[date],
    stock_current_date: Optional[date],
) -> None:
    """按需补齐 signal-return 依赖的历史诊断数据，避免结果留白。"""
    if buy_date is None or stock_current_date is None or stock_current_date <= buy_date:
        return

    target_dates = [
        item for item in _get_stock_trade_dates_range(db, code, buy_date, stock_current_date)
        if item > buy_date
    ]
    if not target_dates:
        return

    existing_dates = {
        row[0]
        for row in (
            db.query(DailyB1Check.check_date)
            .join(
                DailyB1CheckDetail,
                (DailyB1CheckDetail.code == DailyB1Check.code)
                & (DailyB1CheckDetail.check_date == DailyB1Check.check_date),
            )
            .filter(
                DailyB1Check.code == code,
                DailyB1Check.check_date.in_(target_dates),
                DailyB1CheckDetail.status == "ready",
            )
            .all()
        )
        if row and row[0]
    }
    missing_dates = [item for item in target_dates if item not in existing_dates]
    if not missing_dates:
        return

    result = analysis_service.ensure_history_dates(code, missing_dates)
    if not result.get("success"):
        logger.warning(
            "signal return precompute failed code=%s buy_date=%s current_date=%s error=%s",
            code,
            buy_date,
            stock_current_date,
            result.get("error"),
        )


def _is_tomorrow_star(details_json: Optional[dict[str, Any]], verdict: Optional[str], signal_type: Optional[str]) -> bool:
    """判断是否是明日之星"""
    if not isinstance(details_json, dict):
        return False

    # 首先检查显式的tomorrow_star_pass
    direct = details_json.get("tomorrow_star_pass")
    if isinstance(direct, bool):
        return direct

    rules = details_json.get("rules")
    if isinstance(rules, dict) and isinstance(rules.get("tomorrow_star_pass"), bool):
        return rules["tomorrow_star_pass"]

    details = details_json.get("details")
    if isinstance(details, dict) and isinstance(details.get("tomorrow_star_pass"), bool):
        return details["tomorrow_star_pass"]

    # 如果没有显式标记，使用推导逻辑
    prefilter = details_json.get("prefilter", {})
    prefilter_passed = prefilter.get("passed") if isinstance(prefilter, dict) else None

    if prefilter_passed is None:
        return False

    return bool(prefilter_passed and verdict == "PASS" and signal_type == "trend_start")


@router.get("/signal-returns/{source}/{signal_type}/{pick_date}", response_model=SignalReturnAnalysisResponse)
def get_signal_returns(
    source: str,
    signal_type: str,
    pick_date: str,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> SignalReturnAnalysisResponse:
    """
    获取历史信号收益率分析

    参数:
    - source: "tomorrow_star" | "current_hot"
    - signal_type: "trend_start" | "tomorrow_star"
    - pick_date: 信号日期 (YYYY-MM-DD)
    """
    try:
        target_date = datetime.strptime(pick_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD 格式")

    # 验证参数
    if source not in ["tomorrow_star", "current_hot"]:
        raise HTTPException(status_code=400, detail="source 参数必须是 tomorrow_star 或 current_hot")
    if signal_type not in ["trend_start", "tomorrow_star"]:
        raise HTTPException(status_code=400, detail="signal_type 参数必须是 trend_start 或 tomorrow_star")

    # 获取下一个交易日（买入日）
    buy_date = _get_next_trade_date(db, target_date)
    if not buy_date:
        raise HTTPException(status_code=404, detail="未找到下一个交易日数据")

    # 获取股票代码列表
    stock_codes = []
    stock_names = {}

    if source == "tomorrow_star":
        # 从 AnalysisResult 获取
        query = db.query(AnalysisResult.code, Stock.name, AnalysisResult.details_json, AnalysisResult.verdict, AnalysisResult.signal_type).join(
            Stock, AnalysisResult.code == Stock.code
        ).filter(AnalysisResult.pick_date == target_date)

        if signal_type == "trend_start":
            query = query.filter(AnalysisResult.signal_type == "trend_start")
            results = query.all()
            stock_codes = [r[0] for r in results]
            stock_names = {r[0]: r[1] for r in results}
        else:  # tomorrow_star - 需要从details_json中提取
            results = query.all()
            # 过滤出明日之星的记录
            stock_codes = []
            stock_names = {}
            for r in results:
                details_json = r[2]
                verdict = r[3]
                sig_type = r[4]
                if _is_tomorrow_star(details_json, verdict, sig_type):
                    stock_codes.append(r[0])
                    stock_names[r[0]] = r[1]

    else:  # current_hot
        query = db.query(CurrentHotAnalysisResult.code, Stock.name, CurrentHotAnalysisResult.details_json, CurrentHotAnalysisResult.verdict, CurrentHotAnalysisResult.signal_type).join(
            Stock, CurrentHotAnalysisResult.code == Stock.code
        ).filter(CurrentHotAnalysisResult.pick_date == target_date)

        if signal_type == "trend_start":
            query = query.filter(CurrentHotAnalysisResult.signal_type == "trend_start")
            results = query.all()
            stock_codes = [r[0] for r in results]
            stock_names = {r[0]: r[1] for r in results}
        else:  # tomorrow_star - 需要从details_json中提取
            results = query.all()
            # 过滤出明日之星的记录
            stock_codes = []
            stock_names = {}
            for r in results:
                details_json = r[2]
                verdict = r[3]
                sig_type = r[4]
                if _is_tomorrow_star(details_json, verdict, sig_type):
                    stock_codes.append(r[0])
                    stock_names[r[0]] = r[1]

    if not stock_codes:
        return SignalReturnAnalysisResponse(
            pick_date=target_date,
            signal_type=signal_type,
            signal_label="启动" if signal_type == "trend_start" else "明日之星",
            source=source,
            stocks=[],
            total=0,
        )

    # 计算每个股票的收益率
    stock_contexts: list[dict[str, Any]] = []
    day5_returns = []
    day10_returns = []
    day15_returns = []
    current_returns = []
    benchmark_end_date = buy_date

    for code in stock_codes:
        # 获取该股票的买入价格（开盘价）
        buy_price = _get_stock_open_price(db, code, buy_date)

        # 获取该股票各个持有期的结束日期（按该股票的交易日历）
        day5_date = _get_trade_date_offset(db, buy_date, 5, code)
        day10_date = _get_trade_date_offset(db, buy_date, 10, code)
        day15_date = _get_trade_date_offset(db, buy_date, 15, code)

        # 获取该股票的最新交易日日期
        stock_latest_date_record = db.query(StockDaily.trade_date).filter(
            StockDaily.code == code
        ).order_by(StockDaily.trade_date.desc()).first()
        stock_current_date = stock_latest_date_record[0] if stock_latest_date_record else None

        _ensure_signal_return_history_ready(
            db,
            code,
            buy_date=buy_date,
            stock_current_date=stock_current_date,
        )

        # 获取各期价格（收盘价）
        day5_price = _get_stock_close_price(db, code, day5_date) if day5_date else None
        day10_price = _get_stock_close_price(db, code, day10_date) if day10_date else None
        day15_price = _get_stock_close_price(db, code, day15_date) if day15_date else None
        current_price = _get_stock_close_price(db, code, stock_current_date) if stock_current_date else None

        # 计算收益率
        day5_return = _calculate_return(buy_price, day5_price) if (buy_price and day5_price) else None
        day10_return = _calculate_return(buy_price, day10_price) if (buy_price and day10_price) else None
        day15_return = _calculate_return(buy_price, day15_price) if (buy_price and day15_price) else None
        current_return = _calculate_return(buy_price, current_price) if (buy_price and current_price) else None

        # 获取持有期间所有价格数据，计算最大收益和最大亏损
        max_return = None
        max_return_date = None
        max_loss = None
        max_loss_date = None

        price_records: list[tuple] = []
        if stock_current_date and buy_price:
            price_records = _get_stock_prices_range(db, code, buy_date, stock_current_date)
            if price_records:
                for trade_date, high, low, close in price_records:
                    # 用最高价计算最大收益
                    if high:
                        high_return = _calculate_return(buy_price, high)
                        if max_return is None or (high_return is not None and high_return > max_return):
                            max_return = high_return
                            max_return_date = trade_date

                    # 用最低价计算最大亏损
                    if low:
                        low_return = _calculate_return(buy_price, low)
                        if max_loss is None or (low_return is not None and low_return < max_loss):
                            max_loss = low_return
                            max_loss_date = trade_date

        # 查找信号转为fail的日期
        fail_date = None
        fail_return = None
        fail_sell_date = None

        # 查询该股票从buy_date之后的DailyB1Check记录
        check_records = db.query(DailyB1Check, DailyB1CheckDetail).join(
            DailyB1CheckDetail,
            (DailyB1CheckDetail.code == DailyB1Check.code) &
            (DailyB1CheckDetail.check_date == DailyB1Check.check_date)
        ).filter(
            DailyB1Check.code == code,
            DailyB1Check.check_date > buy_date
        ).order_by(DailyB1Check.check_date.asc()).all()

        for check, detail in check_records:
            # 检查是否转为fail
            is_fail = False

            # 从detail的score_details_json中获取verdict
            if detail and isinstance(detail.score_details_json, dict):
                verdict = detail.score_details_json.get('verdict')
                if verdict != 'PASS':
                    is_fail = True

            # 检查tomorrow_star_pass
            if not is_fail and detail and isinstance(detail.rules_json, dict):
                tomorrow_star_pass = detail.rules_json.get('tomorrow_star_pass')
                if tomorrow_star_pass is False:
                    is_fail = True

            if is_fail:
                fail_date = check.check_date
                # 获取fail次日开盘价
                next_trade_date = _get_next_trade_date(db, fail_date)
                if next_trade_date:
                    fail_sell_date = next_trade_date
                    fail_sell_price = _get_stock_open_price(db, code, fail_sell_date)
                    if fail_sell_price and buy_price:
                        fail_return = _calculate_return(buy_price, fail_sell_price)
                break

        # 收集用于计算平均值
        if day5_return is not None:
            day5_returns.append(day5_return)
        if day10_return is not None:
            day10_returns.append(day10_return)
        if day15_return is not None:
            day15_returns.append(day15_return)
        if current_return is not None:
            current_returns.append(current_return)

        if stock_current_date and stock_current_date > benchmark_end_date:
            benchmark_end_date = stock_current_date

        stock_contexts.append({
            "code": code,
            "name": stock_names.get(code),
            "buy_price": buy_price,
            "day5_date": day5_date,
            "day5_price": day5_price,
            "day5_return": day5_return,
            "day10_date": day10_date,
            "day10_price": day10_price,
            "day10_return": day10_return,
            "day15_date": day15_date,
            "day15_price": day15_price,
            "day15_return": day15_return,
            "current_price": current_price,
            "current_return": current_return,
            "max_return": max_return,
            "max_return_date": max_return_date,
            "max_loss": max_loss,
            "max_loss_date": max_loss_date,
            "fail_return": fail_return,
            "fail_date": fail_date,
            "fail_sell_date": fail_sell_date,
            "stock_current_date": stock_current_date,
            "price_records": price_records,
        })

    benchmark_meta, benchmark_points = _build_signal_return_benchmark_series(
        buy_date,
        benchmark_end_date,
        allow_remote_fetch=getattr(user, "role", "") == "admin",
    )

    stock_returns = []
    for context in stock_contexts:
        price_lookup: dict[date, tuple[Optional[float], Optional[float], Optional[float]]] = {}
        for trade_date, high, low, close in context["price_records"]:
            price_lookup[trade_date] = (high, low, close)

        timeline: list[SignalReturnTimelinePoint] = []
        for trade_date, high, low, close in context["price_records"]:
            benchmark_close, benchmark_return = benchmark_points.get(trade_date, (None, None))
            stock_return = _calculate_return(context["buy_price"], close) if context["buy_price"] and close else None
            timeline.append(
                SignalReturnTimelinePoint(
                    trade_date=trade_date,
                    close_price=round(float(close), 2) if close is not None and math.isfinite(float(close)) else None,
                    return_pct=stock_return,
                    benchmark_close=benchmark_close,
                    benchmark_return_pct=benchmark_return,
                )
            )

        def _build_event(
            key: str,
            label: str,
            event_date: Optional[date],
            price: Optional[float],
            return_pct: Optional[float],
        ) -> Optional[SignalReturnEventPoint]:
            if event_date is None:
                return None
            benchmark_return = benchmark_points.get(event_date, (None, None))[1]
            price_value = round(float(price), 2) if price is not None and math.isfinite(float(price)) else None
            return SignalReturnEventPoint(
                key=key,
                label=label,
                trade_date=event_date,
                price=price_value,
                return_pct=return_pct,
                benchmark_return_pct=benchmark_return,
            )

        fail_close_price = None
        if context["fail_date"] is not None:
            fail_close_price = price_lookup.get(context["fail_date"], (None, None, None))[2]

        events = [
            _build_event("day5", "5日", context["day5_date"], context["day5_price"], context["day5_return"]),
            _build_event("day10", "10日", context["day10_date"], context["day10_price"], context["day10_return"]),
            _build_event("day15", "15日", context["day15_date"], context["day15_price"], context["day15_return"]),
            _build_event("max_return", "Max收益", context["max_return_date"], price_lookup.get(context["max_return_date"], (None, None, None))[0] if context["max_return_date"] else None, context["max_return"]),
            _build_event("max_loss", "Max亏损", context["max_loss_date"], price_lookup.get(context["max_loss_date"], (None, None, None))[1] if context["max_loss_date"] else None, context["max_loss"]),
            _build_event("fail", "Fail首次出现", context["fail_date"], fail_close_price, _calculate_return(context["buy_price"], fail_close_price) if context["buy_price"] and fail_close_price else None),
            _build_event("fail_sell", "次日开盘卖点", context["fail_sell_date"], _get_stock_open_price(db, context["code"], context["fail_sell_date"]) if context["fail_sell_date"] else None, context["fail_return"]),
        ]
        event_points = [item for item in events if item is not None]
        event_points.sort(key=lambda item: (item.trade_date, item.key))

        stock_returns.append(
            SignalReturnItem(
                code=context["code"],
                name=context["name"],
                pick_date=target_date,
                buy_date=buy_date,
                buy_price=context["buy_price"],
                day5_return=context["day5_return"],
                day10_return=context["day10_return"],
                day15_return=context["day15_return"],
                current_return=context["current_return"],
                max_return=context["max_return"],
                max_return_date=context["max_return_date"],
                max_loss=context["max_loss"],
                max_loss_date=context["max_loss_date"],
                fail_return=context["fail_return"],
                fail_date=context["fail_date"],
                fail_sell_date=context["fail_sell_date"],
                current_price=context["current_price"],
                timeline=timeline,
                events=event_points,
            )
        )

    # 计算平均收益率
    avg_day5_return = round(sum(day5_returns) / len(day5_returns), 2) if day5_returns else None
    avg_day10_return = round(sum(day10_returns) / len(day10_returns), 2) if day10_returns else None
    avg_day15_return = round(sum(day15_returns) / len(day15_returns), 2) if day15_returns else None
    avg_current_return = round(sum(current_returns) / len(current_returns), 2) if current_returns else None

    return SignalReturnAnalysisResponse(
        pick_date=target_date,
        signal_type=signal_type,
        signal_label="启动" if signal_type == "trend_start" else "明日之星",
        source=source,
        benchmark=benchmark_meta,
        stocks=stock_returns,
        total=len(stock_returns),
        avg_day5_return=avg_day5_return,
        avg_day10_return=avg_day10_return,
        avg_day15_return=avg_day15_return,
        avg_current_return=avg_current_return,
    )


# ==================== 概念板块相关 API ====================

@router.get("/concepts/list", response_model=ConceptsResponse)
async def get_concepts_list(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ConceptsResponse:
    """获取概念板块列表"""
    await ensure_tushare_ready_async()
    service = TushareService()
    concepts = await asyncio.to_thread(service.get_concept_list)
    return ConceptsResponse(
        concepts=[ConceptInfo(**c) for c in concepts],
        total=len(concepts),
    )


@router.get("/concepts/stock/{code}", response_model=StockConceptsResponse)
async def get_stock_concepts(
    code: str,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> StockConceptsResponse:
    """获取股票所属的概念板块"""
    await ensure_tushare_ready_async()
    code = code.zfill(6)

    # 获取股票的 ts_code
    stock = db.query(Stock).filter(Stock.code == code).first()
    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")

    # 构建 ts_code
    ts_code = f"{code}.{stock.market}" if stock.market else f"{code}.SZ"

    service = TushareService()
    concepts = await asyncio.to_thread(service.get_stock_concepts, ts_code)

    return StockConceptsResponse(
        stocks={code: concepts},
        total=len(concepts),
    )


@router.get("/concepts/batch", response_model=StockConceptsResponse)
async def get_stocks_concepts_batch(
    codes: str = Query(..., description="股票代码列表，逗号分隔"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> StockConceptsResponse:
    """批量获取股票所属的概念板块"""
    await ensure_tushare_ready_async()

    code_list = [c.zfill(6) for c in codes.split(",") if c.strip()]
    if not code_list:
        return StockConceptsResponse(stocks={}, total=0)

    # 获取股票的 ts_code 列表
    stocks = db.query(Stock).filter(Stock.code.in_(code_list)).all()
    stock_map = {s.code: s for s in stocks}

    service = TushareService()
    result: dict[str, List[str]] = {}

    def load_concepts_batch() -> dict[str, List[str]]:
        batch_result: dict[str, List[str]] = {}
        for code in code_list:
            stock = stock_map.get(code)
            if stock:
                ts_code = f"{code}.{stock.market}" if stock.market else f"{code}.SZ"
                batch_result[code] = service.get_stock_concepts(ts_code)
            else:
                batch_result[code] = []
        return batch_result

    result = await asyncio.to_thread(load_concepts_batch)

    total_concepts = sum(len(concepts) for concepts in result.values())
    return StockConceptsResponse(stocks=result, total=total_concepts)


@router.get("/concepts/{concept_code}/members", response_model=ConceptMembersResponse)
async def get_concept_members(
    concept_code: str,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ConceptMembersResponse:
    """获取概念板块的成分股"""
    await ensure_tushare_ready_async()
    service = TushareService()
    members = await asyncio.to_thread(service.get_stock_concept_members, concept_code)

    return ConceptMembersResponse(
        concept_code=concept_code,
        concept_name=None,
        members=members,
        total=len(members),
    )
