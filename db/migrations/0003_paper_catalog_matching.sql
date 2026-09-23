CREATE TABLE IF NOT EXISTS paper_standard_catalog (
    paper_standard_id TEXT PRIMARY KEY,
    paper_id TEXT UNIQUE REFERENCES paper(paper_id) ON DELETE SET NULL,
    year INTEGER,
    paper_series TEXT NOT NULL,
    track TEXT NOT NULL DEFAULT '',
    paper_name TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'confirmed',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(year, paper_series, track, paper_name)
);

CREATE TABLE IF NOT EXISTS paper_alias (
    paper_alias_id TEXT PRIMARY KEY,
    paper_standard_id TEXT NOT NULL REFERENCES paper_standard_catalog(paper_standard_id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'historical',
    source TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_standard_id, alias_name)
);

CREATE TABLE IF NOT EXISTS paper_match_review (
    paper_match_review_id TEXT PRIMARY KEY,
    batch_id TEXT,
    draft_id TEXT,
    recognized_year INTEGER,
    recognized_series TEXT NOT NULL DEFAULT '',
    recognized_track TEXT NOT NULL DEFAULT '',
    recognized_name TEXT NOT NULL DEFAULT '',
    suggested_standard_id TEXT REFERENCES paper_standard_catalog(paper_standard_id) ON DELETE SET NULL,
    suggested_score REAL,
    decision TEXT NOT NULL DEFAULT 'pending',
    confirmed_standard_id TEXT REFERENCES paper_standard_catalog(paper_standard_id) ON DELETE SET NULL,
    confirmed_year INTEGER,
    confirmed_series TEXT NOT NULL DEFAULT '',
    confirmed_track TEXT NOT NULL DEFAULT '',
    confirmed_name TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_paper_standard_lookup ON paper_standard_catalog(year, paper_series, track, paper_name);
CREATE INDEX IF NOT EXISTS idx_paper_alias_name ON paper_alias(alias_name);
CREATE INDEX IF NOT EXISTS idx_paper_match_review_decision ON paper_match_review(decision, updated_at);

INSERT OR IGNORE INTO paper_standard_catalog(paper_standard_id, paper_id, year, paper_series, track, paper_name, source_name, status, sort_order, created_at, updated_at)
SELECT 'PS_' || paper_id, paper_id, year, paper_series, track, paper_name, CASE WHEN source_name != '' THEN source_name ELSE paper_name END, 'confirmed', 0, created_at, updated_at FROM paper;

INSERT OR IGNORE INTO paper_alias(paper_alias_id, paper_standard_id, alias_name, alias_type, source, note)
SELECT 'PA_' || paper_id, 'PS_' || paper_id, source_name, 'legacy_source', 'paper.source_name', 'migrated legacy source name'
FROM paper WHERE TRIM(source_name) != '' AND TRIM(source_name) != TRIM(paper_name);

INSERT INTO app_meta(key, value, updated_at) VALUES ('schema_version', '3', CURRENT_TIMESTAMP)
ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP;
