"""
Watchlist API
~~~~~~~~~~~~
重点观察相关 API
"""
from datetime import date as date_class
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.database import get_db
from app.models import Watchlist, WatchlistAnalysis, Stock
from app.services.analysis_cache import analysis_cache
from app.services.tushare_service import TushareService
from app.services.analysis_service import analysis_service
from app.services.task_service import TaskService
from app.schemas import (
    WatchlistResponse,
    WatchlistItem,
    WatchlistAddRequest,
    WatchlistUpdateRequest,
    WatchlistAnalysisItem,
)

router = APIRouter()


def _resolve_analysis_trade_date(result: dict, df) -> date_class:
    """Resolve analysis date to the latest market data date instead of query time."""
    check_date = result.get("check_date") or result.get("analysis_date")
    if check_date:
        try:
            return date_class.fromisoformat(str(check_date)[:10])
        except ValueError:
            pass

    if df is not None and not df.empty and "date" in df.columns:
        latest = df.sort_values("date").iloc[-1]["date"]
        if hasattr(latest, "date"):
            return latest.date()
        return date_class.fromisoformat(str(latest)[:10])

    return date_class.today()


def _resolve_latest_trade_date(df) -> date_class:
    """Resolve the latest trade date from a dataframe row with mixed date types."""
    if df is None or df.empty or "date" not in df.columns:
        return date_class.today()

    latest_value = df.sort_values("date").iloc[-1]["date"]
    if hasattr(latest_value, "date"):
        return latest_value.date()
    if isinstance(latest_value, date_class):
        return latest_value
    return date_class.fromisoformat(str(latest_value)[:10])


def _build_trend_outlook(verdict: str | None, signal_type: str | None, score: float | None) -> str:
    if verdict == "PASS" or signal_type == "trend_start":
        return "bullish"
    if verdict == "FAIL" or signal_type == "distribution_risk":
        return "bearish"
    return "neutral"


def _build_risk_level(
    verdict: str | None,
    signal_type: str | None,
    score: float | None,
    *,
    entry_price: float | None,
    current_price: float | None,
    position_ratio: float | None,
) -> str:
    if signal_type == "distribution_risk" or verdict == "FAIL":
        return "high"
    if entry_price and current_price:
        pnl = current_price / entry_price - 1.0
        if pnl <= -0.05 or (position_ratio or 0) >= 0.7:
            return "high"
        if pnl >= 0.08 or (score or 0) >= 4.0:
            return "medium"
    if verdict == "PASS" and (score or 0) >= 4.0:
        return "low"
    return "medium"


def _build_buy_action(verdict: str | None, signal_type: str | None, score: float | None) -> str:
    if verdict == "PASS" and (score or 0) >= 4.0:
        return "buy"
    if signal_type == "distribution_risk" or verdict == "FAIL":
        return "avoid"
    return "wait"


def _build_hold_action(
    verdict: str | None,
    signal_type: str | None,
    score: float | None,
    *,
    entry_price: float | None,
    current_price: float | None,
) -> str:
    if signal_type == "distribution_risk" or verdict == "FAIL":
        return "trim"
    if verdict == "PASS" and (score or 0) >= 4.0:
        if entry_price and current_price:
            pnl = current_price / entry_price - 1.0
            if pnl >= 0.08:
                return "hold"
            if pnl <= -0.05:
                return "hold_cautious"
        return "add_on_pullback"
    return "hold_cautious"


