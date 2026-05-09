import copy
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd


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


def test_review_stock_df_scores_even_when_prefilter_blocked():
    config = copy.deepcopy(DEFAULT_CONFIG)
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
