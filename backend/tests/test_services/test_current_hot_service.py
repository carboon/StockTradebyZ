from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from app.models import Config, CurrentHotAnalysisResult, CurrentHotCandidate, CurrentHotRun, Stock, StockDaily, StockFinancial
from app.services.current_hot_service import CurrentHotService
from app.services.realtime_daily_bar_service import RealtimeDailyBar


def _seed_stock_history(test_db, code: str, end_date: date, days: int = 90, base: float = 10.0) -> None:
    if test_db.query(Stock).filter(Stock.code == code).first() is None:
        test_db.add(Stock(code=code, name=code, market="SH" if code.startswith("6") else "SZ"))
        test_db.commit()
    current = end_date - timedelta(days=days + 30)
    inserted = 0
    while inserted < days:
        if current.weekday() < 5:
            price = base + inserted * 0.05
            test_db.add(
                StockDaily(
                    code=code,
                    trade_date=current,
                    open=price,
                    close=price + 0.1,
                    high=price + 0.2,
                    low=price - 0.1,
                    volume=100000 + inserted * 100,
                )
            )
            inserted += 1
        current += timedelta(days=1)
    test_db.commit()


class _FakeSelector:
    def prepare_df(self, df: pd.DataFrame) -> pd.DataFrame:
        prepared = df.copy()
        prepared["_vec_pick"] = [False] * (len(prepared) - 1) + [True]
        prepared["J"] = [10.0] * len(prepared)
        prepared["zxdq"] = [2.0] * len(prepared)
        prepared["zxdkx"] = [1.0] * len(prepared)
        prepared["wma_bull"] = [True] * len(prepared)
        return prepared

    def check_b1(self, df: pd.DataFrame, code: str) -> dict:
        return {"b1_passed": True, "b1_signal_type": "old_b1", "j": 10.0}


@pytest.mark.service
def test_get_pool_entries_merges_duplicate_sector_memberships(test_db) -> None:
    service = CurrentHotService(test_db)
    with patch.object(
        CurrentHotService,
        "_load_pool_config",
        return_value={
            "AI服务器": {"中科曙光": "603019"},
            "液冷": {"中科曙光": "603019"},
        },
    ):
        entries = service.get_pool_entries()

    assert len(entries) == 1
    assert entries[0].code == "603019"
    assert entries[0].sector_names == ["AI服务器", "液冷"]
    assert entries[0].board_group == "other"


@pytest.mark.service
def test_get_pool_entries_falls_back_when_stored_config_is_empty(test_db) -> None:
    test_db.add(Config(key=CurrentHotService.CONFIG_KEY, value="{}", description="empty current hot pool"))
    test_db.commit()

    entries = CurrentHotService(test_db).get_pool_entries()

    assert len(entries) > 0
    assert any(entry.code == "600549" and entry.name == "厦门钨业" for entry in entries)


@pytest.mark.service
def test_get_pool_entries_accepts_flat_code_name_config(test_db) -> None:
    test_db.add(Config(key=CurrentHotService.CONFIG_KEY, value='{"600000": "浦发银行"}', description="flat pool"))
    test_db.commit()

    entries = CurrentHotService(test_db).get_pool_entries()

    assert len(entries) == 1
    assert entries[0].code == "600000"
    assert entries[0].name == "浦发银行"


@pytest.mark.service
def test_get_pool_entries_accepts_legacy_current_hot_pool_key(test_db) -> None:
    test_db.add(Config(key=CurrentHotService.LEGACY_CONFIG_KEY, value='{"600000": "浦发银行"}', description="legacy pool"))
    test_db.commit()

    entries = CurrentHotService(test_db).get_pool_entries()

    assert len(entries) == 1
    assert entries[0].code == "600000"
    assert entries[0].primary_sector == "周期性股票"


@pytest.mark.service
def test_load_financial_metrics_refreshes_missing_or_incomplete_cache(test_db) -> None:
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_db.add(Stock(code="000001", name="平安银行", market="SZ"))
    test_db.add(StockFinancial(code="600000", netprofit_yoy=8.0, roe=None))
    test_db.commit()

    service = CurrentHotService(test_db)
    with patch(
        "app.services.current_hot_service.FinancialDataService.get_or_refresh",
        return_value={
            "600000": {"netprofit_yoy": 12.3, "roe": 4.5},
            "000001": {"netprofit_yoy": 7.8, "roe": 6.1},
        },
    ) as mock_refresh:
        result = service._load_financial_metrics(["600000", "000001"])

    mock_refresh.assert_called_once_with(["600000", "000001"], refresh_incomplete=True)
    assert result["600000"]["netprofit_yoy"] == 12.3
    assert result["600000"]["roe"] == 4.5
    assert result["000001"]["netprofit_yoy"] == 7.8
    assert result["000001"]["roe"] == 6.1


