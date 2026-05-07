CREATE TABLE IF NOT EXISTS raw_data_batches (
    id SERIAL PRIMARY KEY,
    batch_type VARCHAR(32) NOT NULL DEFAULT 'daily',
    trade_date DATE NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    source VARCHAR(32) NULL,
    storage_path TEXT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    stock_count INTEGER NOT NULL DEFAULT 0,
    file_size_bytes INTEGER NULL,
    checksum VARCHAR(64) NULL,
    meta_json JSONB NULL,
    error_message TEXT NULL,
    started_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_raw_data_batches_status_trade_date
ON raw_data_batches(status, trade_date);

CREATE INDEX IF NOT EXISTS ix_raw_data_batches_batch_type_created_at
ON raw_data_batches(batch_type, created_at);

CREATE TABLE IF NOT EXISTS raw_data_manifest (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    source VARCHAR(32) NULL,
    batch_id INTEGER NULL REFERENCES raw_data_batches(id),
    storage_path TEXT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    stock_count INTEGER NOT NULL DEFAULT 0,
    db_record_count INTEGER NOT NULL DEFAULT 0,
    db_stock_count INTEGER NOT NULL DEFAULT 0,
    file_size_bytes INTEGER NULL,
    checksum VARCHAR(64) NULL,
    meta_json JSONB NULL,
    fetched_at TIMESTAMPTZ NULL,
    loaded_to_db_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE raw_data_manifest
    ADD CONSTRAINT uq_raw_data_manifest_trade_date UNIQUE (trade_date);

CREATE INDEX IF NOT EXISTS ix_raw_data_manifest_status_trade_date
ON raw_data_manifest(status, trade_date);
