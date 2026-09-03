ALTER TABLE topic ADD COLUMN problem_intro_tex TEXT NOT NULL DEFAULT '';
ALTER TABLE topic ADD COLUMN answer_intro_tex TEXT NOT NULL DEFAULT '';
ALTER TABLE topic ADD COLUMN export_note TEXT NOT NULL DEFAULT '';
ALTER TABLE topic ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}';

INSERT INTO app_meta(key, value, updated_at)
VALUES ('schema_version', '2', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET
    value = excluded.value,
    updated_at = CURRENT_TIMESTAMP;
