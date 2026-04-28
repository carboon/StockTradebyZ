from __future__ import annotations

import json
from pathlib import Path

from pipeline import fetch_kline


def _write_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("date,open,close,high,low,volume\n2024-01-02,1,1,1,1,1\n", encoding="utf-8")


def test_full_fetch_resumes_from_checkpoint_and_skips_completed(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "raw"
    checkpoint_path = tmp_path / "fetch_state.json"
    codes = ["000001", "000002", "000003"]

    _write_csv(out_dir / "000001.csv")
    checkpoint_path.write_text(
        json.dumps(
            {
                "version": 1,
                "completed_codes": ["000001"],
                "failed_codes": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    called_codes: list[str] = []

    def fake_fetch_one(code: str, start: str, end: str, out_dir: Path):
        called_codes.append(code)
        _write_csv(out_dir / f"{code}.csv")
        return {"code": code, "success": True, "error": None}

    monkeypatch.setattr(fetch_kline, "fetch_one", fake_fetch_one)

    result = fetch_kline.full_fetch(
        codes,
        start="20240101",
        end="20240131",
        out_dir=out_dir,
        workers=1,
        checkpoint_path=checkpoint_path,
    )

    assert result["success"] is True
    assert result["initial_completed"] == 1
    assert result["completed"] == 3
    assert called_codes == ["000002", "000003"]
    assert checkpoint_path.exists() is False


def test_full_fetch_keeps_checkpoint_when_failures_remain(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "raw"
    checkpoint_path = tmp_path / "fetch_state.json"
    codes = ["000001", "000002"]

    def fake_fetch_one(code: str, start: str, end: str, out_dir: Path):
        if code == "000001":
            _write_csv(out_dir / f"{code}.csv")
            return {"code": code, "success": True, "error": None}
        return {"code": code, "success": False, "error": "mock failure"}

    monkeypatch.setattr(fetch_kline, "fetch_one", fake_fetch_one)

    result = fetch_kline.full_fetch(
        codes,
        start="20240101",
        end="20240131",
        out_dir=out_dir,
        workers=1,
        checkpoint_path=checkpoint_path,
    )

    assert result["success"] is False
    assert result["completed"] == 1
    assert result["failed"] == 1
    assert checkpoint_path.exists() is True

    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert payload["completed_codes"] == ["000001"]
    assert payload["failed_codes"] == {"000002": "mock failure"}
