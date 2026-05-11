from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.schema_migrations import apply_startup_sql_migrations


def test_apply_startup_sql_migrations_adds_missing_steps_completed(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "add_steps_completed_column.sql").write_text(
        "ALTER TABLE tasks ADD COLUMN steps_completed TEXT DEFAULT '{}';",
        encoding="utf-8",
    )

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, task_type TEXT NOT NULL)"))

    result = apply_startup_sql_migrations(engine, migrations_dir)

    columns = {column["name"] for column in inspect(engine).get_columns("tasks")}
    assert "steps_completed" in columns
    assert result["applied"] == ["add_steps_completed_column.sql"]

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT name, status FROM schema_migrations")).fetchall()
    assert rows == [("add_steps_completed_column.sql", "applied")]


def test_apply_startup_sql_migrations_skips_when_schema_already_satisfied(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "add_steps_completed_column.sql").write_text(
        "SELECT definitely_invalid_sql;",
        encoding="utf-8",
    )

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE tasks ("
                "id INTEGER PRIMARY KEY, "
                "task_type TEXT NOT NULL, "
                "steps_completed TEXT DEFAULT '{}'"
                ")"
            )
        )

    result = apply_startup_sql_migrations(engine, migrations_dir)

    assert result["skipped"] == ["add_steps_completed_column.sql"]

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT name, status FROM schema_migrations")).fetchall()
    assert rows == [("add_steps_completed_column.sql", "skipped_existing")]


def test_apply_startup_sql_migrations_adds_watchlist_entry_date(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "add_watchlist_entry_date.sql").write_text(
        "ALTER TABLE watchlist ADD COLUMN entry_date DATE;",
        encoding="utf-8",
    )

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE watchlist (id INTEGER PRIMARY KEY, code TEXT NOT NULL)"))

    result = apply_startup_sql_migrations(engine, migrations_dir)

    columns = {column["name"] for column in inspect(engine).get_columns("watchlist")}
    assert "entry_date" in columns
    assert result["applied"] == ["add_watchlist_entry_date.sql"]


def test_apply_startup_sql_migrations_adds_tomorrow_star_run_meta_json(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "tomorrow_star_run_meta_json.sql").write_text(
        "ALTER TABLE tomorrow_star_runs ADD COLUMN meta_json JSON;",
        encoding="utf-8",
    )

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE tomorrow_star_runs ("
                "id INTEGER PRIMARY KEY, "
                "pick_date DATE NOT NULL, "
                "status TEXT NOT NULL"
                ")"
            )
        )

    result = apply_startup_sql_migrations(engine, migrations_dir)

    columns = {column["name"] for column in inspect(engine).get_columns("tomorrow_star_runs")}
    assert "meta_json" in columns
    assert result["applied"] == ["tomorrow_star_run_meta_json.sql"]


def test_apply_startup_sql_migrations_skips_tomorrow_star_run_meta_json_when_present(tmp_path: Path) -> None:
    engine = create_engine("sqlite:///:memory:")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "tomorrow_star_run_meta_json.sql").write_text(
        "SELECT definitely_invalid_sql;",
        encoding="utf-8",
    )

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE tomorrow_star_runs ("
                "id INTEGER PRIMARY KEY, "
                "pick_date DATE NOT NULL, "
                "status TEXT NOT NULL, "
                "meta_json JSON"
                ")"
            )
        )

    result = apply_startup_sql_migrations(engine, migrations_dir)

    assert result["skipped"] == ["tomorrow_star_run_meta_json.sql"]
