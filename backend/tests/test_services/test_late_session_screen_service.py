from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd

from app.models import LateSessionScreenResult, LateSessionScreenRun, Stock, StockDaily, Watchlist
from app.services.intraday_analysis_service import ASIA_SHANGHAI
from app.services.late_session_screen_service import LateSessionScreenService


def _seed_history(db: Any, code: str, *, name: str, latest_date: date, pass_metrics: bool) -> None:
    db.add(Stock(code=code, name=name, market="SH" if code.startswith("6") else "SZ", industry="有色金属"))
    start = latest_date - timedelta(days=95)
    current = start
    inserted = 0
    while inserted < 70:
        if current.weekday() < 5:
            base = 8.0 + inserted * 0.04
            volume = 100000 + inserted * 2000
            db.add(
                StockDaily(
                    code=code,
                    trade_date=current,
                    open=base,
                    close=base + 0.05,
                    high=base + 0.12,
                    low=base - 0.08,
                    volume=volume,
                    turnover_rate=6.2 if pass_metrics else 3.1,
                    volume_ratio=1.4 if pass_metrics else 0.8,
                    circ_mv=900000 if pass_metrics else 300000,
                )
            )
            inserted += 1
        current += timedelta(days=1)
    db.commit()


def _minute_df() -> pd.DataFrame:
    rows = []
    for code, pre_close in [("600000", 10.0), ("000001", 10.0)]:
        for time_text, close in [
            ("2026-05-08 09:31:00", 10.08),
            ("2026-05-08 14:29:00", 10.32),
            ("2026-05-08 14:35:00", 10.42),
        ]:
            rows.append(
                {
                    "ts_code": f"{code}.SH" if code.startswith("6") else f"{code}.SZ",
                    "normalized_ts_code": f"{code}.SH" if code.startswith("6") else f"{code}.SZ",
                    "code": code,
                    "trade_time": time_text,
                    "open": 10.05,
                    "close": close,
                    "high": close,
                    "low": close - 0.05,
                    "vol": 150000.0,
                    "amount": 1500000.0,
                    "pre_close": pre_close,
                }
            )
    return pd.DataFrame(rows)


def _quote_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_code": "600000.SH",
                "normalized_ts_code": "600000.SH",
                "code": "600000",
                "open": 10.05,
                "close": 10.42,
                "high": 10.42,
                "low": 10.0,
                "vol": 450000.0,
                "amount": 4500000.0,
                "pre_close": 10.0,
                "volume_ratio": 1.6,
                "turnover_rate": 6.5,
                "circ_mv": 9_000_000_000.0,
            },
            {
                "ts_code": "000001.SZ",
                "normalized_ts_code": "000001.SZ",
                "code": "000001",
                "open": 10.05,
                "close": 10.42,
                "high": 10.42,
                "low": 10.0,
                "vol": 450000.0,
                "amount": 4500000.0,
                "pre_close": 10.0,
                "volume_ratio": 0.8,
                "turnover_rate": 3.2,
                "circ_mv": 3_000_000_000.0,
            },
        ]
    )


def _tencent_body(
    code: str = "600000",
    *,
    name: str = "浦发银行",
    quote_time: str = "20260508145938",
    pct_chg: str = "4.20",
    turnover_rate: str = "6.50",
    volume_ratio: str = "1.60",
    total_mv_yi: str = "100.00",
    circ_mv_yi: str = "90.00",
) -> str:
    parts = [""] * 88
    parts[1] = name
    parts[2] = code
    parts[3] = "10.42"
    parts[4] = "10.00"
    parts[30] = quote_time
    parts[32] = pct_chg
    parts[36] = "450000"
    parts[37] = "4500000"
    parts[38] = turnover_rate
    parts[44] = total_mv_yi
    parts[45] = circ_mv_yi
    parts[49] = volume_ratio
    return "~".join(parts)


