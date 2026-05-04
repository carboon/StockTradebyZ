BEGIN;

LOCK TABLE candidates IN ACCESS EXCLUSIVE MODE;
LOCK TABLE analysis_results IN ACCESS EXCLUSIVE MODE;

WITH ranked_candidates AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY pick_date, code
            ORDER BY created_at DESC NULLS LAST, id DESC
        ) AS rn
    FROM candidates
)
DELETE FROM candidates
WHERE id IN (
    SELECT id
    FROM ranked_candidates
    WHERE rn > 1
);

WITH ranked_analysis_results AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY pick_date, code, reviewer
            ORDER BY created_at DESC NULLS LAST, id DESC
        ) AS rn
    FROM analysis_results
)
DELETE FROM analysis_results
WHERE id IN (
    SELECT id
    FROM ranked_analysis_results
    WHERE rn > 1
);

ALTER TABLE candidates
    ADD CONSTRAINT uq_candidates_pick_date_code
    UNIQUE (pick_date, code);

CREATE INDEX IF NOT EXISTS ix_candidates_pick_date_code
    ON candidates (pick_date, code);

CREATE INDEX IF NOT EXISTS ix_candidates_pick_date_id
    ON candidates (pick_date, id);

ALTER TABLE analysis_results
    ADD CONSTRAINT uq_analysis_results_pick_date_code_reviewer
    UNIQUE (pick_date, code, reviewer);

CREATE INDEX IF NOT EXISTS ix_analysis_results_pick_date_code
    ON analysis_results (pick_date, code);

CREATE INDEX IF NOT EXISTS ix_analysis_results_pick_date_signal_type
    ON analysis_results (pick_date, signal_type);

CREATE INDEX IF NOT EXISTS ix_analysis_results_pick_date_reviewer
    ON analysis_results (pick_date, reviewer);

CREATE TABLE IF NOT EXISTS tomorrow_star_runs (
    id SERIAL PRIMARY KEY,
    pick_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    analysis_count INTEGER NOT NULL DEFAULT 0,
    trend_start_count INTEGER NOT NULL DEFAULT 0,
    reviewer VARCHAR(20),
    strategy_version VARCHAR(32),
    window_size INTEGER NOT NULL DEFAULT 180,
    source VARCHAR(32),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tomorrow_star_runs_pick_date UNIQUE (pick_date)
);

CREATE INDEX IF NOT EXISTS ix_tomorrow_star_runs_status_pick_date
    ON tomorrow_star_runs (status, pick_date);

CREATE INDEX IF NOT EXISTS ix_tomorrow_star_runs_finished_at
    ON tomorrow_star_runs (finished_at);

COMMIT;
