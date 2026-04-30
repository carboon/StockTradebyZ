# Database Migration Plan: SQLite to PostgreSQL

## Overview

This document outlines the migration plan from SQLite to PostgreSQL for the StockTradebyZ application.

## Current Database Schema

### Core Tables (Priority 1 - Critical Business Data)

| Table Name | Description | Estimated Rows | Migration Complexity |
|------------|-------------|----------------|---------------------|
| `stocks` | Stock basic information | ~5,000 | Low |
| `users` | User accounts | < 100 | Low |
| `api_keys` | API keys for authentication | < 500 | Low |
| `watchlist` | User watchlist items | < 1,000 | Low |
| `candidates` | Daily stock candidates | ~50-200/day | Medium |
| `analysis_results` | AI/Quant analysis results | ~50-200/day | Medium |
| `stock_daily` | K-line/daily price data | ~500,000+ | High |

### Supporting Tables (Priority 2 - System Data)

| Table Name | Description | Estimated Rows | Migration Complexity |
|------------|-------------|----------------|---------------------|
| `configs` | System configuration | < 50 | Low |
| `daily_b1_checks` | Single stock diagnosis history | ~1,000-5,000 | Medium |
| `watchlist_analysis` | Watchlist analysis history | < 1,000 | Medium |
| `tasks` | Background task records | < 1,000 | Low |
| `task_logs` | Task execution logs | ~10,000+ | Medium |
| `data_update_log` | Data update records | < 500 | Low |
| `usage_logs` | API usage logs | ~10,000+ | Low |
| `audit_logs` | Audit trail | ~5,000+ | Low |

## SQLAlchemy Compatibility Assessment

### Current SQLite-Specific Configuration

```python
# backend/app/database.py
sqlite_connect_args = {
    "check_same_thread": False,
    "timeout": 30,
}

engine = create_engine(
    settings.database_url,
    connect_args=sqlite_connect_args,
    echo=settings.debug,
    poolclass=StaticPool,
)
```

### Required Changes for PostgreSQL

The current `database.py` already has conditional logic for non-SQLite databases (lines 38-42), which is good. However, the following changes are needed:

1. **Remove SQLite-specific pragmas** (WAL mode, synchronous settings)
2. **Update connection pooling** - PostgreSQL requires different pool settings
3. **Update database URL format** in `config.py`
4. **Handle JSON column differences** - SQLite stores as TEXT, PostgreSQL has native JSON/JSONB

### Configuration Compatibility

| Feature | SQLite | PostgreSQL | Compatible |
|---------|--------|------------|------------|
| DateTime(timezone=True) | Stored as TEXT | TIMESTAMP WITH TIME ZONE | Yes (auto-convert) |
| JSON column | TEXT | JSONB | Yes (SQLAlchemy handles) |
| Float | REAL | DOUBLE PRECISION | Yes |
| String(10) | TEXT | VARCHAR(10) | Yes |
| Boolean | INTEGER | BOOLEAN | Yes (auto-convert) |
| Auto-increment ID | AUTOINCREMENT | SERIAL/SEQUENCE | Yes |

## Query Pattern Analysis & Index Recommendations

### Current Query Patterns

Based on code analysis, here are the most common query patterns:

1. **Stock lookups by code**
   - `db.query(Stock).filter(Stock.code == code).first()`
   - Already indexed: `stocks.code` (primary key)

2. **Candidate filtering by date**
   - `db.query(Candidate).filter(Candidate.pick_date == date)`
   - Already indexed: `candidates.pick_date`

3. **User filtering in watchlist**
   - `db.query(Watchlist).filter(Watchlist.user_id == user.id, Watchlist.is_active == True)`
   - Already indexed: `watchlist.user_id`
   - **Recommendation**: Add composite index on `(user_id, is_active)`

4. **Task logs by task_id**
   - `db.query(TaskLog).filter(TaskLog.task_id == task_id)`
   - Already indexed: `task_logs.task_id`

