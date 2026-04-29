"""
review_prefilter.py
~~~~~~~~~~~~~~~~~~~
第 4 步前置过滤层：

1. 使用 Tushare 元数据做时间一致的候选过滤
2. 实盘与回测共用同一套过滤逻辑
3. 所有过滤结果都带结构化明细，便于独立验证
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import tushare as ts
from backend.app.utils.stock_metadata import market_segment_from_code, resolve_ts_code
from backend.app.utils.tushare_rate_limit import acquire_tushare_slot

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CACHE_DIR = _ROOT / "data" / "tushare_cache"


def _resolve_cfg_path(path_like: str | Path, base_dir: Path = _ROOT) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else (base_dir / path)


def _to_ts_code(code: str) -> str:
    return resolve_ts_code(code)


def _market_segment(code: str) -> str:
    return market_segment_from_code(code)


def _normalize_trade_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y%m%d")
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).strftime("%Y%m%d")
    if isinstance(value, (int, np.integer)):
        return f"{int(value):08d}"
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{int(value):08d}"

    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    if "." in text and text.replace(".", "", 1).isdigit():
        text = text.split(".", 1)[0]
    return text.replace("-", "").replace("/", "")


def _to_timestamp(value: Any) -> pd.Timestamp | None:
    trade_date = _normalize_trade_date(value)
    if not trade_date:
        return None
    try:
        return pd.to_datetime(trade_date, format="%Y%m%d")
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


class TushareMetadataStore:
    def __init__(self, cache_dir: str | Path, token: str | None = None):
        self.cache_dir = _resolve_cfg_path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.token = token or os.environ.get("TUSHARE_TOKEN")
        if not self.token:
            raise ValueError("启用第 4 步预过滤时需要设置环境变量 TUSHARE_TOKEN")

        self.pro = ts.pro_api(self.token)
        self._frames: dict[str, pd.DataFrame] = {}

    def _load_or_fetch(self, rel_path: str, fetcher, *, refetch_if_empty: bool = False) -> pd.DataFrame:
        if rel_path in self._frames:
            return self._frames[rel_path]

        path = self.cache_dir / rel_path
        frame: pd.DataFrame | None = None
        if path.exists():
            frame = pd.read_csv(path)
            if refetch_if_empty and frame.empty:
                frame = None

        if frame is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            acquire_tushare_slot(rel_path)
            frame = fetcher()
            if frame is None:
                frame = pd.DataFrame()
            frame.to_csv(path, index=False)

        self._frames[rel_path] = frame
        return frame

    def namechange(self, start_date: str, end_date: str) -> pd.DataFrame:
        start = _normalize_trade_date(start_date)
        end = _normalize_trade_date(end_date)
        rel = f"namechange/namechange_{start}_{end}.csv"
        return self._load_or_fetch(
            rel,
            lambda: self.pro.namechange(
                start_date=start,
                end_date=end,
                fields="ts_code,name,start_date,end_date,change_reason",
            ),
        )

    def share_float(self, start_date: str, end_date: str) -> pd.DataFrame:
        start = _normalize_trade_date(start_date)
        end = _normalize_trade_date(end_date)
        rel = f"share_float/share_float_{start}_{end}.csv"
        return self._load_or_fetch(
            rel,
            lambda: self.pro.share_float(
                start_date=start,
                end_date=end,
                fields="ts_code,ann_date,float_date,float_share,float_ratio",
            ),
        )

    def daily_basic(self, trade_date: str) -> pd.DataFrame:
        day = _normalize_trade_date(trade_date)
        rel = f"daily_basic/daily_basic_{day}.csv"
        return self._load_or_fetch(
            rel,
            lambda: self.pro.daily_basic(
                trade_date=day,
                fields="ts_code,trade_date,free_share,circ_mv,total_mv,float_share,total_share",
            ),
        )

    def sw_l1_classify(self) -> pd.DataFrame:
        rel = "sw/sw_l1_classify.csv"
        return self._load_or_fetch(
            rel,
            lambda: self.pro.index_classify(
                src="SW2021",
                level="L1",
                fields="index_code,industry_name,level,src",
            ),
        )

    def sw_index_member(self, index_code: str) -> pd.DataFrame:
        rel = f"sw/member_{index_code}.csv"
        return self._load_or_fetch(
            rel,
            lambda: self.pro.index_member(
                index_code=index_code,
                fields="index_code,index_name,con_code,con_name,in_date,out_date,is_new",
            ),
        )

    def index_daily(self, ts_code: str, start_date: str, end_date: str | None = None) -> pd.DataFrame:
        ts_code_text = str(ts_code).strip().upper()
        start = _normalize_trade_date(start_date)
        end = _normalize_trade_date(end_date) if end_date else pd.Timestamp.today().strftime("%Y%m%d")
        rel = f"index_daily/{ts_code_text}_{start}_{end}.csv"
        use_sw_daily = ts_code_text.endswith(".SI")
        return self._load_or_fetch(
            rel,
            lambda: self.pro.sw_daily(
                ts_code=ts_code_text,
                start_date=start,
                end_date=end,
                fields="ts_code,trade_date,close",
            )
            if use_sw_daily
            else self.pro.index_daily(
                ts_code=ts_code_text,
                start_date=start,
                end_date=end,
                fields="ts_code,trade_date,close",
            ),
            refetch_if_empty=use_sw_daily,
        )


def build_prefilter_block_result(
    *,
    code: str,
    strategy: str | None,
    prefilter: dict[str, Any],
) -> dict[str, Any]:
    reason = prefilter.get("summary") or "未通过第 4 步前置过滤"
    return {
        "trend_reasoning": f"未进入程序化评分：{reason}",
        "position_reasoning": "前置过滤已拦截",
        "volume_reasoning": "前置过滤已拦截",
        "abnormal_move_reasoning": "前置过滤已拦截",
        "signal_reasoning": "该股票未通过第 4 步前置过滤，不进入评分阶段",
        "scores": {
            "trend_structure": None,
            "price_position": None,
            "volume_behavior": None,
            "previous_abnormal_move": None,
        },
        "total_score": None,
        "signal_type": "prefilter_blocked",
        "verdict": "FAIL",
        "comment": reason,
        "code": code,
        "strategy": strategy,
        "prefilter": prefilter,
    }


class Step4Prefilter:
    def __init__(self, config: dict[str, Any]):
        self.config = config.get("prefilter", {}) or {}
        self.enabled = bool(self.config.get("enabled", False))
        self.history_start = _normalize_trade_date(self.config.get("history_start", "20190101"))
        self._daily_basic_cache: dict[str, pd.DataFrame] = {}
        self._industry_strength_cache: dict[str, pd.DataFrame] = {}
        self._market_regime_cache: dict[str, dict[str, Any]] = {}
        self._index_frames: dict[str, pd.DataFrame] = {}
        self._sw_member_frame: pd.DataFrame | None = None
        self._namechange_frame: pd.DataFrame | None = None

        if not self.enabled:
            self.store = None
            return

        cache_dir = self.config.get("cache_dir", _DEFAULT_CACHE_DIR)
        token = self.config.get("token_env")
        token_value = os.environ.get(str(token)) if token else None
        self.store = TushareMetadataStore(cache_dir=cache_dir, token=token_value)

    def evaluate(
        self,
        *,
        code: str,
        pick_date: str | pd.Timestamp | None,
        price_df: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "passed": True,
                "blocked_by": [],
                "blocked_labels": [],
                "summary": "预过滤未启用",
                "details": {},
            }

        ts_code = _to_ts_code(code)
        pick_ts = self._resolve_pick_ts(pick_date=pick_date, price_df=price_df)
        trade_date = pick_ts.strftime("%Y%m%d")

        blocked_by: list[str] = []
        blocked_labels: list[str] = []
        details: dict[str, Any] = {
            "pick_date": pick_ts.strftime("%Y-%m-%d"),
            "ts_code": ts_code,
            "market_segment": _market_segment(code),
        }

        universe_cfg = self.config.get("universe", {}) or {}
        if bool(universe_cfg.get("exclude_st", True)):
            is_st = self._is_st(ts_code, trade_date)
            details["is_st"] = is_st
            if is_st:
                blocked_by.append("st")
                blocked_labels.append("ST/*ST 风险")

        min_listing_days = int(universe_cfg.get("min_listing_days", 0) or 0)
        if min_listing_days > 0:
            listing_days = self._listing_days(price_df=price_df, pick_ts=pick_ts)
            details["listing_days"] = listing_days
            if listing_days is not None and listing_days < min_listing_days:
                blocked_by.append("recent_ipo")
                blocked_labels.append(f"上市未满 {min_listing_days} 个交易日")

        unlock_cfg = self.config.get("unlock", {}) or {}
        if bool(unlock_cfg.get("enabled", False)):
            unlock_state = self._unlock_state(
                ts_code=ts_code,
                trade_date=trade_date,
                lookahead_days=int(unlock_cfg.get("lookahead_days", 20)),
            )
            details.update(unlock_state)
            max_ratio = float(unlock_cfg.get("max_free_share_ratio", 0.0) or 0.0)
            ratio = unlock_state.get("unlock_ratio_to_free_share")
            if ratio is not None and ratio >= max_ratio:
                blocked_by.append("unlock")
                blocked_labels.append(
                    f"未来 {int(unlock_cfg.get('lookahead_days', 20))} 日解禁占自由流通比 {ratio * 100:.1f}%"
                )

        size_cfg = self.config.get("size_bucket", {}) or {}
        size_state = self._size_bucket_state(ts_code=ts_code, trade_date=trade_date, cfg=size_cfg)
        details.update(size_state)
        allowed_buckets = {str(v).strip() for v in size_cfg.get("allowed", []) if str(v).strip()}
        if allowed_buckets and size_state.get("size_bucket") not in allowed_buckets:
            blocked_by.append("size_bucket")
            blocked_labels.append(f"流通市值分层 {size_state.get('size_bucket')} 不在允许范围")

        industry_cfg = self.config.get("industry_strength", {}) or {}
        if bool(industry_cfg.get("enabled", False)):
            industry_state = self._industry_strength_state(ts_code=ts_code, trade_date=trade_date, cfg=industry_cfg)
            details.update(industry_state)
            if industry_state.get("industry_filter_pass") is False:
                top_pct = float(industry_cfg.get("top_pct", 0.3))
                blocked_by.append("industry_strength")
                blocked_labels.append(f"申万一级行业强度不在前 {top_pct * 100:.0f}%")

        market_cfg = self.config.get("market_regime", {}) or {}
        if bool(market_cfg.get("enabled", False)):
            market_state = self._market_regime_state(trade_date=trade_date, cfg=market_cfg)
            details["market_regime"] = market_state
            if not market_state.get("passed", True):
                blocked_by.append("market_regime")
                blocked_labels.append("中证 500 / 创业板指环境未达标")

        passed = not blocked_by
        summary = "通过第 4 步预过滤" if passed else "；".join(blocked_labels)
        return {
            "enabled": True,
            "passed": passed,
            "blocked_by": blocked_by,
            "blocked_labels": blocked_labels,
            "summary": summary,
            "details": details,
        }

    def _resolve_pick_ts(
        self,
        *,
        pick_date: str | pd.Timestamp | None,
        price_df: pd.DataFrame | None,
    ) -> pd.Timestamp:
        if pick_date is not None:
            ts_value = _to_timestamp(pick_date)
            if ts_value is not None:
                return ts_value
        if price_df is None or price_df.empty:
            raise ValueError("无法解析 pick_date：缺少价格数据")
        if "date" in price_df.columns:
            dates = pd.to_datetime(price_df["date"])
            return pd.Timestamp(dates.max())
        if isinstance(price_df.index, pd.DatetimeIndex):
            return pd.Timestamp(price_df.index.max())
        raise ValueError("价格数据缺少 date 列，无法解析 pick_date")

    def _listing_days(self, *, price_df: pd.DataFrame | None, pick_ts: pd.Timestamp) -> int | None:
        if price_df is None or price_df.empty:
            return None
        if "date" in price_df.columns:
            dates = pd.to_datetime(price_df["date"], errors="coerce")
        elif isinstance(price_df.index, pd.DatetimeIndex):
            dates = pd.Series(price_df.index, index=price_df.index)
        else:
            return None
        return int((dates <= pick_ts).sum())

    def _load_namechange(self, end_date: str) -> pd.DataFrame:
        if self._namechange_frame is not None:
            return self._namechange_frame

        max_end = max(end_date, pd.Timestamp.today().strftime("%Y%m%d"))
        frame = self.store.namechange(self.history_start, max_end)  # type: ignore[union-attr]
        if frame.empty:
            self._namechange_frame = frame
            return frame

        out = frame.copy()
        out["ts_code"] = out["ts_code"].astype(str)
        out["name"] = out["name"].astype(str)
        out["start_date"] = out["start_date"].map(_normalize_trade_date)
        out["end_date"] = out["end_date"].map(_normalize_trade_date)
        self._namechange_frame = out
        return out

    def _is_st(self, ts_code: str, trade_date: str) -> bool:
        frame = self._load_namechange(trade_date)
        if frame.empty:
            return False

        subset = frame[frame["ts_code"] == ts_code]
        if subset.empty:
            return False

        active = subset[
            (subset["start_date"] <= trade_date)
            & ((subset["end_date"] == "") | (subset["end_date"] >= trade_date))
        ]
        if active.empty:
            return False

        names = active["name"].astype(str).str.replace(" ", "", regex=False).str.upper()
        return bool(names.str.startswith("ST").any() or names.str.startswith("*ST").any())

    def _daily_basic_on(self, trade_date: str) -> pd.DataFrame:
        if trade_date in self._daily_basic_cache:
            return self._daily_basic_cache[trade_date]

        frame = self.store.daily_basic(trade_date)  # type: ignore[union-attr]
        if frame.empty:
            empty = pd.DataFrame()
            self._daily_basic_cache[trade_date] = empty
            return empty

        out = frame.copy()
        out["ts_code"] = out["ts_code"].astype(str)
        for col in ["free_share", "circ_mv", "total_mv", "float_share", "total_share"]:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out = out.drop_duplicates(subset=["ts_code"], keep="last").set_index("ts_code", drop=False)
        self._daily_basic_cache[trade_date] = out
        return out

    def _unlock_state(self, *, ts_code: str, trade_date: str, lookahead_days: int) -> dict[str, Any]:
        pick_ts = pd.to_datetime(trade_date, format="%Y%m%d")
        start = (pick_ts + pd.Timedelta(days=1)).strftime("%Y%m%d")
        end = (pick_ts + pd.Timedelta(days=lookahead_days)).strftime("%Y%m%d")

        frame = self.store.share_float(start, end)  # type: ignore[union-attr]
        if frame.empty:
            return {
                "unlock_events": 0,
                "unlock_ratio_to_free_share": None,
                "unlock_float_share": None,
                "next_unlock_date": None,
            }

        out = frame.copy()
        out["ts_code"] = out["ts_code"].astype(str)
        out["float_date"] = out["float_date"].map(_normalize_trade_date)
        out["float_share"] = pd.to_numeric(out["float_share"], errors="coerce")
        out["float_ratio"] = pd.to_numeric(out["float_ratio"], errors="coerce")
        subset = out[(out["ts_code"] == ts_code) & (out["float_date"] >= start) & (out["float_date"] <= end)]
        if subset.empty:
            return {
                "unlock_events": 0,
                "unlock_ratio_to_free_share": 0.0,
                "unlock_float_share": 0.0,
                "next_unlock_date": None,
            }

        daily = self._daily_basic_on(trade_date)
        free_share = None
        if not daily.empty and ts_code in daily.index:
            free_share = _safe_float(daily.at[ts_code, "free_share"])

        unlock_float_share = float(subset["float_share"].fillna(0.0).sum())
        ratio = None
        if free_share and free_share > 0:
            ratio = unlock_float_share / free_share
        else:
            fallback_ratio = float(subset["float_ratio"].fillna(0.0).sum())
            ratio = fallback_ratio / 100.0 if fallback_ratio > 1.0 else fallback_ratio

        next_unlock_date = subset["float_date"].replace("", np.nan).dropna().min()
        return {
            "unlock_events": int(len(subset)),
            "unlock_ratio_to_free_share": round(float(ratio), 6) if ratio is not None else None,
            "unlock_float_share": round(unlock_float_share, 4),
            "next_unlock_date": next_unlock_date or None,
        }

    def _size_bucket_state(self, *, ts_code: str, trade_date: str, cfg: dict[str, Any]) -> dict[str, Any]:
        if not bool(cfg.get("enabled", False)):
            return {}

        daily = self._daily_basic_on(trade_date)
        if daily.empty or ts_code not in daily.index:
            return {
                "circ_mv": None,
                "circ_mv_100m": None,
                "size_bucket": None,
                "size_bucket_q1_100m": None,
                "size_bucket_q2_100m": None,
            }

        circ_mv = _safe_float(daily.at[ts_code, "circ_mv"])
        series = pd.to_numeric(daily["circ_mv"], errors="coerce").dropna()
        if circ_mv is None or series.empty:
            return {
                "circ_mv": circ_mv,
                "circ_mv_100m": round(circ_mv / 10000.0, 4) if circ_mv is not None else None,
                "size_bucket": None,
                "size_bucket_q1_100m": None,
                "size_bucket_q2_100m": None,
            }

        quantiles = cfg.get("quantiles", [1 / 3, 2 / 3])
        q1 = float(series.quantile(float(quantiles[0])))
        q2 = float(series.quantile(float(quantiles[1])))
        if circ_mv < q1:
            bucket = "small"
        elif circ_mv < q2:
            bucket = "mid"
        else:
            bucket = "large"

        return {
            "circ_mv": round(circ_mv, 4),
            "circ_mv_100m": round(circ_mv / 10000.0, 4),
            "size_bucket": bucket,
            "size_bucket_q1_100m": round(q1 / 10000.0, 4),
            "size_bucket_q2_100m": round(q2 / 10000.0, 4),
        }

    def _load_sw_members(self) -> pd.DataFrame:
        if self._sw_member_frame is not None:
            return self._sw_member_frame

        classify = self.store.sw_l1_classify()  # type: ignore[union-attr]
        if classify.empty:
            self._sw_member_frame = pd.DataFrame()
            return self._sw_member_frame

        frames: list[pd.DataFrame] = []
        for row in classify.itertuples(index=False):
            member = self.store.sw_index_member(str(row.index_code))  # type: ignore[union-attr]
            if member is None or member.empty:
                continue
            frame = member.copy()
            frame["index_code"] = frame["index_code"].astype(str)
            frame["con_code"] = frame["con_code"].astype(str)
            frame["in_date"] = frame["in_date"].map(_normalize_trade_date)
            frame["out_date"] = frame["out_date"].map(_normalize_trade_date)
            frame["industry_name"] = str(row.industry_name)
            frames.append(frame[["index_code", "con_code", "in_date", "out_date", "industry_name"]])

        self._sw_member_frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        return self._sw_member_frame

    def _sw_membership(self, *, ts_code: str, trade_date: str) -> dict[str, Any]:
        members = self._load_sw_members()
        if members.empty:
            return {
                "sw_index_code": None,
                "sw_l1_industry": None,
            }

        subset = members[members["con_code"] == ts_code]
        if subset.empty:
            return {
                "sw_index_code": None,
                "sw_l1_industry": None,
            }

        active = subset[
            (subset["in_date"] <= trade_date)
            & ((subset["out_date"] == "") | (subset["out_date"] >= trade_date))
        ]
        if active.empty:
            subset = subset.sort_values("in_date")
            row = subset.iloc[-1]
        else:
            active = active.sort_values("in_date")
            row = active.iloc[-1]

        return {
            "sw_index_code": row["index_code"],
            "sw_l1_industry": row["industry_name"],
        }

    def _index_frame(self, ts_code: str) -> pd.DataFrame:
        if ts_code in self._index_frames:
            return self._index_frames[ts_code]

        raw = self.store.index_daily(ts_code, self.history_start)  # type: ignore[union-attr]
        if raw.empty:
            empty = pd.DataFrame(columns=["trade_date", "close"])
            self._index_frames[ts_code] = empty
            return empty

        frame = raw.copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"].map(_normalize_trade_date), format="%Y%m%d")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = (
            frame.dropna(subset=["trade_date", "close"])
            .sort_values("trade_date")
            .drop_duplicates(subset=["trade_date"], keep="last")
            .reset_index(drop=True)
        )
        self._index_frames[ts_code] = frame
        return frame

    def _index_return_asof(self, *, ts_code: str, trade_date: str, lookback_days: int) -> float | None:
        frame = self._index_frame(ts_code)
        if frame.empty:
            return None

        pick_ts = pd.to_datetime(trade_date, format="%Y%m%d")
        subset = frame[frame["trade_date"] <= pick_ts]
        if len(subset) <= lookback_days:
            return None

        close_now = _safe_float(subset.iloc[-1]["close"])
        close_prev = _safe_float(subset.iloc[-1 - lookback_days]["close"])
        if close_now is None or close_prev is None or close_prev <= 0:
            return None
        return close_now / close_prev - 1.0

    def _industry_strength_table(self, *, trade_date: str, cfg: dict[str, Any]) -> pd.DataFrame:
        cache_key = f"{trade_date}|{int(cfg.get('lookback_days', 20))}|{cfg.get('benchmark_index', '000905.SH')}"
        if cache_key in self._industry_strength_cache:
            return self._industry_strength_cache[cache_key]

        classify = self.store.sw_l1_classify()  # type: ignore[union-attr]
        if classify.empty:
            empty = pd.DataFrame()
            self._industry_strength_cache[cache_key] = empty
            return empty

        benchmark_index = str(cfg.get("benchmark_index", "000905.SH"))
        lookback_days = int(cfg.get("lookback_days", 20))
        benchmark_ret = self._index_return_asof(ts_code=benchmark_index, trade_date=trade_date, lookback_days=lookback_days)

        rows: list[dict[str, Any]] = []
        for row in classify.itertuples(index=False):
            idx_code = str(row.index_code)
            idx_ret = self._index_return_asof(ts_code=idx_code, trade_date=trade_date, lookback_days=lookback_days)
            if idx_ret is None:
                continue
            relative_strength = idx_ret - benchmark_ret if benchmark_ret is not None else idx_ret
            rows.append(
                {
                    "sw_index_code": idx_code,
                    "sw_l1_industry": str(row.industry_name),
                    "industry_return": idx_ret,
                    "benchmark_return": benchmark_ret,
                    "relative_strength": relative_strength,
                }
            )

        if not rows:
            empty = pd.DataFrame()
            self._industry_strength_cache[cache_key] = empty
            return empty

        table = pd.DataFrame(rows).sort_values(
            ["relative_strength", "industry_return", "sw_index_code"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
        table["industry_rank"] = np.arange(1, len(table) + 1)
        table["industry_rank_pct"] = table["industry_rank"] / float(len(table))
        top_n = max(1, int(math.ceil(len(table) * float(cfg.get("top_pct", 0.3)))))
        table["industry_filter_pass"] = table["industry_rank"] <= top_n
        self._industry_strength_cache[cache_key] = table
        return table

    def _industry_strength_state(self, *, ts_code: str, trade_date: str, cfg: dict[str, Any]) -> dict[str, Any]:
        membership = self._sw_membership(ts_code=ts_code, trade_date=trade_date)
        if not membership.get("sw_index_code"):
            return {
                "sw_index_code": None,
                "sw_l1_industry": None,
                "industry_rank": None,
                "industry_rank_pct": None,
                "industry_return": None,
                "industry_relative_strength": None,
                "industry_filter_pass": None,
            }

        table = self._industry_strength_table(trade_date=trade_date, cfg=cfg)
        if table.empty:
            return {
                **membership,
                "industry_rank": None,
                "industry_rank_pct": None,
                "industry_return": None,
                "industry_relative_strength": None,
                "industry_filter_pass": None,
            }

        matched = table[table["sw_index_code"] == membership["sw_index_code"]]
        if matched.empty:
            return {
                **membership,
                "industry_rank": None,
                "industry_rank_pct": None,
                "industry_return": None,
                "industry_relative_strength": None,
                "industry_filter_pass": None,
            }

        row = matched.iloc[0]
        return {
            **membership,
            "industry_rank": int(row["industry_rank"]),
            "industry_rank_pct": round(float(row["industry_rank_pct"]), 6),
            "industry_return": round(float(row["industry_return"]), 6),
            "industry_relative_strength": round(float(row["relative_strength"]), 6),
            "industry_filter_pass": bool(row["industry_filter_pass"]),
        }

    def _market_regime_state(self, *, trade_date: str, cfg: dict[str, Any]) -> dict[str, Any]:
        cache_key = (
            f"{trade_date}|{int(cfg.get('lookback_days', 20))}|"
            f"{int(cfg.get('ema_fast', 20))}|{int(cfg.get('ema_slow', 60))}|"
            f"{int(cfg.get('min_pass_count', 1))}"
        )
        if cache_key in self._market_regime_cache:
            return self._market_regime_cache[cache_key]

        pick_ts = pd.to_datetime(trade_date, format="%Y%m%d")
        lookback_days = int(cfg.get("lookback_days", 20))
        ema_fast = int(cfg.get("ema_fast", 20))
        ema_slow = int(cfg.get("ema_slow", 60))
        min_pass_count = int(cfg.get("min_pass_count", 1))

        detail_rows: list[dict[str, Any]] = []
        pass_count = 0
        for item in cfg.get(
            "indexes",
            [
                {"ts_code": "000905.SH", "name": "CSI500"},
                {"ts_code": "399006.SZ", "name": "CHINEXT"},
            ],
        ):
            ts_code = str(item.get("ts_code"))
            frame = self._index_frame(ts_code)
            if frame.empty:
                detail_rows.append(
                    {
                        "ts_code": ts_code,
                        "name": item.get("name", ts_code),
                        "passed": False,
                        "close": None,
                        "ema_fast": None,
                        "ema_slow": None,
                        "return_lookback": None,
                    }
                )
                continue

            subset = frame[frame["trade_date"] <= pick_ts].copy()
            if len(subset) <= max(lookback_days, ema_slow):
                detail_rows.append(
                    {
                        "ts_code": ts_code,
                        "name": item.get("name", ts_code),
                        "passed": False,
                        "close": None,
                        "ema_fast": None,
                        "ema_slow": None,
                        "return_lookback": None,
                    }
                )
                continue

            subset["ema_fast"] = subset["close"].ewm(span=ema_fast, adjust=False).mean()
            subset["ema_slow"] = subset["close"].ewm(span=ema_slow, adjust=False).mean()
            subset["return_lookback"] = subset["close"] / subset["close"].shift(lookback_days) - 1.0
            row = subset.iloc[-1]
            close = _safe_float(row["close"])
            fast = _safe_float(row["ema_fast"])
            slow = _safe_float(row["ema_slow"])
            ret = _safe_float(row["return_lookback"])
            passed = bool(
                close is not None
                and fast is not None
                and slow is not None
                and ret is not None
                and close > fast > slow
                and ret > 0
            )
            if passed:
                pass_count += 1
            detail_rows.append(
                {
                    "ts_code": ts_code,
                    "name": item.get("name", ts_code),
                    "passed": passed,
                    "close": round(close, 4) if close is not None else None,
                    "ema_fast": round(fast, 4) if fast is not None else None,
                    "ema_slow": round(slow, 4) if slow is not None else None,
                    "return_lookback": round(ret, 6) if ret is not None else None,
                }
            )

        result = {
            "passed": pass_count >= min_pass_count,
            "pass_count": pass_count,
            "required_pass_count": min_pass_count,
            "details": detail_rows,
        }
        self._market_regime_cache[cache_key] = result
        return result
