-- 004_deck_archetypes.sql
-- Classification results: which archetype(s) each deck matches, by keyword overlap.
-- Populated by scripts/classify_decks.py (recomputed, not scraped).

DROP TABLE IF EXISTS deck_archetypes CASCADE;

CREATE TABLE deck_archetypes (
    deck_id      INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    archetype_id INTEGER NOT NULL REFERENCES archetypes(id) ON DELETE CASCADE,

    match_count  INTEGER NOT NULL,   -- distinct archetype keywords found in the deck
    match_ratio  REAL    NOT NULL,   -- match_count / total keywords for that archetype
    is_primary   BOOLEAN NOT NULL DEFAULT FALSE,  -- top-ranked archetype for this deck

    PRIMARY KEY (deck_id, archetype_id)
);

CREATE INDEX idx_deck_archetypes_deck      ON deck_archetypes(deck_id);
CREATE INDEX idx_deck_archetypes_archetype ON deck_archetypes(archetype_id);
CREATE INDEX idx_deck_archetypes_primary   ON deck_archetypes(archetype_id) WHERE is_primary;
