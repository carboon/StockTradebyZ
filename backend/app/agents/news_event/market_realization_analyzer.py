"""Market realization analyzer - checks if market has priced in the news."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from .schemas import RealizationStatus, StockRealization

logger = logging.getLogger(__name__)


class MarketRealizationAnalyzer:
    """行情兑现判断器 - 查询本地行情数据，判断是否已被市场交易。"""

    def analyze(self, stock_codes: list[str], event_time: Optional[str],
                db: Session) -> list[StockRealization]:
        if not stock_codes or not db:
            return []

        results: list[StockRealization] = []

        try:
            from app.models import Stock, StockDaily

            event_date: Optional[date] = None
            if event_time:
                try:
                    event_date = datetime.fromisoformat(
                        event_time.replace("Z", "+00:00")
                    ).date()
                except (ValueError, TypeError):
                    pass

            stocks = db.query(Stock).filter(Stock.code.in_(stock_codes)).all()
            stock_map = {s.code: s for s in stocks}

            for code in stock_codes:
                stock = stock_map.get(code)
                if not stock:
                    results.append(StockRealization(
                        code=code, name=code,
                        realization_status=RealizationStatus.INSUFFICIENT_MARKET_DATA,
                        reason="未在本地股票库中找到该标的。",
                    ))
                    continue

                dailies = (
                    db.query(StockDaily)
                    .filter(StockDaily.code == code)
                    .order_by(StockDaily.trade_date.desc())
                    .limit(25)
                    .all()
                )

                if not dailies:
                    results.append(StockRealization(
                        code=code, name=stock.name or code,
                        realization_status=RealizationStatus.INSUFFICIENT_MARKET_DATA,
                        reason="无本地行情数据。",
                    ))
                    continue

                realization = self._compute_realization(
                    code=code, name=stock.name or code,
                    dailies=dailies, event_date=event_date,
                )
                results.append(realization)

        except Exception as exc:
            logger.warning("MarketRealizationAnalyzer 查询失败: %s", exc)

        return results

    @staticmethod
    def _compute_realization(
        code: str, name: str, dailies: list[Any],
        event_date: Optional[date],
    ) -> StockRealization:
        today_record = dailies[0] if dailies else None
        today_close = float(getattr(today_record, "close", 0) or 0)

        def get_close(offset: int) -> float:
            if offset < len(dailies):
                return float(getattr(dailies[offset], "close", 0) or 0)
            return 0.0

        def calc_change(offset: int) -> Optional[float]:
            close = get_close(offset)
            if close <= 0 or today_close <= 0:
                return None
            return round((today_close - close) / close * 100, 2)

        change_1d = calc_change(1) if len(dailies) > 1 and get_close(1) > 0 else None
        change_3d = calc_change(3) if len(dailies) > 3 and get_close(3) > 0 else None
        change_5d = calc_change(5) if len(dailies) > 5 and get_close(5) > 0 else None
        change_20d = calc_change(20) if len(dailies) > 20 and get_close(20) > 0 else None

        limit_up = False
        if today_record:
            pre_close = float(getattr(today_record, "pre_close", 0) or 0)
            if pre_close > 0 and today_close > 0:
                pct = (today_close - pre_close) / pre_close * 100
                limit_up = pct >= 9.9

        volume_ratio: Optional[float] = None
        if today_record and len(dailies) > 1:
            today_vol = float(getattr(today_record, "vol", 0) or 0)
            if today_vol > 0:
                prev_vols = [
                    float(getattr(dailies[i], "vol", 0) or 0)
                    for i in range(1, min(6, len(dailies)))
                ]
                avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0
                if avg_vol > 0:
                    volume_ratio = round(today_vol / avg_vol, 2)

        moved_before_news = False
        realization_status = RealizationStatus.NOT_REALIZED
        reason = ""

        if limit_up:
            moved_before_news = True
            realization_status = RealizationStatus.MOVED_BEFORE_NEWS
            reason = "消息相关标的已涨停，短线利好可能已提前反应。"

        if change_5d is not None and change_5d > 15:
            if not limit_up:
                moved_before_news = True
            realization_status = RealizationStatus.LIKELY_PRICED_IN
            reason = f"近5日涨幅 {change_5d}%，短期利好可能已充分定价。"

        if change_3d is not None and change_3d > 8:
            if realization_status == RealizationStatus.NOT_REALIZED:
                realization_status = RealizationStatus.PARTIALLY_REALIZED
                reason = f"近3日涨幅 {change_3d}%，部分利好已兑现。"

        if change_1d is not None and change_1d > 5:
            if realization_status == RealizationStatus.NOT_REALIZED:
                realization_status = RealizationStatus.PARTIALLY_REALIZED
                reason = f"当日涨幅 {change_1d}%，部分利好已在盘中兑现。"

        if change_5d is not None and change_5d < -10:
            realization_status = RealizationStatus.NOT_REALIZED
            reason = f"近5日跌幅 {change_5d}%，存在超跌修复机会，但需确认基本面。"

        if realization_status == RealizationStatus.NOT_REALIZED:
            reason = reason or "近期无明显异动，关注消息发酵后市场反应。"

        return StockRealization(
            code=code, name=name,
            change_1d=change_1d, change_3d=change_3d,
            change_5d=change_5d, change_20d=change_20d,
            limit_up=limit_up, volume_ratio=volume_ratio,
            moved_before_news=moved_before_news,
            realization_status=realization_status,
            reason=reason,
        )


market_realization_analyzer = MarketRealizationAnalyzer()
