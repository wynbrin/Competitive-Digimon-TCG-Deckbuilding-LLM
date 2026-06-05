-- 010_style_stats.sql
-- Read-only analytical views over the style-scored deck data.
-- Safe to re-apply anytime (CREATE OR REPLACE). Depend on:
--   decks, deck_styles, styles, deck_archetypes, archetypes.
--
-- Styles are non-exclusive continuous scores, so "popularity" here means the
-- average lean toward a style and how often a deck leans into it past a
-- threshold (lead_share), NOT an exclusive deck count like the archetype views.

DROP VIEW IF EXISTS v_style_overall      CASCADE;
DROP VIEW IF EXISTS v_style_meta_share   CASCADE;
DROP VIEW IF EXISTS v_archetype_styles   CASCADE;

-- ---------------------------------------------------------------------------
-- Overall style prevalence across all decks. avg_score = mean lean toward the
-- style; lead_share = % of decks that lean into it meaningfully (score >= 0.2).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_style_overall AS
SELECT
    s.name AS style_name,
    s.kind AS style_kind,
    count(*) AS scored_decks,
    round(avg(ds.score)::numeric, 3)                              AS avg_score,
    round(100.0 * count(*) FILTER (WHERE ds.score >= 0.2)
          / count(*), 1)                                          AS lead_share_pct
FROM deck_styles ds
JOIN styles s ON s.id = ds.style_id
GROUP BY s.name, s.kind;

-- ---------------------------------------------------------------------------
-- Style prevalence per block (format): how the meta's strategic mix shifts.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_style_meta_share AS
SELECT
    d.block_id,
    s.name AS style_name,
    count(*) AS scored_decks,
    round(avg(ds.score)::numeric, 3)                              AS avg_score,
    round(100.0 * count(*) FILTER (WHERE ds.score >= 0.2)
          / count(*), 1)                                          AS lead_share_pct
FROM deck_styles ds
JOIN decks  d ON d.id = ds.deck_id
JOIN styles s ON s.id = ds.style_id
GROUP BY d.block_id, s.name;

-- ---------------------------------------------------------------------------
-- The bridge: how each ARCHETYPE is typically built, by style. Answers
-- "Royal Knights usually plays tall-stack, but ~X% of lists go board-spam."
-- Uses each deck's primary archetype (deck_archetypes.is_primary).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_archetype_styles AS
WITH primary_decks AS (
    SELECT archetype_id, deck_id
    FROM deck_archetypes
    WHERE is_primary
)
SELECT
    a.name AS archetype_name,
    s.name AS style_name,
    count(*) AS archetype_decks,
    round(avg(ds.score)::numeric, 3)                              AS avg_score,
    round(100.0 * count(*) FILTER (WHERE ds.score >= 0.2)
          / count(*), 1)                                          AS lead_share_pct
FROM primary_decks pd
JOIN archetypes  a ON a.id  = pd.archetype_id
JOIN deck_styles ds ON ds.deck_id = pd.deck_id
JOIN styles      s ON s.id = ds.style_id
GROUP BY a.name, s.name;
