CREATE TABLE IF NOT EXISTS simulation (
    id TEXT PRIMARY KEY,
    scanned_buildings JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_simulation_updated_at ON simulation(updated_at);