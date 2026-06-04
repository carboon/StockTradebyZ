"""News Event Analysis Agent - main orchestrator."""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Optional

from openai import OpenAI
from sqlalchemy.orm import Session

from app.config import settings
from .event_classifier import event_classifier
from .search_orchestrator import search_orchestrator
from .evidence_ranker import evidence_ranker
from .article_extractor import article_extractor
from .entity_resolver import entity_resolver
from .industry_chain_mapper import industry_chain_mapper
from .market_realization_analyzer import market_realization_analyzer
from .prompts import ANALYSIS_PROMPT, ROUND_DECISION_PROMPT, SYSTEM_PROMPT
from .schemas import (
    AgentStatus,
    AnalysisResult,
    AnalyzeDetailRequest,
    EventClassification,
    EventType,
    ImpactPath,
    LLMRoundOutput,
    MarketScope,
    RelatedStock,
    RoundRecord,
)

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


class NewsEventAnalysisAgent:
    """新闻事件分析 Agent - 编排检索、证据、实体、产业链、行情、LLM 分析流程。"""

    def __init__(self) -> None:
        self._max_rounds = settings.news_agent_max_rounds
        self._max_queries_per_round = settings.news_agent_max_queries_per_round
        self._max_results_per_query = settings.news_agent_max_results_per_queries

    @property
    def _has_llm(self) -> bool:
        key = str(settings.deepseek_api_key or "").strip()
        if not key:
            key = str(os.environ.get("DEEPSEEK_API_KEY", "")).strip()
        return bool(key)

    def analyze(self, request: AnalyzeDetailRequest,
                db: Optional[Session] = None) -> AnalysisResult:
        task_id = f"nea_{uuid.uuid4().hex[:12]}"
        logger.info("NewsEventAnalysisAgent 开始分析: task_id=%s title=%s", task_id, request.title)

        if not self._has_llm:
            return self._analyze_without_llm(request, db=db, task_id=task_id)

        try:
            classification = event_classifier.classify(
                title=request.title,
                summary=request.summary,
                category=request.category,
                source=request.source,
                published_at=request.published_at or "",
                event_time=request.event_time or "",
            )
        except Exception as exc:
            logger.exception("事件分类失败: %s", exc)
            return AnalysisResult(
                status=AgentStatus.FAILED,
                task_id=task_id,
                reason=f"事件分类失败: {exc}",
            )

        if not classification.analyzable:
            return AnalysisResult(
                status=AgentStatus.STOPPED,
                task_id=task_id,
                event_type=classification.event_type.value,
                event_summary=request.title,
                reason=classification.reason,
                watch_points=self._default_watch_points(classification.event_type),
            )

        all_evidence: list[dict[str, Any]] = []
        all_entities: list[dict[str, Any]] = []
        all_realization: list[dict[str, Any]] = []
        rounds: list[RoundRecord] = []

        core_entity = self._extract_core_entity(request.title, request.summary)
        queries = search_orchestrator.generate_initial_queries(
            title=request.title,
            core_entity=core_entity,
            keyword=core_entity,
        )

        for round_num in range(1, self._max_rounds + 1):
            round_record = RoundRecord(
                round_num=round_num,
                queries=list(queries),
                evidence_count=0,
                status=AgentStatus.RUNNING,
            )

            try:
                search_results = search_orchestrator.search_many(
                    queries,
                    freshness="day",
                    max_results=self._max_results_per_query,
                    db=db,
                )
            except Exception as exc:
                logger.warning("搜索轮次失败: queries=%s error=%s", queries, exc)
                search_results = []
            new_evidence = evidence_ranker.rank(
                search_results,
                published_at=request.published_at,
                query_text=f"{request.title} {request.summary}",
            )
            self._enrich_evidence_content(new_evidence)
            for ev in new_evidence:
                all_evidence.append(ev.model_dump())

            round_record.evidence_count = len(new_evidence)

            entities = entity_resolver.resolve(
                request.title + " " + request.summary,
                [e.model_dump() for e in new_evidence],
                db=db,
            )
            all_entities = [e.model_dump() for e in entities]

            stock_codes = [
                e.matched_code for e in entities
                if e.matched_code and not e.is_overseas
            ]
            if db and stock_codes:
                realization = market_realization_analyzer.analyze(
                    stock_codes=stock_codes,
                    event_time=request.event_time,
                    db=db,
                )
                all_realization = [r.model_dump() for r in realization]

            chain_entities = [e.matched_name or e.name for e in entities]
            chains = industry_chain_mapper.map_entities(
                entity_names=chain_entities,
                keywords=[core_entity] if core_entity else None,
            )
            chain_data = [c.model_dump() for c in chains]

            dynamic_stocks = self._extract_stocks_from_evidence(
                all_evidence, db=db,
            )
            for ds in dynamic_stocks:
                found = any(
                    any(s.get("code") == ds["code"] for s in c.a_share_mapping)
                    for c in chains
                )
                if not found:
                    chain_data.append({
                        "sector": ds.get("sector", "动态发现"),
                        "nodes": [],
                        "a_share_mapping": [ds],
                    })

            if round_num == 1 and not search_results:
                return self._analyze_without_llm(request, db=db, task_id=task_id)

            decision = self._llm_round_decision(
                title=request.title,
                classification=classification,
                evidence=all_evidence,
                entities=all_entities,
                realization=all_realization,
                chain_data=chain_data,
                round_num=round_num,
            )

            round_record.status = decision.status
            rounds.append(round_record)

            if decision.status == AgentStatus.READY:
                return self._build_ready_result(
                    task_id=task_id,
                    request=request,
                    classification=classification,
                    evidence=all_evidence,
                    entities=all_entities,
                    realization=all_realization,
                    chain_data=chain_data,
                    rounds=rounds,
                )

            if decision.status == AgentStatus.STOPPED:
                return AnalysisResult(
                    status=AgentStatus.STOPPED,
                    task_id=task_id,
                    event_type=classification.event_type.value,
                    event_summary=request.title,
                    reason=decision.reason or "事件无法映射到具体板块或标的。",
                    evidence=all_evidence,
                    rounds=[r.model_dump() for r in rounds],
                )

            if decision.status == AgentStatus.NEED_MORE_DATA:
                if decision.search_queries:
                    queries = decision.search_queries
                else:
                    break

        return AnalysisResult(
            status=AgentStatus.STOPPED,
            task_id=task_id,
            event_type=classification.event_type.value,
            confidence=0.3,
            event_summary=request.title,
            reason="达到最大检索轮次，但仍证据不足。",
            evidence=all_evidence,
            rounds=[r.model_dump() for r in rounds],
            watch_points=["关注后续是否有更多权威信息发布"],
        )

    def _build_ready_result(
        self, task_id: str, request: AnalyzeDetailRequest,
        classification: EventClassification,
        evidence: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        realization: list[dict[str, Any]],
        chain_data: list[dict[str, Any]],
        rounds: list[RoundRecord],
    ) -> AnalysisResult:
        try:
            allowed_stock_codes = self._allowed_stock_codes(chain_data, entities)
            llm_result = self._llm_final_analysis(
                title=request.title,
                summary=request.summary,
                category=request.category,
                source=request.source,
                published_at=request.published_at or "",
                event_time=request.event_time or "",
                classification=classification.model_dump(),
                evidence=evidence,
                evidence_quality=self._summarize_evidence_quality(evidence),
                missing_slots=self._detect_missing_slots(evidence, chain_data, realization),
                entities=entities,
                chain_data=chain_data,
                realization=realization,
                allowed_stock_codes=allowed_stock_codes,
                round_num=len(rounds),
            )
        except Exception as exc:
            logger.exception("LLM 最终分析失败: %s", exc)
            return AnalysisResult(
                status=AgentStatus.FAILED,
                task_id=task_id,
                reason=f"LLM 分析失败: {exc}",
                evidence=evidence,
                rounds=[r.model_dump() for r in rounds],
            )

        raw_stocks = [
            RelatedStock(**s) if isinstance(s, dict) else RelatedStock()
            for s in llm_result.get("related_stocks", [])
        ]
        related_stocks = self._select_top_stocks(raw_stocks, max_count=5, allowed_codes=allowed_stock_codes)

        return AnalysisResult(
            status=AgentStatus.READY,
            task_id=task_id,
            event_type=classification.event_type.value,
            confidence=llm_result.get("confidence"),
            event_summary=llm_result.get("event_summary", request.title),
            core_facts=llm_result.get("core_facts", []),
            impact_path=[
                ImpactPath(**p) if isinstance(p, dict) else ImpactPath(description=str(p))
                for p in llm_result.get("impact_path", [])
            ],
            direct_sectors=llm_result.get("direct_sectors", []),
            indirect_sectors=llm_result.get("indirect_sectors", []),
            related_stocks=related_stocks,
            market_realization=realization,
            upstream_downstream=llm_result.get("upstream_downstream", []),
            risks=llm_result.get("risks", []),
            watch_points=llm_result.get("watch_points", []),
            evidence=evidence,
            rounds=[r.model_dump() for r in rounds],
            reason="",
        )

    def _llm_round_decision(
        self, title: str, classification: EventClassification,
        evidence: list[dict[str, Any]], entities: list[dict[str, Any]],
        realization: list[dict[str, Any]], chain_data: list[dict[str, Any]],
        round_num: int,
    ) -> LLMRoundOutput:
        if round_num == self._max_rounds:
            evidence_count = len(evidence)
            if evidence_count >= 3:
                return LLMRoundOutput(status=AgentStatus.READY)
            return LLMRoundOutput(
                status=AgentStatus.STOPPED,
                reason="达到最大轮次，证据不足，无法给出可靠分析。",
            )

        prompt = ROUND_DECISION_PROMPT.format(
            title=title,
            round_num=round_num,
            max_rounds=self._max_rounds,
            evidence_count=len(evidence),
            entity_count=len(entities),
            market_data_count=len(realization),
            max_queries=self._max_queries_per_round,
        )

        try:
            result = self._call_llm_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt,
                temperature=0.2,
            )
            return LLMRoundOutput(
                status=AgentStatus(result.get("status", "need_more_data")),
                reason=result.get("reason", ""),
                search_queries=result.get("search_queries", []),
            )
        except Exception as exc:
            logger.warning("LLM round decision failed: %s", exc)
            if len(evidence) >= 3:
                return LLMRoundOutput(status=AgentStatus.READY)
            return LLMRoundOutput(
                status=AgentStatus.NEED_MORE_DATA,
                reason="LLM 决策异常，自动进行补充检索。",
                search_queries=[f"{title} 影响 行业"],
            )

    def _llm_final_analysis(self, **kwargs: Any) -> dict[str, Any]:
        prompt = ANALYSIS_PROMPT.format(
            title=kwargs.get("title", ""),
            summary=kwargs.get("summary", ""),
            category=kwargs.get("category", ""),
            source=kwargs.get("source", ""),
            published_at=kwargs.get("published_at", ""),
            event_time=kwargs.get("event_time", ""),
            classification=json.dumps(kwargs.get("classification", {}), ensure_ascii=False, indent=2),
            evidence=json.dumps(kwargs.get("evidence", []), ensure_ascii=False, indent=2),
            evidence_quality=json.dumps(kwargs.get("evidence_quality", {}), ensure_ascii=False, indent=2),
            missing_slots=json.dumps(kwargs.get("missing_slots", []), ensure_ascii=False, indent=2),
            entities=json.dumps(kwargs.get("entities", []), ensure_ascii=False, indent=2),
            industry_chains=json.dumps(kwargs.get("chain_data", []), ensure_ascii=False, indent=2),
            market_realization=json.dumps(kwargs.get("realization", []), ensure_ascii=False, indent=2),
            allowed_stock_codes=json.dumps(kwargs.get("allowed_stock_codes", []), ensure_ascii=False, indent=2),
            round_num=kwargs.get("round_num", 1),
            max_rounds=self._max_rounds,
        )

        result = self._call_llm_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            temperature=0.2,
        )
        return result

    @staticmethod
    def _summarize_evidence_quality(evidence: list[dict[str, Any]]) -> dict[str, Any]:
        levels: dict[str, int] = {}
        for item in evidence:
            level = str(item.get("source_level") or "C")
            levels[level] = levels.get(level, 0) + 1
        high_quality = levels.get("A", 0) + levels.get("B", 0)
        return {
            "total": len(evidence),
            "by_level": levels,
            "high_quality_count": high_quality,
            "has_high_quality": high_quality > 0,
        }

    @staticmethod
    def _detect_missing_slots(
        evidence: list[dict[str, Any]],
        chain_data: list[dict[str, Any]],
        realization: list[dict[str, Any]],
    ) -> list[str]:
        missing: list[str] = []
        high_quality = sum(1 for item in evidence if str(item.get("source_level") or "") in {"A", "B"})
        if high_quality == 0:
            missing.append("缺少 A/B 级证据")
        if not chain_data:
            missing.append("缺少产业链映射")
        if not realization:
            missing.append("缺少行情兑现数据")
        return missing

    @staticmethod
    def _allowed_stock_codes(chain_data: list[dict[str, Any]], entities: list[dict[str, Any]]) -> list[str]:
        codes: list[str] = []
        seen: set[str] = set()
        for entity in entities:
            code = str(entity.get("matched_code") or "")
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
        for chain in chain_data:
            for item in chain.get("a_share_mapping") or []:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("code") or "")
                if code and code not in seen:
                    seen.add(code)
                    codes.append(code)
        return codes

    @staticmethod
    def _call_llm_json(system_prompt: str, user_prompt: str,
                       temperature: float = 0.2) -> dict[str, Any]:
        api_key = str(settings.deepseek_api_key or "").strip()
        if not api_key:
            api_key = str(os.environ.get("DEEPSEEK_API_KEY", "")).strip()
        if not api_key:
            raise ValueError("DeepSeek API Key 未配置")

        client = OpenAI(
            api_key=api_key,
            base_url=DEEPSEEK_BASE_URL,
            timeout=60.0,
            max_retries=1,
        )
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise ValueError("LLM 未返回内容")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("LLM 返回格式不是 JSON object")
        return payload

    @staticmethod
    def _extract_core_entity(title: str, summary: str) -> str:
        text = f"{title} {summary}"
        priority_keywords = [
            "英伟达", "苹果", "特斯拉", "微软", "谷歌", "亚马逊", "Meta",
            "华为", "比亚迪", "宁德时代", "茅台", "腾讯", "阿里",
            "芯片", "AI", "人工智能", "半导体", "新能源", "光伏",
            "机器人", "自动驾驶", "创新药",
        ]
        for kw in priority_keywords:
            if kw in text:
                return kw
        return title[:30]

    def _analyze_without_llm(self, request: AnalyzeDetailRequest,
                              db: Optional[Session] = None,
                              task_id: str = "") -> AnalysisResult:
        """无 LLM 降级分析：使用规则分类 + 知识库/关键词匹配."""
        classification = event_classifier.classify(
            title=request.title, summary=request.summary,
            category=request.category, source=request.source,
            published_at=request.published_at or "",
            event_time=request.event_time or "",
        )

        if not classification.analyzable:
            return AnalysisResult(
                status=AgentStatus.STOPPED, task_id=task_id,
                event_type=classification.event_type.value,
                event_summary=request.title, reason=classification.reason,
                watch_points=self._default_watch_points(classification.event_type),
            )

        text = f"{request.title} {request.summary}"
        entities = entity_resolver.resolve(text, [], db=db)
        chain_entities = [e.matched_name or e.name for e in entities]
        chains = industry_chain_mapper.map_entities(entity_names=chain_entities)
        all_stocks: list[dict[str, Any]] = []
        seen_codes: set[str] = set()
        for chain in chains:
            for s in chain.a_share_mapping:
                code = s.get("code", "")
                if code and code not in seen_codes:
                    seen_codes.add(code)
                    all_stocks.append(s)

        code_from_text = self._extract_stock_code(text)
        if code_from_text and code_from_text not in seen_codes:
            seen_codes.add(code_from_text)
            name_from_text = self._extract_stock_name(text) or code_from_text
            all_stocks.insert(0, {
                "code": code_from_text, "name": name_from_text,
                "relation": "新闻直接相关", "strength": "strong",
                "reason": "新闻标题中直接提及该股票",
            })

        if not all_stocks:
            broader_keywords = self._match_broader_keywords(text)
            if broader_keywords:
                broader_chains = industry_chain_mapper.map_entities(
                    entity_names=[], keywords=broader_keywords,
                )
                for chain in broader_chains:
                    for s in chain.a_share_mapping:
                        code = s.get("code", "")
                        if code and code not in seen_codes:
                            seen_codes.add(code)
                            all_stocks.append(s)

        if not all_stocks:
            return AnalysisResult(
                status=AgentStatus.STOPPED, task_id=task_id,
                event_type=classification.event_type.value,
                event_summary=request.title,
                reason="未在知识库中找到明确的产业链关联标的，建议手动确认或开启 LLM (设置 DEEPSEEK_API_KEY) 以获更完整分析。",
            )

        realization: list[dict[str, Any]] = []
        if db:
            stock_codes = [s["code"] for s in all_stocks if s.get("code")]
            if stock_codes:
                r = market_realization_analyzer.analyze(
                    stock_codes=stock_codes,
                    event_time=request.event_time, db=db,
                )
                realization = [x.model_dump() for x in r]

        sectors = list({c.sector for c in chains if c.sector})
        all_related = [
            RelatedStock(
                code=s.get("code", ""), name=s.get("name", ""),
                relation=s.get("relation", ""),
                mapping_strength=s.get("strength", "medium"),
                reason=s.get("reason", ""),
            ) for s in all_stocks
        ]
        related_stocks = self._select_top_stocks(all_related, max_count=5)

        impact_text = "减持" if "减持" in text else "公告"
        sentiment_text = "偏利空" if any(kw in text for kw in ("减持", "处罚", "下调", "跌超", "下跌")) else "中性观察"

        return AnalysisResult(
            status=AgentStatus.READY, task_id=task_id,
            event_type=classification.event_type.value,
            confidence=0.5,
            event_summary=request.title,
            core_facts=[request.summary[:200]] if request.summary else [request.title],
            impact_path=[ImpactPath(
                description=f"基于规则分析的{impact_text}事件，{sentiment_text}",
                confidence=0.5,
            )],
            direct_sectors=sectors[:5],
            related_stocks=related_stocks,
            market_realization=realization,
            risks=["本分析基于规则匹配和知识库，未经 LLM 深度分析，建议设置 DEEPSEEK_API_KEY 获取更完整分析。"],
            watch_points=["关注后续公告和市场反应"],
            reason="(规则降级模式，未使用 LLM)",
        )

    def _extract_stocks_from_evidence(
        self, evidence: list[dict[str, Any]], db: Optional[Session] = None,
    ) -> list[dict[str, Any]]:
        if not db or not evidence:
            return []

        all_text = "\n".join(
            f"标题：{e.get('title','')}\n摘要：{e.get('summary','')}"
            for e in evidence[:15]
        )

        codes_in_text: set[str] = set()
        import re as _re
        for m in _re.finditer(r"(\d{6})\.(SZ|SH|BJ)", all_text, _re.IGNORECASE):
            codes_in_text.add(f"{m.group(1)}.{m.group(2).upper()}")

        names_from_llm = self._llm_extract_stock_names(all_text)
        all_names: set[str] = set(names_from_llm)
        for m in _re.finditer(r"([\u4e00-\u9fff]{2,6}(?:科技|股份|集团|控股|电子|通信|医药|能源|汽车|银行|电器|光电|微电|智能|生物))", all_text):
            name = m.group(1)
            if len(name) >= 3:
                all_names.add(name)

        if not codes_in_text and not all_names:
            return []

        try:
            from app.models import Stock
            found = db.query(Stock).filter(
                Stock.code.in_(list(codes_in_text))
                | Stock.name.in_(list(all_names))
            ).limit(30).all()

            results: list[dict[str, Any]] = []
            seen: set[str] = set()
            for s in found:
                code = s.code or ""
                name = s.name or ""
                if code in seen:
                    continue
                seen.add(code)
                results.append({
                    "code": code, "name": name,
                    "relation": "搜索证据关联",
                    "strength": "medium",
                    "reason": "搜索结果中提及，经本地股票库确认",
                })
            return results
        except Exception:
            return []

        all_text = " ".join(
            f"{e.get('title','')} {e.get('summary','')}"
            for e in evidence
        )

        codes_in_text: set[str] = set()
        for m in re.finditer(r"(\d{6})\.(SZ|SH|BJ)", all_text, re.IGNORECASE):
            codes_in_text.add(f"{m.group(1)}.{m.group(2).upper()}")

        names_in_text: set[str] = set()
        for m in re.finditer(
            r"([\u4e00-\u9fff]{2,6}(?:科技|股份|集团|控股|电子|通信|医药|能源|汽车|银行|电器|光电|微电|智能))",
            all_text,
        ):
            name = m.group(1)
            if len(name) >= 3:
                names_in_text.add(name)

        if not codes_in_text and not names_in_text:
            return []

        try:
            from app.models import Stock
            stocks = []
            found = db.query(Stock).filter(
                Stock.code.in_(list(codes_in_text))
                | Stock.name.in_(list(names_in_text))
            ).limit(30).all()

            results: list[dict[str, Any]] = []
            seen: set[str] = set()
            for s in stocks:
                code = s.code or ""
                name = s.name or ""
                if code in seen:
                    continue
                seen.add(code)
                results.append({
                    "code": code, "name": name,
                    "relation": "搜索证据关联",
                    "strength": "medium",
                    "reason": "搜索结果中提及，经本地股票库确认",
                })
            return results
        except Exception:
            return []

    @staticmethod
    def _select_top_stocks(
        stocks: list[RelatedStock],
        max_count: int = 5,
        allowed_codes: list[str] | None = None,
    ) -> list[RelatedStock]:
        if allowed_codes is not None:
            allowed = set(allowed_codes)
            stocks = [stock for stock in stocks if stock.code in allowed]
        if len(stocks) <= max_count:
            return stocks

        strength_order = {"strong": 0, "medium": 1, "weak": 2}
        sorted_stocks = sorted(
            stocks,
            key=lambda s: strength_order.get(s.mapping_strength.value if hasattr(s.mapping_strength, 'value') else str(s.mapping_strength), 3),
        )
        return sorted_stocks[:max_count]

    def _llm_extract_stock_names(self, evidence_text: str) -> list[str]:
        prompt = (
            "从以下搜索文本中，提取所有可能被提及的A股公司名称（只输出名称，不要代码）。\n"
            "如果没有明确的A股公司，输出空列表。\n\n"
            f"{evidence_text[:4000]}\n\n"
            '只输出 JSON: {"names": ["公司名1", "公司名2"]}'
        )
        try:
            result = self._call_llm_json(
                system_prompt="你是A股市场数据提取助手。",
                user_prompt=prompt,
                temperature=0.1,
            )
            names = result.get("names", [])
            return [str(n) for n in names if isinstance(n, str) and len(n) >= 2]
        except Exception:
            return []

    @staticmethod
    def _enrich_evidence_content(evidence_items: list[Any], max_items: int = 3) -> None:
        enriched = 0
        for ev in evidence_items:
            level = getattr(ev, "source_level", "")
            level_text = level.value if hasattr(level, "value") else str(level)
            if level_text not in {"A", "B"}:
                continue
            if not getattr(ev, "url", ""):
                continue
            if len(getattr(ev, "summary", "") or "") >= 500:
                continue
            article = article_extractor.extract(ev.url)
            if not article or not article.get("content"):
                continue
            ev.summary = article["content"][:1200]
            if article.get("title") and not ev.title:
                ev.title = article["title"]
            enriched += 1
            if enriched >= max_items:
                return

    @staticmethod
    def _match_broader_keywords(text: str) -> list[str]:
        keywords_map = {
            "半导体": ["半导体", "芯片", "晶圆", "封测", "光刻"],
            "存储": ["存储", "DRAM", "NAND", "闪存", "内存"],
            "AI": ["AI", "人工智能", "算力", "大模型"],
            "光伏": ["光伏", "太阳能", "硅料", "组件"],
            "新能源": ["新能源", "锂电", "电池", "电动车"],
            "机器人": ["机器人", "自动化", "智能制造"],
            "消费电子": ["消费电子", "手机", "耳机", "MR"],
            "贵金属": ["白银", "黄金", "银价", "金价", "贵金属"],
            "医药": ["医药", "制药", "创新药", "仿制药", "FDA", "biotech", "pharma"],
            "减肥药": ["减肥药", "减重", "GLP-1", "司美格鲁肽", "替尔泊肽"],
            "CXO": ["CXO", "CRO", "CDMO", "药明", "康龙"],
        }
        matched = []
        text_lower = text.lower()
        for sector, kws in keywords_map.items():
            if any(kw.lower() in text_lower for kw in kws):
                matched.append(sector)
        return matched

    @staticmethod
    def _extract_stock_code(text: str) -> str:
        import re
        m = re.search(r"(\d{6})\.(SZ|SH|BJ)", text, re.IGNORECASE)
        if m:
            return f"{m.group(1)}.{m.group(2).upper()}"
        return ""

    @staticmethod
    def _extract_stock_name(text: str) -> str:
        import re
        m = re.search(r"[\u4e00-\u9fff]{2,6}(?:科技|股份|集团|控股|电子|通信|医药|能源|汽车|银行|电器)", text)
        if m:
            return m.group(0)
        return ""

    @staticmethod
    def _default_watch_points(event_type: EventType) -> list[str]:
        if event_type == EventType.GEOPOLITICAL_BROAD:
            return [
                "等待是否出现具体政策文件",
                "观察是否涉及关税、出口管制、行业补贴、订单变化等可交易变量",
            ]
        if event_type == EventType.UNVERIFIABLE_RUMOR:
            return [
                "等待官方或权威媒体确认",
                "观察相关公司是否发布澄清公告",
            ]
        return ["等待更多具体信息发布"]


news_event_agent = NewsEventAnalysisAgent()
