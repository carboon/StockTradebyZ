-- Migration: Add StockAnalysis table for shared analysis results
-- Date: 2026-05-03
-- Description: Create a shared analysis results table that allows multiple users to reuse the same analysis

-- Create stock_analysis table
CREATE TABLE IF NOT EXISTS stock_analysis (
    id SERIAL PRIMARY KEY,
    code VARCHAR(10) NOT NULL REFERENCES stocks(code),
    trade_date DATE NOT NULL,
    analysis_type VARCHAR(20) NOT NULL DEFAULT 'daily_b1',
    strategy_version VARCHAR(10) NOT NULL DEFAULT 'v1',

    -- Public analysis result fields
    close_price FLOAT,
    verdict VARCHAR(10),  -- PASS/WATCH/FAIL
    score FLOAT,
    signal_type VARCHAR(30),  -- trend_start/distribution_risk
    b1_passed BOOLEAN,
    kdj_j FLOAT,
    zx_long_pos BOOLEAN,
    weekly_ma_aligned BOOLEAN,
    volume_healthy BOOLEAN,

    -- Detailed analysis data (JSON)
    details_json JSONB,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Unique constraint: one record per stock, trade date, analysis type, and strategy version
    CONSTRAINT uq_stock_analysis_unique UNIQUE(code, trade_date, analysis_type, strategy_version)
);

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_stock_analysis_lookup ON stock_analysis(code, trade_date);
CREATE INDEX IF NOT EXISTS idx_stock_analysis_date ON stock_analysis(trade_date);
CREATE INDEX IF NOT EXISTS idx_stock_analysis_code ON stock_analysis(code);

-- Add comment
COMMENT ON TABLE stock_analysis IS '公共分析结果表，存储股票分析结果供所有用户复用';
COMMENT ON COLUMN stock_analysis.code IS '股票代码';
COMMENT ON COLUMN stock_analysis.trade_date IS '交易日';
COMMENT ON COLUMN stock_analysis.analysis_type IS '分析类型 (daily_b1/brick)';
COMMENT ON COLUMN stock_analysis.strategy_version IS '策略版本';
COMMENT ON COLUMN stock_analysis.verdict IS '评审结论 (PASS/WATCH/FAIL)';
COMMENT ON COLUMN stock_analysis.score IS '量化评分';
COMMENT ON COLUMN stock_analysis.signal_type IS '信号类型 (trend_start/distribution_risk)';