def _build_recommendation(
    verdict: str | None,
    signal_type: str | None,
    score: float | None,
    *,
    current_price: float | None,
    entry_price: float | None,
    position_ratio: float | None,
) -> str:
    if entry_price and current_price:
        pnl = current_price / entry_price - 1.0
        position_text = f"当前仓位 {position_ratio:.0%}。 " if position_ratio is not None else ""
        if verdict == "PASS" and (score or 0) >= 4.0:
            if pnl >= 0.08:
                return f"{position_text}继续持有，不追高；回踩企稳再加。"
            if pnl <= -0.05:
                return f"{position_text}谨慎持有，暂停加仓；跌破支撑先减仓。"
            return f"{position_text}继续持有；放量突破可小幅加仓。"
        if signal_type == "distribution_risk" or verdict == "FAIL":
            if pnl > 0:
                return f"{position_text}减仓锁盈，先保住利润。"
            return f"{position_text}优先减仓观察；跌破支撑执行止损。"
        if (score or 0) >= 4.0:
            return f"{position_text}暂不加仓；突破确认后再评估。"
        return f"{position_text}先观察；跌破支撑再减仓。"

    if verdict == "PASS" and (score or 0) >= 4.0:
        return "可试仓，不追高；回踩企稳再加。"
    if signal_type == "distribution_risk" or verdict == "FAIL":
        return "不买入；若已持有，减仓观察。"
    if (score or 0) >= 4.0:
        return "先等确认，不追买；突破后再评估。"
    return "继续观察，暂不出手。"


def _build_buy_recommendation(
    verdict: str | None,
    signal_type: str | None,
    score: float | None,
) -> str:
    if verdict == "PASS" and (score or 0) >= 4.0:
        return "可试仓，不追高。"
    if signal_type == "distribution_risk" or verdict == "FAIL":
        return "暂不买入。"
    if (score or 0) >= 4.0:
        return "等待突破确认后再考虑。"
    return "继续观察，先不出手。"


def _build_hold_recommendation(
    verdict: str | None,
    signal_type: str | None,
    score: float | None,
    *,
    current_price: float | None,
    entry_price: float | None,
) -> str:
    if signal_type == "distribution_risk" or verdict == "FAIL":
        if entry_price and current_price and current_price > entry_price:
            return "已有浮盈可先减仓。"
        return "谨慎持有，优先减仓观察。"
    if verdict == "PASS" and (score or 0) >= 4.0:
        return "量化评分较高，可适当加仓，注意仓位。"
    return "以观察为主，暂不加仓。"


def _build_risk_recommendation(
    verdict: str | None,
    signal_type: str | None,
    score: float | None,
    *,
    position_ratio: float | None,
) -> str:
    if signal_type == "distribution_risk" or verdict == "FAIL":
        return "跌破支撑执行止损。"
    if (position_ratio or 0) >= 0.7:
        return "仓位偏高，控制节奏。"
    if verdict == "PASS" and (score or 0) >= 4.0:
        return "关注回踩支撑是否有效。"
    return "等待信号进一步确认。"


def _calc_support_resistance(df) -> tuple[float | None, float | None]:
    if df is None or df.empty:
        return None, None
    frame = df.sort_values("date").reset_index(drop=True).tail(20)
    if frame.empty:
        return None, None
    support = float(frame["low"].min()) if "low" in frame.columns else None
    resistance = float(frame["high"].max()) if "high" in frame.columns else None
    return support, resistance


@router.get("/", response_model=WatchlistResponse)
async def get_watchlist(db: Session = Depends(get_db), user=Depends(require_user)) -> WatchlistResponse:
    """获取当前用户的观察列表"""
    # 按用户过滤并使用 left outer join 支持股票不存在的情况
    watchlist = (
        db.query(Watchlist, Stock)
        .outerjoin(Stock, Watchlist.code == Stock.code)
        .filter(Watchlist.user_id == user.id, Watchlist.is_active == True)
        .order_by(Watchlist.priority.desc(), Watchlist.added_at.desc())
        .all()
    )

    items = []
    for w, stock in watchlist:
        items.append(
            WatchlistItem(
                id=w.id,
                code=w.code,
                name=stock.name if stock else None,
                add_reason=w.add_reason,
                entry_price=w.entry_price,
                position_ratio=w.position_ratio,
                priority=w.priority,
                is_active=w.is_active,
                added_at=w.added_at,
            )
        )

    return WatchlistResponse(items=items, total=len(items))


