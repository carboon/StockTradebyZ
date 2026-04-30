-- PostgreSQL Performance Indexes for StockTradebyZ
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
--
-- This script creates additional indexes to optimize query performance
-- after migrating from SQLite to PostgreSQL.
--
-- Usage:
--   psql -U stocktrade -d stocktrade -f scripts/create_postgres_indexes.sql
--

-- =====================================================
-- Watchlist Optimization
-- =====================================================

-- Composite index for active user watchlist queries
-- Query: db.query(Watchlist).filter(Watchlist.user_id == user.id, Watchlist.is_active == True)
DROP INDEX IF EXISTS idx_watchlist_user_active;
CREATE INDEX idx_watchlist_user_active ON watchlist(user_id, is_active) WHERE is_active = true;

-- Index for priority sorting
DROP INDEX IF EXISTS idx_watchlist_priority;
CREATE INDEX idx_watchlist_priority ON watchlist(user_id, priority DESC, added_at DESC);

-- =====================================================
-- Analysis Results Optimization
-- =====================================================

-- Composite index for date + code filtering
DROP INDEX IF EXISTS idx_analysis_results_date_code;
CREATE INDEX idx_analysis_results_date_code ON analysis_results(pick_date, code);

-- Index for verdict filtering (PASS/FAIL/WATCH)
DROP INDEX IF EXISTS idx_analysis_results_verdict;
CREATE INDEX idx_analysis_results_verdict ON analysis_results(pick_date, verdict) WHERE verdict IS NOT NULL;

-- Index for score-based queries
DROP INDEX IF EXISTS idx_analysis_results_score;
CREATE INDEX idx_analysis_results_score ON analysis_results(pick_date, total_score DESC) WHERE total_score IS NOT NULL;

-- =====================================================
-- Candidates Optimization
-- =====================================================

-- Composite index for date + code filtering
DROP INDEX IF EXISTS idx_candidates_date_code;
CREATE INDEX idx_candidates_date_code ON candidates(pick_date, code);

-- Index for strategy filtering
DROP INDEX IF EXISTS idx_candidates_strategy;
CREATE INDEX idx_candidates_strategy ON candidates(pick_date, strategy) WHERE strategy IS NOT NULL;

-- =====================================================
-- Daily B1 Checks Optimization
-- =====================================================

-- Composite index for code + date queries
DROP INDEX IF EXISTS idx_daily_b1_checks_code_date;
CREATE INDEX idx_daily_b1_checks_code_date ON daily_b1_checks(code, check_date DESC);

-- Index for b1_passed filtering
DROP INDEX IF EXISTS idx_daily_b1_checks_passed;
CREATE INDEX idx_daily_b1_checks_passed ON daily_b1_checks(code, check_date DESC) WHERE b1_passed = true;

-- =====================================================
-- Stock Daily Data Optimization
-- =====================================================

-- The unique constraint (uq_stock_daily_code_date) already provides an index
-- This additional index covers common query patterns

-- Index for latest date queries (used by get_latest_trade_date)
DROP INDEX IF EXISTS idx_stock_daily_latest;
CREATE INDEX idx_stock_daily_latest ON stock_daily(code, trade_date DESC);

-- =====================================================
-- Tasks Optimization
-- =====================================================

-- Composite index for active task queries
DROP INDEX IF EXISTS idx_tasks_status_type;
CREATE INDEX idx_tasks_status_type ON tasks(status, task_type, created_at DESC);

-- Index for running/pending tasks
DROP INDEX IF EXISTS idx_tasks_active;
CREATE INDEX idx_tasks_active ON tasks(task_type, status) WHERE status IN ('pending', 'running');

-- =====================================================
-- Task Logs Optimization
-- =====================================================

-- Composite index for task + time queries
DROP INDEX IF EXISTS idx_task_logs_task_time;
CREATE INDEX idx_task_logs_task_time ON task_logs(task_id, log_time DESC);

-- Index for log level filtering
DROP INDEX IF EXISTS idx_task_logs_level;
CREATE INDEX idx_task_logs_level ON task_logs(task_id, level) WHERE level IN ('error', 'warning');

-- =====================================================
-- Usage Logs Optimization
-- =====================================================

-- Composite index for user + date filtering (with partial index for recent data)
DROP INDEX IF EXISTS idx_usage_logs_user_date;
CREATE INDEX idx_usage_logs_user_date ON usage_logs(user_id, created_at DESC);

-- Partial index for recent logs (last 30 days) - keeps index small
DROP INDEX IF EXISTS idx_usage_logs_recent;
CREATE INDEX idx_usage_logs_recent ON usage_logs(user_id, created_at DESC)
WHERE created_at >= CURRENT_DATE - INTERVAL '30 days';

-- =====================================================
-- Audit Logs Optimization
-- =====================================================

-- Composite index for user + action queries
DROP INDEX IF EXISTS idx_audit_logs_user_date;
CREATE INDEX idx_audit_logs_user_date ON audit_logs(user_id, created_at DESC);

-- Index for action type filtering
DROP INDEX IF EXISTS idx_audit_logs_action;
CREATE INDEX idx_audit_logs_action ON audit_logs(action, created_at DESC) WHERE action IS NOT NULL;

-- =====================================================
-- Watchlist Analysis Optimization
-- =====================================================

-- Unique constraint already exists (uq_watchlist_analysis_watchlist_date)
-- This index covers date-sorted queries
DROP INDEX IF EXISTS idx_watchlist_analysis_date;
CREATE INDEX idx_watchlist_analysis_date ON watchlist_analysis(watchlist_id, analysis_date DESC);

-- =====================================================
-- Query Statistics and Monitoring
-- =====================================================

-- Enable query statistics (optional, for monitoring)
-- ALTER DATABASE stocktrade SET shared_preload_libraries = 'pg_stat_statements';

-- Create view for index usage monitoring
CREATE OR REPLACE VIEW index_usage_stats AS
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan as index_scans,
    idx_tup_read as tuples_read,
    idx_tup_fetch as tuples_fetched
FROM pg_stat_user_indexes
ORDER BY idx_scan ASC;

-- =====================================================
-- Vacuum and Analyze
-- =====================================================

-- Update table statistics for query planner
ANALYZE configs;
ANALYZE stocks;
ANALYZE users;
ANALYZE api_keys;
ANALYZE candidates;
ANALYZE analysis_results;
ANALYZE daily_b1_checks;
ANALYZE watchlist;
ANALYZE watchlist_analysis;
ANALYZE tasks;
ANALYZE task_logs;
ANALYZE data_update_log;
ANALYZE usage_logs;
ANALYZE audit_logs;
ANALYZE stock_daily;

-- =====================================================
-- Verification Queries
-- =====================================================

-- Show all indexes created
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
    AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;

-- Show index sizes
SELECT
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexrelid)) as size
FROM pg_stat_user_indexes
WHERE indexname LIKE 'idx_%'
ORDER BY pg_relation_size(indexrelid) DESC;

-- Display completion message
SELECT 'PostgreSQL indexes created successfully!' as status;
