# scripts/classify_styles.py
"""Score each deck on every strategic STYLE (orthogonal to archetype).

Styles are NON-EXCLUSIVE: a deck gets a continuous score in [0,1] for each
style, not a single label. Two scoring mechanisms, by style kind:

  * text       — phrases (style_signals) matched against each card's EFFECT text
                 (main + source + alt). score = fraction of the deck's card
                 copies whose effect text hits any of the style's signals.

  * structural — composition heuristics computed here (curve / level mix). These
                 carry no signals in data/styles.txt; the slug below routes each
                 to its scorer in STRUCTURAL_SCORERS.

Results are written to deck_styles (recomputed, like deck_archetypes).
Re-running fully replaces the previous results.

Usage:
    python scripts/classify_styles.py [--min-score S]
"""

import sys
import os
import re
import argparse
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from psycopg2.extras import execute_values

from app.db.connection import get_connection
from ingestion.loaders.archetypes_loader import normalize  # same normalization as signals


def _pad(s: str) -> str:
    """Surround with spaces so a multi-word signal matches on token boundaries."""
    return f" {s} "


# ---------------------------------------------------------------------------
# Structural scorers. Each takes the deck's card rows (one per distinct card,
# each a dict with quantity + card attributes) and returns a score in [0,1]
# plus a supporting "hits" count (qualifying copies). These are deliberately
# simple starter heuristics — eyeball the output and refine.
# ---------------------------------------------------------------------------

MEGA_LEVEL = 6  # Lv6+ = Mega / Ultra ("top end")

# Diversity pivots (distinct top-end Digimon in a deck), used to split the two
# top-heavy styles apart. At/below LOW a deck leans on a single line (pure Tall
# Stack); at/above HIGH it's a many-mega toolbox (pure Megazoo); linear between.
# Tuned against observed decks: focused lines run ~3-4 distinct megas, zoos
# (Royal Knights, 7DL) run ~10-11. Raise HIGH to make "zoo" stricter.
TOPEND_DIVERSITY_LOW = 3
TOPEND_DIVERSITY_HIGH = 9

# "Goes wide by effect" engine phrases for Board Spam, matched against card
# effect text (same normalization as text-style signals). These field extra
# bodies without a cheap curve: token generation, suspend-cost deploys, cost
# reduction, and Digisorption. Edit this list to tune what counts as
# effect-driven swarm. (Kept in code, not styles.txt, because Board Spam blends
# them with a structural curve term — see score_board_spam.)
GO_WIDE_SIGNALS = [
    "token",
    "digisorption",
    "by suspending",
    "you may play 1",
    "reduce the play cost",
]
GO_WIDE_SIGNALS_NORM = [_pad(normalize(s)) for s in GO_WIDE_SIGNALS]

# Combat Denial signals with per-phrase weights, matched against card effect
# text. Blocker is a near-staple keyword (~470 cards), so it counts for a
# fraction of the rarer, more intentional denial effects (defensive Decoy,
# outright attack denial). Lower the blocker weight to sharpen the style toward
# pure denial; raise it to lean back toward "blocker-wall density".
COMBAT_DENIAL_SIGNALS = {
    "switch the target of attack to this digimon": 1.0,  # defensive <Decoy>
    "opponent s digimon can t attack": 1.0,              # outright attack denial
    "can t attack or block": 1.0,                        # attack lock (older template)
    "your opponent s digimon can t suspend": 1.0,        # newer template: can't
                                                         # suspend => can't attack
    "blocker": 0.3,                                      # common — down-weighted
}
COMBAT_DENIAL_SIGNALS_NORM = [
    (_pad(normalize(sig)), wt) for sig, wt in COMBAT_DENIAL_SIGNALS.items()
]


def _is_digimon(card) -> bool:
    return (card["type"] or "").strip().lower() == "digimon"


def _digimon_copies(rows) -> int:
    return sum(r["quantity"] for r in rows if _is_digimon(r))


