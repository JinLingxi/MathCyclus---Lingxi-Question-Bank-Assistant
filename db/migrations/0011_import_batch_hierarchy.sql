ALTER TABLE import_batch ADD COLUMN task_id TEXT NOT NULL DEFAULT '';
ALTER TABLE import_batch ADD COLUMN parent_batch_id TEXT REFERENCES import_batch(batch_id) ON DELETE CASCADE;
ALTER TABLE import_batch ADD COLUMN hierarchy_level INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_batch ADD COLUMN subset_key TEXT NOT NULL DEFAULT '';
ALTER TABLE import_batch ADD COLUMN subset_label TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_import_batch_task
    ON import_batch(task_id, hierarchy_level, started_at);
CREATE INDEX IF NOT EXISTS idx_import_batch_parent
    ON import_batch(parent_batch_id, started_at);