5. **Usage logs by date**
   - `db.query(UsageLog).filter(UsageLog.created_at >= start)`
   - Already indexed: `usage_logs.created_at`

6. **Stock daily data queries**
   - `db.query(StockDaily).filter(StockDaily.code == code, StockDaily.trade_date >= start, StockDaily.trade_date <= end)`
   - Already indexed: `stock_daily.code`, `stock_daily.trade_date`
   - **Recommendation**: Add composite index on `(code, trade_date)` (already has unique constraint)

### Recommended Additional Indexes

```sql
-- For watchlist active queries
CREATE INDEX idx_watchlist_user_active ON watchlist(user_id, is_active);

-- For analysis results date filtering with code
CREATE INDEX idx_analysis_results_date_code ON analysis_results(pick_date, code);

-- For daily B1 checks date filtering
CREATE INDEX idx_daily_b1_checks_date_code ON daily_b1_checks(check_date, code);

-- For candidates date + code filtering
CREATE INDEX idx_candidates_date_code ON candidates(pick_date, code);

-- For audit logs user + date filtering
CREATE INDEX idx_audit_logs_user_date ON audit_logs(user_id, created_at);

-- For usage logs user + date filtering
CREATE INDEX idx_usage_logs_user_date ON usage_logs(user_id, created_at);

-- For task filtering by status and type
CREATE INDEX idx_tasks_status_type ON tasks(status, task_type);
```

## Migration Strategy

### Phase 1: Preparation

1. **Update configuration support**
   - Modify `config.py` to support PostgreSQL connection string
   - Update `database.py` connection pooling for PostgreSQL

2. **Create migration script**
   - Use SQLAlchemy to export schema
   - Generate PostgreSQL-compatible DDL

3. **Set up PostgreSQL instance**
   - Install PostgreSQL 14+
   - Create database and user
   - Configure connection limits

### Phase 2: Schema Migration

1. **Create PostgreSQL schema**
   ```bash
   python scripts/migrate_schema.py --engine postgresql
   ```

2. **Verify schema compatibility**
   - Check all tables created successfully
   - Verify constraints and indexes

### Phase 3: Data Migration

1. **Export data from SQLite**
   ```bash
   python scripts/export_sqlite.py --output /tmp/stocktrade_dump.json
   ```

2. **Import to PostgreSQL**
   ```bash
   python scripts/import_postgres.py --input /tmp/stocktrade_dump.json
   ```

3. **Verify data integrity**
   - Run validation script
   - Compare row counts
   - Spot-check critical data

### Phase 4: Cutover

1. **Stop application**
2. **Final data sync** (incremental if needed)
3. **Update configuration** to point to PostgreSQL
4. **Start application**
5. **Monitor** for errors

## Rollback Plan

If migration fails:

1. Stop application
2. Update configuration back to SQLite
3. Restore from backup if needed
4. Start application

Estimated rollback time: < 5 minutes

## Post-Migration Tasks

1. **Update backup strategy** - PostgreSQL requires different backup approach (pg_dump)
2. **Configure connection pooling** - Tune for PostgreSQL
3. **Set up replication** - If high availability is needed
4. **Monitor performance** - Check query execution times
5. **Update documentation** - Reflect new database in deployment docs

## Migration Validation

See `scripts/validate_migration.py` for automated validation checks.

## Estimated Timeline

- **Phase 1 (Preparation)**: 1-2 hours
- **Phase 2 (Schema)**: 30 minutes
- **Phase 3 (Data)**: 1-3 hours (depending on data volume)
- **Phase 4 (Cutover)**: 30 minutes
- **Total**: 3-6 hours

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Data loss during migration | High | Full backup before starting; validation script |
| Application downtime | Medium | Schedule during low-traffic hours; have rollback ready |
| Performance issues | Low | Monitor queries; add indexes as needed |
| Schema incompatibility | Medium | Test migration on staging first |