@router.post("/", response_model=WatchlistItem)
async def add_to_watchlist(request: WatchlistAddRequest, db: Session = Depends(get_db), user=Depends(require_user)) -> WatchlistItem:
    """添加到当前用户的观察列表"""
    code = request.code.zfill(6)

    # 检查当前用户的列表中是否已存在
    existing = db.query(Watchlist).filter(Watchlist.user_id == user.id, Watchlist.code == code).first()
    if existing:
        # 更新为活跃状态
        existing.is_active = True
        existing.add_reason = request.reason
        existing.entry_price = request.entry_price
        existing.position_ratio = request.position_ratio
        existing.priority = request.priority
        db.commit()
        db.refresh(existing)
        w = existing
    else:
        w = Watchlist(
            user_id=user.id,
            code=code,
            add_reason=request.reason,
            entry_price=request.entry_price,
            position_ratio=request.position_ratio,
            priority=request.priority,
        )
        db.add(w)
        db.commit()
        db.refresh(w)

    stock = db.query(Stock).filter(Stock.code == w.code).first()
    if stock is None:
        try:
            stock = TushareService().sync_stock_to_db(db, w.code)
        except Exception:
            stock = None

    return WatchlistItem(
        id=w.id,
        code=w.code,
        name=stock.name if stock else None,
        add_reason=w.add_reason,
        entry_price=w.entry_price,
        position_ratio=w.position_ratio,
        priority=w.priority,
        is_active=w.is_active,
        added_at=w.added_at,
    )


