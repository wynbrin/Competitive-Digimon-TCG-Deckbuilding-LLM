# scripts/ingest_all.py
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from ingestion.loaders.ingestion import (
    run_cards, run_decks, run_archetypes, run_formats, run_banlist
)

def main():
    print("Starting full ingestion pipeline...")
    run_cards()
    run_decks()
    run_archetypes()
    run_formats()
    run_banlist()
    print("Ingestion pipeline complete.")

if __name__ == "__main__":
    main()
