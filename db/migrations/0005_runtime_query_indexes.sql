CREATE INDEX IF NOT EXISTS idx_legacy_question_filters
    ON legacy_question_map(detected_year, detected_chapter, detected_source, detected_question_number);

CREATE INDEX IF NOT EXISTS idx_question_knowledge_area_question
    ON question_knowledge_area(question_id, knowledge_area_id);

CREATE INDEX IF NOT EXISTS idx_paper_question_paper_order
    ON paper_question(paper_id, display_order, question_number, sub_number);

CREATE INDEX IF NOT EXISTS idx_draft_batch_status_updated
    ON question_import_draft(batch_id, review_status, updated_at);

INSERT INTO app_meta(key, value, updated_at) VALUES ('schema_version', '5', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