@router.put("/{item_id}", response_model=WatchlistItem)
async def update_watchlist_item(
    item_id: int,
    request: WatchlistUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> WatchlistItem:
    """更新当前用户的观察列表项"""
    w = db.query(Watchlist).filter(Watchlist.id == item_id, Watchlist.user_id == user.id).first()
    if not w:
        raise HTTPException(status_code=404, detail="观察项不存在")

    fields_set = getattr(request, "model_fields_set", set())

    if "reason" in fields_set:
        w.add_reason = request.reason
    if "entry_price" in fields_set:
        w.entry_price = request.entry_price
    if "position_ratio" in fields_set:
        w.position_ratio = request.position_ratio
    if "priority" in fields_set:
        w.priority = request.priority
    if "is_active" in fields_set:
        w.is_active = request.is_active

    db.commit()
    db.refresh(w)

    stock = db.query(Stock).filter(Stock.code == w.code).first()

    return WatchlistItem(
        id=w.id,
        code=w.code,
        name=stock.name if stock else None,
        add_reason=w.add_reason,
        entry_price=w.entry_price,
        position_ratio=w.position_ratio,
        priority=w.priority,
        is_active=w.is_active,
        added_at=w.added_at,
    )


@router.delete("/{item_id}")
async def delete_watchlist_item(item_id: int, db: Session = Depends(get_db), user=Depends(require_user)) -> dict:
    """删除当前用户的观察列表项"""
    w = db.query(Watchlist).filter(Watchlist.id == item_id, Watchlist.user_id == user.id).first()
    if not w:
        raise HTTPException(status_code=404, detail="观察项不存在")

    # 软删除
    w.is_active = False
    db.commit()

    return {"status": "ok", "message": "已删除"}


@router.get("/{item_id}/analysis")
async def get_watchlist_analysis(item_id: int, db: Session = Depends(get_db), user=Depends(require_user)) -> dict:
    """获取当前用户的观察股票分析历史"""
    w = db.query(Watchlist).filter(Watchlist.id == item_id, Watchlist.user_id == user.id).first()
    if not w:
        raise HTTPException(status_code=404, detail="观察项不存在")

    analyses = (
        db.query(WatchlistAnalysis)
        .filter(WatchlistAnalysis.watchlist_id == item_id)
        .order_by(WatchlistAnalysis.analysis_date.desc())
        .limit(30)
        .all()
    )

    return {
        "code": w.code,
        "analyses": [
            WatchlistAnalysisItem(
                id=a.id,
                watchlist_id=a.watchlist_id,
                analysis_date=a.analysis_date,
                close_price=a.close_price,
                verdict=a.verdict,
                score=a.score,
                trend_outlook=a.trend_outlook,
                buy_action=a.buy_action,
                hold_action=a.hold_action,
                risk_level=a.risk_level,
                buy_recommendation=a.buy_recommendation,
                hold_recommendation=a.hold_recommendation,
                risk_recommendation=a.risk_recommendation,
                support_level=a.support_level,
                resistance_level=a.resistance_level,
                recommendation=a.recommendation,
            ) for a in analyses
        ],
        "total": len(analyses),
    }


@router.post("/{item_id}/analyze")
async def analyze_watchlist_item(
    item_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """立即分析当前用户的重点观察股票

    优先命中已有分析结果：
    1. 检查当日是否已有该股票的分析结果（可来自单股诊断或其他观察列表）
    2. 如果存在，直接复用结果
    3. 如果不存在，创建后台任务并返回 pending 状态（不阻塞请求）
    4. 前端可轮询 /api/v1/tasks/{task_id} 或通过 WebSocket 获取结果
    """
    w = db.query(Watchlist).filter(Watchlist.id == item_id, Watchlist.user_id == user.id).first()
    if not w:
        raise HTTPException(status_code=404, detail="观察项不存在")

    # 先尝试加载数据以确定交易日
    df = analysis_service.load_stock_data(w.code)
    tentative_date = _resolve_latest_trade_date(df)

    # 检查是否有已缓存的分析结果（可来自单股诊断）
    trade_date_str = tentative_date.strftime("%Y-%m-%d")
    cached_result = analysis_cache.get_cached_analysis(w.code, trade_date_str)

    if cached_result is not None:
        # 复用缓存结果，直接返回
        result = cached_result
    else:
        # 检查是否有正在进行的分析任务
        cache_key = analysis_cache.make_cache_key(w.code, trade_date_str, analysis_cache.STRATEGY_VERSION)
        if analysis_cache.is_analysis_in_progress(cache_key):
            return {
                "status": "pending",
                "code": w.code,
                "message": "分析正在进行中，请稍后再试",
                "_cache_key": cache_key,
            }

        # 冷缓存：创建后台分析任务（不阻塞请求）
        task_service = TaskService(db)
        task_response = await task_service.create_task(
            task_type="single_analysis",
            params={
                "code": w.code,
                "reviewer": "quant",
                "trigger_source": "watchlist_analyze",
                "watchlist_item_id": item_id,
            }
        )

        # 如果复用了已存在的任务，检查任务状态
        if task_response.get("existing"):
            task_id = task_response["task_id"]
            task_status = task_service.get_task_status(task_id)
            if task_status and task_status.get("status") == "completed":
                # 任务已完成，直接使用结果
                result = task_status.get("result", {})
                if result:
                    result["_cached"] = True
                else:
                    # 结果为空，返回错误
                    return {
                        "status": "error",
                        "code": w.code,
                        "message": "分析任务已完成但结果为空",
                        "task_id": task_id,
                    }
            else:
                # 任务仍在进行中，返回 pending
                return {
                    "status": "pending",
                    "code": w.code,
                    "message": "分析任务正在进行中",
                    "task_id": task_id,
                    "ws_url": f"/ws/tasks/{task_id}",
                }
        else:
            # 新任务已创建，返回 pending
            return {
                "status": "pending",
                "code": w.code,
                "message": "分析任务已创建",
                "task_id": task_response["task_id"],
                "ws_url": f"/ws/tasks/{task_response['task_id']}",
            }

    # 处理分析中的状态（用于兼容内存中的锁状态）
    if result.get("_status") in ("analyzing", "waiting"):
        return {
            "status": "pending",
            "code": w.code,
            "message": "分析正在进行中，请稍后再试",
            "_cache_key": result.get("_cache_key"),
        }

    # 处理分析结果（缓存命中或直接完成的任务）
    support_level, resistance_level = _calc_support_resistance(df)
    current_price = result.get("close_price")
    verdict = result.get("verdict")
    score = result.get("score")
    if score is None:
        score = result.get("total_score")
    signal_type = result.get("signal_type")
    trend_outlook = _build_trend_outlook(verdict, signal_type, score)
    buy_action = _build_buy_action(verdict, signal_type, score)
    hold_action = _build_hold_action(
        verdict,
        signal_type,
        score,
        entry_price=w.entry_price,
        current_price=current_price,
    )
    risk_level = _build_risk_level(
        verdict,
        signal_type,
        score,
        entry_price=w.entry_price,
        current_price=current_price,
        position_ratio=w.position_ratio,
    )
    recommendation = _build_recommendation(
        verdict,
        signal_type,
        score,
        current_price=current_price,
        entry_price=w.entry_price,
        position_ratio=w.position_ratio,
    )
    buy_recommendation = _build_buy_recommendation(verdict, signal_type, score)
    hold_recommendation = _build_hold_recommendation(
        verdict,
        signal_type,
        score,
        current_price=current_price,
        entry_price=w.entry_price,
    )
    risk_recommendation = _build_risk_recommendation(
        verdict,
        signal_type,
        score,
        position_ratio=w.position_ratio,
    )

    analysis_date = _resolve_analysis_trade_date(result, df)
    existing = (
        db.query(WatchlistAnalysis)
        .filter(
            WatchlistAnalysis.watchlist_id == item_id,
            WatchlistAnalysis.analysis_date == analysis_date,
        )
        .first()
    )
    if existing is None:
        existing = WatchlistAnalysis(
            watchlist_id=item_id,
            analysis_date=analysis_date,
        )
        db.add(existing)

    existing.close_price = current_price
    existing.verdict = verdict
    existing.score = score
    existing.trend_outlook = trend_outlook
    existing.buy_action = buy_action
    existing.hold_action = hold_action
    existing.risk_level = risk_level
    existing.buy_recommendation = buy_recommendation
    existing.hold_recommendation = hold_recommendation
    existing.risk_recommendation = risk_recommendation
    existing.support_level = support_level
    existing.resistance_level = resistance_level
    existing.recommendation = recommendation
    existing.notes = result.get("comment")
    db.commit()
    db.refresh(existing)

    return {
        "status": "ok",
        "code": w.code,
        "analysis": WatchlistAnalysisItem(
            id=existing.id,
            watchlist_id=existing.watchlist_id,
            analysis_date=existing.analysis_date,
            close_price=existing.close_price,
            verdict=existing.verdict,
            score=existing.score,
            trend_outlook=existing.trend_outlook,
            buy_action=existing.buy_action,
            hold_action=existing.hold_action,
            risk_level=existing.risk_level,
            buy_recommendation=existing.buy_recommendation,
            hold_recommendation=existing.hold_recommendation,
            risk_recommendation=existing.risk_recommendation,
            support_level=existing.support_level,
            resistance_level=existing.resistance_level,
            recommendation=existing.recommendation,
        ),
    }


@router.get("/{item_id}/chart")
async def get_watchlist_chart(item_id: int, db: Session = Depends(get_db), user=Depends(require_user)) -> dict:
    """获取当前用户的观察股票 K线图数据"""
    w = db.query(Watchlist).filter(Watchlist.id == item_id, Watchlist.user_id == user.id).first()
    if not w:
        raise HTTPException(status_code=404, detail="观察项不存在")

    # 调用 stock API 获取 K线数据
    from app.api.stock import get_kline_data
    from app.schemas import KLineDataRequest

    kline_request = KLineDataRequest(code=w.code, days=120, include_weekly=True)
    kline_data = await get_kline_data(kline_request)

    return {
        "code": w.code,
        "kline": kline_data,
        "latest_analysis": None,  # TODO: 添加最新分析
    }
