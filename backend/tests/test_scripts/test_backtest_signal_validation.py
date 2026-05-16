from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "backend" / "scripts" / "backtest_signal_validation.py"
SPEC = spec_from_file_location("backtest_signal_validation", MODULE_PATH)
assert SPEC and SPEC.loader
backtest_signal_validation = module_from_spec(SPEC)
sys.modules["backtest_signal_validation"] = backtest_signal_validation
SPEC.loader.exec_module(backtest_signal_validation)


PriceBar = backtest_signal_validation.PriceBar


def test_extract_return_rows_uses_next_open_and_nth_close():
    rows = [
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-02"), open=10.0, close=10.2),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-03"), open=11.0, close=11.1),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-06"), open=12.0, close=12.2),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-07"), open=13.0, close=13.3),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-08"), open=14.0, close=14.4),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-09"), open=15.0, close=15.5),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-10"), open=16.0, close=16.6),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-13"), open=17.0, close=17.7),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-14"), open=18.0, close=18.8),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-15"), open=19.0, close=19.9),
        PriceBar(trade_date=backtest_signal_validation._parse_date("2025-01-16"), open=20.0, close=20.1),
    ]

    result = backtest_signal_validation._extract_return_rows(
        code_to_rows={"600000": rows},
        code="600000",
        trade_date=backtest_signal_validation._parse_date("2025-01-02"),
    )

    assert result is not None
    assert result["entry_date"] == "2025-01-03"
    assert result["entry_open"] == 11.0
    assert round(result["ret_5d"], 6) == round(15.5 / 11.0 - 1.0, 6)
    assert result["sell_date_5d"] == "2025-01-09"
    assert round(result["ret_10d"], 6) == round(20.1 / 11.0 - 1.0, 6)
    assert result["sell_date_10d"] == "2025-01-16"


def test_match_history_scenarios():
    assert backtest_signal_validation._match_history_scenarios(
        b1_passed=True,
        signal_type="rebound",
        tomorrow_star_pass=False,
    ) == ["history_b1_yes_non_trend_start"]

    assert backtest_signal_validation._match_history_scenarios(
        b1_passed=False,
        signal_type="trend_start",
        tomorrow_star_pass=False,
    ) == ["history_b1_no_trend_start"]

    assert backtest_signal_validation._match_history_scenarios(
        b1_passed=True,
        signal_type="trend_start",
        tomorrow_star_pass=True,
    ) == ["history_b1_yes_trend_start_tomorrow_star"]


def test_match_current_hot_scenarios():
    assert backtest_signal_validation._match_current_hot_scenarios(
        b1_passed=True,
        signal_type="rebound",
    ) == ["current_hot_all", "current_hot_b1_yes_non_trend_start"]

    assert backtest_signal_validation._match_current_hot_scenarios(
        b1_passed=False,
        signal_type="trend_start",
    ) == ["current_hot_all", "current_hot_b1_no_trend_start"]

    assert backtest_signal_validation._match_current_hot_scenarios(
        b1_passed=True,
        signal_type="trend_start",
    ) == ["current_hot_all", "current_hot_b1_yes_trend_start"]
