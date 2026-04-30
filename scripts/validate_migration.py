#!/usr/bin/env python3
"""
Database Migration Validation Script
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Validates data integrity after SQLite to PostgreSQL migration.

Usage:
    python scripts/validate_migration.py --source sqlite --target postgres
    python scripts/validate_migration.py --source-url sqlite:///path/to.db --target-url postgresql://user:pass@host/db
"""
import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker


# Tables to validate (ordered by dependency)
TABLES_TO_VALIDATE = [
    "configs",
    "stocks",
    "users",
    "api_keys",
    "candidates",
    "analysis_results",
    "daily_b1_checks",
    "watchlist",
    "watchlist_analysis",
    "tasks",
    "task_logs",
    "data_update_log",
    "usage_logs",
    "audit_logs",
    "stock_daily",
]


class MigrationValidator:
    """Validates data integrity between source and target databases."""

    def __init__(self, source_url: str, target_url: str):
        self.source_engine = create_engine(source_url)
        self.target_engine = create_engine(target_url)
        self.source_session = sessionmaker(bind=self.source_engine)()
        self.target_session = sessionmaker(bind=self.target_engine)()
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_all(self) -> bool:
        """Run all validation checks."""
        print("Starting migration validation...")
        print(f"Source: {self.source_engine.url}")
        print(f"Target: {self.target_engine.url}")
        print("-" * 60)

        checks = [
            ("Schema", self._validate_schema),
            ("Row counts", self._validate_row_counts),
            ("Critical data", self._validate_critical_data),
            ("Foreign keys", self._validate_foreign_keys),
            ("Indexes", self._validate_indexes),
            ("Data samples", self._validate_data_samples),
        ]

        for name, check_func in checks:
            print(f"\n{name}:")
            try:
                check_func()
            except Exception as e:
                self.errors.append(f"{name} check failed: {e}")
                print(f"  ERROR: {e}")

        self._print_summary()
        return len(self.errors) == 0

    def _validate_schema(self):
        """Validate that all tables exist in target."""
        source_inspect = inspect(self.source_engine)
        target_inspect = inspect(self.target_engine)

        source_tables = set(source_inspect.get_table_names())
        target_tables = set(target_inspect.get_table_names())

        # Check for missing tables
        for table in TABLES_TO_VALIDATE:
            if table in source_tables:
                if table not in target_tables:
                    self.errors.append(f"Missing table: {table}")
                    print(f"  MISSING: {table}")
                else:
                    print(f"  OK: {table}")

        # Check for extra tables
        extra_tables = target_tables - source_tables - {"alembic_version"}
        if extra_tables:
            self.warnings.append(f"Extra tables in target: {extra_tables}")
            print(f"  WARNING: Extra tables: {extra_tables}")

    def _validate_row_counts(self):
        """Validate row counts match between source and target."""
        for table in TABLES_TO_VALIDATE:
            try:
                source_count = self._get_row_count(self.source_session, table)
                target_count = self._get_row_count(self.target_session, table)

                if source_count == target_count:
                    print(f"  OK: {table} ({source_count} rows)")
                else:
                    diff = target_count - source_count
                    self.errors.append(
                        f"Row count mismatch in {table}: source={source_count}, target={target_count}, diff={diff}"
                    )
                    print(f"  ERROR: {table} - source={source_count}, target={target_count}")
            except Exception as e:
                self.errors.append(f"Could not validate row count for {table}: {e}")
                print(f"  ERROR: {table} - {e}")

    def _validate_critical_data(self):
        """Validate critical business data."""
        # Check stocks exist
        stock_count = self._get_row_count(self.target_session, "stocks")
        if stock_count == 0:
            self.errors.append("No stocks found in target database")
            print("  ERROR: No stocks found")
        else:
            print(f"  OK: {stock_count} stocks")

        # Check users exist
        user_count = self._get_row_count(self.target_session, "users")
        if user_count == 0:
            self.errors.append("No users found in target database")
            print("  ERROR: No users found")
        else:
            print(f"  OK: {user_count} users")

        # Check admin user exists
        admin = self.target_session.execute(
            text("SELECT * FROM users WHERE username = :username"),
            {"username": "admin"}
        ).first()
        if admin:
            print("  OK: Admin user exists")
        else:
            self.warnings.append("Admin user not found")

    def _validate_foreign_keys(self):
        """Validate foreign key relationships."""
        # Sample a few records to check FK integrity
        checks = [
            ("SELECT * FROM watchlist WHERE user_id NOT IN (SELECT id FROM users)", "Orphaned watchlist records"),
            ("SELECT * FROM candidates WHERE code NOT IN (SELECT code FROM stocks)", "Orphaned candidates"),
            ("SELECT * FROM analysis_results WHERE code NOT IN (SELECT code FROM stocks)", "Orphaned analysis_results"),
        ]

        for query, description in checks:
            result = self.target_session.execute(text(query)).first()
            if result:
                self.errors.append(f"Foreign key violation: {description}")
                print(f"  ERROR: {description}")
            else:
                print(f"  OK: {description}")

    def _validate_indexes(self):
        """Validate critical indexes exist."""
        # Check for unique constraints
        inspector = inspect(self.target_engine)

        critical_indexes = [
            ("stocks", "code"),  # Primary key
            ("users", "username"),  # Unique
            ("api_keys", "key_hash"),  # Unique
            ("stock_daily", "uq_stock_daily_code_date"),  # Unique constraint
            ("watchlist", "uq_watchlist_user_code"),  # Unique constraint
        ]

        for table, index_name in critical_indexes:
            indexes = [idx["name"] for idx in inspector.get_indexes(table)]
            if index_name in indexes or any(
                idx.get("name") == index_name or
                any(c.get("name") == index_name for c in idx.get("column_names", []))
                for idx in inspector.get_indexes(table) + inspector.get_unique_constraints(table)
            ):
                print(f"  OK: {table}.{index_name}")
            else:
                self.warnings.append(f"Missing index: {table}.{index_name}")
                print(f"  WARNING: Missing index {table}.{index_name}")

    def _validate_data_samples(self):
        """Validate sample data integrity."""
        # Check a few stock records
        stocks = self.target_session.execute(
            text("SELECT code, name, market FROM stocks LIMIT 5")
        ).fetchall()

        if stocks:
            print(f"  OK: Sample stock data valid ({len(stocks)} samples)")
        else:
            self.errors.append("No stock data found")
            print("  ERROR: No stock data")

        # Check a few user records
        users = self.target_session.execute(
            text("SELECT id, username, role FROM users")
        ).fetchall()

        if users:
            print(f"  OK: Sample user data valid ({len(users)} users)")
        else:
            self.errors.append("No user data found")
            print("  ERROR: No user data")

    def _get_row_count(self, session: Session, table: str) -> int:
        """Get row count for a table."""
        result = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        return result or 0

    def _print_summary(self):
        """Print validation summary."""
        print("\n" + "=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)

        if self.errors:
            print(f"\nERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"  - {error}")

        if self.warnings:
            print(f"\nWARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  - {warning}")

        if not self.errors and not self.warnings:
            print("\nAll validations passed!")
        elif not self.errors:
            print(f"\nValidation passed with {len(self.warnings)} warnings.")
        else:
            print(f"\nValidation FAILED with {len(self.errors)} errors.")

        print("=" * 60)

    def close(self):
        """Close database connections."""
        self.source_session.close()
        self.target_session.close()
        self.source_engine.dispose()
        self.target_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Validate database migration")
    parser.add_argument("--source-url", help="Source database URL")
    parser.add_argument("--target-url", help="Target database URL")
    parser.add_argument("--source", choices=["sqlite", "postgres"], help="Source type")
    parser.add_argument("--target", choices=["sqlite", "postgres"], help="Target type")

    args = parser.parse_args()

    # Build URLs if not provided
    source_url = args.source_url
    target_url = args.target_url

    if not source_url or not target_url:
        from app.config import settings

        project_root = Path(__file__).parent.parent
        db_path = project_root / "data" / "db" / "stocktrade.db"

        if not source_url:
            if args.source == "postgres":
                source_url = "postgresql://stocktrade:password@localhost:5432/stocktrade"
            else:
                source_url = f"sqlite:///{db_path}"

        if not target_url:
            if args.target == "postgres":
                target_url = "postgresql://stocktrade:password@localhost:5432/stocktrade"
            else:
                target_url = f"sqlite:///{db_path}"

    validator = MigrationValidator(source_url, target_url)
    try:
        success = validator.validate_all()
        sys.exit(0 if success else 1)
    finally:
        validator.close()


if __name__ == "__main__":
    main()
