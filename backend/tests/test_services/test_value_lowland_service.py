from __future__ import annotations

import pytest

from app.schemas import ValueLowlandCandidate, ValueLowlandCompanyProfile
from app.services.value_lowland_service import ValueLowlandService


class _DummyQuery:
    def filter(self, *args, **kwargs):
        return self

    def scalar(self):
        return ""


class _DummyDb:
    def query(self, *args, **kwargs):
        return _DummyQuery()


class _ProfileModel:
    def __init__(self, ownership_type: str, confidence: float):
        self.ownership_type = ownership_type
        self.confidence = confidence


def _service() -> ValueLowlandService:
    return ValueLowlandService(_DummyDb())


def _candidate(**overrides) -> ValueLowlandCandidate:
    data = {
        "code": "600000",
        "ts_code": "600000.SH",
        "name": "样例股份",
        "market": "SH",
        "industry": "煤炭开采",
        "close": 8.0,
        "total_mv": 800_000,
        "circ_mv": 700_000,
        "pe_ttm": 12.0,
        "pb": 0.9,
        "low_position_ratio": 0.2,
        "drawdown_from_high_pct": -45.0,
        "roe": 8.0,
        "netprofit_yoy": 30.0,
        "rev_yoy": 12.0,
        "grossprofit_margin": 25.0,
    }
    data.update(overrides)
    return ValueLowlandCandidate(**data)


def _profile(**overrides) -> ValueLowlandCompanyProfile:
    data = {
        "ownership_type": "unknown",
        "controller": "unknown",
        "main_business": "主营业务",
        "business_focus_score": 0,
        "scarcity_score": 0,
        "cycle_type": "other",
        "unique_assets": [],
        "evidence": [],
        "confidence": 0,
        "risk_notes": [],
    }
    data.update(overrides)
    return ValueLowlandCompanyProfile(**data)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ownership_type", "expected_score"),
    [
        ("central_soe", 20),
        ("provincial_soe", 18),
        ("local_soe", 8),
        ("private", 0),
        ("unknown", 0),
    ],
)
def test_ownership_score_distinguishes_soe_types(ownership_type, expected_score):
    service = _service()

    score = service._score_candidate(
        _candidate(),
        profile=_profile(ownership_type=ownership_type, confidence=80),
    )

    assert score.ownership_score == expected_score


@pytest.mark.unit
@pytest.mark.parametrize(
    ("candidate", "profile", "assertion"),
    [
        (_candidate(name="ST样例"), _profile(confidence=80), "st_penalty"),
        (_candidate(low_position_ratio=0.95), _profile(confidence=80), "high_position_penalty"),
        (_candidate(netprofit_yoy=-60), _profile(confidence=80), "profit_penalty"),
        (_candidate(), _profile(ownership_type="private", confidence=80), "private_penalty"),
        (_candidate(), _profile(ownership_type="local_soe", confidence=80), "local_soe_penalty"),
        (_candidate(industry="煤炭开采"), _profile(cycle_type="resource", confidence=80), "cycle_resource"),
        (_candidate(industry="化工原料"), _profile(cycle_type="chemical", confidence=80), "cycle_chemical"),
        (_candidate(industry="软件服务", low_position_ratio=0.5), _profile(cycle_type="other", confidence=80), "ordinary_no_cycle"),
    ],
)
def test_scoring_handles_risk_and_cycle_archetypes(candidate, profile, assertion):
    service = _service()

    score = service._score_candidate(candidate, profile=profile)

    if assertion == "st_penalty":
        assert score.risk_penalty == -40
    elif assertion == "high_position_penalty":
        assert score.risk_penalty <= -8
    elif assertion == "profit_penalty":
        assert score.risk_penalty <= -8
    elif assertion == "private_penalty":
        assert score.risk_penalty <= -15
    elif assertion == "local_soe_penalty":
        assert score.risk_penalty <= -5
    elif assertion in {"cycle_resource", "cycle_chemical"}:
        assert score.cycle_elasticity_score >= 10
    elif assertion == "ordinary_no_cycle":
        assert score.cycle_elasticity_score == 0


