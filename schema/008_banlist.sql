-- 008_banlist.sql
-- Per-format banlist / restriction list (legality context for the assistant).
-- Source of truth: data/banlist.txt. Keyed to a format in the formats table.

DROP TABLE IF EXISTS banlist CASCADE;

CREATE TABLE banlist (
    id        SERIAL PRIMARY KEY,
    block_id  TEXT NOT NULL REFERENCES formats(block_id) ON DELETE CASCADE,
    card_name TEXT NOT NULL,        -- as written; matched loosely against cards.name
    status    TEXT NOT NULL,        -- 'banned' | 'restricted' (max 1) | 'limited_2' | ...
    note      TEXT,

    UNIQUE (block_id, card_name, status)
);

CREATE INDEX idx_banlist_block ON banlist(block_id);
