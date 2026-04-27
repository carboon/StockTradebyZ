"""
Tasks API
~~~~~~~~~
任务调度相关 API
"""
import os
import platform
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Task, TaskLog
from app.services.task_service import TaskService
from app.services.tushare_service import TushareService
from app.schemas import (
    DataStatusResponse,
    TaskAlertItem,
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


def _ensure_tushare_ready() -> None:
    service = TushareService()
    valid, message = service.verify_token()
    if not valid:
        raise HTTPException(status_code=503, detail=f"Tushare 未就绪: {message}")


@router.get("/status", response_model=DataStatusResponse)
async def get_data_status() -> DataStatusResponse:
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
async def start_update(request: UpdateStartRequest, db: Session = Depends(get_db)) -> TaskResponse:
    """启动全量更新"""
    _ensure_tushare_ready()
    # 导入 manager 实例
    from app.main import manager
    task_service = TaskService(db, manager=manager)

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


@router.get("/overview", response_model=TaskOverviewResponse)
async def get_task_overview(db: Session = Depends(get_db)) -> TaskOverviewResponse:
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
            status="danger" if failed_count else "success",
            meta="历史累计",
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
                level="error",
                title="存在失败任务",
                message=f"当前共有 {failed_count} 个失败任务，请优先检查最近失败记录。",
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
async def get_running_tasks(db: Session = Depends(get_db)) -> TaskRunningResponse:
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
async def get_task_environment(db: Session = Depends(get_db)) -> TaskEnvironmentResponse:
    tushare_service = TushareService()
    data_status = tushare_service.check_data_status()
    sections = [
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
                "tushare_configured": bool(settings.tushare_token),
                "zhipuai_configured": bool(settings.zhipuai_api_key),
                "dashscope_configured": bool(settings.dashscope_api_key),
                "gemini_configured": bool(settings.gemini_api_key),
                "default_reviewer": settings.default_reviewer,
            },
        ),
        TaskEnvironmentSection(
            key="data_status",
            label="数据状态",
            items=data_status,
        ),
    ]
    return TaskEnvironmentResponse(sections=sections)


@router.get("/", response_model=TaskListResponse)
async def get_tasks(
    status: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
) -> TaskListResponse:
    """获取任务列表"""
    query = db.query(Task)

    if status:
        query = query.filter(Task.status == status)

    # 先获取总数（在应用limit之前）
    total = query.count()

    # 再获取限制数量的任务
    tasks = query.order_by(Task.created_at.desc()).limit(limit).all()

    return TaskListResponse(
        tasks=[TaskItem.model_validate(t, from_attributes=True) for t in tasks],
        total=total,
    )


@router.get("/{task_id}/logs", response_model=TaskLogListResponse)
async def get_task_logs(task_id: int, limit: int = 300, db: Session = Depends(get_db)) -> TaskLogListResponse:
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
async def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskItem:
    """获取任务详情"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return TaskItem.model_validate(task, from_attributes=True)


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: int, db: Session = Depends(get_db)) -> dict:
    """取消任务"""
    task_service = TaskService(db)
    success = await task_service.cancel_task(task_id)

    if success:
        # 更新数据库状态
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = "cancelled"
            task.task_stage = "cancelled"
            db.add(TaskLog(task_id=task.id, level="warning", stage="cancelled", message="任务已取消"))
            db.commit()
            _overview_cache["expires_at"] = 0.0
        return {"status": "ok", "message": "任务已取消"}
    else:
        return {"status": "error", "message": "任务无法取消"}


@router.delete("/clear")
async def clear_tasks(db: Session = Depends(get_db)) -> dict:
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
