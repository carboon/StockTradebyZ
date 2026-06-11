from datetime import date
from unittest.mock import MagicMock, patch

from app.services.realtime_daily_bar_service import RealtimeDailyBarService


def _tencent_body(code: str = "600000", quote_time: str = "20260508145938") -> str:
    parts = [""] * 88
    parts[1] = "浦发银行"
    parts[2] = code
    parts[3] = "10.42"
    parts[4] = "10.00"
    parts[5] = "10.05"
    parts[30] = quote_time
    parts[33] = "10.50"
    parts[34] = "9.95"
    parts[36] = "450000"
    parts[37] = "4500000"
    parts[38] = "6.50"
    parts[44] = "100.00"
    parts[45] = "90.00"
    parts[49] = "1.60"
    return "~".join(parts)


def test_realtime_daily_bar_service_fetches_tencent_bar() -> None:
    response = MagicMock()
    response.text = f'v_sh600000="{_tencent_body()}";'

    with patch("app.services.realtime_daily_bar_service.requests.get", return_value=response) as mocked_get:
        bars = RealtimeDailyBarService().fetch_bars(["600000"], trade_date=date(2026, 5, 8))

    assert mocked_get.call_args.args[0].endswith("sh600000")
    bar = bars["600000"]
    assert bar.open == 10.05
    assert bar.close == 10.42
    assert bar.high == 10.5
    assert bar.low == 9.95
    assert bar.volume == 450000
    assert bar.turnover_rate == 6.5
    assert bar.volume_ratio == 1.6
    assert bar.circ_mv == 9_000_000_000
    assert bar.source == "tencent_quote"
