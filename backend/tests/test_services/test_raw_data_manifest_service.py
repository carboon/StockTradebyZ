from datetime import date
import json

from app.services.raw_data_manifest_service import RawDataManifestService


def test_serialize_json_lines_converts_date_to_isoformat(tmp_path) -> None:
    path = tmp_path / "raw_daily" / "2026-05-06.jsonl"

    count, size = RawDataManifestService.serialize_json_lines(
        [
            {
                "code": "000001",
                "trade_date": date(2026, 5, 6),
                "open": 10.5,
            }
        ],
        path,
    )

    assert count == 1
    assert size > 0

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["trade_date"] == "2026-05-06"
