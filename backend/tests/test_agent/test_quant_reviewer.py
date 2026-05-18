import copy
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[3]
AGENT_DIR = ROOT / "agent"
PIPELINE_DIR = ROOT / "pipeline"
for path in (ROOT, AGENT_DIR, PIPELINE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from quant_reviewer import DEFAULT_CONFIG, QuantReviewer  # noqa: E402


def _build_sample_df(days: int = 320) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    close = np.linspace(10.0, 26.0, days)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "volume": np.linspace(1_000_000, 2_500_000, days),
        }
    )


def _load_raw_sample(code: str) -> pd.DataFrame:
    path = ROOT / "data" / "raw" / f"{code}.csv"
    return pd.read_csv(path)


def _build_reviewer() -> QuantReviewer:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["prefilter"]["enabled"] = False
    reviewer = QuantReviewer(config)
    reviewer.prefilter = MagicMock(
        evaluate=MagicMock(
            return_value={
                "enabled": True,
                "passed": True,
                "blocked_by": [],
                "blocked_labels": [],
                "summary": "通过第 4 步预过滤",
                "details": {},
            }
        )
    )
    return reviewer


def test_review_stock_df_scores_even_when_prefilter_blocked():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["prefilter"]["enabled"] = False
    reviewer = QuantReviewer(config)
    reviewer.prefilter = MagicMock(
        evaluate=MagicMock(
            return_value={
                "enabled": True,
                "passed": False,
                "blocked_by": ["market_regime"],
                "blocked_labels": ["中证 500 / 创业板指环境未达标"],
                "summary": "中证 500 / 创业板指环境未达标",
                "details": {},
            }
        )
    )

    result = reviewer.review_stock_df("600000", _build_sample_df(), asof_date="2025-03-21", strategy="b1")

    assert isinstance(result["total_score"], float)
    assert result["signal_type"] != "prefilter_blocked"
    assert result["prefilter"]["passed"] is False


def test_review_stock_df_penalizes_expanding_selloff_sample():
    reviewer = _build_reviewer()

    healthy = reviewer.review_stock_df("301021", _load_raw_sample("301021"), asof_date="2026-05-06", strategy="b1")
    weak = reviewer.review_stock_df("688183", _load_raw_sample("688183"), asof_date="2026-05-06", strategy="b1")

    assert healthy["scores"]["volume_behavior"] >= 4
    assert weak["scores"]["volume_behavior"] <= 2
    assert healthy["total_score"] > weak["total_score"]
    assert "down_volume_increasing" in weak["pullback_negative_flags"]
    assert "abnormal_bear_bar" in weak["pullback_negative_flags"]


@pytest.mark.parametrize(
    ("code", "asof_date"),
    [
        ("301183", "2026-04-28"),
        ("002903", "2026-04-24"),
        ("002222", "2026-04-29"),
    ],
)
def test_review_stock_df_keeps_contracting_pullback_samples_high_volume_score(code: str, asof_date: str):
    reviewer = _build_reviewer()

    result = reviewer.review_stock_df(code, _load_raw_sample(code), asof_date=asof_date, strategy="b1")

    assert result["scores"]["volume_behavior"] >= 4
    assert "down_volume_increasing" not in result["pullback_negative_flags"]
