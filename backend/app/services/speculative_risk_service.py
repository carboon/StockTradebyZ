"""Speculative-risk detection service for narrative-driven hot stocks."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import Config


GENERIC_SECTOR_NAMES = {"", "当前热盘", "周期性股票", "热力股票池", "当前热盘AI标的"}


@dataclass(frozen=True)
class NarrativeThemeRule:
    name: str
    keywords: tuple[str, ...]
    related_codes: tuple[str, ...]
    related_names: tuple[str, ...]
    note: Optional[str] = None


class SpeculativeRiskService:
    """识别高热度、弱确认、强叙事的风险标的。"""

    CONFIG_KEY = "speculative_risk_catalog"

    def __init__(self, db: Session):
        self.db = db
        self._theme_rules: Optional[list[NarrativeThemeRule]] = None

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_text(value: Any) -> str:
        text = str(value or "").strip().lower()
        for token in (" ", "\t", "\n", "_", "-", "/", "（", "）", "(", ")", "，", ",", "。", "."):
            text = text.replace(token, "")
        return text

    @staticmethod
    def _unique_list(values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            segments = [
                segment.strip()
                for segment in value.replace("\r", "\n").replace("，", ",").split(",")
            ]
            if len(segments) == 1:
                segments = [
                    segment.strip()
                    for segment in value.replace("\r", "\n").replace("，", "\n").split("\n")
                ]
            return [segment for segment in segments if segment]
        return []

    def _load_theme_rules(self) -> list[NarrativeThemeRule]:
        if self._theme_rules is not None:
            return self._theme_rules

        raw_value = self.db.query(Config.value).filter(Config.key == self.CONFIG_KEY).scalar()
        raw_text = str(raw_value or "").strip()
        if not raw_text:
            self._theme_rules = []
            return self._theme_rules

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            self._theme_rules = []
            return self._theme_rules
        if not isinstance(payload, dict):
            self._theme_rules = []
            return self._theme_rules

        rules: list[NarrativeThemeRule] = []
        for item in list(payload.get("themes") or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            keywords = self._unique_list(
                [name] + self._normalize_string_list(item.get("keywords")) + self._normalize_string_list(item.get("aliases"))
            )
            related_codes = self._unique_list(
                [str(code).zfill(6) for code in self._normalize_string_list(item.get("related_codes")) if str(code or "").strip()]
            )
            related_names = self._unique_list(self._normalize_string_list(item.get("related_names")))
            rules.append(
                NarrativeThemeRule(
                    name=name,
                    keywords=tuple(keywords),
                    related_codes=tuple(related_codes),
                    related_names=tuple(related_names),
                    note=str(item.get("note") or "").strip() or None,
                )
            )

        self._theme_rules = rules
        return rules

    def _evaluate_narrative_matches(
        self,
        *,
        code: str,
        name: Optional[str],
        sector_names: list[str],
    ) -> tuple[float, list[str], list[str], list[str]]:
        normalized_name = self._normalize_text(name)
        normalized_sectors = [self._normalize_text(item) for item in sector_names if str(item or "").strip()]
        tags: list[str] = []
        reasons: list[str] = []
        matched_themes: list[str] = []
        score = 0.0

        for rule in self._load_theme_rules():
            matched = False
            if code in rule.related_codes:
                score += 22.0
                tags.append("故事关联映射")
                reasons.append(f"命中手工维护的关联题材: {rule.name}")
                matched = True
            elif normalized_name and any(
                len(self._normalize_text(keyword)) >= 2 and self._normalize_text(keyword) in normalized_name
                for keyword in rule.keywords + rule.related_names
            ):
                score += 18.0
                tags.append("名称/关键词映射")
                reasons.append(f"股票名称与题材关键词存在映射: {rule.name}")
                matched = True
            elif normalized_sectors and any(
                len(self._normalize_text(keyword)) >= 2
                and any(self._normalize_text(keyword) in sector for sector in normalized_sectors)
                for keyword in rule.keywords
            ):
                score += 12.0
                tags.append("题材关键词映射")
                reasons.append(f"所属题材命中手工维护关键词: {rule.name}")
                matched = True

            if matched:
                matched_themes.append(rule.name)

        return min(score, 35.0), self._unique_list(tags), self._unique_list(reasons), self._unique_list(matched_themes)

    def evaluate(
        self,
        *,
        code: str,
        name: Optional[str] = None,
        industry: Optional[str] = None,
        sector_names: Optional[list[str]] = None,
        change_pct: Optional[float] = None,
        turnover_rate: Optional[float] = None,
        volume_ratio: Optional[float] = None,
        active_pool_rank: Optional[int] = None,
        b1_passed: Optional[bool] = None,
        verdict: Optional[str] = None,
        total_score: Optional[float] = None,
        signal_type: Optional[str] = None,
        prefilter_passed: Optional[bool] = None,
        pullback_negative_flags: Optional[list[str]] = None,
        recent_limit_up_days: Optional[int] = None,
        recent_runup_pct: Optional[float] = None,
        sector_breadth: Optional[float] = None,
        sector_avg_change_pct: Optional[float] = None,
        isolated_spike: Optional[bool] = None,
        sector_focus_name: Optional[str] = None,
    ) -> dict[str, Any]:
        normalized_sector_names = self._unique_list(
            [str(item).strip() for item in (sector_names or []) if str(item or "").strip() and str(item).strip() not in GENERIC_SECTOR_NAMES]
        )
        normalized_industry = str(industry or "").strip()
        negative_flags = self._unique_list([str(item).strip() for item in (pullback_negative_flags or []) if str(item or "").strip()])

        heat_score = 0.0
        confirmation_score = 0.0
        narrative_score = 0.0
        tags: list[str] = []
        reasons: list[str] = []

        if active_pool_rank is not None:
            if active_pool_rank <= 10:
                heat_score += 25.0
            elif active_pool_rank <= 20:
                heat_score += 18.0
            elif active_pool_rank <= 50:
                heat_score += 12.0
            elif active_pool_rank <= 100:
                heat_score += 6.0

        change_pct_value = self._safe_float(change_pct)
        if change_pct_value is not None:
            if change_pct_value >= 8.0:
                heat_score += 18.0
            elif change_pct_value >= 5.0:
                heat_score += 12.0
            elif change_pct_value >= 2.0:
                heat_score += 6.0

        turnover_rate_value = self._safe_float(turnover_rate)
        if turnover_rate_value is not None:
            if turnover_rate_value >= 20.0:
                heat_score += 18.0
            elif turnover_rate_value >= 12.0:
                heat_score += 12.0
            elif turnover_rate_value >= 6.0:
                heat_score += 6.0

        volume_ratio_value = self._safe_float(volume_ratio)
        if volume_ratio_value is not None:
            if volume_ratio_value >= 3.0:
                heat_score += 14.0
            elif volume_ratio_value >= 1.8:
                heat_score += 9.0
            elif volume_ratio_value >= 1.2:
                heat_score += 4.0

        if recent_limit_up_days is not None:
            if recent_limit_up_days >= 2:
                heat_score += 22.0
                tags.append("连板/准连板")
                reasons.append(f"近 5 日出现 {recent_limit_up_days} 次近似涨停")
            elif recent_limit_up_days == 1:
                heat_score += 10.0

        if recent_runup_pct is not None:
            if recent_runup_pct >= 20.0:
                heat_score += 14.0
                reasons.append(f"近 5 日累计涨幅 {recent_runup_pct:.1f}%")
            elif recent_runup_pct >= 10.0:
                heat_score += 8.0

        if signal_type != "trend_start":
            confirmation_score += 24.0
            reasons.append(f"当前信号为 {signal_type or '未知'}，未确认趋势启动")

        if verdict == "FAIL":
            confirmation_score += 16.0
        elif verdict == "WATCH":
            confirmation_score += 10.0
        elif verdict is None:
            confirmation_score += 6.0

        if b1_passed is False:
            confirmation_score += 18.0
            reasons.append("B1 未通过")
        elif b1_passed is None:
            confirmation_score += 6.0

        if total_score is None:
            confirmation_score += 6.0
        elif total_score < 4.0:
            confirmation_score += 18.0
            reasons.append(f"量化评分偏低: {total_score:.1f}")
        elif total_score < 4.5:
            confirmation_score += 8.0

        if prefilter_passed is False:
            confirmation_score += 12.0
            reasons.append("前置过滤未通过")

        if negative_flags:
            confirmation_score += min(18.0, 8.0 + 4.0 * max(0, len(negative_flags) - 1))
            tags.append("负面结构")
            reasons.append(f"存在负面结构信号: {' / '.join(negative_flags)}")

        if normalized_sector_names:
            if len(normalized_sector_names) >= 3:
                narrative_score += 18.0
                tags.append("多题材叠加")
                reasons.append(f"同时挂钩 {len(normalized_sector_names)} 个题材")
            elif len(normalized_sector_names) == 2:
                narrative_score += 10.0
                tags.append("双题材叠加")

        if normalized_industry and normalized_sector_names:
            normalized_industry_text = self._normalize_text(normalized_industry)
            industry_matched = any(
                normalized_industry_text and (
                    normalized_industry_text in self._normalize_text(sector_name)
                    or self._normalize_text(sector_name) in normalized_industry_text
                )
                for sector_name in normalized_sector_names
            )
            if not industry_matched:
                narrative_score += 14.0
                tags.append("跨行业题材映射")
                reasons.append(f"题材与主营行业存在错位: {normalized_industry}")

        if isolated_spike:
            narrative_score += 18.0
            tags.append("板块内孤立拉升")
            if sector_focus_name and sector_breadth is not None and sector_avg_change_pct is not None and change_pct_value is not None:
                reasons.append(
                    f"{sector_focus_name} 普涨不足（上涨占比 {sector_breadth * 100:.0f}%），但个股涨幅 {change_pct_value:.1f}% 明显高于板块均值 {sector_avg_change_pct:.1f}%"
                )
            else:
                reasons.append("板块内普涨不足，个股走势明显脱离板块均值")

        theme_score, theme_tags, theme_reasons, matched_themes = self._evaluate_narrative_matches(
            code=code,
            name=name,
            sector_names=normalized_sector_names,
        )
        narrative_score += theme_score
        tags.extend(theme_tags)
        reasons.extend(theme_reasons)

        heat_score = min(100.0, heat_score)
        confirmation_score = min(100.0, confirmation_score)
        narrative_score = min(100.0, narrative_score)

        raw_risk_score = heat_score * 0.45 + confirmation_score * 0.35 + narrative_score * 0.20
        if heat_score >= 55.0 and (confirmation_score >= 30.0 or narrative_score >= 22.0):
            level = "high"
            raw_risk_score = max(raw_risk_score, 60.0)
        elif heat_score >= 35.0 and (confirmation_score >= 20.0 or narrative_score >= 14.0):
            level = "medium"
            raw_risk_score = max(raw_risk_score, 40.0)
        elif raw_risk_score >= 48.0:
            level = "medium"
        else:
            level = "low"

        if heat_score >= 40.0:
            tags.append("高热度追捧")
        if confirmation_score >= 26.0:
            tags.append("技术确认不足")
        if theme_score > 0:
            tags.append("手工叙事命中")
        if narrative_score >= 22.0 and theme_score == 0:
            tags.append("叙事驱动")

        reversal_risk = bool(heat_score >= 55.0 and confirmation_score >= 25.0)
        if level == "high":
            summary = "热度显著高于技术确认，属于情绪化风险标的，需防范退潮后的快速回撤。"
        elif level == "medium":
            summary = "热度与结构出现背离，适合纳入风险标的跟踪。"
        else:
            summary = "暂无明显的情绪化风险特征。"

        return {
            "level": level,
            "score": round(min(raw_risk_score, 100.0), 1),
            "heat_score": round(heat_score, 1),
            "confirmation_score": round(confirmation_score, 1),
            "narrative_score": round(narrative_score, 1),
            "recent_limit_up_days": recent_limit_up_days,
            "recent_runup_pct": round(recent_runup_pct, 2) if recent_runup_pct is not None else None,
            "sector_breadth": round(sector_breadth, 4) if sector_breadth is not None else None,
            "sector_avg_change_pct": round(sector_avg_change_pct, 2) if sector_avg_change_pct is not None else None,
            "isolated_spike": bool(isolated_spike),
            "reversal_risk": reversal_risk,
            "tags": self._unique_list(tags),
            "reasons": self._unique_list(reasons),
            "matched_themes": matched_themes,
            "summary": summary,
        }
