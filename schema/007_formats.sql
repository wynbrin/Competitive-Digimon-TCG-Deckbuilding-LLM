-- 007_formats.sql
-- The format calendar: each block_id is a meta period (set legality + banlist
-- window) with a date range and region. Lets dated tournament results be
-- assigned to the right meta. Source of truth: data/formats.txt.

DROP TABLE IF EXISTS formats CASCADE;

CREATE TABLE formats (
    block_id   TEXT PRIMARY KEY,    -- matches decks.block_id, e.g. "bt24_ex11"
    name       TEXT NOT NULL,       -- display name, e.g. "BT24 Time Stranger / EX11..."
    region     TEXT,                -- e.g. "EN" (English format)
    start_date DATE,                -- when this format became current
    end_date   DATE                 -- last day; NULL = current/ongoing
);

CREATE INDEX idx_formats_start ON formats(start_date);
