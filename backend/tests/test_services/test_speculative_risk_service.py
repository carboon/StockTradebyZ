import json

import pytest

from app.models import Config
from app.services.speculative_risk_service import SpeculativeRiskService


@pytest.mark.service
def test_speculative_risk_service_marks_high_risk_for_isolated_hot_spike(test_db) -> None:
    risk = SpeculativeRiskService(test_db).evaluate(
        code="600001",
        name="题材股份",
        industry="房地产开发",
        sector_names=["存储芯片", "算力"],
        change_pct=9.8,
        turnover_rate=18.2,
        volume_ratio=3.4,
        active_pool_rank=12,
        b1_passed=False,
        verdict="WATCH",
        total_score=3.8,
        signal_type="rebound",
        recent_limit_up_days=2,
        recent_runup_pct=24.5,
        sector_breadth=0.33,
        sector_avg_change_pct=1.4,
        isolated_spike=True,
        sector_focus_name="存储芯片",
    )

    assert risk["level"] == "high"
    assert risk["isolated_spike"] is True
    assert risk["reversal_risk"] is True
    assert "板块内孤立拉升" in risk["tags"]
    assert any("近 5 日出现 2 次近似涨停" in reason for reason in risk["reasons"])


@pytest.mark.service
def test_speculative_risk_service_stays_low_when_heat_and_confirmation_are_aligned(test_db) -> None:
    risk = SpeculativeRiskService(test_db).evaluate(
        code="600002",
        name="趋势龙头",
        industry="通信设备",
        sector_names=["通信设备"],
        change_pct=4.5,
        turnover_rate=8.6,
        volume_ratio=1.4,
        active_pool_rank=28,
        b1_passed=True,
        verdict="PASS",
        total_score=5.1,
        signal_type="trend_start",
        recent_limit_up_days=0,
        recent_runup_pct=8.2,
        sector_breadth=0.78,
        sector_avg_change_pct=3.9,
        isolated_spike=False,
    )

    assert risk["level"] == "low"
    assert risk["reversal_risk"] is False
    assert "技术确认不足" not in risk["tags"]


@pytest.mark.service
def test_speculative_risk_service_matches_manual_narrative_catalog(test_db) -> None:
    test_db.add(
        Config(
            key=SpeculativeRiskService.CONFIG_KEY,
            value=json.dumps(
                {
                    "themes": [
                        {
                            "name": "事件映射",
                            "related_names": ["川大智胜"],
                            "keywords": ["特朗普"],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        )
    )
    test_db.commit()

    risk = SpeculativeRiskService(test_db).evaluate(
        code="002253",
        name="川大智胜",
        active_pool_rank=18,
        change_pct=6.2,
        turnover_rate=14.0,
        volume_ratio=2.1,
        verdict="WATCH",
        total_score=4.0,
        signal_type="rebound",
    )

    assert "事件映射" in risk["matched_themes"]
    assert "手工叙事命中" in risk["tags"]
    assert risk["narrative_score"] >= 18.0
