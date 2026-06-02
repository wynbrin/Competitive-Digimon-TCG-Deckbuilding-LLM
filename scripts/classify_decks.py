# scripts/classify_decks.py
"""Classify each deck by archetype, using keyword overlap with its cards.

For every deck we normalize its card names the same way archetype keywords
were normalized, then count how many of each archetype's keywords appear as
whole-token matches in the deck. The top-scoring archetype is flagged primary.

Results are written to the deck_archetypes table (top N candidates per deck).
Re-running fully replaces the previous results.

Usage:
    python scripts/classify_decks.py [--top N] [--min-matches M]
"""

import sys
import os
import argparse
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from psycopg2.extras import execute_values

from app.db.connection import get_connection
from ingestion.loaders.archetypes_loader import normalize  # same normalization as keywords


def _pad(s: str) -> str:
    """Surround with spaces so substring search matches whole tokens only."""
    return f" {s} "


def load_archetypes(cur):
    cur.execute(
        """
        SELECT a.id, a.name, count(ak.id) AS n_keywords
        FROM archetypes a
        LEFT JOIN archetype_keywords ak ON ak.archetype_id = a.id
        GROUP BY a.id, a.name;
        """
    )
    archetypes = {
        r["id"]: {"name": r["name"], "n": r["n_keywords"], "keywords": []}
        for r in cur.fetchall()
    }

    cur.execute("SELECT archetype_id, keyword_norm FROM archetype_keywords;")
    for r in cur.fetchall():
        archetypes[r["archetype_id"]]["keywords"].append(_pad(r["keyword_norm"]))

    return archetypes


def load_card_norms(cur):
    cur.execute("SELECT card_id, name FROM cards WHERE name IS NOT NULL;")
    return {r["card_id"]: _pad(normalize(r["name"])) for r in cur.fetchall()}


def load_deck_cards(cur):
    cur.execute("SELECT deck_id, card_id FROM deck_cards;")
    deck_cards = defaultdict(list)
    for r in cur.fetchall():
        deck_cards[r["deck_id"]].append(r["card_id"])
    return deck_cards


def classify_deck(card_ids, card_norms, archetypes):
    """Return [(archetype_id, match_count, match_ratio), ...] sorted best-first."""
    # One blob per deck; ' | ' separators stop keywords matching across cards.
    blob = _pad(" | ".join(card_norms[c] for c in card_ids if c in card_norms))

    scored = []
    for aid, a in archetypes.items():
        if a["n"] == 0:
            continue
        mc = sum(1 for kw in a["keywords"] if kw in blob)
        if mc > 0:
            scored.append((aid, mc, mc / a["n"]))

    # Best = most keywords matched, tie-broken by fraction of the archetype hit.
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return scored


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=5,
                        help="store at most N candidate archetypes per deck")
    parser.add_argument("--min-matches", type=int, default=1,
                        help="ignore archetypes with fewer than M keyword matches")
    args = parser.parse_args()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            print("Loading archetypes, cards, and decks...")
            archetypes = load_archetypes(cur)
            card_norms = load_card_norms(cur)
            deck_cards = load_deck_cards(cur)
            print(f"  {len(archetypes)} archetypes, {len(card_norms)} cards, "
                  f"{len(deck_cards)} decks")

            rows = []
            classified = 0
            unmatched = 0
            for deck_id, card_ids in deck_cards.items():
                scored = classify_deck(card_ids, card_norms, archetypes)
                scored = [s for s in scored if s[1] >= args.min_matches][: args.top]
                if not scored:
                    unmatched += 1
                    continue
                classified += 1
                for rank, (aid, mc, ratio) in enumerate(scored):
                    rows.append((deck_id, aid, mc, round(ratio, 4), rank == 0))

            print("Writing results...")
            cur.execute("TRUNCATE deck_archetypes;")
            execute_values(
                cur,
                """
                INSERT INTO deck_archetypes
                    (deck_id, archetype_id, match_count, match_ratio, is_primary)
                VALUES %s
                """,
                rows,
            )
        conn.commit()
        print(f"Done. Classified {classified} decks "
              f"({unmatched} with no keyword match), {len(rows)} rows written.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
