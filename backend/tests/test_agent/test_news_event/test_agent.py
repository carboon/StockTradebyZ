"""Tests for NewsEventAnalysisAgent."""
from __future__ import annotations

from app.agents.news_event.agent import NewsEventAnalysisAgent
from app.agents.news_event.schemas import (
    AgentStatus,
    AnalyzeDetailRequest,
    EventClassification,
    EventType,
    MarketScope,
)


def test_ready_result_falls_back_to_chain_stocks(monkeypatch):
    agent = NewsEventAnalysisAgent()
    request = AnalyzeDetailRequest(
        title="南京港新增美国休斯敦直航航线",
        summary="一艘满载国产设备及工程车辆的货轮从南京港码头启航。",
    )
    classification = EventClassification(
        event_type=EventType.DOMESTIC_INDUSTRY,
        market_scope=MarketScope.DOMESTIC,
        analyzable=True,
        mapping_required=True,
        reason="",
    )
    chain_data = [{
        "sector": "港口航运",
        "nodes": ["南京港", "国际航线"],
        "a_share_mapping": [{
            "code": "002040.SZ",
            "name": "南京港",
            "relation": "新闻直接相关港口",
            "strength": "strong",
            "reason": "新闻直接提及南京港新增国际航线",
        }],
    }]

    monkeypatch.setattr(agent, "_llm_final_analysis", lambda **kwargs: {
        "confidence": 0.7,
        "event_summary": request.title,
        "core_facts": [request.summary],
        "impact_path": [],
        "direct_sectors": [],
        "related_stocks": [],
    })

    result = agent._build_ready_result(
        task_id="test_task",
        request=request,
        classification=classification,
        evidence=[],
        entities=[],
        realization=[],
        chain_data=chain_data,
        rounds=[],
    )

    assert result.status == AgentStatus.READY
    assert result.direct_sectors == ["港口航运"]
    assert result.related_stocks
    assert result.related_stocks[0].code == "002040.SZ"