def _topend_stats(rows):
    """(digimon_copies, topend_copies, distinct_topend) for one deck.

    distinct_topend counts *different* Lv6+ Digimon cards (rows are already one
    per distinct card), which is what separates a single-line stack from a zoo.
    """
    total = _digimon_copies(rows)
    topend = [
        r for r in rows
        if _is_digimon(r) and r["level"] is not None and r["level"] >= MEGA_LEVEL
    ]
    return total, sum(r["quantity"] for r in topend), len(topend)


def _topend_diversity(distinct: int) -> float:
    """0.0 (single-line) .. 1.0 (full zoo), ramped between the pivots."""
    lo, hi = TOPEND_DIVERSITY_LOW, TOPEND_DIVERSITY_HIGH
    return max(0.0, min(1.0, (distinct - lo) / (hi - lo)))


def score_board_spam(rows, effects):
    """Goes wide — by a cheap curve AND/OR by effect.

    Two ways a deck floods the board: many low-level (<=4) bodies, or engines
    that deploy extra Digimon by effect (tokens, suspend-cost plays, cost
    reduction, Digisorption) even on a higher curve. The two terms are combined
    as a probabilistic OR, so a deck counts if it swarms cheaply, by effect, or
    both — that's what catches Vegetation/Vortex/Puppets, which run a normal
    curve but field a wide board through effects.
    """
    total = _digimon_copies(rows)
    if total == 0:
        return 0.0, 0
    cheap = gowide = wide = 0
    for r in rows:
        is_cheap = _is_digimon(r) and r["level"] is not None and r["level"] <= 4
        is_gw = any(sig in effects.get(r["card_id"], "") for sig in GO_WIDE_SIGNALS_NORM)
        if is_cheap:
            cheap += r["quantity"]
        if is_gw:
            gowide += r["quantity"]
        if is_cheap or is_gw:
            wide += r["quantity"]
    low_curve = cheap / total
    deploy = min(1.0, gowide / total)
    score = 1.0 - (1.0 - low_curve) * (1.0 - deploy)  # probabilistic OR

    # A wide board of many *distinct* megas is a Megazoo, not spam. Down-weight
    # by the same top-heavy*diverse factor Megazoo uses, so zoos (Royal Knights)
    # shed their board-spam bleed while few-mega effect-swarms (Vegetation,
    # Puppets) are barely touched.
    _, topend_copies, distinct = _topend_stats(rows)
    megazoo_factor = (topend_copies / total) * _topend_diversity(distinct)
    score *= 1.0 - megazoo_factor
    return score, wide


def score_tall_stack(rows, effects):
    """Traditional tall stack: top-heavy AND *concentrated* on few lines.

    Same top-heaviness as Megazoo, but rewards leaning on one big digivolution
    line (few distinct megas) rather than a toolbox of many.
    """
    total, topend_copies, distinct = _topend_stats(rows)
    if total == 0 or topend_copies == 0:
        return 0.0, 0
    mega_share = topend_copies / total
    concentration = 1.0 - _topend_diversity(distinct)
    return mega_share * concentration, topend_copies


def score_megazoo(rows, effects):
    """Top-heavy AND *diverse*: many different Lv6+ Digimon cheated out by
    effect/cost-reduction rather than a single climbed line."""
    total, topend_copies, distinct = _topend_stats(rows)
    if total == 0 or topend_copies == 0:
        return 0.0, 0
    mega_share = topend_copies / total
    diversity = _topend_diversity(distinct)
    return mega_share * diversity, topend_copies


def score_combat_denial(rows, effects):
    """Stops/redirects the opponent's attacks. Weighted copy-share: each card
    counts at its highest-weight matching signal, so a deck of cheap blockers
    scores below one running real attack-denial (with blocker down-weighted)."""
    total = sum(r["quantity"] for r in rows)
    if total == 0:
        return 0.0, 0
    weighted = 0.0
    hits = 0
    for r in rows:
        eff = effects.get(r["card_id"], "")
        w = max((wt for sig, wt in COMBAT_DENIAL_SIGNALS_NORM if sig in eff), default=0.0)
        if w > 0:
            weighted += w * r["quantity"]
            hits += r["quantity"]
    return min(1.0, weighted / total), hits


