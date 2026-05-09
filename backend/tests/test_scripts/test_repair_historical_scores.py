from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "backend" / "scripts" / "repair_historical_scores.py"
SPEC = spec_from_file_location("repair_historical_scores", MODULE_PATH)
assert SPEC and SPEC.loader
repair_historical_scores = module_from_spec(SPEC)
SPEC.loader.exec_module(repair_historical_scores)


def test_build_tomorrow_star_issues_detects_old_prefilter_block_anomaly():
    snapshot = {
        "run": SimpleNamespace(
            status="success",
            candidate_count=189,
            analysis_count=189,
            trend_start_count=0,
            consecutive_candidate_count=0,
        ),
        "candidate_count": 189,
        "analysis_count": 189,
        "trend_start_count": 0,
        "consecutive_candidate_count": 0,
        "null_score_count": 189,
        "prefilter_blocked_signal_count": 189,
        "missing_prefilter_count": 189,
    }

    issues = repair_historical_scores.build_tomorrow_star_issues(snapshot)

    assert "存在 189 条空评分记录" in issues
    assert "存在 189 条旧版 prefilter_blocked 信号" in issues
    assert "存在 189 条记录缺少 prefilter 明细" in issues


def test_build_tomorrow_star_issues_returns_empty_for_compliant_snapshot():
    snapshot = {
        "run": SimpleNamespace(
            status="success",
            candidate_count=172,
            analysis_count=172,
            trend_start_count=1,
            consecutive_candidate_count=12,
            source="manual_repair",
        ),
        "candidate_count": 172,
        "analysis_count": 172,
        "trend_start_count": 1,
        "consecutive_candidate_count": 12,
        "null_score_count": 0,
        "prefilter_blocked_signal_count": 0,
        "missing_prefilter_count": 0,
    }

    assert repair_historical_scores.build_tomorrow_star_issues(snapshot) == []


def test_build_tomorrow_star_issues_ignores_stale_run_counts_when_rows_are_complete():
    snapshot = {
        "run": SimpleNamespace(
            status="running",
            candidate_count=10,
            analysis_count=9,
            trend_start_count=0,
            consecutive_candidate_count=0,
            source="background_update",
        ),
        "candidate_count": 172,
        "analysis_count": 172,
        "trend_start_count": 1,
        "consecutive_candidate_count": 12,
        "null_score_count": 0,
        "prefilter_blocked_signal_count": 0,
        "missing_prefilter_count": 0,
    }

    assert repair_historical_scores.build_tomorrow_star_issues(snapshot) == []


def test_build_tomorrow_star_issues_detects_legacy_manual_rebuild_empty_run():
    snapshot = {
        "run": SimpleNamespace(
            status="success",
            candidate_count=0,
            analysis_count=0,
            trend_start_count=0,
            consecutive_candidate_count=0,
            source="manual_rebuild",
        ),
        "candidate_count": 0,
        "analysis_count": 0,
        "trend_start_count": 0,
        "consecutive_candidate_count": 0,
        "null_score_count": 0,
        "prefilter_blocked_signal_count": 0,
        "missing_prefilter_count": 0,
    }

    issues = repair_historical_scores.build_tomorrow_star_issues(snapshot)

    assert issues == ["旧版 manual_rebuild 空结果"]


def test_build_current_hot_issues_detects_missing_run_and_details():
    snapshot = {
        "run": None,
        "candidate_count": 120,
        "analysis_count": 118,
        "trend_start_count": 3,
        "consecutive_candidate_count": 6,
        "missing_details_count": 5,
    }

    issues = repair_historical_scores.build_current_hot_issues(snapshot)

    assert "缺少运行记录" in issues
    assert "候选数 120 与分析数 118 不一致" in issues
    assert "存在 5 条记录缺少 details_json" in issues


def test_build_current_hot_issues_ignores_non_success_run_when_rows_are_complete():
    snapshot = {
        "run": SimpleNamespace(
            status="running",
            candidate_count=10,
            analysis_count=8,
            trend_start_count=0,
            consecutive_candidate_count=0,
        ),
        "candidate_count": 92,
        "analysis_count": 92,
        "trend_start_count": 3,
        "consecutive_candidate_count": 6,
        "missing_details_count": 0,
    }

    assert repair_historical_scores.build_current_hot_issues(snapshot) == []


def test_repair_tomorrow_star_uses_batch_rebuild_entry(monkeypatch):
    calls: list[list[str]] = []

    class _FakeSession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return None

    class _FakeService:
        def __init__(self, db):
            self.db = db

        def rebuild_trade_dates(self, trade_dates, *, reviewer, source, window_size):
            calls.append(list(trade_dates))
            return [
                {
                    "success": True,
                    "status": "success",
                    "pick_date": trade_date,
                    "candidate_count": 1,
                    "analysis_count": 1,
                    "trend_start_count": 1,
                }
                for trade_date in trade_dates
            ]

    monkeypatch.setattr(repair_historical_scores, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(repair_historical_scores, "TomorrowStarWindowService", _FakeService)
    monkeypatch.setattr(
        repair_historical_scores,
        "build_trade_date_batches",
        lambda trade_dates: [["2024-01-02", "2024-01-03"]],
    )

    results = repair_historical_scores.repair_tomorrow_star(
        ["2024-01-02", "2024-01-03"],
        reviewer="quant",
        window_size=180,
    )

    assert calls == [["2024-01-02", "2024-01-03"]]
    assert [item["pick_date"] for item in results] == ["2024-01-02", "2024-01-03"]
