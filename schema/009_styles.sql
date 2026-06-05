-- 009_styles.sql
-- Strategic STYLE axes (source stripping, board spam, tall stack, ...),
-- orthogonal to archetype. Source of truth is data/styles.txt
--   "<kind> | <Name> : signal, signal, ...".
-- Loaded by ingestion/loaders/styles_loader.py; scored by scripts/classify_styles.py.
--
-- Unlike archetypes (matched on card NAMES, one primary per deck), styles are
-- matched on card EFFECT text / deck composition and are NON-EXCLUSIVE: every
-- deck gets a continuous score in [0,1] for every style.

DROP TABLE IF EXISTS deck_styles    CASCADE;
DROP TABLE IF EXISTS style_signals  CASCADE;
DROP TABLE IF EXISTS styles         CASCADE;

CREATE TABLE styles (
    id   SERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,        -- stable identifier, e.g. "source_stripping"
    name TEXT NOT NULL,               -- display name, e.g. "Source Stripping"
    kind TEXT NOT NULL                -- 'text' (effect-keyword) | 'structural' (composition)
        CHECK (kind IN ('text', 'structural')),
    category TEXT NOT NULL DEFAULT 'misc'  -- tier, e.g. 'disruption' | 'build' | 'resource'
                                           -- | 'engine'; set via "# @category X" in styles.txt
);

-- Effect-text signal phrases for kind='text' styles (none for 'structural').
CREATE TABLE style_signals (
    id          SERIAL PRIMARY KEY,
    style_id    INTEGER NOT NULL REFERENCES styles(id) ON DELETE CASCADE,
    signal      TEXT NOT NULL,        -- original phrase, as written in the source file
    signal_norm TEXT NOT NULL,        -- normalized for matching against effect text

    UNIQUE (style_id, signal_norm)
);

-- Classification results: per deck, a continuous score for each style.
-- Populated by scripts/classify_styles.py (recomputed, not scraped).
CREATE TABLE deck_styles (
    deck_id     INTEGER NOT NULL REFERENCES decks(id)   ON DELETE CASCADE,
    style_id    INTEGER NOT NULL REFERENCES styles(id)  ON DELETE CASCADE,

    score       REAL    NOT NULL,     -- [0,1]: how strongly the deck leans this style
    signal_hits INTEGER NOT NULL,     -- supporting evidence (card copies for text;
                                      -- the qualifying-copy count for structural)

    PRIMARY KEY (deck_id, style_id)
);

CREATE INDEX idx_style_signals_style   ON style_signals(style_id);
CREATE INDEX idx_style_signals_norm    ON style_signals(signal_norm);
CREATE INDEX idx_deck_styles_deck      ON deck_styles(deck_id);
CREATE INDEX idx_deck_styles_style     ON deck_styles(style_id);
CREATE INDEX idx_deck_styles_score     ON deck_styles(style_id, score DESC);
