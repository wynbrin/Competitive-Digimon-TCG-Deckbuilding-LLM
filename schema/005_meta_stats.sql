-- 005_meta_stats.sql
-- Read-only analytical views over the classified deck data.
-- Safe to re-apply anytime (CREATE OR REPLACE). Depend on:
--   decks, deck_cards, cards, archetypes, deck_archetypes.
-- "Primary archetype" = the top keyword-match for each deck (deck_archetypes.is_primary).

-- Drop first so column/structure changes re-apply cleanly (CREATE OR REPLACE
-- cannot alter a view's column list).
DROP VIEW IF EXISTS v_archetype_card_usage  CASCADE;
DROP VIEW IF EXISTS v_archetype_meta_share  CASCADE;
DROP VIEW IF EXISTS v_archetype_overall     CASCADE;
DROP VIEW IF EXISTS v_archetype_performance CASCADE;

-- ---------------------------------------------------------------------------
-- Card inclusion rates per archetype: the core "what cards define / tech this
-- archetype" view. inclusion_pct = % of the archetype's decks running the card;
-- avg_copies = average number of copies *when played*.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_archetype_card_usage AS
WITH primary_decks AS (
    SELECT archetype_id, deck_id
    FROM deck_archetypes
    WHERE is_primary
),
arch_totals AS (
    SELECT archetype_id, count(*) AS total_decks
    FROM primary_decks
    GROUP BY archetype_id
)
SELECT
    pd.archetype_id,
    a.name                                   AS archetype_name,
    dc.card_id,
    c.name                                   AS card_name,
    c.type                                   AS card_type,
    c.color                                  AS card_color,
    t.total_decks,
    count(DISTINCT pd.deck_id)               AS decks_with_card,
    round(100.0 * count(DISTINCT pd.deck_id) / t.total_decks, 1) AS inclusion_pct,
    round(avg(dc.quantity)::numeric, 2)      AS avg_copies
FROM primary_decks pd
JOIN arch_totals t ON t.archetype_id = pd.archetype_id
JOIN archetypes  a ON a.id          = pd.archetype_id
JOIN deck_cards dc ON dc.deck_id     = pd.deck_id
JOIN cards       c ON c.card_id      = dc.card_id
GROUP BY pd.archetype_id, a.name, dc.card_id, c.name, c.type, c.color, t.total_decks;

-- ---------------------------------------------------------------------------
-- Meta share per block (format): how popular each archetype is within a block.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_archetype_meta_share AS
SELECT
    d.block_id,
    da.archetype_id,
    a.name AS archetype_name,
    count(*) AS deck_count,
    round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY d.block_id), 1) AS block_share_pct
FROM deck_archetypes da
JOIN decks      d ON d.id  = da.deck_id
JOIN archetypes a ON a.id  = da.archetype_id
WHERE da.is_primary
GROUP BY d.block_id, da.archetype_id, a.name;

-- ---------------------------------------------------------------------------
-- Overall meta share across all blocks.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_archetype_overall AS
SELECT
    a.name AS archetype_name,
    count(*) AS deck_count,
    round(100.0 * count(*) / (SELECT count(*) FROM deck_archetypes WHERE is_primary), 2) AS overall_pct
FROM deck_archetypes da
JOIN archetypes a ON a.id = da.archetype_id
WHERE da.is_primary
GROUP BY a.name;

-- ---------------------------------------------------------------------------
-- Archetype performance.
-- NOTE: the source skews heavily toward winning/top-cut lists (~58% of all
-- recorded decks are "1st Place"), so this reflects *what wins/places*, not a
-- true win rate. first_place_pct = share of an archetype's recorded decks that
-- finished 1st. Placement is free-text ("1st Place", "Top-8", "T4", ...).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_archetype_performance AS
SELECT
    a.name AS archetype_name,
    count(*) AS deck_count,
    count(*) FILTER (WHERE d.placement ~* '1st|winner|champion') AS first_place,
    round(
        100.0 * count(*) FILTER (WHERE d.placement ~* '1st|winner|champion')
        / count(*), 1
    ) AS first_place_pct
FROM deck_archetypes da
JOIN decks      d ON d.id = da.deck_id
JOIN archetypes a ON a.id = da.archetype_id
WHERE da.is_primary
GROUP BY a.name;
