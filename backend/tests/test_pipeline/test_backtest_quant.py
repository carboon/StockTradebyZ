import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PIPELINE_DIR = ROOT / "pipeline"
AGENT_DIR = ROOT / "agent"
for path in (ROOT, PIPELINE_DIR, AGENT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pipeline.backtest_quant import run_backtest  # noqa: E402


def test_run_backtest_keeps_scores_when_prefilter_blocked():
    trade_dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    raw_df = pd.DataFrame(
        {
            "date": trade_dates,
            "open": [10.0, 10.2, 10.4],
            "high": [10.3, 10.5, 10.7],
            "low": [9.8, 10.0, 10.2],
            "close": [10.1, 10.3, 10.6],
            "volume": [1000, 1200, 1500],
        }
    )
    prepared_row = pd.Series(
        {
            "_ready": True,
            "close": 10.3,
            "open": 10.2,
            "high": 10.5,
            "low": 10.0,
            "volume": 1200,
        },
        name=pd.Timestamp("2024-01-03"),
    )
    review_frame = pd.DataFrame([prepared_row])
    review_frame.index = [pd.Timestamp("2024-01-03")]
    b1_frame = pd.DataFrame([{"J": 12.3}], index=[pd.Timestamp("2024-01-03")])

    mock_selector = MagicMock()
    mock_selector.prepare_df.return_value = b1_frame
    mock_selector.vec_picks_from_prepared.return_value = [pd.Timestamp("2024-01-03")]

    mock_prefilter = MagicMock()
    mock_prefilter.evaluate.return_value = {
        "enabled": True,
        "passed": False,
        "blocked_by": ["market_regime"],
        "summary": "blocked",
        "details": {},
    }

    with patch("pipeline.backtest_quant.load_preselect_config", return_value={"global": {"n_turnover_days": 1, "top_m": 10}, "brick": {"enabled": False}}), \
         patch("pipeline.backtest_quant.load_review_config", return_value={"backtest": {"holding_periods": [1], "score_buckets": [3.2]}}), \
         patch("pipeline.backtest_quant.load_raw_data", return_value={"600000": raw_df}), \
         patch("pipeline.backtest_quant.TopTurnoverPoolBuilder") as mock_pool_builder_cls, \
         patch("pipeline.backtest_quant._build_b1_selector", return_value=mock_selector), \
         patch("pipeline.backtest_quant.prepare_review_frame", return_value=review_frame), \
         patch("pipeline.backtest_quant.review_prepared_row", return_value={"verdict": "PASS", "total_score": 4.2, "signal_type": "trend_start", "comment": "ok", "scores": {"trend_structure": 4, "price_position": 4, "volume_behavior": 5, "previous_abnormal_move": 4}}), \
         patch("pipeline.backtest_quant.Step4Prefilter", return_value=mock_prefilter):
        mock_pool_builder = MagicMock()
        mock_pool_builder.build.return_value = {pd.Timestamp("2024-01-03"): ["600000"]}
        mock_pool_builder_cls.return_value = mock_pool_builder

        events_df, _summary = run_backtest(start_date="2024-01-03", end_date="2024-01-03")

    assert len(events_df) == 1
    row = events_df.iloc[0]
    assert row["prefilter_status"] == "blocked"
    assert row["total_score"] == 4.2
    assert row["signal_type"] == "trend_start"
