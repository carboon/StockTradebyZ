from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from pipeline.review_prefilter import TushareMetadataStore


def test_index_daily_uses_sw_daily_for_si_and_recovers_empty_cache(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    empty_cache = cache_dir / "index_daily" / "801170.SI_20190101_20260429.csv"
    empty_cache.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=["ts_code", "trade_date", "close"]).to_csv(empty_cache, index=False)

    sw_daily_df = pd.DataFrame(
        {
            "ts_code": ["801170.SI"],
            "trade_date": ["20260429"],
            "close": [1234.56],
        }
    )

    mock_pro = MagicMock()
    mock_pro.sw_daily.return_value = sw_daily_df
    mock_pro.index_daily.return_value = pd.DataFrame()

    with patch("tushare.pro_api", return_value=mock_pro):
        with patch("pipeline.review_prefilter.acquire_tushare_slot", lambda endpoint: None):
            store = TushareMetadataStore(cache_dir=cache_dir, token="test_token_123456")
            frame = store.index_daily("801170.SI", "20190101", "20260429")

    assert len(frame) == 1
    assert frame.iloc[0]["ts_code"] == "801170.SI"
    mock_pro.sw_daily.assert_called_once_with(
        ts_code="801170.SI",
        start_date="20190101",
        end_date="20260429",
        fields="ts_code,trade_date,close",
    )
    mock_pro.index_daily.assert_not_called()

    cached = pd.read_csv(empty_cache)
    assert not cached.empty
    assert cached.iloc[0]["ts_code"] == "801170.SI"


def test_index_daily_uses_latest_local_trade_date_for_default_end(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    index_df = pd.DataFrame(
        {
            "ts_code": ["000905.SH"],
            "trade_date": ["20260522"],
            "close": [5012.34],
        }
    )

    mock_pro = MagicMock()
    mock_pro.index_daily.return_value = index_df

    with patch("tushare.pro_api", return_value=mock_pro):
        with patch("pipeline.review_prefilter.acquire_tushare_slot", lambda endpoint: None):
            with patch("pipeline.review_prefilter._default_index_end_date", return_value="20260522"):
                store = TushareMetadataStore(cache_dir=cache_dir, token="test_token_123456")
                frame = store.index_daily("000905.SH", "20190101")

    assert len(frame) == 1
    mock_pro.index_daily.assert_called_once_with(
        ts_code="000905.SH",
        start_date="20190101",
        end_date="20260522",
        fields="ts_code,trade_date,close",
    )
    assert (cache_dir / "index_daily" / "000905.SH_20190101_20260522.csv").exists()
