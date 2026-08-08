PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS debate_documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_path TEXT,
    source_format TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parse_runs (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES debate_documents(id) ON DELETE CASCADE,
    parser_version TEXT NOT NULL,
    source_format TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES debate_documents(id) ON DELETE CASCADE,
    parent_id TEXT REFERENCES sections(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    argument_type TEXT NOT NULL DEFAULT 'unknown',
    order_index INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS evidence_cards (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES debate_documents(id) ON DELETE CASCADE,
    section_id TEXT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    card_name TEXT,
    argument_name TEXT,
    body TEXT NOT NULL,
    category TEXT,
    topical INTEGER,
    side TEXT,
    source_path TEXT,
    content_hash TEXT NOT NULL,
    paragraph_start INTEGER,
    paragraph_end INTEGER,
    source_format TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citations (
    id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL UNIQUE REFERENCES evidence_cards(id) ON DELETE CASCADE,
    raw TEXT NOT NULL,
    author TEXT,
    year INTEGER,
    source_url TEXT
);

CREATE TABLE IF NOT EXISTS highlights (
    id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES evidence_cards(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    color TEXT,
    highlight_color TEXT,
    paragraph_index INTEGER,
    run_index INTEGER,
    start_char INTEGER,
    end_char INTEGER,
    style TEXT,
    font_size REAL,
    bold INTEGER,
    underline INTEGER,
    order_index INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS card_embeddings (
    id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES evidence_cards(id) ON DELETE CASCADE,
    embedding_kind TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    source_text_hash TEXT NOT NULL,
    vector_collection TEXT NOT NULL,
    vector_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(card_id, embedding_kind, embedding_model)
);

CREATE VIRTUAL TABLE IF NOT EXISTS evidence_cards_fts USING fts5(
    card_id UNINDEXED,
    tag,
    card_name,
    citation,
    body,
    tokenize='porter unicode61'
);

CREATE INDEX IF NOT EXISTS idx_sections_document_id
    ON sections(document_id);

CREATE INDEX IF NOT EXISTS idx_cards_document_id
    ON evidence_cards(document_id);

CREATE INDEX IF NOT EXISTS idx_cards_section_id
    ON evidence_cards(section_id);

CREATE INDEX IF NOT EXISTS idx_cards_content_hash
    ON evidence_cards(content_hash);

CREATE INDEX IF NOT EXISTS idx_citations_author_year
    ON citations(author, year);

CREATE INDEX IF NOT EXISTS idx_highlights_card_id
    ON highlights(card_id);

CREATE INDEX IF NOT EXISTS idx_card_embeddings_card_id
    ON card_embeddings(card_id);
