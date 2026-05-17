"""
review_scorecard.py
~~~~~~~~~~~~~~~~~~~
Code-led review scoring for the final chart review stage.

The scorecard turns OHLCV history into stable four-dimensional scores and a
structured evidence packet. The final review stage is fully deterministic:
no chart image is read and no model is called.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboard.components.charts import _calc_zx_lines  # noqa: E402
try:
    from review_params import ReviewRuleParams
except ImportError:
    from agent.review_params import ReviewRuleParams
try:
    from pipeline.db import read_one_history
except Exception:
    read_one_history = None


WEIGHTS = {
    "trend_structure": 0.20,
    "price_position": 0.20,
    "volume_behavior": 0.30,
    "previous_abnormal_move": 0.30,
}


def _round_score(value: float) -> float:
    return round(float(max(1.0, min(5.0, value))), 1)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(out):
        return default
    return out


def _pct(a: float, b: float) -> float:
    if b == 0 or not np.isfinite(b):
        return 0.0
    return (a / b - 1.0) * 100.0


def _score_from_thresholds(value: float, thresholds: list[tuple[float, float]]) -> float:
    for limit, score in thresholds:
        if value >= limit:
            return score
    return 1.0


def _verdict(total_score: float, volume_score: float, params: ReviewRuleParams) -> str:
    if volume_score <= params.volume_fail_max:
        return "FAIL"
    if total_score >= params.pass_score_min:
        return "PASS"
    if total_score >= params.watch_score_min:
        return "WATCH"
    return "FAIL"


def _signal_type(scores: dict[str, float], evidence: dict[str, Any], params: ReviewRuleParams) -> str:
    if evidence.get("limit_status") in {"D", "Z"}:
        return "distribution_risk"
    if (
        evidence.get("range_position_120d", 0) >= params.high_position_risk
        and evidence.get("close_vs_zxdq_pct", 0) > params.overheat_bias_pct
    ) or evidence.get("has_recent_destructive_bearish_volume", False):
        return "distribution_risk"
    if (
        evidence.get("limit_times", 0) >= 3
        and evidence.get("range_position_120d", 0) >= params.multi_limit_high_position
        and evidence.get("close_vs_zxdq_pct", 0) > params.multi_limit_bias_pct
    ):
        return "distribution_risk"

    if (
        scores["trend_structure"] >= params.trend_start_min_trend
        and scores["price_position"] >= params.trend_start_min_position
        and scores["volume_behavior"] >= params.trend_start_min_volume
        and evidence.get("range_position_120d", 0) < params.trend_start_max_range_position
        and evidence.get("limit_status") != "Z"
    ):
        return "trend_start"

    return "rebound"


class ReviewScorecardBuilder:
    """Builds deterministic review scores from local OHLCV CSV data."""

    def __init__(
        self,
        raw_dir: str | Path,
        *,
        min_bars: int = 120,
        tushare_start: str = "20190101",
        overlap_days: int = 5,
        review_data_dir: str | Path | None = None,
        use_tushare_review_data: bool = True,
        rule_params: ReviewRuleParams | None = None,
        db_path: str | Path | None = None,
    ):
        self.raw_dir = Path(raw_dir)
        self.min_bars = int(min_bars)
        self.tushare_start = str(tushare_start)
        self.overlap_days = int(overlap_days)
        self.review_data_dir = Path(review_data_dir) if review_data_dir else _ROOT / "data" / "tushare_review"
        self.use_tushare_review_data = bool(use_tushare_review_data)
        self.rule_params = rule_params or ReviewRuleParams()
        default_raw = (_ROOT / "data" / "raw").resolve()
        self.db_path = Path(db_path) if db_path else ((_ROOT / "data" / "stocktrade.duckdb") if self.raw_dir.resolve() == default_raw else None)
        self._pro = None

    def build(self, code: str, pick_date: str, candidate: dict[str, Any] | None = None) -> dict[str, Any]:
        df = self._load_history(code, pick_date)
        review_data = self._load_review_data(code, pick_date)
        return build_scorecard_from_df(
            df,
            code=code,
            pick_date=pick_date,
            candidate=candidate or {},
            review_data=review_data,
            rule_params=self.rule_params,
        )

    def _load_history(self, code: str, pick_date: str) -> pd.DataFrame:
        path = self.raw_dir / f"{code}.csv"
        df = self._read_local_history(path, code, pick_date)
        if self._history_is_ready(df, pick_date):
            return df

        df = self._fetch_and_merge_history(code, pick_date, path, df)
        if not self._history_is_ready(df, pick_date):
            latest = "" if df.empty else pd.to_datetime(df["date"].max()).strftime("%Y-%m-%d")
            raise ValueError(
                f"{code} 行情数据不足：需要至少 {self.min_bars} 根且覆盖 {pick_date}，"
                f"当前 {len(df)} 根，最新日期 {latest or '无'}"
            )
        return df

    @staticmethod
    def _normalize_history(df: pd.DataFrame, path: Path | None = None) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df.columns = [c.lower() for c in df.columns]
        if "trade_date" in df.columns and "date" not in df.columns:
            df = df.rename(columns={"trade_date": "date"})
        if "vol" in df.columns and "volume" not in df.columns:
            df = df.rename(columns={"vol": "volume"})
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            label = str(path) if path else "行情数据"
            raise ValueError(f"{label} 缺少列: {sorted(missing)}")

        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        df["date"] = pd.to_datetime(df["date"])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.dropna(subset=["date", "open", "high", "low", "close", "volume"])
        df = df.drop_duplicates(subset="date", keep="last")
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def _read_local_history(self, path: Path, code: str, pick_date: str) -> pd.DataFrame:
        if read_one_history is not None:
            try:
                if self.db_path is None:
                    raise RuntimeError("DuckDB history disabled for this raw_dir")
                df_db = read_one_history(code, self.db_path, end_date=pick_date)
                df_db = self._normalize_history(df_db)
                if not df_db.empty:
                    return df_db
            except Exception:
                pass
        if not path.exists():
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        df = pd.read_csv(path)
        df = self._normalize_history(df, path)
        df = df[df["date"] <= pd.to_datetime(pick_date)].reset_index(drop=True)
        return df

    def _history_is_ready(self, df: pd.DataFrame, pick_date: str) -> bool:
        if df.empty or len(df) < self.min_bars:
            return False
        pick_ts = pd.to_datetime(pick_date)
        return bool(pd.to_datetime(df["date"].max()) >= pick_ts)

    def _fetch_and_merge_history(
        self,
        code: str,
        pick_date: str,
        path: Path,
        local_df: pd.DataFrame,
    ) -> pd.DataFrame:
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            if path.exists():
                raise ValueError(f"{code} 本地行情不足，且未设置 TUSHARE_TOKEN，无法自动补齐。")
            raise FileNotFoundError(f"找不到原始行情文件: {path}，且未设置 TUSHARE_TOKEN，无法自动补齐。")

        start = self.tushare_start
        if not local_df.empty:
            last_ts = pd.to_datetime(local_df["date"].max())
            fetch_start = last_ts - pd.Timedelta(days=max(0, self.overlap_days - 1))
            start = fetch_start.strftime("%Y%m%d")
        end = pd.to_datetime(pick_date).strftime("%Y%m%d")

        pro = self._tushare_pro()
        if pro is None:
            raise RuntimeError("未设置 TUSHARE_TOKEN，无法自动补齐行情。")
        try:
            import tushare as ts
        except ImportError as exc:
            raise RuntimeError("自动补齐行情需要安装 tushare。") from exc
        fetched = ts.pro_bar(
            ts_code=_to_ts_code(code),
            adj="qfq",
            start_date=start,
            end_date=end,
            freq="D",
            api=pro,
        )
        fetched_df = self._normalize_history(fetched)
        merged = pd.concat([local_df, fetched_df], ignore_index=True)
        merged = self._normalize_history(merged)
        merged = merged[merged["date"] <= pd.to_datetime(pick_date)].reset_index(drop=True)

        self.raw_dir.mkdir(parents=True, exist_ok=True)
        merged.to_csv(path, index=False)
        return merged

    def _tushare_pro(self):
        if self._pro is not None:
            return self._pro
        token = os.environ.get("TUSHARE_TOKEN")
        if not token:
            return None
        try:
            import tushare as ts
        except ImportError as exc:
            raise RuntimeError("自动补齐行情需要安装 tushare。") from exc
        ts.set_token(token)
        self._pro = ts.pro_api()
        return self._pro

    def _load_review_data(self, code: str, pick_date: str) -> dict[str, Any]:
        empty = {
            "daily_basic": {},
            "moneyflow": {},
            "limit": {},
            "available": False,
            "errors": [],
        }
        if not self.use_tushare_review_data:
            return empty
        if not os.environ.get("TUSHARE_TOKEN"):
            empty["errors"].append("TUSHARE_TOKEN 未设置，跳过扩展复评数据。")
            return empty

        ts_code = _to_ts_code(code)
        trade_date = pd.to_datetime(pick_date).strftime("%Y%m%d")
        out: dict[str, Any] = {
            "daily_basic": self._load_daily_basic(ts_code, trade_date),
            "moneyflow": self._load_moneyflow(ts_code, trade_date),
            "limit": self._load_limit_event(ts_code, trade_date),
            "available": True,
            "errors": [],
        }
        for key in ("daily_basic", "moneyflow", "limit"):
            err = out[key].pop("_error", "")
            if err:
                out["errors"].append(err)
        return out

    def _load_daily_basic(self, ts_code: str, trade_date: str) -> dict[str, Any]:
        fields = "ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,total_mv,circ_mv,float_share,free_share"
        return self._load_daily_row_cache(
            "daily_basic",
            ts_code,
            trade_date,
            lambda: self._tushare_pro().daily_basic(ts_code="", trade_date=trade_date, fields=fields),
            label=f"daily_basic {ts_code} {trade_date}",
        )

    def _load_moneyflow(self, ts_code: str, trade_date: str) -> dict[str, Any]:
        fields = (
            "ts_code,trade_date,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,"
            "net_mf_amount,buy_lg_vol,sell_lg_vol,buy_elg_vol,sell_elg_vol"
        )
        return self._load_daily_row_cache(
            "moneyflow",
            ts_code,
            trade_date,
            lambda: self._tushare_pro().moneyflow(trade_date=trade_date, fields=fields),
            label=f"moneyflow {ts_code} {trade_date}",
        )

    def _load_limit_event(self, ts_code: str, trade_date: str) -> dict[str, Any]:
        fields = (
            "ts_code,trade_date,limit,open_times,limit_times,fd_amount,first_time,last_time,"
            "up_stat,turnover_ratio,float_mv,total_mv,pct_chg"
        )
        return self._load_daily_row_cache(
            "limit_list_d",
            ts_code,
            trade_date,
            lambda: self._tushare_pro().limit_list_d(trade_date=trade_date, fields=fields),
            label=f"limit_list_d {ts_code} {trade_date}",
        )

    def _load_daily_row_cache(self, kind: str, ts_code: str, trade_date: str, fetcher, *, label: str) -> dict[str, Any]:
        date_dir = self.review_data_dir / kind / trade_date
        code_cache = date_dir / f"{_plain_code(ts_code)}.csv"
        all_cache = date_dir / "_all.csv"
        try:
            if code_cache.exists():
                df = pd.read_csv(code_cache)
            else:
                if all_cache.exists():
                    df_all = pd.read_csv(all_cache)
                else:
                    df_all = fetcher()
                    if df_all is None:
                        df_all = pd.DataFrame()
                    date_dir.mkdir(parents=True, exist_ok=True)
                    df_all.to_csv(all_cache, index=False)
                df = self._select_ts_code(df_all, ts_code)
                if not df.empty:
                    date_dir.mkdir(parents=True, exist_ok=True)
                    df.to_csv(code_cache, index=False)
            if df is None or df.empty:
                return {}
            return df.iloc[0].to_dict()
        except Exception as exc:
            return {"_error": f"{label} 获取失败: {exc}"}

    @staticmethod
    def _select_ts_code(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
        if df is None or df.empty or "ts_code" not in df.columns:
            return pd.DataFrame()
        return df[df["ts_code"].astype(str).str.upper() == str(ts_code).upper()].head(1).copy()

    @staticmethod
    def _load_one_row_cache(cache_path: Path, fetcher, *, label: str) -> dict[str, Any]:
        try:
            if cache_path.exists():
                df = pd.read_csv(cache_path)
            else:
                df = fetcher()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                if df is None:
                    df = pd.DataFrame()
                df.to_csv(cache_path, index=False)
            if df is None or df.empty:
                return {}
            row = df.iloc[0].to_dict()
            return {str(k).lower(): _json_scalar(v) for k, v in row.items()}
        except Exception as exc:
            return {"_error": f"{label} 获取失败：{exc}"}


def build_scorecard_from_df(
    df: pd.DataFrame,
    *,
    code: str = "",
    pick_date: str = "",
    candidate: dict[str, Any] | None = None,
    review_data: dict[str, Any] | None = None,
    rule_params: ReviewRuleParams | None = None,
) -> dict[str, Any]:
    """Pure function used by tests and the review runner."""
    candidate = candidate or {}
    review_data = review_data or {}
    params = rule_params or ReviewRuleParams()
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)

    zxdq, zxdkx = _calc_zx_lines(d)
    d["_zxdq"] = zxdq.values
    d["_zxdkx"] = zxdkx.values
    d["_ret"] = d["close"].pct_change()
    d["_vol_ma5"] = d["volume"].rolling(5, min_periods=1).mean()
    d["_vol_ma20"] = d["volume"].rolling(20, min_periods=1).mean()
    d["_ma5"] = d["close"].rolling(5, min_periods=1).mean()
    d["_ma10"] = d["close"].rolling(10, min_periods=1).mean()
    d["_ma20"] = d["close"].rolling(20, min_periods=1).mean()
    d["_ma60"] = d["close"].rolling(60, min_periods=1).mean()

    main = d.tail(120).copy()
    recent = d.tail(60).copy()
    last = d.iloc[-1]
    close = _safe_float(last["close"])
    zxdq_last = _safe_float(last["_zxdq"])
    zxdkx_last = _safe_float(last["_zxdkx"])

    high_120 = _safe_float(main["high"].max(), close)
    low_120 = _safe_float(main["low"].min(), close)
    high_60 = _safe_float(recent["high"].max(), close)
    low_60 = _safe_float(recent["low"].min(), close)
    range_span = high_120 - low_120
    range_position = 0.5 if range_span <= 0 else (close - low_120) / range_span

    close_vs_zxdq_pct = _pct(close, zxdq_last)
    close_vs_zxdkx_pct = _pct(close, zxdkx_last)
    ma5_last = _safe_float(last["_ma5"], close)
    ma10_last = _safe_float(last["_ma10"], close)
    ma20_last = _safe_float(last["_ma20"], close)
    ma60_last = _safe_float(last["_ma60"], close)
    zxdq_slope_5d = _pct(zxdq_last, _safe_float(d["_zxdq"].iloc[-6], zxdq_last)) if len(d) >= 6 else 0.0
    zxdkx_slope_10d = _pct(zxdkx_last, _safe_float(d["_zxdkx"].iloc[-11], zxdkx_last)) if len(d) >= 11 else 0.0
    close_slope_20d = _pct(close, _safe_float(d["close"].iloc[-21], close)) if len(d) >= 21 else 0.0
    distance_to_high_60d_pct = _pct(close, high_60)
    distance_to_high_120d_pct = _pct(close, high_120)
    distance_from_low_60d_pct = _pct(close, low_60)
    volume_ratio_5d_20d = _safe_float(last["_vol_ma5"]) / max(_safe_float(last["_vol_ma20"]), 1e-9)

    up_days = d.tail(20)[d.tail(20)["close"] >= d.tail(20)["open"]]
    down_days = d.tail(20)[d.tail(20)["close"] < d.tail(20)["open"]]
    up_vol_mean = _safe_float(up_days["volume"].mean(), _safe_float(d.tail(20)["volume"].mean()))
    down_vol_mean = _safe_float(down_days["volume"].mean(), up_vol_mean)
    up_down_volume_ratio_20d = up_vol_mean / max(down_vol_mean, 1e-9)

    last_up_leg = d.tail(15)
    pullback = last_up_leg[last_up_leg["close"] < last_up_leg["open"]].tail(3)
    advance = last_up_leg[last_up_leg["close"] >= last_up_leg["open"]].tail(5)
    pullback_volume_shrink_ratio = (
        _safe_float(pullback["volume"].mean(), _safe_float(last_up_leg["volume"].mean()))
        / max(_safe_float(advance["volume"].mean(), _safe_float(last_up_leg["volume"].mean())), 1e-9)
    )

    max_vol_idx = int(recent["volume"].idxmax())
    max_vol_row = d.loc[max_vol_idx]
    max_volume_day_is_bullish = bool(max_vol_row["close"] >= max_vol_row["open"])
    has_recent_destructive_bearish_volume = bool(
        ((recent["close"] < recent["open"]) & (recent["volume"] > recent["volume"].rolling(20, min_periods=1).mean() * params.destructive_volume_ratio)).tail(20).any()
    )

    abnormal = _find_abnormal_bull_day(recent, params)
    abnormal_bull_day_gain_pct = abnormal["gain_pct"]
    abnormal_bull_day_volume_ratio = abnormal["volume_ratio"]
    abnormal_follow_through_pct = _pct(close, abnormal["close"]) if abnormal["close"] > 0 else 0.0
    weekly = _weekly_trend_evidence(d)
    external = _external_review_evidence(review_data)
    visual_check = _visual_check(
        range_position=range_position,
        close_vs_zxdq_pct=close_vs_zxdq_pct,
        destructive=has_recent_destructive_bearish_volume,
        volume_ratio=volume_ratio_5d_20d,
        limit_status=external["limit_status"],
        open_times=external["limit_open_times"],
    )

    evidence = {
        "bars_available": int(len(d)),
        "strategy": candidate.get("strategy", ""),
        "candidate_close": _safe_float(candidate.get("close"), close),
        "close": round(close, 4),
        "ma5": round(ma5_last, 4),
        "ma10": round(ma10_last, 4),
        "ma20": round(ma20_last, 4),
        "ma60": round(ma60_last, 4),
        "daily_ma_bull": bool(ma5_last > ma10_last > ma20_last),
        "zxdq": round(zxdq_last, 4),
        "zxdkx": round(zxdkx_last, 4),
        "close_vs_zxdq_pct": round(close_vs_zxdq_pct, 2),
        "close_vs_zxdkx_pct": round(close_vs_zxdkx_pct, 2),
        "zxdq_slope_5d": round(zxdq_slope_5d, 2),
        "zxdkx_slope_10d": round(zxdkx_slope_10d, 2),
        "close_slope_20d": round(close_slope_20d, 2),
        "range_position_120d": round(float(max(0.0, min(1.0, range_position))), 3),
        "distance_to_high_60d_pct": round(distance_to_high_60d_pct, 2),
        "distance_to_high_120d_pct": round(distance_to_high_120d_pct, 2),
        "distance_from_low_60d_pct": round(distance_from_low_60d_pct, 2),
        "volume_ratio_5d_20d": round(volume_ratio_5d_20d, 2),
        "up_down_volume_ratio_20d": round(up_down_volume_ratio_20d, 2),
        "pullback_volume_shrink_ratio": round(pullback_volume_shrink_ratio, 2),
        "max_volume_day_is_bullish": max_volume_day_is_bullish,
        "has_recent_destructive_bearish_volume": has_recent_destructive_bearish_volume,
        "abnormal_bull_day_date": abnormal["date"],
        "abnormal_bull_day_gain_pct": round(abnormal_bull_day_gain_pct, 2),
        "abnormal_bull_day_volume_ratio": round(abnormal_bull_day_volume_ratio, 2),
        "abnormal_bull_day_breaks_20d_high": abnormal["breaks_20d_high"],
        "abnormal_follow_through_pct": round(abnormal_follow_through_pct, 2),
        "weekly_trend": weekly["trend"],
        "weekly_ma_bull": weekly["ma_bull"],
        "weekly_close_slope_4w": weekly["close_slope_4w"],
        "tushare_review_data_available": external["available"],
        "tushare_review_data_errors": external["errors"],
        "turnover_rate": external["turnover_rate"],
        "turnover_rate_f": external["turnover_rate_f"],
        "tushare_volume_ratio": external["volume_ratio"],
        "total_mv": external["total_mv"],
        "circ_mv": external["circ_mv"],
        "net_mf_amount": external["net_mf_amount"],
        "large_net_amount": external["large_net_amount"],
        "extra_large_net_amount": external["extra_large_net_amount"],
        "main_net_amount_ratio": external["main_net_amount_ratio"],
        "large_order_balance": external["large_order_balance"],
        "limit_status": external["limit_status"],
        "limit_open_times": external["limit_open_times"],
        "limit_times": external["limit_times"],
        "limit_fd_amount": external["limit_fd_amount"],
        "limit_turnover_ratio": external["limit_turnover_ratio"],
        "visual_check": visual_check,
    }

    scores = {
        "trend_structure": _score_trend(evidence),
        "price_position": _score_position(evidence),
        "volume_behavior": _score_volume(evidence, params),
        "previous_abnormal_move": _score_abnormal(evidence, params),
    }
    total = round(sum(scores[k] * WEIGHTS[k] for k in WEIGHTS), 1)
    verdict = _verdict(total, scores["volume_behavior"], params)
    signal = _signal_type(scores, evidence, params)
    reasoning = _build_reasoning(scores, evidence, signal, verdict)

    return {
        "code": code,
        "date": pick_date,
        "weights": WEIGHTS.copy(),
        "review_thresholds": params.to_dict(),
        "scores": scores,
        "evidence": evidence,
        "code_total_score": total,
        "total_score": total,
        "signal_type": signal,
        "verdict": verdict,
        "trend_reasoning": reasoning["trend_reasoning"],
        "position_reasoning": reasoning["position_reasoning"],
        "volume_reasoning": reasoning["volume_reasoning"],
        "abnormal_move_reasoning": reasoning["abnormal_move_reasoning"],
        "signal_reasoning": reasoning["signal_reasoning"],
        "visual_check": visual_check,
        "comment": reasoning["comment"],
        "ai_adjustment": 0.0,
        "final_score_source": "code_scorecard",
    }


def _score_trend(e: dict[str, Any]) -> float:
    score = 2.5
    if e["close_vs_zxdq_pct"] >= 0:
        score += 0.5
    if e["close_vs_zxdkx_pct"] >= 0:
        score += 0.7
    if e["zxdq_slope_5d"] > 1:
        score += 0.7
    elif e["zxdq_slope_5d"] > 0:
        score += 0.4
    if e["zxdkx_slope_10d"] > 0:
        score += 0.4
    if e["close_slope_20d"] > 8:
        score += 0.4
    elif e["close_slope_20d"] < -5:
        score -= 0.7
    if e["close_vs_zxdq_pct"] < -5 or e["close_vs_zxdkx_pct"] < -8:
        score -= 0.8
    return _round_score(score)


def _score_position(e: dict[str, Any]) -> float:
    pos = e["range_position_120d"]
    dist_high = e["distance_to_high_60d_pct"]
    bias = e["close_vs_zxdq_pct"]
    score = _score_from_thresholds(
        pos,
        [
            (0.82, 2.7),
            (0.62, 4.0),
            (0.38, 4.5),
            (0.18, 3.6),
        ],
    )
    if -8 <= dist_high <= -1:
        score += 0.4
    elif dist_high >= -1:
        score -= 0.3
    if bias > 12:
        score -= 1.0
    elif bias > 8:
        score -= 0.5
    if e["distance_from_low_60d_pct"] > 80:
        score -= 0.5
    return _round_score(score)


def _score_volume(e: dict[str, Any], params: ReviewRuleParams) -> float:
    score = 3.0
    if e["volume_ratio_5d_20d"] >= 1.5:
        score += 0.7
    elif e["volume_ratio_5d_20d"] >= 1.1:
        score += 0.3
    elif e["volume_ratio_5d_20d"] < 0.7:
        score -= 0.4

    if e["up_down_volume_ratio_20d"] >= 1.3:
        score += 0.7
    elif e["up_down_volume_ratio_20d"] < 0.8:
        score -= 0.8

    if e["pullback_volume_shrink_ratio"] <= 0.65:
        score += 0.7
    elif e["pullback_volume_shrink_ratio"] > 1.1:
        score -= 0.7

    if e["max_volume_day_is_bullish"]:
        score += 0.4
    else:
        score -= 0.8

    turnover_f = e.get("turnover_rate_f")
    if turnover_f is not None:
        if params.turnover_f_good_low <= turnover_f <= params.turnover_f_good_high:
            score += 0.4
        elif turnover_f > params.turnover_f_hot:
            score -= 0.7
        elif turnover_f < params.turnover_f_cold:
            score -= 0.3

    ts_volume_ratio = e.get("tushare_volume_ratio")
    if ts_volume_ratio is not None:
        if params.tushare_volume_good_low <= ts_volume_ratio <= params.tushare_volume_good_high:
            score += 0.3
        elif ts_volume_ratio > params.tushare_volume_hot and e["range_position_120d"] >= 0.78:
            score -= 0.6

    if e.get("main_net_amount_ratio") is not None:
        if e["main_net_amount_ratio"] >= params.main_net_confirm_pct:
            score += 0.4
        elif e["main_net_amount_ratio"] <= params.main_net_outflow_pct:
            score -= 0.6
    elif e.get("large_order_balance") is not None:
        if e["large_order_balance"] >= 0.2:
            score += 0.3
        elif e["large_order_balance"] <= -0.2:
            score -= 0.4

    if e["has_recent_destructive_bearish_volume"]:
        score -= 1.5
    if e.get("limit_status") == "Z":
        score -= 0.5
    return _round_score(score)


def _score_abnormal(e: dict[str, Any], params: ReviewRuleParams) -> float:
    if not e["abnormal_bull_day_date"]:
        return 2.2
    score = 2.8
    if e["abnormal_bull_day_gain_pct"] >= params.abnormal_gain_strong:
        score += 0.8
    elif e["abnormal_bull_day_gain_pct"] >= params.abnormal_gain_medium:
        score += 0.4
    if e["abnormal_bull_day_volume_ratio"] >= params.abnormal_volume_ratio_strong:
        score += 0.9
    elif e["abnormal_bull_day_volume_ratio"] >= params.abnormal_volume_ratio_medium:
        score += 0.5
    if e.get("abnormal_bull_day_breaks_20d_high"):
        score += 0.4
    if e.get("main_net_amount_ratio") is not None:
        if e["main_net_amount_ratio"] >= params.abnormal_main_net_confirm_pct:
            score += 0.5
        elif e["main_net_amount_ratio"] <= params.abnormal_main_net_outflow_pct:
            score -= 0.7
    if e.get("limit_status") == "U":
        score += 0.4
        if e.get("limit_open_times", 0) == 0:
            score += 0.2
        if e.get("limit_times", 0) >= 3 and e["range_position_120d"] >= 0.82:
            score -= 0.6
    elif e.get("limit_status") == "Z":
        score -= 0.8
    elif e.get("limit_status") == "D":
        score -= 1.0
    if 0 <= e["abnormal_follow_through_pct"] <= params.abnormal_follow_through_ok_max:
        score += 0.4
    elif e["abnormal_follow_through_pct"] > params.abnormal_follow_through_hot:
        score -= 1.0
    if e["has_recent_destructive_bearish_volume"]:
        score -= 0.8
    return _round_score(score)


def _find_abnormal_bull_day(df: pd.DataFrame, params: ReviewRuleParams) -> dict[str, Any]:
    if df.empty:
        return {"date": "", "gain_pct": 0.0, "volume_ratio": 0.0, "close": 0.0, "breaks_20d_high": False}

    d = df.copy()
    d["_gain_pct"] = (d["close"] / d["open"] - 1.0) * 100.0
    d["_vol_ratio"] = d["volume"] / d["volume"].rolling(20, min_periods=1).mean().replace(0, np.nan)
    d["_prior_20d_high"] = d["high"].rolling(20, min_periods=3).max().shift(1)
    d["_breaks_20d_high"] = d["close"] > d["_prior_20d_high"].fillna(d["high"])
    mask = (
        (d["close"] >= d["open"])
        & (d["_gain_pct"] >= params.abnormal_gain_min)
        & (d["_vol_ratio"] >= params.abnormal_volume_ratio_min)
    )
    if not mask.any():
        return {"date": "", "gain_pct": 0.0, "volume_ratio": 0.0, "close": 0.0, "breaks_20d_high": False}

    candidates = d[mask].copy()
    candidates["_rank"] = candidates["_gain_pct"] * candidates["_vol_ratio"] + candidates["_breaks_20d_high"].astype(float) * 2.0
    row = candidates.sort_values("_rank").iloc[-1]
    return {
        "date": pd.to_datetime(row["date"]).strftime("%Y-%m-%d"),
        "gain_pct": _safe_float(row["_gain_pct"]),
        "volume_ratio": _safe_float(row["_vol_ratio"]),
        "close": _safe_float(row["close"]),
        "breaks_20d_high": bool(row["_breaks_20d_high"]),
    }


def _to_ts_code(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _plain_code(ts_code: str) -> str:
    return str(ts_code).split(".", 1)[0].zfill(6)


def _json_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def _optional_float(row: dict[str, Any], key: str) -> float | None:
    if key not in row or row.get(key) is None:
        return None
    try:
        out = float(row[key])
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    return out


def _optional_int(row: dict[str, Any], key: str) -> int:
    value = _optional_float(row, key)
    return int(value) if value is not None else 0


def _external_review_evidence(review_data: dict[str, Any]) -> dict[str, Any]:
    daily_basic = review_data.get("daily_basic") or {}
    moneyflow = review_data.get("moneyflow") or {}
    limit_data = review_data.get("limit") or {}

    turnover_rate = _optional_float(daily_basic, "turnover_rate")
    turnover_rate_f = _optional_float(daily_basic, "turnover_rate_f")
    volume_ratio = _optional_float(daily_basic, "volume_ratio")
    total_mv = _optional_float(daily_basic, "total_mv")
    circ_mv = _optional_float(daily_basic, "circ_mv")

    net_mf_amount = _optional_float(moneyflow, "net_mf_amount")
    buy_lg = _optional_float(moneyflow, "buy_lg_amount") or 0.0
    sell_lg = _optional_float(moneyflow, "sell_lg_amount") or 0.0
    buy_elg = _optional_float(moneyflow, "buy_elg_amount") or 0.0
    sell_elg = _optional_float(moneyflow, "sell_elg_amount") or 0.0
    large_net = buy_lg - sell_lg
    extra_large_net = buy_elg - sell_elg
    main_net = large_net + extra_large_net
    circ_mv_yuan = (circ_mv or 0.0) * 10000.0
    main_net_yuan = main_net * 10000.0
    main_net_amount_ratio = main_net_yuan / circ_mv_yuan * 100.0 if circ_mv_yuan > 0 else None

    buy_lg_vol = _optional_float(moneyflow, "buy_lg_vol") or 0.0
    sell_lg_vol = _optional_float(moneyflow, "sell_lg_vol") or 0.0
    buy_elg_vol = _optional_float(moneyflow, "buy_elg_vol") or 0.0
    sell_elg_vol = _optional_float(moneyflow, "sell_elg_vol") or 0.0
    buy_big_vol = buy_lg_vol + buy_elg_vol
    sell_big_vol = sell_lg_vol + sell_elg_vol
    large_order_balance = (
        (buy_big_vol - sell_big_vol) / (buy_big_vol + sell_big_vol)
        if (buy_big_vol + sell_big_vol) > 0
        else None
    )

    limit_status = str(limit_data.get("limit") or "").strip().upper()
    if limit_status not in {"U", "D", "Z"}:
        limit_status = ""

    return {
        "available": bool(review_data.get("available")),
        "errors": review_data.get("errors") or [],
        "turnover_rate": _round_optional(turnover_rate),
        "turnover_rate_f": _round_optional(turnover_rate_f),
        "volume_ratio": _round_optional(volume_ratio),
        "total_mv": _round_optional(total_mv),
        "circ_mv": _round_optional(circ_mv),
        "net_mf_amount": _round_optional(net_mf_amount),
        "large_net_amount": round(large_net, 2) if moneyflow else None,
        "extra_large_net_amount": round(extra_large_net, 2) if moneyflow else None,
        "main_net_amount_ratio": _round_optional(main_net_amount_ratio),
        "large_order_balance": _round_optional(large_order_balance, digits=3),
        "limit_status": limit_status,
        "limit_open_times": _optional_int(limit_data, "open_times"),
        "limit_times": _optional_int(limit_data, "limit_times"),
        "limit_fd_amount": _optional_float(limit_data, "fd_amount") or 0.0,
        "limit_turnover_ratio": _round_optional(_optional_float(limit_data, "turnover_ratio")),
    }


def _round_optional(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _weekly_trend_evidence(df: pd.DataFrame) -> dict[str, Any]:
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    weekly = (
        d.set_index("date")
        .resample("W-FRI")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["close"])
    )
    if weekly.empty:
        return {"trend": "unknown", "ma_bull": False, "close_slope_4w": 0.0}

    close = weekly["close"].astype(float)
    ma5 = close.rolling(5, min_periods=5).mean()
    ma10 = close.rolling(10, min_periods=10).mean()
    ma20 = close.rolling(20, min_periods=20).mean()
    last_close = _safe_float(close.iloc[-1])
    slope_4w = _pct(last_close, _safe_float(close.iloc[-5], last_close)) if len(close) >= 5 else 0.0
    ma_bull = bool(
        len(close) >= 20
        and _safe_float(ma5.iloc[-1]) > _safe_float(ma10.iloc[-1]) > _safe_float(ma20.iloc[-1])
    )
    if ma_bull and slope_4w > 0:
        trend = "bull"
    elif slope_4w < -5:
        trend = "weak"
    else:
        trend = "neutral"
    return {"trend": trend, "ma_bull": ma_bull, "close_slope_4w": round(slope_4w, 2)}


def _visual_check(
    *,
    range_position: float,
    close_vs_zxdq_pct: float,
    destructive: bool,
    volume_ratio: float,
    limit_status: str = "",
    open_times: int = 0,
) -> str:
    if limit_status in {"D", "Z"} or destructive or (range_position >= 0.9 and close_vs_zxdq_pct > 15):
        return "conflict"
    if (
        range_position >= 0.82
        or close_vs_zxdq_pct > 10
        or volume_ratio < 0.75
        or (limit_status == "U" and open_times >= 2)
    ):
        return "caution"
    return "pass"


def _trend_reasoning(scores: dict[str, float], e: dict[str, Any]) -> str:
    if scores["trend_structure"] >= 4.5:
        return "日线均线和知行线同步转强，价格站在关键趋势线之上，趋势启动特征清晰。"
    if scores["trend_structure"] >= 3.5:
        return "日线结构偏多，价格保持在趋势线附近上方运行，但上行动能仍需延续确认。"
    if scores["trend_structure"] >= 2.5:
        return "日线趋势已有修复迹象，但均线斜率和价格节奏还不够流畅。"
    return "日线均线结构偏弱或反复交叉，当前更像弱修复而非稳定趋势启动。"


def _position_reasoning(scores: dict[str, float], e: dict[str, Any]) -> str:
    pos = e["range_position_120d"]
    if scores["price_position"] >= 4.3:
        return "价格处于中低位到中位区间，距离阶段前高仍有空间，风险收益比较好。"
    if scores["price_position"] >= 3.6:
        return "价格已脱离低位整理并向前高推进，仍有空间但不再是最低风险位置。"
    if pos >= 0.82:
        return "价格接近阶段高位或压力区，追高风险上升，上方空间受到压制。"
    return "当前位置缺少清晰突破优势，空间和防守位置都需要进一步观察。"


def _volume_reasoning(scores: dict[str, float], e: dict[str, Any]) -> str:
    if e.get("limit_status") == "Z":
        return "当日存在炸板记录，说明高位承接或封板强度不足，量价结构需要降权。"
    if e["has_recent_destructive_bearish_volume"]:
        return "近期出现破坏性放量阴线，量价结构被削弱，需要优先回避出货风险。"
    if e.get("main_net_amount_ratio") is not None and e["main_net_amount_ratio"] <= -0.8:
        return "成交放大但大单和特大单资金偏净流出，放量质量不足。"
    if e.get("turnover_rate_f") is not None and e["turnover_rate_f"] > 25:
        return "自由流通换手率过高，筹码交换偏剧烈，短线过热风险上升。"
    if scores["volume_behavior"] >= 4.5:
        return "上涨放量、回调缩量特征明显，最大量更多出现在上涨阶段，量价配合健康。"
    if scores["volume_behavior"] >= 3.5:
        return "量价关系整体偏健康，上涨与回调的量能差异支持继续观察。"
    if scores["volume_behavior"] >= 2.5:
        return "量价表现偏中性，上涨放量或回调缩量特征不够突出。"
    return "量价结构偏弱，上涨量能不足或回调不缩量，短线承接质量一般。"


def _abnormal_reasoning(scores: dict[str, float], e: dict[str, Any]) -> str:
    if e.get("limit_status") == "U":
        if e.get("limit_open_times", 0) == 0:
            return "当日涨停且未明显开板，叠加前期放量异动，短线资金确认度较高。"
        return "当日涨停但存在开板记录，异动有效但封板强度需要打折。"
    if e.get("limit_status") == "Z":
        return "当日出现炸板，前期异动容易被短线兑现，建仓有效性需要明显打折。"
    if e.get("limit_status") == "D":
        return "当日进入跌停记录，结构已被事件性抛压破坏，异动评分应降权。"
    if not e["abnormal_bull_day_date"]:
        return "近 60 日没有识别到明确放量中大阳，前期建仓异动证据不足。"
    if scores["previous_abnormal_move"] >= 4.3:
        return (
            f"{e['abnormal_bull_day_date']} 出现放量中大阳，量能显著高于区间均量，"
            "且异动后涨幅未明显透支。"
        )
    if scores["previous_abnormal_move"] >= 3.2:
        return "近 60 日存在一定放量上涨痕迹，但突破意义或后续承接强度还不算充分。"
    return "前期异动质量偏弱，或异动后涨幅已经透支，建仓有效性需要打折。"


def _signal_reasoning(signal_type: str, verdict: str, scores: dict[str, float], e: dict[str, Any]) -> str:
    if signal_type == "distribution_risk":
        return "当前位置或量价结构触发风险条件，综合判定为出货风险型。"
    if signal_type == "trend_start":
        return "趋势、位置和量价均达到启动要求，且未处于明显过热区，综合判定为主升启动型。"
    if verdict == "WATCH":
        return "结构处于修复和确认之间，尚未同时满足主升启动的趋势与量价条件。"
    return "综合分项仍偏弱，当前更接近反弹修复，暂不满足高确定性启动条件。"


def _comment(signal_type: str, verdict: str, scores: dict[str, float], e: dict[str, Any]) -> str:
    weekly_text = {
        "bull": "周线偏多",
        "neutral": "周线中性",
        "weak": "周线偏弱",
    }.get(e["weekly_trend"], "周线不明")
    if signal_type == "distribution_risk":
        return f"{weekly_text}但日线位置偏高或放量阴线破坏结构，量价转弱后空间受限，需防出货风险。"
    if verdict == "PASS":
        return f"{weekly_text}，日线量价配合较健康，前期异动有承接，当前仍有波段推进空间。"
    if verdict == "WATCH":
        return f"{weekly_text}，日线结构有修复迹象，量价和异动证据尚需确认，当前适合观察等待。"
    weakest = min(scores, key=scores.get)
    weak_text = {
        "trend_structure": "趋势",
        "price_position": "位置",
        "volume_behavior": "量价",
        "previous_abnormal_move": "异动",
    }[weakest]
    return f"{weekly_text}，日线{weak_text}证据偏弱，历史异动或承接不足，当前风险收益比不佳。"


def _build_reasoning(
    scores: dict[str, float],
    evidence: dict[str, Any],
    signal_type: str,
    verdict: str,
) -> dict[str, str]:
    return {
        "trend_reasoning": _trend_reasoning(scores, evidence),
        "position_reasoning": _position_reasoning(scores, evidence),
        "volume_reasoning": _volume_reasoning(scores, evidence),
        "abnormal_move_reasoning": _abnormal_reasoning(scores, evidence),
        "signal_reasoning": _signal_reasoning(signal_type, verdict, scores, evidence),
        "comment": _comment(signal_type, verdict, scores, evidence),
    }
