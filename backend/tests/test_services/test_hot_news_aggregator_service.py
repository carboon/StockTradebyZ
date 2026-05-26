from datetime import date

from app.config import settings
from app.services.hot_news_aggregator_service import HotNewsAggregatorService


class FakeTushareService:
    def get_news_items(self, **kwargs):
        return [
            {"datetime": "2026-05-26 10:00:00", "title": "半导体存储芯片走强 长鑫存储产业链受关注", "content": "", "src": "yicai"},
            {"datetime": "2026-05-26 11:00:00", "title": "PCB和AI算力方向持续活跃", "content": "", "src": "yicai"},
        ]


class DisabledDeepSeekService:
    enabled = False


class EnabledDeepSeekService:
    enabled = True

    def infer_json(self, **kwargs):
        return {
            "keywords": [
                {
                    "keyword": "半导体",
                    "category": "industry",
                    "heat": 92,
                    "reason": "新闻提到存储芯片和产业链活跃",
                    "related_sectors": ["半导体"],
                    "related_companies": ["长鑫存储"],
                    "evidence": ["半导体存储芯片走强 长鑫存储产业链受关注"],
                }
            ],
            "summary": "半导体和AI算力方向热度较高",
            "confidence": 82,
        }


def test_hot_topics_fallback_uses_news_and_sector_flow(db_session, monkeypatch) -> None:
    service = HotNewsAggregatorService(
        db_session,
        tushare_service=FakeTushareService(),
        deepseek_service=DisabledDeepSeekService(),
    )
    monkeypatch.setattr(service, "_fetch_public_finance_news", lambda limit: [])

    payload = service.get_market_hot_topics(
        trade_date=date(2026, 5, 26),
        sector_flow={"inflow_top3": [{"sector_name": "半导体", "net_mf_amount": 120000}], "outflow_top3": []},
    )

    keywords = {item["keyword"] for item in payload["keywords"]}
    assert payload["source"] == "local_fallback"
    assert "半导体" in keywords
    assert "PCB" in keywords
    assert payload["evidence"]


def test_hot_topics_ai_uses_evidence_and_keeps_keyword_evidence(db_session, monkeypatch) -> None:
    service = HotNewsAggregatorService(
        db_session,
        tushare_service=FakeTushareService(),
        deepseek_service=EnabledDeepSeekService(),
    )
    monkeypatch.setattr(service, "_fetch_public_finance_news", lambda limit: [])

    payload = service.get_market_hot_topics(
        trade_date=date(2026, 5, 26),
        sector_flow={"inflow_top3": [{"sector_name": "半导体", "net_mf_amount": 120000}], "outflow_top3": []},
    )

    assert payload["source"] == "deepseek"
    assert payload["keywords"][0]["keyword"] == "半导体"
    assert payload["keywords"][0]["related_companies"] == ["长鑫存储"]
    assert payload["keywords"][0]["evidence"]


def test_tavily_search_provider_maps_results(db_session, monkeypatch) -> None:
    service = HotNewsAggregatorService(
        db_session,
        tushare_service=FakeTushareService(),
        deepseek_service=DisabledDeepSeekService(),
    )
    monkeypatch.setattr(settings, "tavily_api_key", "tvly-test")
    monkeypatch.setattr(settings, "hot_news_search_provider", "tavily")
    monkeypatch.setattr(settings, "hot_news_search_enabled", True)
    monkeypatch.setattr(settings, "hot_news_search_max_results", 2)
    service.tavily_api_key = "tvly-test"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {
                        "title": "A股PCB概念持续活跃",
                        "url": "https://example.com/pcb",
                        "content": "AI服务器带动PCB需求。",
                        "published_date": "2026-05-26",
                    }
                ]
            }

    monkeypatch.setattr("app.services.hot_news_aggregator_service.requests.post", lambda *args, **kwargs: FakeResponse())

    items = service._search_tavily_news(
        query="A股 PCB 热点",
        start_date=date(2026, 5, 23),
        end_date=date(2026, 5, 26),
    )

    assert items[0]["title"] == "A股PCB概念持续活跃"
    assert items[0]["source_key"] == "tavily"
    assert items[0]["query"] == "A股 PCB 热点"


def test_bocha_search_provider_extracts_results(db_session, monkeypatch) -> None:
    service = HotNewsAggregatorService(
        db_session,
        tushare_service=FakeTushareService(),
        deepseek_service=DisabledDeepSeekService(),
    )
    monkeypatch.setattr(settings, "bocha_api_key", "bocha-test")
    monkeypatch.setattr(settings, "hot_news_search_provider", "bocha")
    monkeypatch.setattr(settings, "hot_news_search_enabled", True)
    monkeypatch.setattr(settings, "hot_news_search_max_results", 2)
    service.bocha_api_key = "bocha-test"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "webPages": {
                        "value": [
                            {
                                "title": "A股半导体和PCB方向走强",
                                "url": "https://example.com/hot",
                                "summary": "存储芯片、PCB、自主可控受到资金关注。",
                                "siteName": "博查新闻",
                                "datePublished": "2026-05-26",
                            }
                        ]
                    }
                }
            }

    monkeypatch.setattr("app.services.hot_news_aggregator_service.requests.post", lambda *args, **kwargs: FakeResponse())

    items = service._search_bocha_news(query="A股 半导体 PCB 热点")

    assert items[0]["title"] == "A股半导体和PCB方向走强"
    assert items[0]["source_key"] == "bocha"
    assert items[0]["query"] == "A股 半导体 PCB 热点"


def test_ai360_search_provider_extracts_nested_results(db_session, monkeypatch) -> None:
    service = HotNewsAggregatorService(
        db_session,
        tushare_service=FakeTushareService(),
        deepseek_service=DisabledDeepSeekService(),
    )
    monkeypatch.setattr(settings, "ai360_api_key", "360-test")
    monkeypatch.setattr(settings, "hot_news_search_provider", "ai360")
    monkeypatch.setattr(settings, "hot_news_search_enabled", True)
    service.ai360_api_key = "360-test"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "list": [
                        {
                            "title": "半导体产业链热度提升",
                            "summary_ai": "存储芯片、自主可控方向受到关注。",
                            "url": "https://example.com/chip",
                            "site": "360新闻",
                        }
                    ]
                }
            }

    monkeypatch.setattr("app.services.hot_news_aggregator_service.requests.get", lambda *args, **kwargs: FakeResponse())

    items = service._search_ai360_news(query="A股 半导体 热点")

    assert items[0]["title"] == "半导体产业链热度提升"
    assert items[0]["content"] == "存储芯片、自主可控方向受到关注。"
    assert items[0]["source_key"] == "ai360"
