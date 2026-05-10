import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.services.exit_plan_service import ExitPlanService


def _history(days: int = 40, *, start_price: float = 10.0, last_close: float | None = None) -> pd.DataFrame:
    start = date(2026, 1, 1)
    rows = []
    for i in range(days):
        close = start_price + i * 0.03
        if i == days - 1 and last_close is not None:
            close = last_close
        rows.append(
            {
                "date": start + timedelta(days=i),
                "open": close - 0.05,
                "high": close + 0.12,
                "low": close - 0.12,
                "close": close,
                "volume": 100000 + i * 100,
            }
        )
    return pd.DataFrame(rows)


def _service_with_missing_profiles(tmp_path: Path) -> ExitPlanService:
    config_path = tmp_path / "exit_plan.yaml"
    config_path.write_text(f"profiles_path: {tmp_path / 'missing_profiles.json'}\n", encoding="utf-8")
    return ExitPlanService(config_path=config_path)


def test_exit_plan_uses_fallback_target_quantiles(tmp_path: Path) -> None:
    service = _service_with_missing_profiles(tmp_path)

    plan = service.build_exit_plan(
        code="600000",
        history_df=_history(),
        entry_price=10.0,
        current_price=10.2,
        entry_date=date(2026, 1, 1),
    )

    assert plan["target_prices"]["5d"]["p50"] == 10.6
    assert plan["target_prices"]["10d"]["p75"] == 11.85
    assert plan["target_prices"]["20d"]["p90"] == 15.89
    assert plan["target_progress"] == "below_p50"


def test_exit_plan_loads_generated_backtest_profile_targets(tmp_path: Path) -> None:
    profile_path = tmp_path / "exit_profiles.json"
    profile_path.write_text(
        json.dumps(
            {
                "filters": {
                    "strategy": "b1",
                    "verdict": "PASS",
                    "signal_type": "trend_start",
                    "prefilter_status": "passed",
                },
                "profiles": {
                    "b1|PASS|trend_start|passed|all": {
                        "sample_count": 32,
                        "min_sample_met": True,
                        "horizons": {
                            "5d": {"mfe": {"p50": 0.07, "p75": 0.12, "p90": 0.18}},
                            "10d": {"mfe": {"p50": 0.11, "p75": 0.22, "p90": 0.37}},
                            "20d": {"mfe": {"p50": 0.15, "p75": 0.31, "p90": 0.52}},
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "exit_plan.yaml"
    config_path.write_text(f"profiles_path: {profile_path}\n", encoding="utf-8")

    service = ExitPlanService(config_path=config_path)

    plan = service.build_exit_plan(
        code="600000",
        history_df=_history(),
        entry_price=10.0,
        current_price=10.2,
        entry_date=date(2026, 1, 1),
    )

    assert service.targets["10d"]["p75"] == 0.22
    assert plan["target_prices"]["5d"]["p50"] == 10.7
    assert plan["target_prices"]["20d"]["p90"] == 15.2


def test_exit_plan_reaching_p75_takes_partial_profit(tmp_path: Path) -> None:
    service = _service_with_missing_profiles(tmp_path)
    frame = _history(last_close=12.0)
    frame.loc[frame.index[-1], "high"] = 12.2
    frame.loc[frame.index[-1], "low"] = 11.8

    plan = service.build_exit_plan(
        code="600000",
        history_df=frame,
        entry_price=10.0,
        current_price=12.0,
        entry_date=date(2026, 1, 1),
        verdict="PASS",
        signal_type="trend_start",
    )

    assert plan["target_progress"] == "p75"
    assert plan["action"] == "take_profit_partial"
    assert plan["phase"] == "profit_protect"
    assert "target_p75_reached" in plan["rules"]


def test_exit_plan_intraday_structure_pierce_and_reclaim_is_wash_observe(tmp_path: Path) -> None:
    service = _service_with_missing_profiles(tmp_path)
    frame = _history(last_close=10.4)
    frame.loc[frame.index[-6:-1], "low"] = [10.25, 10.22, 10.21, 10.2, 10.23]
    frame.loc[frame.index[-1], ["open", "high", "low", "close", "volume"]] = [10.0, 10.45, 9.95, 10.3, 120000]

    plan = service.build_exit_plan(
        code="600000",
        history_df=frame,
        entry_price=10.0,
        current_price=10.3,
        entry_date=date(2026, 1, 1),
        verdict="PASS",
        signal_type="trend_start",
        is_intraday=True,
    )

    assert plan["morning_state"] == "wash_observe"
    assert plan["afternoon_action"] == "hold_if_reclaim"
    assert plan["action"] == "wash_observe"


def test_exit_plan_distribution_risk_trims_before_breakdown(tmp_path: Path) -> None:
    service = _service_with_missing_profiles(tmp_path)
    frame = _history(last_close=11.4)

    plan = service.build_exit_plan(
        code="600000",
        history_df=frame,
        entry_price=10.0,
        current_price=11.4,
        entry_date=date(2026, 1, 1),
        verdict="WATCH",
        signal_type="distribution_risk",
        is_intraday=True,
    )

    assert plan["morning_state"] == "distribution_risk"
    assert plan["afternoon_action"] == "trim"
    assert plan["action"] == "trim"


def test_exit_plan_fail_breakdown_exits(tmp_path: Path) -> None:
    service = _service_with_missing_profiles(tmp_path)
    frame = _history(last_close=8.9)
    frame.loc[frame.index[-1], ["open", "high", "low", "close"]] = [9.1, 9.2, 8.8, 8.9]

    plan = service.build_exit_plan(
        code="600000",
        history_df=frame,
        entry_price=10.0,
        current_price=8.9,
        entry_date=date(2026, 1, 1),
        verdict="FAIL",
        signal_type="distribution_risk",
    )

    assert plan["action"] == "exit"
    assert plan["phase"] == "risk_control"
    assert "hard_stop_broken" in plan["rules"]
