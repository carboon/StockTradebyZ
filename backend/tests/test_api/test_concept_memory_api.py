from unittest.mock import PropertyMock, patch

from fastapi.testclient import TestClient

from app.models import ConceptMemoryEntry


def _create_entry(test_client: TestClient, **overrides) -> dict:
    payload = {
        "keyword": "PCB",
        "title": "PCB 产业链基础知识",
        "content": "PCB 主要包括上游材料、中游制造和下游应用。",
        "category": "industry",
        "source_type": "manual",
        "source_name": "人工整理",
        "source_url": "https://example.com",
        "status": "ready",
        "priority": 10,
        "is_fixed": True,
        "tags": ["印制电路板", "FPC"],
        "related_stock_codes": ["000001"],
    }
    payload.update(overrides)
    response = test_client.post("/api/v1/concept-memory/", json=payload)
    assert response.status_code == 200
    return response.json()


def test_create_list_and_refresh_concept_memory(test_client_with_db) -> None:
    created = _create_entry(test_client_with_db)
    assert created["keyword"] == "PCB"
    assert created["is_fixed"] is True
    assert created["tags"] == ["印制电路板", "FPC"]

    list_response = test_client_with_db.get("/api/v1/concept-memory/")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 1
    assert list_payload["stats"]["fixed_count"] == 1

    concept_list = [
        {
            "concept_code": "TS0001",
            "concept_name": "印制电路板",
            "concept_type": "N",
            "start_date": "20200101",
        }
    ]
    concept_members = {
        "TS0001": [
            {"ts_code": "000001.SZ", "name": "样例股份", "in_date": "20200101", "out_date": None},
        ]
    }
    news_items = [
        {
            "datetime": "202405010930",
            "title": "PCB 需求回暖",
            "content": "第一财经报道 PCB 产业链景气度改善。",
            "src": "yicai",
        }
    ]
    ai_result = {
        "summary": "PCB 是印制电路板产业链主题，核心围绕材料与制造。",
        "keywords": ["印制电路板", "FPC", "HDI"],
        "related_stock_codes": ["000001"],
        "reason": "本地固定知识与新闻都支持该主题。",
        "importance_score": 88,
        "content_suggestion": "PCB 是印制电路板产业链主题，核心围绕材料与制造。",
        "extra_notes": ["建议后续补充龙头与上下游映射。"],
    }

    with (
        patch("app.services.tushare_service.TushareService.get_concept_list", return_value=concept_list),
        patch(
            "app.services.tushare_service.TushareService.get_stock_concept_members",
            side_effect=lambda concept_code: concept_members.get(concept_code, []),
        ),
        patch(
            "app.services.tushare_service.TushareService.get_news_items",
            return_value=news_items,
        ),
        patch("app.services.deepseek_service.DeepSeekService.enabled", new_callable=PropertyMock, return_value=True),
        patch("app.services.deepseek_service.DeepSeekService.infer_json", return_value=ai_result) as infer_mock,
    ):
        compose_first = test_client_with_db.post(
            "/api/v1/concept-memory/compose",
            json={"query": "PCB", "use_ai": True, "force_refresh": False, "max_entries": 5, "max_news": 5},
        )
        assert compose_first.status_code == 200
        compose_first_payload = compose_first.json()
        assert compose_first_payload["source"] == "ai"
        assert compose_first_payload["matched_entries"][0]["keyword"] == "PCB"
        assert compose_first_payload["ai_result"]["summary"] == "PCB 是印制电路板产业链主题，核心围绕材料与制造。"
        assert infer_mock.call_count == 1

        compose_second = test_client_with_db.post(
            "/api/v1/concept-memory/compose",
            json={"query": "PCB", "use_ai": True, "force_refresh": False, "max_entries": 5, "max_news": 5},
        )
        assert compose_second.status_code == 200
        compose_second_payload = compose_second.json()
        assert compose_second_payload["source"] == "cache"
        assert compose_second_payload["cache_hit"] is True
        assert infer_mock.call_count == 1

        refresh_response = test_client_with_db.post(f"/api/v1/concept-memory/{created['id']}/refresh")
        assert refresh_response.status_code == 200
        refresh_payload = refresh_response.json()
        assert refresh_payload["ai_summary"] == "PCB 是印制电路板产业链主题，核心围绕材料与制造。"
        assert refresh_payload["matched_news_count"] == 1
        assert refresh_payload["matched_official_concepts"][0]["concept_name"] == "印制电路板"

    test_client_with_db.db.expire_all()
    saved_entry = test_client_with_db.db.query(ConceptMemoryEntry).filter(ConceptMemoryEntry.id == created["id"]).first()
    assert saved_entry is not None
    assert saved_entry.status == "ready"
    assert saved_entry.summary == "PCB 是印制电路板产业链主题，核心围绕材料与制造。"
