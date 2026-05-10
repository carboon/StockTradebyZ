"""
Analysis API
~~~~~~~~~~~~
分析相关 API (明日之星、单股诊断)

阶段5改造：长任务统一通过TaskService管理，不再使用BackgroundTasks。
"""
import json
import logging
import os
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.cache_decorators import (
    build_candidates_cache_key,
    build_freshness_cache_key,
)
from app.api.deps import get_admin_user, require_user
from app.api.rate_limit import single_analysis_rate_limit, history_generation_rate_limit
from app.api.tasks import _cleanup_stale_active_tasks, _raise_initialization_in_progress
from app.cache import cache
from app.database import get_db
from app.models import Candidate, AnalysisResult, DailyB1Check, DailyB1CheckDetail, Stock, StockDaily, Task
from app.services.analysis_service import analysis_service
from app.services.current_hot_intraday_service import CurrentHotIntradayAnalysisService
from app.services.current_hot_service import CurrentHotService
from app.services.diagnosis_history_cache_service import diagnosis_history_cache_service
from app.services.intraday_analysis_service import IntradayAnalysisService
from app.services.task_service import TaskService
from app.services.tomorrow_star_window_service import TomorrowStarWindowService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now
from app.schemas import (
    CandidatesResponse,
    CandidateItem,
    AnalysisResultResponse,
    AnalysisItem,
    CurrentHotCandidateItem,
    CurrentHotCandidatesResponse,
    CurrentHotAnalysisItem,
    CurrentHotAnalysisResultResponse,
    CurrentHotDatesResponse,
    CurrentHotHistoryItem,
    CurrentHotIntradayAnalysisGenerateResponse,
    CurrentHotIntradayAnalysisResponse,
    TomorrowStarDatesResponse,
    TomorrowStarHistoryItem,
    TomorrowStarWindowStatusResponse,
    IntradayAnalysisGenerateResponse,
    IntradayAnalysisResponse,
    DiagnosisHistoryResponse,
    DiagnosisHistoryDetailResponse,
    B1CheckItem,
    DiagnosisRequest,
    DiagnosisResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()
DIAGNOSIS_HISTORY_WINDOW_DAYS = analysis_service.HISTORY_WINDOW_DAYS

ROOT = Path(__file__).parent.parent.parent.parent


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
async def get_tomorrow_star_window_status(
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


@router.get("/tomorrow-star/candidates", response_model=CandidatesResponse)
async def get_candidates(
    date: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CandidatesResponse:
    """获取候选股票列表（只读数据库持久化结果）"""
    from app.services.candidate_service import CandidateService
    from app.models import TomorrowStarRun
    import pandas as pd

    requested_date = analysis_service._normalize_pick_date(date)
    cache_key = f"{build_candidates_cache_key(requested_date, limit)}:market-metrics-v3"
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
async def get_analysis_results(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> AnalysisResultResponse:
    """获取指定日期的分析结果"""
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


@router.get("/current-hot/dates", response_model=CurrentHotDatesResponse)
async def get_current_hot_dates(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotDatesResponse:
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


@router.get("/current-hot/candidates", response_model=CurrentHotCandidatesResponse)
async def get_current_hot_candidates(
    date: Optional[str] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotCandidatesResponse:
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
            consecutive_days=int(item.get("consecutive_days") or 1),
        )
        for item in payload.get("candidates", [])
    ]
    return CurrentHotCandidatesResponse(
        pick_date=pick_date,
        candidates=items,
        total=int(payload.get("total", 0) or 0),
    )


@router.get("/current-hot/results", response_model=CurrentHotAnalysisResultResponse)
async def get_current_hot_results(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> CurrentHotAnalysisResultResponse:
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
        )
        for item in payload.get("results", [])
    ]
    return CurrentHotAnalysisResultResponse(
        pick_date=pick_date,
        results=items,
        total=int(payload.get("total", 0) or 0),
        min_score_threshold=float(payload.get("min_score_threshold", 4.0) or 4.0),
    )


@router.post("/current-hot/generate")
async def generate_current_hot(
    date: Optional[str] = Query(default=None, description="交易日"),
    reviewer: str = Query(default="quant", description="评审者类型"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    ensure_tushare_ready()
    return CurrentHotService(db).generate_for_trade_date(date, reviewer=reviewer)


@router.get("/current-hot/intraday/status")
async def get_current_hot_intraday_status(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    service = CurrentHotIntradayAnalysisService(db)
    status = service.get_status(is_admin=True)
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
async def get_current_hot_intraday_data(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> CurrentHotIntradayAnalysisResponse:
    service = CurrentHotIntradayAnalysisService(db)
    payload = service.get_snapshot_payload(is_admin=True)
    return CurrentHotIntradayAnalysisResponse(**payload)


@router.post("/current-hot/intraday/generate", response_model=CurrentHotIntradayAnalysisGenerateResponse)
async def generate_current_hot_intraday(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> CurrentHotIntradayAnalysisGenerateResponse:
    ensure_tushare_ready()
    service = CurrentHotIntradayAnalysisService(db)
    payload = service.generate_snapshot()
    return CurrentHotIntradayAnalysisGenerateResponse(**payload)


@router.get("/intraday/status")
async def get_intraday_analysis_status(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    service = IntradayAnalysisService(db)
    status = service.get_status(is_admin=True)
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
async def get_intraday_analysis_data(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> IntradayAnalysisResponse:
    service = IntradayAnalysisService(db)
    payload = service.get_snapshot_payload(is_admin=True)
    return IntradayAnalysisResponse(**payload)


@router.post("/intraday/generate", response_model=IntradayAnalysisGenerateResponse)
async def generate_intraday_analysis(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> IntradayAnalysisGenerateResponse:
    ensure_tushare_ready()
    service = IntradayAnalysisService(db)
    payload = service.generate_snapshot()
    return IntradayAnalysisGenerateResponse(**payload)


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
        result = analysis_service.ensure_history_page(
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
    page_size = max(1, min(int(page_size), days, 50))
    result = analysis_service.generate_stock_history_checks(
        code,
        days=days,
        clean=True,
    ) if force else analysis_service.ensure_history_page(
        code,
        days=days,
        page=page,
        page_size=page_size,
        force=False,
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
    return {
        "exists": count > 0,
        "generating": False,
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
    try:
        stock = TushareService().sync_stock_to_db(db, code)
    except Exception:
        stock = db.query(Stock).filter(Stock.code == code).first()

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
        }

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
            "active_pool_rank": result_json.get("active_pool_rank"),
            "turnover_rate": result_json.get("turnover_rate"),
            "volume_ratio": result_json.get("volume_ratio"),
            "in_active_pool": result_json.get("in_active_pool"),
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
