"""Concept memory library service."""
from __future__ import annotations

import json
import hashlib
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.cache import cache
from app.models import Config, ConceptMemoryEntry, ConceptMemoryRun, Stock
from app.services.deepseek_service import DeepSeekService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now


class ConceptMemoryService:
    """概念记忆库的条目管理、上下文组装与 AI 汇聚。"""

    PROMPT_VERSION = "v1"
    DEFAULT_MAX_ENTRIES = 8
    DEFAULT_MAX_NEWS = 10
    COMPOSE_CACHE_TTL = 300

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
        for token in (" ", "\t", "\n", "_", "-", "/", "，", ",", "、", ";", "；"):
            text = text.replace(token, "")
        return text

    @staticmethod
    def _normalize_name(value: Any) -> str:
        text = str(value or "").strip()
        return " ".join(text.split())

    @staticmethod
    def _normalize_content(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _unique_strings(values: Any) -> list[str]:
        seen: set[str] = set()
        items: list[str] = []
        if not isinstance(values, list):
            return items
        for value in values:
            text = " ".join(str(value or "").strip().split())
            if not text or text in seen:
                continue
            seen.add(text)
            items.append(text)
        return items

    @staticmethod
    def _normalize_codes(values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        seen: set[str] = set()
        items: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            if "." in text:
                text = text.split(".", 1)[0]
            code = text.zfill(6)
            if code in seen:
                continue
            seen.add(code)
            items.append(code)
        return items

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): ConceptMemoryService._json_safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [ConceptMemoryService._json_safe(item) for item in value]
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:
                return str(value)
        return value

    def _get_entry(self, entry_id: int) -> ConceptMemoryEntry:
        entry = self.db.query(ConceptMemoryEntry).filter(ConceptMemoryEntry.id == entry_id).first()
        if entry is None:
            raise LookupError("概念记忆条目不存在")
        return entry

    def _serialize_entry(self, entry: ConceptMemoryEntry, *, recent_runs: Optional[list[ConceptMemoryRun]] = None) -> dict[str, Any]:
        payload = {
            "id": entry.id,
            "keyword": entry.keyword,
            "title": entry.title,
            "content": entry.content,
            "category": entry.category,
            "source_type": entry.source_type,
            "source_name": entry.source_name,
            "source_url": entry.source_url,
            "status": entry.status,
            "priority": int(entry.priority or 0),
            "is_fixed": bool(entry.is_fixed),
            "tags": self._unique_strings(entry.tags_json or []),
            "related_stock_codes": self._normalize_codes(entry.related_stock_codes_json or []),
            "summary": entry.summary,
            "evidence": entry.evidence_json if isinstance(entry.evidence_json, dict) else None,
            "prompt_version": entry.prompt_version,
            "last_refreshed_at": entry.last_refreshed_at,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
        }
        if recent_runs is not None:
            payload["recent_runs"] = [self._serialize_run(run) for run in recent_runs]
        return payload

    @staticmethod
    def _serialize_run(run: ConceptMemoryRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "entry_id": run.entry_id,
            "run_type": run.run_type,
            "query_text": run.query_text,
            "status": run.status,
            "provider": run.provider,
            "model": run.model,
            "prompt_version": run.prompt_version,
            "matched_entry_count": int(run.matched_entry_count or 0),
            "matched_news_count": int(run.matched_news_count or 0),
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_message": run.error_message,
        }

    def list_entries(
        self,
        *,
        keyword: Optional[str] = None,
        source_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        query = self.db.query(ConceptMemoryEntry)
        if source_type:
            query = query.filter(ConceptMemoryEntry.source_type == source_type)
        if status:
            query = query.filter(ConceptMemoryEntry.status == status)
        entries = query.order_by(
            ConceptMemoryEntry.is_fixed.desc(),
            ConceptMemoryEntry.priority.desc(),
            ConceptMemoryEntry.updated_at.desc(),
            ConceptMemoryEntry.id.desc(),
        ).all()

        normalized_keyword = self._normalize_text(keyword) if keyword else ""
        filtered: list[ConceptMemoryEntry] = []
        for entry in entries:
            if normalized_keyword:
                haystack = self._normalize_text(
                    " ".join([
                        entry.keyword or "",
                        entry.title or "",
                        entry.content or "",
                        " ".join(self._unique_strings(entry.tags_json or [])),
                    ])
                )
                if normalized_keyword not in haystack:
                    continue
            filtered.append(entry)
        filtered = filtered[: max(1, min(int(limit or 500), 2000))]

        stats = {
            "total": len(entries),
            "filtered": len(filtered),
            "fixed_count": sum(1 for entry in entries if entry.is_fixed),
            "manual_count": sum(1 for entry in entries if entry.source_type == "manual"),
            "website_count": sum(1 for entry in entries if entry.source_type == "website"),
            "ai_count": sum(1 for entry in entries if entry.source_type == "ai"),
            "ready_count": sum(1 for entry in entries if entry.status == "ready"),
        }
        return {
            "entries": [self._serialize_entry(entry) for entry in filtered],
            "total": len(filtered),
            "stats": stats,
        }

    def get_detail(self, entry_id: int) -> dict[str, Any]:
        entry = self._get_entry(entry_id)
        recent_runs = (
            self.db.query(ConceptMemoryRun)
            .filter(ConceptMemoryRun.entry_id == entry_id)
            .order_by(ConceptMemoryRun.created_at.desc(), ConceptMemoryRun.id.desc())
            .limit(10)
            .all()
        )
        return self._serialize_entry(entry, recent_runs=recent_runs)

    def upsert_entry(self, payload: dict[str, Any], entry_id: Optional[int] = None) -> dict[str, Any]:
        keyword = self._normalize_name(payload.get("keyword"))
        title = self._normalize_name(payload.get("title"))
        content = self._normalize_content(payload.get("content"))
        if not keyword:
            raise ValueError("主题关键字不能为空")
        if not title:
            raise ValueError("标题不能为空")
        if not content:
            raise ValueError("内容不能为空")

        status = self._normalize_name(payload.get("status") or "draft").lower() or "draft"
        source_type = self._normalize_name(payload.get("source_type") or "manual").lower() or "manual"
        if source_type not in {"manual", "website", "ai", "static"}:
            raise ValueError("source_type 仅支持 manual/website/ai/static")

        entry = self._get_entry(entry_id) if entry_id is not None else ConceptMemoryEntry()
        if entry_id is None:
            self.db.add(entry)

        entry.keyword = keyword
        entry.title = title
        entry.content = content
        entry.category = self._normalize_name(payload.get("category")) or None
        entry.source_type = source_type
        entry.source_name = self._normalize_name(payload.get("source_name")) or None
        entry.source_url = self._normalize_name(payload.get("source_url")) or None
        entry.status = status
        entry.priority = int(payload.get("priority") or 0)
        entry.is_fixed = bool(payload.get("is_fixed"))
        entry.tags_json = self._unique_strings(payload.get("tags") or [])
        entry.related_stock_codes_json = self._normalize_codes(payload.get("related_stock_codes") or [])
        entry.prompt_version = self.PROMPT_VERSION
        self.db.commit()
        return self.get_detail(entry.id)

    def _score_entry(self, entry: ConceptMemoryEntry, normalized_query: str) -> int:
        score = 0
        keyword = self._normalize_text(entry.keyword)
        title = self._normalize_text(entry.title)
        content = self._normalize_text(entry.content)
        tags = self._normalize_text(" ".join(self._unique_strings(entry.tags_json or [])))

        if normalized_query == keyword:
            score += 100
        if normalized_query and normalized_query in keyword:
            score += 80
        if keyword and keyword in normalized_query:
            score += 70
        if normalized_query and normalized_query in title:
            score += 60
        if any(token for token in [normalized_query] if token and token in tags):
            score += 45
        if normalized_query and normalized_query in content:
            score += 30
        if entry.is_fixed:
            score += 20
        score += max(0, min(int(entry.priority or 0), 50))
        return score

    def _collect_entries_for_query(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        normalized_query = self._normalize_text(query)
        if not normalized_query:
            return []
        entries = self.db.query(ConceptMemoryEntry).filter(ConceptMemoryEntry.status != "error").all()
        scored: list[tuple[int, ConceptMemoryEntry]] = []
        for entry in entries:
            score = self._score_entry(entry, normalized_query)
            if score <= 0:
                continue
            scored.append((score, entry))

        scored.sort(
            key=lambda item: (
                -item[0],
                -int(item[1].is_fixed),
                -int(item[1].priority or 0),
                -(item[1].updated_at.timestamp() if item[1].updated_at else 0.0),
                -int(item[1].id or 0),
            )
        )
        selected = [item[1] for item in scored[: max(1, min(limit, 50))]]
        return [self._serialize_entry(entry) for entry in selected]

    def _collect_official_context(self, query: str | list[str]) -> list[dict[str, Any]]:
        terms = query if isinstance(query, list) else [query]
        normalized_terms = [self._normalize_text(item) for item in terms if self._normalize_text(item)]
        if not normalized_terms:
            return []

        matches: list[dict[str, Any]] = []
        for item in self.tushare_service.get_concept_list():
            concept_name = self._normalize_name(item.get("concept_name"))
            normalized_name = self._normalize_text(concept_name)
            if not normalized_name:
                continue
            if not any(
                term in normalized_name or normalized_name in term
                for term in normalized_terms
            ):
                continue
            members = self.tushare_service.get_stock_concept_members(str(item.get("concept_code") or ""))
            matches.append(
                {
                    "concept_code": str(item.get("concept_code") or ""),
                    "concept_name": concept_name,
                    "concept_type": self._normalize_name(item.get("concept_type")) or None,
                    "start_date": item.get("start_date"),
                    "members": members[:20],
                }
            )
            if len(matches) >= 8:
                break
        return matches

    def _collect_news_context(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        normalized_query = self._normalize_text(query)
        if not normalized_query:
            return []

        end_date = utc_now().date()
        start_date = end_date - timedelta(days=7)
        news_items = self.tushare_service.get_news_items(
            src="yicai",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            limit=max(limit * 3, 20),
        )
        matched: list[dict[str, Any]] = []
        for item in news_items:
            title = self._normalize_text(item.get("title"))
            content = self._normalize_text(item.get("content"))
            haystack = f"{title}{content}"
            if normalized_query not in haystack and haystack.find(normalized_query[: min(4, len(normalized_query))]) < 0:
                continue
            matched.append(
                {
                    "datetime": item.get("datetime"),
                    "title": self._normalize_name(item.get("title")),
                    "content": self._normalize_name(item.get("content")),
                    "src": item.get("src"),
                }
            )
            if len(matched) >= limit:
                break
        return matched

    def _compose_context_text(
        self,
        *,
        query: str,
        entries: list[dict[str, Any]],
        official_matches: list[dict[str, Any]],
        news_items: list[dict[str, Any]],
    ) -> str:
        blocks: list[str] = [f"主题: {query}"]
        if entries:
            blocks.append("本地记忆:")
            for item in entries:
                blocks.append(
                    f"- {item['keyword']} | {item['title']} | 来源:{item['source_type']} | 标签:{', '.join(item.get('tags') or []) or '-'}"
                )
                if item.get("summary"):
                    blocks.append(f"  摘要: {item['summary']}")
        if official_matches:
            blocks.append("官方数据源:")
            for item in official_matches:
                members = item.get("members") or []
                sample = " / ".join([str(member.get("name") or member.get("ts_code") or "") for member in members[:8] if member])
                blocks.append(
                    f"- {item['concept_name']} ({item.get('concept_code')}) | 成分样例: {sample or '-'}"
                )
        if news_items:
            blocks.append("近期新闻:")
            for item in news_items:
                blocks.append(f"- {item.get('title') or '-'} | {item.get('content') or '-'}")
        return "\n".join(blocks)

    def _build_refresh_prompt(
        self,
        *,
        entry: ConceptMemoryEntry,
        entries: list[dict[str, Any]],
        official_matches: list[dict[str, Any]],
        news_items: list[dict[str, Any]],
    ) -> tuple[str, str]:
        system_prompt = (
            "你是A股概念记忆库整理助手。"
            "你需要基于提供的记忆条目、官方概念与新闻，输出结构化 JSON，不能输出 markdown。"
        )
        user_payload = {
            "entry": {
                "keyword": entry.keyword,
                "title": entry.title,
                "content": entry.content,
                "category": entry.category,
                "source_type": entry.source_type,
                "source_name": entry.source_name,
                "source_url": entry.source_url,
                "is_fixed": entry.is_fixed,
                "tags": self._unique_strings(entry.tags_json or []),
                "related_stock_codes": self._normalize_codes(entry.related_stock_codes_json or []),
            },
            "matched_memory_entries": entries,
            "matched_official_concepts": official_matches,
            "matched_news": news_items,
        }
        safe_user_payload = self._json_safe(user_payload)
        user_prompt = (
            "请基于上下文，整理和补充这个概念记忆条目。\n"
            "必须返回 JSON object，且只返回 JSON。\n"
            "固定字段：\n"
            "{"
            "\"summary\":\"string\","
            "\"keywords\":[\"string\"],"
            "\"related_stock_codes\":[\"000001\"],"
            "\"reason\":\"string\","
            "\"importance_score\":0-100,"
            "\"content_suggestion\":\"string\","
            "\"extra_notes\":[\"string\"]"
            "}\n"
            "要求：\n"
            "1. 优先保留固定知识，不要随意改写明确事实。\n"
            "2. 如果新闻与官方数据能支持，补充更强的解释和关键词。\n"
            "3. 如果没有足够证据，不要强行扩展股票关联。\n"
            f"上下文如下：\n{json.dumps(safe_user_payload, ensure_ascii=False, default=str)}"
        )
        return system_prompt, user_prompt

    def _validate_ai_refresh_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("AI 返回格式错误")
        return {
            "summary": self._normalize_name(payload.get("summary")) or None,
            "keywords": self._unique_strings(payload.get("keywords") or []),
            "related_stock_codes": self._normalize_codes(payload.get("related_stock_codes") or []),
            "reason": self._normalize_name(payload.get("reason")) or None,
            "importance_score": int(self._clamp_score(payload.get("importance_score")) or 0),
            "content_suggestion": self._normalize_content(payload.get("content_suggestion")) or None,
            "extra_notes": self._unique_strings(payload.get("extra_notes") or []),
        }

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

    def refresh_entry(self, entry_id: int) -> dict[str, Any]:
        entry = self._get_entry(entry_id)
        matched_memory_entries = self._collect_entries_for_query(entry.keyword, limit=self.DEFAULT_MAX_ENTRIES)
        official_matches = self._collect_official_context([
            entry.keyword,
            entry.title,
            *(entry.tags_json or []),
        ])
        news_items = self._collect_news_context(entry.keyword, limit=self.DEFAULT_MAX_NEWS)

        run = ConceptMemoryRun(
            entry_id=entry.id,
            run_type="refresh",
            query_text=entry.keyword,
            status="running",
            provider="deepseek" if self.deepseek_service.enabled else "local",
            model=self.deepseek_service.DEFAULT_MODEL if self.deepseek_service.enabled else None,
            prompt_version=self.PROMPT_VERSION,
            matched_entry_count=len(matched_memory_entries),
            matched_news_count=len(news_items),
            started_at=utc_now(),
            input_context_json=self._json_safe({
                "entry": self._serialize_entry(entry),
                "matched_memory_entries": matched_memory_entries,
                "matched_official_concepts": official_matches,
                "matched_news": news_items,
            }),
        )
        self.db.add(run)
        self.db.flush()

        try:
            ai_result: Optional[dict[str, Any]] = None
            if self.deepseek_service.enabled:
                system_prompt, user_prompt = self._build_refresh_prompt(
                    entry=entry,
                    entries=matched_memory_entries,
                    official_matches=official_matches,
                    news_items=news_items,
                )
                ai_payload = self.deepseek_service.infer_json(system_prompt=system_prompt, user_prompt=user_prompt)
                ai_result = self._validate_ai_refresh_result(ai_payload)

                entry.summary = ai_result.get("summary") or entry.summary
                if ai_result.get("keywords"):
                    entry.tags_json = self._unique_strings([*(entry.tags_json or []), *ai_result["keywords"]])
                if ai_result.get("related_stock_codes"):
                    entry.related_stock_codes_json = self._normalize_codes([
                        *(entry.related_stock_codes_json or []),
                        *ai_result["related_stock_codes"],
                    ])
                if ai_result.get("content_suggestion"):
                    entry.content = self._normalize_content(ai_result["content_suggestion"]) or entry.content
                entry.evidence_json = self._json_safe({
                    "matched_memory_entries": matched_memory_entries,
                    "matched_official_concepts": official_matches,
                    "matched_news": news_items,
                    "reason": ai_result.get("reason"),
                    "extra_notes": ai_result.get("extra_notes") or [],
                })
                entry.status = "ready"
                entry.prompt_version = self.PROMPT_VERSION
                entry.last_refreshed_at = utc_now()
                run.provider = "deepseek"
                run.model = self.deepseek_service.DEFAULT_MODEL
                run.result_json = ai_result
            else:
                entry.evidence_json = self._json_safe({
                    "matched_memory_entries": matched_memory_entries,
                    "matched_official_concepts": official_matches,
                    "matched_news": news_items,
                })
                entry.status = "ready"
                entry.last_refreshed_at = utc_now()
                run.provider = "local"
                run.result_json = {
                    "summary": entry.summary or entry.title,
                    "keywords": self._unique_strings(entry.tags_json or []),
                    "related_stock_codes": self._normalize_codes(entry.related_stock_codes_json or []),
                    "reason": "local context refresh",
                    "importance_score": int(entry.priority or 0),
                    "content_suggestion": entry.content,
                    "extra_notes": [],
                }

            run.status = "completed"
            run.finished_at = utc_now()
            self.db.commit()
            return {
                "entry_id": entry.id,
                "keyword": entry.keyword,
                "run": self._serialize_run(run),
                "matched_news_count": len(news_items),
                "matched_official_concepts": official_matches,
                "matched_memory_entries": matched_memory_entries,
                "ai_summary": ai_result.get("summary") if ai_result else None,
                "ai_keywords": ai_result.get("keywords") if ai_result else [],
                "ai_related_stock_codes": ai_result.get("related_stock_codes") if ai_result else [],
            }
        except Exception as exc:
            self.db.rollback()
            failed_run = self.db.query(ConceptMemoryRun).filter(ConceptMemoryRun.id == run.id).first()
            failed_entry = self._get_entry(entry_id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.error_message = str(exc)
                failed_run.finished_at = utc_now()
            failed_entry.status = "error"
            self.db.commit()
            raise

    def compose_context(
        self,
        *,
        query: str,
        use_ai: bool = True,
        force_refresh: bool = False,
        max_entries: int = 8,
        max_news: int = 10,
    ) -> dict[str, Any]:
        normalized_query = self._normalize_name(query)
        if not normalized_query:
            raise ValueError("查询关键词不能为空")

        cache_hash = hashlib.sha1(normalized_query.encode("utf-8")).hexdigest()
        cache_key = f"concept_memory:compose:{cache_hash}:{int(use_ai)}:{max_entries}:{max_news}"
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached is not None:
                cached["cache_hit"] = True
                cached["source"] = "cache"
                return cached

        matched_entries = self._collect_entries_for_query(normalized_query, limit=max_entries)
        official_matches = self._collect_official_context(normalized_query)
        news_items = self._collect_news_context(normalized_query, limit=max_news)
        context_text = self._compose_context_text(
            query=normalized_query,
            entries=matched_entries,
            official_matches=official_matches,
            news_items=news_items,
        )

        run = ConceptMemoryRun(
            run_type="query",
            query_text=normalized_query,
            status="running",
            provider="deepseek" if use_ai and self.deepseek_service.enabled else "local",
            model=self.deepseek_service.DEFAULT_MODEL if use_ai and self.deepseek_service.enabled else None,
            prompt_version=self.PROMPT_VERSION,
            matched_entry_count=len(matched_entries),
            matched_news_count=len(news_items),
            started_at=utc_now(),
            input_context_json=self._json_safe({
                "query": normalized_query,
                "matched_entries": matched_entries,
                "matched_official_concepts": official_matches,
                "matched_news": news_items,
            }),
        )
        self.db.add(run)
        self.db.flush()

        try:
            ai_result: Optional[dict[str, Any]] = None
            if use_ai and self.deepseek_service.enabled:
                system_prompt = (
                    "你是A股概念记忆库检索助手。"
                    "你需要结合本地记忆、官方数据与新闻，输出可供二次分析的 JSON。"
                    "不能输出 markdown。"
                )
                user_prompt = (
                    "请基于提供的上下文，为用户检索问题生成结构化分析。\n"
                    "必须返回 JSON object，字段固定为："
                    '{"answer":"string","summary":"string","keywords":["string"],"suggested_filters":["string"],'
                    '"confidence":0-100,"source_usage":{"memory":0-100,"official":0-100,"news":0-100},'
                    '"related_stock_codes":["000001"],"reason":"string"}\n'
                    f"上下文如下：\n{context_text}\n\n结构化上下文：\n{json.dumps(run.input_context_json, ensure_ascii=False, default=str)}"
                )
                ai_payload = self.deepseek_service.infer_json(system_prompt=system_prompt, user_prompt=user_prompt)
                ai_result = {
                    "answer": self._normalize_name(ai_payload.get("answer")) or None,
                    "summary": self._normalize_name(ai_payload.get("summary")) or None,
                    "keywords": self._unique_strings(ai_payload.get("keywords") or []),
                    "suggested_filters": self._unique_strings(ai_payload.get("suggested_filters") or []),
                    "confidence": self._clamp_score(ai_payload.get("confidence")),
                    "source_usage": ai_payload.get("source_usage") if isinstance(ai_payload.get("source_usage"), dict) else {},
                    "related_stock_codes": self._normalize_codes(ai_payload.get("related_stock_codes") or []),
                    "reason": self._normalize_name(ai_payload.get("reason")) or None,
                }
                run.provider = "deepseek"
                run.model = self.deepseek_service.DEFAULT_MODEL
                run.result_json = ai_result
            else:
                ai_result = None
                run.provider = "local"
                run.result_json = {
                    "answer": None,
                    "summary": context_text,
                    "keywords": self._unique_strings([
                        *(item.get("keyword") for item in matched_entries),
                    ]),
                    "suggested_filters": [],
                    "confidence": None,
                    "source_usage": {"memory": 100, "official": 0, "news": 0},
                    "related_stock_codes": [],
                    "reason": "local context only",
                }

            run.status = "completed"
            run.finished_at = utc_now()
            payload = {
                "query": normalized_query,
                "cache_hit": False,
                "source": "ai" if ai_result is not None else "local",
                "context_text": context_text,
                "matched_entries": matched_entries,
                "matched_news": news_items,
                "matched_official_concepts": official_matches,
                "ai_result": ai_result,
                "run": self._serialize_run(run),
            }
            self.db.commit()
            cache.set(cache_key, payload, self.COMPOSE_CACHE_TTL)
            return payload
        except Exception as exc:
            self.db.rollback()
            failed_run = self.db.query(ConceptMemoryRun).filter(ConceptMemoryRun.id == run.id).first()
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.error_message = str(exc)
                failed_run.finished_at = utc_now()
            self.db.commit()
            raise
