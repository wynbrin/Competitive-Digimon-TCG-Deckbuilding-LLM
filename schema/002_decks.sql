-- 002_decks.sql
-- Deck metadata + deck card quantities

DROP TABLE IF EXISTS deck_cards;
DROP TABLE IF EXISTS decks;

CREATE TABLE decks (
    id SERIAL PRIMARY KEY,

    block_id TEXT NOT NULL,
    deck_name TEXT NOT NULL,
    date_text TEXT,                 -- original scraped string, e.g. "11/8/2025"
    deck_date DATE,                 -- parsed date (US M/D/Y); NULL if unparseable
    country TEXT,
    author TEXT,
    placement TEXT,
    tournament TEXT,
    host TEXT,

    checksum TEXT,
    content_hash TEXT NOT NULL UNIQUE,   -- dedup key; re-ingesting is a no-op
    raw_dg TEXT NOT NULL,
    source_url TEXT NOT NULL,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_decks_block_id ON decks(block_id);
CREATE INDEX idx_decks_deck_name ON decks(deck_name);
CREATE INDEX idx_decks_deck_date ON decks(deck_date);

CREATE TABLE deck_cards (
    id SERIAL PRIMARY KEY,

    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    card_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_deck_cards_deck_id ON deck_cards(deck_id);
CREATE INDEX idx_deck_cards_card_id ON deck_cards(card_id);
