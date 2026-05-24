"""
管理员 CSV 导入导出 API 测试
"""
import csv
import io
from datetime import datetime

import pytest

from app.models import Stock, User, Watchlist


def _build_csv_content(headers: list[str], rows: list[dict[str, object]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


@pytest.mark.api
def test_admin_export_users_csv(test_client_with_db) -> None:
    response = test_client_with_db.get("/api/v1/auth/admin/users/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]

    content = response.content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    assert reader.fieldnames == [
        "id",
        "username",
        "display_name",
        "role",
        "is_active",
        "daily_quota",
        "last_login_at",
        "is_online",
        "created_at",
        "updated_at",
    ]
    assert len(rows) == 1
    assert rows[0]["username"] == "testuser"


@pytest.mark.api
def test_admin_import_users_csv_upserts_and_creates(test_client_with_db) -> None:
    existing_user = test_client_with_db.db.query(User).filter(User.username == "testuser").first()
    assert existing_user is not None

    headers = [
        "username",
        "display_name",
        "role",
        "is_active",
        "daily_quota",
        "last_login_at",
        "is_online",
        "created_at",
        "updated_at",
        "password",
    ]
    csv_content = _build_csv_content(
        headers,
        [
            {
                "username": "testuser",
                "display_name": "管理员更新后",
                "role": "admin",
                "is_active": "true",
                "daily_quota": "2000",
                "last_login_at": "2026-05-20T12:30:00+00:00",
                "is_online": "true",
                "created_at": "2026-05-01T00:00:00+00:00",
                "updated_at": "2026-05-22T00:00:00+00:00",
                "password": "",
            },
            {
                "username": "new_user",
                "display_name": "新用户",
                "role": "user",
                "is_active": "yes",
                "daily_quota": "123",
                "last_login_at": "",
                "is_online": "false",
                "created_at": "2026-05-23T00:00:00+00:00",
                "updated_at": "2026-05-23T01:00:00+00:00",
                "password": "secret123",
            },
        ],
    )

    response = test_client_with_db.post(
        "/api/v1/auth/admin/users/import",
        files={"upload_file": ("users.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_rows"] == 2
    assert payload["updated_count"] == 1
    assert payload["inserted_count"] == 1

    test_client_with_db.db.rollback()
    updated_user = test_client_with_db.db.query(User).filter(User.username == "testuser").first()
    created_user = test_client_with_db.db.query(User).filter(User.username == "new_user").first()

    assert updated_user is not None
    assert updated_user.display_name == "管理员更新后"
    assert updated_user.role == "admin"
    assert updated_user.daily_quota == 2000
    assert updated_user.is_online is True
    assert updated_user.last_login_at == datetime(2026, 5, 20, 12, 30)
    assert created_user is not None
    assert created_user.is_active is True
    assert created_user.role == "user"


@pytest.mark.api
def test_admin_import_users_csv_validation_fails(test_client_with_db) -> None:
    csv_content = _build_csv_content(
        ["username", "role", "is_active", "daily_quota"],
        [
            {
                "username": "bad_row",
                "role": "user",
                "is_active": "maybe",
                "daily_quota": "100",
            }
        ],
    )

    response = test_client_with_db.post(
        "/api/v1/auth/admin/users/import",
        files={"upload_file": ("users.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 400
    assert "有效布尔值" in response.json()["detail"]


@pytest.mark.api
def test_admin_import_watchlist_csv_upserts_and_validates_stock(test_client_with_db) -> None:
    test_client_with_db.db.add(Stock(code="600000", name="浦发银行", market="SH"))
    test_client_with_db.db.commit()

    headers = [
        "username",
        "code",
        "add_reason",
        "entry_price",
        "entry_date",
        "position_ratio",
        "priority",
        "is_active",
        "added_at",
    ]
    csv_content = _build_csv_content(
        headers,
        [
            {
                "username": "testuser",
                "code": "600000",
                "add_reason": "技术面强势",
                "entry_price": "10.5",
                "entry_date": "2026-05-24",
                "position_ratio": "0.35",
                "priority": "2",
                "is_active": "true",
                "added_at": "2026-05-24T09:30:00+00:00",
            }
        ],
    )

    response = test_client_with_db.post(
        "/api/v1/auth/admin/watchlist/import",
        files={"upload_file": ("watchlist.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_rows"] == 1
    assert payload["inserted_count"] == 1

    test_client_with_db.db.rollback()
    watchlist = test_client_with_db.db.query(Watchlist).filter(Watchlist.code == "600000").first()
    assert watchlist is not None
    assert watchlist.user_id == test_client_with_db.db.query(User).filter(User.username == "testuser").first().id
    assert watchlist.position_ratio == 0.35
    assert watchlist.is_active is True


@pytest.mark.api
def test_admin_import_watchlist_csv_rejects_unknown_stock(test_client_with_db) -> None:
    csv_content = _build_csv_content(
        ["username", "code", "is_active", "priority"],
        [
            {
                "username": "testuser",
                "code": "999999",
                "is_active": "true",
                "priority": "1",
            }
        ],
    )

    response = test_client_with_db.post(
        "/api/v1/auth/admin/watchlist/import",
        files={"upload_file": ("watchlist.csv", csv_content, "text/csv")},
    )

    assert response.status_code == 400
    assert "股票不存在" in response.json()["detail"]
