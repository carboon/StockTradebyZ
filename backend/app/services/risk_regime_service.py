"""Market-level overheating and reversal-risk regime service."""
from __future__ import annotations

from typing import Any, Optional


class RiskRegimeService:
    """根据全市场样本的风险分布，识别市场是否处于过热转弱区间。"""

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> Optional[float]:
        if denominator <= 0:
            return None
        return numerator / denominator

    @staticmethod
    def _pct_text(value: Optional[float]) -> str:
        if value is None:
            return "-"
        return f"{value * 100:.0f}%"

    @staticmethod
    def _avg(values: list[float]) -> Optional[float]:
        if not values:
            return None
        return sum(values) / len(values)

    def evaluate(
        self,
        *,
        items: list[dict[str, Any]],
        previous_items: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        total_count = len(items)
        if total_count <= 0:
            return {
                "level": "low",
                "score": 0.0,
                "heat_score": 0.0,
                "failure_score": 0.0,
                "breadth_score": 0.0,
                "triggered": False,
                "risk_count": 0,
                "total_count": 0,
                "risk_ratio": None,
                "high_risk_count": 0,
                "reversal_risk_count": 0,
                "isolated_spike_ratio": None,
                "b1_pass_ratio": None,
                "trend_start_ratio": None,
                "failure_ratio": None,
                "risk_trend": None,
                "tags": [],
                "reasons": [],
                "summary": "暂无可用于评估过热转弱的全市场样本。",
            }

        risk_items = [item for item in items if str((item.get("risk_flag") or {}).get("level") or "") in {"medium", "high"}]
        high_risk_items = [item for item in items if str((item.get("risk_flag") or {}).get("level") or "") == "high"]
        reversal_risk_items = [item for item in items if bool((item.get("risk_flag") or {}).get("reversal_risk"))]
        isolated_spike_items = [item for item in items if bool((item.get("risk_flag") or {}).get("isolated_spike"))]
        trend_start_items = [item for item in items if str(item.get("signal_type") or "") == "trend_start"]
        b1_pass_items = [item for item in items if item.get("b1_passed") is True]
        weak_confirmation_items = [
            item
            for item in items
            if str(item.get("signal_type") or "") != "trend_start" or item.get("b1_passed") is not True
        ]
        low_score_items = [
            item
            for item in items
            if self._safe_float(item.get("total_score")) is not None and self._safe_float(item.get("total_score")) < 4.0
        ]

        risk_ratio = self._ratio(len(risk_items), total_count)
        high_risk_ratio = self._ratio(len(high_risk_items), total_count)
        reversal_risk_ratio = self._ratio(len(reversal_risk_items), total_count)
        isolated_spike_ratio = self._ratio(len(isolated_spike_items), total_count)
        trend_start_ratio = self._ratio(len(trend_start_items), total_count)
        b1_pass_ratio = self._ratio(len(b1_pass_items), total_count)
        weak_confirmation_ratio = self._ratio(len(weak_confirmation_items), total_count)
        low_score_ratio = self._ratio(len(low_score_items), total_count)

        risk_scores = [
            self._safe_float((item.get("risk_flag") or {}).get("score"))
            for item in risk_items
            if self._safe_float((item.get("risk_flag") or {}).get("score")) is not None
        ]
        avg_risk_score = self._avg([float(value) for value in risk_scores if value is not None]) or 0.0

        heat_score = min(
            100.0,
            (risk_ratio or 0.0) * 45.0
            + (high_risk_ratio or 0.0) * 25.0
            + (reversal_risk_ratio or 0.0) * 20.0
            + min(avg_risk_score, 100.0) * 0.10,
        )
        failure_score = min(
            100.0,
            (weak_confirmation_ratio or 0.0) * 50.0
            + (1.0 - (trend_start_ratio or 0.0)) * 25.0
            + (1.0 - (b1_pass_ratio or 0.0)) * 15.0
            + (low_score_ratio or 0.0) * 10.0,
        )
        breadth_score = min(
            100.0,
            (isolated_spike_ratio or 0.0) * 55.0
            + (reversal_risk_ratio or 0.0) * 25.0
            + (high_risk_ratio or 0.0) * 20.0,
        )

        previous_risk_ratio = None
        previous_trend_start_ratio = None
        previous_b1_pass_ratio = None
        if previous_items:
            previous_total = len(previous_items)
            if previous_total > 0:
                previous_risk_ratio = self._ratio(
                    sum(
                        1
                        for item in previous_items
                        if str((item.get("risk_flag") or {}).get("level") or "") in {"medium", "high"}
                    ),
                    previous_total,
                )
                previous_trend_start_ratio = self._ratio(
                    sum(1 for item in previous_items if str(item.get("signal_type") or "") == "trend_start"),
                    previous_total,
                )
                previous_b1_pass_ratio = self._ratio(
                    sum(1 for item in previous_items if item.get("b1_passed") is True),
                    previous_total,
                )

        tags: list[str] = []
        reasons: list[str] = []
        trend_delta = None
        b1_delta = None
        risk_delta = None
        risk_trend = "flat"
        if previous_risk_ratio is not None and risk_ratio is not None:
            risk_delta = risk_ratio - previous_risk_ratio
            if risk_delta >= 0.15:
                risk_trend = "worsening"
                tags.append("风险扩散")
                reasons.append(
                    f"风险标的占比由 {self._pct_text(previous_risk_ratio)} 升至 {self._pct_text(risk_ratio)}"
                )
        if previous_trend_start_ratio is not None and trend_start_ratio is not None:
            trend_delta = trend_start_ratio - previous_trend_start_ratio
            if trend_delta <= -0.2:
                risk_trend = "worsening"
                tags.append("趋势确认下降")
                reasons.append(
                    f"趋势启动占比由 {self._pct_text(previous_trend_start_ratio)} 降至 {self._pct_text(trend_start_ratio)}"
                )
        if previous_b1_pass_ratio is not None and b1_pass_ratio is not None:
            b1_delta = b1_pass_ratio - previous_b1_pass_ratio
            if b1_delta <= -0.2:
                risk_trend = "worsening"
                tags.append("B1通过率下降")
                reasons.append(
                    f"B1 通过占比由 {self._pct_text(previous_b1_pass_ratio)} 降至 {self._pct_text(b1_pass_ratio)}"
                )

        if (risk_ratio or 0.0) >= 0.4:
            tags.append("风险标的占比高")
            reasons.append(f"风险标的占比达到 {self._pct_text(risk_ratio)}")
        if (reversal_risk_ratio or 0.0) >= 0.25:
            tags.append("高热反转增加")
            reasons.append(f"处于热度反转边缘的标的占比达到 {self._pct_text(reversal_risk_ratio)}")
        if (isolated_spike_ratio or 0.0) >= 0.25:
            tags.append("板块跟风不足")
            reasons.append(f"板块内孤立上涨占比达到 {self._pct_text(isolated_spike_ratio)}")
        if (trend_start_ratio or 0.0) <= 0.35:
            tags.append("接力确认偏弱")
            reasons.append(f"趋势启动占比仅 {self._pct_text(trend_start_ratio)}")
        if (b1_pass_ratio or 0.0) <= 0.4:
            tags.append("结构质量走弱")
            reasons.append(f"B1 通过占比仅 {self._pct_text(b1_pass_ratio)}")

        score = heat_score * 0.4 + failure_score * 0.35 + breadth_score * 0.25
        triggered = bool(
            score >= 58.0
            or (
                (risk_ratio or 0.0) >= 0.45
                and (trend_start_ratio or 0.0) <= 0.35
                and (isolated_spike_ratio or 0.0) >= 0.2
            )
        )
        if score >= 72.0:
            level = "high"
        elif score >= 48.0:
            level = "medium"
        else:
            level = "low"

        if triggered and "过热转弱预警" not in tags:
            tags.insert(0, "过热转弱预警")
        if triggered and not any("市场已进入" in reason for reason in reasons):
            reasons.insert(0, "当前热盘内部已出现高热聚集、接力变差、广度收缩的组合信号")

        if level == "high":
            summary = "全市场活跃样本已出现明显的高热聚集和接力走弱，需把它视为过热转调整的高警惕阶段。"
        elif level == "medium":
            summary = "全市场活跃样本存在一定过热转弱迹象，建议把追高节奏切慢，并重点盯接力是否继续恶化。"
        else:
            summary = "全市场活跃样本仍以局部风险为主，尚未形成明确的市场级过热转弱信号。"

        return {
            "level": level,
            "score": round(score, 2),
            "heat_score": round(heat_score, 2),
            "failure_score": round(failure_score, 2),
            "breadth_score": round(breadth_score, 2),
            "triggered": triggered,
            "risk_count": len(risk_items),
            "total_count": total_count,
            "risk_ratio": risk_ratio,
            "high_risk_count": len(high_risk_items),
            "reversal_risk_count": len(reversal_risk_items),
            "isolated_spike_ratio": isolated_spike_ratio,
            "b1_pass_ratio": b1_pass_ratio,
            "trend_start_ratio": trend_start_ratio,
            "failure_ratio": weak_confirmation_ratio,
            "risk_trend": risk_trend,
            "tags": tags,
            "reasons": reasons[:6],
            "summary": summary,
        }
