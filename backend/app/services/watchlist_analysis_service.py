"""
Watchlist Analysis Service
~~~~~~~~~~~~~~~~~~~~~~~~~~
重点观察分析服务：公共结果 + 用户配置拼装

负责：
1. 读取用户的 watchlist 配置
2. 读取公共分析结果 (StockAnalysis)
3. 动态拼装展示数据
"""
from datetime import date as date_class
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models import Watchlist, Stock, StockAnalysis, StockDaily
from app.services.analysis_cache import analysis_cache
from app.time_utils import utc_now


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


def _calc_support_resistance(df) -> tuple[float | None, float | None]:
    """计算支撑位和阻力位"""
    if df is None or df.empty:
        return None, None
    frame = df.sort_values("date").reset_index(drop=True).tail(20)
    if frame.empty:
        return None, None
    support = float(frame["low"].min()) if "low" in frame.columns else None
    resistance = float(frame["high"].max()) if "high" in frame.columns else None
    return support, resistance


def _build_trend_outlook(verdict: str | None, signal_type: str | None, score: float | None) -> str:
    """构建趋势展望"""
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
    """构建风险等级"""
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
    """构建买入建议"""
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
    """构建持有建议"""
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
    """构建综合建议"""
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


class WatchlistAnalysisService:
    """重点观察分析服务"""

    def __init__(self, db: Session):
        self.db = db

    def get_watchlist_with_analysis(
        self,
        user_id: int,
        trade_date: Optional[date_class] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取用户的重点观察列表，并拼装公共分析结果

        Args:
            user_id: 用户ID
            trade_date: 指定交易日，None 表示最新交易日

        Returns:
            拼装后的观察列表数据
        """
        # 1. 获取用户的 watchlist
        watchlist_query = (
            self.db.query(Watchlist, Stock)
            .outerjoin(Stock, Watchlist.code == Stock.code)
            .filter(Watchlist.user_id == user_id, Watchlist.is_active == True)
            .order_by(Watchlist.priority.desc(), Watchlist.added_at.desc())
        )
        watchlist_items = watchlist_query.all()

        if not watchlist_items:
            return []

        # 提取所有关注的股票代码
        codes = [w.code for w, _ in watchlist_items]

        # 2. 批量查询公共分析结果
        analysis_map = self._load_analysis_map(codes, trade_date)
        levels_map = self._load_support_resistance_map(codes)

        # 3. 拼装结果
        results = []
        for w, stock in watchlist_items:
            item = {
                "id": w.id,
                "code": w.code,
                "name": stock.name if stock else None,
                "user_config": {
                    "entry_price": w.entry_price,
                    "position_ratio": w.position_ratio,
                    "add_reason": w.add_reason,
                    "priority": w.priority,
                },
            }

            # 获取该股票的分析结果
            analysis = analysis_map.get(w.code)
            if analysis:
                # 计算派生字段
                current_price = analysis.close_price
                entry_price = w.entry_price
                position_ratio = w.position_ratio

                pnl = None
                if entry_price and current_price:
                    pnl = current_price / entry_price - 1.0

                item["analysis"] = {
                    "trade_date": analysis.trade_date.isoformat() if analysis.trade_date else None,
                    "close_price": analysis.close_price,
                    "verdict": analysis.verdict,
                    "score": analysis.score,
                    "signal_type": analysis.signal_type,
                    "b1_passed": analysis.b1_passed,
                    "kdj_j": analysis.kdj_j,
                    "zx_long_pos": analysis.zx_long_pos,
                    "weekly_ma_aligned": analysis.weekly_ma_aligned,
                    "volume_healthy": analysis.volume_healthy,
                }

                # 批量预取近 20 日行情后统一计算支撑/阻力位，避免逐只股票重复查库
                support_level, resistance_level = levels_map.get(w.code, (None, None))

                # 派生字段
                item["derived"] = {
                    "pnl": pnl,
                    "trend_outlook": _build_trend_outlook(
                        analysis.verdict, analysis.signal_type, analysis.score
                    ),
                    "buy_action": _build_buy_action(
                        analysis.verdict, analysis.signal_type, analysis.score
                    ),
                    "hold_action": _build_hold_action(
                        analysis.verdict,
                        analysis.signal_type,
                        analysis.score,
                        entry_price=entry_price,
                        current_price=current_price,
                    ),
                    "risk_level": _build_risk_level(
                        analysis.verdict,
                        analysis.signal_type,
                        analysis.score,
                        entry_price=entry_price,
                        current_price=current_price,
                        position_ratio=position_ratio,
                    ),
                    "recommendation": _build_recommendation(
                        analysis.verdict,
                        analysis.signal_type,
                        analysis.score,
                        current_price=current_price,
                        entry_price=entry_price,
                        position_ratio=position_ratio,
                    ),
                    "support_level": support_level,
                    "resistance_level": resistance_level,
                }
            else:
                # 没有分析结果
                item["analysis"] = None
                item["derived"] = None

            results.append(item)

        return results

    def _load_analysis_map(
        self,
        codes: List[str],
        trade_date: Optional[date_class],
    ) -> Dict[str, StockAnalysis]:
        if not codes:
            return {}

        if trade_date is not None:
            stock_analyses = (
                self.db.query(StockAnalysis)
                .filter(
                    StockAnalysis.code.in_(codes),
                    StockAnalysis.trade_date == trade_date,
                )
                .all()
            )
            return {analysis.code: analysis for analysis in stock_analyses}

        latest_trade_dates = (
            self.db.query(
                StockAnalysis.code.label("code"),
                func.max(StockAnalysis.trade_date).label("latest_trade_date"),
            )
            .filter(StockAnalysis.code.in_(codes))
            .group_by(StockAnalysis.code)
            .subquery()
        )

        stock_analyses = (
            self.db.query(StockAnalysis)
            .join(
                latest_trade_dates,
                and_(
                    StockAnalysis.code == latest_trade_dates.c.code,
                    StockAnalysis.trade_date == latest_trade_dates.c.latest_trade_date,
                ),
            )
            .all()
        )
        return {analysis.code: analysis for analysis in stock_analyses}

    def _load_support_resistance_map(
        self,
        codes: List[str],
        lookback: int = 20,
    ) -> Dict[str, tuple[float | None, float | None]]:
        if not codes:
            return {}

        trade_dates_subquery = (
            self.db.query(
                StockDaily.code.label("code"),
                StockDaily.trade_date.label("trade_date"),
                func.row_number().over(
                    partition_by=StockDaily.code,
                    order_by=StockDaily.trade_date.desc(),
                ).label("rn"),
            )
            .filter(StockDaily.code.in_(codes))
            .subquery()
        )

        rows = (
            self.db.query(
                StockDaily.code,
                StockDaily.trade_date,
                StockDaily.low,
                StockDaily.high,
            )
            .join(
                trade_dates_subquery,
                and_(
                    StockDaily.code == trade_dates_subquery.c.code,
                    StockDaily.trade_date == trade_dates_subquery.c.trade_date,
                ),
            )
            .filter(trade_dates_subquery.c.rn <= lookback)
            .all()
        )

        grouped: Dict[str, List[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row.code, []).append({
                "date": row.trade_date,
                "low": row.low,
                "high": row.high,
            })

        levels_map: Dict[str, tuple[float | None, float | None]] = {}
        for code, values in grouped.items():
            df = pd.DataFrame(values)
            levels_map[code] = _calc_support_resistance(df)

        return levels_map

    def get_stock_analysis_from_cache(
        self,
        code: str,
        trade_date: Optional[date_class] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        从缓存获取股票分析结果

        优先从 StockAnalysis 表查询，如果没有则尝试从文件缓存读取

        Args:
            code: 股票代码
            trade_date: 交易日，None 表示最新

        Returns:
            分析结果字典，如果不存在则返回 None
        """
        # 1. 先尝试从数据库查询
        query = self.db.query(StockAnalysis).filter(StockAnalysis.code == code)

        if trade_date:
            query = query.filter(StockAnalysis.trade_date == trade_date)
        else:
            # 获取最新的分析结果
            query = query.order_by(StockAnalysis.trade_date.desc())

        analysis = query.first()
        if analysis:
            return {
                "code": analysis.code,
                "trade_date": analysis.trade_date.isoformat() if analysis.trade_date else None,
                "close_price": analysis.close_price,
                "verdict": analysis.verdict,
                "score": analysis.score,
                "signal_type": analysis.signal_type,
                "b1_passed": analysis.b1_passed,
                "kdj_j": analysis.kdj_j,
                "zx_long_pos": analysis.zx_long_pos,
                "weekly_ma_aligned": analysis.weekly_ma_aligned,
                "volume_healthy": analysis.volume_healthy,
                "details": analysis.details_json,
            }

        # 2. 从文件缓存读取
        if trade_date:
            trade_date_str = trade_date.isoformat()
        else:
            # 尝试从文件系统获取最新日期
            from app.services.analysis_service import analysis_service
            trade_date_str = analysis_service.get_latest_result_date()
            if not trade_date_str:
                return None

        cached_result = analysis_cache.get_cached_analysis(code, trade_date_str)
        if cached_result:
            return cached_result

        return None

    def save_stock_analysis(
        self,
        code: str,
        trade_date: date_class,
        analysis_result: Dict[str, Any],
        analysis_type: str = "daily_b1",
        strategy_version: str = "v1",
    ) -> StockAnalysis:
        """
        保存或更新公共分析结果

        Args:
            code: 股票代码
            trade_date: 交易日
            analysis_result: 分析结果字典
            analysis_type: 分析类型
            strategy_version: 策略版本

        Returns:
            保存后的 StockAnalysis 对象
        """
        # 查找是否已存在
        analysis = (
            self.db.query(StockAnalysis)
            .filter(
                StockAnalysis.code == code,
                StockAnalysis.trade_date == trade_date,
                StockAnalysis.analysis_type == analysis_type,
                StockAnalysis.strategy_version == strategy_version,
            )
            .first()
        )

        if analysis:
            # 更新现有记录
            analysis.close_price = analysis_result.get("close_price")
            analysis.verdict = analysis_result.get("verdict")
            analysis.score = analysis_result.get("score") or analysis_result.get("total_score")
            analysis.signal_type = analysis_result.get("signal_type")
            analysis.b1_passed = analysis_result.get("b1_passed")
            analysis.kdj_j = analysis_result.get("kdj_j")
            analysis.zx_long_pos = analysis_result.get("zx_long_pos")
            analysis.weekly_ma_aligned = analysis_result.get("weekly_ma_aligned")
            analysis.volume_healthy = analysis_result.get("volume_healthy")
            analysis.details_json = analysis_result.get("details")
            analysis.updated_at = utc_now()
        else:
            # 创建新记录
            analysis = StockAnalysis(
                code=code,
                trade_date=trade_date,
                analysis_type=analysis_type,
                strategy_version=strategy_version,
                close_price=analysis_result.get("close_price"),
                verdict=analysis_result.get("verdict"),
                score=analysis_result.get("score") or analysis_result.get("total_score"),
                signal_type=analysis_result.get("signal_type"),
                b1_passed=analysis_result.get("b1_passed"),
                kdj_j=analysis_result.get("kdj_j"),
                zx_long_pos=analysis_result.get("zx_long_pos"),
                weekly_ma_aligned=analysis_result.get("weekly_ma_aligned"),
                volume_healthy=analysis_result.get("volume_healthy"),
                details_json=analysis_result.get("details"),
            )
            self.db.add(analysis)

        self.db.commit()
        self.db.refresh(analysis)
        return analysis
