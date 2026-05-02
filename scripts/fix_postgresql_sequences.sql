-- PostgreSQL 数据一致性修复脚本
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
--
-- 目标：
-- 1. 校准各自增表 sequence
-- 2. 补齐 stock_daily 引用缺失的 stocks 主数据
-- 3. 输出可读的校验结果
--
-- 特点：
-- - 幂等
-- - 直接兼容 PostgreSQL
-- - 避免使用会与 RETURNS TABLE 字段重名的 PL/pgSQL 参数

\set ON_ERROR_STOP on

\echo '====================================================='
\echo 'Phase 1: 校准所有自增表序列'
\echo '====================================================='

SELECT setval('configs_id_seq', COALESCE((SELECT MAX(id) FROM configs), 1), true);
SELECT setval('users_id_seq', COALESCE((SELECT MAX(id) FROM users), 1), true);
SELECT setval('api_keys_id_seq', COALESCE((SELECT MAX(id) FROM api_keys), 1), true);
SELECT setval('candidates_id_seq', COALESCE((SELECT MAX(id) FROM candidates), 1), true);
SELECT setval('analysis_results_id_seq', COALESCE((SELECT MAX(id) FROM analysis_results), 1), true);
SELECT setval('daily_b1_checks_id_seq', COALESCE((SELECT MAX(id) FROM daily_b1_checks), 1), true);
SELECT setval('watchlist_id_seq', COALESCE((SELECT MAX(id) FROM watchlist), 1), true);
SELECT setval('watchlist_analysis_id_seq', COALESCE((SELECT MAX(id) FROM watchlist_analysis), 1), true);
SELECT setval('tasks_id_seq', COALESCE((SELECT MAX(id) FROM tasks), 1), true);
SELECT setval('task_logs_id_seq', COALESCE((SELECT MAX(id) FROM task_logs), 1), true);
SELECT setval('data_update_log_id_seq', COALESCE((SELECT MAX(id) FROM data_update_log), 1), true);
SELECT setval('usage_logs_id_seq', COALESCE((SELECT MAX(id) FROM usage_logs), 1), true);
SELECT setval('audit_logs_id_seq', COALESCE((SELECT MAX(id) FROM audit_logs), 1), true);
SELECT setval('stock_daily_id_seq', COALESCE((SELECT MAX(id) FROM stock_daily), 1), true);

\echo ''
\echo 'Sequence 校验摘要'
SELECT 'configs' AS table_name, MAX(id) AS max_id FROM configs
UNION ALL SELECT 'users', MAX(id) FROM users
UNION ALL SELECT 'api_keys', MAX(id) FROM api_keys
UNION ALL SELECT 'candidates', MAX(id) FROM candidates
UNION ALL SELECT 'analysis_results', MAX(id) FROM analysis_results
UNION ALL SELECT 'daily_b1_checks', MAX(id) FROM daily_b1_checks
UNION ALL SELECT 'watchlist', MAX(id) FROM watchlist
UNION ALL SELECT 'watchlist_analysis', MAX(id) FROM watchlist_analysis
UNION ALL SELECT 'tasks', MAX(id) FROM tasks
UNION ALL SELECT 'task_logs', MAX(id) FROM task_logs
UNION ALL SELECT 'data_update_log', MAX(id) FROM data_update_log
UNION ALL SELECT 'usage_logs', MAX(id) FROM usage_logs
UNION ALL SELECT 'audit_logs', MAX(id) FROM audit_logs
UNION ALL SELECT 'stock_daily', MAX(id) FROM stock_daily
ORDER BY table_name;

\echo ''
\echo '====================================================='
\echo 'Phase 2: 修复 stock_daily -> stocks 外键依赖'
\echo '====================================================='

INSERT INTO stocks (code, name, market, industry, created_at, updated_at)
SELECT DISTINCT
    sd.code,
    '未知股票' AS name,
    CASE
        WHEN substring(sd.code, 1, 1) IN ('6', '9') THEN 'SH'
        WHEN substring(sd.code, 1, 1) IN ('0', '2', '3') THEN 'SZ'
        ELSE 'UNKNOWN'
    END AS market,
    '未分类' AS industry,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM stock_daily sd
LEFT JOIN stocks s ON s.code = sd.code
WHERE s.code IS NULL
ON CONFLICT (code) DO NOTHING;

\echo ''
\echo '外键完整性校验'
SELECT COUNT(*) AS orphan_stock_daily
FROM stock_daily sd
LEFT JOIN stocks s ON s.code = sd.code
WHERE s.code IS NULL;

\echo ''
\echo '====================================================='
\echo 'Phase 3: 布尔字段状态校验'
\echo '====================================================='

SELECT 'users.is_active' AS field_name, pg_typeof(is_active) AS field_type, COUNT(*) AS row_count
FROM users
GROUP BY pg_typeof(is_active)
UNION ALL
SELECT 'watchlist.is_active', pg_typeof(is_active), COUNT(*)
FROM watchlist
GROUP BY pg_typeof(is_active)
UNION ALL
SELECT 'api_keys.is_active', pg_typeof(is_active), COUNT(*)
FROM api_keys
GROUP BY pg_typeof(is_active)
ORDER BY field_name;

\echo ''
\echo '====================================================='
\echo 'Phase 4: 最终关键状态'
\echo '====================================================='

SELECT
    (SELECT last_value FROM stock_daily_id_seq) AS stock_daily_seq,
    (SELECT MAX(id) FROM stock_daily) AS stock_daily_max_id,
    (SELECT COUNT(*) FROM stock_daily sd LEFT JOIN stocks s ON s.code = sd.code WHERE s.code IS NULL) AS stock_daily_orphans,
    (SELECT COUNT(*) FROM users WHERE is_active = true) AS active_users;
