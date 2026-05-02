-- PostgreSQL 序列修复脚本（简化版）
-- 修复 stock_daily, tasks, users 等表的序列未对齐问题

\echo '====================================================='
\echo '修复序列对齐问题 (Sequence Alignment Fix)'
\echo '====================================================='

-- 1. 修复 stock_daily 序列（最严重）
\echo ''
\echo '1. 修复 stock_daily 序列...'
SELECT setval('stock_daily_id_seq', (SELECT COALESCE(MAX(id), 1) FROM stock_daily), true);

-- 2. 修复 tasks 序列
\echo '2. 修复 tasks 序列...'
SELECT setval('tasks_id_seq', (SELECT COALESCE(MAX(id), 1) FROM tasks), true);

-- 3. 修复 users 序列
\echo '3. 修复 users 序列...'
SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id), 1) FROM users), true);

-- 4. 修复 api_keys 序列
\echo '4. 修复 api_keys 序列...'
SELECT setval('api_keys_id_seq', (SELECT COALESCE(MAX(id), 1) FROM api_keys), true);

-- 5. 修复 candidates 序列
\echo '5. 修复 candidates 序列...'
SELECT setval('candidates_id_seq', (SELECT COALESCE(MAX(id), 1) FROM candidates), true);

-- 6. 修复 analysis_results 序列
\echo '6. 修复 analysis_results 序列...'
SELECT setval('analysis_results_id_seq', (SELECT COALESCE(MAX(id), 1) FROM analysis_results), true);

-- 7. 修复 daily_b1_checks 序列
\echo '7. 修复 daily_b1_checks 序列...'
SELECT setval('daily_b1_checks_id_seq', (SELECT COALESCE(MAX(id), 1) FROM daily_b1_checks), true);

-- 8. 修复 task_logs 序列
\echo '8. 修复 task_logs 序列...'
SELECT setval('task_logs_id_seq', (SELECT COALESCE(MAX(id), 1) FROM task_logs), true);

-- 9. 修复 data_update_log 序列
\echo '9. 修复 data_update_log 序列...'
SELECT setval('data_update_log_id_seq', (SELECT COALESCE(MAX(id), 1) FROM data_update_log), true);

-- 10. 修复 audit_logs 序列
\echo '10. 修复 audit_logs 序列...'
SELECT setval('audit_logs_id_seq', (SELECT COALESCE(MAX(id), 1) FROM audit_logs), true);

\echo ''
\echo '====================================================='
\echo '验证修复结果 (Verification)'
\echo '====================================================='

\echo ''
\echo '所有自增表序列状态：'
SELECT
    'stock_daily' as table_name,
    (SELECT last_value FROM stock_daily_id_seq) as seq_value,
    (SELECT COALESCE(MAX(id), 0) FROM stock_daily) as max_id,
    CASE
        WHEN (SELECT last_value FROM stock_daily_id_seq) >= (SELECT COALESCE(MAX(id), 0) FROM stock_daily)
        THEN 'OK'
        ELSE 'MISALIGNED'
    END as status
UNION ALL
SELECT
    'tasks',
    (SELECT last_value FROM tasks_id_seq),
    (SELECT COALESCE(MAX(id), 0) FROM tasks),
    CASE
        WHEN (SELECT last_value FROM tasks_id_seq) >= (SELECT COALESCE(MAX(id), 0) FROM tasks)
        THEN 'OK'
        ELSE 'MISALIGNED'
    END
UNION ALL
SELECT
    'users',
    (SELECT last_value FROM users_id_seq),
    (SELECT COALESCE(MAX(id), 0) FROM users),
    CASE
        WHEN (SELECT last_value FROM users_id_seq) >= (SELECT COALESCE(MAX(id), 0) FROM users)
        THEN 'OK'
        ELSE 'MISALIGNED'
    END
UNION ALL
SELECT
    'api_keys',
    (SELECT last_value FROM api_keys_id_seq),
    (SELECT COALESCE(MAX(id), 0) FROM api_keys),
    CASE
        WHEN (SELECT last_value FROM api_keys_id_seq) >= (SELECT COALESCE(MAX(id), 0) FROM api_keys)
        THEN 'OK'
        ELSE 'MISALIGNED'
    END
ORDER BY table_name;

\echo ''
\echo '====================================================='
\echo '修复完成！(Fix Complete)'
\echo '====================================================='
