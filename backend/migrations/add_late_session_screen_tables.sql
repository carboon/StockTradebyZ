CREATE TABLE IF NOT EXISTS late_session_screen_runs (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    snapshot_time TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ready',
    message TEXT,
    total_count INTEGER NOT NULL DEFAULT 0,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    final_count INTEGER NOT NULL DEFAULT 0,
    funnel_json JSON,
    market_overview_json JSON,
    generated_by_user_id INTEGER REFERENCES users(id),
    force_generated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_late_session_screen_runs_trade_date UNIQUE (trade_date)
);

CREATE INDEX IF NOT EXISTS ix_late_session_screen_runs_trade_date
    ON late_session_screen_runs (trade_date);
CREATE INDEX IF NOT EXISTS ix_late_session_screen_runs_snapshot_time
    ON late_session_screen_runs (snapshot_time);
CREATE INDEX IF NOT EXISTS ix_late_session_screen_runs_status_trade_date
    ON late_session_screen_runs (status, trade_date);

CREATE TABLE IF NOT EXISTS late_session_screen_results (
    id SERIAL PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES late_session_screen_runs(id) ON DELETE CASCADE,
    trade_date DATE NOT NULL,
    code VARCHAR(10) NOT NULL REFERENCES stocks(code),
    name VARCHAR(50),
    industry VARCHAR(50),
    latest_price DOUBLE PRECISION,
    change_pct DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    turnover_rate DOUBLE PRECISION,
    circ_mv DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    amount DOUBLE PRECISION,
    final_score DOUBLE PRECISION,
    final_pass BOOLEAN NOT NULL DEFAULT FALSE,
    hard_pass BOOLEAN NOT NULL DEFAULT FALSE,
    reject_reason TEXT,
    volume_pattern VARCHAR(30),
    ma_pattern VARCHAR(30),
    intraday_pattern VARCHAR(30),
    hot_topics_json JSON,
    details_json JSON,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_late_session_screen_results_run_code UNIQUE (run_id, code)
);

CREATE INDEX IF NOT EXISTS ix_late_session_screen_results_run_id
    ON late_session_screen_results (run_id);
CREATE INDEX IF NOT EXISTS ix_late_session_screen_results_run_score
    ON late_session_screen_results (run_id, final_score);
CREATE INDEX IF NOT EXISTS ix_late_session_screen_results_trade_date_code
    ON late_session_screen_results (trade_date, code);
CREATE INDEX IF NOT EXISTS ix_late_session_screen_results_final_pass
    ON late_session_screen_results (final_pass);
CREATE INDEX IF NOT EXISTS ix_late_session_screen_results_hard_pass
    ON late_session_screen_results (hard_pass);
