-- 003_archetypes.sql
-- Archetype taxonomy + their signal keywords.
-- Source of truth is data/archetypes.txt (one line per archetype:
--   "Name: keyword, keyword, ...").  Loaded by ingestion/loaders/archetypes_loader.py.

DROP TABLE IF EXISTS archetype_keywords CASCADE;
DROP TABLE IF EXISTS archetypes CASCADE;

CREATE TABLE archetypes (
    id   SERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,        -- stable identifier, e.g. "royal_knights"
    name TEXT NOT NULL                -- display name, e.g. "Royal Knights"
);

CREATE TABLE archetype_keywords (
    id            SERIAL PRIMARY KEY,
    archetype_id  INTEGER NOT NULL REFERENCES archetypes(id) ON DELETE CASCADE,
    keyword       TEXT NOT NULL,      -- original, as written in the source file
    keyword_norm  TEXT NOT NULL,      -- normalized for matching (lowercased, punctuation collapsed)

    UNIQUE (archetype_id, keyword_norm)
);

CREATE INDEX idx_archetype_keywords_archetype_id ON archetype_keywords(archetype_id);
CREATE INDEX idx_archetype_keywords_norm         ON archetype_keywords(keyword_norm);
