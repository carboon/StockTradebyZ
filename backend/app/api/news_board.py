"""News board API."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user, require_user
from app.database import get_db
from app.schemas import (
    NewsBoardAnalyzeDetailRequest,
    NewsBoardAnalyzeDetailResponse,
    NewsBoardAnalyzeRequest,
    NewsBoardAnalyzeResponse,
    NewsBoardBatchAnalyzeRequest,
    NewsBoardBatchAnalyzeResponse,
    NewsBoardItemsResponse,
    NewsBoardRelatedStock,
)
from app.services.news_board_cache_service import (
    NewsBoardCacheService,
    _infer_related_stocks,
    _infer_related_industries,
    _infer_attention_level,
    _infer_sentiment,
)

router = APIRouter()

_css = NewsBoardCacheService()


@router.get("/items", response_model=NewsBoardItemsResponse)
def get_news_board_items(
    window_hours: int = Query(default=24, ge=1, le=72, description="消息窗口小时数"),
    limit: int = Query(default=50, ge=1, le=200, description="每页条数"),
    before: Optional[str] = Query(default=None, description="ISO 时间戳，返回此时间之前的消息（用于无限滚动）"),
    keyword: Optional[str] = Query(default=None, description="关键词搜索（在标题和摘要中匹配）"),
    user=Depends(require_user),
) -> NewsBoardItemsResponse:
    del user
    before_ts: float | None = None
    if before:
        try:
            before_ts = datetime.fromisoformat(before.replace("Z", "+00:00")).timestamp() - 0.001
        except ValueError:
            pass
    if keyword and keyword.strip():
        return _css.search_items(keyword=keyword.strip(), window_hours=window_hours, limit=min(limit, 100))
    return _css.get_items(window_hours=window_hours, limit=limit, before_ts=before_ts)


@router.get("/status")
def get_news_board_status(
    user=Depends(require_user),
) -> dict[str, Any]:
    del user
    return _css.get_status()


@router.post("/refresh")
def refresh_news_board(
    user=Depends(get_admin_user),
) -> dict[str, Any]:
    del user
    return _css.update_once()


@router.post("/analyze", response_model=NewsBoardAnalyzeResponse)
def analyze_news_board_item(
    request: NewsBoardAnalyzeRequest,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> NewsBoardAnalyzeResponse:
    del db, user
    text = f"{request.title} {request.summary}"
    stocks = _infer_related_stocks(text)
    industries = _infer_related_industries(text)
    attention = _infer_attention_level(request.title, request.summary)
    sentiment = _infer_sentiment(text)
    sentiment_text = {"positive": "偏利好", "negative": "偏利空", "neutral": "中性观察"}.get(sentiment, "中性观察")
    if not stocks:
        stocks = [NewsBoardRelatedStock(code="000300.SH", name="沪深300", sentiment="neutral", reason="未识别到明确 A 股产业链，先作为市场风险偏好观察")]
    industry_text = "；".join(f"{name}：{chain}" for name, chain in industries) if industries else "未识别到明确行业，建议作为宏观/情绪消息观察"
    return NewsBoardAnalyzeResponse(
        summary=(
            f"关注度：{attention}。A股影响方向：{sentiment_text}。"
            f"涉及行业/板块：{industry_text}。"
            f"已列出 {len(stocks)} 个与该消息上下游更紧密的 A 股标的；需要结合板块成交额、涨停扩散和原始来源二次确认。"
        ),
        stocks=stocks,
    )


@router.post("/analyze-detail", response_model=NewsBoardAnalyzeDetailResponse)
def analyze_news_detail(
    request: NewsBoardAnalyzeDetailRequest,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> NewsBoardAnalyzeDetailResponse:
    """详情分析 - 使用 NewsEventAnalysisAgent 进行深度事件分析."""
    del user

    import os as _os
    if not _os.environ.get("DEEPSEEK_API_KEY", "").strip():
        from app.models import Config as _Config
        db_key = db.query(_Config.value).filter(_Config.key == "deepseek_api_key").scalar()
        if db_key:
            _os.environ["DEEPSEEK_API_KEY"] = str(db_key).strip()

    try:
        from app.agents.news_event.agent import news_event_agent
        from app.agents.news_event.schemas import AnalyzeDetailRequest as AgentRequest

        agent_request = AgentRequest(
            news_id=request.news_id,
            title=request.title,
            summary=request.summary,
            category=request.category,
            source=request.source,
            published_at=request.published_at,
            event_time=request.event_time,
            url=request.url,
        )

        result = news_event_agent.analyze(agent_request, db=db)
        return NewsBoardAnalyzeDetailResponse(**result.model_dump())

    except Exception as exc:
        return NewsBoardAnalyzeDetailResponse(
            status="failed",
            reason=f"分析失败: {exc}",
        )


@router.post("/analyze-batch", response_model=NewsBoardBatchAnalyzeResponse)
def analyze_news_batch(
    request: NewsBoardBatchAnalyzeRequest,
    user=Depends(require_user),
) -> NewsBoardBatchAnalyzeResponse:
    """批量消息分析 - 对搜索结果进行全盘分析."""
    del user

    try:
        from app.services.news_batch_analysis_service import NewsBatchAnalysisService

        items = request.items
        if not items and request.keyword:
            items = _css.search_items(keyword=request.keyword, window_hours=24, limit=50)
            if hasattr(items, 'items'):
                raw_items = items.items
                items = []
                for it in raw_items:
                    d = it.model_dump() if hasattr(it, 'model_dump') else dict(it) if isinstance(it, dict) else {}
                    if d:
                        items.append(d)
            elif isinstance(items, list):
                pass
            else:
                items = []

        if not items:
            return NewsBoardBatchAnalyzeResponse(status="empty", reason="无搜索结果")

        result = NewsBatchAnalysisService.analyze(items)
        return NewsBoardBatchAnalyzeResponse(**result)

    except Exception as exc:
        logger.exception("批量分析失败")
        return NewsBoardBatchAnalyzeResponse(status="failed", reason=f"分析失败: {exc}")
