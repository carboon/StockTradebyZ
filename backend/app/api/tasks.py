"""
Tasks API
~~~~~~~~~
任务调度相关 API
"""
import os
import platform
import csv
from datetime import date as date_class, datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, require_user
from app.api.rate_limit import status_api_rate_limit
from app.cache import cache
from app.config import PROJECT_ROOT, settings
from app.database import get_db
from app.models import (
    AnalysisResult,
    Candidate,
    Config,
    CurrentHotAnalysisResult,
    CurrentHotCandidate,
    DailyB1Check,
    RawDataManifest,
    StockDaily,
    Task,
    TaskLog,
    TomorrowStarRun,
)
from app.services.task_service import TaskService
from app.services.tushare_service import TushareService
from app.schemas import (
    AdminSummaryCard,
    AdminSummaryDataGap,
    AdminPipelineStageSummary,
    AdminSummaryResponse,
    AdminSummaryTaskInfo,
    DataStatusResponse,
    TaskAlertItem,
    TaskDiagnosticCheck,
    TaskDiagnosticsResponse,
    TaskEnvironmentResponse,
    TaskEnvironmentSection,
    TaskItem,
    TaskListResponse,
    TaskLogItem,
    TaskLogListResponse,
    TaskOverviewCard,
    TaskOverviewResponse,
    TaskResponse,
    TaskRunningResponse,
    UpdateStartRequest,
)

router = APIRouter()

# 缓存 TTL 配置（秒）
# 针对非实时系统优化：使用较长的缓存时间减少数据库压力
STATUS_CACHE_TTL = 120         # 数据状态缓存 2 分钟
RUNNING_CACHE_TTL = 10         # 运行中任务缓存 10 秒（需要相对及时）
OVERVIEW_CACHE_TTL_SECONDS = 60  # 总览缓存 1 分钟
_overview_cache: dict = {"data": None, "expires_at": 0.0}

# CSV 进度评估缓存（优化性能）
_csv_progress_cache: dict = {"data": None, "expires_at": 0.0}
_CSV_PROGRESS_CACHE_TTL = 120  # CSV 进度缓存 2 分钟

# 预期股票代码缓存（避免重复读取 CSV）
_expected_codes_cache: dict = {"data": None, "expires_at": 0.0}
_EXPECTED_CODES_CACHE_TTL = 600  # 10 分钟缓存（股票列表很少变化）


def _resolve_raw_status_for_views(raw_status: dict | None) -> dict:
    raw_status = raw_status or {}
    manifest_preferred = bool(raw_status.get("manifest_preferred"))
    manifest_loaded = bool(raw_status.get("manifest_db_loaded"))
    latest_db_date = raw_status.get("latest_db_date") or raw_status.get("latest_loaded_trade_date") or raw_status.get("latest_date")
    latest_available_date = raw_status.get("latest_available_date") or raw_status.get("manifest_latest_trade_date") or raw_status.get("latest_date")
    return {
        "manifest_preferred": manifest_preferred,
        "manifest_loaded": manifest_loaded,
        "latest_db_date": latest_db_date,
        "latest_available_date": latest_available_date,
        "display_date": latest_available_date if manifest_preferred else latest_db_date,
        "available_stock_count": int(
            raw_status.get("latest_available_stock_count")
            or raw_status.get("manifest_stock_count")
            or raw_status.get("latest_date_stock_count")
            or raw_status.get("stock_count")
            or 0
        ),
        "available_record_count": int(
            raw_status.get("latest_available_record_count")
            or raw_status.get("manifest_record_count")
            or raw_status.get("raw_record_count")
            or 0
        ),
    }


def _clear_all_caches(db: Session | None = None) -> None:
    """清除所有相关缓存"""
    import time
    _overview_cache["expires_at"] = 0.0
    _csv_progress_cache["expires_at"] = 0.0
    _expected_codes_cache["expires_at"] = 0.0

    # 清除数据库级元数据缓存
    if db:
        try:
            from app.services.admin_summary_metadata_service import get_admin_summary_metadata_service
            metadata_service = get_admin_summary_metadata_service(db)
            metadata_service.invalidate()
        except Exception:
            pass  # 不影响主流程