def test_late_session_generate_persists_funnel_and_final_pick(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    latest_date = date(2026, 5, 7)
    _seed_history(db, "600000", name="通过股", latest_date=latest_date, pass_metrics=True)
    _seed_history(db, "000001", name="剔除股", latest_date=latest_date, pass_metrics=False)
    fake_now = datetime(2026, 5, 8, 14, 35, tzinfo=ASIA_SHANGHAI)

    with (
        patch("app.services.late_session_screen_service.LateSessionScreenService.now_shanghai", return_value=fake_now),
        patch("app.services.late_session_screen_service.LateSessionScreenService._fetch_realtime_quotes", return_value=_quote_df()),
        patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_minute_quotes", return_value=_minute_df()),
        patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_intraday_raw_once", return_value=_minute_df()),
    ):
        payload = LateSessionScreenService(db).generate(user_id=1, is_admin=True, force=True)

    assert payload["status"] == "ok"
    assert payload["final_count"] == 1
    assert payload["funnel"][-1]["count"] == 1
    result = db.query(LateSessionScreenResult).filter(LateSessionScreenResult.code == "600000").one()
    assert result.final_pass is True
    assert result.volume_pattern in {"step_up", "expanding"}
    rejected = db.query(LateSessionScreenResult).filter(LateSessionScreenResult.code == "000001").one()
    assert rejected.hard_pass is False
    assert rejected.reject_reason in {"量比小于 1 或缺失", "换手率不在 5%-10%", "流通市值不在 50-200 亿"}


def test_late_session_allows_regular_user_outside_window(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    fake_now = datetime(2026, 5, 8, 13, 35, tzinfo=ASIA_SHANGHAI)

    with patch("app.services.late_session_screen_service.LateSessionScreenService.now_shanghai", return_value=fake_now):
        payload = LateSessionScreenService(db).generate(user_id=1, is_admin=False, force=False)

    assert payload["status"] == "no_data"
    assert payload["has_data"] is False


def test_late_session_force_refresh_has_one_minute_cooldown(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    trade_date = date(2026, 5, 8)
    snapshot_time = datetime(2026, 5, 8, 13, 35, tzinfo=ASIA_SHANGHAI)
    db.add(
        LateSessionScreenRun(
            trade_date=trade_date,
            snapshot_time=snapshot_time,
            status="empty",
            message="尾盘筛选未得到最终标的",
            total_count=0,
            candidate_count=0,
            final_count=0,
            generated_by_user_id=1,
        )
    )
    db.commit()

    fake_now = datetime(2026, 5, 8, 13, 35, 30, tzinfo=ASIA_SHANGHAI)
    with (
        patch("app.services.late_session_screen_service.LateSessionScreenService.now_shanghai", return_value=fake_now),
        patch("app.services.late_session_screen_service.LateSessionScreenService._fetch_realtime_quotes") as mocked_fetch,
    ):
        payload = LateSessionScreenService(db).generate(user_id=1, is_admin=False, force=True)

    assert payload["message"] == "刷新过于频繁，请 1 分钟后再试"
    assert payload["status"] == "empty"
    mocked_fetch.assert_not_called()


def test_late_session_does_not_fallback_to_daily_metrics(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    latest_date = date(2026, 5, 7)
    _seed_history(db, "600000", name="通过股", latest_date=latest_date, pass_metrics=True)
    fake_now = datetime(2026, 5, 8, 14, 35, tzinfo=ASIA_SHANGHAI)
    realtime_without_metrics = _quote_df().drop(columns=["volume_ratio", "turnover_rate", "circ_mv"])

    with (
        patch("app.services.late_session_screen_service.LateSessionScreenService.now_shanghai", return_value=fake_now),
        patch("app.services.late_session_screen_service.LateSessionScreenService._fetch_realtime_quotes", return_value=realtime_without_metrics),
        patch("app.services.intraday_analysis_service.IntradayAnalysisService._fetch_intraday_raw_once", return_value=_minute_df()),
    ):
        payload = LateSessionScreenService(db).generate(user_id=1, is_admin=True, force=True)

    assert payload["final_count"] == 0
    row = db.query(LateSessionScreenResult).filter(LateSessionScreenResult.code == "600000").one()
    assert row.hard_pass is False
    assert row.volume_ratio is None
    assert row.turnover_rate is None
    assert row.circ_mv is None
    assert row.reject_reason == "量比小于 1 或缺失"


def test_late_session_fetches_eastmoney_realtime_fields(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "total": 1,
            "diff": [
                {
                    "f12": "600000",
                    "f14": "浦发银行",
                    "f2": 10.42,
                    "f3": 4.2,
                    "f5": 450000,
                    "f6": 4500000,
                    "f8": 6.5,
                    "f10": 1.6,
                    "f20": 10_000_000_000,
                    "f21": 9_000_000_000,
                }
            ],
        }
    }

    with patch("app.services.late_session_screen_service.requests.get", return_value=response):
        frame = LateSessionScreenService(db)._fetch_realtime_quotes(["600000"])

    assert frame.iloc[0]["code"] == "600000"
    assert frame.iloc[0]["pct_chg"] == 4.2
    assert frame.iloc[0]["volume_ratio"] == 1.6
    assert frame.iloc[0]["turnover_rate"] == 6.5
    assert frame.iloc[0]["circ_mv"] == 9_000_000_000
    assert frame.iloc[0]["source"] == "eastmoney_clist"


def test_late_session_fetches_all_eastmoney_pages(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    responses = []
    for page in range(3):
        response = MagicMock()
        response.json.return_value = {
            "data": {
                "total": 250,
                "diff": [
                    {
                        "f12": str(600000 + page * 100 + idx),
                        "f14": "测试股",
                        "f2": 10.42,
                        "f3": 4.2,
                        "f5": 450000,
                        "f6": 4500000,
                        "f8": 6.5,
                        "f10": 1.6,
                        "f20": 10_000_000_000,
                        "f21": 9_000_000_000,
                    }
                    for idx in range(100 if page < 2 else 50)
                ],
            }
        }
        responses.append(response)

    target_codes = [str(600000 + idx) for idx in range(250)]
    with (
        patch("app.services.late_session_screen_service.requests.get", side_effect=responses) as mocked_get,
        patch("app.services.late_session_screen_service.time_module.sleep"),
    ):
        frame = LateSessionScreenService(db)._fetch_realtime_quotes(target_codes)

    assert len(frame) == 250
    assert mocked_get.call_count == 3
    assert [call.kwargs["params"]["pn"] for call in mocked_get.mock_calls] == [1, 2, 3]
    assert all(call.kwargs["params"]["pz"] == 100 for call in mocked_get.mock_calls)


def test_late_session_rejects_partial_eastmoney_pages(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    first_page = MagicMock()
    first_page.json.return_value = {
        "data": {
            "total": 250,
            "diff": [
                {
                    "f12": str(600000 + idx),
                    "f14": "测试股",
                    "f2": 10.42,
                    "f3": 4.2,
                    "f5": 450000,
                    "f6": 4500000,
                    "f8": 6.5,
                    "f10": 1.6,
                    "f20": 10_000_000_000,
                    "f21": 9_000_000_000,
                }
                for idx in range(100)
            ],
        }
    }

    target_codes = [str(600000 + idx) for idx in range(250)]
    with (
        patch(
            "app.services.late_session_screen_service.requests.get",
            side_effect=[first_page] + [RuntimeError("disconnect")] * 10,
        ) as mocked_get,
        patch("app.services.late_session_screen_service.LateSessionScreenService._fetch_tencent_realtime_quotes", return_value=pd.DataFrame()),
        patch("app.services.late_session_screen_service.time_module.sleep"),
    ):
        frame = LateSessionScreenService(db)._fetch_realtime_quotes(target_codes)

    assert frame.empty
    assert mocked_get.call_count == 11


def test_late_session_retries_full_eastmoney_fetch_after_partial_failure(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    failed_first_page = MagicMock()
    failed_first_page.json.return_value = {
        "data": {
            "total": 250,
            "diff": [
                {
                    "f12": str(600000 + idx),
                    "f14": "测试股",
                    "f2": 10.42,
                    "f3": 4.2,
                    "f5": 450000,
                    "f6": 4500000,
                    "f8": 6.5,
                    "f10": 1.6,
                    "f20": 10_000_000_000,
                    "f21": 9_000_000_000,
                }
                for idx in range(100)
            ],
        }
    }
    success_pages = []
    for page in range(3):
        response = MagicMock()
        response.json.return_value = {
            "data": {
                "total": 250,
                "diff": [
                    {
                        "f12": str(600000 + page * 100 + idx),
                        "f14": "测试股",
                        "f2": 10.42,
                        "f3": 4.2,
                        "f5": 450000,
                        "f6": 4500000,
                        "f8": 6.5,
                        "f10": 1.6,
                        "f20": 10_000_000_000,
                        "f21": 9_000_000_000,
                    }
                    for idx in range(100 if page < 2 else 50)
                ],
            }
        }
        success_pages.append(response)

    target_codes = [str(600000 + idx) for idx in range(250)]
    with (
        patch(
            "app.services.late_session_screen_service.requests.get",
            side_effect=[failed_first_page] + [RuntimeError("disconnect")] * 5 + success_pages,
        ) as mocked_get,
        patch("app.services.late_session_screen_service.LateSessionScreenService._fetch_tencent_realtime_quotes", return_value=pd.DataFrame()),
        patch("app.services.late_session_screen_service.time_module.sleep"),
    ):
        frame = LateSessionScreenService(db)._fetch_realtime_quotes(target_codes)

    assert len(frame) == 250
    assert mocked_get.call_count == 9


def test_late_session_parses_tencent_realtime_fields(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    fake_now = datetime(2026, 5, 8, 15, 5, tzinfo=ASIA_SHANGHAI)
    response = MagicMock()
    response.text = f'v_sh600000="{_tencent_body()}";'

    with (
        patch("app.services.late_session_screen_service.LateSessionScreenService.now_shanghai", return_value=fake_now),
        patch("app.services.late_session_screen_service.requests.get", return_value=response) as mocked_get,
        patch("app.services.late_session_screen_service.time_module.sleep"),
    ):
        frame = LateSessionScreenService(db)._fetch_tencent_realtime_quotes({"600000"})

    assert mocked_get.call_args.args[0].endswith("sh600000")
    assert frame.iloc[0]["code"] == "600000"
    assert frame.iloc[0]["pct_chg"] == 4.2
    assert frame.iloc[0]["volume_ratio"] == 1.6
    assert frame.iloc[0]["turnover_rate"] == 6.5
    assert frame.iloc[0]["circ_mv"] == 9_000_000_000
    assert frame.iloc[0]["source"] == "tencent_quote"


def test_late_session_falls_back_to_tencent_after_eastmoney_failure(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    fake_now = datetime(2026, 5, 8, 15, 5, tzinfo=ASIA_SHANGHAI)
    response = MagicMock()
    response.text = f'v_sh600000="{_tencent_body()}";'

    with (
        patch("app.services.late_session_screen_service.LateSessionScreenService.now_shanghai", return_value=fake_now),
        patch("app.services.late_session_screen_service.requests.get", side_effect=[RuntimeError("disconnect")] * 10 + [response]) as mocked_get,
        patch("app.services.late_session_screen_service.time_module.sleep"),
    ):
        frame = LateSessionScreenService(db)._fetch_realtime_quotes(["600000"])

    assert len(frame) == 1
    assert mocked_get.call_count == 11
    assert frame.iloc[0]["source"] == "tencent_quote"


def test_late_session_add_watchlist_reactivates_existing(test_client_with_db: Any) -> None:
    db = test_client_with_db.db
    db.add(Stock(code="600000", name="通过股", market="SH"))
    db.add(Watchlist(user_id=1, code="600000", is_active=False))
    db.commit()

    payload = LateSessionScreenService(db).add_watchlist(user_id=1, codes=["600000", "600000.SH"])

    assert payload["added_count"] == 1
    watch = db.query(Watchlist).filter(Watchlist.user_id == 1, Watchlist.code == "600000").one()
    assert watch.is_active is True
    assert watch.add_reason == "尾盘筛选通过"
