PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL DEFAULT '',
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS question_type (
    question_type_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS question (
    question_id TEXT PRIMARY KEY,
    question_type_id INTEGER REFERENCES question_type(question_type_id),
    stem_tex TEXT NOT NULL DEFAULT '',
    choices_json TEXT NOT NULL DEFAULT '[]',
    answer_tex TEXT NOT NULL DEFAULT '',
    solution_tex TEXT NOT NULL DEFAULT '',
    difficulty INTEGER,
    tags_json TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    official_flag INTEGER NOT NULL DEFAULT 0,
    canonical_tex TEXT NOT NULL DEFAULT '',
    raw_source_tex TEXT NOT NULL DEFAULT '',
    normalized_status TEXT NOT NULL DEFAULT 'raw',
    legacy_id TEXT,
    legacy_file_path TEXT,
    usage_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_manual_edit_at TEXT
);

CREATE TABLE IF NOT EXISTS question_analysis (
    question_id TEXT PRIMARY KEY REFERENCES question(question_id) ON DELETE CASCADE,
    target_tex TEXT NOT NULL DEFAULT '',
    production_tex TEXT NOT NULL DEFAULT '',
    evaluation_tex TEXT NOT NULL DEFAULT '',
    marking_data_tex TEXT NOT NULL DEFAULT '',
    warning_tex TEXT NOT NULL DEFAULT '',
    reference_text TEXT NOT NULL DEFAULT '',
    extra_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS knowledge_area (
    knowledge_area_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    parent_id TEXT REFERENCES knowledge_area(knowledge_area_id) ON DELETE SET NULL,
    description TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS question_knowledge_area (
    question_id TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    knowledge_area_id TEXT NOT NULL REFERENCES knowledge_area(knowledge_area_id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'migration',
    confidence REAL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(question_id, knowledge_area_id)
);

CREATE TABLE IF NOT EXISTS question_equivalence (
    equivalence_id TEXT PRIMARY KEY,
    question_id_a TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    question_id_b TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'same_stem',
    confidence REAL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(question_id_a, question_id_b, relation_type),
    CHECK(question_id_a != question_id_b)
);

CREATE TABLE IF NOT EXISTS paper (
    paper_id TEXT PRIMARY KEY,
    year INTEGER,
    paper_series TEXT NOT NULL DEFAULT '',
    track TEXT NOT NULL DEFAULT '',
    paper_name TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(year, paper_series, track, paper_name)
);

CREATE TABLE IF NOT EXISTS paper_question (
    paper_question_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES paper(paper_id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    question_number TEXT NOT NULL DEFAULT '',
    sub_number TEXT NOT NULL DEFAULT '',
    display_order INTEGER NOT NULL DEFAULT 0,
    origin_tex TEXT NOT NULL DEFAULT '',
    location_tex TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_id, question_id, question_number, sub_number)
);

CREATE TABLE IF NOT EXISTS book (
    book_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL DEFAULT '',
    edition TEXT NOT NULL DEFAULT '',
    grade TEXT NOT NULL DEFAULT '',
    volume TEXT NOT NULL DEFAULT '',
    curriculum_version TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS book_section (
    section_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES book(book_id) ON DELETE CASCADE,
    parent_section_id TEXT REFERENCES book_section(section_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    section_level INTEGER NOT NULL DEFAULT 1,
    page_start INTEGER,
    page_end INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS book_exercise_question (
    book_exercise_question_id TEXT PRIMARY KEY,
    book_id TEXT NOT NULL REFERENCES book(book_id) ON DELETE CASCADE,
    section_id TEXT REFERENCES book_section(section_id) ON DELETE SET NULL,
    question_id TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    page_number INTEGER,
    column_name TEXT NOT NULL DEFAULT '',
    exercise_number TEXT NOT NULL DEFAULT '',
    sub_number TEXT NOT NULL DEFAULT '',
    display_order INTEGER NOT NULL DEFAULT 0,
    source_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS topic_module (
    module_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS topic (
    topic_id TEXT PRIMARY KEY,
    module_id TEXT REFERENCES topic_module(module_id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    file_name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(module_id, name)
);

CREATE TABLE IF NOT EXISTS topic_question (
    topic_question_id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topic(topic_id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    group_name TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    topic_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(topic_id, question_id, group_name)
);

CREATE TABLE IF NOT EXISTS question_asset (
    asset_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    file_path TEXT NOT NULL,
    original_file_name TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    width INTEGER,
    height INTEGER,
    file_hash TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS question_revision (
    revision_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES question(question_id) ON DELETE CASCADE,
    change_source TEXT NOT NULL,
    changed_fields_json TEXT NOT NULL DEFAULT '[]',
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    operator TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_batch (
    batch_id TEXT PRIMARY KEY,
    import_type TEXT NOT NULL,
    source_path TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'dry_run',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    summary TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS question_import_draft (
    draft_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES import_batch(batch_id) ON DELETE CASCADE,
    source_item_id TEXT NOT NULL DEFAULT '',
    source_label TEXT NOT NULL DEFAULT '',
    proposed_action TEXT NOT NULL DEFAULT 'insert',
    target_question_id TEXT REFERENCES question(question_id) ON DELETE SET NULL,
    review_status TEXT NOT NULL DEFAULT 'needs_review',
    review_reason TEXT NOT NULL DEFAULT '',
    question_type_id INTEGER REFERENCES question_type(question_type_id),
    stem_tex TEXT NOT NULL DEFAULT '',
    choices_json TEXT NOT NULL DEFAULT '[]',
    answer_tex TEXT NOT NULL DEFAULT '',
    solution_tex TEXT NOT NULL DEFAULT '',
    difficulty INTEGER,
    tags_json TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    official_flag INTEGER NOT NULL DEFAULT 0,
    raw_source_text TEXT NOT NULL DEFAULT '',
    normalized_tex TEXT NOT NULL DEFAULT '',
    confidence_json TEXT NOT NULL DEFAULT '{}',
    validation_json TEXT NOT NULL DEFAULT '{}',
    extra_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS question_import_draft_asset (
    draft_asset_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL REFERENCES question_import_draft(draft_id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'problem',
    source_path TEXT NOT NULL DEFAULT '',
    planned_file_path TEXT NOT NULL DEFAULT '',
    original_file_name TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT '',
    file_hash TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'needs_review',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_report_item (
    item_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES import_batch(batch_id) ON DELETE CASCADE,
    source_file TEXT NOT NULL DEFAULT '',
    question_id TEXT REFERENCES question(question_id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS legacy_question_map (
    question_id TEXT PRIMARY KEY REFERENCES question(question_id) ON DELETE CASCADE,
    legacy_id TEXT,
    legacy_file_path TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL DEFAULT '',
    detected_chapter TEXT NOT NULL DEFAULT '',
    detected_year INTEGER,
    detected_source TEXT NOT NULL DEFAULT '',
    detected_question_number TEXT NOT NULL DEFAULT '',
    detected_topic TEXT NOT NULL DEFAULT '',
    scan_status TEXT NOT NULL DEFAULT 'pending',
    scan_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_question_legacy_id ON question(legacy_id);
CREATE INDEX IF NOT EXISTS idx_question_difficulty ON question(difficulty);
CREATE INDEX IF NOT EXISTS idx_question_updated_at ON question(updated_at);
CREATE INDEX IF NOT EXISTS idx_question_knowledge_area_area ON question_knowledge_area(knowledge_area_id);
CREATE INDEX IF NOT EXISTS idx_question_equivalence_a ON question_equivalence(question_id_a);
CREATE INDEX IF NOT EXISTS idx_question_equivalence_b ON question_equivalence(question_id_b);
CREATE INDEX IF NOT EXISTS idx_paper_year ON paper(year);
CREATE INDEX IF NOT EXISTS idx_paper_question_question ON paper_question(question_id);
CREATE INDEX IF NOT EXISTS idx_book_exercise_question ON book_exercise_question(question_id);
CREATE INDEX IF NOT EXISTS idx_topic_question_question ON topic_question(question_id);
CREATE INDEX IF NOT EXISTS idx_question_asset_question ON question_asset(question_id);
CREATE INDEX IF NOT EXISTS idx_question_revision_question ON question_revision(question_id);
CREATE INDEX IF NOT EXISTS idx_import_report_batch ON import_report_item(batch_id);
CREATE INDEX IF NOT EXISTS idx_question_import_draft_batch ON question_import_draft(batch_id);
CREATE INDEX IF NOT EXISTS idx_question_import_draft_status ON question_import_draft(review_status);
CREATE INDEX IF NOT EXISTS idx_question_import_draft_target ON question_import_draft(target_question_id);
CREATE INDEX IF NOT EXISTS idx_question_import_draft_asset_draft ON question_import_draft_asset(draft_id);

INSERT OR IGNORE INTO question_type(question_type_id, code, name, description) VALUES
    (1, 'single_choice', '单选题', '含 A/B/C/D 等选项的选择题'),
    (2, 'multiple_choice', '多选题', '含多个正确选项的选择题'),
    (3, 'fill_blank', '填空题', '填空、求值或简答型非解答题'),
    (4, 'solution', '解答题', '需要完整过程书写的解答题'),
    (5, 'other', '其他', '暂不能归类的题型');

INSERT OR IGNORE INTO app_meta(key, value) VALUES
    ('app_name', 'MathCyclus'),
    ('schema_version', '1'),
    ('schema_baseline', '20260903');

INSERT OR IGNORE INTO schema_migration(version, name, checksum) VALUES
    (1, 'schema_version_baseline', '');
