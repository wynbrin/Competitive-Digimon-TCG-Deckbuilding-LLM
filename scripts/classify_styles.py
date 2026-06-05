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

def _is_digimon(card) -> bool:
    return (card["type"] or "").strip().lower() == "digimon"


def _digimon_copies(rows) -> int:
    return sum(r["quantity"] for r in rows if _is_digimon(r))


def score_board_spam(rows):
    """Wide/cheap board: share of Digimon copies that are low-level (<= 4)."""
    total = _digimon_copies(rows)
    if total == 0:
        return 0.0, 0
    cheap = sum(
        r["quantity"] for r in rows
        if _is_digimon(r) and r["level"] is not None and r["level"] <= 4
    )
    return cheap / total, cheap


def score_tall_stack(rows):
    """Traditional tall stack: share of Digimon copies that are top-end (>= 6)."""
    total = _digimon_copies(rows)
    if total == 0:
        return 0.0, 0
    big = sum(
        r["quantity"] for r in rows
        if _is_digimon(r) and r["level"] is not None and r["level"] >= 6
    )
    return big / total, big


STRUCTURAL_SCORERS = {
    "board_spam": score_board_spam,
    "tall_stack": score_tall_stack,
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
    """Return {deck_id: [ {card_id, quantity, type, level, play_cost}, ... ]}."""
    cur.execute(
        """
        SELECT dc.deck_id, dc.card_id, dc.quantity,
               c.type, c.level, c.play_cost
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
            score, hits = scorer(rows)
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