@pytest.mark.service
def test_load_price_streak_days_uses_close_to_previous_close(test_db) -> None:
    dates = [date(2026, 5, day) for day in range(4, 9)]
    test_db.add_all([
        Stock(code="600000", name="连涨", market="SH"),
        Stock(code="600001", name="今日转跌", market="SH"),
        Stock(code="600002", name="平盘", market="SH"),
        Stock(code="600003", name="红K下跌", market="SH"),
    ])
    test_db.add_all([
        StockDaily(code="600000", trade_date=dates[0], open=10.0, close=9.8, high=10.1, low=9.7, volume=100),
        StockDaily(code="600000", trade_date=dates[1], open=10.0, close=10.2, high=10.3, low=9.9, volume=100),
        StockDaily(code="600000", trade_date=dates[2], open=10.1, close=10.3, high=10.4, low=10.0, volume=100),
        StockDaily(code="600000", trade_date=dates[3], open=10.2, close=10.4, high=10.5, low=10.1, volume=100),
        StockDaily(code="600000", trade_date=dates[4], open=10.3, close=10.5, high=10.6, low=10.2, volume=100),
        StockDaily(code="600001", trade_date=dates[3], open=10.0, close=10.2, high=10.3, low=9.9, volume=100),
        StockDaily(code="600001", trade_date=dates[4], open=10.2, close=10.0, high=10.3, low=9.9, volume=100),
        StockDaily(code="600002", trade_date=dates[4], open=10.0, close=10.0, high=10.1, low=9.9, volume=100),
        StockDaily(code="600003", trade_date=dates[3], open=10.0, close=10.2, high=10.3, low=9.9, volume=100),
        StockDaily(code="600003", trade_date=dates[4], open=9.9, close=10.1, high=10.2, low=9.8, volume=100),
    ])
    test_db.commit()

    result = CurrentHotService(test_db)._load_price_streak_days(
        ["600000", "600001", "600002", "600003"],
        dates[4],
    )

    assert result["600000"] == 4
    assert result["600001"] == -1
    assert result["600002"] == 0
    assert result["600003"] == -1


@pytest.mark.service
def test_load_price_position_pct_uses_recent_120_day_range(test_db) -> None:
    target_date = date(2026, 5, 8)
    test_db.add(Stock(code="600000", name="区间位置", market="SH"))
    test_db.add_all([
        StockDaily(code="600000", trade_date=date(2026, 5, 6), open=10.0, close=12.0, high=12.0, low=10.0, volume=100),
        StockDaily(code="600000", trade_date=date(2026, 5, 7), open=12.0, close=14.0, high=14.0, low=11.0, volume=100),
        StockDaily(code="600000", trade_date=target_date, open=13.0, close=13.0, high=15.0, low=12.0, volume=100),
    ])
    test_db.commit()

    result = CurrentHotService(test_db)._load_price_position_pct(["600000"], target_date)

    assert result["600000"] == 60.0


