"""Concept memory library API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, require_user
from app.database import get_db
from app.schemas import (
    ConceptMemoryComposeRequest,
    ConceptMemoryComposeResponse,
    ConceptMemoryDetailResponse,
    ConceptMemoryListResponse,
    ConceptMemoryRefreshResponse,
    ConceptMemoryUpsertRequest,
)
from app.services.concept_memory_service import ConceptMemoryService

router = APIRouter()


@router.get("/", response_model=ConceptMemoryListResponse)
def list_concept_memory_entries(
    keyword: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
) -> ConceptMemoryListResponse:
    return ConceptMemoryService(db).list_entries(
        keyword=keyword,
        source_type=source_type,
        status=status,
        limit=limit,
    )


@router.get("/{entry_id}", response_model=ConceptMemoryDetailResponse)
def get_concept_memory_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
) -> ConceptMemoryDetailResponse:
    try:
        return ConceptMemoryService(db).get_detail(entry_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/", response_model=ConceptMemoryDetailResponse)
def create_concept_memory_entry(
    request: ConceptMemoryUpsertRequest,
    db: Session = Depends(get_db),
    _admin=Depends(get_admin_user),
) -> ConceptMemoryDetailResponse:
    try:
        return ConceptMemoryService(db).upsert_entry(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{entry_id}", response_model=ConceptMemoryDetailResponse)
def update_concept_memory_entry(
    entry_id: int,
    request: ConceptMemoryUpsertRequest,
    db: Session = Depends(get_db),
    _admin=Depends(get_admin_user),
) -> ConceptMemoryDetailResponse:
    try:
        return ConceptMemoryService(db).upsert_entry(request.model_dump(), entry_id=entry_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{entry_id}/refresh", response_model=ConceptMemoryRefreshResponse)
def refresh_concept_memory_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_admin_user),
) -> ConceptMemoryRefreshResponse:
    try:
        return ConceptMemoryService(db).refresh_entry(entry_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/compose", response_model=ConceptMemoryComposeResponse)
def compose_concept_memory_context(
    request: ConceptMemoryComposeRequest,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
) -> ConceptMemoryComposeResponse:
    try:
        return ConceptMemoryService(db).compose_context(
            query=request.query,
            use_ai=bool(request.use_ai),
            force_refresh=bool(request.force_refresh),
            max_entries=max(1, min(int(request.max_entries or 8), 50)),
            max_news=max(1, min(int(request.max_news or 10), 50)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
