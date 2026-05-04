#!/usr/bin/env python3
"""
dailyUpdateTest
~~~~~~~~~~~~~~~~
验证日更链路的端到端自动化测试：

1. 删除指定交易日的原始行情与派生结果
2. 基于前一交易日重新计算离线结果
3. 通过现有抓取链路补回指定交易日增量数据
4. 基于指定交易日重新计算离线结果
5. 输出耗时、负载与校验报告

默认行为会修改当前运行数据，但会留下可恢复快照。
如需自动恢复，请使用 --restore-after。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml
from sqlalchemy import delete, func, select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AnalysisResult,
    Candidate,
    DailyB1Check,
    DataUpdateLog,
    StockAnalysis,
    StockDaily,
)
from app.services.analysis_service import analysis_service  # noqa: E402
from app.services.candidate_service import get_candidate_service  # noqa: E402


TABLE_SPECS = {
    "stock_daily": (StockDaily, StockDaily.trade_date),
    "candidates": (Candidate, Candidate.pick_date),
    "analysis_results": (AnalysisResult, AnalysisResult.pick_date),
    "daily_b1_checks": (DailyB1Check, DailyB1Check.check_date),
    "stock_analysis": (StockAnalysis, StockAnalysis.trade_date),
    "data_update_log": (DataUpdateLog, DataUpdateLog.update_date),
}


@dataclass
class StageResult:
    name: str
    elapsed_seconds: float
    details: dict[str, Any]


def _print_progress(message: str) -> None:
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[dailyUpdateTest {now}] {message}", flush=True)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _now_label() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _system_snapshot() -> dict[str, Any]:
    loadavg = None
    if hasattr(os, "getloadavg"):
        try:
            loadavg = list(os.getloadavg())
        except OSError:
            loadavg = None

    return {
        "timestamp": datetime.now().isoformat(),
        "loadavg": loadavg,
        "maxrss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def _append_event(snapshot_dir: Path, event_type: str, payload: dict[str, Any]) -> None:
    event_file = snapshot_dir / "events.jsonl"
    event_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(),
        "type": event_type,
        **payload,
    }
    with event_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=_json_default) + "\n")


def _stage_status_path(snapshot_dir: Path, name: str) -> Path:
    return snapshot_dir / "stages" / f"{name}.json"


def _write_stage_status(
    snapshot_dir: Path,
    name: str,
    status: str,
    *,
    started_at: str | None = None,
    ended_at: str | None = None,
    elapsed_seconds: float | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "name": name,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_seconds": elapsed_seconds,
        "details": details or {},
    }
    _write_json(_stage_status_path(snapshot_dir, name), payload)


def _write_runtime_state(snapshot_dir: Path, payload: dict[str, Any]) -> None:
    _write_json(snapshot_dir / "runtime_state.json", payload)


def _stage(snapshot_dir: Path, name: str, fn, *args, **kwargs) -> StageResult:
    started = time.perf_counter()
    started_at = datetime.now().isoformat()
    before = _system_snapshot()
    _print_progress(f"阶段开始: {name}")
    _append_event(snapshot_dir, "stage_started", {"stage": name})
    _write_stage_status(snapshot_dir, name, "running", started_at=started_at, details={"before": before})
    details = fn(*args, **kwargs)
    after = _system_snapshot()
    elapsed = time.perf_counter() - started
    ended_at = datetime.now().isoformat()
    _write_stage_status(
        snapshot_dir,
        name,
        "completed",
        started_at=started_at,
        ended_at=ended_at,
        elapsed_seconds=elapsed,
        details={"before": before, "after": after, "result": details},
    )
    _append_event(snapshot_dir, "stage_completed", {"stage": name, "elapsed_seconds": round(elapsed, 3)})
    _print_progress(f"阶段完成: {name} | {elapsed:.1f}s")
    return StageResult(
        name=name,
        elapsed_seconds=elapsed,
        details={
            "before": before,
            "after": after,
            "result": details,
        },
    )


def _run_command(
    snapshot_dir: Path,
    stage_name: str,
    name: str,
    cmd: list[str],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    merged_env = os.environ.copy()
    merged_env.setdefault("PYTHONPATH", f"{ROOT}:{ROOT / 'backend'}")
    if env:
        merged_env.update(env)

    started = time.perf_counter()
    started_at = datetime.now().isoformat()
    _print_progress(f"命令开始: {name} | {' '.join(cmd)}")
    _append_event(snapshot_dir, "command_started", {"stage": stage_name, "name": name, "command": cmd})
    log_path = snapshot_dir / "commands" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    captured_lines: list[str] = []
    last_line: str | None = None
    with log_path.open("w", encoding="utf-8") as log_file:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\n")
            log_file.write(raw_line)
            log_file.flush()
            captured_lines.append(line)
            last_line = line

            if len(captured_lines) > 200:
                captured_lines = captured_lines[-200:]

            if "[PROGRESS_JSON]" in line or "进度:" in line or "[INFO]" in line:
                _print_progress(f"{name}: {line}")
                _write_runtime_state(
                    snapshot_dir,
                    {
                        "stage": stage_name,
                        "command": name,
                        "status": "running",
                        "started_at": started_at,
                        "last_output": line,
                        "log_file": str(log_path),
                    },
                )
                _append_event(
                    snapshot_dir,
                    "command_progress",
                    {"stage": stage_name, "name": name, "line": line},
                )

    returncode = process.wait()
    elapsed = time.perf_counter() - started
    ended_at = datetime.now().isoformat()
    payload = {
        "name": name,
        "command": cmd,
        "returncode": returncode,
        "elapsed_seconds": elapsed,
        "output_tail": "\n".join(captured_lines[-50:]),
        "log_file": str(log_path),
        "last_output": last_line,
    }
    _append_event(
        snapshot_dir,
        "command_completed",
        {
            "stage": stage_name,
            "name": name,
            "returncode": returncode,
            "elapsed_seconds": round(elapsed, 3),
        },
    )
    _print_progress(f"命令结束: {name} | rc={returncode} | {elapsed:.1f}s")
    if returncode != 0:
        raise RuntimeError(f"{name} failed: rc={result.returncode}")
    return payload


def _latest_trade_date() -> str:
    with SessionLocal() as db:
        row = db.execute(
            select(StockDaily.trade_date)
            .order_by(StockDaily.trade_date.desc())
            .limit(1)
        ).first()
        if not row:
            raise RuntimeError("stock_daily is empty")
        return row[0].isoformat()


def _previous_trade_date(target_date: str) -> str:
    target = date.fromisoformat(target_date)
    with SessionLocal() as db:
        row = db.execute(
            select(StockDaily.trade_date)
            .where(StockDaily.trade_date < target)
            .order_by(StockDaily.trade_date.desc())
            .limit(1)
        ).first()
        if not row:
            raise RuntimeError(f"cannot find previous trade date before {target_date}")
        return row[0].isoformat()


def _serialize_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for row in rows:
        item = {}
        for column in row.__table__.columns:
            item[column.name] = getattr(row, column.name)
        serialized.append(item)
    return serialized


def _collect_target_rows(target_date: str) -> dict[str, list[dict[str, Any]]]:
    target = date.fromisoformat(target_date)
    snapshot: dict[str, list[dict[str, Any]]] = {}
    with SessionLocal() as db:
        for table_name, (model, field) in TABLE_SPECS.items():
            rows = db.execute(select(model).where(field == target)).scalars().all()
            snapshot[table_name] = _serialize_rows(rows)
    return snapshot


def _count_by_date(target_date: str) -> dict[str, int]:
    target = date.fromisoformat(target_date)
    result: dict[str, int] = {}
    with SessionLocal() as db:
        for table_name, (model, field) in TABLE_SPECS.items():
            count = db.execute(
                select(func.count()).select_from(model).where(field == target)
            ).scalar_one()
            result[table_name] = int(count)
    return result


def _delete_target_rows(target_date: str) -> dict[str, int]:
    target = date.fromisoformat(target_date)
    deleted: dict[str, int] = {}
    with SessionLocal() as db:
        for table_name, (model, field) in TABLE_SPECS.items():
            count = db.execute(
                delete(model).where(field == target).returning(field)
            ).fetchall()
            deleted[table_name] = len(count)
        db.commit()
    return deleted


def _restore_table_rows(table_rows: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    restored: dict[str, int] = {}
    with SessionLocal() as db:
        for table_name, rows in table_rows.items():
            model, field = TABLE_SPECS[table_name]
            if rows:
                target_date = rows[0][field.key]
                db.execute(delete(model).where(field == target_date))
                db.execute(model.__table__.insert(), rows)
                restored[table_name] = len(rows)
            else:
                restored[table_name] = 0
        db.commit()
    return restored


def _copy_if_exists(src: Path, dest: Path) -> bool:
    if not src.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    else:
        shutil.copy2(src, dest)
    return True


def _remove_path(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def _collect_recommendation_codes(review_dir: Path) -> list[str]:
    suggestion_file = review_dir / "suggestion.json"
    payload = _read_json(suggestion_file, default={}) or {}
    codes: list[str] = []
    for item in payload.get("recommendations", []):
        code = str(item.get("code", "")).zfill(6)
        if code:
            codes.append(code)
    return codes


def _snapshot_files(target_date: str, snapshot_dir: Path) -> dict[str, Any]:
    file_snapshot: dict[str, Any] = {"paths": {}, "history_codes": []}

    candidates_dir = ROOT / "data" / "candidates"
    review_dir = ROOT / "data" / "review"
    latest_file = candidates_dir / "candidates_latest.json"
    dated_candidate = candidates_dir / f"candidates_{target_date}.json"
    target_review_dir = review_dir / target_date

    original_codes = _collect_recommendation_codes(target_review_dir)
    file_snapshot["history_codes"] = original_codes

    path_map = {
        "candidates_latest": latest_file,
        "candidates_dated": dated_candidate,
        "review_target_dir": target_review_dir,
    }

    for key, src in path_map.items():
        dest = snapshot_dir / "files" / key
        if _copy_if_exists(src, dest):
            file_snapshot["paths"][key] = str(dest)

    history_dir = review_dir / "history"
    for code in original_codes:
        src = history_dir / f"{code}.json"
        dest = snapshot_dir / "files" / "history" / f"{code}.json"
        if _copy_if_exists(src, dest):
            file_snapshot.setdefault("history_files", []).append(str(dest))

    return file_snapshot


def _strip_target_date_from_raw(target_date: str, snapshot_dir: Path) -> dict[str, Any]:
    raw_dir = ROOT / "data" / "raw"
    removed_rows: list[dict[str, Any]] = []
    touched_files = 0

    for csv_path in sorted(raw_dir.glob("*.csv")):
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if not fieldnames:
                continue
            rows = list(reader)

        matched = [row for row in rows if str(row.get("date", ""))[:10] == target_date]
        if not matched:
            continue

        remaining = [row for row in rows if str(row.get("date", ""))[:10] != target_date]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(remaining)

        touched_files += 1
        removed_rows.append(
            {
                "file": str(csv_path.relative_to(ROOT)),
                "fieldnames": fieldnames,
                "rows": matched,
            }
        )

    backup_path = snapshot_dir / "raw_removed_rows.json"
    _write_json(backup_path, removed_rows)
    return {
        "touched_files": touched_files,
        "removed_row_count": sum(len(item["rows"]) for item in removed_rows),
        "backup_file": str(backup_path),
    }


def _restore_raw(snapshot_dir: Path) -> dict[str, Any]:
    removed_rows = _read_json(snapshot_dir / "raw_removed_rows.json", default=[]) or []
    restored_files = 0
    restored_rows = 0

    for item in removed_rows:
        csv_path = ROOT / item["file"]
        fieldnames = item["fieldnames"]
        restored = item["rows"]

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        rows.extend(restored)
        rows.sort(key=lambda row: str(row.get("date", "")))

        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        restored_files += 1
        restored_rows += len(restored)

    return {"restored_files": restored_files, "restored_rows": restored_rows}


def _sync_candidates_from_latest() -> dict[str, Any]:
    latest_file = ROOT / "data" / "candidates" / "candidates_latest.json"
    payload = _read_json(latest_file, default={}) or {}
    pick_date = str(payload.get("pick_date") or "").strip()
    candidates = payload.get("candidates") or []
    if not pick_date or not isinstance(candidates, list):
        raise RuntimeError("candidates_latest.json is missing pick_date/candidates")

    service = get_candidate_service()
    count = service.save_candidates(
        pick_date=pick_date,
        candidates=candidates,
        strategy="b1",
        clean_existing=True,
    )
    return {"pick_date": pick_date, "saved": count}


def _sync_analysis_for_date(pick_date: str, reviewer: str) -> dict[str, Any]:
    review_dir = ROOT / "data" / "review" / pick_date
    if not review_dir.exists():
        raise RuntimeError(f"review dir missing: {review_dir}")

    stock_files = sorted(
        path for path in review_dir.glob("*.json") if path.name != "suggestion.json"
    )
    rows: list[dict[str, Any]] = []

    for path in stock_files:
        payload = _read_json(path, default={}) or {}
        code = str(payload.get("code") or path.stem).zfill(6)
        if not code or code == "000000":
            continue
        rows.append(
            {
                "pick_date": date.fromisoformat(pick_date),
                "code": code,
                "reviewer": reviewer,
                "verdict": payload.get("verdict"),
                "total_score": float(payload["total_score"]) if payload.get("total_score") is not None else None,
                "signal_type": payload.get("signal_type"),
                "comment": payload.get("comment"),
                "details_json": payload,
            }
        )

    with SessionLocal() as db:
        db.execute(delete(AnalysisResult).where(AnalysisResult.pick_date == date.fromisoformat(pick_date)))
        if rows:
            db.execute(AnalysisResult.__table__.insert(), rows)
        db.commit()

    return {"pick_date": pick_date, "saved": len(rows)}


def _generate_top5_history(pick_date: str) -> dict[str, Any]:
    review_dir = ROOT / "data" / "review" / pick_date
    codes = _collect_recommendation_codes(review_dir)[:5]
    generated: list[dict[str, Any]] = []
    for code in codes:
        generated.append(analysis_service.generate_stock_history_checks(code, days=30, clean=False))
    return {"codes": codes, "results": generated}


def _restore_files(snapshot_dir: Path, final_target_codes: list[str]) -> dict[str, Any]:
    restored: dict[str, Any] = {"restored": [], "removed_new_history": []}
    files_dir = snapshot_dir / "files"
    candidates_dir = ROOT / "data" / "candidates"
    review_dir = ROOT / "data" / "review"
    meta = _read_json(snapshot_dir / "meta.json") or {}
    target_date = meta["target_date"]

    restore_targets = {
        "candidates_latest": candidates_dir / "candidates_latest.json",
        "candidates_dated": candidates_dir / f"candidates_{target_date}.json",
        "review_target_dir": review_dir / target_date,
    }

    for key, dest in restore_targets.items():
        src = files_dir / key
        _remove_path(dest)
        if _copy_if_exists(src, dest):
            restored["restored"].append(str(dest))

    original_codes = (_read_json(snapshot_dir / "files_snapshot.json", default={}) or {}).get("history_codes", [])
    union_codes = sorted(set(original_codes) | set(final_target_codes))
    history_live_dir = review_dir / "history"
    backup_history_dir = files_dir / "history"

    for code in union_codes:
        live_file = history_live_dir / f"{code}.json"
        if live_file.exists():
            live_file.unlink()
            restored["removed_new_history"].append(str(live_file))
        backup_file = backup_history_dir / f"{code}.json"
        if backup_file.exists():
            live_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_file, live_file)

    return restored


def _build_quant_temp_config(base_config: Path, candidate_file: Path) -> Path:
    payload = yaml.safe_load(base_config.read_text(encoding="utf-8")) or {}
    payload["candidates"] = str(candidate_file.relative_to(ROOT))
    temp_path = ROOT / "data" / "logs" / "dailyUpdateTest" / f"quant-review-{candidate_file.stem}.yaml"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return temp_path


def _baseline_summary(target_date: str) -> dict[str, Any]:
    candidates_latest = _read_json(ROOT / "data" / "candidates" / "candidates_latest.json", default={}) or {}
    return {
        "target_date_counts": _count_by_date(target_date),
        "latest_trade_date": _latest_trade_date(),
        "latest_candidate_file_date": candidates_latest.get("pick_date"),
        "target_review_codes": _collect_recommendation_codes(ROOT / "data" / "review" / target_date),
    }


def restore_snapshot(snapshot_dir: Path) -> dict[str, Any]:
    snapshot_dir = snapshot_dir.resolve()
    meta = _read_json(snapshot_dir / "meta.json")
    if not meta:
        raise RuntimeError(f"invalid snapshot dir: missing meta.json | {snapshot_dir}")

    db_rows = _read_json(snapshot_dir / "db_rows.json")
    if db_rows is None:
        raise RuntimeError(f"invalid snapshot dir: missing db_rows.json | {snapshot_dir}")

    target_date = str(meta["target_date"])
    live_target_codes = _collect_recommendation_codes(ROOT / "data" / "review" / target_date)

    _print_progress(f"开始恢复快照: {snapshot_dir}")
    result = {
        "snapshot_dir": str(snapshot_dir),
        "target_date": target_date,
        "db": _restore_table_rows(db_rows),
        "raw": _restore_raw(snapshot_dir),
        "files": _restore_files(snapshot_dir, live_target_codes),
    }
    _write_json(snapshot_dir / "restore_result.json", result)
    _print_progress(f"恢复完成: {snapshot_dir / 'restore_result.json'}")
    return result


def run_daily_update_test(args: argparse.Namespace) -> dict[str, Any]:
    target_date = args.target_date or _latest_trade_date()
    prev_date = _previous_trade_date(target_date)

    snapshot_dir = ROOT / "data" / "logs" / "dailyUpdateTest" / _now_label()
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "target_date": target_date,
        "previous_trade_date": prev_date,
        "created_at": datetime.now().isoformat(),
        "restore_after": args.restore_after,
        "with_history": args.with_history,
        "reviewer": args.reviewer,
    }
    _write_json(snapshot_dir / "meta.json", meta)
    _append_event(snapshot_dir, "test_started", meta)
    _write_runtime_state(
        snapshot_dir,
        {
            "status": "running",
            "stage": "initializing",
            "target_date": target_date,
            "previous_trade_date": prev_date,
        },
    )
    _print_progress(f"测试开始 | target_date={target_date} | previous_trade_date={prev_date}")

    baseline = _baseline_summary(target_date)
    _write_json(snapshot_dir / "baseline.json", baseline)

    table_rows = _collect_target_rows(target_date)
    _write_json(snapshot_dir / "db_rows.json", table_rows)
    files_snapshot = _snapshot_files(target_date, snapshot_dir)
    _write_json(snapshot_dir / "files_snapshot.json", files_snapshot)

    stage_results: list[StageResult] = []
    final_target_codes: list[str] = []
    summary: dict[str, Any] = {
        "meta": meta,
        "baseline": baseline,
        "status": "running",
        "stages": [],
    }

    try:
        stage_results.append(_stage(snapshot_dir, "strip_raw_target_date", _strip_target_date_from_raw, target_date, snapshot_dir))
        stage_results.append(_stage(snapshot_dir, "delete_target_rows", _delete_target_rows, target_date))

        prev_candidate_file = ROOT / "data" / "candidates" / f"candidates_{prev_date}.json"
        prev_review_config = _build_quant_temp_config(ROOT / "config" / "quant_review.yaml", prev_candidate_file)

        def phase_prev_rebuild() -> dict[str, Any]:
            details = {}
            details["preselect"] = _run_command(
                snapshot_dir,
                "phase_previous_rebuild",
                "preselect_previous_trade_date",
                [sys.executable, "-m", "pipeline.cli", "preselect", "--date", prev_date],
            )
            details["sync_candidates"] = _sync_candidates_from_latest()
            _print_progress(f"同步候选完成: previous_trade_date={prev_date} | saved={details['sync_candidates']['saved']}")
            details["quant_review"] = _run_command(
                snapshot_dir,
                "phase_previous_rebuild",
                "quant_review_previous_trade_date",
                [sys.executable, "agent/quant_reviewer.py", "--config", str(prev_review_config)],
            )
            details["sync_analysis"] = _sync_analysis_for_date(prev_date, args.reviewer)
            _print_progress(f"同步分析完成: previous_trade_date={prev_date} | saved={details['sync_analysis']['saved']}")
            return details

        def phase_incremental_fill() -> dict[str, Any]:
            return {
                "fetch_incremental": _run_command(
                    snapshot_dir,
                    "phase_incremental_fill",
                    "fetch_incremental_with_db",
                    [sys.executable, "-m", "pipeline.fetch_kline", "--incremental", "--db"],
                ),
                "after_counts": _count_by_date(target_date),
            }

        target_candidate_file = ROOT / "data" / "candidates" / f"candidates_{target_date}.json"
        target_review_config = _build_quant_temp_config(ROOT / "config" / "quant_review.yaml", target_candidate_file)

        def phase_target_rebuild() -> dict[str, Any]:
            details = {}
            details["preselect"] = _run_command(
                snapshot_dir,
                "phase_target_rebuild",
                "preselect_target_trade_date",
                [sys.executable, "-m", "pipeline.cli", "preselect", "--date", target_date],
            )
            details["sync_candidates"] = _sync_candidates_from_latest()
            _print_progress(f"同步候选完成: target_date={target_date} | saved={details['sync_candidates']['saved']}")
            details["quant_review"] = _run_command(
                snapshot_dir,
                "phase_target_rebuild",
                "quant_review_target_trade_date",
                [sys.executable, "agent/quant_reviewer.py", "--config", str(target_review_config)],
            )
            details["sync_analysis"] = _sync_analysis_for_date(target_date, args.reviewer)
            _print_progress(f"同步分析完成: target_date={target_date} | saved={details['sync_analysis']['saved']}")
            if args.with_history:
                details["top5_history"] = _generate_top5_history(target_date)
                _print_progress(f"Top5 历史生成完成: target_date={target_date} | codes={','.join(details['top5_history']['codes'])}")
            details["after_counts"] = _count_by_date(target_date)
            return details

        stage_results.append(_stage(snapshot_dir, "phase_previous_rebuild", phase_prev_rebuild))
        stage_results.append(_stage(snapshot_dir, "phase_incremental_fill", phase_incremental_fill))
        stage_results.append(_stage(snapshot_dir, "phase_target_rebuild", phase_target_rebuild))

        final_target_codes = _collect_recommendation_codes(ROOT / "data" / "review" / target_date)
        summary["status"] = "completed"
        summary["final_counts"] = _count_by_date(target_date)
        _append_event(snapshot_dir, "test_completed", {"target_date": target_date})
    except Exception as exc:
        summary["status"] = "failed"
        summary["error"] = str(exc)
        summary["final_counts"] = _count_by_date(target_date)
        _append_event(snapshot_dir, "test_failed", {"error": str(exc)})
        _print_progress(f"测试失败: {exc}")
        raise
    finally:
        summary["stages"] = [
            {
                "name": item.name,
                "elapsed_seconds": round(item.elapsed_seconds, 3),
                "details": item.details,
            }
            for item in stage_results
        ]
        elapsed_map = {item.name: round(item.elapsed_seconds, 3) for item in stage_results}
        longest = sorted(elapsed_map.items(), key=lambda pair: pair[1], reverse=True)
        summary["performance"] = {
            "total_elapsed_seconds": round(sum(item.elapsed_seconds for item in stage_results), 3),
            "longest_stages": longest[:5],
        }
        if args.restore_after:
            try:
                _print_progress("开始恢复原始状态")
                summary["restore"] = {
                    "db": _restore_table_rows(table_rows),
                    "raw": _restore_raw(snapshot_dir),
                    "files": _restore_files(snapshot_dir, final_target_codes),
                }
                _print_progress("恢复原始状态完成")
            except Exception as restore_exc:
                summary["restore"] = {
                    "status": "failed",
                    "error": str(restore_exc),
                }
        _write_json(snapshot_dir / "report.json", summary)
        _write_runtime_state(
            snapshot_dir,
            {
                "status": summary["status"],
                "stage": "finished",
                "report_file": str(snapshot_dir / "report.json"),
                "performance": summary.get("performance"),
            },
        )
        _print_progress(f"报告已写入: {snapshot_dir / 'report.json'}")

    return {
        "snapshot_dir": str(snapshot_dir),
        "target_date": target_date,
        "previous_trade_date": prev_date,
        "report_file": str(snapshot_dir / "report.json"),
        "performance": summary["performance"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run dailyUpdateTest end-to-end workflow")
    parser.add_argument(
        "--restore-snapshot-dir",
        help="Only restore from an existing snapshot dir and exit",
    )
    parser.add_argument(
        "--target-date",
        help="Target trade date in YYYY-MM-DD. Default: latest date in stock_daily",
    )
    parser.add_argument(
        "--reviewer",
        default="quant",
        choices=["quant", "glm", "qwen", "gemini"],
        help="Reviewer name used when syncing analysis rows",
    )
    parser.add_argument(
        "--with-history",
        action="store_true",
        help="Also generate top5 stock history files for the target date",
    )
    parser.add_argument(
        "--restore-after",
        action="store_true",
        help="Restore DB/raw/files from snapshot after the test finishes",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.restore_snapshot_dir:
        result = restore_snapshot(Path(args.restore_snapshot_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
        return
    result = run_daily_update_test(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
