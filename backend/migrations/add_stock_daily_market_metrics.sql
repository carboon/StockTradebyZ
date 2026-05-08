-- Migration: Add market metrics columns to stock_daily
-- Date: 2026-05-09
-- Description: Persist turnover, volume ratio, and moneyflow metrics alongside OHLCV.

ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS turnover_rate FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS turnover_rate_f FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS volume_ratio FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS free_share FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS circ_mv FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS buy_sm_amount FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS sell_sm_amount FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS buy_md_amount FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS sell_md_amount FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS buy_lg_amount FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS sell_lg_amount FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS buy_elg_amount FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS sell_elg_amount FLOAT;
ALTER TABLE stock_daily ADD COLUMN IF NOT EXISTS net_mf_amount FLOAT;
