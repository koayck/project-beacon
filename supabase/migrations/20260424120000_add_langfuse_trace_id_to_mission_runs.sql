ALTER TABLE mission_runs ADD COLUMN IF NOT EXISTS langfuse_trace_id TEXT;
CREATE INDEX IF NOT EXISTS idx_mission_runs_langfuse_trace_id ON mission_runs (langfuse_trace_id);
