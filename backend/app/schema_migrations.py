"""
Startup schema migrations
~~~~~~~~~~~~~~~~~~~~~~~~~
Apply SQL migrations for existing databases that were created before new
columns/constraints were introduced.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

_MIGRATION_STATUS_APPLIED = "applied"
_MIGRATION_STATUS_SKIPPED = "skipped_existing"
_MigrationCheck = Callable[[Any], bool]


def _has_table(inspector: Any, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_column(inspector: Any, table_name: str, column_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def _has_unique_constraint(inspector: Any, table_name: str, constraint_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    constraints = inspector.get_unique_constraints(table_name)
    return any(item.get("name") == constraint_name for item in constraints)


def _has_index(inspector: Any, table_name: str, index_name: str) -> bool:
    if not _has_table(inspector, table_name):
        return False
    indexes = inspector.get_indexes(table_name)
    return any(item.get("name") == index_name for item in indexes)


def _tomorrow_star_migration_satisfied(inspector: Any) -> bool:
    return (
        _has_table(inspector, "tomorrow_star_runs")
        and _has_unique_constraint(inspector, "candidates", "uq_candidates_pick_date_code")
        and _has_unique_constraint(inspector, "analysis_results", "uq_analysis_results_pick_date_code_reviewer")
        and _has_index(inspector, "candidates", "ix_candidates_pick_date_code")
        and _has_index(inspector, "analysis_results", "ix_analysis_results_pick_date_code")
    )


def _daily_b1_detail_migration_satisfied(inspector: Any) -> bool:
    return (
        _has_table(inspector, "daily_b1_check_details")
        and _has_unique_constraint(inspector, "daily_b1_checks", "uq_daily_b1_checks_code_check_date")
        and _has_unique_constraint(inspector, "daily_b1_check_details", "uq_daily_b1_check_details_code_check_date")
        and _has_index(inspector, "daily_b1_checks", "ix_daily_b1_checks_code_check_date")
        and _has_index(inspector, "daily_b1_check_details", "ix_daily_b1_check_details_code_check_date")
    )


def _stock_analysis_migration_satisfied(inspector: Any) -> bool:
    return _has_table(inspector, "stock_analysis")


def _task_steps_completed_migration_satisfied(inspector: Any) -> bool:
    return _has_column(inspector, "tasks", "steps_completed")


def _raw_data_manifest_migration_satisfied(inspector: Any) -> bool:
    return (
        _has_table(inspector, "raw_data_batches")
        and _has_table(inspector, "raw_data_manifest")
        and _has_unique_constraint(inspector, "raw_data_manifest", "uq_raw_data_manifest_trade_date")
        and _has_index(inspector, "raw_data_batches", "ix_raw_data_batches_status_trade_date")
        and _has_index(inspector, "raw_data_manifest", "ix_raw_data_manifest_status_trade_date")
    )


def _candidate_consecutive_metrics_migration_satisfied(inspector: Any) -> bool:
    return (
        _has_column(inspector, "candidates", "consecutive_days")
        and _has_column(inspector, "tomorrow_star_runs", "consecutive_candidate_count")
    )


def _tomorrow_star_run_meta_json_migration_satisfied(inspector: Any) -> bool:
    return _has_column(inspector, "tomorrow_star_runs", "meta_json")


def _current_hot_tables_migration_satisfied(inspector: Any) -> bool:
    return (
        _has_table(inspector, "current_hot_runs")
        and _has_table(inspector, "current_hot_candidates")
        and _has_table(inspector, "current_hot_analysis_results")
        and _has_table(inspector, "current_hot_intraday_snapshots")
        and _has_unique_constraint(inspector, "current_hot_runs", "uq_current_hot_runs_pick_date")
        and _has_unique_constraint(inspector, "current_hot_candidates", "uq_current_hot_candidates_pick_date_code")
        and _has_unique_constraint(
            inspector,
            "current_hot_analysis_results",
            "uq_current_hot_analysis_results_pick_date_code_reviewer",
        )
        and _has_unique_constraint(
            inspector,
            "current_hot_intraday_snapshots",
            "uq_current_hot_intraday_snapshots_trade_date_code",
        )
    )


def _stock_daily_market_metrics_migration_satisfied(inspector: Any) -> bool:
    required_columns = {
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "free_share",
        "circ_mv",
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
        "net_mf_amount",
    }
    return all(_has_column(inspector, "stock_daily", column) for column in required_columns)


def _daily_b1_check_market_metrics_migration_satisfied(inspector: Any) -> bool:
    required_columns = {
        "active_pool_rank",
        "turnover_rate",
        "volume_ratio",
    }
    return all(_has_column(inspector, "daily_b1_checks", column) for column in required_columns)


def _active_pool_rank_migration_satisfied(inspector: Any) -> bool:
    return (
        _has_table(inspector, "stock_active_pool_ranks")
        and _has_unique_constraint(
            inspector,
            "stock_active_pool_ranks",
            "uq_stock_active_pool_ranks_date_code_params",
        )
        and _has_index(inspector, "stock_active_pool_ranks", "ix_stock_active_pool_ranks_date_rank")
        and _has_index(inspector, "stock_active_pool_ranks", "ix_stock_active_pool_ranks_code_date")
        and _has_index(inspector, "stock_active_pool_ranks", "ix_stock_active_pool_ranks_code_date_params")
    )


def _watchlist_entry_date_migration_satisfied(inspector: Any) -> bool:
    return _has_column(inspector, "watchlist", "entry_date")


_COMPATIBILITY_CHECKS: dict[str, _MigrationCheck] = {
    "tomorrow_star_180d.sql": _tomorrow_star_migration_satisfied,
    "daily_b1_check_details_180d.sql": _daily_b1_detail_migration_satisfied,
    "add_stock_analysis_table.sql": _stock_analysis_migration_satisfied,
    "add_steps_completed_column.sql": _task_steps_completed_migration_satisfied,
    "add_raw_data_manifest_tables.sql": _raw_data_manifest_migration_satisfied,
    "add_candidate_consecutive_metrics.sql": _candidate_consecutive_metrics_migration_satisfied,
    "tomorrow_star_run_meta_json.sql": _tomorrow_star_run_meta_json_migration_satisfied,
    "add_current_hot_tables.sql": _current_hot_tables_migration_satisfied,
    "add_stock_daily_market_metrics.sql": _stock_daily_market_metrics_migration_satisfied,
    "add_daily_b1_check_market_metrics.sql": _daily_b1_check_market_metrics_migration_satisfied,
    "add_stock_active_pool_ranks.sql": _active_pool_rank_migration_satisfied,
    "add_watchlist_entry_date.sql": _watchlist_entry_date_migration_satisfied,
}


def _ensure_schema_migrations_table(engine: Engine) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        name TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))


def _get_recorded_migrations(engine: Engine) -> set[str]:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT name FROM schema_migrations")).fetchall()
    return {str(row[0]) for row in rows}


def _record_migration(engine: Engine, name: str, status: str) -> None:
    stmt = (
        "INSERT INTO schema_migrations (name, status) VALUES (:name, :status) "
        "ON CONFLICT (name) DO NOTHING"
    )
    if engine.dialect.name == "sqlite":
        stmt = "INSERT OR IGNORE INTO schema_migrations (name, status) VALUES (:name, :status)"

    with engine.begin() as conn:
        conn.execute(text(stmt), {"name": name, "status": status})


def _execute_sql_script(engine: Engine, sql_text: str) -> None:
    raw_connection = engine.raw_connection()
    try:
        if engine.dialect.name == "sqlite":
            raw_connection.executescript(sql_text)
            return

        previous_autocommit = getattr(raw_connection, "autocommit", None)
        if previous_autocommit is not None:
            raw_connection.autocommit = True

        try:
            with raw_connection.cursor() as cursor:
                cursor.execute(sql_text)
        finally:
            if previous_autocommit is not None:
                raw_connection.autocommit = previous_autocommit

        raw_connection.commit()
    finally:
        raw_connection.close()


def apply_startup_sql_migrations(engine: Engine, migrations_dir: Path) -> dict[str, list[str]]:
    """Apply startup SQL migrations and record their status.

    Existing databases may already satisfy a migration's final schema state while
    lacking any migration bookkeeping. In that case we record the migration and
    skip execution to avoid duplicate constraint errors.
    """
    if not migrations_dir.exists():
        logger.info("Schema migrations directory does not exist: %s", migrations_dir)
        return {"applied": [], "skipped": [], "already_recorded": []}

    _ensure_schema_migrations_table(engine)

    recorded = _get_recorded_migrations(engine)
    results = {"applied": [], "skipped": [], "already_recorded": []}

    for migration_path in sorted(migrations_dir.glob("*.sql")):
        name = migration_path.name
        if name in recorded:
            results["already_recorded"].append(name)
            continue

        inspector = inspect(engine)
        checker = _COMPATIBILITY_CHECKS.get(name)
        if checker and checker(inspector):
            _record_migration(engine, name, _MIGRATION_STATUS_SKIPPED)
            recorded.add(name)
            results["skipped"].append(name)
            logger.info("Schema migration already satisfied, recorded without execution: %s", name)
            continue

        sql_text = migration_path.read_text(encoding="utf-8")
        try:
            _execute_sql_script(engine, sql_text)
        except SQLAlchemyError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Failed to apply schema migration {name}: {exc}") from exc

        _record_migration(engine, name, _MIGRATION_STATUS_APPLIED)
        recorded.add(name)
        results["applied"].append(name)
        logger.info("Applied schema migration: %s", name)

    return results
