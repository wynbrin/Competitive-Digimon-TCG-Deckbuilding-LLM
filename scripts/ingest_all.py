# scripts/ingest_all.py
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from ingestion.loaders.ingestion import run_cards, run_decks
from ingestion.loaders.meta_blocks import META_BLOCKS

def main():
    print("Starting full ingestion pipeline...")
    run_cards()
    run_decks()
    print("Ingestion pipeline complete.")

if __name__ == "__main__":
    main()
