-- Persist daily active-pool ranks so online diagnosis never recomputes the full-market pool.

CREATE TABLE IF NOT EXISTS stock_active_pool_ranks (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    code VARCHAR(10) NOT NULL REFERENCES stocks(code),
    top_m INTEGER NOT NULL DEFAULT 2000,
    n_turnover_days INTEGER NOT NULL DEFAULT 43,
    turnover_n DOUBLE PRECISION NOT NULL,
    active_pool_rank INTEGER NOT NULL,
    in_active_pool BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_stock_active_pool_ranks_date_code_params
        UNIQUE (trade_date, code, top_m, n_turnover_days)
);

CREATE INDEX IF NOT EXISTS ix_stock_active_pool_ranks_date_rank
    ON stock_active_pool_ranks (trade_date, top_m, n_turnover_days, active_pool_rank);

CREATE INDEX IF NOT EXISTS ix_stock_active_pool_ranks_code_date
    ON stock_active_pool_ranks (code, trade_date);

CREATE INDEX IF NOT EXISTS ix_stock_active_pool_ranks_code_date_params
    ON stock_active_pool_ranks (code, trade_date, top_m, n_turnover_days);