@pytest.mark.service
def test_generate_current_hot_persists_and_updates_consecutive_metrics(test_db) -> None:
    first_date = date(2026, 5, 7)
    second_date = date(2026, 5, 8)
    _seed_stock_history(test_db, "600000", second_date, base=10.0)
    _seed_stock_history(test_db, "688001", second_date, base=20.0)

    service = CurrentHotService(test_db)

    def fake_quant_review(code: str, df: pd.DataFrame, check_date: str) -> dict:
        score = 5.2 if code == "600000" else 4.1
        return {
            "score": score,
            "verdict": "PASS",
            "signal_type": "trend_start" if code == "600000" else "rebound",
            "comment": f"{code}-{check_date}",
            "signal_reasoning": None,
            "scores": {},
            "trend_reasoning": None,
            "position_reasoning": None,
            "volume_reasoning": None,
            "abnormal_move_reasoning": None,
        }

    with patch.object(
        CurrentHotService,
        "_load_pool_config",
        return_value={"测试主题": {"浦发银行": "600000", "测试科创": "688001"}},
    ), patch(
        "app.services.current_hot_service.analysis_service._quant_review_for_date",
        side_effect=fake_quant_review,
    ):
        first_payload = service.generate_for_trade_date(first_date)
        second_payload = service.generate_for_trade_date(second_date)

    assert first_payload["status"] == "ok"
    assert second_payload["status"] == "ok"

    first_run = test_db.query(CurrentHotRun).filter(CurrentHotRun.pick_date == first_date).one()
    second_run = test_db.query(CurrentHotRun).filter(CurrentHotRun.pick_date == second_date).one()
    assert first_run.candidate_count == 2
    assert first_run.trend_start_count == 1
    assert first_run.consecutive_candidate_count == 0
    assert second_run.candidate_count == 2
    assert second_run.trend_start_count == 1
    assert second_run.consecutive_candidate_count == 2

    first_candidates = (
        test_db.query(CurrentHotCandidate)
        .filter(CurrentHotCandidate.pick_date == first_date)
        .order_by(CurrentHotCandidate.code.asc())
        .all()
    )
    second_candidates = (
        test_db.query(CurrentHotCandidate)
        .filter(CurrentHotCandidate.pick_date == second_date)
        .order_by(CurrentHotCandidate.code.asc())
        .all()
    )
    assert [row.consecutive_days for row in first_candidates] == [1, 1]
    assert [row.consecutive_days for row in second_candidates] == [2, 2]

    results_payload = service.get_results(second_date.isoformat())
    assert [item["code"] for item in results_payload["results"]] == ["600000", "688001"]
    assert results_payload["results"][0]["total_score"] == 5.2
    assert test_db.query(CurrentHotAnalysisResult).count() == 4


@pytest.mark.service
def test_generate_current_hot_preview_realtime_appends_today_bar(test_db) -> None:
    today = date(2026, 5, 8)
    previous_trade_date = date(2026, 5, 7)
    _seed_stock_history(test_db, "600000", previous_trade_date, days=70, base=10.0)
    service = CurrentHotService(test_db)

    def fake_quant_review(code: str, df: pd.DataFrame, check_date: str) -> dict:
        assert check_date == today.isoformat()
        assert pd.Timestamp(df.iloc[-1]["date"]).date() == today
        assert df.iloc[-1]["close"] == 12.3
        return {
            "score": 6.0,
            "verdict": "PASS",
            "signal_type": "trend_start",
            "comment": "preview",
            "signal_reasoning": None,
            "scores": {},
            "trend_reasoning": None,
            "position_reasoning": None,
            "volume_reasoning": None,
            "abnormal_move_reasoning": None,
        }

    realtime_bar = RealtimeDailyBar(
        code="600000",
        trade_date=today,
        open=12.0,
        close=12.3,
        high=12.5,
        low=11.9,
        volume=456000,
        amount=5600000,
        turnover_rate=6.6,
        volume_ratio=1.7,
        total_mv=10_000_000_000,
        circ_mv=9_000_000_000,
        source="tencent_quote",
        quote_time="20260508150100",
    )

    with patch.object(
        CurrentHotService,
        "_load_pool_config",
        return_value={"测试主题": {"浦发银行": "600000"}},
    ), patch.object(
        service.realtime_daily_bar_service,
        "get_today",
        return_value=today,
    ), patch.object(
        service.realtime_daily_bar_service,
        "fetch_bars",
        return_value={"600000": realtime_bar},
    ), patch(
        "app.services.current_hot_service.analysis_service._build_hybrid_b1_selector",
        return_value=_FakeSelector(),
    ), patch(
        "app.services.current_hot_service.analysis_service._quant_review_for_date",
        side_effect=fake_quant_review,
    ):
        payload = service.generate_for_trade_date(preview_realtime=True, recalculate_consecutive=False)

    assert payload["status"] == "ok"
    assert payload["trade_date"] == today
    candidate = test_db.query(CurrentHotCandidate).filter(CurrentHotCandidate.pick_date == today, CurrentHotCandidate.code == "600000").one()
    assert candidate.close_price == 12.3
    assert candidate.turnover_rate == 6.6
    result = test_db.query(CurrentHotAnalysisResult).filter(CurrentHotAnalysisResult.pick_date == today, CurrentHotAnalysisResult.code == "600000").one()
    assert result.details_json["data_source"] == "preview_realtime"
    assert result.details_json["realtime_source"] == "tencent_quote"


