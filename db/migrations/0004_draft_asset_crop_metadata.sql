ALTER TABLE question_import_draft_asset ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}';

INSERT INTO app_meta(key, value, updated_at) VALUES ('schema_version', '4', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP;
