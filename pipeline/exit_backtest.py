"""
Offline exit quantile backtest for B1 review events.

Builds:
    data/exit/exit_events.csv
    data/exit/exit_profiles.json

Usage:
    .venv/bin/python -m pipeline.exit_backtest --start-date 2026-01-01 --end-date 2026-04-30
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_HORIZONS = (5, 10, 20)
TARGET_PCTS = (0.10, 0.20)
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _normalize_code(value: Any) -> str:
    text = str(value).strip()
    if text.endswith(".SZ") or text.endswith(".SH") or text.endswith(".BJ"):
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() and len(text) < 6 else text


def _date_in_range(date_text: str, start_date: str | None, end_date: str | None) -> bool:
    if start_date and date_text < start_date:
        return False
    if end_date and date_text > end_date:
        return False
    return True


def _candidate_b1_codes(candidate_path: Path) -> set[str]:
    if not candidate_path.exists():
        return set()
    payload = _read_json(candidate_path)
    candidates = payload.get("candidates", payload if isinstance(payload, list) else [])
    codes: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if str(item.get("strategy", "")).lower() == "b1":
            codes.add(_normalize_code(item.get("code", "")))
    return {code for code in codes if code}


def _prefilter_status(review: dict[str, Any]) -> str:
    prefilter = review.get("prefilter") or {}
    if not isinstance(prefilter, dict):
        return "unknown"
    if bool(prefilter.get("passed", True)):
        return "passed"
    return "blocked"


def _review_size_bucket(review: dict[str, Any]) -> str:
    prefilter = review.get("prefilter") or {}
    details = prefilter.get("details") if isinstance(prefilter, dict) else {}
    value = details.get("size_bucket") if isinstance(details, dict) else None
    return str(value) if value not in (None, "") else "unknown"


def iter_review_events(
    *,
    data_root: Path = ROOT / "data",
    start_date: str | None = None,
    end_date: str | None = None,
) -> Iterable[dict[str, Any]]:
    review_root = data_root / "review"
    candidate_root = data_root / "candidates"
    if not review_root.exists():
        return

    for day_dir in sorted(p for p in review_root.iterdir() if p.is_dir()):
        pick_date = day_dir.name
        if not _date_in_range(pick_date, start_date, end_date):
            continue
        b1_codes = _candidate_b1_codes(candidate_root / f"candidates_{pick_date}.json")
        if not b1_codes:
            continue

        for review_path in sorted(day_dir.glob("*.json")):
            if review_path.name == "suggestion.json":
                continue
            review = _read_json(review_path)
            if not isinstance(review, dict):
                continue
            code = _normalize_code(review.get("code") or review_path.stem)
            strategy = str(review.get("strategy", "")).lower()
            if strategy != "b1" or code not in b1_codes:
                continue
            yield {
                "pick_date": str(review.get("pick_date") or review.get("analysis_date") or pick_date),
                "code": code,
                "strategy": "b1",
                "verdict": str(review.get("verdict") or "unknown"),
                "signal_type": str(review.get("signal_type") or "unknown"),
                "prefilter_status": _prefilter_status(review),
                "size_bucket": _review_size_bucket(review),
                "total_score": review.get("total_score"),
            }


def load_price_frame(raw_dir: Path, code: str) -> pd.DataFrame:
    path = raw_dir / f"{code}.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    frame.columns = [str(c).lower() for c in frame.columns]
    required = {"date", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    frame = frame[["date", "open", "high", "low", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for col in ("open", "high", "low", "close"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = (
        frame.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    return frame


def _days_to_target(window: pd.DataFrame, entry_open: float, pct: float) -> int | None:
    target = entry_open * (1.0 + pct)
    hits = window.index[window["high"] >= target].tolist()
    if not hits:
        return None
    return int(hits[0] + 1)


def compute_exit_metrics(
    event: dict[str, Any],
    prices: pd.DataFrame,
    *,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> dict[str, Any] | None:
    if prices.empty:
        return None

    pick_ts = pd.to_datetime(event["pick_date"])
    future = prices[prices["date"] > pick_ts].reset_index(drop=True)
    if future.empty:
        return None

    entry = future.iloc[0]
    entry_open = float(entry["open"])
    if not np.isfinite(entry_open) or entry_open <= 0:
        return None

    row: dict[str, Any] = {
        **event,
        "entry_date": entry["date"].strftime("%Y-%m-%d"),
        "entry_open": round(entry_open, 6),
    }

    for horizon in horizons:
        window = future.iloc[: int(horizon)].reset_index(drop=True)
        prefix = f"{int(horizon)}d"
        if len(window) < int(horizon):
            row[f"{prefix}_complete"] = False
            row[f"{prefix}_mfe"] = None
            row[f"{prefix}_mae"] = None
            row[f"{prefix}_close_ret"] = None
            row[f"{prefix}_high_date"] = None
            row[f"{prefix}_low_date"] = None
            row[f"{prefix}_days_to_10pct"] = None
            row[f"{prefix}_days_to_20pct"] = None
            continue

        high_pos = int(window["high"].idxmax())
        low_pos = int(window["low"].idxmin())
        row[f"{prefix}_complete"] = True
        row[f"{prefix}_mfe"] = round(float(window["high"].max() / entry_open - 1.0), 6)
        row[f"{prefix}_mae"] = round(float(window["low"].min() / entry_open - 1.0), 6)
        row[f"{prefix}_close_ret"] = round(float(window.iloc[-1]["close"] / entry_open - 1.0), 6)
        row[f"{prefix}_high_date"] = window.iloc[high_pos]["date"].strftime("%Y-%m-%d")
        row[f"{prefix}_low_date"] = window.iloc[low_pos]["date"].strftime("%Y-%m-%d")
        for pct in TARGET_PCTS:
            label = f"{int(pct * 100)}pct"
            row[f"{prefix}_days_to_{label}"] = _days_to_target(window, entry_open, pct)

    return row


def build_exit_events(
    *,
    data_root: Path = ROOT / "data",
    start_date: str | None = None,
    end_date: str | None = None,
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> pd.DataFrame:
    raw_dir = data_root / "raw"
    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[dict[str, Any]] = []

    for event in iter_review_events(data_root=data_root, start_date=start_date, end_date=end_date):
        code = event["code"]
        if code not in price_cache:
            price_cache[code] = load_price_frame(raw_dir, code)
        row = compute_exit_metrics(event, price_cache[code], horizons=horizons)
        if row is not None:
            rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["pick_date", "code"]).reset_index(drop=True)


def _quantile_map(series: pd.Series) -> dict[str, float | None]:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return {f"p{int(q * 100)}": None for q in QUANTILES}
    return {f"p{int(q * 100)}": round(float(vals.quantile(q)), 6) for q in QUANTILES}


def _profile_for_group(group: pd.DataFrame, horizons: Iterable[int], *, min_samples: int) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "sample_count": int(len(group)),
        "min_sample_met": bool(len(group) >= min_samples),
        "horizons": {},
    }
    for horizon in horizons:
        prefix = f"{int(horizon)}d"
        complete_col = f"{prefix}_complete"
        complete = group[group[complete_col] == True] if complete_col in group.columns else group.iloc[0:0]  # noqa: E712
        profile["horizons"][prefix] = {
            "complete_count": int(len(complete)),
            "mfe": _quantile_map(complete.get(f"{prefix}_mfe", pd.Series(dtype=float))),
            "mae": _quantile_map(complete.get(f"{prefix}_mae", pd.Series(dtype=float))),
            "close_ret": _quantile_map(complete.get(f"{prefix}_close_ret", pd.Series(dtype=float))),
            "days_to_10pct": _quantile_map(complete.get(f"{prefix}_days_to_10pct", pd.Series(dtype=float))),
            "days_to_20pct": _quantile_map(complete.get(f"{prefix}_days_to_20pct", pd.Series(dtype=float))),
        }
    return profile


def _profile_key(strategy: str, verdict: str, signal_type: str, prefilter_status: str, size_bucket: str) -> str:
    return "|".join([strategy, verdict, signal_type, prefilter_status, size_bucket])


def build_profiles(
    events: pd.DataFrame,
    *,
    verdict: str = "PASS",
    signal_type: str = "trend_start",
    prefilter_status: str = "passed",
    horizons: Iterable[int] = DEFAULT_HORIZONS,
    min_samples: int = 30,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    filters = {
        "strategy": "b1",
        "verdict": verdict,
        "signal_type": signal_type,
        "prefilter_status": prefilter_status,
    }
    payload: dict[str, Any] = {
        "generated_at": generated_at,
        "filters": filters,
        "profiles": {},
    }

    profiles = payload["profiles"]
    if events.empty:
        empty = _profile_for_group(events, horizons, min_samples=min_samples)
        profiles[_profile_key("b1", verdict, signal_type, prefilter_status, "all")] = empty
        profiles["fallback"] = empty
        return payload

    core = events[
        (events["strategy"] == "b1")
        & (events["verdict"] == verdict)
        & (events["signal_type"] == signal_type)
        & (events["prefilter_status"] == prefilter_status)
    ]
    profiles[_profile_key("b1", verdict, signal_type, prefilter_status, "all")] = _profile_for_group(
        core,
        horizons,
        min_samples=min_samples,
    )

    group_cols = ["strategy", "verdict", "signal_type", "prefilter_status", "size_bucket"]
    for values, group in events.groupby(group_cols, dropna=False, sort=True):
        strategy, group_verdict, group_signal, group_prefilter, size_bucket = [str(v) for v in values]
        key = _profile_key(strategy, group_verdict, group_signal, group_prefilter, size_bucket)
        profiles[key] = _profile_for_group(group, horizons, min_samples=min_samples)

    for values, group in events.groupby(group_cols[:-1], dropna=False, sort=True):
        strategy, group_verdict, group_signal, group_prefilter = [str(v) for v in values]
        key = _profile_key(strategy, group_verdict, group_signal, group_prefilter, "all")
        profiles.setdefault(key, _profile_for_group(group, horizons, min_samples=min_samples))

    fallback = events[events["strategy"] == "b1"]
    fallback_profile = _profile_for_group(fallback, horizons, min_samples=min_samples)
    profiles[_profile_key("b1", "all", "all", "all", "all")] = fallback_profile
    profiles["fallback"] = fallback_profile
    return payload


def run_exit_backtest(
    *,
    data_root: Path = ROOT / "data",
    output_dir: Path | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    verdict: str = "PASS",
    signal_type: str = "trend_start",
    prefilter_status: str = "passed",
    min_samples: int = 30,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    output_dir = output_dir or data_root / "exit"
    events = build_exit_events(data_root=data_root, start_date=start_date, end_date=end_date)
    if not events.empty:
        events = events.copy()
        events["matches_profile_filter"] = (
            (events["strategy"] == "b1")
            & (events["verdict"] == verdict)
            & (events["signal_type"] == signal_type)
            & (events["prefilter_status"] == prefilter_status)
        )
    profiles = build_profiles(
        events,
        verdict=verdict,
        signal_type=signal_type,
        prefilter_status=prefilter_status,
        min_samples=min_samples,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    events.to_csv(output_dir / "exit_events.csv", index=False, encoding="utf-8")
    with (output_dir / "exit_profiles.json").open("w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)
    return events, profiles


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline MFE/MAE exit quantile profiles")
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--verdict", default="PASS")
    parser.add_argument("--signal-type", default="trend_start")
    parser.add_argument("--prefilter", default="passed", dest="prefilter_status")
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--min-samples", type=int, default=30)
    args = parser.parse_args()

    events, profiles = run_exit_backtest(
        data_root=Path(args.data_root),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        start_date=args.start_date,
        end_date=args.end_date,
        verdict=args.verdict,
        signal_type=args.signal_type,
        prefilter_status=args.prefilter_status,
        min_samples=args.min_samples,
    )
    print(f"exit events: {len(events)}")
    print(f"profiles: {len(profiles.get('profiles', {}))}")


if __name__ == "__main__":
    main()