@pytest.mark.service
def test_generate_current_hot_backfills_history_before_analysis(test_db) -> None:
    target_date = date(2026, 5, 8)
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_db.add(
        StockDaily(
            code="600000",
            trade_date=target_date,
            open=10.0,
            close=10.2,
            high=10.3,
            low=9.9,
            volume=100000,
        )
    )
    test_db.commit()

    def fake_fetch_daily_data(_self, code: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        del start_date, end_date
        rows: list[dict] = []
        current = target_date - timedelta(days=120)
        inserted = 0
        while inserted < 80:
            if current.weekday() < 5:
                base = 10.0 + inserted * 0.05
                rows.append(
                    {
                        "code": code,
                        "trade_date": current,
                        "open": base,
                        "high": base + 0.2,
                        "low": base - 0.1,
                        "close": base + 0.1,
                        "volume": 100000 + inserted * 100,
                    }
                )
                inserted += 1
            current += timedelta(days=1)
        return pd.DataFrame(rows)

    service = CurrentHotService(test_db)
    with patch.object(
        CurrentHotService,
        "_load_pool_config",
        return_value={"测试主题": {"浦发银行": "600000"}},
    ), patch(
        "app.services.current_hot_service.DailyDataService.fetch_daily_data",
        autospec=True,
        side_effect=fake_fetch_daily_data,
    ) as mock_fetch, patch(
        "app.services.current_hot_service.analysis_service._quant_review_for_date",
        return_value={
            "score": 5.6,
            "verdict": "PASS",
            "signal_type": "trend_start",
            "comment": "filled-history",
            "signal_reasoning": None,
            "scores": {},
            "trend_reasoning": None,
            "position_reasoning": None,
            "volume_reasoning": None,
            "abnormal_move_reasoning": None,
        },
    ):
        payload = service.generate_for_trade_date(target_date)

    assert payload["status"] == "ok"
    assert mock_fetch.call_count == 1
    candidate = test_db.query(CurrentHotCandidate).filter(CurrentHotCandidate.pick_date == target_date).one()
    analysis = test_db.query(CurrentHotAnalysisResult).filter(CurrentHotAnalysisResult.pick_date == target_date).one()
    assert candidate.kdj_j is not None
    assert candidate.b1_passed in {True, False, None}
    assert analysis.total_score == 5.6
    assert analysis.signal_type == "trend_start"
    assert test_db.query(StockDaily).filter(StockDaily.code == "600000").count() >= 60


@pytest.mark.service
def test_generate_current_hot_can_skip_remote_history_backfill(test_db) -> None:
    target_date = date(2026, 5, 8)
    test_db.add(Stock(code="688795", name="摩尔线程-U", market="SH", industry="半导体"))
    test_db.add(
        StockDaily(
            code="688795",
            trade_date=target_date,
            open=727.96,
            close=703.0,
            high=740.0,
            low=700.0,
            volume=100000,
            turnover_rate=13.1383,
            volume_ratio=0.78,
        )
    )
    test_db.commit()

    service = CurrentHotService(test_db)
    with patch.object(
        CurrentHotService,
        "_load_pool_config",
        return_value={"半导体": {"摩尔线程-U": "688795"}},
    ), patch(
        "app.services.current_hot_service.DailyDataService.fetch_daily_data",
    ) as mock_fetch:
        payload = service.generate_for_trade_date(target_date, backfill_missing_history=False)

    assert payload["status"] == "ok"
    assert mock_fetch.call_count == 0
    candidate = test_db.query(CurrentHotCandidate).filter(CurrentHotCandidate.pick_date == target_date).one()
    analysis = test_db.query(CurrentHotAnalysisResult).filter(CurrentHotAnalysisResult.pick_date == target_date).one()
    assert candidate.code == "688795"
    assert candidate.turnover_rate == 13.1383
    assert candidate.volume_ratio == 0.78
    assert candidate.b1_passed is False
    assert analysis.comment == "历史数据不足"
    assert analysis.turnover_rate == 13.1383
    assert analysis.volume_ratio == 0.78


@pytest.mark.service
def test_current_hot_change_pct_uses_previous_close(test_db) -> None:
    target_date = date(2026, 5, 8)
    test_db.add(Stock(code="688795", name="摩尔线程-U", market="SH", industry="半导体"))
    test_db.add_all(
        [
            StockDaily(
                code="688795",
                trade_date=date(2026, 5, 7),
                open=90.0,
                close=100.0,
                high=101.0,
                low=89.0,
                volume=100000,
            ),
            StockDaily(
                code="688795",
                trade_date=target_date,
                open=110.0,
                close=105.0,
                high=112.0,
                low=104.0,
                volume=100000,
                turnover_rate=13.1383,
                volume_ratio=0.78,
            ),
        ]
    )
    test_db.commit()

    payload = CurrentHotService(test_db).build_trade_snapshot("688795", target_date)

    assert payload["comment"] == "历史数据不足"
    assert payload["change_pct"] == pytest.approx(5.0)


@pytest.mark.service
def test_ensure_window_rebuilds_missing_trade_dates(test_db) -> None:
    trade_dates = [date(2026, 5, 7), date(2026, 5, 8)]
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_db.add_all([
        StockDaily(
            code="600000",
            trade_date=trade_date,
            open=10.0,
            close=10.2,
            high=10.3,
            low=9.9,
            volume=100000,
        )
        for trade_date in trade_dates
    ])
    test_db.commit()

    service = CurrentHotService(test_db)
    generated_dates: list[date] = []

    def fake_generate_for_trade_date(
        target_trade_date: date,
        reviewer: str = "quant",
        *,
        backfill_missing_history: bool = True,
        recalculate_consecutive: bool = True,
    ) -> dict:
        del backfill_missing_history, recalculate_consecutive
        generated_dates.append(target_trade_date)
        test_db.add(
            CurrentHotRun(
                pick_date=target_trade_date,
                status="success",
                candidate_count=1,
                analysis_count=1,
                trend_start_count=1,
                consecutive_candidate_count=0,
                reviewer=reviewer,
            )
        )
        test_db.add(
            CurrentHotCandidate(
                pick_date=target_trade_date,
                code="600000",
                sector_names_json=["测试主题"],
                board_group="other",
                open_price=10.0,
                close_price=10.2,
                change_pct=2.0,
                b1_passed=True,
                kdj_j=10.0,
            )
        )
        test_db.add(
            CurrentHotAnalysisResult(
                pick_date=target_trade_date,
                code="600000",
                reviewer=reviewer,
                b1_passed=True,
                verdict="PASS",
                total_score=5.1,
                signal_type="trend_start",
                comment="rebuilt",
                details_json={"comment": "rebuilt"},
            )
        )
        test_db.commit()
        return {"status": "ok"}

    with patch.object(service, "generate_for_trade_date", side_effect=fake_generate_for_trade_date):
        result = service.ensure_window(window_size=2)

    assert generated_dates == trade_dates
    assert result["rebuilt_dates"] == ["2026-05-07", "2026-05-08"]
    assert result["failed_dates"] == []
    assert [item["pick_date"] for item in result["summary"]["history"]] == ["2026-05-08", "2026-05-07"]
    assert all(item["status"] == "success" for item in result["summary"]["history"])


@pytest.mark.service
def test_ensure_window_recalculates_consecutive_metrics_once(test_db, mocker) -> None:
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    for trade_date in [date(2026, 5, 7), date(2026, 5, 8)]:
        test_db.add(
            StockDaily(
                code="600000",
                trade_date=trade_date,
                open=10.0,
                close=10.2,
                high=10.3,
                low=9.9,
                volume=100000,
            )
        )
    test_db.commit()

    service = CurrentHotService(test_db)
    generate_mock = mocker.patch.object(service, "generate_for_trade_date", return_value={"status": "ok", "generated_count": 1, "skipped_count": 0})
    recalc_mock = mocker.patch.object(CurrentHotService, "recalculate_consecutive_metrics", return_value={"candidate_rows": 2, "run_rows": 2, "days_with_consecutive_candidates": 1})

    result = service.ensure_window(window_size=2)

    assert result["failed_dates"] == []
    assert generate_mock.call_count == 2
    assert recalc_mock.call_count == 1