def _load_expected_fetch_codes() -> set[str]:
    import time

    # 检查缓存
    now = time.time()
    if _expected_codes_cache["data"] is not None and now < _expected_codes_cache["expires_at"]:
        return _expected_codes_cache["data"]

    import yaml

    cfg_path = PROJECT_ROOT / "config" / "fetch_kline.yaml"
    if not cfg_path.exists():
        return set()

    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    stocklist_path = Path(cfg.get("stocklist", "./pipeline/stocklist.csv"))
    if not stocklist_path.is_absolute():
        stocklist_path = PROJECT_ROOT / stocklist_path
    if not stocklist_path.exists():
        return set()

    exclude_boards = {str(x).lower() for x in (cfg.get("exclude_boards") or [])}
    codes: set[str] = set()
    with open(stocklist_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = str(row.get("symbol", "")).zfill(6)
            ts_code = str(row.get("ts_code", "")).upper()
            if not symbol or symbol == "000000":
                continue
            board = "main"
            if ts_code.endswith(".BJ") or symbol.startswith(("4", "8")):
                board = "bj"
            elif ts_code.endswith(".SZ") and symbol.startswith(("300", "301")):
                board = "gem"
            elif ts_code.endswith(".SH") and symbol.startswith("688"):
                board = "star"
            if board in exclude_boards:
                continue
            codes.add(symbol)

    # 更新缓存
    _expected_codes_cache["data"] = codes
    _expected_codes_cache["expires_at"] = now + _EXPECTED_CODES_CACHE_TTL

    return codes


def _get_latest_date_from_csv(csv_path: Path) -> str | None:
    try:
        with open(csv_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            if file_size <= 0:
                return None

            chunk_size = min(4096, file_size)
            f.seek(-chunk_size, os.SEEK_END)
            tail = f.read(chunk_size).decode("utf-8", errors="ignore")

        lines = [line for line in tail.splitlines() if line.strip()]
        if len(lines) < 2:
            return None
        value = lines[-1].split(",", 1)[0].strip()
        return value[:10] if value else None
    except Exception:
        return None


def _assess_raw_csv_progress(latest_trade_date: str | None) -> dict[str, int | str | None]:
    """评估 CSV 文件进度（带缓存优化）"""
    import time

    # 检查缓存
    now = time.time()
    if _csv_progress_cache["data"] is not None and now < _csv_progress_cache["expires_at"]:
        return _csv_progress_cache["data"]

    raw_dir = settings.raw_data_dir
    expected_codes = _load_expected_fetch_codes()
    ready = 0
    missing = 0
    stale = 0
    invalid = 0
    latest_local_date: str | None = None

    # 采样检查优化：只检查前 100 个文件来快速评估状态
    # 这样可以在大量文件时大幅提高响应速度
    sample_size = min(100, len(expected_codes))
    sampled_codes = list(expected_codes)[:sample_size]
    sample_missing = 0
    sample_ready = 0

    for code in sampled_codes:
        csv_path = raw_dir / f"{code}.csv"
        if not csv_path.exists():
            sample_missing += 1
            continue
        csv_latest = _get_latest_date_from_csv(csv_path)
        if not csv_latest:
            invalid += 1
            continue
        if latest_local_date is None or csv_latest > latest_local_date:
            latest_local_date = csv_latest
        if latest_trade_date and csv_latest < latest_trade_date:
            stale += 1
            continue
        sample_ready += 1

    # 基于采样结果推算整体状态
    if len(expected_codes) > sample_size:
        ratio = len(expected_codes) / sample_size
        missing = int(sample_missing * ratio)
        ready = int(sample_ready * ratio)
        # stale 和 invalid 保持采样值，避免过度放大
    else:
        # 完整检查
        for code in expected_codes:
            csv_path = raw_dir / f"{code}.csv"
            if not csv_path.exists():
                missing += 1
                continue
            csv_latest = _get_latest_date_from_csv(csv_path)
            if not csv_latest:
                invalid += 1
                continue
            if latest_local_date is None or csv_latest > latest_local_date:
                latest_local_date = csv_latest
            if latest_trade_date and csv_latest < latest_trade_date:
                stale += 1
                continue
            ready += 1

    result = {
        "expected_total": len(expected_codes),
        "ready_count": ready,
        "missing_count": missing,
        "stale_count": stale,
        "invalid_count": invalid,
        "latest_local_date": latest_local_date,
    }

    # 更新缓存
    _csv_progress_cache["data"] = result
    _csv_progress_cache["expires_at"] = now + _CSV_PROGRESS_CACHE_TTL

    return result


def _raise_initialization_in_progress(task: Task) -> None:
    raise HTTPException(
        status_code=409,
        detail=f"正在初始化，请等待（任务 #{task.id}）",
    )


def _cleanup_stale_active_tasks(db: Session) -> set[int]:
    """将数据库中无对应活跃进程的 pending/running 任务标记为 cancelled。"""
    if _is_test_mode():
        return set()

    task_service = TaskService(db)
    active_tasks = (
        db.query(Task)
        .filter(Task.status.in_(["pending", "running"]))
        .all()
    )

    stale_ids: set[int] = set()
    for task in active_tasks:
        if task_service.is_task_process_alive(task.id):
            continue
        task.status = "cancelled"
        task.task_stage = "cancelled"
        task.progress_meta_json = TaskService._build_stage_meta(
            "cancelled",
            progress=task.progress,
            message="任务进程已结束，自动清理残留运行状态",
        )
        stale_ids.add(task.id)

    if stale_ids:
        db.add_all([
            TaskLog(
                task_id=task_id,
                level="warning",
                stage="cancelled",
                message="检测到残留运行状态，系统已自动清理",
            )
            for task_id in stale_ids
        ])
        db.commit()
        cache.delete("running_tasks")
        _overview_cache["expires_at"] = 0.0

    # 清除管理员总览元数据缓存
    try:
        from app.services.admin_summary_metadata_service import get_admin_summary_metadata_service
        metadata_service = get_admin_summary_metadata_service(db)
        metadata_service.invalidate()
    except Exception:
        pass  # 不影响主流程

    return stale_ids


def _is_test_mode() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ


def _is_failure_resolved(
    latest_failed: Task | None,
    latest_success: Task | None,
    *,
    data_ready: bool,
) -> bool:
    if not data_ready or latest_failed is None or latest_success is None:
        return False
    if latest_failed.completed_at is None or latest_success.completed_at is None:
        return False
    return latest_success.completed_at > latest_failed.completed_at


def _ensure_tushare_ready() -> None:
    service = TushareService()
    valid, message = service.verify_token()
    if not valid:
        raise HTTPException(status_code=503, detail=f"Tushare 未就绪: {message}")


def _resolve_full_update_params(request: UpdateStartRequest, service: TushareService) -> dict:
    """根据当前数据状态自动选择全量初始化的起点。"""
    params = {
        "reviewer": request.reviewer,
        "skip_fetch": request.skip_fetch,
        "start_from": request.start_from,
        "reset_derived_state": request.reset_derived_state,
    }
    if request.skip_fetch or request.start_from > 1:
        return params

    try:
        status = service.check_data_status()
    except Exception:
        return params

    raw_status = status.get("raw_data") if isinstance(status, dict) else None
    if not isinstance(raw_status, dict):
        return params

    if raw_status.get("exists") and raw_status.get("is_latest_complete") is True:
        params["skip_fetch"] = True
        params["start_from"] = 2

    return params


def _resolve_recent_trade_dates(db: Session, window_size: int = 120) -> list[date_class]:
    rows = (
        db.query(StockDaily.trade_date)
        .distinct()
        .order_by(StockDaily.trade_date.desc())
        .limit(max(1, int(window_size)))
        .all()
    )
    return [trade_date for trade_date, in rows if trade_date]


def _date_counts_map(rows) -> dict[str, dict[str, int]]:
    return {
        trade_date.isoformat(): {
            "row_count": int(row_count or 0),
            "turnover_count": int(turnover_count or 0),
            "volume_ratio_count": int(volume_ratio_count or 0),
        }
        for trade_date, row_count, turnover_count, volume_ratio_count in rows
        if trade_date
    }


def _build_recent_120_integrity_report(db: Session, *, window_size: int = 120) -> dict:
    trade_dates = _resolve_recent_trade_dates(db, window_size)
    if not trade_dates:
        return {
            "success": False,
            "window_size": window_size,
            "date_count": 0,
            "message": "数据库中没有可检查的行情交易日",
            "issues": [],
            "dates": [],
            "summary": {},
        }

    rows = (
        db.query(
            StockDaily.trade_date,
            func.count(StockDaily.id),
            func.count(StockDaily.turnover_rate),
            func.count(StockDaily.volume_ratio),
        )
        .filter(StockDaily.trade_date.in_(trade_dates))
        .group_by(StockDaily.trade_date)
        .all()
    )
    daily_stats = _date_counts_map(rows)

    manifest_map = {
        item.trade_date.isoformat(): item
        for item in db.query(RawDataManifest).filter(RawDataManifest.trade_date.in_(trade_dates)).all()
    }
    star_run_map = {
        item.pick_date.isoformat(): item
        for item in db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date.in_(trade_dates)).all()
    }
    current_hot_dates = {
        pick_date.isoformat()
        for pick_date, in db.query(CurrentHotCandidate.pick_date)
        .filter(CurrentHotCandidate.pick_date.in_(trade_dates))
        .distinct()
        .all()
        if pick_date
    }
    diagnosis_dates = {
        check_date.isoformat()
        for check_date, in db.query(DailyB1Check.check_date)
        .filter(DailyB1Check.check_date.in_(trade_dates))
        .distinct()
        .all()
        if check_date
    }

    min_rows = 3000
    min_metric_ratio = 0.90
    issues: list[dict] = []
    date_reports: list[dict] = []
    for trade_date in trade_dates:
        key = trade_date.isoformat()
        item = daily_stats.get(key, {"row_count": 0, "turnover_count": 0, "volume_ratio_count": 0})
        row_count = int(item["row_count"])
        metric_count = min(int(item["turnover_count"]), int(item["volume_ratio_count"]))
        metric_ratio = (metric_count / row_count) if row_count else 0.0
        manifest = manifest_map.get(key)
        star_run = star_run_map.get(key)
        has_current_hot = key in current_hot_dates
        has_diagnosis = key in diagnosis_dates
        day_issues: list[str] = []
        if row_count < min_rows:
            day_issues.append("行情行数偏低")
        if row_count > 0 and metric_ratio < min_metric_ratio:
            day_issues.append("换手率/量比填充不足")
        if manifest and int(manifest.db_stock_count or 0) > 0 and row_count < int(manifest.db_stock_count or 0):
            day_issues.append("DB 行数低于 manifest 入库股票数")
        if not star_run or str(star_run.status or "").lower() != "success":
            day_issues.append("明日之星未成功生成")
        if not has_current_hot:
            day_issues.append("当前热盘缺少候选")
        if not has_diagnosis:
            day_issues.append("单股诊断历史未覆盖")

        report = {
            "trade_date": key,
            "row_count": row_count,
            "turnover_count": int(item["turnover_count"]),
            "volume_ratio_count": int(item["volume_ratio_count"]),
            "metric_fill_ratio": round(metric_ratio, 4),
            "manifest_status": manifest.status if manifest else None,
            "manifest_stock_count": int(manifest.stock_count or 0) if manifest else 0,
            "manifest_db_stock_count": int(manifest.db_stock_count or 0) if manifest else 0,
            "tomorrow_star_status": star_run.status if star_run else None,
            "tomorrow_star_candidates": int(star_run.candidate_count or 0) if star_run else 0,
            "current_hot_ready": has_current_hot,
            "diagnosis_ready": has_diagnosis,
            "issues": day_issues,
        }
        date_reports.append(report)
        if day_issues:
            issues.append({"trade_date": key, "issues": day_issues})

    return {
        "success": not issues,
        "window_size": window_size,
        "date_count": len(trade_dates),
        "date_range": [trade_dates[-1].isoformat(), trade_dates[0].isoformat()],
        "summary": {
            "issue_dates": len(issues),
            "checked_dates": len(trade_dates),
            "min_rows": min_rows,
            "min_metric_fill_ratio": min_metric_ratio,
        },
        "issues": issues[:50],
        "dates": date_reports,
        "message": "近120交易日数据完整" if not issues else f"发现 {len(issues)} 个交易日存在完整性问题",
    }


def _count_for_date(db: Session, model: Any, date_field: Any, target_date: date_class, *extra_filters: Any) -> int:
    query = db.query(func.count(model.id)).filter(date_field == target_date)
    for filter_item in extra_filters:
        query = query.filter(filter_item)
    return int(query.scalar() or 0)


def _build_trade_date_revalidation_report(db: Session, target_date: date_class) -> dict:
    from app.services.current_hot_service import CurrentHotService

    def same_float(left: Any, right: Any, tolerance: float = 1e-4) -> bool:
        if left is None and right is None:
            return True
        if left is None or right is None:
            return False
        try:
            return abs(float(left) - float(right)) <= tolerance
        except (TypeError, ValueError):
            return False

    row_count = _count_for_date(db, StockDaily, StockDaily.trade_date, target_date)
    turnover_count = int(
        db.query(func.count(StockDaily.turnover_rate))
        .filter(StockDaily.trade_date == target_date)
        .scalar()
        or 0
    )
    volume_ratio_count = int(
        db.query(func.count(StockDaily.volume_ratio))
        .filter(StockDaily.trade_date == target_date)
        .scalar()
        or 0
    )
    candidate_count = _count_for_date(db, Candidate, Candidate.pick_date, target_date)
    analysis_count = _count_for_date(db, AnalysisResult, AnalysisResult.pick_date, target_date)
    trend_start_count = _count_for_date(
        db,
        AnalysisResult,
        AnalysisResult.pick_date,
        target_date,
        AnalysisResult.signal_type == "trend_start",
    )
    current_hot_candidate_count = _count_for_date(db, CurrentHotCandidate, CurrentHotCandidate.pick_date, target_date)
    current_hot_analysis_count = _count_for_date(db, CurrentHotAnalysisResult, CurrentHotAnalysisResult.pick_date, target_date)
    current_hot_b1_count = _count_for_date(
        db,
        CurrentHotAnalysisResult,
        CurrentHotAnalysisResult.pick_date,
        target_date,
        CurrentHotAnalysisResult.b1_passed.is_(True),
    )
    diagnosis_count = _count_for_date(db, DailyB1Check, DailyB1Check.check_date, target_date)

    hot_service = CurrentHotService(db)
    pool_entries = hot_service.get_pool_entries()
    persisted_candidates = {
        row.code: row
        for row in db.query(CurrentHotCandidate)
        .filter(CurrentHotCandidate.pick_date == target_date)
        .all()
    }
    persisted_analysis = {
        row.code: row
        for row in db.query(CurrentHotAnalysisResult)
        .filter(CurrentHotAnalysisResult.pick_date == target_date)
        .all()
    }
    sample_recomputed: list[dict] = []
    current_hot_mismatches: list[dict[str, Any]] = []
    for entry in pool_entries:
        snapshot = hot_service.build_trade_snapshot(entry.code, target_date)
        recomputed_item = {
            "code": entry.code,
            "close_price": snapshot.get("close_price"),
            "b1_passed": snapshot.get("b1_passed"),
            "signal_type": snapshot.get("signal_type"),
            "score": snapshot.get("score"),
            "turnover_rate": snapshot.get("turnover_rate"),
            "volume_ratio": snapshot.get("volume_ratio"),
        }
        if len(sample_recomputed) < 10:
            sample_recomputed.append(recomputed_item)

        candidate = persisted_candidates.get(entry.code)
        analysis = persisted_analysis.get(entry.code)
        mismatch_fields: list[str] = []
        if candidate is None:
            mismatch_fields.append("missing_candidate")
        else:
            if not same_float(candidate.close_price, snapshot.get("close_price")):
                mismatch_fields.append("close_price")
            if not same_float(candidate.turnover_rate, snapshot.get("turnover_rate")):
                mismatch_fields.append("turnover_rate")
            if not same_float(candidate.volume_ratio, snapshot.get("volume_ratio")):
                mismatch_fields.append("volume_ratio")
            if candidate.b1_passed != snapshot.get("b1_passed"):
                mismatch_fields.append("candidate_b1_passed")
        if analysis is None:
            mismatch_fields.append("missing_analysis")
        else:
            if analysis.b1_passed != snapshot.get("b1_passed"):
                mismatch_fields.append("analysis_b1_passed")
            if str(analysis.signal_type or "") != str(snapshot.get("signal_type") or ""):
                mismatch_fields.append("signal_type")
            if not same_float(analysis.total_score, snapshot.get("score")):
                mismatch_fields.append("score")
        if mismatch_fields:
            current_hot_mismatches.append(
                {
                    "code": entry.code,
                    "fields": mismatch_fields,
                    "persisted": {
                        "close_price": candidate.close_price if candidate else None,
                        "b1_passed": analysis.b1_passed if analysis else (candidate.b1_passed if candidate else None),
                        "signal_type": analysis.signal_type if analysis else None,
                        "score": analysis.total_score if analysis else None,
                        "turnover_rate": candidate.turnover_rate if candidate else None,
                        "volume_ratio": candidate.volume_ratio if candidate else None,
                    },
                    "recomputed": recomputed_item,
                }
            )

    issues: list[str] = []
    if row_count <= 0:
        issues.append("该交易日没有行情数据")
    if row_count > 0 and min(turnover_count, volume_ratio_count) / row_count < 0.90:
        issues.append("换手率/量比填充比例低于 90%")
    if candidate_count > 0 and analysis_count < candidate_count:
        issues.append("明日之星分析数量少于候选数量")
    if pool_entries and current_hot_candidate_count < len(pool_entries):
        issues.append("当前热盘候选数量少于配置股票池")
    if current_hot_candidate_count > 0 and current_hot_analysis_count < current_hot_candidate_count:
        issues.append("当前热盘分析数量少于候选数量")
    if current_hot_mismatches:
        issues.append(f"当前热盘本地重算与持久化结果存在 {len(current_hot_mismatches)} 只股票差异")
    if diagnosis_count <= 0:
        issues.append("该交易日没有单股诊断历史")

    return {
        "success": not issues,
        "trade_date": target_date.isoformat(),
        "summary": {
            "stock_daily_rows": row_count,
            "turnover_count": turnover_count,
            "volume_ratio_count": volume_ratio_count,
            "metric_fill_ratio": round((min(turnover_count, volume_ratio_count) / row_count) if row_count else 0.0, 4),
            "tomorrow_star_candidates": candidate_count,
            "tomorrow_star_analysis": analysis_count,
            "tomorrow_star_trend_start": trend_start_count,
            "current_hot_pool_size": len(pool_entries),
            "current_hot_candidates": current_hot_candidate_count,
            "current_hot_analysis": current_hot_analysis_count,
            "current_hot_b1_pass": current_hot_b1_count,
            "current_hot_mismatch_count": len(current_hot_mismatches),
            "diagnosis_count": diagnosis_count,
        },
        "sample_recomputed_current_hot": sample_recomputed,
        "current_hot_mismatches": current_hot_mismatches[:30],
        "issues": issues,
        "message": "指定日期本地重验证通过" if not issues else "指定日期重验证发现差异",
    }


def _resolve_runtime_config_value(db: Session, key: str) -> str:
    env_key = key.upper()
    env_value = os.environ.get(env_key, "").strip()
    if env_value and env_value != "your_tushare_token_here":
        return env_value

    db_key = key.lower()
    db_config = db.query(Config).filter(Config.key == db_key).first()
    return str(db_config.value).strip() if db_config and db_config.value is not None else ""


def _build_environment_sections(tushare_service: TushareService, db: Session) -> list[TaskEnvironmentSection]:
    data_status = tushare_service.check_data_status()
    runtime_tushare_token = _resolve_runtime_config_value(db, "TUSHARE_TOKEN")
    runtime_zhipuai_api_key = _resolve_runtime_config_value(db, "ZHIPUAI_API_KEY")
    runtime_dashscope_api_key = _resolve_runtime_config_value(db, "DASHSCOPE_API_KEY")
    runtime_gemini_api_key = _resolve_runtime_config_value(db, "GEMINI_API_KEY")
    runtime_default_reviewer = _resolve_runtime_config_value(db, "DEFAULT_REVIEWER") or settings.default_reviewer
    return [
        TaskEnvironmentSection(
            key="service",
            label="服务信息",
            items={
                "app_name": settings.app_name,
                "debug": settings.debug,
                "host": settings.host,
                "port": settings.port,
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "timezone": os.environ.get("TZ", "system-default"),
            },
        ),
        TaskEnvironmentSection(
            key="paths",
            label="运行路径",
            items={
                "data_dir": str(settings.data_dir),
                "db_dir": str(settings.db_dir),
                "raw_data_dir": str(settings.raw_data_dir),
                "review_dir": str(settings.review_dir),
                "logs_dir": str(settings.logs_dir),
            },
        ),
        TaskEnvironmentSection(
            key="integrations",
            label="外部依赖",
            items={
                "tushare_configured": bool(runtime_tushare_token),
                "zhipuai_configured": bool(runtime_zhipuai_api_key),
                "dashscope_configured": bool(runtime_dashscope_api_key),
                "gemini_configured": bool(runtime_gemini_api_key),
                "default_reviewer": runtime_default_reviewer,
            },
        ),
        TaskEnvironmentSection(
            key="data_status",
            label="数据状态",
            items=data_status,
        ),
    ]


@router.get("/status", response_model=DataStatusResponse)
async def get_data_status(
    _rate_limit: None = Depends(status_api_rate_limit),
    user=Depends(require_user)
) -> DataStatusResponse:
    """获取数据更新状态（缓存 30 秒）"""
    # 尝试从缓存获取
    cached = None if _is_test_mode() else cache.get("data_status")
    if cached:
        return cached

    tushare_service = TushareService()
    status = tushare_service.check_data_status()
    raw_status = status.get("raw_data", {})
    raw_view = _resolve_raw_status_for_views(raw_status)

    # 格式化日期
    if raw_status.get("latest_date"):
        from datetime import datetime
        ts = raw_status["latest_date"]
        if isinstance(ts, (int, float)):
            raw_status["latest_date"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    raw_status["display_latest_date"] = raw_view["display_date"]
    raw_status["display_stock_count"] = raw_view["available_stock_count"]
    raw_status["display_record_count"] = raw_view["available_record_count"]

    result = DataStatusResponse(**status)
    if not _is_test_mode():
        cache.set("data_status", result, STATUS_CACHE_TTL)
    return result


@router.get("/data-freshness")
async def get_data_freshness(user=Depends(require_user)) -> dict:
    """实时查询 Tushare 日线数据最新时效"""
    service = TushareService()
    return service.get_data_freshness()


@router.post("/start", response_model=TaskResponse)
async def start_update(request: UpdateStartRequest, db: Session = Depends(get_db), admin=Depends(get_admin_user)) -> TaskResponse:
    """启动全量更新"""
    # 导入 manager 实例
    from app.main import manager
    from app.services.market_service import MarketService
    task_service = TaskService(db, manager=manager)

    existing_task = task_service.get_active_full_task()
    if existing_task:
        return TaskResponse(
            task=TaskItem.model_validate(existing_task, from_attributes=True),
            ws_url=f"/ws/tasks/{existing_task.id}",
        )

    incremental_state = MarketService.get_update_state()
    if incremental_state.get("running"):
        raise HTTPException(
            status_code=409,
            detail="当前有增量更新任务正在运行，请等待完成后再启动全量初始化。",
        )

    _ensure_tushare_ready()

    effective_params = _resolve_full_update_params(request, TushareService())
    effective_params["trigger_source"] = "manual"

    result = await task_service.create_task("full_update", effective_params)

    task = db.query(Task).filter(Task.id == result["task_id"]).first()

    return TaskResponse(
        task=TaskItem.model_validate(task, from_attributes=True),
        ws_url=result["ws_url"],
    )


@router.post("/start-incremental")
async def start_incremental_update(
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """启动增量数据更新

    Args:
        end_date: 结束日期 (YYYY-MM-DD)，默认为今天

    更新逻辑：
    1. 批量增量抓取最新交易日数据
    2. 同步更新 data/raw CSV
    3. 将新增交易日写入数据库
    """
    from app.main import manager
    from app.services.market_service import MarketService

    task_service = TaskService(db, manager=manager)

    # 检查是否有全量任务在运行
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        return {
            "success": False,
            "message": f"正在初始化，请等待（任务 #{active_full_task.id}）",
            "running": False,
            "blocking_task_id": active_full_task.id,
        }

    tushare_service = TushareService()
    resolved_end_date = end_date or tushare_service.get_effective_latest_trade_date(prefer_realtime=True)
    if not resolved_end_date:
        raise HTTPException(status_code=503, detail="无法确定目标交易日")

    MarketService.start_update()
    result = await task_service.create_task(
        TaskService.INCREMENTAL_UPDATE_TASK_TYPE,
        {
            "trade_date": resolved_end_date,
            "source": "incremental_update",
            "trigger_source": "manual",
        },
    )
    task = db.query(Task).filter(Task.id == result["task_id"]).first()
    if task and result.get("existing"):
        MarketService.start_update(task.id)

    cache.delete("data_status")
    _clear_all_caches(db)

    return {
        "success": True,
        "message": f"增量更新已启动，目标日期 {resolved_end_date}",
        "running": False,
        "trade_date": resolved_end_date,
        "task_id": result["task_id"],
        "ws_url": result["ws_url"],
        "existing": result.get("existing", False),
        "task": TaskItem.model_validate(task, from_attributes=True) if task else None,
    }


@router.post("/start-daily-batch")
async def start_daily_batch_update(
    trade_date: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """启动按交易日批量刷新。

    通过正式 TaskService 任务体系执行，支持任务中心、日志和状态观测。
    """
    from app.main import manager

    task_service = TaskService(db)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)

    service = TushareService()
    resolved_trade_date = trade_date or service.get_effective_latest_trade_date(prefer_realtime=True)
    if not resolved_trade_date:
        raise HTTPException(status_code=503, detail="无法确定目标交易日")

    task_service = TaskService(db, manager=manager)
    result = await task_service.create_task(
        TaskService.DAILY_BATCH_UPDATE_TASK_TYPE,
        {
            "trade_date": resolved_trade_date,
            "source": "manual_daily_batch",
            "trigger_source": "manual",
        },
    )
    task = db.query(Task).filter(Task.id == result["task_id"]).first()
    cache.delete("data_status")
    _clear_all_caches(db)

    return {
        "success": True,
        "message": f"按交易日批量刷新已启动，目标日期 {resolved_trade_date}",
        "trade_date": resolved_trade_date,
        "task_id": result["task_id"],
        "ws_url": result["ws_url"],
        "existing": result.get("existing", False),
        "task": TaskItem.model_validate(task, from_attributes=True) if task else None,
    }


@router.post("/start-recent-120-rebuild")
async def start_recent_120_rebuild(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """启动近120交易日完整重建任务。"""
    from app.main import manager

    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)

    _ensure_tushare_ready()
    result = await task_service.create_task(
        TaskService.RECENT_120_REBUILD_TASK_TYPE,
        {
            "window_size": 120,
            "reviewer": "quant",
            "trigger_source": "manual_recent_120_rebuild",
        },
    )
    task = db.query(Task).filter(Task.id == result["task_id"]).first()
    cache.delete("data_status")
    _clear_all_caches(db)

    return {
        "success": True,
        "message": "近120交易日完整重建已启动",
        "task_id": result["task_id"],
        "ws_url": result["ws_url"],
        "existing": result.get("existing", False),
        "task": TaskItem.model_validate(task, from_attributes=True) if task else None,
    }


@router.get("/data-integrity/recent-120")
async def check_recent_120_integrity(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """只读检查近120交易日数据完整性。"""
    return _build_recent_120_integrity_report(db, window_size=120)


@router.post("/data-integrity/revalidate-date")
async def revalidate_trade_date(
    trade_date: str = Query(..., description="交易日 YYYY-MM-DD"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """基于本地数据对指定交易日做只读重验证。"""
    try:
        target_date = date_class.fromisoformat(str(trade_date).strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="trade_date 必须是 YYYY-MM-DD") from exc
    return _build_trade_date_revalidation_report(db, target_date)


@router.get("/incremental-status")
async def get_incremental_status(
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(status_api_rate_limit),
    user=Depends(require_user)
) -> dict:
    """获取增量更新状态

    注意：前端应根据 running 字段决定是否继续轮询。
    当 running=False 时，应停止或大幅降低轮询频率以减少服务器压力。
    """
    from app.services.market_service import MarketService

    task_service = TaskService(db)
    latest_incremental_task = task_service.get_latest_incremental_task()
    if latest_incremental_task:
        MarketService.sync_update_state_from_task(latest_incremental_task)

    state = MarketService.get_update_state()
    mode = str(state.get("mode") or "per_stock")
    task_type = str(state.get("task_type") or ("daily_batch_update" if mode == "daily_batch" else "incremental_update"))
    target_trade_date = state.get("target_trade_date")
    stage_label = state.get("stage_label")
    progress = int(state.get("progress") or 0)
    if state["running"] and mode == "daily_batch" and state.get("total") == 1 and state.get("current") == 0 and progress <= 0:
        progress = 1

    if mode == "daily_batch":
        title = "按交易日批量刷新"
        if state["running"]:
            status_label = f"{title}进行中"
            detail = f"目标交易日 {target_trade_date or state.get('current_code') or '-'}"
        elif state["status"] == "completed":
            status_label = f"{title}已完成"
            detail = f"目标交易日 {target_trade_date or state.get('current_code') or '-'}"
        elif state["status"] == "failed":
            status_label = f"{title}失败"
            detail = state.get("last_error") or state.get("message") or "任务失败"
        else:
            status_label = title
            detail = state.get("message") or "等待启动"
    else:
        status_label = "增量更新"
        detail = state.get("message") or "等待启动"

    return {
        "status": state["status"],
        "running": state["running"],
        "progress": progress,
        "current": state["current"],
        "total": state["total"],
        "current_code": state["current_code"],
        "task_type": task_type,
        "mode": mode,
        "target_trade_date": target_trade_date,
        "stage_label": stage_label,
        "display_title": status_label,
        "display_detail": detail,
        "updated_count": state["updated_count"],
        "skipped_count": state["skipped_count"],
        "failed_count": state["failed_count"],
        "started_at": state["started_at"],
        "completed_at": state["completed_at"],
        "eta_seconds": state["eta_seconds"],
        "elapsed_seconds": state["elapsed_seconds"],
        "resume_supported": state["resume_supported"],
        "initial_completed": state["initial_completed"],
        "completed_in_run": state["completed_in_run"],
        "checkpoint_path": state["checkpoint_path"],
        "last_error": state["last_error"],
        "message": state["message"],
    }


@router.get("/overview", response_model=TaskOverviewResponse)
async def get_task_overview(db: Session = Depends(get_db), user=Depends(require_user)) -> TaskOverviewResponse:
    import time

    now = time.time()
    if _overview_cache["data"] is not None and now < _overview_cache["expires_at"]:
        return _overview_cache["data"]

    running_count = db.query(func.count(Task.id)).filter(Task.status.in_(["pending", "running"])).scalar() or 0
    failed_count = db.query(func.count(Task.id)).filter(Task.status == "failed").scalar() or 0
    total_logs = db.query(func.count(TaskLog.id)).scalar() or 0
    latest_success = (
        db.query(Task)
        .filter(Task.status == "completed")
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .first()
    )
    latest_failed = (
        db.query(Task)
        .filter(Task.status == "failed")
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .first()
    )

    tushare_service = TushareService()
    data_status = tushare_service.check_data_status()
    raw_status = data_status.get("raw_data", {})
    raw_view = _resolve_raw_status_for_views(raw_status)
    raw_csv_progress = (
        {
            "expected_total": int(raw_status.get("expected_stock_count") or 0),
            "ready_count": raw_view["available_stock_count"],
            "missing_count": max(int(raw_status.get("expected_stock_count") or 0) - raw_view["available_stock_count"], 0),
            "stale_count": 0,
            "invalid_count": 0,
            "latest_local_date": raw_view["latest_available_date"],
        }
        if raw_view["manifest_preferred"]
        else _assess_raw_csv_progress(raw_status.get("latest_trade_date"))
    )
    data_ready = all(bool(data_status[key].get("exists")) for key in ["raw_data", "candidates", "analysis"])
    failure_resolved = _is_failure_resolved(latest_failed, latest_success, data_ready=data_ready)

    cards = [
        TaskOverviewCard(
            key="running",
            label="运行中任务",
            value=str(running_count),
            status="warning" if running_count else "success",
            meta="pending + running",
        ),
        TaskOverviewCard(
            key="failed",
            label="失败任务",
            value=str(failed_count),
            status="warning" if failed_count and failure_resolved else ("danger" if failed_count else "success"),
            meta="历史累计（当前已恢复）" if failed_count and failure_resolved else "历史累计",
        ),
        TaskOverviewCard(
            key="latest_success",
            label="最近成功任务",
            value=latest_success.completed_at.strftime("%Y-%m-%d %H:%M:%S") if latest_success and latest_success.completed_at else "-",
            status="success" if latest_success else "info",
            meta=latest_success.summary if latest_success and latest_success.summary else None,
        ),
        TaskOverviewCard(
            key="logs",
            label="日志条数",
            value=str(total_logs),
            status="info",
            meta="task_logs",
        ),
        TaskOverviewCard(
            key="data_ready",
            label="数据状态",
            value="正常" if data_ready else "待检查",
            status="success" if data_ready else "warning",
            meta=(
                f"manifest={raw_status.get('manifest_status', '-')} / raw={raw_view['available_stock_count']} / analysis={data_status['analysis'].get('count', 0)}"
                if raw_view["manifest_preferred"]
                else f"raw={data_status['raw_data'].get('count', 0)} / analysis={data_status['analysis'].get('count', 0)}"
            ),
        ),
    ]

    alerts: list[TaskAlertItem] = []
    if failed_count:
        alerts.append(
            TaskAlertItem(
                level="warning" if failure_resolved else "error",
                title="存在历史失败记录" if failure_resolved else "存在失败任务",
                message=(
                    f"当前共有 {failed_count} 个失败任务，但最新一次初始化已成功完成，可按需查看历史失败记录。"
                    if failure_resolved
                    else f"当前共有 {failed_count} 个失败任务，请优先检查最近失败记录。"
                ),
            )
        )
    if latest_failed and latest_failed.error_message:
        alerts.append(
            TaskAlertItem(
                level="warning",
                title="最近失败摘要",
                message=f"任务 #{latest_failed.id}: {latest_failed.error_message}",
            )
        )
    if running_count:
        alerts.append(
            TaskAlertItem(
                level="info",
                title="存在运行中任务",
                message=f"当前有 {running_count} 个任务正在运行或排队。",
            )
        )
    if not data_ready:
        alerts.append(
            TaskAlertItem(
                level="warning",
                title="数据状态未完全就绪",
                message=(
                    f"原始数据、候选数据或评分数据至少有一项缺失。最新交易日 {raw_status.get('latest_trade_date') or '-'}，"
                    f"当前已就绪 {int(raw_csv_progress.get('ready_count') or 0)} / {int(raw_csv_progress.get('expected_total') or 0)}。"
                ),
            )
        )

    result = TaskOverviewResponse(cards=cards, alerts=alerts)
    _overview_cache["data"] = result
    _overview_cache["expires_at"] = now + OVERVIEW_CACHE_TTL_SECONDS
    return result


@router.get("/running", response_model=TaskRunningResponse)
async def get_running_tasks(
    _rate_limit: None = Depends(status_api_rate_limit),
    db: Session = Depends(get_db),
    user=Depends(require_user)
) -> TaskRunningResponse:
    """获取运行中的任务（缓存 10 秒）

    注意：前端应根据返回的 total 数值决定是否继续轮询。
    当 total=0 时，应停止或大幅降低轮询频率以减少服务器压力。
    """
    # 尝试从缓存获取
    cached = cache.get("running_tasks")
    if cached:
        return cached

    _cleanup_stale_active_tasks(db)

    tasks = (
        db.query(Task)
        .filter(Task.status.in_(["pending", "running"]))
        .order_by(Task.created_at.desc())
        .all()
    )
    result = TaskRunningResponse(
        tasks=[TaskItem.model_validate(t, from_attributes=True) for t in tasks],
        total=len(tasks),
    )
    cache.set("running_tasks", result, RUNNING_CACHE_TTL)
    return result


@router.get("/environment", response_model=TaskEnvironmentResponse)
async def get_task_environment(
    _rate_limit: None = Depends(status_api_rate_limit),
    db: Session = Depends(get_db),
    user=Depends(require_user)
) -> TaskEnvironmentResponse:
    tushare_service = TushareService()
    return TaskEnvironmentResponse(sections=_build_environment_sections(tushare_service, db))


@router.get("/diagnostics", response_model=TaskDiagnosticsResponse)
async def get_task_diagnostics(
    _rate_limit: None = Depends(status_api_rate_limit),
    db: Session = Depends(get_db),
    user=Depends(require_user)
) -> TaskDiagnosticsResponse:
    _cleanup_stale_active_tasks(db)

    tushare_service = TushareService()
    data_status = tushare_service.check_data_status()
    environment = _build_environment_sections(tushare_service, db)

    running_tasks = (
        db.query(Task)
        .filter(Task.status.in_(["pending", "running"]))
        .order_by(Task.created_at.desc())
        .all()
    )
    latest_failed = (
        db.query(Task)
        .filter(Task.status == "failed")
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .first()
    )
    latest_completed = (
        db.query(Task)
        .filter(Task.status == "completed")
        .order_by(Task.completed_at.desc(), Task.id.desc())
        .first()
    )

    db_access_ok = True
    db_access_error = ""
    try:
        db.execute(select(func.count(Task.id)))
    except Exception as exc:
        db_access_ok = False
        db_access_error = str(exc)

    db_dir = settings.db_dir
    db_dir_writable = os.access(db_dir, os.W_OK) if db_dir.exists() else False
    data_ready = all(bool(data_status[key].get("exists")) for key in ["raw_data", "candidates", "analysis"])
    failure_resolved = _is_failure_resolved(latest_failed, latest_completed, data_ready=data_ready)

    checks = [
        TaskDiagnosticCheck(
            key="backend",
            label="后端服务",
            status="success",
            summary=f"接口可访问，运行于 {platform.python_version()} / {platform.system()}。",
        ),
        TaskDiagnosticCheck(
            key="database",
            label="数据库可用性",
            status="success" if db_access_ok and db_dir_writable else "error",
            summary=(
                f"数据库目录可写：{db_dir}"
                if db_access_ok and db_dir_writable
                else f"数据库检查失败：{db_access_error or f'目录不可写 {db_dir}'}"
            ),
            action="请检查 data/db 目录权限，或确认当前进程拥有本地写入权限。",
        ),
        TaskDiagnosticCheck(
            key="tushare",
            label="Tushare 配置",
            status="success" if tushare_service.token else "warning",
            summary="已检测到 Tushare Token，可继续验证。"
            if tushare_service.token
            else "尚未配置 Tushare Token，首次初始化无法启动。",
            action="前往配置页填写并验证 Tushare Token。",
        ),
        TaskDiagnosticCheck(
            key="initialization",
            label="首次初始化",
            status="success" if data_ready else ("warning" if running_tasks else "info"),
            summary=(
                "原始数据、候选结果和分析结果均已就绪。"
                if data_ready
                else f"当前缺少：{', '.join([name for key, name in [('raw_data', '原始数据'), ('candidates', '候选结果'), ('analysis', '分析结果')] if not data_status[key].get('exists')])}"
            ),
            action="去任务中心继续初始化或查看失败日志。" if not data_ready else "可以直接进入业务页面使用。",
        ),
        TaskDiagnosticCheck(
            key="task_recovery",
            label="任务恢复",
            status="success" if failure_resolved else ("warning" if latest_failed else ("info" if running_tasks else "success")),
            summary=(
                f"存在 {len(running_tasks)} 个运行中任务，可在任务中心恢复查看。"
                if running_tasks
                else "最近一次初始化已成功完成，历史失败记录不影响当前使用。"
                if failure_resolved
                else f"最近一次失败任务 #{latest_failed.id} 可查看日志恢复。"
                if latest_failed
                else "当前没有运行中任务，也没有待处理失败任务。"
            ),
            action="任务中心支持查看日志、重新发起初始化和导出诊断信息。",
        ),
    ]

    return TaskDiagnosticsResponse(
        generated_at=datetime.now().isoformat(),
        checks=checks,
        running_tasks=[TaskItem.model_validate(task, from_attributes=True) for task in running_tasks],
        latest_failed_task=TaskItem.model_validate(latest_failed, from_attributes=True) if latest_failed else None,
        latest_completed_task=TaskItem.model_validate(latest_completed, from_attributes=True) if latest_completed else None,
        environment=environment,
        data_status=data_status,
    )


@router.get("/", response_model=TaskListResponse)
async def get_tasks(
    status: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> TaskListResponse:
    """获取任务列表"""
    query = db.query(Task)

    if status:
        status_values = [item.strip() for item in status.split(",") if item.strip()]
        if len(status_values) == 1:
            query = query.filter(Task.status == status_values[0])
        elif status_values:
            query = query.filter(Task.status.in_(status_values))

    # 先获取总数（在应用limit之前）
    total = query.count()

    # 再获取限制数量的任务
    tasks = query.order_by(Task.created_at.desc()).limit(limit).all()

    return TaskListResponse(
        tasks=[TaskItem.model_validate(t, from_attributes=True) for t in tasks],
        total=total,
    )


@router.get("/{task_id}/logs", response_model=TaskLogListResponse)
async def get_task_logs(task_id: int, limit: int = 300, db: Session = Depends(get_db), user=Depends(require_user)) -> TaskLogListResponse:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    logs = (
        db.query(TaskLog)
        .filter(TaskLog.task_id == task_id)
        .order_by(TaskLog.log_time.asc(), TaskLog.id.asc())
        .limit(limit)
        .all()
    )
    return TaskLogListResponse(
        task_id=task_id,
        logs=[TaskLogItem.model_validate(log, from_attributes=True) for log in logs],
        total=len(logs),
    )


@router.get("/{task_id}", response_model=TaskItem)
async def get_task(task_id: int, db: Session = Depends(get_db), user=Depends(require_user)) -> TaskItem:
    """获取任务详情"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskItem.model_validate(task, from_attributes=True)


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: int, db: Session = Depends(get_db), admin=Depends(get_admin_user)) -> dict:
    """取消任务"""
    task_service = TaskService(db)
    success = await task_service.cancel_task(task_id)

    # 无论进程是否在运行，都尝试更新数据库状态
    task = db.query(Task).filter(Task.id == task_id).first()
    if task:
        if task.status in ["running", "pending"]:
            task.status = "cancelled"
            task.task_stage = "cancelled"
            task.progress_meta_json = TaskService._build_stage_meta("cancelled", progress=task.progress, message="任务已取消")
            if not success:
                db.add(TaskLog(task_id=task.id, level="warning", stage="cancelled", message="任务已取消"))
            db.commit()
            _overview_cache["expires_at"] = 0.0
            try:
                from app.services.admin_summary_metadata_service import get_admin_summary_metadata_service
                metadata_service = get_admin_summary_metadata_service(db)
                metadata_service.invalidate()
            except Exception:
                pass  # 不影响主流程
            return {"status": "ok", "message": "任务已取消"}
        else:
            return {"status": "error", "message": f"任务状态为 {task.status}，无需取消"}

    if success:
        return {"status": "ok", "message": "任务已取消"}
    else:
        return {"status": "error", "message": "任务不存在或无法取消"}


@router.get("/{task_id}/resume-info")
async def get_task_resume_info(
    task_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_user)
) -> dict:
    """获取任务恢复信息（断点续传）

    返回任务的已完成步骤和可恢复的步骤信息。
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_service = TaskService(db)
    resume_info = task_service.get_resume_info(task)

    return resume_info


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: int,
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user)
) -> TaskResponse:
    """从失败点恢复任务执行（断点续传）

    创建一个新的任务，从原任务失败的步骤继续执行。
    """
    from app.main import manager

    # 获取原任务
    original_task = db.query(Task).filter(Task.id == task_id).first()
    if not original_task:
        raise HTTPException(status_code=404, detail="任务不存在")

    if original_task.task_type not in TaskService.FULL_TASK_TYPES:
        raise HTTPException(status_code=400, detail="只有全量更新任务支持断点续传")

    task_service = TaskService(db, manager=manager)

    # 检查是否可以恢复
    if not task_service.can_resume_task(original_task):
        raise HTTPException(
            status_code=400,
            detail=f"任务状态为 {original_task.status}，不支持恢复。只能恢复失败或已取消的全量更新任务。"
        )

    # 检查是否有活跃的全量任务
    active_task = task_service.get_active_full_task()
    if active_task:
        _raise_initialization_in_progress(active_task)

    # 获取恢复信息
    resume_info = task_service.get_resume_info(original_task)

    # 准备新任务参数
    params = dict(original_task.params_json or {})
    params["start_from"] = resume_info["start_from"]
    params["skip_fetch"] = resume_info["start_from"] > 1
    params["resume_from"] = resume_info["next_step"]
    params["resumed_from_task_id"] = task_id
    params["trigger_source"] = "manual_resume"

    # 创建新任务
    result = await task_service.create_task(original_task.task_type, params)

    new_task = db.query(Task).filter(Task.id == result["task_id"]).first()

    # 记录恢复日志
    db.add(TaskLog(
        task_id=new_task.id,
        level="info",
        stage="preparing",
        message=f"从任务 #{task_id} 恢复执行，已步骤: {', '.join(resume_info['completed_step_labels'])}"
    ))
    db.commit()

    return TaskResponse(
        task=TaskItem.model_validate(new_task, from_attributes=True),
        ws_url=result["ws_url"],
    )


@router.delete("/clear")
async def clear_tasks(db: Session = Depends(get_db), admin=Depends(get_admin_user)) -> dict:
    """清空历史任务"""
    try:
        # 删除所有已完成的任务
        finished_task_ids = [
            task_id
            for (task_id,) in db.query(Task.id).filter(Task.status.in_(["completed", "failed", "cancelled"])).all()
        ]
        if finished_task_ids:
            db.query(TaskLog).filter(TaskLog.task_id.in_(finished_task_ids)).delete(synchronize_session=False)
            db.query(Task).filter(Task.id.in_(finished_task_ids)).delete(synchronize_session=False)
        db.commit()
        _overview_cache["expires_at"] = 0.0
        _admin_summary_cache["expires_at"] = 0.0
        return {"status": "ok", "message": "历史任务已清空"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": f"清空失败: {str(e)}"}


# ==================== 阶段3：区间增量更新 API ====================

@router.get("/incremental/fill-status")
async def get_incremental_fill_status(
    _rate_limit: None = Depends(status_api_rate_limit),
    user=Depends(require_user)
) -> dict:
    """获取区间增量更新状态总览

    返回当前数据缺口情况、各阶段补齐状态等信息。
    """
    from app.services.incremental_service import get_incremental_fill_service

    service = get_incremental_fill_service()
    return service.get_fill_summary()


@router.post("/incremental/detect-gap")
async def detect_data_gap(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user)
) -> dict:
    """检测数据缺口（任务 3.1）

    识别当前最新交易日与本地数据之间的缺口。

    Returns:
        包含缺口信息的字典
    """
    from app.services.incremental_service import get_incremental_fill_service

    service = get_incremental_fill_service()
    gap_status = service.detect_gap_status()

    return {
        "success": True,
        "gap": gap_status,
        "recommended_action": service._get_recommended_action(
            gap_status,
            service._get_existing_tomorrow_star_dates() and max(service._get_existing_tomorrow_star_dates()),
        ),
    }


@router.post("/incremental/fill-kline")
async def fill_kline_gap(
    target_date: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user)
) -> dict:
    """补齐行情数据（任务 3.2）

    按缺失交易日逐步补齐行情数据。

    Args:
        target_date: 目标日期 (YYYY-MM-DD)，默认补齐到最新交易日

    Returns:
        补齐状态
    """
    from app.services.incremental_service import get_incremental_fill_service
    from app.main import manager

    service = get_incremental_fill_service()

    # 检查是否有全量任务在运行
    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)

    # 执行补齐
    result = service.fill_kline_data(target_date=target_date)

    # 清除缓存
    cache.delete("data_status")
    _overview_cache["expires_at"] = 0.0
    _admin_summary_cache["expires_at"] = 0.0

    return {
        "success": result.status in ["completed", "partial"],
        "result": result.to_dict(),
    }


@router.post("/incremental/fill-tomorrow-star")
async def fill_tomorrow_star_gap(
    target_date: Optional[str] = None,
    reviewer: str = "quant",
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user)
) -> dict:
    """补齐明日之星结果（任务 3.3）

    对增量新增交易日逐日生成候选结果、评分结果、Top5推荐。

    Args:
        target_date: 目标日期
        reviewer: 评审者类型

    Returns:
        补齐状态
    """
    from app.services.incremental_service import get_incremental_fill_service

    service = get_incremental_fill_service()
    task_service = TaskService(db)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)

    # 执行补齐
    result = service.fill_tomorrow_star_results(
        target_date=target_date,
        reviewer=reviewer,
    )

    # 清除缓存
    cache.delete("data_status")
    _overview_cache["expires_at"] = 0.0
    _admin_summary_cache["expires_at"] = 0.0

    return {
        "success": result.status in ["completed", "partial"],
        "result": result.to_dict(),
    }


@router.post("/incremental/fill-top5-diagnosis")
async def fill_top5_diagnosis_gap(
    target_date: Optional[str] = None,
    reviewer: str = "quant",
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user)
) -> dict:
    """补齐 Top5 诊断与历史（任务 3.4）

    对区间内每个交易日的 Top5 股票生成单股诊断结果，
    并补齐每日检查历史。

    Args:
        target_date: 目标日期
        reviewer: 评审者类型

    Returns:
        补齐状态
    """
    from app.services.incremental_service import get_incremental_fill_service

    service = get_incremental_fill_service()
    task_service = TaskService(db)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)

    # 执行补齐
    result = service.fill_top5_diagnosis_and_history(
        target_date=target_date,
        reviewer=reviewer,
    )

    # 清除缓存
    cache.delete("data_status")
    _overview_cache["expires_at"] = 0.0
    _admin_summary_cache["expires_at"] = 0.0

    return {
        "success": result.status in ["completed", "partial"],
        "result": result.to_dict(),
    }


