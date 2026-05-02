#!/usr/bin/env python3
"""
Data Migration Script: SQLite to PostgreSQL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Migrates data from SQLite to PostgreSQL for StockTradebyZ.

Usage:
    # Dry run (validate only)
    python scripts/migrate_data.py --dry-run

    # Full migration
    python scripts/migrate_data.py --source sqlite:///path/to/source.db --target postgresql://user:pass@host/db

    # Using environment variables
    export SOURCE_DB="sqlite:///data/db/stocktrade.db"
    export TARGET_DB="postgresql://stocktrade:password@localhost:5432/stocktrade"
    python scripts/migrate_data.py
"""
import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

# Add project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.models import (
    AuditLog, ApiKey, AnalysisResult, Candidate, Config, DailyB1Check,
    DataUpdateLog, Stock, StockDaily, Task, TaskLog, UsageLog, User,
    Watchlist, WatchlistAnalysis,
)


# Define migration order (respecting foreign keys)
MIGRATION_ORDER = [
    ("configs", Config),
    ("stocks", Stock),
    ("users", User),
    ("api_keys", ApiKey),
    ("candidates", Candidate),
    ("analysis_results", AnalysisResult),
    ("daily_b1_checks", DailyB1Check),
    ("watchlist", Watchlist),
    ("watchlist_analysis", WatchlistAnalysis),
    ("tasks", Task),
    ("task_logs", TaskLog),
    ("data_update_log", DataUpdateLog),
    ("usage_logs", UsageLog),
    ("audit_logs", AuditLog),
    ("stock_daily", StockDaily),
]


