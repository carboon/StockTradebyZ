from datetime import date

from fastapi.testclient import TestClient

from app.services.hot_news_aggregator_service import HotNewsAggregatorService


def test_get_hot_topics_returns_keywords(test_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.closing_analysis_service.ClosingAnalysisService._build_sector_flow",
        lambda self, trade_date: {"inflow_top3": [{"sector_name": "半导体", "net_mf_amount": 1000}], "outflow_top3": []},
    )

    def fake_get_market_hot_topics(self, *, trade_date, window_days=3, limit=12, sector_flow=None):
        assert trade_date == date(2026, 5, 26)
        assert window_days == 3
        assert sector_flow["inflow_top3"][0]["sector_name"] == "半导体"
        return {
            "source": "local_fallback",
            "window_days": 3,
            "start_date": "2026-05-23",
            "end_date": "2026-05-26",
            "keywords": [
                {
                    "keyword": "半导体",
                    "category": "industry",
                    "heat": 90,
                    "reason": "资金流和新闻共振",
                    "related_sectors": ["半导体"],
                    "related_companies": ["长鑫存储"],
                    "evidence": [{"title": "半导体存储芯片走强", "source": "yicai"}],
                }
            ],
            "summary": "半导体热度较高",
            "confidence": None,
            "evidence": [{"title": "半导体存储芯片走强", "source": "yicai"}],
        }

    monkeypatch.setattr(HotNewsAggregatorService, "get_market_hot_topics", fake_get_market_hot_topics)

    response = test_client.get("/api/v1/analysis/hot-topics?trade_date=2026-05-26&window_days=3")

    assert response.status_code == 200
    data = response.json()
    assert data["keywords"][0]["keyword"] == "半导体"
    assert data["keywords"][0]["related_companies"] == ["长鑫存储"]
    assert data["evidence"][0]["title"] == "半导体存储芯片走强"


def test_get_hot_topics_rejects_bad_date(test_client: TestClient) -> None:
    response = test_client.get("/api/v1/analysis/hot-topics?trade_date=20260526")

    assert response.status_code == 400