@router.post("/incremental/fill-all")
async def fill_all_gaps(
    target_date: Optional[str] = None,
    reviewer: str = "quant",
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user)
) -> dict:
    """一键补齐所有缺口

    按顺序执行：
    1. 补齐行情数据
    2. 补齐明日之星结果
    3. 补齐 Top5 诊断与历史

    Args:
        target_date: 目标日期
        reviewer: 评审者类型

    Returns:
        整体补齐状态
    """
    from app.services.incremental_service import get_incremental_fill_service
    from app.main import manager

    service = get_incremental_fill_service()

    # 检查是否有全量任务在运行
    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)

    results = {}

    # 1. 补齐行情数据
    kline_result = service.fill_kline_data(target_date=target_date)
    results["kline"] = kline_result.to_dict()

    # 2. 补齐明日之星结果
    if kline_result.status in ["completed", "partial"]:
        star_result = service.fill_tomorrow_star_results(
            target_date=target_date,
            reviewer=reviewer,
        )
        results["tomorrow_star"] = star_result.to_dict()

        # 3. 补齐 Top5 诊断
        if star_result.status in ["completed", "partial"]:
            diagnosis_result = service.fill_top5_diagnosis_and_history(
                target_date=target_date,
                reviewer=reviewer,
            )
            results["top5_diagnosis"] = diagnosis_result.to_dict()

    # 清除缓存
    cache.delete("data_status")
    _overview_cache["expires_at"] = 0.0
    _admin_summary_cache["expires_at"] = 0.0

    # 计算整体状态
    all_completed = all(
        r.get("status") in ["completed", "partial"]
        for r in results.values()
    )

    return {
        "success": all_completed,
        "results": results,
        "summary": {
            "total_stages": len(results),
            "completed_stages": sum(1 for r in results.values() if r.get("status") == "completed"),
            "partial_stages": sum(1 for r in results.values() if r.get("status") == "partial"),
            "failed_stages": sum(1 for r in results.values() if r.get("status") == "failed"),
        },
    }


