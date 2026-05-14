#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

if (
    os.environ.get("STOCKTRADE_IMPORT_USERS_BOOTSTRAPPED") != "1"
    and VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
):
    env = dict(os.environ)
    env["STOCKTRADE_IMPORT_USERS_BOOTSTRAPPED"] = "1"
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]], env)

pythonpath_entries = [entry for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry]
for required_path in (str(ROOT), str(BACKEND)):
    if required_path not in pythonpath_entries:
        pythonpath_entries.append(required_path)
    if required_path not in sys.path:
        sys.path.insert(0, required_path)
if pythonpath_entries:
    os.environ["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

from sqlalchemy import text


@dataclass
class ImportedUserRow:
    id: int
    username: str
    hashed_password: str
    display_name: str | None
    role: str
    is_active: bool
    daily_quota: int
    created_at: datetime | None
    updated_at: datetime | None
    source_file: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 user/*/users.csv 导入用户到当前系统")
    parser.add_argument(
        "--database-url",
        default=None,
        help="可选，显式指定 DATABASE_URL。适用于宿主机直连本地 5432 等场景。",
    )
    parser.add_argument(
        "--source-dir",
        default=str(ROOT / "user"),
        help="导出目录根路径，默认仓库根目录下的 user/",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="用户名已存在时，同步 display_name/role/is_active/daily_quota/hashed_password/时间戳",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要导入的结果，不写数据库",
    )
    return parser.parse_args()


def get_app_models():
    from app.database import SessionLocal
    from app.models import User

    return SessionLocal, User


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"t", "true", "1", "y", "yes"}:
        return True
    if lowered in {"f", "false", "0", "n", "no"}:
        return False
    raise ValueError(f"无法解析布尔值: {value!r}")


def parse_datetime(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_nullable_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def discover_csv_files(source_dir: Path) -> list[Path]:
    if not source_dir.exists():
        raise FileNotFoundError(f"导出目录不存在: {source_dir}")
    csv_files = sorted(
        child / "users.csv"
        for child in source_dir.iterdir()
        if child.is_dir() and (child / "users.csv").exists()
    )
    if not csv_files:
        raise FileNotFoundError(f"未在 {source_dir} 下找到任何 */users.csv")
    return csv_files


def load_rows(csv_files: list[Path]) -> list[ImportedUserRow]:
    rows_by_username: dict[str, ImportedUserRow] = {}
    for csv_file in csv_files:
        with csv_file.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                username = raw["username"].strip()
                rows_by_username[username] = ImportedUserRow(
                    id=int(raw["id"]),
                    username=username,
                    hashed_password=raw["hashed_password"].strip(),
                    display_name=parse_nullable_text(raw.get("display_name")),
                    role=raw["role"].strip() or "user",
                    is_active=parse_bool(raw["is_active"]),
                    daily_quota=int(raw["daily_quota"]),
                    created_at=parse_datetime(raw["created_at"]),
                    updated_at=parse_datetime(raw["updated_at"]),
                    source_file=csv_file,
                )
    return sorted(rows_by_username.values(), key=lambda item: (item.id, item.username))


def apply_user_fields(user: User, row: ImportedUserRow) -> bool:
    changed = False
    fields = {
        "hashed_password": row.hashed_password,
        "display_name": row.display_name,
        "role": row.role,
        "is_active": row.is_active,
        "daily_quota": row.daily_quota,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    for field_name, new_value in fields.items():
        if getattr(user, field_name) != new_value:
            setattr(user, field_name, new_value)
            changed = True
    return changed


def sync_users(rows: list[ImportedUserRow], update_existing: bool, dry_run: bool) -> dict[str, int]:
    SessionLocal, User = get_app_models()
    summary = {
        "total_rows": len(rows),
        "inserted": 0,
        "updated": 0,
        "skipped_existing": 0,
        "id_reassigned": 0,
    }

    with SessionLocal() as db:
        existing_users = db.query(User).all()
        users_by_username = {user.username: user for user in existing_users}
        used_ids = {user.id for user in existing_users}

        for row in rows:
            existing = users_by_username.get(row.username)
            if existing is not None:
                if update_existing and apply_user_fields(existing, row):
                    summary["updated"] += 1
                else:
                    summary["skipped_existing"] += 1
                continue

            new_user = User(
                username=row.username,
                hashed_password=row.hashed_password,
                display_name=row.display_name,
                role=row.role,
                is_active=row.is_active,
                daily_quota=row.daily_quota,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            if row.id not in used_ids:
                new_user.id = row.id
            else:
                summary["id_reassigned"] += 1

            db.add(new_user)
            if not dry_run:
                db.flush()
                used_ids.add(new_user.id)
                users_by_username[new_user.username] = new_user
            summary["inserted"] += 1

        if dry_run:
            db.rollback()
            return summary

        db.commit()
        db.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence('users', 'id'),
                    COALESCE((SELECT MAX(id) FROM users), 1),
                    true
                )
                """
            )
        )
        db.commit()

    return summary


def main() -> int:
    args = parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    source_dir = Path(args.source_dir).resolve()
    csv_files = discover_csv_files(source_dir)
    rows = load_rows(csv_files)

    print("发现以下用户导出文件:")
    for csv_file in csv_files:
        print(f"  - {csv_file}")
    print(f"共读取 {len(rows)} 个唯一用户名")

    summary = sync_users(rows, update_existing=args.update_existing, dry_run=args.dry_run)

    print("导入结果:")
    print(f"  total_rows={summary['total_rows']}")
    print(f"  inserted={summary['inserted']}")
    print(f"  updated={summary['updated']}")
    print(f"  skipped_existing={summary['skipped_existing']}")
    print(f"  id_reassigned={summary['id_reassigned']}")
    print(f"  dry_run={str(args.dry_run).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
