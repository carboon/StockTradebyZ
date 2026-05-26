"""Single-stock AI context and analysis."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Config, CustomConcept, CustomConceptStockTag, DailyB1Check, Stock, StockDaily
from app.services.deepseek_service import DeepSeekService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now


class StockAiAnalysisService:
    PROMPT_VERSION = "v1"

    def __init__(self, db: Session):
        self.db = db
        self.tushare_service = TushareService()
        self.deepseek_service = DeepSeekService(api_key=self._load_deepseek_api_key())

    def _load_deepseek_api_key(self) -> str:
        value = self.db.query(Config.value).filter(Config.key == "deepseek_api_key").scalar()
        return str(value or "").strip()

    @staticmethod
    def _normalize_code(value: Any) -> str:
        text = str(value or "").strip()
        if "." in text:
            text = text.split(".", 1)[0]
        return text.zfill(6) if text else ""

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _latest_daily_context(self, code: str) -> dict[str, Any]:
        rows = (
            self.db.query(StockDaily)
            .filter(StockDaily.code == code)
            .order_by(StockDaily.trade_date.desc())
            .limit(2)
            .all()
        )
        latest = rows[0] if rows else None
        previous = rows[1] if len(rows) > 1 else None
        change_pct = None
        if latest and previous and previous.close:
            change_pct = (latest.close - previous.close) / previous.close * 100
        return {
            "trade_date": latest.trade_date.isoformat() if latest else None,
            "close": latest.close if latest else None,
            "previous_close": previous.close if previous else None,
            "change_pct": round(change_pct, 4) if change_pct is not None else None,
            "turnover_rate": latest.turnover_rate if latest else None,
            "volume_ratio": latest.volume_ratio if latest else None,
        }

    def _sector_context(self, stock: Stock, daily_context: dict[str, Any]) -> dict[str, Any]:
        industry = str(stock.industry or "").strip()
        trade_date_text = daily_context.get("trade_date")
        trade_date = None
        if trade_date_text:
            try:
                trade_date = date.fromisoformat(str(trade_date_text))
            except Exception:
                trade_date = trade_date_text
        if not industry or not trade_date:
            return {"industry": industry or None, "avg_change_pct": None, "up_count": 0, "down_count": 0, "sample_count": 0}

        latest_rows = (
            self.db.query(StockDaily.code, StockDaily.close)
            .join(Stock, Stock.code == StockDaily.code)
            .filter(Stock.industry == industry, StockDaily.trade_date == trade_date)
            .all()
        )
        previous_date = (
            self.db.query(func.max(StockDaily.trade_date))
            .filter(StockDaily.trade_date < trade_date)
            .scalar()
        )
        previous_map = dict(
            self.db.query(StockDaily.code, StockDaily.close)
            .filter(StockDaily.trade_date == previous_date)
            .all()
        ) if previous_date else {}

        changes: list[float] = []
        for code, close in latest_rows:
            previous_close = previous_map.get(code)
            if previous_close:
                changes.append((float(close) - float(previous_close)) / float(previous_close) * 100)

        return {
            "industry": industry,
            "trade_date": str(trade_date_text),
            "avg_change_pct": round(sum(changes) / len(changes), 4) if changes else None,
            "up_count": sum(1 for item in changes if item > 0),
            "down_count": sum(1 for item in changes if item < 0),
            "sample_count": len(changes),
        }

    def _custom_concepts_context(self, code: str) -> list[dict[str, Any]]:
        rows = (
            self.db.query(CustomConceptStockTag, CustomConcept.display_name)
            .join(CustomConcept, CustomConcept.id == CustomConceptStockTag.concept_id)
            .filter(CustomConceptStockTag.stock_code == code)
            .order_by(func.coalesce(CustomConceptStockTag.relevance_score, -1.0).desc())
            .limit(20)
            .all()
        )
        return [
            {
                "concept_name": display_name,
                "relevance_score": tag.relevance_score,
                "confidence": tag.confidence,
                "chain_position": tag.chain_position,
                "role_tags": tag.role_tags_json or [],
                "reason": tag.reason,
            }
            for tag, display_name in rows
        ]

    def _latest_diagnosis_context(self, code: str) -> dict[str, Any]:
        row = (
            self.db.query(DailyB1Check)
            .filter(DailyB1Check.code == code)
            .order_by(DailyB1Check.check_date.desc(), DailyB1Check.id.desc())
            .first()
        )
        if row is None:
            return {}
        return {
            "check_date": row.check_date.isoformat() if row.check_date else None,
            "b1_passed": row.b1_passed,
            "score": row.score,
            "b1_signal_type": row.b1_signal_type,
            "notes": row.notes,
            "turnover_rate": row.turnover_rate,
            "volume_ratio": row.volume_ratio,
            "active_pool_rank": row.active_pool_rank,
        }

    def _news_context(self, stock: Stock, concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        end_date = utc_now().date()
        start_date = end_date - timedelta(days=14)
        keywords = [
            str(stock.name or "").strip(),
            str(stock.industry or "").strip(),
            *[str(item.get("concept_name") or "").strip() for item in concepts[:5]],
        ]
        keywords = [item for item in keywords if item]
        news_items = self.tushare_service.get_news_items(
            src="yicai",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            limit=80,
        )
        matched: list[dict[str, Any]] = []
        for item in news_items:
            text = f"{item.get('title') or ''} {item.get('content') or ''}"
            if not any(keyword in text for keyword in keywords):
                continue
            matched.append({
                "datetime": item.get("datetime"),
                "title": item.get("title"),
                "content": item.get("content"),
                "src": item.get("src"),
            })
            if len(matched) >= 12:
                break
        return matched

    def analyze(self, code: str) -> dict[str, Any]:
        normalized_code = self._normalize_code(code)
        if not normalized_code:
            raise ValueError("股票代码不能为空")
        if not self.deepseek_service.enabled:
            raise ValueError("DeepSeek API Key 未配置")

        stock = self.db.query(Stock).filter(Stock.code == normalized_code).first()
        if stock is None:
            raise LookupError("股票不存在")

        daily_context = self._latest_daily_context(normalized_code)
        concepts = self._custom_concepts_context(normalized_code)
        context = {
            "stock": {
                "code": normalized_code,
                "name": stock.name,
                "industry": stock.industry,
                "market": stock.market,
            },
            "daily": daily_context,
            "sector": self._sector_context(stock, daily_context),
            "custom_concepts": concepts,
            "latest_diagnosis": self._latest_diagnosis_context(normalized_code),
            "news": self._news_context(stock, concepts),
        }
        system_prompt = (
            "你是A股单股产业链与消息面分析助手。"
            "只能基于提供的上下文分析，必须输出 JSON object，不能输出 markdown。"
        )
        user_prompt = (
            "请分析这只股票所在板块表现、上下游关联、异动消息、三大利好和三大利空。\n"
            "固定 JSON 字段："
            '{"summary":"string","sector_view":{"avg_change_pct":0,"comment":"string"},'
            '"upstream_stocks":[{"code":"string","name":"string","reason":"string"}],'
            '"downstream_stocks":[{"code":"string","name":"string","reason":"string"}],'
            '"abnormal_news":["string"],"top_bullish":["string"],"top_bearish":["string"],'
            '"risk_notes":["string"],"confidence":0-100}\n'
            f"上下文：\n{json.dumps(context, ensure_ascii=False, default=str)}"
        )
        result = self.deepseek_service.infer_json(system_prompt=system_prompt, user_prompt=user_prompt)
        if not isinstance(result, dict):
            raise ValueError("AI 返回格式错误")
        return {
            "code": normalized_code,
            "name": stock.name,
            "provider": "deepseek",
            "model": self.deepseek_service.DEFAULT_MODEL,
            "context": context,
            "result": result,
        }
