"""
Tasks API
~~~~~~~~~
任务调度相关 API
"""
import os
import platform
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, require_user
from app.config import settings
from app.database import get_db
from app.models import Config, Task, TaskLog
from app.services.task_service import TaskService
from app.services.tushare_service import TushareService
from app.schemas import (
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
OVERVIEW_CACHE_TTL_SECONDS = 20
_overview_cache: dict = {"data": None, "expires_at": 0.0}


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
async def get_data_status(user=Depends(require_user)) -> DataStatusResponse:
    """获取数据更新状态"""
    tushare_service = TushareService()
    status = tushare_service.check_data_status()

    # 格式化日期
    if status["raw_data"].get("latest_date"):
        from datetime import datetime
        ts = status["raw_data"]["latest_date"]
        if isinstance(ts, (int, float)):
            status["raw_data"]["latest_date"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    return DataStatusResponse(**status)


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

    result = await task_service.create_task(
        "full_update",
        {
            "reviewer": request.reviewer,
            "skip_fetch": request.skip_fetch,
            "start_from": request.start_from,
            "trigger_source": "manual",
        }
    )

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
    """
    from app.services.market_service import market_service, MarketService
    task_service = TaskService(db)

    active_full_task = task_service.get_active_full_task()
    if active_full_task:
        return {
            "success": False,
            "message": f"当前有全量初始化任务 #{active_full_task.id} 正在运行，请稍后再执行增量更新。",
            "running": False,
            "blocking_task_id": active_full_task.id,
        }

    # 检查是否已有更新在运行
    update_state = MarketService.get_update_state()
    if update_state["running"]:
        return {
            "success": False,
            "message": "已有更新任务正在运行",
            "running": True,
            "state": update_state,
        }

    # 开始更新
    if not MarketService.start_update():
        return {
            "success": False,
            "message": "无法启动更新任务",
            "running": False,
        }

    async def run_incremental_update():
        try:
            # 定义进度回调
            def progress_cb(payload):
                MarketService.update_progress(payload)

            result = market_service.incremental_update(
                end_date=end_date,
                progress_callback=progress_cb,
            )

            if result.get("ok"):
                MarketService.finish_update("增量更新完成")
            else:
                failed_count = result.get("failed", 0)
                MarketService.fail_update(f"增量更新失败，仍有 {failed_count} 只股票未完成，可稍后继续恢复。")
        except Exception:
            import traceback
            traceback.print_exc()
            MarketService.fail_update("增量更新异常中断，可稍后继续恢复。")

    # 在后台运行
    import asyncio
    asyncio.create_task(run_incremental_update())

    return {
        "success": True,
        "message": "增量更新已启动",
        "running": False,
    }


@router.get("/incremental-status")
async def get_incremental_status(user=Depends(require_user)) -> dict:
    """获取增量更新状态"""
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
async def get_running_tasks(db: Session = Depends(get_db), user=Depends(require_user)) -> TaskRunningResponse:
    tasks = (
        db.query(Task)
        .filter(Task.status.in_(["pending", "running"]))
        .order_by(Task.created_at.desc())
        .all()
    )
    return TaskRunningResponse(
        tasks=[TaskItem.model_validate(t, from_attributes=True) for t in tasks],
        total=len(tasks),
    )


@router.get("/environment", response_model=TaskEnvironmentResponse)
async def get_task_environment(db: Session = Depends(get_db), user=Depends(require_user)) -> TaskEnvironmentResponse:
    tushare_service = TushareService()
    return TaskEnvironmentResponse(sections=_build_environment_sections(tushare_service, db))


@router.get("/diagnostics", response_model=TaskDiagnosticsResponse)
async def get_task_diagnostics(db: Session = Depends(get_db), user=Depends(require_user)) -> TaskDiagnosticsResponse:
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
            return {"status": "ok", "message": "任务已取消"}
        else:
            return {"status": "error", "message": f"任务状态为 {task.status}，无需取消"}

    if success:
        return {"status": "ok", "message": "任务已取消"}
    else:
        return {"status": "error", "message": "任务不存在或无法取消"}


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
        return {"status": "ok", "message": "历史任务已清空"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": f"清空失败: {str(e)}"}
