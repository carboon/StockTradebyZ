"""AI-assisted regime confirmation for speculative overheating."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Config, Stock
from app.services.deepseek_service import DeepSeekService
from app.services.tushare_service import TushareService


class RiskRegimeAIService:
    """基于结构化上下文和外部证据，使用 AI 做二次确认。"""

    ENABLED_CONFIG_KEY = "risk_regime_ai_enabled"

    def __init__(self, db: Session):
        self.db = db
        self.tushare_service = TushareService()
        self.deepseek_service = DeepSeekService(api_key=self._load_deepseek_api_key())

    def _load_deepseek_api_key(self) -> str:
        value = self.db.query(Config.value).filter(Config.key == "deepseek_api_key").scalar()
        return str(value or "").strip()

    def is_enabled(self) -> bool:
        value = self.db.query(Config.value).filter(Config.key == self.ENABLED_CONFIG_KEY).scalar()
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return self.deepseek_service.enabled
        return False

    @staticmethod
    def _to_ts_code(code: str, market: Optional[str]) -> str:
        normalized = str(code or "").zfill(6)
        suffix = str(market or "").strip().upper()
        if suffix in {"SH", "SZ", "BJ"}:
            return f"{normalized}.{suffix}"
        if normalized.startswith(("600", "601", "603", "605", "688", "689")):
            return f"{normalized}.SH"
        if normalized.startswith(("430", "8", "920")):
            return f"{normalized}.BJ"
        return f"{normalized}.SZ"

    @staticmethod
    def _trim_text(value: Any, limit: int = 160) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    def _collect_news_signals(
        self,
        *,
        names: list[str],
        themes: list[str],
        start_date: str,
        end_date: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        keywords = [item for item in names + themes if str(item or "").strip()]
        if not keywords:
            return []

        news_items = self.tushare_service.get_news_items(start_date=start_date, end_date=end_date, limit=limit * 2)
        matched: list[dict[str, Any]] = []
        lowered_keywords = [str(item).strip().lower() for item in keywords]
        for item in news_items:
            haystack = f"{item.get('title') or ''} {item.get('content') or ''}".lower()
            if any(keyword and keyword in haystack for keyword in lowered_keywords):
                matched.append({
                    "datetime": item.get("datetime"),
                    "title": self._trim_text(item.get("title"), 80),
                    "content": self._trim_text(item.get("content"), 120),
                    "src": item.get("src"),
                })
            if len(matched) >= limit:
                break
        return matched

    def build_market_context(
        self,
        *,
        pick_date: date,
        items: list[dict[str, Any]],
        base_regime: dict[str, Any],
    ) -> dict[str, Any]:
        target_stocks = sorted(
            items,
            key=lambda item: (
                0 if str((item.get("risk_flag") or {}).get("level") or "") == "high" else 1,
                -float((item.get("risk_flag") or {}).get("score") or 0.0),
            ),
        )[:6]

        stock_rows = (
            self.db.query(Stock.code, Stock.name, Stock.market)
            .filter(Stock.code.in_([str(item.get("code") or "").zfill(6) for item in target_stocks]))
            .all()
        )
        stock_map = {str(code).zfill(6): {"name": name, "market": market} for code, name, market in stock_rows}

        evidence_items: list[dict[str, Any]] = []
        all_names: list[str] = []
        all_themes: list[str] = []
        start_date = (pick_date - timedelta(days=10)).strftime("%Y%m%d")
        end_date = pick_date.strftime("%Y%m%d")
        trade_date = pick_date.strftime("%Y%m%d")

        for item in target_stocks:
            code = str(item.get("code") or "").zfill(6)
            stock_meta = stock_map.get(code, {})
            name = str(item.get("name") or stock_meta.get("name") or code)
            market = stock_meta.get("market")
            ts_code = self._to_ts_code(code, market)
            risk_flag = item.get("risk_flag") or {}
            all_names.append(name)
            all_themes.extend([str(theme) for theme in risk_flag.get("matched_themes") or []])
            all_themes.extend([str(theme) for theme in item.get("sector_names") or []])

            evidence_items.append({
                "code": code,
                "name": name,
                "sector_names": item.get("sector_names") or [],
                "signal_type": item.get("signal_type"),
                "b1_passed": item.get("b1_passed"),
                "total_score": item.get("total_score"),
                "change_pct": item.get("change_pct"),
                "turnover_rate": item.get("turnover_rate"),
                "volume_ratio": item.get("volume_ratio"),
                "risk_flag": risk_flag,
                "announcements": self.tushare_service.get_announcements(ts_code, start_date=start_date, end_date=end_date, limit=6),
                "abnormal_volatility": self.tushare_service.get_abnormal_volatility_events(ts_code, trade_date=trade_date, limit=4),
            })

        matched_news = self._collect_news_signals(
            names=list(dict.fromkeys(all_names)),
            themes=list(dict.fromkeys([theme for theme in all_themes if theme])),
            start_date=start_date,
            end_date=end_date,
            limit=16,
        )

        return {
            "pick_date": pick_date.isoformat(),
            "base_regime": base_regime,
            "target_stocks": evidence_items,
            "matched_news": matched_news,
            "notes": {
                "source_priority": [
                    "local_rule_engine",
                    "tushare_announcements",
                    "tushare_abnormal_volatility",
                    "tushare_news_keyword_match",
                ],
                "missing_evidence_allowed": True,
            },
        }

    def confirm_market_regime(
        self,
        *,
        pick_date: date,
        items: list[dict[str, Any]],
        base_regime: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        if not self.is_enabled():
            return None

        context = self.build_market_context(pick_date=pick_date, items=items, base_regime=base_regime)
        system_prompt = (
            "你是A股短线投机风险分析助手。"
            "你需要结合规则初筛结果、公告、异常波动信息和新闻线索，"
            "判断市场是否处于‘过热转调整的急跌前夜’。"
            "如果证据不足，必须明确标注 evidence_strength 为 weak，不能硬下结论。"
            "返回必须是 JSON object，不要输出 markdown。"
        )
        user_prompt = (
            "请分析下面的市场级风险上下文。\n"
            "要求：\n"
            "1. 先判断本地规则结论是否可信。\n"
            "2. 若公告/异常波动/新闻能够支持‘题材炒作、无明显业绩支撑、故事驱动、监管关注、澄清降温’，提高确认度。\n"
            "3. 若外部证据不足，必须说明你是在规则基础上做保守确认。\n"
            "4. 固定返回字段："
            '{"confirmed_level":"low|medium|high","confidence":0-100,'
            '"evidence_strength":"weak|medium|strong","stance":"confirm|soft_confirm|reject",'
            '"summary":"string","reasons":["string"],"risk_signals":["string"],'
            '"news_findings":["string"],"announcement_findings":["string"],"warnings":["string"]}\n'
            f"上下文如下：\n{json.dumps(context, ensure_ascii=False)}"
        )
        result = self.deepseek_service.infer_json(system_prompt=system_prompt, user_prompt=user_prompt)
        return {
            "provider": "deepseek",
            "model": self.deepseek_service.DEFAULT_MODEL,
            "enabled": True,
            "context": context,
            "result": result,
        }
