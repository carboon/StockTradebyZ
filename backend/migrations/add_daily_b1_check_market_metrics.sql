-- Migration: Add market metrics columns to daily_b1_checks
-- Date: 2026-05-10
-- Description: Persist active-pool rank, turnover rate, and volume ratio for single-stock diagnosis history.

ALTER TABLE daily_b1_checks ADD COLUMN IF NOT EXISTS active_pool_rank INTEGER;
ALTER TABLE daily_b1_checks ADD COLUMN IF NOT EXISTS turnover_rate FLOAT;
ALTER TABLE daily_b1_checks ADD COLUMN IF NOT EXISTS volume_ratio FLOAT;
