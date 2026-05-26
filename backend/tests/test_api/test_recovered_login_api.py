from app.auth import verify_password
from app.models import User


def test_recovered_user_first_login_initializes_password(test_client_with_db) -> None:
    response = test_client_with_db.post(
        "/api/v1/auth/login",
        json={"username": "307god", "password": "first-pass"},
    )

    assert response.status_code == 200
    user = test_client_with_db.db.query(User).filter(User.username == "307god").one()
    assert user.id == 3
    assert user.role == "user"
    assert verify_password("first-pass", user.hashed_password)


def test_recovered_user_second_login_requires_initialized_password(test_client_with_db) -> None:
    first = test_client_with_db.post(
        "/api/v1/auth/login",
        json={"username": "307god", "password": "first-pass"},
    )
    assert first.status_code == 200

    wrong = test_client_with_db.post(
        "/api/v1/auth/login",
        json={"username": "307god", "password": "wrong-pass"},
    )
    assert wrong.status_code == 401

    correct = test_client_with_db.post(
        "/api/v1/auth/login",
        json={"username": "307god", "password": "first-pass"},
    )
    assert correct.status_code == 200


def test_admin_is_not_recovered_by_legacy_login_path(test_client_with_db) -> None:
    test_client_with_db.db.query(User).filter(User.username == "admin").delete()
    test_client_with_db.db.commit()

    response = test_client_with_db.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "anything"},
    )

    assert response.status_code == 401
    assert test_client_with_db.db.query(User).filter(User.username == "admin").first() is None
