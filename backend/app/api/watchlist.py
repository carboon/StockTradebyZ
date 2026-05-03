"""
Watchlist API
~~~~~~~~~~~~
重点观察相关 API

阶段2改造：从"按用户触发分析"改为"公共结果复用 + 用户配置叠加"
"""
from datetime import date as date_class
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.database import get_db
from app.models import Watchlist, Stock, StockAnalysis
from app.services.analysis_cache import analysis_cache
from app.services.tushare_service import TushareService
from app.services.analysis_service import analysis_service
# TaskService 不再在此模块使用（阶段2改造：不再创建后台分析任务）
from app.services.watchlist_analysis_service import WatchlistAnalysisService
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


def _build_watchlist_history_item(
    *,
    watchlist_id: int,
    history_item: dict,
    entry_price: float | None,
    position_ratio: float | None,
    support_level: float | None,
    resistance_level: float | None,
    synthetic_id: int,
) -> WatchlistAnalysisItem:
    score = history_item.get("score")
    verdict = history_item.get("verdict")
    signal_type = history_item.get("signal_type")
    current_price = history_item.get("close_price")

    return WatchlistAnalysisItem(
        id=synthetic_id,
        watchlist_id=watchlist_id,
        analysis_date=date_class.fromisoformat(str(history_item["check_date"])[:10]),
        close_price=current_price,
        verdict=verdict,
        score=score,
        trend_outlook=_build_trend_outlook(verdict, signal_type, score),
        buy_action=_build_buy_action(verdict, signal_type, score),
        hold_action=_build_hold_action(
            verdict,
            signal_type,
            score,
            entry_price=entry_price,
            current_price=current_price,
        ),
        risk_level=_build_risk_level(
            verdict,
            signal_type,
            score,
            entry_price=entry_price,
            current_price=current_price,
            position_ratio=position_ratio,
        ),
        buy_recommendation=_build_buy_recommendation(verdict, signal_type, score),
        hold_recommendation=_build_hold_recommendation(
            verdict,
            signal_type,
            score,
            current_price=current_price,
            entry_price=entry_price,
        ),
        risk_recommendation=_build_risk_recommendation(
            verdict,
            signal_type,
            score,
            position_ratio=position_ratio,
        ),
        support_level=support_level,
        resistance_level=resistance_level,
        recommendation=_build_recommendation(
            verdict,
            signal_type,
            score,
            current_price=current_price,
            entry_price=entry_price,
            position_ratio=position_ratio,
        ),
    )


