from unittest.mock import PropertyMock, patch
from datetime import timedelta

from fastapi.testclient import TestClient

from app.models import CustomConcept, CustomConceptStockTag, Stock
from app.time_utils import utc_now


def _create_concept(test_client: TestClient) -> dict:
    response = test_client.post(
        "/api/v1/custom-concepts/",
        json={
            "name": "PCB",
            "display_name": "PCB",
            "description": "印制电路板产业链",
            "chain_hint": "重点识别覆铜板、PCB 制造、下游应用",
            "aliases": ["印制电路板", "FPC"],
            "related_sectors": ["印制电路板"],
            "status": "draft",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_create_and_list_custom_concepts(test_client: TestClient) -> None:
    created = _create_concept(test_client)
    assert created["name"] == "PCB"
    assert created["aliases"] == ["印制电路板", "FPC"]
    assert created["related_sectors"] == ["印制电路板"]
    assert created["tag_count"] == 0

    response = test_client.get("/api/v1/custom-concepts/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["concepts"][0]["display_name"] == "PCB"
    assert payload["concepts"][0]["updated_at"]


def test_delete_custom_concept_removes_related_rows(test_client_with_db) -> None:
    db = test_client_with_db.db
    db.add(Stock(code="000001", name="覆铜股份", market="SZ", industry="电子"))
    db.commit()

    created = _create_concept(test_client_with_db)
    concept_id = created["id"]
    db.add(
        CustomConceptStockTag(
            concept_id=concept_id,
            stock_code="000001",
            relevance_score=90,
            confidence=80,
            chain_position="upstream",
            role_tags_json=["材料"],
            source="ai",
            is_manual=False,
        )
    )
    db.commit()

    response = test_client_with_db.delete(f"/api/v1/custom-concepts/{concept_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True

    assert db.query(CustomConcept).filter(CustomConcept.id == concept_id).first() is None
    assert db.query(CustomConceptStockTag).filter(CustomConceptStockTag.concept_id == concept_id).count() == 0


def test_refresh_custom_concept_and_query_tags(test_client_with_db) -> None:
    db = test_client_with_db.db
    db.add_all(
        [
            Stock(code="000001", name="覆铜股份", market="SZ", industry="电子"),
            Stock(code="000002", name="应用科技", market="SZ", industry="消费电子"),
        ]
    )
    db.commit()

    created = _create_concept(test_client_with_db)
    concept_id = created["id"]

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
            {"ts_code": "000001.SZ", "name": "覆铜股份", "in_date": "20200101", "out_date": None},
            {"ts_code": "000002.SZ", "name": "应用科技", "in_date": "20200101", "out_date": None},
        ]
    }
    ai_result = {
        "concept_summary": "PCB 概念以上游材料和制造环节为主。",
        "industry_chain_definition": "上游材料，中游 PCB 制造，下游消费电子与服务器应用。",
        "stocks": [
            {
                "code": "000001",
                "matched": True,
                "relevance_score": 92,
                "confidence": 88,
                "chain_position": "upstream",
                "role_tags": ["材料", "核心"],
                "reason": "主营更接近覆铜板材料，是 PCB 产业链上游。",
            },
            {
                "code": "000002",
                "matched": False,
                "relevance_score": 18,
                "confidence": 44,
                "chain_position": "application",
                "role_tags": ["应用"],
                "reason": "只有终端应用属性，和 PCB 概念直接关联较弱。",
            },
        ],
    }

    with (
        patch("app.services.tushare_service.TushareService.get_concept_list", return_value=concept_list),
        patch(
            "app.services.tushare_service.TushareService.get_stock_concept_members",
            side_effect=lambda concept_code: concept_members.get(concept_code, []),
        ),
        patch("app.services.deepseek_service.DeepSeekService.enabled", new_callable=PropertyMock, return_value=True),
        patch("app.services.deepseek_service.DeepSeekService.infer_json", return_value=ai_result),
    ):
        response = test_client_with_db.post(f"/api/v1/custom-concepts/{concept_id}/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stocks_saved"] == 1
    assert payload["run"]["status"] == "completed"
    assert payload["official_matches"][0]["concept_name"] == "印制电路板"

    db.expire_all()
    saved_tags = db.query(CustomConceptStockTag).filter(CustomConceptStockTag.concept_id == concept_id).all()
    assert len(saved_tags) == 1
    assert saved_tags[0].stock_code == "000001"
    assert saved_tags[0].chain_position == "upstream"

    stocks_response = test_client_with_db.get(f"/api/v1/custom-concepts/{concept_id}/stocks")
    assert stocks_response.status_code == 200
    stocks_payload = stocks_response.json()
    assert stocks_payload["total"] == 1
    assert stocks_payload["stocks"][0]["stock_code"] == "000001"
    assert stocks_payload["stocks"][0]["matched_source_concepts"] == ["印制电路板"]

    by_stock_response = test_client_with_db.get("/api/v1/custom-concepts/by-stock/1")
    assert by_stock_response.status_code == 200
    by_stock_payload = by_stock_response.json()
    assert by_stock_payload["code"] == "000001"
    assert by_stock_payload["total"] == 1
    assert by_stock_payload["concepts"][0]["concept_name"] == "PCB"


def test_match_candidates_uses_cache_then_ai(test_client_with_db) -> None:
    db = test_client_with_db.db
    db.add_all(
        [
            Stock(code="000010", name="光模股份", market="SZ", industry="通信"),
            Stock(code="000011", name="终端应用", market="SZ", industry="电子"),
        ]
    )
    db.commit()

    ai_result = {
        "concept_summary": "光模块概念以中游模组制造为主。",
        "industry_chain_definition": "上游光芯片，中游光模块，下游算力与交换机应用。",
        "stocks": [
            {
                "code": "000010",
                "matched": True,
                "relevance_score": 95,
                "confidence": 90,
                "chain_position": "midstream",
                "role_tags": ["模组", "核心"],
                "reason": "主营与光模块直接相关。",
            },
            {
                "code": "000011",
                "matched": False,
                "relevance_score": 20,
                "confidence": 35,
                "chain_position": "application",
                "role_tags": ["应用"],
                "reason": "只属于弱相关应用端。",
            },
        ],
    }

    payload = {
        "query": "光模块",
        "candidates": [
            {
                "code": "000010",
                "name": "光模股份",
                "industry": "通信",
                "sector_names": ["CPO"],
                "signal_type": "trend_start",
                "total_score": 4.7,
                "comment": "模组弹性",
            },
            {
                "code": "000011",
                "name": "终端应用",
                "industry": "电子",
                "sector_names": ["消费电子"],
                "signal_type": "watch",
                "total_score": 3.8,
                "comment": "应用端",
            },
        ],
    }

    with (
        patch("app.services.deepseek_service.DeepSeekService.enabled", new_callable=PropertyMock, return_value=True),
        patch("app.services.deepseek_service.DeepSeekService.infer_json", return_value=ai_result) as infer_mock,
    ):
        first = test_client_with_db.post("/api/v1/custom-concepts/match-candidates", json=payload)
        assert first.status_code == 200
        first_payload = first.json()
        assert first_payload["source"] == "ai"
        assert first_payload["matched_count"] == 1
        assert first_payload["matches"][0]["code"] == "000010"
        assert infer_mock.call_count == 1

        second = test_client_with_db.post("/api/v1/custom-concepts/match-candidates", json=payload)
        assert second.status_code == 200
        second_payload = second.json()
        assert second_payload["cache_hit"] is True
        assert second_payload["source"] == "cache"
        assert second_payload["refresh_scheduled"] is False
        assert second_payload["matched_count"] == 1
        assert infer_mock.call_count == 1


def test_match_candidates_returns_stale_cache_and_schedules_refresh(test_client_with_db) -> None:
    db = test_client_with_db.db
    db.add(Stock(code="000010", name="光模股份", market="SZ", industry="通信"))
    db.commit()

    created = _create_concept(test_client_with_db)
    concept_id = created["id"]
    concept = db.query(CustomConcept).filter(CustomConcept.id == concept_id).first()
    assert concept is not None
    concept.name = "光模块"
    concept.display_name = "光模块"
    concept.status = "ready"
    concept.last_refreshed_at = utc_now() - timedelta(days=1)
    db.add(
        CustomConceptStockTag(
            concept_id=concept_id,
            stock_code="000010",
            relevance_score=90,
            confidence=80,
            chain_position="midstream",
            role_tags_json=["模组"],
            reason="旧缓存",
            source="ai",
            is_manual=False,
        )
    )
    db.commit()

    payload = {
        "query": "光模块",
        "candidates": [
            {
                "code": "000010",
                "name": "光模股份",
                "industry": "通信",
                "sector_names": ["CPO"],
                "signal_type": "trend_start",
                "total_score": 4.7,
                "comment": "模组弹性",
            }
        ],
    }

    with patch("app.api.custom_concepts._refresh_candidate_matches_background") as refresh_mock:
        response = test_client_with_db.post("/api/v1/custom-concepts/match-candidates", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["cache_hit"] is True
    assert body["source"] == "stale_cache"
    assert body["refresh_scheduled"] is True
    assert body["matched_count"] == 1
    assert refresh_mock.call_count == 1
