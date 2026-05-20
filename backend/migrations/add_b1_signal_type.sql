-- 添加 b1_signal_type 字段到 daily_b1_checks 表
-- 执行日期: 2026-05-20

-- 添加列
ALTER TABLE daily_b1_checks
ADD COLUMN b1_signal_type VARCHAR(20);

-- 创建索引
CREATE INDEX ix_daily_b1_checks_signal_type
ON daily_b1_checks (b1_signal_type);

-- 说明
-- b1_signal_type 可能的值:
-- - 'old_b1': 原有B1Selector通过的信号
-- - '原始B1': newB1 Signal 3 (白线>黄线+接近黄线+超卖)
-- - '回踩黄线B': newB1 Signal 7 (中期趋势回踩黄线)
-- - '回踩超级B': newB1 Signal 6 (超牛股回踩)
-- - NULL: 未通过B1检查
