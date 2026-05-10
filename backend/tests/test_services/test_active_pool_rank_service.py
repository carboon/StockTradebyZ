from contextlib import nullcontext
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from app.models import Stock, StockActivePoolRank, StockDaily
from app.services.active_pool_rank_service import active_pool_rank_service
from app.services.analysis_service import analysis_service


def _seed_daily_rows(test_db, code: str, start: date, volumes: list[float]) -> None:
    test_db.add(Stock(code=code, name=code, market="SZ"))
    for offset, volume in enumerate(volumes):
        trade_date = start + timedelta(days=offset)
        test_db.add(
            StockDaily(
                code=code,
                trade_date=trade_date,
                open=10.0,
                close=10.0,
                high=10.5,
                low=9.5,
                volume=volume,
            )
        )


@pytest.mark.service
def test_compute_active_pool_ranks_from_stock_daily(test_db) -> None:
    start = date(2026, 5, 4)
    target = date(2026, 5, 6)
    _seed_daily_rows(test_db, "000001", start, [100, 100, 100])
    _seed_daily_rows(test_db, "000002", start, [200, 200, 200])
    _seed_daily_rows(test_db, "000003", start, [300, 300, 300])
    test_db.commit()

    with patch("app.services.active_pool_rank_service.SessionLocal", return_value=nullcontext(test_db)):
        active_pool_rank_service.invalidate()
        result = active_pool_rank_service.compute_for_dates(
            [target],
            top_m=2,
            n_turnover_days=2,
            force=True,
        )
        rankings = active_pool_rank_service.get_rankings(
            start_date=target,
            end_date=target,
            target_codes={"000001", "000002", "000003"},
            top_m=2,
            n_turnover_days=2,
        )
        pool_sets = active_pool_rank_service.get_pool_sets(
            start_date=target,
            end_date=target,
            top_m=2,
            n_turnover_days=2,
        )

    assert result["success"] is True
    assert result["inserted_count"] == 3
    assert test_db.query(StockActivePoolRank).count() == 3
    assert rankings is not None
    assert rankings["000003"][pd.Timestamp(target)] == 1
    assert rankings["000002"][pd.Timestamp(target)] == 2
    assert rankings["000001"][pd.Timestamp(target)] == 3
    assert pool_sets == {pd.Timestamp(target): {"000002", "000003"}}


@pytest.mark.service
def test_analysis_service_active_pool_rank_uses_persisted_factors(test_db) -> None:
    trade_date = date(2026, 5, 6)
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_db.add(
        StockActivePoolRank(
            code="600000",
            trade_date=trade_date,
            top_m=2000,
            n_turnover_days=43,
            turnover_n=123456.0,
            active_pool_rank=88,
            in_active_pool=True,
        )
    )
    test_db.commit()

    with (
        patch("app.services.active_pool_rank_service.SessionLocal", return_value=nullcontext(test_db)),
        patch.object(active_pool_rank_service, "get_date_payload", side_effect=AssertionError("不应加载整日全市场 payload")),
    ):
        active_pool_rank_service.invalidate()
        rankings = analysis_service._safe_build_active_pool_rankings(
            start_ts=pd.Timestamp(trade_date),
            end_ts=pd.Timestamp(trade_date),
            preselect_cfg={"global": {"top_m": 2000, "n_turnover_days": 43}},
            target_codes={"600000"},
        )

    assert rankings is not None
    assert rankings["600000"][pd.Timestamp(trade_date)] == 88


@pytest.mark.service
def test_get_rankings_queries_target_codes_without_full_date_payload(test_db) -> None:
    trade_date = date(2026, 5, 6)
    test_db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_db.add(Stock(code="000001", name="平安银行", market="SZ"))
    test_db.add_all([
        StockActivePoolRank(
            code="600000",
            trade_date=trade_date,
            top_m=2000,
            n_turnover_days=43,
            turnover_n=123456.0,
            active_pool_rank=88,
            in_active_pool=True,
        ),
        StockActivePoolRank(
            code="000001",
            trade_date=trade_date,
            top_m=2000,
            n_turnover_days=43,
            turnover_n=999999.0,
            active_pool_rank=1,
            in_active_pool=True,
        ),
    ])
    test_db.commit()

    with (
        patch("app.services.active_pool_rank_service.SessionLocal", return_value=nullcontext(test_db)),
        patch.object(active_pool_rank_service, "get_date_payload", side_effect=AssertionError("不应加载整日全市场 payload")),
    ):
        active_pool_rank_service.invalidate()
        rankings = active_pool_rank_service.get_rankings(
            start_date=trade_date,
            end_date=trade_date,
            target_codes={"600000"},
            top_m=2000,
            n_turnover_days=43,
        )

    assert rankings is not None
    assert rankings == {"600000": {pd.Timestamp(trade_date): 88}}
