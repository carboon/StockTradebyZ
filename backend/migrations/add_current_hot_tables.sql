-- Migration: add current hot tables
-- Date: 2026-05-09
-- Description: create current hot pool daily result tables and intraday snapshot table

CREATE TABLE IF NOT EXISTS current_hot_runs (
    id SERIAL PRIMARY KEY,
    pick_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    analysis_count INTEGER NOT NULL DEFAULT 0,
    trend_start_count INTEGER NOT NULL DEFAULT 0,
    consecutive_candidate_count INTEGER NOT NULL DEFAULT 0,
    reviewer VARCHAR(20),
    source VARCHAR(32),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_current_hot_runs_pick_date UNIQUE (pick_date)
);

CREATE INDEX IF NOT EXISTS ix_current_hot_runs_status_pick_date
    ON current_hot_runs (status, pick_date);

CREATE INDEX IF NOT EXISTS ix_current_hot_runs_finished_at
    ON current_hot_runs (finished_at);

CREATE TABLE IF NOT EXISTS current_hot_candidates (
    id SERIAL PRIMARY KEY,
    pick_date DATE NOT NULL,
    code VARCHAR(10) NOT NULL REFERENCES stocks(code),
    sector_names_json JSONB,
    board_group VARCHAR(20),
    open_price FLOAT,
    close_price FLOAT,
    change_pct FLOAT,
    turnover FLOAT,
    b1_passed BOOLEAN,
    kdj_j FLOAT,
    consecutive_days INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_current_hot_candidates_pick_date_code UNIQUE (pick_date, code)
);

CREATE INDEX IF NOT EXISTS ix_current_hot_candidates_pick_date_code
    ON current_hot_candidates (pick_date, code);

CREATE INDEX IF NOT EXISTS ix_current_hot_candidates_pick_date_board
    ON current_hot_candidates (pick_date, board_group);

CREATE TABLE IF NOT EXISTS current_hot_analysis_results (
    id SERIAL PRIMARY KEY,
    pick_date DATE NOT NULL,
    code VARCHAR(10) NOT NULL REFERENCES stocks(code),
    reviewer VARCHAR(20),
    b1_passed BOOLEAN,
    verdict VARCHAR(10),
    total_score FLOAT,
    signal_type VARCHAR(30),
    comment TEXT,
    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_current_hot_analysis_results_pick_date_code_reviewer UNIQUE (pick_date, code, reviewer)
);

CREATE INDEX IF NOT EXISTS ix_current_hot_analysis_results_pick_date_code
    ON current_hot_analysis_results (pick_date, code);

CREATE INDEX IF NOT EXISTS ix_current_hot_analysis_results_pick_date_signal_type
    ON current_hot_analysis_results (pick_date, signal_type);

CREATE TABLE IF NOT EXISTS current_hot_intraday_snapshots (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    code VARCHAR(10) NOT NULL REFERENCES stocks(code),
    source_pick_date DATE NOT NULL,
    snapshot_time TIMESTAMPTZ NOT NULL,
    sector_names_json JSONB,
    board_group VARCHAR(20),
    open_price FLOAT,
    close_price FLOAT,
    high_price FLOAT,
    low_price FLOAT,
    volume FLOAT,
    amount FLOAT,
    change_pct FLOAT,
    turnover FLOAT,
    b1_passed BOOLEAN,
    score FLOAT,
    verdict VARCHAR(10),
    signal_type VARCHAR(30),
    kdj_j FLOAT,
    zx_long_pos BOOLEAN,
    weekly_ma_aligned BOOLEAN,
    volume_healthy BOOLEAN,
    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_current_hot_intraday_snapshots_trade_date_code UNIQUE (trade_date, code)
);

CREATE INDEX IF NOT EXISTS ix_current_hot_intraday_snapshots_trade_date_code
    ON current_hot_intraday_snapshots (trade_date, code);

CREATE INDEX IF NOT EXISTS ix_current_hot_intraday_snapshots_board_group
    ON current_hot_intraday_snapshots (trade_date, board_group);