@pytest.mark.unit
def test_focus_and_scarcity_scores_come_from_ai_profile():
    service = _service()

    score = service._score_candidate(
        _candidate(),
        profile=_profile(
            ownership_type="central_soe",
            business_focus_score=85,
            scarcity_score=70,
            cycle_type="resource",
            confidence=90,
        ),
    )

    assert score.business_focus_score == 8.5
    assert score.scarcity_score == 7.0
    assert service._total_score(score) > 60


@pytest.mark.unit
def test_ai_profile_without_evidence_url_is_downgraded():
    service = _service()

    result = service._normalize_ai_profile(
        {
            "ownership_type": "central_soe",
            "controller": "某国资委",
            "business_focus_score": 90,
            "scarcity_score": 80,
            "cycle_type": "resource",
            "evidence": [{"title": "无URL证据", "summary": "不能作为可点击证据"}],
            "confidence": 90,
        },
        fallback_evidence=[],
    )

    assert result["evidence"] == []
    assert result["confidence"] <= 30


@pytest.mark.unit
def test_ai_profile_uses_fallback_evidence_urls():
    service = _service()

    result = service._normalize_ai_profile(
        {
            "ownership_type": "provincial_soe",
            "controller": "省国资委",
            "business_focus_score": 75,
            "scarcity_score": 60,
            "cycle_type": "energy",
            "confidence": 70,
        },
        fallback_evidence=[{"title": "公告", "url": "https://example.com/report", "summary": "年报证据"}],
    )

    assert result["ownership_type"] == "provincial_soe"
    assert result["evidence"][0]["url"] == "https://example.com/report"
    assert result["confidence"] == 70


@pytest.mark.unit
@pytest.mark.parametrize(
    ("summary", "expected_type"),
    [
        ("公司实际控制人为国务院国资委，是中央企业控股上市公司。", "central_soe"),
        ("公司实际控制人为中国电子科技集团有限公司。", "central_soe"),
        ("公司控股股东为某某集团，实际控制人为山东省国资委。", "provincial_soe"),
        ("公司实际控制人为湖南省人民政府国有资产监督管理委员会。", "provincial_soe"),
        ("公司实际控制人为杭州市国资委。", "local_soe"),
        ("公司实际控制人为兴山县人民政府国有资产监督管理局。", "local_soe"),
        ("公司实际控制人为青岛西海岸新区国有资产管理局。", "local_soe"),
        ("公司实际控制人为自然人张三，属于民营控股企业。", "private"),
    ],
)
def test_rule_based_ownership_resolution(summary, expected_type):
    service = _service()

    result = service._infer_ownership_with_rules(
        name="样例股份",
        evidence=[{"title": "公司公告", "url": "https://example.com/notice", "summary": summary}],
    )

    assert result["ownership_type"] == expected_type
    assert result["confidence"] >= 70


@pytest.mark.unit
def test_prefer_soe_ranking_when_enriched():
    private = _candidate(code="000001", ts_code="000001.SZ")
    private.profile = _profile(ownership_type="private", confidence=80)
    private.score = 90
    soe = _candidate(code="600001", ts_code="600001.SH")
    soe.profile = _profile(ownership_type="provincial_soe", confidence=80)
    soe.score = 50

    ranked = ValueLowlandService._rank_candidates([private, soe], limit=2, prefer_soe=True)

    assert [item.code for item in ranked] == ["600001", "000001"]


@pytest.mark.unit
def test_rank_candidates_without_limit_returns_all_items():
    candidates = [_candidate(code=f"60000{index}", name=f"样例{index}") for index in range(3)]
    for index, candidate in enumerate(candidates):
        candidate.score = index

    ranked = ValueLowlandService._rank_candidates(candidates, limit=None, prefer_soe=False)

    assert [item.code for item in ranked] == ["600002", "600001", "600000"]