class DataMigrator:
    """Handles data migration from SQLite to PostgreSQL."""

    def __init__(self, source_url: str, target_url: str, batch_size: int = 1000):
        self.source_engine = create_engine(source_url)
        self.target_engine = create_engine(target_url)
        self.source_session = sessionmaker(bind=self.source_engine)()
        self.target_session = sessionmaker(bind=self.target_engine)()
        self.batch_size = batch_size
        self.stats: Dict[str, int] = {"tables": 0, "rows": 0, "errors": 0}

    def migrate(self, dry_run: bool = False) -> bool:
        """Execute full migration."""
        print("=" * 60)
        print("DATA MIGRATION: SQLite to PostgreSQL")
        print("=" * 60)
        print(f"Source: {self.source_engine.url}")
        print(f"Target: {self.target_engine.url}")
        print(f"Batch size: {self.batch_size}")
        print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
        print("-" * 60)

        if dry_run:
            print("\n*** DRY RUN MODE - No data will be written ***\n")

        # Step 1: Create schema
        print("\n[1/4] Creating schema in target database...")
        if not dry_run:
            if not self._create_schema():
                print("ERROR: Schema creation failed")
                return False
        else:
            print("  DRY RUN: Would create schema")

        # Step 2: Migrate tables
        print("\n[2/4] Migrating table data...")
        for table_name, model in MIGRATION_ORDER:
            self._migrate_table(table_name, model, dry_run)

        # Step 3: Reset sequences (for auto-increment IDs)
        if not dry_run:
            print("\n[3/4] Resetting sequences...")
            self._reset_sequences()
        else:
            print("\n[3/4] DRY RUN: Would reset sequences")

        # Step 4: Verify
        print("\n[4/4] Verifying migration...")
        if not self._verify_migration():
            print("WARNING: Verification found issues")

        self._print_summary()
        return self.stats["errors"] == 0

    def _create_schema(self) -> bool:
        """Create all tables in target database."""
        try:
            # Create all tables using SQLAlchemy models
            from app.database import Base
            Base.metadata.create_all(self.target_engine)
            print("  Schema created successfully")
            return True
        except Exception as e:
            print(f"  ERROR: {e}")
            return False

    def _migrate_table(self, table_name: str, model, dry_run: bool):
        """Migrate a single table."""
        print(f"\n  Migrating {table_name}...")

        try:
            # Get row count
            source_count = self.source_session.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar()

            if source_count == 0:
                print(f"    SKIP: No data in {table_name}")
                return

            print(f"    Source rows: {source_count:,}")

            # Clear target table if not empty
            target_count = self.target_session.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar()

            if target_count > 0:
                if dry_run:
                    print(f"    DRY RUN: Would clear {target_count:,} existing rows")
                else:
                    print(f"    Clearing {target_count:,} existing rows...")
                    self.target_session.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))
                    self.target_session.commit()

            # Migrate in batches
            migrated = 0
            offset = 0

            while offset < source_count:
                # Fetch batch from source
                query = self.source_session.query(model).offset(offset).limit(self.batch_size)
                batch = query.all()

                if not batch:
                    break

                if not dry_run:
                    # Insert batch to target
                    for row in batch:
                        # Convert to dict and handle datetime serialization
                        row_dict = self._row_to_dict(row)
                        self.target_session.execute(
                            text(f"INSERT INTO {table_name} ({', '.join(row_dict.keys())}) "
                                 f"VALUES ({', '.join([f':{k}' for k in row_dict.keys()])})"),
                            row_dict
                        )

                    self.target_session.commit()

                migrated += len(batch)
                offset += len(batch)

                # Progress indicator
                progress = (migrated / source_count) * 100
                print(f"    Progress: {migrated:,}/{source_count:,} ({progress:.1f}%)")

            self.stats["tables"] += 1
            self.stats["rows"] += migrated
            print(f"  OK: Migrated {migrated:,} rows from {table_name}")

        except Exception as e:
            self.stats["errors"] += 1
            print(f"  ERROR: Failed to migrate {table_name}: {e}")
            import traceback
            traceback.print_exc()

    def _row_to_dict(self, row) -> Dict[str, Any]:
        """Convert SQLAlchemy model row to dictionary, handling datetime serialization."""
        result = {}
        for column in row.__table__.columns:
            value = getattr(row, column.name)
            if value is None:
                result[column.name] = None
            elif isinstance(value, datetime):
                result[column.name] = value.isoformat()
            elif hasattr(value, "isoformat"):  # date, time
                result[column.name] = value.isoformat()
            elif isinstance(value, dict):  # JSON columns
                import json
                result[column.name] = json.dumps(value)
            else:
                result[column.name] = value
        return result

    def _reset_sequences(self):
        """Reset PostgreSQL sequences after data migration."""
        try:
            # Get all tables and their sequences
            inspector = inspect(self.target_engine)

            for table_name, _ in MIGRATION_ORDER:
                # Find the primary key column
                columns = inspector.get_columns(table_name)
                pk_constraint = inspector.get_pk_constraint(table_name)

                if pk_constraint and pk_constraint.get("constrained_columns"):
                    pk_column = pk_constraint["constrained_columns"][0]
                    sequence_name = f"{table_name}_{pk_column}_seq"

                    # Get max ID from table
                    max_id = self.target_session.execute(
                        text(f"SELECT COALESCE(MAX({pk_column}), 0) FROM {table_name}")
                    ).scalar()

                    if max_id > 0:
                        # Reset sequence to max_id + 1
                        self.target_session.execute(
                            text(f"SELECT setval('{sequence_name}', {max_id}, true)")
                        )
                        self.target_session.commit()
                        print(f"  Reset {sequence_name} to {max_id + 1}")

        except Exception as e:
            print(f"  WARNING: Could not reset all sequences: {e}")

    def _verify_migration(self) -> bool:
        """Verify that row counts match between source and target."""
        print("\n  Verifying row counts...")
        all_match = True

        for table_name, _ in MIGRATION_ORDER:
            try:
                source_count = self.source_session.execute(
                    text(f"SELECT COUNT(*) FROM {table_name}")
                ).scalar()

                target_count = self.target_session.execute(
                    text(f"SELECT COUNT(*) FROM {table_name}")
                ).scalar()

                if source_count == target_count:
                    print(f"    OK: {table_name} ({source_count:,} rows)")
                else:
                    print(f"    MISMATCH: {table_name} - source: {source_count:,}, target: {target_count:,}")
                    all_match = False
            except Exception as e:
                print(f"    ERROR: Could not verify {table_name}: {e}")
                all_match = False

        return all_match

    def _print_summary(self):
        """Print migration summary."""
        print("\n" + "=" * 60)
        print("MIGRATION SUMMARY")
        print("=" * 60)
        print(f"Tables processed: {self.stats['tables']}")
        print(f"Total rows migrated: {self.stats['rows']:,}")
        print(f"Errors encountered: {self.stats['errors']}")
        print("=" * 60)

        if self.stats["errors"] == 0:
            print("\nMigration completed successfully!")
        else:
            print(f"\nMigration completed with {self.stats['errors']} errors.")
            print("Please review the errors above.")

    def close(self):
        """Close database connections."""
        self.source_session.close()
        self.target_session.close()
        self.source_engine.dispose()
        self.target_engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Migrate data from SQLite to PostgreSQL")
    parser.add_argument("--source-url", help="Source database URL")
    parser.add_argument("--target-url", help="Target database URL")
    parser.add_argument("--dry-run", action="store_true", help="Validate without migrating data")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for migration")

    args = parser.parse_args()

    # Build URLs from environment or defaults
    source_url = args.source_url or os.getenv("SOURCE_DB")
    target_url = args.target_url or os.getenv("TARGET_DB")

    if not source_url:
        from app.config import settings
        db_path = project_root / "data" / "db" / "stocktrade.db"
        source_url = f"sqlite:///{db_path}"

    if not target_url:
        target_url = "postgresql://stocktrade:change_me@localhost:5432/stocktrade"

    print(f"\nSource: {source_url}")
    print(f"Target: {target_url}")

    if not args.dry_run:
        # Confirm before proceeding
        response = input("\nProceed with migration? (yes/no): ")
        if response.lower() != "yes":
            print("Migration cancelled.")
            return 0

    migrator = DataMigrator(source_url, target_url, batch_size=args.batch_size)
    try:
        success = migrator.migrate(dry_run=args.dry_run)
        return 0 if success else 1
    finally:
        migrator.close()


if __name__ == "__main__":
    sys.exit(main())
