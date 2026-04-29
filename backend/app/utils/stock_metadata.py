from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STOCKLIST_PATH = ROOT / "pipeline" / "stocklist.csv"
VALID_MARKETS = {"SH", "SZ", "BJ"}


def normalize_stock_code(code: object) -> str:
    text = str(code or "").strip().upper()
    if "." in text:
        text = text.split(".", 1)[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return ""
    return digits[-6:].zfill(6)


def clear_stock_metadata_cache() -> None:
    _load_stocklist_ts_code_map.cache_clear()


def _fallback_market(code: str) -> str:
    if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return "SH"
    if code.startswith(("4", "8", "92", "43", "83", "87", "88")):
        return "BJ"
    return "SZ"


@lru_cache(maxsize=None)
def _load_stocklist_ts_code_map(stocklist_path: str = "") -> dict[str, str]:
    path = Path(stocklist_path) if stocklist_path else STOCKLIST_PATH
    if not path.exists():
        return {}

    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            code = normalize_stock_code(row.get("symbol"))
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if not code or not ts_code or "." not in ts_code:
                continue
            mapping.setdefault(code, ts_code)
    return mapping


def resolve_ts_code(
    code: object,
    *,
    stocklist_path: str | Path | None = None,
    market: str | None = None,
) -> str:
    normalized = normalize_stock_code(code)
    if not normalized:
        return ""

    path_key = str(Path(stocklist_path).resolve()) if stocklist_path else ""
    ts_code = _load_stocklist_ts_code_map(path_key).get(normalized)
    if ts_code:
        return ts_code

    market_text = str(market or "").strip().upper().removeprefix(".")
    if market_text in VALID_MARKETS:
        return f"{normalized}.{market_text}"

    return f"{normalized}.{_fallback_market(normalized)}"


def resolve_market(
    code: object,
    *,
    stocklist_path: str | Path | None = None,
    market: str | None = None,
) -> str:
    normalized = normalize_stock_code(code)
    if not normalized:
        return ""

    ts_code = resolve_ts_code(normalized, stocklist_path=stocklist_path, market=market)
    suffix = ts_code.rsplit(".", 1)[-1].upper() if "." in ts_code else ""
    if suffix in VALID_MARKETS:
        return suffix
    return _fallback_market(normalized)


def market_segment_from_code(
    code: object,
    *,
    stocklist_path: str | Path | None = None,
    market: str | None = None,
) -> str:
    normalized = normalize_stock_code(code)
    resolved_market = resolve_market(normalized, stocklist_path=stocklist_path, market=market)
    if resolved_market == "BJ":
        return "bj"
    if resolved_market == "SH" and normalized.startswith("688"):
        return "star"
    if resolved_market == "SZ" and normalized.startswith(("300", "301")):
        return "gem"
    return "main"
