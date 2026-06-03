"""Value lowland screener API."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.database import SessionLocal, close_db_session, get_db
from app.models import ValueLowlandRun
from app.schemas import ValueLowlandCompanyProfile, ValueLowlandResponse, ValueLowlandRunStatus
from app.services.value_lowland_service import ValueLowlandService
from app.time_utils import utc_now

router = APIRouter()
logger = logging.getLogger(__name__)


def _run_value_lowland_refresh(run_id: int) -> None:
    db = SessionLocal()
    try:
        run = db.get(ValueLowlandRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.started_at = utc_now()
        run.updated_at = run.started_at
        db.commit()

        response = ValueLowlandService(db).screen(
            limit=run.limit,
            enrich=run.enrich,
            force_refresh=run.force_refresh,
            allow_ai_profiles=False,
            profile_attempt_limit=None if run.limit <= 0 else min(200, max(run.limit * 3, 30)),
        )
        ValueLowlandService(db).save_run_result(run, response)
    except Exception as exc:
        logger.exception("价值洼地后台刷新失败: run_id=%s", run_id)
        db.rollback()
        run = db.get(ValueLowlandRun, run_id)
        if run is not None:
            now = utc_now()
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = now
            run.updated_at = now
            db.commit()
    finally:
        close_db_session(db)


def _status_from_run(run: ValueLowlandRun | None) -> ValueLowlandRunStatus:
    if run is None:
        return ValueLowlandRunStatus()
    return ValueLowlandRunStatus(
        id=run.id,
        status=run.status,
        limit=run.limit,
        enrich=run.enrich,
        force_refresh=run.force_refresh,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_message=run.error_message,
    )


@router.get("/screen", response_model=ValueLowlandResponse)
def screen_value_lowland(
    limit: int = Query(default=0, ge=0, le=5000, description="0 表示读取完整批处理结果"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ValueLowlandResponse:
    del user
    return ValueLowlandService(db).get_cached_screen(limit=limit)


@router.post("/refresh", response_model=ValueLowlandRunStatus)
def refresh_value_lowland(
    background_tasks: BackgroundTasks,
    limit: int = Query(default=0, ge=0, le=5000, description="0 表示全量分析所有本地股票"),
    enrich: bool = Query(default=True, description="是否启用搜索引擎/DeepSeek 软信息补全"),
    force_refresh: bool = Query(default=False, description="仅对本地缺失或低置信画像尝试重新检索；已确认静态画像不会覆盖"),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ValueLowlandRunStatus:
    del user
    running = (
        db.query(ValueLowlandRun)
        .filter(ValueLowlandRun.status.in_(("pending", "running")))
        .order_by(ValueLowlandRun.created_at.desc(), ValueLowlandRun.id.desc())
        .first()
    )
    if running is not None:
        return _status_from_run(running)

    now = utc_now()
    run = ValueLowlandRun(
        status="pending",
        limit=limit,
        enrich=enrich,
        force_refresh=force_refresh,
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    background_tasks.add_task(_run_value_lowland_refresh, run.id)
    return _status_from_run(run)


@router.get("/refresh/status", response_model=ValueLowlandRunStatus)
def get_value_lowland_refresh_status(
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ValueLowlandRunStatus:
    del user
    run = (
        db.query(ValueLowlandRun)
        .order_by(ValueLowlandRun.created_at.desc(), ValueLowlandRun.id.desc())
        .first()
    )
    return _status_from_run(run)


@router.post("/{code}/refresh-profile", response_model=ValueLowlandCompanyProfile)
def refresh_company_profile(
    code: str,
    name: str = Query(default=""),
    industry: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> ValueLowlandCompanyProfile:
    del user
    return ValueLowlandService(db).get_company_profile(
        code=code,
        name=name or code,
        industry=industry,
        ts_code=None,
        force_refresh=True,
    )
