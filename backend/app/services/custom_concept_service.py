"""Custom concept AI tagging service."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Config,
    ConceptMemoryEntry,
    CustomConcept,
    CustomConceptAlias,
    CustomConceptRelatedSector,
    CustomConceptRun,
    CustomConceptStockTag,
    Stock,
    StockDaily,
)
from app.services.deepseek_service import DeepSeekService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now


class CustomConceptService:
    """管理自定义概念与 AI 批量标签。"""

    PROMPT_VERSION = "v1"
    MAX_MATCHED_OFFICIAL_CONCEPTS = 12
    MAX_CANDIDATES = 240
    CHUNK_SIZE = 60
    VALID_CHAIN_POSITIONS = {"upstream", "midstream", "downstream", "application", "unknown"}
    DATA_FRESHNESS_TZ = ZoneInfo("Asia/Shanghai")

    def __init__(self, db: Session):
        self.db = db
        self.tushare_service = TushareService()
        self.deepseek_service = DeepSeekService(api_key=self._load_deepseek_api_key())

    def _load_deepseek_api_key(self) -> str:
        value = self.db.query(Config.value).filter(Config.key == "deepseek_api_key").scalar()
        return str(value or "").strip()

    @staticmethod
    def _normalize_text(value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        return "".join(ch for ch in text if not ch.isspace() and ch not in "-_/")

    @staticmethod
    def _normalize_name(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return " ".join(text.split())

    @staticmethod
    def _normalize_code(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if "." in text:
            text = text.split(".", 1)[0]
        return text.zfill(6)

    @staticmethod
    def _unique_strings(values: Iterable[Any]) -> list[str]:
        seen: set[str] = set()
        items: list[str] = []
        for value in values:
            text = " ".join(str(value or "").strip().split())
            if not text or text in seen:
                continue
            seen.add(text)
            items.append(text)
        return items

    @staticmethod
    def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
        return [items[index:index + size] for index in range(0, len(items), size)]

    @staticmethod
    def _clamp_score(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        if score < 0:
            return 0.0
        if score > 100:
            return 100.0
        return round(score, 2)

    def _get_concept(self, concept_id: int) -> CustomConcept:
        concept = self.db.query(CustomConcept).filter(CustomConcept.id == concept_id).first()
        if concept is None:
            raise LookupError("概念不存在")
        return concept

    def _find_concept_by_query(self, query: str) -> Optional[CustomConcept]:
        normalized_query = self._normalize_text(query)
        if not normalized_query:
            return None

        concepts = self.db.query(CustomConcept).all()
        for concept in concepts:
            if (
                self._normalize_text(concept.name) == normalized_query
                or self._normalize_text(concept.display_name) == normalized_query
            ):
                return concept

        alias_rows = self.db.query(CustomConceptAlias).all()
        concept_by_id = {concept.id: concept for concept in concepts}
        for alias in alias_rows:
            if self._normalize_text(alias.alias) == normalized_query:
                return concept_by_id.get(alias.concept_id)
        return None

    def _aliases_map(self, concept_ids: list[int]) -> dict[int, list[str]]:
        if not concept_ids:
            return {}
        rows = (
            self.db.query(CustomConceptAlias.concept_id, CustomConceptAlias.alias)
            .filter(CustomConceptAlias.concept_id.in_(concept_ids))
            .order_by(CustomConceptAlias.id.asc())
            .all()
        )
        result: dict[int, list[str]] = {concept_id: [] for concept_id in concept_ids}
        for concept_id, alias in rows:
            result.setdefault(int(concept_id), []).append(str(alias))
        return result

    def _related_sector_map(self, concept_ids: list[int]) -> dict[int, list[str]]:
        if not concept_ids:
            return {}
        rows = (
            self.db.query(CustomConceptRelatedSector.concept_id, CustomConceptRelatedSector.sector_name)
            .filter(CustomConceptRelatedSector.concept_id.in_(concept_ids))
            .order_by(CustomConceptRelatedSector.id.asc())
            .all()
        )
        result: dict[int, list[str]] = {concept_id: [] for concept_id in concept_ids}
        for concept_id, sector_name in rows:
            result.setdefault(int(concept_id), []).append(str(sector_name))
        return result

    def _tag_count_map(self, concept_ids: list[int]) -> dict[int, int]:
        if not concept_ids:
            return {}
        rows = (
            self.db.query(CustomConceptStockTag.concept_id, func.count(CustomConceptStockTag.id))
            .filter(CustomConceptStockTag.concept_id.in_(concept_ids))
            .group_by(CustomConceptStockTag.concept_id)
            .all()
        )
        return {int(concept_id): int(count or 0) for concept_id, count in rows}

    def _latest_run_map(self, concept_ids: list[int]) -> dict[int, CustomConceptRun]:
        if not concept_ids:
            return {}
        rows = (
            self.db.query(CustomConceptRun)
            .filter(CustomConceptRun.concept_id.in_(concept_ids))
            .order_by(CustomConceptRun.concept_id.asc(), CustomConceptRun.created_at.desc(), CustomConceptRun.id.desc())
            .all()
        )
        latest: dict[int, CustomConceptRun] = {}
        for row in rows:
            if row.concept_id not in latest:
                latest[row.concept_id] = row
        return latest

    def _serialize_run(self, run: CustomConceptRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "status": run.status,
            "provider": run.provider,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "candidate_count": int(run.candidate_count or 0),
            "matched_stock_count": int(run.matched_stock_count or 0),
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_message": run.error_message,
        }

    def _serialize_concept(
        self,
        concept: CustomConcept,
        *,
        aliases: list[str],
        related_sectors: list[str],
        tag_count: int,
        latest_run: Optional[CustomConceptRun],
        recent_runs: Optional[list[CustomConceptRun]] = None,
    ) -> dict[str, Any]:
        payload = {
            "id": concept.id,
            "name": concept.name,
            "display_name": concept.display_name,
            "description": concept.description,
            "chain_hint": concept.chain_hint,
            "status": concept.status,
            "prompt_version": concept.prompt_version,
            "aliases": aliases,
            "related_sectors": related_sectors,
            "tag_count": tag_count,
            "last_refreshed_at": concept.last_refreshed_at,
            "updated_at": concept.updated_at,
            "latest_run": self._serialize_run(latest_run) if latest_run is not None else None,
        }
        if recent_runs is not None:
            payload["recent_runs"] = [self._serialize_run(run) for run in recent_runs]
        return payload

    def list_concepts(self) -> dict[str, Any]:
        concepts = (
            self.db.query(CustomConcept)
            .order_by(CustomConcept.updated_at.desc(), CustomConcept.id.desc())
            .all()
        )
        concept_ids = [concept.id for concept in concepts]
        aliases_map = self._aliases_map(concept_ids)
        sectors_map = self._related_sector_map(concept_ids)
        tag_counts = self._tag_count_map(concept_ids)
        latest_runs = self._latest_run_map(concept_ids)
        return {
            "concepts": [
                self._serialize_concept(
                    concept,
                    aliases=aliases_map.get(concept.id, []),
                    related_sectors=sectors_map.get(concept.id, []),
                    tag_count=tag_counts.get(concept.id, 0),
                    latest_run=latest_runs.get(concept.id),
                )
                for concept in concepts
            ],
            "total": len(concepts),
        }

    def get_concept_detail(self, concept_id: int) -> dict[str, Any]:
        concept = self._get_concept(concept_id)
        aliases = self._aliases_map([concept_id]).get(concept_id, [])
        related_sectors = self._related_sector_map([concept_id]).get(concept_id, [])
        tag_count = self._tag_count_map([concept_id]).get(concept_id, 0)
        recent_runs = (
            self.db.query(CustomConceptRun)
            .filter(CustomConceptRun.concept_id == concept_id)
            .order_by(CustomConceptRun.created_at.desc(), CustomConceptRun.id.desc())
            .limit(10)
            .all()
        )
        latest_run = recent_runs[0] if recent_runs else None
        return self._serialize_concept(
            concept,
            aliases=aliases,
            related_sectors=related_sectors,
            tag_count=tag_count,
            latest_run=latest_run,
            recent_runs=recent_runs,
        )

    def upsert_concept(
        self,
        *,
        payload: dict[str, Any],
        concept_id: Optional[int] = None,
    ) -> dict[str, Any]:
        name = self._normalize_name(payload.get("name"))
        display_name = self._normalize_name(payload.get("display_name") or name)
        status = self._normalize_name(payload.get("status") or "draft").lower() or "draft"
        if not name:
            raise ValueError("概念名称不能为空")
        if not display_name:
            raise ValueError("概念展示名称不能为空")

        aliases = self._unique_strings(payload.get("aliases") or [])
        related_sectors = self._unique_strings(payload.get("related_sectors") or [])

        query = self.db.query(CustomConcept).filter(CustomConcept.name == name)
        if concept_id is not None:
            query = query.filter(CustomConcept.id != concept_id)
        if query.first() is not None:
            raise ValueError("概念名称已存在")

        concept = self._get_concept(concept_id) if concept_id is not None else CustomConcept()
        if concept_id is None:
            self.db.add(concept)

        concept.name = name
        concept.display_name = display_name
        concept.description = self._normalize_name(payload.get("description")) or None
        concept.chain_hint = self._normalize_name(payload.get("chain_hint")) or None
        concept.status = status
        concept.prompt_version = self.PROMPT_VERSION
        concept.source_config_json = {
            "aliases": aliases,
            "related_sectors": related_sectors,
        }
        self.db.flush()

        self.db.query(CustomConceptAlias).filter(CustomConceptAlias.concept_id == concept.id).delete()
        self.db.query(CustomConceptRelatedSector).filter(CustomConceptRelatedSector.concept_id == concept.id).delete()
        for alias in aliases:
            self.db.add(CustomConceptAlias(concept_id=concept.id, alias=alias))
        for sector_name in related_sectors:
            self.db.add(
                CustomConceptRelatedSector(
                    concept_id=concept.id,
                    sector_name=sector_name,
                    sector_source="tushare_concept",
                )
            )

        self.db.commit()
        return self.get_concept_detail(concept.id)

    def delete_concept(self, concept_id: int) -> dict[str, Any]:
        concept = self._get_concept(concept_id)
        self.db.query(CustomConceptStockTag).filter(CustomConceptStockTag.concept_id == concept.id).delete()
        self.db.query(CustomConceptAlias).filter(CustomConceptAlias.concept_id == concept.id).delete()
        self.db.query(CustomConceptRelatedSector).filter(CustomConceptRelatedSector.concept_id == concept.id).delete()
        self.db.query(CustomConceptRun).filter(CustomConceptRun.concept_id == concept.id).delete()
        self.db.delete(concept)
        self.db.commit()
        return {"deleted": True, "concept_id": concept_id}

    def _concept_terms(self, concept: CustomConcept, aliases: list[str], related_sectors: list[str]) -> list[str]:
        return self._unique_strings(
            [
                concept.name,
                concept.display_name,
                concept.description,
                concept.chain_hint,
                *aliases,
                *related_sectors,
            ]
        )

    def _match_official_concepts(
        self,
        concept: CustomConcept,
        *,
        aliases: list[str],
        related_sectors: list[str],
    ) -> list[dict[str, Any]]:
        official_concepts = self.tushare_service.get_concept_list()
        if not official_concepts:
            return []

        terms = self._concept_terms(concept, aliases, related_sectors)
        normalized_terms = [
            (term, self._normalize_text(term))
            for term in terms
            if self._normalize_text(term)
        ]
        matches: list[dict[str, Any]] = []
        for item in official_concepts:
            concept_name = self._normalize_name(item.get("concept_name"))
            normalized_name = self._normalize_text(concept_name)
            if not normalized_name:
                continue
            score = 0
            matched_terms: list[str] = []
            for term, normalized_term in normalized_terms:
                if len(normalized_term) < 2:
                    continue
                if normalized_name == normalized_term:
                    score = max(score, 100)
                    matched_terms.append(term)
                    continue
                if normalized_term in normalized_name:
                    score = max(score, 80)
                    matched_terms.append(term)
                    continue
                if normalized_name in normalized_term:
                    score = max(score, 65)
                    matched_terms.append(term)
            if score <= 0:
                continue
            matches.append(
                {
                    "concept_code": str(item.get("concept_code") or ""),
                    "concept_name": concept_name,
                    "score": score,
                    "matched_terms": self._unique_strings(matched_terms),
                }
            )

        matches.sort(key=lambda item: (-int(item["score"]), item["concept_name"]))
        deduped: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for item in matches:
            concept_code = str(item["concept_code"])
            if not concept_code or concept_code in seen_codes:
                continue
            seen_codes.add(concept_code)
            deduped.append(item)
            if len(deduped) >= self.MAX_MATCHED_OFFICIAL_CONCEPTS:
                break
        return deduped

    def _build_candidate_snapshot(self, official_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: dict[str, dict[str, Any]] = {}
        for item in official_matches:
            concept_code = str(item.get("concept_code") or "")
            concept_name = self._normalize_name(item.get("concept_name"))
            if not concept_code:
                continue
            members = self.tushare_service.get_stock_concept_members(concept_code)
            for member in members:
                code = self._normalize_code(member.get("ts_code"))
                if not code:
                    continue
                entry = candidates.setdefault(
                    code,
                    {
                        "code": code,
                        "stock_name": self._normalize_name(member.get("name")) or None,
                        "industry": None,
                        "matched_source_concepts": [],
                        "matched_source_codes": [],
                    },
                )
                if concept_name and concept_name not in entry["matched_source_concepts"]:
                    entry["matched_source_concepts"].append(concept_name)
                if concept_code and concept_code not in entry["matched_source_codes"]:
                    entry["matched_source_codes"].append(concept_code)

        if not candidates:
            return []

        stock_rows = (
            self.db.query(Stock.code, Stock.name, Stock.industry)
            .filter(Stock.code.in_(list(candidates.keys())))
            .all()
        )
        stock_map = {
            self._normalize_code(code): {
                "stock_name": self._normalize_name(name) or None,
                "industry": self._normalize_name(industry) or None,
            }
            for code, name, industry in stock_rows
        }

        items: list[dict[str, Any]] = []
        for code, entry in candidates.items():
            stock_meta = stock_map.get(code, {})
            if stock_meta.get("stock_name"):
                entry["stock_name"] = stock_meta["stock_name"]
            entry["industry"] = stock_meta.get("industry")
            entry["matched_source_concepts"] = self._unique_strings(entry["matched_source_concepts"])
            items.append(entry)

        items.sort(
            key=lambda item: (
                -len(item.get("matched_source_concepts") or []),
                str(item.get("industry") or ""),
                str(item.get("code") or ""),
            )
        )
        return items[: self.MAX_CANDIDATES]

    def _build_chunk_prompt(
        self,
        concept: CustomConcept,
        *,
        aliases: list[str],
        related_sectors: list[str],
        official_matches: list[dict[str, Any]],
        chunk: list[dict[str, Any]],
    ) -> tuple[str, str]:
        system_prompt = (
            "你是A股产业链与概念归因助手。"
            "你只能基于提供的候选股票与上下文判断某股票是否属于该自定义概念。"
            "如果证据不足，matched 必须返回 false。"
            "必须返回 JSON object，不能输出 markdown 或额外解释。"
        )
        user_payload = {
            "concept": {
                "name": concept.name,
                "display_name": concept.display_name,
                "description": concept.description,
                "chain_hint": concept.chain_hint,
                "aliases": aliases,
                "related_sectors": related_sectors,
                "official_matches": official_matches,
            },
            "candidates": chunk,
        }
        user_prompt = (
            "请基于下面的概念定义和候选股票，判断每只股票是否属于该概念，并尽量区分上下游与角色标签。\n"
            "固定输出字段：\n"
            "{"
            "\"concept_summary\":\"string\","
            "\"industry_chain_definition\":\"string\","
            "\"stocks\":["
            "{"
            "\"code\":\"6位股票代码\","
            "\"matched\":true,"
            "\"relevance_score\":0-100,"
            "\"confidence\":0-100,"
            "\"chain_position\":\"upstream|midstream|downstream|application|unknown\","
            "\"role_tags\":[\"string\"],"
            "\"reason\":\"string\""
            "}"
            "]"
            "}\n"
            "要求：\n"
            "1. 只允许返回候选列表中的股票代码。\n"
            "2. 没把握时 matched=false。\n"
            "3. role_tags 可包含材料、设备、制造、应用、龙头、弹性、配套等角色词。\n"
            "4. relevance_score 表示和该概念的相关强度，不是涨跌评分。\n"
            f"上下文如下：\n{json.dumps(user_payload, ensure_ascii=False)}"
        )
        return system_prompt, user_prompt

    def _build_ad_hoc_chunk_prompt(
        self,
        *,
        query: str,
        concept: CustomConcept,
        chunk: list[dict[str, Any]],
    ) -> tuple[str, str]:
        system_prompt = (
            "你是A股概念归因助手。"
            "你需要在给定候选股票中，判断哪些股票与用户输入的概念最相关。"
            "必须返回 JSON object，不能输出 markdown。"
        )
        user_payload = {
            "query": query,
            "concept_hint": {
                "name": concept.name,
                "display_name": concept.display_name,
                "description": concept.description,
                "chain_hint": concept.chain_hint,
            },
            "candidates": chunk,
        }
        user_prompt = (
            "请只在下面提供的候选股票中做概念相关性判断，并按用户输入概念给出匹配结果。\n"
            "你必须返回一个 JSON object，且只能返回 JSON，不允许 markdown、解释、前后缀文本。\n"
            "输出结构必须严格等于：\n"
            "{\n"
            "  \"concept_summary\": \"string\",\n"
            "  \"industry_chain_definition\": \"string\",\n"
            "  \"stocks\": [\n"
            "    {\n"
            "      \"code\": \"6位股票代码\",\n"
            "      \"matched\": true,\n"
            "      \"relevance_score\": 0,\n"
            "      \"confidence\": 0,\n"
            "      \"chain_position\": \"upstream|midstream|downstream|application|unknown\",\n"
            "      \"role_tags\": [\"string\"],\n"
            "      \"reason\": \"string\"\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "要求：\n"
            "1. 只能返回候选池内股票。\n"
            "2. 候选池中的每一只股票都必须返回一条结果，不能遗漏，也不能重复。\n"
            "3. 若仅弱相关或看不出关系，matched=false。\n"
            "4. relevance_score 用于给候选股票做相关性排序，范围 0-100。\n"
            "5. confidence 表示判断把握度，范围 0-100。\n"
            "6. role_tags 必须是字符串数组；没有明确角色时返回空数组。\n"
            "7. 可结合股票名称、行业、板块、提示性注释判断。\n"
            f"上下文如下：\n{json.dumps(user_payload, ensure_ascii=False)}"
        )
        return system_prompt, user_prompt

    def _validate_ai_result(
        self,
        payload: dict[str, Any],
        *,
        allowed_codes: set[str],
        require_full_coverage: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("AI 返回格式错误")
        raw_stocks = payload.get("stocks")
        if not isinstance(raw_stocks, list):
            raise ValueError("AI 返回缺少 stocks 列表")

        normalized_stocks: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for raw_item in raw_stocks:
            if not isinstance(raw_item, dict):
                raise ValueError("AI stocks 项格式错误")
            code = self._normalize_code(raw_item.get("code"))
            if not code or code not in allowed_codes:
                raise ValueError(f"AI 返回了候选池外股票: {raw_item.get('code')}")
            if code in seen_codes:
                raise ValueError(f"AI 返回了重复股票: {code}")
            seen_codes.add(code)

            matched = bool(raw_item.get("matched"))
            chain_position = str(raw_item.get("chain_position") or "unknown").strip().lower()
            if chain_position not in self.VALID_CHAIN_POSITIONS:
                chain_position = "unknown"

            normalized_stocks.append(
                {
                    "code": code,
                    "matched": matched,
                    "relevance_score": self._clamp_score(raw_item.get("relevance_score")),
                    "confidence": self._clamp_score(raw_item.get("confidence")),
                    "chain_position": chain_position,
                    "role_tags": self._unique_strings(raw_item.get("role_tags") or []),
                    "reason": self._normalize_name(raw_item.get("reason")),
                }
            )

        if require_full_coverage and seen_codes != allowed_codes:
            missing_codes = sorted(allowed_codes - seen_codes)
            extra_codes = sorted(seen_codes - allowed_codes)
            parts: list[str] = []
            if missing_codes:
                parts.append(f"缺少股票: {', '.join(missing_codes)}")
            if extra_codes:
                parts.append(f"多余股票: {', '.join(extra_codes)}")
            raise ValueError(f"AI 返回覆盖不完整: {'; '.join(parts)}")

        return {
            "concept_summary": self._normalize_name(payload.get("concept_summary")),
            "industry_chain_definition": self._normalize_name(payload.get("industry_chain_definition")),
            "stocks": normalized_stocks,
        }

    def _merge_ai_outputs(
        self,
        chunk_outputs: list[dict[str, Any]],
        candidate_snapshot: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        candidate_map = {item["code"]: item for item in candidate_snapshot}
        merged_tags: dict[str, dict[str, Any]] = {}
        concept_summary = ""
        industry_chain_definition = ""

        for payload in chunk_outputs:
            if not concept_summary and payload.get("concept_summary"):
                concept_summary = str(payload["concept_summary"])
            if not industry_chain_definition and payload.get("industry_chain_definition"):
                industry_chain_definition = str(payload["industry_chain_definition"])

            for item in payload.get("stocks") or []:
                if not item.get("matched"):
                    continue
                code = str(item["code"])
                base = candidate_map.get(code, {})
                existing = merged_tags.get(code)
                if existing is None or float(item.get("relevance_score") or 0.0) >= float(existing.get("relevance_score") or 0.0):
                    merged_tags[code] = {
                        **item,
                        "matched_source_concepts": list(base.get("matched_source_concepts") or []),
                        "stock_name": base.get("stock_name"),
                        "industry": base.get("industry"),
                    }
                else:
                    existing["role_tags"] = self._unique_strings([*(existing.get("role_tags") or []), *(item.get("role_tags") or [])])

        merged_list = sorted(
            merged_tags.values(),
            key=lambda item: (-float(item.get("relevance_score") or 0.0), str(item.get("code") or "")),
        )
        return (
            {
                "concept_summary": concept_summary or None,
                "industry_chain_definition": industry_chain_definition or None,
                "chunks": chunk_outputs,
            },
            merged_list,
        )

    def refresh_concept(self, concept_id: int) -> dict[str, Any]:
        concept = self._get_concept(concept_id)
        aliases = self._aliases_map([concept_id]).get(concept_id, [])
        related_sectors = self._related_sector_map([concept_id]).get(concept_id, [])
        if not self.deepseek_service.enabled:
            raise ValueError("DeepSeek API Key 未配置")

        official_matches = self._match_official_concepts(concept, aliases=aliases, related_sectors=related_sectors)
        candidate_snapshot = self._build_candidate_snapshot(official_matches)

        run = CustomConceptRun(
            concept_id=concept.id,
            status="running",
            provider="deepseek",
            model=self.deepseek_service.DEFAULT_MODEL,
            prompt_version=self.PROMPT_VERSION,
            candidate_count=len(candidate_snapshot),
            started_at=utc_now(),
            input_context_json={
                "official_matches": official_matches,
                "candidate_snapshot": candidate_snapshot,
            },
        )
        self.db.add(run)
        self.db.flush()
        self.db.commit()
        self.db.refresh(run)

        try:
            concept = self._get_concept(concept_id)
            if not candidate_snapshot:
                raise ValueError("未召回到候选股票，请补充别名或关联板块")

            chunk_outputs: list[dict[str, Any]] = []
            for chunk in self._chunked(candidate_snapshot, self.CHUNK_SIZE):
                system_prompt, user_prompt = self._build_chunk_prompt(
                    concept,
                    aliases=aliases,
                    related_sectors=related_sectors,
                    official_matches=official_matches,
                    chunk=chunk,
                )
                payload = self.deepseek_service.infer_json(system_prompt=system_prompt, user_prompt=user_prompt)
                validated = self._validate_ai_result(
                    payload,
                    allowed_codes={item["code"] for item in chunk},
                    require_full_coverage=True,
                )
                chunk_outputs.append(validated)

            aggregated_result, merged_tags = self._merge_ai_outputs(chunk_outputs, candidate_snapshot)

            self.db.query(CustomConceptStockTag).filter(CustomConceptStockTag.concept_id == concept.id).delete()
            for item in merged_tags:
                self.db.add(
                    CustomConceptStockTag(
                        concept_id=concept.id,
                        run_id=run.id,
                        stock_code=item["code"],
                        relevance_score=item.get("relevance_score"),
                        confidence=item.get("confidence"),
                        chain_position=item.get("chain_position") or "unknown",
                        role_tags_json=item.get("role_tags") or [],
                        reason=item.get("reason"),
                        evidence_json={
                            "matched_source_concepts": item.get("matched_source_concepts") or [],
                            "stock_name": item.get("stock_name"),
                            "industry": item.get("industry"),
                        },
                        source="ai",
                        is_manual=False,
                    )
                )

            run.status = "completed"
            run.matched_stock_count = len(merged_tags)
            run.result_json = aggregated_result
            run.finished_at = utc_now()

            concept.status = "ready"
            concept.last_refreshed_at = run.finished_at
            concept.prompt_version = self.PROMPT_VERSION

            self.db.commit()
            return {
                "concept_id": concept.id,
                "concept_name": concept.display_name,
                "run": self._serialize_run(run),
                "official_matches": official_matches,
                "stocks_saved": len(merged_tags),
                "concept_summary": aggregated_result.get("concept_summary"),
                "industry_chain_definition": aggregated_result.get("industry_chain_definition"),
            }
        except Exception as exc:
            self.db.rollback()
            failed_run = self.db.query(CustomConceptRun).filter(CustomConceptRun.id == run.id).first()
            failed_concept = self._get_concept(concept_id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.error_message = str(exc)
                failed_run.finished_at = utc_now()
            failed_concept.status = "error"
            self.db.commit()
            raise

    def get_concept_stocks(
        self,
        concept_id: int,
        *,
        chain_position: Optional[str] = None,
        role_tag: Optional[str] = None,
        min_relevance: Optional[float] = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        concept = self._get_concept(concept_id)
        query = (
            self.db.query(
                CustomConceptStockTag,
                Stock.name,
                Stock.industry,
            )
            .join(Stock, Stock.code == CustomConceptStockTag.stock_code)
            .filter(CustomConceptStockTag.concept_id == concept_id)
        )

        normalized_chain = str(chain_position or "").strip().lower()
        if normalized_chain:
            query = query.filter(CustomConceptStockTag.chain_position == normalized_chain)
        if min_relevance is not None:
            query = query.filter(CustomConceptStockTag.relevance_score >= float(min_relevance))

        rows = query.order_by(
            func.coalesce(CustomConceptStockTag.relevance_score, -1.0).desc(),
            CustomConceptStockTag.updated_at.desc(),
            CustomConceptStockTag.stock_code.asc(),
        ).limit(max(1, min(int(limit or 500), 2000))).all()

        normalized_role_tag = self._normalize_text(role_tag)
        stocks: list[dict[str, Any]] = []
        for tag, stock_name, industry in rows:
            role_tags = self._unique_strings(tag.role_tags_json or [])
            if normalized_role_tag and normalized_role_tag not in {self._normalize_text(item) for item in role_tags}:
                continue
            evidence = tag.evidence_json if isinstance(tag.evidence_json, dict) else {}
            stocks.append(
                {
                    "stock_code": tag.stock_code,
                    "stock_name": self._normalize_name(stock_name),
                    "industry": self._normalize_name(industry),
                    "relevance_score": tag.relevance_score,
                    "confidence": tag.confidence,
                    "chain_position": tag.chain_position,
                    "role_tags": role_tags,
                    "reason": tag.reason,
                    "matched_source_concepts": self._unique_strings(evidence.get("matched_source_concepts") or []),
                    "updated_at": tag.updated_at,
                }
            )

        return {
            "concept_id": concept.id,
            "concept_name": concept.display_name,
            "stocks": stocks,
            "total": len(stocks),
        }

    def get_stock_concepts(self, code: str) -> dict[str, Any]:
        normalized_code = self._normalize_code(code)
        if not normalized_code:
            raise ValueError("股票代码不能为空")

        rows = (
            self.db.query(
                CustomConceptStockTag,
                CustomConcept.id,
                CustomConcept.display_name,
                CustomConcept.name,
            )
            .join(CustomConcept, CustomConcept.id == CustomConceptStockTag.concept_id)
            .filter(CustomConceptStockTag.stock_code == normalized_code)
            .order_by(
                func.coalesce(CustomConceptStockTag.relevance_score, -1.0).desc(),
                CustomConceptStockTag.updated_at.desc(),
            )
            .all()
        )
        concepts: list[dict[str, Any]] = []
        for tag, concept_id, display_name, name in rows:
            concepts.append(
                {
                    "concept_id": int(concept_id),
                    "concept_name": str(display_name),
                    "concept_display_name": str(display_name),
                    "relevance_score": tag.relevance_score,
                    "confidence": tag.confidence,
                    "chain_position": tag.chain_position,
                    "role_tags": self._unique_strings(tag.role_tags_json or []),
                    "reason": tag.reason,
                    "updated_at": tag.updated_at,
                }
            )
        return {
            "code": normalized_code,
            "concepts": concepts,
            "total": len(concepts),
        }

    def _ensure_concept_for_query(self, query: str) -> CustomConcept:
        concept = self._find_concept_by_query(query)
        if concept is not None:
            return concept

        normalized_name = self._normalize_name(query)
        concept = CustomConcept(
            name=normalized_name,
            display_name=normalized_name,
            description=None,
            chain_hint=None,
            status="draft",
            prompt_version=self.PROMPT_VERSION,
            source_config_json={"source": "candidate_match"},
        )
        self.db.add(concept)
        self.db.commit()
        self.db.refresh(concept)
        return concept

    def suggest_queries(self, keyword: str = "", *, limit: int = 10) -> dict[str, Any]:
        normalized_keyword = self._normalize_text(keyword)
        max_items = max(1, min(int(limit or 10), 30))
        candidates: list[dict[str, Any]] = []

        def add_item(query: str, label: str, source: str, updated_at: Any = None) -> None:
            text = self._normalize_name(query)
            if not text:
                return
            normalized_text = self._normalize_text(text)
            normalized_label = self._normalize_text(label)
            if normalized_keyword and normalized_keyword not in normalized_text and normalized_keyword not in normalized_label:
                return
            score = 0
            if normalized_keyword:
                if normalized_text == normalized_keyword:
                    score += 100
                elif normalized_text.startswith(normalized_keyword):
                    score += 80
                elif normalized_keyword in normalized_text:
                    score += 60
                elif normalized_keyword in normalized_label:
                    score += 40
            score += 10 if source == "custom_concept" else 0
            candidates.append({
                "query": text,
                "label": self._normalize_name(label) or text,
                "source": source,
                "updated_at": updated_at,
                "_score": score,
            })

        for concept in self.db.query(CustomConcept).order_by(CustomConcept.updated_at.desc(), CustomConcept.id.desc()).limit(1000).all():
            add_item(concept.name, concept.display_name or concept.name, "custom_concept", concept.updated_at)
            if concept.display_name and concept.display_name != concept.name:
                add_item(concept.display_name, concept.display_name, "custom_concept", concept.updated_at)

        for alias in self.db.query(CustomConceptAlias).order_by(CustomConceptAlias.created_at.desc(), CustomConceptAlias.id.desc()).limit(1000).all():
            add_item(alias.alias, alias.alias, "alias", alias.created_at)

        for entry in self.db.query(ConceptMemoryEntry).order_by(ConceptMemoryEntry.updated_at.desc(), ConceptMemoryEntry.id.desc()).limit(1000).all():
            add_item(entry.keyword, entry.title or entry.keyword, "memory", entry.updated_at)

        deduped: dict[str, dict[str, Any]] = {}
        for item in candidates:
            key = self._normalize_text(item["query"])
            existing = deduped.get(key)
            if existing is None or item["_score"] > existing["_score"]:
                deduped[key] = item

        items = sorted(
            deduped.values(),
            key=lambda item: (
                -int(item.get("_score") or 0),
                -(item["updated_at"].timestamp() if item.get("updated_at") and hasattr(item.get("updated_at"), "timestamp") else 0),
                item["query"],
            ),
        )[:max_items]
        for item in items:
            item.pop("_score", None)
        return {"items": items, "total": len(items)}

    def _build_candidate_items_from_request(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for raw_item in candidates:
            code = self._normalize_code(raw_item.get("code"))
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            items.append(
                {
                    "code": code,
                    "stock_name": self._normalize_name(raw_item.get("name")) or None,
                    "industry": self._normalize_name(raw_item.get("industry")) or None,
                    "sector_names": self._unique_strings(raw_item.get("sector_names") or []),
                    "signal_type": self._normalize_name(raw_item.get("signal_type")) or None,
                    "total_score": raw_item.get("total_score"),
                    "comment": self._normalize_name(raw_item.get("comment")) or None,
                }
            )
        return items

    def _get_cached_candidate_matches(self, concept_id: int, candidate_codes: set[str]) -> list[dict[str, Any]]:
        rows = (
            self.db.query(CustomConceptStockTag, Stock.name, Stock.industry)
            .join(Stock, Stock.code == CustomConceptStockTag.stock_code)
            .filter(
                CustomConceptStockTag.concept_id == concept_id,
                CustomConceptStockTag.stock_code.in_(list(candidate_codes)),
            )
            .order_by(
                func.coalesce(CustomConceptStockTag.relevance_score, -1.0).desc(),
                CustomConceptStockTag.updated_at.desc(),
            )
            .all()
        )
        matches: list[dict[str, Any]] = []
        for tag, stock_name, industry in rows:
            matches.append(
                {
                    "code": tag.stock_code,
                    "name": self._normalize_name(stock_name) or None,
                    "industry": self._normalize_name(industry) or None,
                    "relevance_score": tag.relevance_score,
                    "confidence": tag.confidence,
                    "chain_position": tag.chain_position,
                    "role_tags": self._unique_strings(tag.role_tags_json or []),
                    "reason": tag.reason,
                }
            )
        return matches

    def _is_current_market_data(self, value: Optional[datetime]) -> bool:
        if value is None:
            return False
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value_date = value.astimezone(self.DATA_FRESHNESS_TZ).date()
        latest_trade_date = self.db.query(func.max(StockDaily.trade_date)).scalar()
        if latest_trade_date is None:
            return value_date == utc_now().astimezone(self.DATA_FRESHNESS_TZ).date()
        return value_date >= latest_trade_date

    def match_candidates(
        self,
        *,
        query: str,
        candidates: list[dict[str, Any]],
        force_refresh: bool = False,
        async_refresh: bool = False,
    ) -> dict[str, Any]:
        normalized_query = self._normalize_name(query)
        if not normalized_query:
            raise ValueError("过滤关键词不能为空")

        candidate_items = self._build_candidate_items_from_request(candidates)
        if not candidate_items:
            raise ValueError("候选股票不能为空")

        concept = self._find_concept_by_query(normalized_query)
        concept_existed = concept is not None
        if concept is None:
            concept = self._ensure_concept_for_query(normalized_query)
        candidate_codes = {item["code"] for item in candidate_items}
        cached_matches = self._get_cached_candidate_matches(concept.id, candidate_codes)
        if async_refresh and not force_refresh:
            return {
                "query": normalized_query,
                "concept_id": concept.id,
                "concept_name": concept.display_name,
                "cache_hit": bool(cached_matches),
                "source": "async_refresh",
                "data_updated_at": concept.last_refreshed_at,
                "refresh_scheduled": True,
                "total_candidates": len(candidate_items),
                "matched_count": len(cached_matches),
                "matches": cached_matches,
            }
        if not force_refresh:
            cache_available = bool(cached_matches) or (
                concept_existed and (concept.last_refreshed_at is not None or concept.status == "ready")
            )
            cache_is_current_market_data = self._is_current_market_data(concept.last_refreshed_at)
            if cache_available and cache_is_current_market_data:
                return {
                    "query": normalized_query,
                    "concept_id": concept.id,
                    "concept_name": concept.display_name,
                    "cache_hit": True,
                    "source": "cache",
                    "data_updated_at": concept.last_refreshed_at,
                    "refresh_scheduled": False,
                    "total_candidates": len(candidate_items),
                    "matched_count": len(cached_matches),
                    "matches": cached_matches,
                }
            if cache_available:
                return {
                    "query": normalized_query,
                    "concept_id": concept.id,
                    "concept_name": concept.display_name,
                    "cache_hit": True,
                    "source": "stale_cache",
                    "data_updated_at": concept.last_refreshed_at,
                    "refresh_scheduled": True,
                    "total_candidates": len(candidate_items),
                    "matched_count": len(cached_matches),
                    "matches": cached_matches,
                }

        if not self.deepseek_service.enabled:
            raise ValueError("DeepSeek API Key 未配置")

        run = CustomConceptRun(
            concept_id=concept.id,
            status="running",
            provider="deepseek",
            model=self.deepseek_service.DEFAULT_MODEL,
            prompt_version=self.PROMPT_VERSION,
            candidate_count=len(candidate_items),
            started_at=utc_now(),
            input_context_json={
                "query": normalized_query,
                "candidate_snapshot": candidate_items,
                "source": "candidate_match",
            },
        )
        self.db.add(run)
        self.db.flush()
        self.db.commit()
        self.db.refresh(run)

        try:
            chunk_outputs: list[dict[str, Any]] = []
            for chunk in self._chunked(candidate_items, self.CHUNK_SIZE):
                system_prompt, user_prompt = self._build_ad_hoc_chunk_prompt(
                    query=normalized_query,
                    concept=concept,
                    chunk=chunk,
                )
                payload = self.deepseek_service.infer_json(system_prompt=system_prompt, user_prompt=user_prompt)
                validated = self._validate_ai_result(payload, allowed_codes={item["code"] for item in chunk})
                chunk_outputs.append(validated)

            aggregated_result, merged_tags = self._merge_ai_outputs(chunk_outputs, candidate_items)

            self.db.query(CustomConceptStockTag).filter(
                CustomConceptStockTag.concept_id == concept.id,
                CustomConceptStockTag.stock_code.in_(list(candidate_codes)),
            ).delete(synchronize_session=False)
            for item in merged_tags:
                self.db.add(
                    CustomConceptStockTag(
                        concept_id=concept.id,
                        run_id=run.id,
                        stock_code=item["code"],
                        relevance_score=item.get("relevance_score"),
                        confidence=item.get("confidence"),
                        chain_position=item.get("chain_position") or "unknown",
                        role_tags_json=item.get("role_tags") or [],
                        reason=item.get("reason"),
                        evidence_json={
                            "matched_source_concepts": item.get("matched_source_concepts") or [],
                            "stock_name": item.get("stock_name"),
                            "industry": item.get("industry"),
                            "source": "candidate_match",
                        },
                        source="ai",
                        is_manual=False,
                    )
                )

            run.status = "completed"
            run.matched_stock_count = len(merged_tags)
            run.result_json = aggregated_result
            run.finished_at = utc_now()
            concept.status = "ready"
            concept.last_refreshed_at = run.finished_at
            concept.prompt_version = self.PROMPT_VERSION
            self.db.commit()

            return {
                "query": normalized_query,
                "concept_id": concept.id,
                "concept_name": concept.display_name,
                "cache_hit": False,
                "source": "ai",
                "data_updated_at": concept.last_refreshed_at,
                "refresh_scheduled": False,
                "total_candidates": len(candidate_items),
                "matched_count": len(merged_tags),
                "matches": [
                    {
                        "code": item["code"],
                        "name": item.get("stock_name"),
                        "industry": item.get("industry"),
                        "relevance_score": item.get("relevance_score"),
                        "confidence": item.get("confidence"),
                        "chain_position": item.get("chain_position") or "unknown",
                        "role_tags": item.get("role_tags") or [],
                        "reason": item.get("reason"),
                    }
                    for item in merged_tags
                ],
            }
        except Exception as exc:
            self.db.rollback()
            failed_run = self.db.query(CustomConceptRun).filter(CustomConceptRun.id == run.id).first()
            failed_concept = self._get_concept(concept.id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.error_message = str(exc)
                failed_run.finished_at = utc_now()
            failed_concept.status = "error"
            self.db.commit()
            raise
