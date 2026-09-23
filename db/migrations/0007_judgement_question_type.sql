INSERT OR IGNORE INTO question_type(question_type_id, code, name, description)
VALUES (6, 'true_false', '判断题', '判断命题正误的题目');

INSERT INTO app_meta(key, value, updated_at)
VALUES ('schema_version', '7', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET
    value = excluded.value,
    updated_at = CURRENT_TIMESTAMP;
