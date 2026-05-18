CREATE TABLE IF NOT EXISTS sector_analysis_runs (
    id SERIAL PRIMARY KEY,
    pick_date DATE NOT NULL,
    sector_key VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    analysis_count INTEGER NOT NULL DEFAULT 0,
    trend_start_count INTEGER NOT NULL DEFAULT 0,
    b1_count INTEGER NOT NULL DEFAULT 0,
    reviewer VARCHAR(20),
    source VARCHAR(32),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sector_analysis_runs_pick_date_sector UNIQUE (pick_date, sector_key)
);

CREATE INDEX IF NOT EXISTS ix_sector_analysis_runs_status_pick_date
    ON sector_analysis_runs (status, pick_date);

CREATE INDEX IF NOT EXISTS ix_sector_analysis_runs_pick_date_sector
    ON sector_analysis_runs (pick_date, sector_key);

CREATE TABLE IF NOT EXISTS sector_analysis_candidates (
    id SERIAL PRIMARY KEY,
    pick_date DATE NOT NULL,
    sector_key VARCHAR(64) NOT NULL,
    code VARCHAR(10) NOT NULL REFERENCES stocks(code),
    sector_names_json JSONB,
    board_group VARCHAR(20),
    open_price DOUBLE PRECISION,
    close_price DOUBLE PRECISION,
    change_pct DOUBLE PRECISION,
    turnover DOUBLE PRECISION,
    turnover_rate DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    b1_passed BOOLEAN,
    kdj_j DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sector_analysis_candidates_pick_date_sector_code UNIQUE (pick_date, sector_key, code)
);

CREATE INDEX IF NOT EXISTS ix_sector_analysis_candidates_pick_date_sector
    ON sector_analysis_candidates (pick_date, sector_key);

CREATE INDEX IF NOT EXISTS ix_sector_analysis_candidates_pick_date_code
    ON sector_analysis_candidates (pick_date, code);

CREATE TABLE IF NOT EXISTS sector_analysis_results (
    id SERIAL PRIMARY KEY,
    pick_date DATE NOT NULL,
    sector_key VARCHAR(64) NOT NULL,
    code VARCHAR(10) NOT NULL REFERENCES stocks(code),
    reviewer VARCHAR(20),
    b1_passed BOOLEAN,
    verdict VARCHAR(10),
    total_score DOUBLE PRECISION,
    signal_type VARCHAR(30),
    comment TEXT,
    turnover_rate DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sector_analysis_results_pick_date_sector_code_reviewer UNIQUE (pick_date, sector_key, code, reviewer)
);

CREATE INDEX IF NOT EXISTS ix_sector_analysis_results_pick_date_sector
    ON sector_analysis_results (pick_date, sector_key);

CREATE INDEX IF NOT EXISTS ix_sector_analysis_results_pick_date_code
    ON sector_analysis_results (pick_date, code);

CREATE INDEX IF NOT EXISTS ix_sector_analysis_results_pick_date_signal_type
    ON sector_analysis_results (pick_date, signal_type);
