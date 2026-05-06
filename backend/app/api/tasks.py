"""
Tasks API
~~~~~~~~~
任务调度相关 API
"""
import os
import platform
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, require_user
from app.api.rate_limit import status_api_rate_limit
from app.cache import cache
from app.config import PROJECT_ROOT, settings
from app.database import get_db
from app.models import Config, Task, TaskLog
from app.services.task_service import TaskService
from app.services.tomorrow_star_window_service import maintain_tomorrow_star_for_trade_date
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
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return None
        value = str(rows[-1].get("date", "")).strip()
        if len(value) >= 10:
            value = value[:10]
        return value or None
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

    # 格式化日期
    if status["raw_data"].get("latest_date"):
        from datetime import datetime
        ts = status["raw_data"]["latest_date"]
        if isinstance(ts, (int, float)):
            status["raw_data"]["latest_date"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    result = DataStatusResponse(**status)
    if not _is_test_mode():
        cache.set("data_status", result, STATUS_CACHE_TTL)
    return result


@router.post("/start", response_model=TaskResponse)
async def start_update(request: UpdateStartRequest, db: Session = Depends(get_db), admin=Depends(get_admin_user)) -> TaskResponse:
    """启动全量更新"""
    # 导入 manager 实例
    from app.main import manager
    from app.services.market_service import MarketService
    task_service = TaskService(db, manager=manager)

    existing_task = task_service.get_active_full_task()
    if existing_task:
        _raise_initialization_in_progress(existing_task)

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
    """启动增量数据更新（数据库版本）

    Args:
        end_date: 结束日期 (YYYY-MM-DD)，默认为今天

    更新逻辑：
    1. 获取所有股票列表
    2. 对每只股票，检查数据库中最新日期
    3. 从 Tushare 拉取新数据并存入数据库
    """
    from app.services.daily_data_service import get_daily_data_service
    from app.services.market_service import MarketService

    task_service = TaskService(db)

    # 检查是否有全量任务在运行
    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        _raise_initialization_in_progress(active_full_task)

    # 检查是否已有更新在运行
    update_state = MarketService.get_update_state()
    if update_state["running"]:
        return {
            "success": False,
            "message": "已有更新任务正在运行",
            "running": True,
        }

    # 开始更新
    if not MarketService.start_update():
        return {
            "success": False,
            "message": "无法启动更新任务",
            "running": False,
        }

    daily_data_service = get_daily_data_service()

    async def run_incremental_update():
        try:
            # 定义进度回调
            def progress_cb(*args, **kwargs):
                """兼容旧式位置参数和新式 payload 字典的进度回调。"""
                if args and isinstance(args[0], dict):
                    payload = dict(args[0])
                elif kwargs:
                    payload = dict(kwargs)
                elif len(args) >= 4:
                    current, total, code, status = args[:4]
                    payload = {
                        "current": current,
                        "total": total,
                        "current_code": code,
                        "status": status,
                    }
                else:
                    return

                MarketService.update_progress(payload)

            # 使用 asyncio.to_thread 在线程池中运行同步函数，避免阻塞事件循环
            result = await asyncio.to_thread(
                daily_data_service.incremental_update,
                end_date=end_date,
                progress_callback=progress_cb,
            )

            if result.get("success"):
                latest_trade_date = TushareService().get_latest_trade_date()
                if latest_trade_date and TushareService().is_trade_date_data_ready(latest_trade_date):
                    try:
                        await asyncio.to_thread(
                            maintain_tomorrow_star_for_trade_date,
                            latest_trade_date,
                            reviewer="quant",
                            source="incremental_update",
                            window_size=180,
                        )
                    except Exception as exc:
                        print(f"增量更新后维护明日之星 180 日窗口失败: {exc}")
                MarketService.finish_update(
                    f"增量更新完成: {result.get('updated')} 更新, {result.get('skipped')} 跳过, {result.get('failed')} 失败"
                )
            else:
                MarketService.fail_update(result.get("message", "增量更新失败"))
        except Exception as e:
            import traceback
            traceback.print_exc()
            MarketService.fail_update(f"增量更新异常: {str(e)}")
        finally:
            # 清除缓存
            cache.delete("data_status")

    # 在后台运行
    import asyncio
    asyncio.create_task(run_incremental_update())

    return {
        "success": True,
        "message": "增量更新已启动",
        "running": False,
    }


@router.get("/incremental-status")


@router.get("/incremental-status")
async def get_incremental_status(
    _rate_limit: None = Depends(status_api_rate_limit),
    user=Depends(require_user)
) -> dict:
    """获取增量更新状态

    注意：前端应根据 running 字段决定是否继续轮询。
    当 running=False 时，应停止或大幅降低轮询频率以减少服务器压力。
    """
    from app.services.market_service import MarketService

    state = MarketService.get_update_state()
    return {
        "status": state["status"],
        "running": state["running"],
        "progress": state["progress"],
        "current": state["current"],
        "total": state["total"],
        "current_code": state["current_code"],
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
    raw_csv_progress = _assess_raw_csv_progress(data_status.get("raw_data", {}).get("latest_trade_date"))
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
            meta=f"raw={data_status['raw_data'].get('count', 0)} / analysis={data_status['analysis'].get('count', 0)}",
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
                message="原始数据、候选数据或评分数据至少有一项缺失。",
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
