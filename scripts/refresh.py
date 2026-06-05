# scripts/refresh.py
"""Refresh the database with new data and rebuild the derived layers.

Pulls new tournament decks (and optionally new cards), then re-labels and
re-embeds so everything stays consistent. The meta-stat views are live and
need no rebuild; formats/banlist sync only when you edit their files.

This does NOT touch the schema — it never drops tables. Safe to run regularly.

Usage:
    python scripts/refresh.py              # decks -> classify -> embed
    python scripts/refresh.py --cards      # also re-pull cards (do this on set release)
    python scripts/refresh.py --formats    # also re-sync formats + banlist (after editing the files)
"""

import sys
import os
import argparse
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from ingestion.loaders.ingestion import (
    run_cards,
    run_decks,
    run_formats,
    run_banlist,
)


def _step(label, fn):
    print(f"\n=== {label} ===")
    start = time.time()
    fn()
    print(f"--- {label} done in {time.time() - start:.0f}s ---")


def main():
    parser = argparse.ArgumentParser(description="Refresh the Digimon DB and derived layers")
    parser.add_argument("--cards", action="store_true", help="also re-pull cards (run on set release)")
    parser.add_argument(
        "--formats", action="store_true",
        help="also re-sync formats + banlist from their flat files",
    )
    args = parser.parse_args()

    overall = time.time()

    if args.cards:
        _step("Cards", run_cards)

    _step("Decks (new tournament results)", run_decks)

    if args.formats:
        _step("Formats", run_formats)
        _step("Banlist", run_banlist)

    # Derived layers — must run after new decks land. Imported lazily because
    # they pull in heavy deps (sentence-transformers) only when needed.
    from scripts.classify_decks import classify
    from scripts.classify_styles import classify as classify_styles
    from scripts.embed_decks import main as embed_main

    _step("Classify decks by archetype", classify)
    _step("Classify decks by style", classify_styles)
    _step("Embed decks for semantic search", embed_main)

    print(f"\nRefresh complete in {time.time() - overall:.0f}s. "
          f"(Meta-stat views are live — no rebuild needed.)")


if __name__ == "__main__":
    main()