@router.get("/admin/summary", response_model=AdminSummaryResponse)
async def get_admin_summary(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user)
) -> AdminSummaryResponse:
    """获取管理员总览摘要（仅管理员）

    使用数据库级元数据缓存，响应时间约 50-100ms。
    - 缓存未过期：直接返回缓存
    - 缓存过期：返回旧数据，后台异步更新
    - 首次访问：同步计算并缓存（约 2-5 秒）
    """
    from app.services.admin_summary_metadata_service import get_admin_summary_metadata_service

    service = get_admin_summary_metadata_service(db)
    return await service.get_cached_summary()


@router.post("/admin/summary/refresh")
async def refresh_admin_summary(
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user)
) -> dict:
    """强制刷新管理员总览缓存（仅管理员）

    手动触发重新计算并缓存管理员总览数据。
    用于用户点击刷新按钮时。

    Returns:
        {"success": true, "message": "...", "from_cache": false, "data": {...}}
    """
    from app.services.admin_summary_metadata_service import get_admin_summary_metadata_service

    service = get_admin_summary_metadata_service(db)
    return await service.force_refresh()


# ==================== 阶段6：历史回溯相关 API ====================

@router.get("/history-backfill/status/{code}")
async def get_history_backfill_status(
    code: str,
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """获取股票的历史回溯状态

    Args:
        code: 股票代码

    Returns:
        历史回溯状态信息
    """
    from app.services.history_backfill_service import get_history_backfill_service

    service = get_history_backfill_service()
    status = service.get_stock_backfill_status(code)
    return status.to_dict()


@router.post("/history-backfill/initialize/{code}")
async def initialize_history_backfill(
    code: str,
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """初始化股票历史回溯（补齐近一年历史）

    Args:
        code: 股票代码

    Returns:
        初始化任务状态
    """
    from app.services.history_backfill_service import get_history_backfill_service
    from app.main import manager

    service = get_history_backfill_service()

    # 创建后台任务
    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)
    result = await task_service.create_task(
        "history_backfill_initialize",
        {
            "code": code,
            "reviewer": "quant",
            "trigger_source": "manual"
        }
    )

    return {
        "task_id": result["task_id"],
        "code": code,
        "status": "pending",
        "ws_url": result["ws_url"],
        "message": "历史回溯初始化任务已创建",
    }


@router.post("/history-backfill/incremental/{code}")
async def incremental_history_backfill(
    code: str,
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """增量补齐股票最新交易日历史

    只补齐最新交易日，不重复回算已有历史。

    Args:
        code: 股票代码

    Returns:
        增量补齐状态
    """
    from app.services.history_backfill_service import get_history_backfill_service
    from app.main import manager

    service = get_history_backfill_service()

    # 创建后台任务
    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)
    result = await task_service.create_task(
        "history_backfill_incremental",
        {
            "code": code,
            "reviewer": "quant",
            "trigger_source": "manual"
        }
    )

    return {
        "task_id": result["task_id"],
        "code": code,
        "status": "pending",
        "ws_url": result["ws_url"],
        "message": "增量历史补齐任务已创建",
    }


@router.get("/history-backfill/batch-status")
async def get_batch_backfill_status(
    codes: str = Query(default="", description="股票代码列表，逗号分隔"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """获取批量股票的历史回溯状态

    Args:
        codes: 股票代码列表，逗号分隔

    Returns:
        批量回溯状态汇总
    """
    from app.services.history_backfill_service import get_history_backfill_service

    if not codes:
        raise HTTPException(status_code=400, detail="缺少股票代码")

    code_list = [c.strip() for c in codes.split(",") if c.strip()]

    service = get_history_backfill_service()
    return service.get_batch_backfill_status(code_list)


@router.post("/history-backfill/batch")
async def batch_history_backfill(
    codes: str = Query(default="", description="股票代码列表，逗号分隔"),
    target_date: Optional[str] = Query(default=None, description="目标日期"),
    db: Session = Depends(get_db),
    admin=Depends(get_admin_user),
) -> dict:
    """批量历史回溯

    Args:
        codes: 股票代码列表，逗号分隔
        target_date: 目标日期

    Returns:
        批量回溯任务信息
    """
    from app.services.history_backfill_service import get_history_backfill_service
    from app.main import manager

    if not codes:
        raise HTTPException(status_code=400, detail="缺少股票代码")

    code_list = [c.strip() for c in codes.split(",") if c.strip()]

    # 创建后台任务
    task_service = TaskService(db, manager=manager)
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)
    result = await task_service.create_task(
        "history_backfill_batch",
        {
            "codes": code_list,
            "target_date": target_date,
            "reviewer": "quant",
            "trigger_source": "manual"
        }
    )

    return {
        "task_id": result["task_id"],
        "codes": code_list,
        "status": "pending",
        "ws_url": result["ws_url"],
        "message": f"批量历史回溯任务已创建 ({len(code_list)} 只股票)",
    }
