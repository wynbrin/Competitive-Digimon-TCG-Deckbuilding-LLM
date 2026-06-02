# scripts/search_decks.py
"""Semantic search over decks.

Usage:
    python scripts/search_decks.py "aggressive red rush with Agumon"
    python scripts/search_decks.py "control deck with security removal" --k 8
    python scripts/search_decks.py "Imperialdramon" --block bt24_ex11
"""

import sys
import os
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from app.db.connection import get_connection
from app.services.retrieval import search_decks


def main():
    parser = argparse.ArgumentParser(description="Semantic deck search")
    parser.add_argument("query", help="free-text description of the deck you want")
    parser.add_argument("--k", type=int, default=5, help="number of results")
    parser.add_argument("--block", default=None, help="restrict to a block_id (format)")
    args = parser.parse_args()

    conn = get_connection()
    try:
        results = search_decks(conn, args.query, k=args.k, block_id=args.block)
    finally:
        conn.close()

    if not results:
        print("No results (have you run embed_decks.py yet?).")
        return

    print(f'\nTop {len(results)} decks for: "{args.query}"\n')
    for r in results:
        arch = r["archetype"] or "Unknown"
        print(f"  [{r['similarity']:.3f}] #{r['id']} {arch}  "
              f"({r['block_id']}, {r['placement']}) - scraped: {r['deck_name']}")
        cards = r["cardlist"]
        if len(cards) > 110:
            cards = cards[:110] + "..."
        print(f"          {cards}\n")


if __name__ == "__main__":
    main()
