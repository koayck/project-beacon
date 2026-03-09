-- Registered drone assets (uplinked to commander)
CREATE TABLE IF NOT EXISTS assets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id     TEXT    UNIQUE NOT NULL,
    asset_class  TEXT    NOT NULL DEFAULT 'scout_quadcopter',
    grpc_host    TEXT    NOT NULL,
    grpc_port    INTEGER NOT NULL,
    registered_at TEXT   NOT NULL DEFAULT (datetime('now'))
);

-- Mission command log
CREATE TABLE IF NOT EXISTS mission_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id   TEXT NOT NULL,
    command    TEXT NOT NULL,
    params     TEXT,
    result     TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- License keys (pre-provisioned, offline validation)
CREATE TABLE IF NOT EXISTS licenses (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    license_key  TEXT    UNIQUE NOT NULL,
    org_name     TEXT    NOT NULL,
    expiry_date  TEXT    NOT NULL,  -- ISO 8601 date
    seat_count   INTEGER NOT NULL DEFAULT 1,
    activated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    is_active    INTEGER NOT NULL DEFAULT 1
);
