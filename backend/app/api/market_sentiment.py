"""Market sentiment API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_user
from app.services.market_sentiment_service import market_sentiment_service

router = APIRouter()


@router.get("/current")
def get_current_market_sentiment(
    force_refresh: bool = Query(default=False, description="是否强制刷新远程数据"),
    user=Depends(require_user),
) -> dict[str, Any]:
    del user
    return market_sentiment_service.get_current(force_refresh=force_refresh)