@router.get("/", response_model=WatchlistResponse)
async def get_watchlist(
    trade_date: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> WatchlistResponse:
    """获取当前用户的观察列表（带公共分析结果拼装）

    阶段2改造：公共结果复用模式
    1. 读取用户的 watchlist 配置（entry_price, position_ratio 等）
    2. 读取公共分析结果（StockAnalysis 表或缓存文件）
    3. 动态拼装展示数据，不触发重分析

    Args:
        trade_date: 指定交易日 (YYYY-MM-DD)，None 表示使用最新交易日
    """
    # 使用新的 WatchlistAnalysisService 进行拼装
    service = WatchlistAnalysisService(db)

    # 解析交易日期
    target_date: Optional[date_class] = None
    if trade_date:
        try:
            target_date = date_class.fromisoformat(trade_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD 格式")

    # 获取拼装后的数据
    results = service.get_watchlist_with_analysis(user.id, target_date)

    # 转换为响应格式
    items = []
    for item in results:
        # 基础字段（兼容旧格式）
        base_item = WatchlistItem(
            id=item["id"],
            code=item["code"],
            name=item["name"],
            add_reason=item["user_config"]["add_reason"],
            entry_price=item["user_config"]["entry_price"],
            position_ratio=item["user_config"]["position_ratio"],
            priority=item["user_config"]["priority"],
            is_active=True,
            added_at=date_class.today(),  # TODO: 从数据库获取真实值
        )

        # 添加分析结果（扩展字段）
        if item.get("analysis"):
            base_item.analysis = item["analysis"]
        if item.get("derived"):
            base_item.derived = item["derived"]

        items.append(base_item)

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
    """获取当前用户的观察股票分析历史。

    历史展示统一复用个股历史检查文件，不再读取废弃的 watchlist_analysis 表。
    """
    w = db.query(Watchlist).filter(Watchlist.id == item_id, Watchlist.user_id == user.id).first()
    if not w:
        raise HTTPException(status_code=404, detail="观察项不存在")

    history = analysis_service.get_stock_history_checks(w.code, 30)
    if not history:
        return {
            "code": w.code,
            "analyses": [],
            "total": 0,
        }

    df = analysis_service.load_stock_data(w.code)
    price_windows: dict[str, tuple[float | None, float | None]] = {}
    analyses: list[WatchlistAnalysisItem] = []

    if df is not None and not df.empty and "date" in df.columns:
        df = df.copy()
        df["trade_date_key"] = df["date"].astype(str).str[:10]

    for index, item in enumerate(history):
        check_date = str(item.get("check_date") or "")[:10]
        support_level = None
        resistance_level = None

        if check_date and check_date not in price_windows and df is not None and not df.empty:
            df_until_date = df[df["trade_date_key"] <= check_date]
            price_windows[check_date] = _calc_support_resistance(df_until_date)

        if check_date in price_windows:
            support_level, resistance_level = price_windows[check_date]

        analyses.append(
            _build_watchlist_history_item(
                watchlist_id=item_id,
                history_item=item,
                entry_price=w.entry_price,
                position_ratio=w.position_ratio,
                support_level=support_level,
                resistance_level=resistance_level,
                synthetic_id=item_id * 100000 + index + 1,
            )
        )

    return {
        "code": w.code,
        "analyses": analyses,
        "total": len(analyses),
    }


@router.post("/{item_id}/analyze")
async def analyze_watchlist_item(
    item_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_user),
) -> dict:
    """获取重点观察股票的分析结果（只读模式）

    阶段2改造：只读模式，不触发重分析
    1. 优先从 StockAnalysis 表读取公共结果
    2. 如果表不存在，从文件缓存读取
    3. 如果都不存在，返回 not_ready 状态
    4. 不再创建后台任务

    数据补齐应通过：
    - 管理员在任务中心发起离线任务
    - worker 自动补齐机制
    """
    w = db.query(Watchlist).filter(Watchlist.id == item_id, Watchlist.user_id == user.id).first()
    if not w:
        raise HTTPException(status_code=404, detail="观察项不存在")

    # 先尝试加载数据以确定交易日
    df = analysis_service.load_stock_data(w.code)
    tentative_date = _resolve_latest_trade_date(df)
    trade_date_str = tentative_date.strftime("%Y-%m-%d")

    # 1. 优先从 StockAnalysis 表读取（新的公共结果表）
    stock_analysis = (
        db.query(StockAnalysis)
        .filter(
            StockAnalysis.code == w.code,
            StockAnalysis.trade_date == tentative_date,
            StockAnalysis.analysis_type == "daily_b1",
            StockAnalysis.strategy_version == "v1",
        )
        .first()
    )

    if stock_analysis:
        # 从数据库获取到结果
        result = {
            "code": w.code,
            "close_price": stock_analysis.close_price,
            "verdict": stock_analysis.verdict,
            "score": stock_analysis.score,
            "signal_type": stock_analysis.signal_type,
            "b1_passed": stock_analysis.b1_passed,
            "kdj_j": stock_analysis.kdj_j,
            "zx_long_pos": stock_analysis.zx_long_pos,
            "weekly_ma_aligned": stock_analysis.weekly_ma_aligned,
            "volume_healthy": stock_analysis.volume_healthy,
            "analysis_date": trade_date_str,
            "_source": "stock_analysis_table",
        }
        # 补充 details_json 中的字段
        if stock_analysis.details_json:
            result.update(stock_analysis.details_json)
    else:
        # 2. 从文件缓存读取（兼容旧逻辑）
        cached_result = analysis_cache.get_cached_analysis(w.code, trade_date_str)

        if cached_result is not None:
            result = cached_result
            result["_source"] = "file_cache"
        else:
            # 3. 没有缓存结果，返回 not_ready 状态
            # 不再创建后台任务
            return {
                "status": "not_ready",
                "code": w.code,
                "message": "暂无分析结果，请等待数据更新或联系管理员",
                "trade_date": trade_date_str,
            }

    # 处理分析中的状态（兼容内存中的锁状态）
    if result.get("_status") in ("analyzing", "waiting"):
        return {
            "status": "pending",
            "code": w.code,
            "message": "分析正在进行中，请稍后再试",
            "_cache_key": result.get("_cache_key"),
        }

    # 处理分析结果（拼装公共结果 + 用户配置）
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

    # 阶段2：不再写入 WatchlistAnalysis 表
    # 该表已废弃，公共结果存储在 StockAnalysis 表
    # 用户配置存储在 Watchlist 表
    # 展示时动态拼装

    return {
        "status": "ok",
        "code": w.code,
        "analysis": {
            "id": item_id,  # 使用 watchlist_item_id
            "watchlist_id": item_id,
            "analysis_date": analysis_date,
            "close_price": current_price,
            "verdict": verdict,
            "score": score,
            "trend_outlook": trend_outlook,
            "buy_action": buy_action,
            "hold_action": hold_action,
            "risk_level": risk_level,
            "buy_recommendation": buy_recommendation,
            "hold_recommendation": hold_recommendation,
            "risk_recommendation": risk_recommendation,
            "support_level": support_level,
            "resistance_level": resistance_level,
            "recommendation": recommendation,
        },
        "user_config": {
            "entry_price": w.entry_price,
            "position_ratio": w.position_ratio,
            "add_reason": w.add_reason,
        },
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
