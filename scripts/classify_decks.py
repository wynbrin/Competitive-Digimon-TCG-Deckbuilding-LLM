# scripts/classify_decks.py
"""Classify each deck by archetype, using keyword overlap with its cards.

For every deck we normalize its card names the same way archetype keywords
were normalized, then count how many of each archetype's keywords appear as
whole-token matches in the deck. The top-scoring archetype is flagged primary.

Two kinds of keyword (both written in data/archetypes.txt):
  * name keywords  — matched against card names (the default).
  * trait keywords — written "trait:<TraitName>" (e.g. "trait:Hero"); matched
    against each card's digi_type instead, and counted once per *distinct card*
    bearing the trait. This lets trait-defined decks (e.g. Hero/Appmon, which
    reuse names shared with other archetypes) score by how central the trait is.

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


def load_card_traits(cur):
    """{card_id: set of normalized digi_type traits} for 'trait:' keywords."""
    cur.execute("SELECT card_id, digi_type FROM cards WHERE digi_type IS NOT NULL;")
    return {
        r["card_id"]: {normalize(t) for t in (r["digi_type"] or []) if t}
        for r in cur.fetchall()
    }


def load_deck_cards(cur):
    cur.execute("SELECT deck_id, card_id FROM deck_cards;")
    deck_cards = defaultdict(list)
    for r in cur.fetchall():
        deck_cards[r["deck_id"]].append(r["card_id"])
    return deck_cards


def classify_deck(card_ids, card_norms, card_traits, archetypes):
    """Return [(archetype_id, match_count, match_ratio), ...] sorted best-first."""
    # One blob per deck; ' | ' separators stop keywords matching across cards.
    blob = _pad(" | ".join(card_norms[c] for c in card_ids if c in card_norms))

    scored = []
    for aid, a in archetypes.items():
        if a["n"] == 0:
            continue
        mc = 0
        for kw in a["keywords"]:
            token = kw.strip()
            if token.startswith("trait "):
                # Trait keyword: count distinct deck cards carrying the trait,
                # so a trait-defined deck scores by how central the trait is.
                trait = token[len("trait "):]
                mc += sum(1 for c in card_ids if trait in card_traits.get(c, ()))
            elif kw in blob:
                mc += 1
        if mc > 0:
            # Ratio capped at 1.0 (trait keywords can match many cards from one
            # keyword, which would otherwise push the fraction above 1).
            scored.append((aid, mc, min(1.0, mc / a["n"])))

    # Best = most matches, tie-broken by fraction of the archetype hit.
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return scored


def classify(top: int = 5, min_matches: int = 1):
    """Classify all decks and (re)write deck_archetypes. Importable by refresh.py."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            print("Loading archetypes, cards, and decks...")
            archetypes = load_archetypes(cur)
            card_norms = load_card_norms(cur)
            card_traits = load_card_traits(cur)
            deck_cards = load_deck_cards(cur)
            print(f"  {len(archetypes)} archetypes, {len(card_norms)} cards, "
                  f"{len(deck_cards)} decks")

            rows = []
            classified = 0
            unmatched = 0
            for deck_id, card_ids in deck_cards.items():
                scored = classify_deck(card_ids, card_norms, card_traits, archetypes)
                scored = [s for s in scored if s[1] >= min_matches][:top]
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=5,
                        help="store at most N candidate archetypes per deck")
    parser.add_argument("--min-matches", type=int, default=1,
                        help="ignore archetypes with fewer than M keyword matches")
    args = parser.parse_args()
    classify(top=args.top, min_matches=args.min_matches)


if __name__ == "__main__":
    main()
