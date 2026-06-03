"""Relative value-lowland stock screener — multi-phase principle-driven pipeline."""
from __future__ import annotations

import json
import logging
import math
import re
import html
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import pandas as pd
import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Config, Stock, StockDaily, ValueLowlandProfile, ValueLowlandRun
from app.schemas import (
    ValueLowlandCandidate,
    ValueLowlandCompanyProfile,
    ValueLowlandEvidence,
    ValueLowlandResponse,
    ValueLowlandScoreBreakdown,
)
from app.services.deepseek_service import DeepSeekService
from app.services.financial_data_service import FinancialDataService
from app.services.tushare_service import TushareService
from app.time_utils import utc_now
from app.utils.tushare_rate_limit import acquire_tushare_slot

logger = logging.getLogger(__name__)

# ── Principle-driven filter constants ────────────────────────────────────────
# P1: 央企/省国资优先；民企不纳入核心标的
SOE_TYPES = frozenset({"central_soe", "provincial_soe"})
COST_OF_PRIVATE = -15          # 民企硬扣分（不看到）
COST_OF_UNKNOWN = -10          # 未知权属硬扣分
COST_OF_LOCAL_SOE = -5         # 市县级国资弱扣分

# P2: 不买 ST、退市、业绩连续下降或亏损
ST_NAME_KEYWORDS = ("ST", "*ST", "退")
EXCLUDE_LOW_POS_MAX = 0.90     # 区间位置 > 90% → 排除（不是低位）
EXCLUDE_MCAP_MAX_WAN = 3_000_000  # 市值 > 300 亿 → 排除（太大无弹性）
EXCLUDE_PB_MAX = 10            # PB > 10 → 排除（明显高估）
EXCLUDE_PE_EXTREME = 1000      # PE 极端值排除
EXCLUDE_NP_YOY_CATASTROPHE = -200  # 净利润暴跌 >200% → 排除
EXCLUDE_ROE_DEEP_LOSS = -100   # ROE 深度亏损 < -100% → 排除

# P3: 低位低价，经历两年以上盘整
PRICE_RANGE_LOOKBACK_DAYS = 760  # ~2 年
STRICT_LOW_POSITION_MAX = 0.70  # 严选只保留两年区间位置不高于 70% 的低位票
LOW_POSITION_PENALTY = 0.70    # 区间位置 > 70% → 开始扣分
LOW_POSITION_PENALTY_MAX = -10
RISEN_2X_FROM_LOW = 2.0        # 已从低点翻倍 → 标记警告

# P4: 市值 < 200 亿
MCAP_BONUS_50YI = 500_000      # 50 亿以内 +5
MCAP_BONUS_100YI = 1_000_000   # 100 亿以内 +4
MCAP_BONUS_200YI = 2_000_000   # 200 亿以内 +3
MCAP_BONUS_500YI = 5_000_000   # 500 亿以内 +1
MCAP_PENALTY_200YI = 2_000_000 # 超过 200 亿扣分

# P6: 业绩边际改善
NP_YOY_BURST = 50              # 爆发式增长 >50%
NP_YOY_GOOD = 15               # 良好增长
NP_YOY_MARGINAL = 0            # 边际改善
NP_YOY_WEAK = -20              # 弱衰退

# ── Pipeline size constants ──────────────────────────────────────────────────
FINANCIAL_FETCH_LIMIT = 600    # Phase 2 最多拉财务数据的股票数
AI_ENRICH_LIMIT = 200          # Phase 3 最多做 AI 画像的股票数
ENRICH_OUTPUT_LIMIT = 300      # enrich 时扩大硬筛候选池，避免低分国资被过早截断
FULL_ANALYSIS_LIMIT_SENTINEL = 0
RULE_CONFIDENCE_THRESHOLD = 70
QUICK_PROFILE_ATTEMPT_LIMIT = 5
WIKIPEDIA_API_URL = "https://zh.wikipedia.org/w/api.php"
WIKIPEDIA_PAGE_URL = "https://zh.wikipedia.org/wiki/"
BAIDU_BAIKE_PAGE_URL = "https://baike.baidu.com/item/"
ENCYCLOPEDIA_TIMEOUT_SECONDS = 3
OFFICIAL_SITE_TIMEOUT_SECONDS = 3
OFFICIAL_SITE_MAX_BYTES = 300_000
OFFICIAL_SITE_PATHS = (
    "",
    "/about",
    "/about.html",
    "/about/index.html",
    "/gsjj",
    "/investor",
)

# ── Cycle industry keywords (P5 周期弹性) ────────────────────────────────────
CYCLE_INDUSTRY_KEYWORDS = (
    "煤", "有色", "钢", "石油", "化工", "化学", "矿", "稀土", "钨", "铜", "铝", "锂",
    "军工", "航天", "电力", "水务", "燃气", "港口", "建材", "农", "种业",
)
CYCLE_TYPES = frozenset({"resource", "chemical", "military", "energy", "utility"})
STRICT_DISPLAY_CYCLE_TYPES = frozenset({"resource", "chemical", "energy"})
STRICT_PROFILE_CONFIDENCE_MIN = 50