def score_hybrid(rows, effects):
    """Hybrid (Frontier spirit-evolution) engine: share of Digimon copies that
    are Hybrid-form (played/digivolved off a Tamer rather than climbing a curve).
    Structural — read off the card's `form`, which is cleaner than effect text."""
    total = _digimon_copies(rows)
    if total == 0:
        return 0.0, 0
    hyb = sum(
        r["quantity"] for r in rows
        if _is_digimon(r) and (r.get("form") or "").strip().lower() == "hybrid"
    )
    return hyb / total, hyb


def score_armor(rows, effects):
    """Armor digivolution engine: share of Digimon copies that are Armor-form
    (digivolved with a Digi-Egg). Structural — read off the card `form`."""
    total = _digimon_copies(rows)
    if total == 0:
        return 0.0, 0
    arm = sum(
        r["quantity"] for r in rows
        if _is_digimon(r) and (r.get("form") or "").strip().lower() == "armor form"
    )
    return arm / total, arm


def _has_trait(card, trait_lower: str) -> bool:
    return any((t or "").strip().lower() == trait_lower for t in (card.get("digi_type") or []))


# Mill: trashing cards off the top of a deck (self and/or opponent) to fuel
# trash-count synergies. Regex (not a plain phrase) so the card count varies and
# we don't grab "trash the top card of your opponent's SECURITY" (that's Security
# Manipulation). Matches "trash the top [N] card(s) of your [opponent's] deck".
MILL_RE = re.compile(r"trash the top (\d+ )?cards? of your (opponent s )?deck")


def score_mill(rows, effects):
    """Mill engine: share of copies that trash off the top of a deck (self-mill
    like Beelzemon, opponent-mill like Creepymon, or both)."""
    total = sum(r["quantity"] for r in rows)
    if total == 0:
        return 0.0, 0
    hits = sum(r["quantity"] for r in rows if MILL_RE.search(effects.get(r["card_id"], "")))
    return hits / total, hits


def score_x_antibody(rows, effects):
    """X Antibody engine: share of Digimon copies carrying the [X Antibody] trait
    (X-evolution). A tribal-style mechanic spanning many lines; structural, off
    digi_type. X decks tend to co-score Tall Stack, but the X engine is the
    defining axis, not the stack shape."""
    total = _digimon_copies(rows)
    if total == 0:
        return 0.0, 0
    xa = sum(r["quantity"] for r in rows if _is_digimon(r) and _has_trait(r, "x antibody"))
    return xa / total, xa


def _trait_engine(trait_lower):
    """Build a structural scorer for a trait-defined engine (e.g. Time Stranger,
    Cyber Sleuth, Data Squad). Score = share of ALL deck copies carrying the
    trait — these themes span Digimon, Tamers and Options, so we don't restrict
    to Digimon (unlike X Antibody)."""
    def scorer(rows, effects):
        total = sum(r["quantity"] for r in rows)
        if total == 0:
            return 0.0, 0
        n = sum(r["quantity"] for r in rows if _has_trait(r, trait_lower))
        return n / total, n
    return scorer


