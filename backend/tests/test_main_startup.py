import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import ensure_admin_user, hydrate_runtime_env_from_db
from app.models import Config, User


def test_ensure_admin_user_sets_required_online_status(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    monkeypatch.setattr("app.main.engine", engine)

    ensure_admin_user()

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "admin").one()
        assert user.is_online is False


def test_hydrate_runtime_env_from_db_includes_tavily_key(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        db.add(Config(key="tavily_api_key", value="test-tavily-key"))
        db.commit()

    monkeypatch.setattr("app.main.engine", engine)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    hydrate_runtime_env_from_db()

    assert os.environ["TAVILY_API_KEY"] == "test-tavily-key"
