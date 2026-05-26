from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import ensure_admin_user
from app.models import User


def test_ensure_admin_user_sets_required_online_status(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    monkeypatch.setattr("app.main.engine", engine)

    ensure_admin_user()

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "admin").one()
        assert user.is_online is False