STRUCTURAL_SCORERS = {
    "board_spam": score_board_spam,
    "tall_stack": score_tall_stack,
    "megazoo": score_megazoo,
    "combat_denial": score_combat_denial,
    "hybrid": score_hybrid,
    "armor": score_armor,
    "x_antibody": score_x_antibody,
    "mill": score_mill,
    # Trait-defined engines (over-encompassing themes spanning many colors).
    "adventure": _trait_engine("adventure"),
    "time_stranger": _trait_engine("ts"),
    "cyber_sleuth": _trait_engine("cs"),
    "dm": _trait_engine("dm"),
    "data_squad": _trait_engine("data squad"),
    "beat_break": _trait_engine("beatbreak"),
}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_styles(cur):
    """Return {style_id: {name, slug, kind, signals:[padded_norm,...]}}."""
    cur.execute("SELECT id, name, slug, kind FROM styles;")
    styles = {
        r["id"]: {"name": r["name"], "slug": r["slug"], "kind": r["kind"], "signals": []}
        for r in cur.fetchall()
    }
    cur.execute("SELECT style_id, signal_norm FROM style_signals;")
    for r in cur.fetchall():
        styles[r["style_id"]]["signals"].append(_pad(r["signal_norm"]))
    return styles


def load_card_effects(cur):
    """Return {card_id: padded normalized effect blob} for text matching."""
    cur.execute(
        """
        SELECT card_id,
               concat_ws(' ', main_effect, source_effect, alt_effect) AS effect
        FROM cards;
        """
    )
    return {r["card_id"]: _pad(normalize(r["effect"] or "")) for r in cur.fetchall()}


def load_deck_rows(cur):
    """Return {deck_id: [ {card_id, quantity, type, level, play_cost, form, digi_type}, ... ]}."""
    cur.execute(
        """
        SELECT dc.deck_id, dc.card_id, dc.quantity,
               c.type, c.level, c.play_cost, c.form, c.digi_type
        FROM deck_cards dc
        JOIN cards c ON c.card_id = dc.card_id;
        """
    )
    decks = defaultdict(list)
    for r in cur.fetchall():
        decks[r["deck_id"]].append(dict(r))
    return decks


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_deck(rows, styles, card_effects):
    """Return [(style_id, score, hits), ...] for a single deck."""
    total_copies = sum(r["quantity"] for r in rows)
    out = []
    for sid, s in styles.items():
        if s["kind"] == "structural":
            scorer = STRUCTURAL_SCORERS.get(s["slug"])
            if scorer is None:
                # Structural style with no coded scorer yet — skip quietly.
                continue
            score, hits = scorer(rows, card_effects)
        else:  # text
            if not s["signals"] or total_copies == 0:
                continue
            hits = sum(
                r["quantity"] for r in rows
                if any(sig in card_effects.get(r["card_id"], "") for sig in s["signals"])
            )
            score = hits / total_copies
        out.append((sid, round(float(score), 4), int(hits)))
    return out


def classify(min_score: float = 0.0):
    """Score all decks and (re)write deck_styles. Importable by refresh.py."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            print("Loading styles, card effects, and decks...")
            styles = load_styles(cur)
            card_effects = load_card_effects(cur)
            deck_rows = load_deck_rows(cur)

            missing = [
                s["slug"] for s in styles.values()
                if s["kind"] == "structural" and s["slug"] not in STRUCTURAL_SCORERS
            ]
            if missing:
                print(f"  NOTE: structural styles with no scorer (skipped): {missing}")
            print(f"  {len(styles)} styles, {len(card_effects)} cards, "
                  f"{len(deck_rows)} decks")

            rows = []
            for deck_id, dr in deck_rows.items():
                for sid, score, hits in score_deck(dr, styles, card_effects):
                    if score > min_score:
                        rows.append((deck_id, sid, score, hits))

            print("Writing results...")
            cur.execute("TRUNCATE deck_styles;")
            execute_values(
                cur,
                """
                INSERT INTO deck_styles (deck_id, style_id, score, signal_hits)
                VALUES %s
                """,
                rows,
            )
        conn.commit()
        print(f"Done. {len(rows)} deck-style scores written "
              f"(min_score > {min_score}).")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-score", type=float, default=0.0,
                        help="only store scores strictly above this threshold")
    args = parser.parse_args()
    classify(min_score=args.min_score)


if __name__ == "__main__":
    main()
