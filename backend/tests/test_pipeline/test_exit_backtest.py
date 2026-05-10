import json
from pathlib import Path

import pandas as pd

from pipeline.exit_backtest import build_profiles, compute_exit_metrics, run_exit_backtest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_fixture_tree(root: Path) -> None:
    _write_json(
        root / "candidates" / "candidates_2024-01-02.json",
        {
            "pick_date": "2024-01-02",
            "candidates": [
                {"code": "600001", "date": "2024-01-02", "strategy": "b1"},
                {"code": "600002", "date": "2024-01-02", "strategy": "brick"},
            ],
        },
    )
    _write_json(
        root / "review" / "2024-01-02" / "600001.json",
        {
            "code": "600001",
            "pick_date": "2024-01-02",
            "strategy": "b1",
            "verdict": "PASS",
            "signal_type": "trend_start",
            "total_score": 4.2,
            "prefilter": {"passed": True, "details": {"size_bucket": "mid"}},
        },
    )
    _write_json(
        root / "review" / "2024-01-02" / "600002.json",
        {
            "code": "600002",
            "pick_date": "2024-01-02",
            "strategy": "brick",
            "verdict": "PASS",
            "signal_type": "trend_start",
            "prefilter": {"passed": True, "details": {"size_bucket": "mid"}},
        },
    )
    raw = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-02", periods=22, freq="B").strftime("%Y-%m-%d"),
            "open": [10.0] + [100.0] * 21,
            "high": [999.0, 106.0, 109.0, 112.0, 121.0] + [118.0] * 17,
            "low": [1.0, 98.0, 95.0, 97.0, 96.0] + [99.0] * 17,
            "close": [10.0] + [101.0] * 21,
        }
    )
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw.to_csv(raw_dir / "600001.csv", index=False)


def test_compute_exit_metrics_uses_next_open_and_excludes_pick_day() -> None:
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "open": [10.0, 100.0, 100.0],
            "high": [999.0, 110.0, 105.0],
            "low": [1.0, 90.0, 95.0],
            "close": [10.0, 105.0, 102.0],
        }
    )

    row = compute_exit_metrics(
        {
            "pick_date": "2024-01-02",
            "code": "600001",
            "strategy": "b1",
            "verdict": "PASS",
            "signal_type": "trend_start",
            "prefilter_status": "passed",
            "size_bucket": "mid",
        },
        prices,
        horizons=[2],
    )

    assert row is not None
    assert row["entry_date"] == "2024-01-03"
    assert row["entry_open"] == 100.0
    assert row["2d_mfe"] == 0.1
    assert row["2d_mae"] == -0.1
    assert row["2d_high_date"] == "2024-01-03"
    assert row["2d_low_date"] == "2024-01-03"


def test_run_exit_backtest_writes_events_and_profiles(tmp_path: Path) -> None:
    _write_fixture_tree(tmp_path)

    events, profiles = run_exit_backtest(
        data_root=tmp_path,
        output_dir=tmp_path / "exit",
        start_date="2024-01-02",
        end_date="2024-01-02",
        min_samples=1,
    )

    assert len(events) == 1
    assert (tmp_path / "exit" / "exit_events.csv").exists()
    assert (tmp_path / "exit" / "exit_profiles.json").exists()

    key = "b1|PASS|trend_start|passed|all"
    profile = profiles["profiles"][key]
    assert profile["sample_count"] == 1
    assert profile["horizons"]["5d"]["mfe"]["p50"] == 0.21
    assert profile["horizons"]["5d"]["mae"]["p50"] == -0.05
    assert profile["horizons"]["5d"]["close_ret"]["p50"] == 0.01
    assert profiles["profiles"]["fallback"]["sample_count"] == 1


def test_build_profiles_outputs_quantiles_for_groups() -> None:
    events = pd.DataFrame(
        [
            {
                "strategy": "b1",
                "verdict": "PASS",
                "signal_type": "trend_start",
                "prefilter_status": "passed",
                "size_bucket": "small",
                "5d_complete": True,
                "5d_mfe": 0.10,
                "5d_mae": -0.03,
                "5d_close_ret": 0.02,
            },
            {
                "strategy": "b1",
                "verdict": "PASS",
                "signal_type": "trend_start",
                "prefilter_status": "passed",
                "size_bucket": "small",
                "5d_complete": True,
                "5d_mfe": 0.30,
                "5d_mae": -0.09,
                "5d_close_ret": 0.08,
            },
        ]
    )

    profiles = build_profiles(events, horizons=[5], min_samples=2)
    key = "b1|PASS|trend_start|passed|small"

    assert profiles["profiles"][key]["sample_count"] == 2
    assert profiles["profiles"][key]["min_sample_met"] is True
    assert profiles["profiles"][key]["horizons"]["5d"]["mfe"]["p50"] == 0.2
    assert profiles["profiles"]["b1|PASS|trend_start|passed|all"]["horizons"]["5d"]["close_ret"]["p75"] == 0.065