@pytest.mark.unit
def test_strict_profile_filter_only_keeps_soe_resource_chemical_energy():
    kept_resource = _candidate(code="600001", ts_code="600001.SH")
    kept_resource.profile = _profile(ownership_type="central_soe", cycle_type="resource", confidence=80)
    kept_chemical = _candidate(code="600002", ts_code="600002.SH")
    kept_chemical.profile = _profile(ownership_type="provincial_soe", cycle_type="chemical", confidence=80)
    private_energy = _candidate(code="600003", ts_code="600003.SH")
    private_energy.profile = _profile(ownership_type="private", cycle_type="energy", confidence=80)
    local_resource = _candidate(code="600004", ts_code="600004.SH")
    local_resource.profile = _profile(ownership_type="local_soe", cycle_type="resource", confidence=80)
    military_soe = _candidate(code="600005", ts_code="600005.SH")
    military_soe.profile = _profile(ownership_type="central_soe", cycle_type="military", confidence=80)
    utility_soe = _candidate(code="600006", ts_code="600006.SH")
    utility_soe.profile = _profile(ownership_type="central_soe", cycle_type="utility", confidence=80)
    low_confidence = _candidate(code="600007", ts_code="600007.SH")
    low_confidence.profile = _profile(ownership_type="central_soe", cycle_type="resource", confidence=40)

    filtered = ValueLowlandService._apply_strict_profile_filter([
        kept_resource,
        kept_chemical,
        private_energy,
        local_resource,
        military_soe,
        utility_soe,
        low_confidence,
    ])

    assert [item.code for item in filtered] == ["600001", "600002"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("netprofit_yoy", "rev_yoy", "expected"),
    [
        (0, None, True),
        (-10, 0, True),
        (-10, 5, True),
        (-10, -1, False),
        (None, None, False),
    ],
)
def test_financial_improvement_is_required(netprofit_yoy, rev_yoy, expected):
    candidate = _candidate(netprofit_yoy=netprofit_yoy, rev_yoy=rev_yoy)

    assert ValueLowlandService._has_financial_improvement(candidate) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(total_mv=None, circ_mv=None),
        _candidate(total_mv=3_000_001),
        _candidate(low_position_ratio=None),
        _candidate(low_position_ratio=0.71),
        _candidate(netprofit_yoy=-1, rev_yoy=-1),
        _candidate(tags=["已从低点翻倍+"]),
    ],
)
def test_strict_lowland_filter_rejects_non_core_hard_conditions(candidate):
    candidate.profile = _profile(ownership_type="central_soe", cycle_type="resource", confidence=80)

    assert ValueLowlandService._passes_strict_lowland_filter(candidate) is False


@pytest.mark.unit
def test_unknown_or_low_confidence_profile_cache_is_refreshed():
    assert ValueLowlandService._should_refresh_profile(_ProfileModel("unknown", 0)) is True
    assert ValueLowlandService._should_refresh_profile(_ProfileModel("unknown", 80)) is False
    assert ValueLowlandService._should_refresh_profile(_ProfileModel("private", 0)) is True
    assert ValueLowlandService._should_refresh_profile(_ProfileModel("private", 80)) is False


@pytest.mark.unit
def test_static_profile_cache_is_permanent_when_usable():
    assert ValueLowlandService._is_profile_cache_usable(_ProfileModel("central_soe", 80)) is True
    assert ValueLowlandService._is_profile_cache_usable(_ProfileModel("provincial_soe", 70)) is True
    assert ValueLowlandService._is_profile_cache_usable(_ProfileModel("unknown", 80)) is True
    assert ValueLowlandService._is_profile_cache_usable(_ProfileModel("private", 80)) is True


@pytest.mark.unit
def test_unknown_low_confidence_profile_cache_is_not_usable():
    assert ValueLowlandService._is_profile_cache_usable(_ProfileModel("unknown", 0)) is False