class ValueLowlandService:
    """原则驱动的多阶段价值洼地筛选器。

    管线：
      Phase 1 — 硬数据过滤（价格位置 / PB / PE / 市值），无需财务数据
      Phase 2 — 财务过滤（净利润增速 / ROE），需 Tushare fina_indicator
      Phase 3 — 静态画像（本地缓存 + Tushare 基础信息，必要时 AI 结构化）
      Phase 4 — 综合排序 + 分类输出
    """

    def __init__(
        self,
        db: Session,
        *,
        tushare_service: TushareService | None = None,
        deepseek_service: DeepSeekService | None = None,
        financial_service: FinancialDataService | None = None,
    ) -> None:
        self.db = db
        self.tushare_service = tushare_service or TushareService()
        self.deepseek_service = deepseek_service or DeepSeekService(api_key=self._load_deepseek_api_key())
        self.financial_service = financial_service or FinancialDataService(db, self.tushare_service)
        self._tushare_basic_profile_cache: dict[str, dict[str, Any]] | None = None
        self._tushare_company_profile_cache: dict[str, dict[str, Any]] | None = None

    # ── Public API ───────────────────────────────────────────────────────────────

    def screen(
        self,
        *,
        limit: int = 50,
        enrich: bool = False,
        force_refresh: bool = False,
        allow_ai_profiles: bool = False,
        profile_attempt_limit: int | None = None,
    ) -> ValueLowlandResponse:
        full_analysis = int(limit or 0) <= FULL_ANALYSIS_LIMIT_SENTINEL
        output_limit = None if full_analysis else max(1, min(int(limit or 50), 100))
        latest_trade_date = self._latest_trade_date()
        if latest_trade_date is None:
            return ValueLowlandResponse(
                generated_at=utc_now(),
                message="本地 stock_daily 暂无行情数据，请先完成行情初始化。",
            )

        hard_candidates = self._build_hard_candidates(
            latest_trade_date=latest_trade_date,
            output_limit=None if full_analysis else (ENRICH_OUTPUT_LIMIT if enrich else output_limit * 3),
            full_analysis=full_analysis,
        )
        if not hard_candidates:
            return ValueLowlandResponse(
                generated_at=utc_now(),
                trade_date=latest_trade_date,
                message="未筛出候选；请确认本地日线和 Tushare Token 状态。",
            )

        enriched_count = 0
        profile_attempts = 0
        self._apply_cached_profiles(hard_candidates)
        if enrich:
            # 得分门槛：距 top limit 差距 > 35 分的股票无法靠 AI 追上，跳过
            threshold_idx = min(output_limit or len(hard_candidates), len(hard_candidates)) - 1
            cutoff_score = hard_candidates[threshold_idx].score if threshold_idx >= 0 else float("-inf")
            enrich_min_score = float("-inf") if full_analysis else cutoff_score - 35
            enrich_attempt_limit = (
                max(0, int(profile_attempt_limit))
                if profile_attempt_limit is not None
                else (len(hard_candidates) if full_analysis else (AI_ENRICH_LIMIT if allow_ai_profiles else QUICK_PROFILE_ATTEMPT_LIMIT))
            )

            for candidate in hard_candidates:
                if profile_attempts >= enrich_attempt_limit:
                    break
                if candidate.score < enrich_min_score:
                    continue
                if candidate.profile.confidence >= 50 and candidate.profile.ownership_type != "unknown":
                    continue

                profile_attempts += 1
                profile = self.get_company_profile(
                    code=candidate.code,
                    name=candidate.name or candidate.code,
                    industry=candidate.industry,
                    ts_code=candidate.ts_code,
                    force_refresh=force_refresh,
                    allow_ai=allow_ai_profiles,
                )
                candidate.profile = profile
                candidate.score_breakdown = self._score_candidate(candidate, profile=profile)
                candidate.score = self._total_score(candidate.score_breakdown)
                candidate.reasons = self._build_reasons(candidate)
                candidate.risk_notes = self._build_risk_notes(candidate)
                if profile.confidence > 0:
                    enriched_count += 1

            logger.info(
                "Profile enrich: %d stocks refreshed from %d attempts (limit %d, cutoff %.1f)",
                enriched_count,
                profile_attempts,
                enrich_attempt_limit,
                enrich_min_score,
            )

            cached_applied = self._apply_cached_profiles(hard_candidates)
            if cached_applied:
                logger.info("Profile enrich: applied %d cached profiles before ranking", cached_applied)

        hard_candidates = self._apply_strict_profile_filter(hard_candidates)
        if not hard_candidates:
            return ValueLowlandResponse(
                generated_at=utc_now(),
                trade_date=latest_trade_date,
                message="未筛出候选；请确认本地日线、Tushare Token 和公司画像缓存状态。",
            )

        ranked = self._rank_candidates(hard_candidates, limit=output_limit, prefer_soe=enrich)
        for index, candidate in enumerate(ranked, start=1):
            candidate.rank = index

        return ValueLowlandResponse(
            generated_at=utc_now(),
            trade_date=latest_trade_date,
            total=len(ranked),
            enriched_count=enriched_count,
            message=self._build_response_message(enrich=enrich),
            total_rank=ranked,
            soe_lowland=ranked,
            cycle_resource=[],
            earnings_reversal=[],
            insufficient_evidence=[],
        )

    def get_cached_screen(self, *, limit: int = 50) -> ValueLowlandResponse:
        full_response = int(limit or 0) <= FULL_ANALYSIS_LIMIT_SENTINEL
        run = (
            self.db.query(ValueLowlandRun)
            .filter(ValueLowlandRun.status == "completed", ValueLowlandRun.result_json.isnot(None))
            .order_by(ValueLowlandRun.completed_at.desc(), ValueLowlandRun.id.desc())
            .first()
        )
        if run is None or not isinstance(run.result_json, dict):
            return ValueLowlandResponse(
                generated_at=utc_now(),
                message="暂无价值洼地批量结果，请先启动后台刷新。",
            )
        response = ValueLowlandResponse(**run.result_json)
        if full_response:
            return self._limit_response(response, limit=max(len(response.total_rank), 1))
        return self._limit_response(response, limit=max(1, min(int(limit or 50), 1000)))

    def save_run_result(self, run: ValueLowlandRun, response: ValueLowlandResponse) -> None:
        run.result_json = response.model_dump(mode="json")
        run.status = "completed"
        run.completed_at = utc_now()
        run.updated_at = run.completed_at
        self.db.commit()

    @staticmethod
    def _limit_response(response: ValueLowlandResponse, *, limit: int) -> ValueLowlandResponse:
        limited = response.model_copy(deep=True)
        ranked = ValueLowlandService._apply_strict_profile_filter(limited.total_rank)[:limit]
        for index, candidate in enumerate(ranked, start=1):
            candidate.rank = index
        limited.total_rank = ranked
        limited.total = len(ranked)
        limited.soe_lowland = ranked
        limited.cycle_resource = []
        limited.earnings_reversal = []
        limited.insufficient_evidence = []
        return limited

    @staticmethod
    def _apply_strict_profile_filter(candidates: list[ValueLowlandCandidate]) -> list[ValueLowlandCandidate]:
        return [item for item in candidates if ValueLowlandService._passes_strict_lowland_filter(item)]

    @staticmethod
    def _passes_strict_lowland_filter(candidate: ValueLowlandCandidate) -> bool:
        mv = candidate.total_mv or candidate.circ_mv
        return bool(
            candidate.profile.ownership_type in SOE_TYPES
            and candidate.profile.cycle_type in STRICT_DISPLAY_CYCLE_TYPES
            and candidate.profile.confidence >= STRICT_PROFILE_CONFIDENCE_MIN
            and mv is not None
            and mv <= EXCLUDE_MCAP_MAX_WAN
            and candidate.low_position_ratio is not None
            and candidate.low_position_ratio <= STRICT_LOW_POSITION_MAX
            and not any(str(tag).startswith("已从低点翻倍") for tag in candidate.tags)
            and ValueLowlandService._has_financial_improvement(candidate)
        )

    def get_company_profile(
        self,
        *,
        code: str,
        name: str,
        industry: str | None,
        ts_code: str | None = None,
        force_refresh: bool = False,
        allow_ai: bool = True,
    ) -> ValueLowlandCompanyProfile:
        code = str(code or "").zfill(6)
        cached = self.db.query(ValueLowlandProfile).filter(ValueLowlandProfile.code == code).first()
        now = utc_now()
        if cached and self._is_profile_cache_usable(cached):
            return self._profile_from_model(cached, cached_flag=True)

        tushare_result = self._profile_from_tushare_static(
            code=code,
            name=name,
            industry=industry,
            ts_code=ts_code or self._to_ts_code(code, None),
        )
        if tushare_result["confidence"] >= RULE_CONFIDENCE_THRESHOLD:
            model = self._upsert_profile_cache(
                code=code,
                result=tushare_result,
                evidence=tushare_result.get("evidence") or [],
                now=now,
            )
            return self._profile_from_model(model, cached_flag=False)

        official_result = self._profile_from_official_site(
            code=code,
            name=name,
            industry=industry,
            ts_code=ts_code or self._to_ts_code(code, None),
            base_result=tushare_result,
        )
        if official_result["confidence"] >= tushare_result["confidence"] and official_result["confidence"] > 0:
            model = self._upsert_profile_cache(
                code=code,
                result=official_result,
                evidence=official_result.get("evidence") or [],
                now=now,
            )
            if official_result["confidence"] >= RULE_CONFIDENCE_THRESHOLD or not allow_ai:
                return self._profile_from_model(model, cached_flag=False)

        wikipedia_result = self._profile_from_wikipedia(
            code=code,
            name=name,
            industry=industry,
            base_result=official_result,
        )
        if wikipedia_result["confidence"] >= tushare_result["confidence"] and wikipedia_result["confidence"] > 0:
            model = self._upsert_profile_cache(
                code=code,
                result=wikipedia_result,
                evidence=wikipedia_result.get("evidence") or [],
                now=now,
            )
            if wikipedia_result["confidence"] >= RULE_CONFIDENCE_THRESHOLD or not allow_ai:
                return self._profile_from_model(model, cached_flag=False)

        ownership_evidence = self._search_ownership_evidence(name=name, ts_code=ts_code or self._to_ts_code(code, None))
        rule_result = self._infer_ownership_with_rules(name=name, evidence=ownership_evidence)
        if (
            rule_result["ownership_type"] != "unknown"
            and rule_result["confidence"] >= RULE_CONFIDENCE_THRESHOLD
        ):
            result = self._profile_from_rule_result(rule_result, fallback_evidence=ownership_evidence)
            model = self._upsert_profile_cache(code=code, result=result, evidence=ownership_evidence, now=now)
            return self._profile_from_model(model, cached_flag=False)

        if not allow_ai:
            if tushare_result["confidence"] > 0:
                model = self._upsert_profile_cache(
                    code=code,
                    result=tushare_result,
                    evidence=tushare_result.get("evidence") or [],
                    now=now,
                )
                return self._profile_from_model(model, cached_flag=False)
            return self._unknown_profile("Tushare 静态信息和公告证据不足，需人工复核。")
        if not self.deepseek_service.enabled:
            return self._unknown_profile("DeepSeek API Key 未配置，无法结构化判断公司画像。")

        evidence = self._search_company_evidence(
            name=name,
            ts_code=ts_code or self._to_ts_code(code, None),
            initial_evidence=ownership_evidence,
        )
        if not evidence:
            return self._unknown_profile("检索未返回可用证据。")

        result = self._infer_company_profile_with_ai(code=code, name=name, industry=industry, evidence=evidence)
        model = self._upsert_profile_cache(code=code, result=result, evidence=evidence, now=now)
        return self._profile_from_model(model, cached_flag=False)

    # ── Phase 0: Data loading ────────────────────────────────────────────────────

    def _latest_trade_date(self) -> date | None:
        return self.db.execute(select(func.max(StockDaily.trade_date))).scalar_one_or_none()

    def _apply_cached_profiles(self, candidates: list[ValueLowlandCandidate]) -> int:
        codes = [candidate.code for candidate in candidates]
        if not codes:
            return 0

        rows = (
            self.db.query(ValueLowlandProfile)
            .filter(ValueLowlandProfile.code.in_(codes))
            .all()
        )
        profile_by_code = {
            str(row.code).zfill(6): row
            for row in rows
        }
        applied = 0
        for candidate in candidates:
            model = profile_by_code.get(candidate.code)
            if model is None:
                continue
            profile = self._profile_from_model(model, cached_flag=True)
            if candidate.profile.confidence > profile.confidence:
                continue
            candidate.profile = profile
            candidate.score_breakdown = self._score_candidate(candidate, profile=profile)
            candidate.score = self._total_score(candidate.score_breakdown)
            candidate.reasons = self._build_reasons(candidate)
            candidate.risk_notes = self._build_risk_notes(candidate)
            applied += 1
        return applied

    # ── Phase 1 + 2: Multi-stage hard screening ──────────────────────────────────

    def _build_hard_candidates(
        self,
        *,
        latest_trade_date: date,
        output_limit: int | None,
        full_analysis: bool = False,
    ) -> list[ValueLowlandCandidate]:
        """三阶段管线：

        Phase 1 — 价格/估值过滤（无需财务数据）：加载全部股票，计算区间位置，
                  排除 ST、高位、市值过大、PB/PE 极端值，按价格分排序取 top。
        Phase 2 — 财务过滤：为 Phase 1 前 FINANCIAL_FETCH_LIMIT 只拉财务数据，
                  排除净利润暴跌/深度亏损，按综合分排序返回。
        Phase 3 — （在 screen() 中调用）AI 画像。
        """
        # ── Phase 1: 加载全量数据 ──────────────────────────────────────────
        all_stocks = self._load_all_stock_rows(latest_trade_date)
        if not all_stocks:
            return []

        valuation_map = self._fetch_daily_basic(latest_trade_date)
        price_range_map = self._price_ranges(
            latest_trade_date=latest_trade_date,
            codes=[s.code for s in all_stocks],
        )

        # ── Phase 1: 硬指标过滤 + 初评 ─────────────────────────────────────
        phase1: list[ValueLowlandCandidate] = []
        for stock in all_stocks:
            if self._is_risk_name(stock.name):
                continue

            valuation = valuation_map.get(stock.code, {})
            pr = price_range_map.get(stock.code, {})
            close = self._safe_float(stock.close)
            low = self._safe_float(pr.get("low"))
            high = self._safe_float(pr.get("high"))
            low_pos = self._low_position_ratio(close=close, low=low, high=high)
            drawdown = self._drawdown_pct(close=close, high=high)
            pb = self._safe_float(valuation.get("pb"))
            pe = self._safe_float(valuation.get("pe_ttm"))
            mv = self._safe_float(valuation.get("total_mv") or stock.circ_mv)

            # P3: 严选只保留两年区间内的低位票
            if low_pos is None or low_pos > STRICT_LOW_POSITION_MAX:
                continue
            # P4: 排除市值过大
            if mv is None or mv > EXCLUDE_MCAP_MAX_WAN:
                continue
            # P2: 排除 PB 明显高估
            if pb is not None and pb > EXCLUDE_PB_MAX:
                continue
            # P2: 排除 PE 极端值
            if pe is not None and (pe <= 0 and pb is None) or (pe is not None and pe > EXCLUDE_PE_EXTREME):
                if pb is None or pb > EXCLUDE_PB_MAX:
                    continue

            # P3: 去除近两年已经从低点翻倍的高位票
            if low is not None and close is not None and low > 0 and close >= low * RISEN_2X_FROM_LOW:
                continue

            tags = self._build_initial_tags(stock.industry, low_pos, valuation)

            candidate = ValueLowlandCandidate(
                code=stock.code,
                ts_code=self._to_ts_code(stock.code, stock.market),
                name=stock.name,
                market=stock.market,
                industry=stock.industry,
                close=close,
                trade_date=latest_trade_date,
                circ_mv=self._safe_float(valuation.get("circ_mv") or stock.circ_mv),
                total_mv=mv,
                pe_ttm=pe,
                pb=pb,
                low_position_ratio=low_pos,
                drawdown_from_high_pct=drawdown,
                tags=tags,
            )
            # Phase 1 score: only position + valuation (no financials, no AI)
            candidate.score_breakdown = ValueLowlandScoreBreakdown(
                ownership_score=0,                     # AI 阶段才有
                low_valuation_score=self._low_valuation_score(candidate),
                financial_improvement_score=0,          # Phase 2 才有
                cycle_elasticity_score=self._quick_cycle_score(candidate),
                business_focus_score=0,
                scarcity_score=0,
                risk_penalty=self._phase1_risk_penalty(candidate),
            )
            candidate.score = self._total_score(candidate.score_breakdown)
            candidate.reasons = self._build_reasons(candidate)
            candidate.risk_notes = self._build_risk_notes(candidate)
            phase1.append(candidate)

        phase1.sort(key=lambda item: item.score, reverse=True)
        logger.info("Phase 1: %d stocks pass hard filters (from %d total)",
                     len(phase1), len(all_stocks))

        # ── Phase 2: 财务过滤 ──────────────────────────────────────────────
        financial_batch = phase1 if full_analysis else phase1[:FINANCIAL_FETCH_LIMIT]
        financial_map = self._fetch_financials([item.ts_code for item in financial_batch])

        phase2: list[ValueLowlandCandidate] = []
        for candidate in financial_batch:
            fin = financial_map.get(candidate.code, {})
            np_yoy = self._safe_float(fin.get("netprofit_yoy"))
            roe = self._safe_float(fin.get("roe"))

            # P2: 排除净利润极速崩溃
            if np_yoy is not None and np_yoy < EXCLUDE_NP_YOY_CATASTROPHE:
                continue
            # P2: 排除 ROE 深度亏损
            if roe is not None and roe < EXCLUDE_ROE_DEEP_LOSS:
                continue

            candidate.netprofit_yoy = np_yoy
            candidate.rev_yoy = self._safe_float(fin.get("rev_yoy"))
            candidate.roe = roe
            candidate.grossprofit_margin = self._safe_float(fin.get("grossprofit_margin"))
            if not self._has_financial_improvement(candidate):
                continue

            # Full hard score (still no AI)
            candidate.score_breakdown = ValueLowlandScoreBreakdown(
                ownership_score=0,
                low_valuation_score=self._low_valuation_score(candidate),
                financial_improvement_score=self._financial_score(candidate),
                cycle_elasticity_score=self._quick_cycle_score(candidate),
                business_focus_score=0,
                scarcity_score=0,
                risk_penalty=self._phase2_risk_penalty(candidate),
            )
            candidate.score = self._total_score(candidate.score_breakdown)
            candidate.reasons = self._build_reasons(candidate)
            candidate.risk_notes = self._build_risk_notes(candidate)
            phase2.append(candidate)

        phase2.sort(key=lambda item: item.score, reverse=True)
        logger.info("Phase 2: %d stocks pass financial filters (from %d fetched)",
                     len(phase2), len(financial_batch))
        return phase2 if output_limit is None else phase2[:output_limit]

    # ── Data helpers ────────────────────────────────────────────────────────────

    @dataclass
    class _StockRow:
        code: str = ""
        name: str = ""
        market: str = ""
        industry: str | None = None
        close: Any = None
        circ_mv: Any = None

    def _load_all_stock_rows(self, latest_trade_date: date) -> list[_StockRow]:
        rows = (
            self.db.query(StockDaily, Stock)
            .join(Stock, Stock.code == StockDaily.code)
            .filter(StockDaily.trade_date == latest_trade_date)
            .all()
        )
        return [
            self._StockRow(
                code=str(stock.code).zfill(6),
                name=stock.name or "",
                market=stock.market or "",
                industry=stock.industry,
                close=daily.close,
                circ_mv=daily.circ_mv,
            )
            for daily, stock in rows
        ]

    def _price_ranges(self, *, latest_trade_date: date, codes: list[str]) -> dict[str, dict[str, float | None]]:
        if not codes:
            return {}
        start_date = latest_trade_date - timedelta(days=PRICE_RANGE_LOOKBACK_DAYS)
        rows = (
            self.db.query(StockDaily.code, func.min(StockDaily.low), func.max(StockDaily.high))
            .filter(StockDaily.trade_date >= start_date, StockDaily.code.in_(codes))
            .group_by(StockDaily.code)
            .all()
        )
        return {str(code).zfill(6): {"low": low, "high": high} for code, low, high in rows}

    def _fetch_daily_basic(self, trade_date: date) -> dict[str, dict[str, Any]]:
        if not self.tushare_service.token:
            return {}
        try:
            acquire_tushare_slot("daily_basic")
            df = self.tushare_service.pro.daily_basic(
                trade_date=trade_date.strftime("%Y%m%d"),
                fields="ts_code,trade_date,total_mv,circ_mv,pe_ttm,pb,ps_ttm",
            )
        except Exception as exc:
            logger.warning("获取 daily_basic 失败，估值分降级: %s", exc)
            return {}
        if df is None or df.empty:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for _, row in df.iterrows():
            ts_code = str(row.get("ts_code") or "")
            code = ts_code.split(".")[0] if "." in ts_code else ts_code
            result[str(code).zfill(6)] = {
                "total_mv": row.get("total_mv"),
                "circ_mv": row.get("circ_mv"),
                "pe_ttm": row.get("pe_ttm"),
                "pb": row.get("pb"),
            }
        return result

    def _fetch_financials(self, ts_codes: list[str]) -> dict[str, dict[str, Any]]:
        """从本地缓存获取财务指标，过期自动从 Tushare 月度刷新。"""
        try:
            return self.financial_service.get_or_refresh(ts_codes)
        except Exception as exc:
            logger.warning("获取财务指标失败: %s", exc)
            return {}

    # ── Scoring (principle-aligned) ──────────────────────────────────────────────

    def _score_candidate(
        self,
        candidate: ValueLowlandCandidate,
        *,
        profile: ValueLowlandCompanyProfile,
    ) -> ValueLowlandScoreBreakdown:
        ownership = self._ownership_score(profile)
        low_val = self._low_valuation_score(candidate)
        financial = self._financial_score(candidate)
        cycle = self._cycle_score(candidate, profile)
        focus = max(0.0, min(10.0, (profile.business_focus_score or 0) / 10))
        scarcity = max(0.0, min(10.0, (profile.scarcity_score or 0) / 10))
        penalty = self._risk_penalty(candidate, profile)
        return ValueLowlandScoreBreakdown(
            ownership_score=round(ownership, 2),
            low_valuation_score=round(low_val, 2),
            financial_improvement_score=round(financial, 2),
            cycle_elasticity_score=round(cycle, 2),
            business_focus_score=round(focus, 2),
            scarcity_score=round(scarcity, 2),
            risk_penalty=round(penalty, 2),
        )

    def _ownership_score(self, profile: ValueLowlandCompanyProfile) -> float:
        """P1: 国资委央企 / 省国资委 → 高分；民企 → 0。"""
        if profile.ownership_type == "central_soe":
            return 20
        if profile.ownership_type == "provincial_soe":
            return 18
        if profile.ownership_type == "local_soe":
            return 8
        return 0

    def _low_valuation_score(self, candidate: ValueLowlandCandidate) -> float:
        """P3 + P4: 低位 + 低价 + 小市值。"""
        score = 0.0

        # P3: 区间位置越低越好
        ratio = candidate.low_position_ratio
        if ratio is not None:
            position_score = (1.0 - ratio) * 12.0
            # P3: 高位惩罚（>70% 开始扣分）
            if ratio > LOW_POSITION_PENALTY:
                over = (ratio - LOW_POSITION_PENALTY) / (EXCLUDE_LOW_POS_MAX - LOW_POSITION_PENALTY)
                position_score -= over * abs(LOW_POSITION_PENALTY_MAX)
            score += max(0.0, min(12.0, position_score))

        # P3: 回撤深度加分
        if candidate.drawdown_from_high_pct is not None:
            score += max(0.0, min(4.0, abs(candidate.drawdown_from_high_pct) / 20.0))

        # P4: 小市值加分（单位：万元）
        mv = candidate.total_mv or candidate.circ_mv
        if mv:
            if mv <= MCAP_BONUS_50YI:
                score += 5
            elif mv <= MCAP_BONUS_100YI:
                score += 4
            elif mv <= MCAP_BONUS_200YI:
                score += 3
            elif mv <= MCAP_BONUS_500YI:
                score += 1

        # P3: 低 PB 加分
        if candidate.pb is not None:
            if 0 < candidate.pb <= 1:
                score += 5
            elif candidate.pb <= 1.5:
                score += 4
            elif candidate.pb <= 2.5:
                score += 2

        return max(0.0, min(25.0, score))

    def _financial_score(self, candidate: ValueLowlandCandidate) -> float:
        """P6: 业绩边际改善 — 爆发 > 改善 > 持平 > 微退。"""
        score = 0.0

        np_yoy = candidate.netprofit_yoy
        if np_yoy is not None:
            if np_yoy >= NP_YOY_BURST:
                score += 10  # 爆发式
            elif np_yoy >= NP_YOY_GOOD:
                score += 7   # 良好
            elif np_yoy >= NP_YOY_MARGINAL:
                score += 4   # 边际改善
            elif np_yoy > NP_YOY_WEAK:
                score += 2   # 微退

        rev_yoy = candidate.rev_yoy
        if rev_yoy is not None:
            if rev_yoy >= 20:
                score += 5
            elif rev_yoy >= 10:
                score += 3
            elif rev_yoy >= 0:
                score += 1

        roe = candidate.roe
        if roe is not None:
            if roe >= 10:
                score += 4
            elif roe >= 5:
                score += 2
            elif roe > 0:
                score += 1

        gpm = candidate.grossprofit_margin
        if gpm is not None and gpm >= 20:
            score += 2

        return max(0.0, min(20.0, score))

    @staticmethod
    def _has_financial_improvement(candidate: ValueLowlandCandidate) -> bool:
        return bool(
            (candidate.netprofit_yoy is not None and candidate.netprofit_yoy >= NP_YOY_MARGINAL)
            or (candidate.rev_yoy is not None and candidate.rev_yoy >= 0)
        )

    def _quick_cycle_score(self, candidate: ValueLowlandCandidate) -> float:
        """Phase 1/2 快速周期评分（无需 AI profile）。"""
        score = 0.0
        industry = str(candidate.industry or "")
        if any(kw in industry for kw in CYCLE_INDUSTRY_KEYWORDS):
            score += 7
        if candidate.low_position_ratio is not None and candidate.low_position_ratio <= 0.35:
            score += 3
        return max(0.0, min(10.0, score))

    def _cycle_score(self, candidate: ValueLowlandCandidate, profile: ValueLowlandCompanyProfile) -> float:
        """P5: 周期弹性（AI profile 补充后）。"""
        score = 0.0
        if profile.cycle_type in CYCLE_TYPES:
            score += 10
        industry = str(candidate.industry or "")
        if any(kw in industry for kw in CYCLE_INDUSTRY_KEYWORDS):
            score += 7
        if candidate.low_position_ratio is not None and candidate.low_position_ratio <= 0.35:
            score += 3
        return max(0.0, min(15.0, score))

    def _phase1_risk_penalty(self, candidate: ValueLowlandCandidate) -> float:
        """Phase 1 风险扣分（无财务、无 AI 画像）。"""
        penalty = 0.0
        if self._is_risk_name(candidate.name or ""):
            penalty -= 30
        mv = candidate.total_mv or candidate.circ_mv
        if mv is not None and mv > MCAP_PENALTY_200YI:
            penalty -= 5
        if candidate.pe_ttm is not None and (candidate.pe_ttm <= 0 or candidate.pe_ttm > 120):
            penalty -= 5
        return max(-30.0, min(0.0, penalty))

    def _phase2_risk_penalty(self, candidate: ValueLowlandCandidate) -> float:
        """Phase 2 风险扣分（有财务，无 AI）。"""
        penalty = self._phase1_risk_penalty(candidate)
        if candidate.netprofit_yoy is not None and candidate.netprofit_yoy <= -60:
            penalty -= 8
        return max(-30.0, min(0.0, penalty))

    def _risk_penalty(self, candidate: ValueLowlandCandidate, profile: ValueLowlandCompanyProfile) -> float:
        """P1+P2+P3: 完整风险扣分（含 AI 画像）。"""
        penalty = 0.0

        # P2: ST/退
        if self._is_risk_name(candidate.name or ""):
            penalty -= 40

        # P1: 权属惩罚 — 民企/未知/市县国资
        if profile.ownership_type == "private":
            penalty += COST_OF_PRIVATE
        elif profile.ownership_type == "unknown":
            penalty += COST_OF_UNKNOWN
        elif profile.ownership_type == "local_soe":
            penalty += COST_OF_LOCAL_SOE

        # P3: 高位惩罚
        if candidate.low_position_ratio is not None and candidate.low_position_ratio > 0.85:
            penalty -= 10

        # P2: 财务风险
        if candidate.netprofit_yoy is not None and candidate.netprofit_yoy <= -60:
            penalty -= 10
        elif candidate.netprofit_yoy is not None and candidate.netprofit_yoy < NP_YOY_WEAK:
            penalty -= 5

        # P4: 大市值减分
        mv = candidate.total_mv or candidate.circ_mv
        if mv is not None and mv > MCAP_PENALTY_200YI:
            penalty -= 6

        # P2: PE 异常
        if candidate.pe_ttm is not None and (candidate.pe_ttm <= 0 or candidate.pe_ttm > 120):
            penalty -= 5

        # AI 置信度低
        if profile.confidence and profile.confidence < 50:
            penalty -= 5

        return max(-40.0, min(0.0, penalty))

    @staticmethod
    def _total_score(score: ValueLowlandScoreBreakdown) -> float:
        return round(
            score.ownership_score
            + score.low_valuation_score
            + score.financial_improvement_score
            + score.cycle_elasticity_score
            + score.business_focus_score
            + score.scarcity_score
            + score.risk_penalty,
            2,
        )

    @staticmethod
    def _rank_candidates(candidates: list[ValueLowlandCandidate], *, limit: int | None, prefer_soe: bool) -> list[ValueLowlandCandidate]:
        if not prefer_soe:
            ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
            return ranked if limit is None else ranked[:limit]

        ownership_priority = {
            "central_soe": 0,
            "provincial_soe": 0,
            "local_soe": 1,
            "unknown": 2,
            "private": 3,
        }
        ranked = sorted(
            candidates,
            key=lambda item: (
                ownership_priority.get(item.profile.ownership_type, 2),
                -item.score,
            ),
        )
        return ranked if limit is None else ranked[:limit]

    # ── Evidence search ──────────────────────────────────────────────────────────

    def _profile_from_tushare_static(
        self,
        *,
        code: str,
        name: str,
        industry: str | None,
        ts_code: str | None,
    ) -> dict[str, Any]:
        ts_code = ts_code or self._to_ts_code(code, None)
        basic = self._tushare_basic_profile_map().get(str(ts_code or ""))
        company = self._tushare_company_profile_map().get(str(ts_code or ""))
        if not basic and not company:
            return {
                "ownership_type": "unknown",
                "controller": "unknown",
                "main_business": "",
                "business_focus_score": 0,
                "scarcity_score": 0,
                "cycle_type": self._infer_cycle_type(industry=industry, business_text=""),
                "unique_assets": [],
                "evidence": [],
                "confidence": 0,
                "risk_notes": ["Tushare stock_basic/stock_company 未返回静态画像。"],
            }

        act_name = str((basic or {}).get("act_name") or "").strip()
        act_ent_type = str((basic or {}).get("act_ent_type") or "").strip()
        main_business = str((company or {}).get("main_business") or "").strip()
        business_scope = str((company or {}).get("business_scope") or "").strip()
        introduction = str((company or {}).get("introduction") or "").strip()
        business_text = "\n".join(part for part in (main_business, business_scope, introduction, industry or "") if part)
        ownership_type, confidence, risk_notes = self._infer_ownership_from_tushare(
            controller=act_name,
            enterprise_type=act_ent_type,
        )
        evidence = self._build_tushare_static_evidence(
            ts_code=ts_code,
            name=name,
            basic=basic or {},
            company=company or {},
        )
        return {
            "ownership_type": ownership_type,
            "controller": act_name or act_ent_type or "unknown",
            "main_business": main_business or business_scope or introduction[:300],
            "business_focus_score": 85 if main_business else (65 if business_scope else 30),
            "scarcity_score": self._infer_scarcity_score(business_text),
            "cycle_type": self._infer_cycle_type(industry=industry, business_text=business_text),
            "unique_assets": self._infer_unique_assets(business_text),
            "evidence": evidence,
            "confidence": confidence,
            "risk_notes": risk_notes,
        }

    def _profile_from_official_site(
        self,
        *,
        code: str,
        name: str,
        industry: str | None,
        ts_code: str | None,
        base_result: dict[str, Any],
    ) -> dict[str, Any]:
        del code
        company = self._tushare_company_profile_map().get(str(ts_code or ""))
        website = str((company or {}).get("website") or "").strip()
        if not website:
            return base_result
        pages = self._fetch_official_site_pages(name=name, website=website)
        if not pages:
            return base_result

        evidence = list(base_result.get("evidence") or [])
        for page in pages[:3]:
            evidence.append(
                {
                    "title": f"{name} 官网信息 - {page['title']}",
                    "url": page["url"],
                    "summary": page["text"][:1500],
                    "source": "official_site",
                }
            )

        rule_result = self._infer_ownership_with_rules(name=name, evidence=evidence)
        ownership_type = str(base_result.get("ownership_type") or "unknown")
        confidence = float(base_result.get("confidence") or 0)
        controller = str(base_result.get("controller") or "unknown")
        risk_notes = self._string_list(base_result.get("risk_notes"))

        if rule_result["ownership_type"] != "unknown" and rule_result["confidence"] >= confidence:
            ownership_type = str(rule_result["ownership_type"])
            confidence = float(rule_result["confidence"])
            controller = str(rule_result.get("controller") or controller or "unknown")
            risk_notes = self._string_list(rule_result.get("risk_notes"))
        elif confidence < 50:
            confidence = max(confidence, 45)
            risk_notes = [note for note in risk_notes if "未返回" not in note]
            risk_notes.append("官网资料补充了公司介绍，但未能确认国资层级。")

        main_business = str(base_result.get("main_business") or "").strip()
        site_text = "\n".join(str(page.get("text") or "") for page in pages[:3])
        if not main_business:
            main_business = self._extract_business_summary(site_text)
        business_text = "\n".join(part for part in (main_business, site_text, industry or "") if part)
        return {
            "ownership_type": ownership_type,
            "controller": controller or "unknown",
            "main_business": main_business,
            "business_focus_score": max(
                self._safe_float(base_result.get("business_focus_score")) or 0,
                70 if main_business else 55,
            ),
            "scarcity_score": max(
                self._safe_float(base_result.get("scarcity_score")) or 0,
                self._infer_scarcity_score(business_text),
            ),
            "cycle_type": (
                base_result.get("cycle_type")
                if base_result.get("cycle_type") and base_result.get("cycle_type") != "other"
                else self._infer_cycle_type(industry=industry, business_text=business_text)
            ),
            "unique_assets": self._unique_strings(
                self._string_list(base_result.get("unique_assets")) + self._infer_unique_assets(business_text)
            ),
            "evidence": evidence[:8],
            "confidence": confidence,
            "risk_notes": risk_notes,
        }

    def _fetch_official_site_pages(self, *, name: str, website: str) -> list[dict[str, str]]:
        base_url = self._normalize_official_site_url(website)
        if not base_url:
            return []
        pages: list[dict[str, str]] = []
        visited: set[str] = set()
        for path in OFFICIAL_SITE_PATHS:
            target_url = urljoin(base_url, path)
            if target_url in visited:
                continue
            visited.add(target_url)
            page = self._fetch_official_site_page(name=name, url=target_url)
            if page:
                pages.append(page)
            if len(pages) >= 3:
                break
        return pages

    @staticmethod
    def _normalize_official_site_url(website: str) -> str:
        value = str(website or "").strip()
        if not value:
            return ""
        value = re.split(r"[;；,\s]+", value, maxsplit=1)[0].strip()
        if not re.match(r"^https?://", value, re.I):
            value = f"http://{value}"
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}/"

    @staticmethod
    def _fetch_official_site_page(*, name: str, url: str) -> dict[str, str] | None:
        try:
            response = requests.get(
                url,
                timeout=OFFICIAL_SITE_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                },
                allow_redirects=True,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning("公司官网页面获取失败: name=%s url=%s error=%s", name, url, exc)
            return None
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type and response.text.lstrip()[:1] != "<":
            return None
        raw_html = response.text[:OFFICIAL_SITE_MAX_BYTES]
        title_match = re.search(r"<title>(.*?)</title>", raw_html, re.S | re.I)
        title = ValueLowlandService._clean_html_text(title_match.group(1)) if title_match else url
        body_html = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", "", raw_html, flags=re.S | re.I)
        text = ValueLowlandService._clean_html_text(body_html)
        if not ValueLowlandService._is_relevant_official_site_page(name=name, title=title, text=text):
            return None
        summary = ValueLowlandService._extract_relevant_text(name=name, text=text)
        if not summary:
            return None
        return {"title": title[:120] or url, "url": response.url or url, "text": summary}

    @staticmethod
    def _is_relevant_official_site_page(*, name: str, title: str, text: str) -> bool:
        stock_name = re.sub(r"\s+", "", str(name or ""))
        haystack = re.sub(r"\s+", "", f"{title}\n{text[:3000]}")
        if not stock_name:
            return False
        aliases = {
            stock_name,
            stock_name.removesuffix("股份"),
            stock_name.removesuffix("集团"),
            stock_name.removesuffix("科技"),
        }
        aliases.discard("")
        return any(len(alias) >= 3 and alias in haystack for alias in aliases)

    @staticmethod
    def _extract_relevant_text(*, name: str, text: str) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return ""
        keywords = (
            name,
            "公司简介",
            "集团简介",
            "关于我们",
            "主营业务",
            "经营范围",
            "控股股东",
            "实际控制人",
            "国资委",
            "核心产品",
            "核心技术",
        )
        snippets: list[str] = []
        for keyword in keywords:
            if not keyword:
                continue
            index = normalized.find(keyword)
            if index >= 0:
                start = max(0, index - 120)
                end = min(len(normalized), index + 900)
                snippets.append(normalized[start:end])
        if not snippets:
            snippets.append(normalized[:1200])
        return " ".join(ValueLowlandService._unique_strings(snippets))[:1800]

    @staticmethod
    def _extract_business_summary(text: str) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        for keyword in ("主营业务", "经营范围", "核心产品", "产品包括", "业务涵盖", "主要从事"):
            index = normalized.find(keyword)
            if index >= 0:
                return normalized[index : index + 300]
        return normalized[:300]

    def _profile_from_wikipedia(
        self,
        *,
        code: str,
        name: str,
        industry: str | None,
        base_result: dict[str, Any],
    ) -> dict[str, Any]:
        page = self._fetch_wikipedia_page(name=name)
        if page is None:
            return base_result

        title = str(page.get("title") or name)
        extract = str(page.get("extract") or "").strip()
        source = str(page.get("source") or "wikipedia")
        url_title = str(page.get("url_title") or title).replace(" ", "_")
        page_url = str(page.get("url") or f"{WIKIPEDIA_PAGE_URL}{url_title}")
        evidence = list(base_result.get("evidence") or [])
        evidence.append(
            {
                "title": f"{title} - {'百度百科' if source == 'baidu_baike' else '维基百科'}",
                "url": page_url,
                "summary": extract[:1500],
                "source": source,
            }
        )

        wiki_text = self._normalize_rule_text(f"{title}\n{extract}")
        rule_result = self._infer_ownership_with_rules(name=name, evidence=evidence)
        ownership_type = str(base_result.get("ownership_type") or "unknown")
        confidence = float(base_result.get("confidence") or 0)
        controller = str(base_result.get("controller") or "unknown")
        risk_notes = self._string_list(base_result.get("risk_notes"))

        if rule_result["ownership_type"] != "unknown" and rule_result["confidence"] >= confidence:
            ownership_type = str(rule_result["ownership_type"])
            confidence = float(rule_result["confidence"])
            controller = str(rule_result.get("controller") or controller or "unknown")
            risk_notes = self._string_list(rule_result.get("risk_notes"))
        elif extract and confidence < 50:
            confidence = max(confidence, 45)
            risk_notes = [note for note in risk_notes if "未返回" not in note]
            risk_notes.append("百科资料补充了公司摘要，但未能确认国资层级。")

        main_business = str(base_result.get("main_business") or "").strip()
        if not main_business and extract:
            main_business = extract[:300]
        business_text = "\n".join(part for part in (main_business, extract, industry or "") if part)
        return {
            "ownership_type": ownership_type,
            "controller": controller or "unknown",
            "main_business": main_business,
            "business_focus_score": max(
                self._safe_float(base_result.get("business_focus_score")) or 0,
                55 if extract else 0,
            ),
            "scarcity_score": max(
                self._safe_float(base_result.get("scarcity_score")) or 0,
                self._infer_scarcity_score(business_text),
            ),
            "cycle_type": (
                base_result.get("cycle_type")
                if base_result.get("cycle_type") and base_result.get("cycle_type") != "other"
                else self._infer_cycle_type(industry=industry, business_text=business_text)
            ),
            "unique_assets": self._unique_strings(
                self._string_list(base_result.get("unique_assets")) + self._infer_unique_assets(business_text)
            ),
            "evidence": evidence[:8],
            "confidence": confidence,
            "risk_notes": risk_notes,
        }

    def _fetch_wikipedia_page(self, *, name: str) -> dict[str, Any] | None:
        query = str(name or "").strip()
        if not query:
            return None
        candidates = [query, f"{query} 公司", f"{query}股份"]
        for term in candidates:
            title = self._wikipedia_search_title(term)
            if not title:
                continue
            page = self._wikipedia_page_extract(title)
            if page and self._is_relevant_wikipedia_page(name=name, page=page):
                return page
        return self._fetch_baidu_baike_page(name=name)

    @staticmethod
    def _fetch_baidu_baike_page(*, name: str) -> dict[str, Any] | None:
        query = str(name or "").strip()
        if not query:
            return None
        url = f"{BAIDU_BAIKE_PAGE_URL}{quote(query)}"
        try:
            response = requests.get(
                url,
                timeout=ENCYCLOPEDIA_TIMEOUT_SECONDS,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
            )
            response.raise_for_status()
            raw_html = response.text
        except Exception as exc:
            logger.warning("百度百科页面获取失败: name=%s error=%s", query, exc)
            return None

        compact_html = re.sub(r"\s+", "", raw_html)
        if query not in compact_html[:20000]:
            return None
        title_match = re.search(r"<title>(.*?)</title>", raw_html, re.S | re.I)
        desc_match = re.search(
            r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\'](.*?)["\']',
            raw_html,
            re.S | re.I,
        )
        title = query
        if title_match:
            title = re.sub(r"_百度百科.*$", "", ValueLowlandService._clean_html_text(title_match.group(1))) or query
        description = ValueLowlandService._clean_html_text(desc_match.group(1)) if desc_match else ""
        if not description:
            body_html = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw_html, flags=re.S | re.I)
            body_text = ValueLowlandService._clean_html_text(body_html)
            index = body_text.find(query)
            description = body_text[index : index + 800] if index >= 0 else body_text[:800]
        page = {
            "title": title,
            "url": url,
            "url_title": query,
            "extract": description[:1500],
            "source": "baidu_baike",
        }
        if not page["extract"]:
            return None
        return page if ValueLowlandService._is_relevant_wikipedia_page(name=name, page=page) else None

    @staticmethod
    def _is_relevant_wikipedia_page(*, name: str, page: dict[str, Any]) -> bool:
        stock_name = re.sub(r"\s+", "", str(name or ""))
        title = re.sub(r"\s+", "", str(page.get("title") or ""))
        extract = re.sub(r"\s+", "", str(page.get("extract") or ""))
        if not stock_name or not title:
            return False
        if stock_name in title or stock_name in extract[:500]:
            return True
        aliases = {
            stock_name.removesuffix("股份"),
            stock_name.removesuffix("集团"),
            stock_name.removesuffix("科技"),
        }
        aliases.discard("")
        return any(len(alias) >= 4 and (alias in title or alias in extract[:500]) for alias in aliases)

    @staticmethod
    def _wikipedia_search_title(query: str) -> str | None:
        try:
            response = requests.get(
                WIKIPEDIA_API_URL,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": 1,
                    "format": "json",
                    "utf8": 1,
                },
                timeout=ENCYCLOPEDIA_TIMEOUT_SECONDS,
                headers={"User-Agent": "StockTradebyZ/1.0 value-lowland profile cache"},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("Wikipedia 搜索失败: query=%s error=%s", query, exc)
            return None
        results = data.get("query", {}).get("search", []) if isinstance(data, dict) else []
        if not results:
            return None
        title = str(results[0].get("title") or "").strip()
        return title or None

    @staticmethod
    def _wikipedia_page_extract(title: str) -> dict[str, Any] | None:
        try:
            response = requests.get(
                WIKIPEDIA_API_URL,
                params={
                    "action": "query",
                    "prop": "extracts",
                    "exintro": 1,
                    "explaintext": 1,
                    "redirects": 1,
                    "titles": title,
                    "format": "json",
                    "utf8": 1,
                },
                timeout=ENCYCLOPEDIA_TIMEOUT_SECONDS,
                headers={"User-Agent": "StockTradebyZ/1.0 value-lowland profile cache"},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("Wikipedia 页面获取失败: title=%s error=%s", title, exc)
            return None
        pages = data.get("query", {}).get("pages", {}) if isinstance(data, dict) else {}
        if not isinstance(pages, dict):
            return None
        for page in pages.values():
            if not isinstance(page, dict) or page.get("missing") is not None:
                continue
            extract = str(page.get("extract") or "").strip()
            page_title = str(page.get("title") or title).strip()
            if extract:
                return {"title": page_title, "url_title": page_title, "extract": extract, "source": "wikipedia"}
        return None

    @staticmethod
    def _clean_html_text(value: str) -> str:
        text = html.unescape(str(value or ""))
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _tushare_basic_profile_map(self) -> dict[str, dict[str, Any]]:
        if self._tushare_basic_profile_cache is not None:
            return self._tushare_basic_profile_cache
        self._tushare_basic_profile_cache = {}
        if not self.tushare_service.token:
            return self._tushare_basic_profile_cache
        try:
            acquire_tushare_slot("stock_basic")
            df = self.tushare_service.pro.stock_basic(
                exchange="",
                list_status="L",
                fields="ts_code,name,area,industry,market,exchange,list_date,act_name,act_ent_type",
            )
        except Exception as exc:
            logger.warning("Tushare stock_basic 静态画像获取失败: %s", exc)
            return self._tushare_basic_profile_cache
        if df is None or df.empty:
            return self._tushare_basic_profile_cache
        self._tushare_basic_profile_cache = {
            str(row.get("ts_code") or ""): row.to_dict()
            for _, row in df.iterrows()
            if row.get("ts_code")
        }
        return self._tushare_basic_profile_cache

    def _tushare_company_profile_map(self) -> dict[str, dict[str, Any]]:
        if self._tushare_company_profile_cache is not None:
            return self._tushare_company_profile_cache
        self._tushare_company_profile_cache = {}
        if not self.tushare_service.token:
            return self._tushare_company_profile_cache
        fields = (
            "ts_code,chairman,manager,secretary,reg_capital,setup_date,province,city,"
            "introduction,website,main_business,business_scope"
        )
        for exchange in ("SSE", "SZSE", "BSE"):
            try:
                acquire_tushare_slot("stock_company")
                df = self.tushare_service.pro.stock_company(exchange=exchange, fields=fields)
            except Exception as exc:
                logger.warning("Tushare stock_company 静态画像获取失败: exchange=%s error=%s", exchange, exc)
                continue
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                ts_code = str(row.get("ts_code") or "")
                if ts_code:
                    self._tushare_company_profile_cache[ts_code] = row.to_dict()
        return self._tushare_company_profile_cache

    @staticmethod
    def _infer_ownership_from_tushare(*, controller: str, enterprise_type: str) -> tuple[str, float, list[str]]:
        text = ValueLowlandService._normalize_rule_text(f"{controller}\n{enterprise_type}")
        if any(
            token in text
            for token in (
                "国务院国资委",
                "国务院国有资产监督管理委员会",
                "中央企业",
                "央企",
                "中国电子科技集团有限公司",
                "中国航空发动机集团有限公司",
                "中国航发",
            )
        ):
            return "central_soe", 95, []
        if any(
            token in text
            for token in (
                "省国资委",
                "省国有资产监督管理委员会",
                "省人民政府国有资产监督管理委员会",
                "自治区国资委",
                "自治区国有资产监督管理委员会",
                "自治区人民政府国有资产监督管理委员会",
            )
        ):
            return "provincial_soe", 90, []
        if any(
            token in text
            for token in (
                "市国资委",
                "市国有资产监督管理委员会",
                "市人民政府国有资产监督管理委员会",
                "市人民政府国有资产监督管理局",
                "区国资委",
                "区国有资产监督管理委员会",
                "区国有资产管理局",
                "新区国有资产管理局",
                "县国资委",
                "县国有资产监督管理委员会",
                "县人民政府国有资产监督管理局",
            )
        ):
            return "local_soe", 80, ["Tushare 实控人显示为市县区级国资，不纳入核心央企/省国资池。"]
        if any(token in text for token in ("地方国有企业", "国有企业", "国资")):
            return "local_soe", 70, ["Tushare 企业性质显示国资，但层级未明确到央企/省国资。"]
        if any(token in text for token in ("民营", "自然人", "个人", "外资", "公众企业")):
            return "private", 85, ["Tushare 实控人企业性质显示非国资背景。"]
        if controller or enterprise_type:
            return "unknown", 45, ["Tushare 返回了实控人信息，但无法规则确认国资层级。"]
        return "unknown", 0, ["Tushare 未返回实控人信息。"]

    @staticmethod
    def _build_tushare_static_evidence(
        *,
        ts_code: str | None,
        name: str,
        basic: dict[str, Any],
        company: dict[str, Any],
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        if basic:
            evidence.append(
                {
                    "title": f"{name} Tushare 股票基础信息",
                    "url": "",
                    "summary": "；".join(
                        part
                        for part in (
                            f"TS代码 {ts_code}" if ts_code else "",
                            f"实控人 {basic.get('act_name')}" if basic.get("act_name") else "",
                            f"企业性质 {basic.get('act_ent_type')}" if basic.get("act_ent_type") else "",
                            f"行业 {basic.get('industry')}" if basic.get("industry") else "",
                            f"地域 {basic.get('area')}" if basic.get("area") else "",
                        )
                        if part
                    ),
                    "source": "tushare.stock_basic",
                }
            )
        if company:
            evidence.append(
                {
                    "title": f"{name} Tushare 上市公司基本信息",
                    "url": "",
                    "summary": "；".join(
                        part
                        for part in (
                            f"主营 {company.get('main_business')}" if company.get("main_business") else "",
                            f"经营范围 {company.get('business_scope')}" if company.get("business_scope") else "",
                            f"公司介绍 {company.get('introduction')}" if company.get("introduction") else "",
                        )
                        if part
                    )[:1500],
                    "source": "tushare.stock_company",
                }
            )
        return evidence

    @staticmethod
    def _infer_cycle_type(*, industry: str | None, business_text: str) -> str:
        text = f"{industry or ''}\n{business_text}"
        if any(token in text for token in ("矿", "煤", "铁", "铜", "铝", "锂", "稀土", "钨", "金属", "资源")):
            return "resource"
        if any(token in text for token in ("化工", "化学", "树脂", "材料", "农药", "化肥")):
            return "chemical"
        if any(token in text for token in ("军工", "航天", "航空", "兵器", "国防")):
            return "military"
        if any(token in text for token in ("电力", "煤炭", "石油", "天然气", "能源", "风电", "光伏")):
            return "energy"
        if any(token in text for token in ("水务", "燃气", "供热", "环保", "公用")):
            return "utility"
        return "other"

    @staticmethod
    def _infer_scarcity_score(text: str) -> float:
        score = 0.0
        if any(token in text for token in ("矿山", "矿产", "采矿", "资源", "稀土", "钨", "锂", "铜", "铁矿")):
            score += 45
        if any(token in text for token in ("牌照", "特许经营", "专营", "许可", "资质")):
            score += 25
        if any(token in text for token in ("核心技术", "专利", "国内领先", "龙头", "唯一", "稀缺")):
            score += 20
        return max(0.0, min(90.0, score))

    @staticmethod
    def _infer_unique_assets(text: str) -> list[str]:
        assets: list[str] = []
        for label, tokens in (
            ("矿产/资源资产", ("矿山", "矿产", "铁矿", "煤矿", "稀土", "锂", "铜", "钨")),
            ("牌照/特许经营", ("牌照", "特许经营", "专营", "许可")),
            ("军工/航天资质", ("军工", "航天", "兵器", "国防")),
            ("公用事业资产", ("水务", "燃气", "供热", "电力")),
        ):
            if any(token in text for token in tokens):
                assets.append(label)
        return assets[:5]

    def _search_ownership_evidence(self, *, name: str, ts_code: str | None) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = self._fetch_tushare_announcement_evidence(ts_code=ts_code)
        return evidence[:10]

    def _search_company_evidence(
        self,
        *,
        name: str,
        ts_code: str | None,
        initial_evidence: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """P1+P5+P6 导向的搜索词；权属证据已先做规则预判。"""
        evidence: list[dict[str, Any]] = list(initial_evidence or self._fetch_tushare_announcement_evidence(ts_code=ts_code))
        return evidence[:15]

    def _infer_ownership_with_rules(self, *, name: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        joined = "\n".join(
            f"{item.get('title') or ''}\n{item.get('summary') or ''}\n{item.get('source') or ''}"
            for item in evidence
            if isinstance(item, dict)
        )
        text = self._normalize_rule_text(f"{name}\n{joined}")
        matched_evidence = self._evidence_with_text(evidence)

        central_patterns = (
            r"国务院国有资产监督管理委员会",
            r"国务院国资委",
            r"中央企业",
            r"央企",
            r"中国电子科技集团有限公司",
            r"中国航空发动机集团有限公司",
            r"中国航发",
        )
        provincial_patterns = (
            r"省国有资产监督管理委员会",
            r"省国资委",
            r"省人民政府国有资产监督管理委员会",
            r"自治区国有资产监督管理委员会",
            r"自治区国资委",
            r"自治区人民政府国有资产监督管理委员会",
            r"直辖市国有资产监督管理委员会",
        )
        local_patterns = (
            r"市国有资产监督管理委员会",
            r"市国资委",
            r"市人民政府国有资产监督管理委员会",
            r"市人民政府国有资产监督管理局",
            r"区国有资产监督管理委员会",
            r"区国资委",
            r"区国有资产管理局",
            r"新区国有资产管理局",
            r"县国有资产监督管理委员会",
            r"县国资委",
            r"县人民政府国有资产监督管理局",
        )
        private_patterns = (
            r"实际控制人为自然人",
            r"实际控制人.*自然人",
            r"民营企业",
            r"民营控股",
            r"家族控制",
            r"私营企业",
        )

        if self._matches_any(text, central_patterns):
            return {
                "ownership_type": "central_soe",
                "controller": self._extract_controller_text(text, fallback="国务院国资委/中央企业"),
                "confidence": 90,
                "risk_notes": [],
                "evidence": matched_evidence,
            }
        if self._matches_any(text, provincial_patterns):
            return {
                "ownership_type": "provincial_soe",
                "controller": self._extract_controller_text(text, fallback="省级国资委"),
                "confidence": 85,
                "risk_notes": [],
                "evidence": matched_evidence,
            }
        if self._matches_any(text, local_patterns):
            return {
                "ownership_type": "local_soe",
                "controller": self._extract_controller_text(text, fallback="地方国资委"),
                "confidence": 78,
                "risk_notes": ["仅命中市县区级国资，不属于核心央企/省国资池。"],
                "evidence": matched_evidence,
            }
        if self._matches_any(text, private_patterns):
            return {
                "ownership_type": "private",
                "controller": self._extract_controller_text(text, fallback="民营/自然人控制"),
                "confidence": 80,
                "risk_notes": ["规则证据显示为民企或自然人控制，不纳入核心严选。"],
                "evidence": matched_evidence,
            }

        return {
            "ownership_type": "unknown",
            "controller": "unknown",
            "confidence": 0,
            "risk_notes": ["权属规则证据不足，需 AI 或人工复核。"],
            "evidence": matched_evidence,
        }

    def _profile_from_rule_result(
        self,
        rule_result: dict[str, Any],
        *,
        fallback_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        evidence = rule_result.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            evidence = fallback_evidence
        return {
            "ownership_type": rule_result.get("ownership_type") or "unknown",
            "controller": rule_result.get("controller") or "unknown",
            "main_business": "",
            "business_focus_score": 0,
            "scarcity_score": 0,
            "cycle_type": "other",
            "unique_assets": [],
            "evidence": [
                {
                    "title": str(item.get("title") or "").strip(),
                    "url": str(item.get("url") or "").strip(),
                    "summary": str(item.get("summary") or "").strip(),
                    "source": item.get("source"),
                    "published_at": item.get("published_at"),
                }
                for item in evidence
                if isinstance(item, dict) and (item.get("title") or item.get("summary") or item.get("url"))
            ][:5],
            "confidence": self._bounded_float(rule_result.get("confidence"), 0, 100),
            "risk_notes": self._string_list(rule_result.get("risk_notes")),
        }

    @staticmethod
    def _normalize_rule_text(value: str) -> str:
        return re.sub(r"\s+", "", str(value or ""))

    @staticmethod
    def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text) for pattern in patterns)

    @staticmethod
    def _extract_controller_text(text: str, *, fallback: str) -> str:
        for keyword in ("实际控制人", "控股股东", "最终控制方", "控制人"):
            index = text.find(keyword)
            if index >= 0:
                return text[index : index + 80]
        return fallback

    @staticmethod
    def _evidence_with_text(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            item
            for item in evidence
            if isinstance(item, dict) and (item.get("title") or item.get("summary") or item.get("url"))
        ][:5]

    def _fetch_tushare_announcement_evidence(self, *, ts_code: str | None) -> list[dict[str, Any]]:
        if not ts_code:
            return []
        end_date = utc_now().strftime("%Y%m%d")
        start_date = (utc_now() - timedelta(days=365)).strftime("%Y%m%d")
        items = self.tushare_service.get_announcements(
            ts_code,
            start_date=start_date,
            end_date=end_date,
            limit=8,
        )
        evidence: list[dict[str, Any]] = []
        for item in items:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            evidence.append(
                {
                    "title": title,
                    "url": str(item.get("url") or "").strip(),
                    "summary": f"Tushare 公告摘要，公告日期 {item.get('ann_date') or '-'}。",
                    "published_at": str(item.get("ann_date") or ""),
                    "source": "tushare_anns_d",
                }
            )
        return evidence

    # ── AI inference ─────────────────────────────────────────────────────────────

    def _infer_company_profile_with_ai(
        self,
        *,
        code: str,
        name: str,
        industry: str | None,
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        context = json.dumps(evidence, ensure_ascii=False)[:14000]
        system_prompt = (
            "你是A股价值洼地筛选器的公司画像分析助手。"
            "筛选原则：1)只关注国务院国资委央企/省国资委国企，民企不是核心标的；"
            "2)排除ST/退市/持续亏损/业绩崩溃股票；"
            "3)买在低位低价，避免已涨2-3倍的高位股；"
            "4)市值<200亿优先，越小越有弹性；"
            "5)主营集中、业务简单、产品稀缺不可替代；"
            "6)业绩边际改善，最好有爆发式增长或周期价格驱动。"
            "只允许基于用户提供的Tushare基础信息和搜索证据判断，"
            "证据不足时必须返回 unknown 或低置信度。输出 JSON object，不输出 markdown。"
        )
        user_prompt = (
            f"股票代码：{code}\n公司名称：{name}\n行业：{industry or ''}\n"
            f"搜索证据：{context}\n"
            "请按原则输出固定JSON字段："
            '{"ownership_type":"central_soe|provincial_soe|local_soe|private|unknown",'
            '"controller":"实际控制人（含持股路径说明）或unknown","main_business":"主营业务",'
            '"business_focus_score":0-100,"scarcity_score":0-100,'
            '"cycle_type":"resource|chemical|military|energy|utility|other",'
            '"unique_assets":["稀缺资源/牌照/产能/区域优势"],'
            '"earnings_trend":"improving|stable|declining|unknown",'
            '"evidence":[{"title":"string","url":"string","summary":"string"}],'
            '"confidence":0-100,"risk_notes":["string"]}。'
            "evidence 中必须引用输入证据里的URL；没有URL则不要编造。"
            "earnings_trend 用来判断 P6 业绩改善是否成立。"
        )
        try:
            result = self.deepseek_service.infer_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
            )
        except Exception as exc:
            logger.warning("AI 公司画像失败: code=%s error=%s", code, exc)
            result = {}
        return self._normalize_ai_profile(result, fallback_evidence=evidence)

    def _normalize_ai_profile(self, result: dict[str, Any], *, fallback_evidence: list[dict[str, Any]]) -> dict[str, Any]:
        allowed_ownership = SOE_TYPES | {"local_soe", "private", "unknown"}
        allowed_cycle = CYCLE_TYPES | {"other"}
        evidence = result.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
        normalized_evidence = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            normalized_evidence.append(
                {
                    "title": str(item.get("title") or "").strip(),
                    "url": url,
                    "summary": str(item.get("summary") or "").strip(),
                }
            )
        if not normalized_evidence:
            normalized_evidence = [
                {
                    "title": str(item.get("title") or "").strip(),
                    "url": str(item.get("url") or "").strip(),
                    "summary": str(item.get("summary") or "").strip(),
                    "source": item.get("source"),
                    "published_at": item.get("published_at"),
                }
                for item in fallback_evidence
                if str(item.get("url") or "").strip()
            ][:5]

        confidence = self._bounded_float(result.get("confidence"), 0, 100)
        if not normalized_evidence:
            confidence = min(confidence, 30)

        return {
            "ownership_type": result.get("ownership_type") if result.get("ownership_type") in allowed_ownership else "unknown",
            "controller": str(result.get("controller") or "unknown"),
            "main_business": str(result.get("main_business") or ""),
            "business_focus_score": self._bounded_float(result.get("business_focus_score"), 0, 100),
            "scarcity_score": self._bounded_float(result.get("scarcity_score"), 0, 100),
            "cycle_type": result.get("cycle_type") if result.get("cycle_type") in allowed_cycle else "other",
            "unique_assets": self._string_list(result.get("unique_assets")),
            "evidence": normalized_evidence,
            "confidence": confidence,
            "risk_notes": self._string_list(result.get("risk_notes")),
        }

    def _upsert_profile_cache(
        self,
        *,
        code: str,
        result: dict[str, Any],
        evidence: list[dict[str, Any]],
        now: datetime,
    ) -> ValueLowlandProfile:
        model = self.db.query(ValueLowlandProfile).filter(ValueLowlandProfile.code == code).first()
        if model is not None and self._is_profile_cache_usable(model):
            return model
        if model is None:
            model = ValueLowlandProfile(code=code)
            self.db.add(model)
        model.ownership_type = str(result.get("ownership_type") or "unknown")
        model.controller = str(result.get("controller") or "")
        model.main_business = str(result.get("main_business") or "")
        model.business_focus_score = self._safe_float(result.get("business_focus_score"))
        model.scarcity_score = self._safe_float(result.get("scarcity_score"))
        model.cycle_type = str(result.get("cycle_type") or "other")
        model.unique_assets_json = result.get("unique_assets") or []
        model.evidence_json = result.get("evidence") or []
        model.confidence = self._safe_float(result.get("confidence")) or 0
        model.risk_notes_json = result.get("risk_notes") or []
        model.raw_result_json = {
            "static_profile": result,
            "web_evidence": evidence,
            "cache_policy": "permanent_static_profile",
            "note": "权属、实控人、主营、资源属性等静态画像永久固化；财务/行情数据不写入此缓存。",
        }
        model.searched_at = now
        model.analyzed_at = now
        model.expires_at = None
        self.db.commit()
        self.db.refresh(model)
        return model

    def _profile_from_model(self, model: ValueLowlandProfile, *, cached_flag: bool) -> ValueLowlandCompanyProfile:
        return ValueLowlandCompanyProfile(
            ownership_type=model.ownership_type or "unknown",
            controller=model.controller,
            main_business=model.main_business,
            business_focus_score=float(model.business_focus_score or 0),
            scarcity_score=float(model.scarcity_score or 0),
            cycle_type=model.cycle_type or "other",
            unique_assets=self._string_list(model.unique_assets_json),
            evidence=[ValueLowlandEvidence(**item) for item in (model.evidence_json or []) if isinstance(item, dict)],
            confidence=float(model.confidence or 0),
            risk_notes=self._string_list(model.risk_notes_json),
            cached=cached_flag,
            expires_at=None if self._is_profile_cache_usable(model) else model.expires_at,
        )

    @staticmethod
    def _should_refresh_profile(model: ValueLowlandProfile) -> bool:
        confidence = float(model.confidence or 0)
        return confidence < 50

    @classmethod
    def _is_profile_cache_usable(cls, model: ValueLowlandProfile) -> bool:
        """Static company profiles do not expire once a useful result is stored."""
        return not cls._should_refresh_profile(model)

    def _unknown_profile(self, note: str) -> ValueLowlandCompanyProfile:
        return ValueLowlandCompanyProfile(
            ownership_type="unknown",
            controller="unknown",
            confidence=0,
            risk_notes=[note],
        )

    def _build_reasons(self, candidate: ValueLowlandCandidate) -> list[str]:
        reasons: list[str] = []
        if candidate.low_position_ratio is not None:
            reasons.append(f"两年区间位置 {candidate.low_position_ratio:.2f}")
        if candidate.pb is not None:
            reasons.append(f"PB {candidate.pb:.2f}")
        elif candidate.pe_ttm is not None:
            reasons.append(f"PE(TTM) {candidate.pe_ttm:.1f}")
        if candidate.netprofit_yoy is not None and candidate.netprofit_yoy >= 0:
            reasons.append(f"净利润同比 {candidate.netprofit_yoy:.1f}%")
        if candidate.profile.ownership_type in SOE_TYPES:
            reasons.append(f"国资属性 {candidate.profile.ownership_type}")
        if candidate.profile.unique_assets:
            reasons.append(f"稀缺资产：{'、'.join(candidate.profile.unique_assets[:2])}")
        if not reasons:
            reasons.append("本地硬筛入围，需补充估值/画像证据")
        return reasons[:5]

    def _build_risk_notes(self, candidate: ValueLowlandCandidate) -> list[str]:
        notes = list(candidate.profile.risk_notes or [])
        if candidate.pb is None and candidate.pe_ttm is None:
            notes.append("未获取到 PB/PE，估值分使用市值和位置降级计算。")
        if candidate.profile.confidence < 50:
            notes.append("AI 画像证据不足，需人工复核。")
        if candidate.netprofit_yoy is not None and candidate.netprofit_yoy < 0:
            notes.append(f"净利润同比为负：{candidate.netprofit_yoy:.1f}%")
        return list(dict.fromkeys(notes))[:5]

    def _build_initial_tags(self, industry: Any, low_position: float | None, valuation: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        text = str(industry or "")
        if any(keyword in text for keyword in CYCLE_INDUSTRY_KEYWORDS):
            tags.append("周期/资源")
        if low_position is not None and low_position <= 0.35:
            tags.append("低位")
        pb = self._safe_float(valuation.get("pb"))
        if pb is not None and pb <= 1.5:
            tags.append("低PB")
        return tags

    def _is_cycle_candidate(self, candidate: ValueLowlandCandidate) -> bool:
        return self._is_cycle_candidate_static(candidate)

    @staticmethod
    def _is_cycle_candidate_static(candidate: ValueLowlandCandidate) -> bool:
        return candidate.profile.cycle_type in STRICT_DISPLAY_CYCLE_TYPES

    @staticmethod
    def _is_earnings_reversal(candidate: ValueLowlandCandidate) -> bool:
        return bool(
            (candidate.netprofit_yoy is not None and candidate.netprofit_yoy >= 15)
            or (candidate.rev_yoy is not None and candidate.rev_yoy >= 10)
        )

    @staticmethod
    def _to_ts_code(code: str, market: Any) -> str:
        suffix = str(market or "").upper()
        if suffix in {"SH", "SZ", "BJ"}:
            return f"{str(code).zfill(6)}.{suffix}"
        if str(code).startswith(("60", "68", "90")):
            return f"{str(code).zfill(6)}.SH"
        if str(code).startswith(("00", "30", "20")):
            return f"{str(code).zfill(6)}.SZ"
        if str(code).startswith(("43", "83", "87", "92")):
            return f"{str(code).zfill(6)}.BJ"
        return str(code).zfill(6)

    @classmethod
    def _is_risk_name(cls, name: str) -> bool:
        text = str(name or "").upper()
        return any(keyword in text for keyword in ST_NAME_KEYWORDS)

    @staticmethod
    def _low_position_ratio(*, close: float | None, low: float | None, high: float | None) -> float | None:
        if close is None or low is None or high is None or high <= low:
            return None
        return round(max(0.0, min(1.0, (close - low) / (high - low))), 4)

    @staticmethod
    def _drawdown_pct(*, close: float | None, high: float | None) -> float | None:
        if close is None or high is None or high <= 0:
            return None
        return round((close / high - 1) * 100, 2)

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
            result = float(value)
            if math.isnan(result) or math.isinf(result):
                return None
            return result
        except (TypeError, ValueError):
            return None

    @classmethod
    def _bounded_float(cls, value: Any, low: float, high: float) -> float:
        parsed = cls._safe_float(value)
        if parsed is None:
            return low
        return max(low, min(high, parsed))

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _unique_strings(value: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _load_deepseek_api_key(self) -> str:
        value = self.db.query(Config.value).filter(Config.key == "deepseek_api_key").scalar()
        return str(value or "").strip()

    def _build_response_message(self, *, enrich: bool) -> str:
        if enrich:
            return "已执行 Phase1 价格过滤 → Phase2 财务过滤 → Tushare/官网/百科静态画像补全。"
        return "已执行多阶段硬筛（价格→财务→AI画像）按六原则排序。"
