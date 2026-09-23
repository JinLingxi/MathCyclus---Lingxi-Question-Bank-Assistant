CREATE VIRTUAL TABLE IF NOT EXISTS question_search USING fts5(
    question_id UNINDEXED,
    search_text,
    tokenize = 'trigram'
);

CREATE TRIGGER IF NOT EXISTS question_search_question_ai
AFTER INSERT ON question
BEGIN
    INSERT INTO question_search(question_id, search_text)
    SELECT NEW.question_id,
        trim(
            coalesce(NEW.question_id, '') || ' ' ||
            coalesce(NEW.legacy_id, '') || ' ' ||
            coalesce(NEW.stem_tex, '') || ' ' ||
            coalesce(NEW.choices_json, '') || ' ' ||
            coalesce(NEW.answer_tex, '') || ' ' ||
            coalesce(NEW.solution_tex, '') || ' ' ||
            coalesce(NEW.tags_json, '') || ' ' ||
            coalesce(NEW.note, '') || ' ' ||
            coalesce(NEW.canonical_tex, '') || ' ' ||
            coalesce(NEW.raw_source_tex, '')
        );
END;

CREATE TRIGGER IF NOT EXISTS question_search_question_au
AFTER UPDATE ON question
BEGIN
    DELETE FROM question_search WHERE question_id = NEW.question_id;
    INSERT INTO question_search(question_id, search_text)
    SELECT NEW.question_id,
        trim(
            coalesce(NEW.question_id, '') || ' ' ||
            coalesce(NEW.legacy_id, '') || ' ' ||
            coalesce(NEW.stem_tex, '') || ' ' ||
            coalesce(NEW.choices_json, '') || ' ' ||
            coalesce(NEW.answer_tex, '') || ' ' ||
            coalesce(NEW.solution_tex, '') || ' ' ||
            coalesce(NEW.tags_json, '') || ' ' ||
            coalesce(NEW.note, '') || ' ' ||
            coalesce(NEW.canonical_tex, '') || ' ' ||
            coalesce(NEW.raw_source_tex, '')
        );
END;

CREATE TRIGGER IF NOT EXISTS question_search_question_ad
AFTER DELETE ON question
BEGIN
    DELETE FROM question_search WHERE question_id = OLD.question_id;
END;

CREATE TRIGGER IF NOT EXISTS question_search_legacy_ai
AFTER INSERT ON legacy_question_map
BEGIN
    DELETE FROM question_search WHERE question_id = NEW.question_id;
    INSERT INTO question_search(question_id, search_text)
    SELECT q.question_id, trim(
        coalesce(q.question_id, '') || ' ' || coalesce(q.legacy_id, '') || ' ' ||
        coalesce(q.stem_tex, '') || ' ' || coalesce(q.choices_json, '') || ' ' ||
        coalesce(q.answer_tex, '') || ' ' || coalesce(q.solution_tex, '') || ' ' ||
        coalesce(q.tags_json, '') || ' ' || coalesce(q.note, '') || ' ' ||
        coalesce(q.canonical_tex, '') || ' ' || coalesce(q.raw_source_tex, '') || ' ' ||
        coalesce(NEW.legacy_file_path, '') || ' ' || coalesce(NEW.detected_chapter, '') || ' ' ||
        coalesce(NEW.detected_year, '') || ' ' || coalesce(NEW.detected_source, '') || ' ' ||
        coalesce(NEW.detected_question_number, '') || ' ' || coalesce(NEW.detected_topic, '')
    ) FROM question q WHERE q.question_id = NEW.question_id;
END;

CREATE TRIGGER IF NOT EXISTS question_search_legacy_au
AFTER UPDATE ON legacy_question_map
BEGIN
    DELETE FROM question_search WHERE question_id = NEW.question_id;
    INSERT INTO question_search(question_id, search_text)
    SELECT q.question_id, trim(
        coalesce(q.question_id, '') || ' ' || coalesce(q.legacy_id, '') || ' ' ||
        coalesce(q.stem_tex, '') || ' ' || coalesce(q.choices_json, '') || ' ' ||
        coalesce(q.answer_tex, '') || ' ' || coalesce(q.solution_tex, '') || ' ' ||
        coalesce(q.tags_json, '') || ' ' || coalesce(q.note, '') || ' ' ||
        coalesce(q.canonical_tex, '') || ' ' || coalesce(q.raw_source_tex, '') || ' ' ||
        coalesce(NEW.legacy_file_path, '') || ' ' || coalesce(NEW.detected_chapter, '') || ' ' ||
        coalesce(NEW.detected_year, '') || ' ' || coalesce(NEW.detected_source, '') || ' ' ||
        coalesce(NEW.detected_question_number, '') || ' ' || coalesce(NEW.detected_topic, '')
    ) FROM question q WHERE q.question_id = NEW.question_id;
END;

CREATE TRIGGER IF NOT EXISTS question_search_legacy_ad
AFTER DELETE ON legacy_question_map
BEGIN
    DELETE FROM question_search WHERE question_id = OLD.question_id;
END;

INSERT INTO question_search(question_id, search_text)
SELECT q.question_id, trim(
    coalesce(q.question_id, '') || ' ' || coalesce(q.legacy_id, '') || ' ' ||
    coalesce(q.stem_tex, '') || ' ' || coalesce(q.choices_json, '') || ' ' ||
    coalesce(q.answer_tex, '') || ' ' || coalesce(q.solution_tex, '') || ' ' ||
    coalesce(q.tags_json, '') || ' ' || coalesce(q.note, '') || ' ' ||
    coalesce(q.canonical_tex, '') || ' ' || coalesce(q.raw_source_tex, '') || ' ' ||
    coalesce(l.legacy_file_path, '') || ' ' || coalesce(l.detected_chapter, '') || ' ' ||
    coalesce(l.detected_year, '') || ' ' || coalesce(l.detected_source, '') || ' ' ||
    coalesce(l.detected_question_number, '') || ' ' || coalesce(l.detected_topic, '')
)
FROM question q LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
WHERE NOT EXISTS (SELECT 1 FROM question_search s WHERE s.question_id = q.question_id);

INSERT INTO app_meta(key, value, updated_at) VALUES ('schema_version', '6', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
