CREATE TABLE IF NOT EXISTS assets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id      TEXT    NOT NULL UNIQUE,
    asset_class   TEXT    NOT NULL DEFAULT 'scout_quadcopter',
    grpc_host     TEXT    NOT NULL,
    grpc_port     INTEGER NOT NULL,
    registered_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_assets_registered_at ON assets(registered_at DESC);

CREATE TABLE IF NOT EXISTS mission_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id   TEXT NOT NULL,
    command    TEXT NOT NULL,
    params     TEXT,
    result     TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_mission_logs_asset_id_created_at
    ON mission_logs(asset_id, created_at DESC);

CREATE TABLE IF NOT EXISTS licenses (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    license_key   TEXT    NOT NULL UNIQUE,
    org_name      TEXT    NOT NULL,
    expiry_date   TEXT    NOT NULL,
    seat_count    INTEGER NOT NULL DEFAULT 1,
    activated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    is_active     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_licenses_is_active_id ON licenses(is_active, id DESC);

CREATE TABLE IF NOT EXISTS simulation (
    id                TEXT PRIMARY KEY,
    scanned_buildings TEXT NOT NULL DEFAULT '[]',
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_simulation_updated_at ON simulation(updated_at);

CREATE TABLE IF NOT EXISTS mission_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id       TEXT,
    asset_id            TEXT NOT NULL,
    prompt              TEXT NOT NULL,
    status              TEXT NOT NULL,
    started_at          TEXT,
    ended_at            TEXT,
    duration_ms         INTEGER,
    ttft_ms             INTEGER,
    tool_call_count     INTEGER DEFAULT 0,
    survivors_detected  INTEGER DEFAULT 0,
    survivors_rescued   INTEGER DEFAULT 0,
    result_summary      TEXT,
    error_message       TEXT,
    langfuse_trace_id   TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_mission_runs_created_at ON mission_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mission_runs_simulation  ON mission_runs(simulation_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mission_runs_status      ON mission_runs(status);
CREATE INDEX IF NOT EXISTS idx_mission_runs_langfuse    ON mission_runs(langfuse_trace_id);

CREATE TABLE IF NOT EXISTS mission_run_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    ts          TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (run_id) REFERENCES mission_runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mission_run_events_run_seq
    ON mission_run_events(run_id, seq);
