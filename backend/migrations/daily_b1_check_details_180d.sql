BEGIN;

LOCK TABLE daily_b1_checks IN ACCESS EXCLUSIVE MODE;

WITH ranked_daily_b1_checks AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY code, check_date
            ORDER BY created_at DESC NULLS LAST, id DESC
        ) AS rn
    FROM daily_b1_checks
)
DELETE FROM daily_b1_checks
WHERE id IN (
    SELECT id
    FROM ranked_daily_b1_checks
    WHERE rn > 1
);

ALTER TABLE daily_b1_checks
    ADD CONSTRAINT uq_daily_b1_checks_code_check_date
    UNIQUE (code, check_date);

CREATE INDEX IF NOT EXISTS ix_daily_b1_checks_code_check_date
    ON daily_b1_checks (code, check_date);

CREATE INDEX IF NOT EXISTS ix_daily_b1_checks_check_date_code
    ON daily_b1_checks (check_date, code);

CREATE TABLE IF NOT EXISTS daily_b1_check_details (
    id SERIAL PRIMARY KEY,
    code VARCHAR(10) NOT NULL REFERENCES stocks(code),
    check_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ready',
    detail_version VARCHAR(32),
    strategy_version VARCHAR(32),
    rule_version VARCHAR(32),
    score_details_json JSONB,
    rules_json JSONB,
    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_daily_b1_check_details_code_check_date UNIQUE (code, check_date)
);

CREATE INDEX IF NOT EXISTS ix_daily_b1_check_details_code_check_date
    ON daily_b1_check_details (code, check_date);

CREATE INDEX IF NOT EXISTS ix_daily_b1_check_details_status_check_date
    ON daily_b1_check_details (status, check_date);

COMMIT;
