"""Custom concepts API."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, require_user
from app.database import SessionLocal, close_db_session, get_db
from app.schemas import (
    CandidateConceptMatchRequest,
    CandidateConceptMatchResponse,
    ConceptQuerySuggestionsResponse,
    CustomConceptDetailResponse,
    CustomConceptListResponse,
    CustomConceptRefreshResponse,
    CustomConceptStockTagsResponse,
    CustomConceptUpsertRequest,
    StockCustomConceptsResponse,
)
from app.services.custom_concept_service import CustomConceptService

router = APIRouter()
logger = logging.getLogger(__name__)


def _refresh_candidate_matches_background(query: str, candidates: list[dict]) -> None:
    db = SessionLocal()
    try:
        CustomConceptService(db).match_candidates(
            query=query,
            candidates=candidates,
            force_refresh=True,
        )
    except Exception:
        logger.exception("Background custom concept candidate refresh failed: %s", query)
    finally:
        close_db_session(db)


@router.post("/match-candidates", response_model=CandidateConceptMatchResponse)
def match_custom_concept_candidates(
    request: CandidateConceptMatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
) -> CandidateConceptMatchResponse:
    try:
        response = CustomConceptService(db).match_candidates(
            query=request.query,
            candidates=[item.model_dump() for item in request.candidates],
            force_refresh=bool(request.force_refresh),
            async_refresh=bool(request.async_refresh),
        )
        if response.get("refresh_scheduled"):
            background_tasks.add_task(
                _refresh_candidate_matches_background,
                request.query,
                [item.model_dump() for item in request.candidates],
            )
        return response
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/query-suggestions", response_model=ConceptQuerySuggestionsResponse)
def suggest_custom_concept_queries(
    q: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=30),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
) -> ConceptQuerySuggestionsResponse:
    return CustomConceptService(db).suggest_queries(q, limit=limit)


@router.get("/", response_model=CustomConceptListResponse)
def list_custom_concepts(
    db: Session = Depends(get_db),
    _user=Depends(require_user),
) -> CustomConceptListResponse:
    return CustomConceptService(db).list_concepts()


@router.get("/by-stock/{code}", response_model=StockCustomConceptsResponse)
def get_custom_concepts_by_stock(
    code: str,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
) -> StockCustomConceptsResponse:
    try:
        return CustomConceptService(db).get_stock_concepts(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{concept_id}", response_model=CustomConceptDetailResponse)
def get_custom_concept_detail(
    concept_id: int,
    db: Session = Depends(get_db),
    _user=Depends(require_user),
) -> CustomConceptDetailResponse:
    try:
        return CustomConceptService(db).get_concept_detail(concept_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{concept_id}/stocks", response_model=CustomConceptStockTagsResponse)
def get_custom_concept_stocks(
    concept_id: int,
    chain_position: str | None = Query(default=None),
    role_tag: str | None = Query(default=None),
    min_relevance: float | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
    _user=Depends(require_user),
) -> CustomConceptStockTagsResponse:
    try:
        return CustomConceptService(db).get_concept_stocks(
            concept_id,
            chain_position=chain_position,
            role_tag=role_tag,
            min_relevance=min_relevance,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/", response_model=CustomConceptDetailResponse)
def create_custom_concept(
    request: CustomConceptUpsertRequest,
    db: Session = Depends(get_db),
    _admin=Depends(get_admin_user),
) -> CustomConceptDetailResponse:
    try:
        return CustomConceptService(db).upsert_concept(payload=request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{concept_id}", response_model=CustomConceptDetailResponse)
def update_custom_concept(
    concept_id: int,
    request: CustomConceptUpsertRequest,
    db: Session = Depends(get_db),
    _admin=Depends(get_admin_user),
) -> CustomConceptDetailResponse:
    try:
        return CustomConceptService(db).upsert_concept(payload=request.model_dump(), concept_id=concept_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{concept_id}")
def delete_custom_concept(
    concept_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_admin_user),
) -> dict:
    try:
        return CustomConceptService(db).delete_concept(concept_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{concept_id}/refresh", response_model=CustomConceptRefreshResponse)
def refresh_custom_concept(
    concept_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(get_admin_user),
) -> CustomConceptRefreshResponse:
    try:
        return CustomConceptService(db).refresh_concept(concept_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
