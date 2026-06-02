# ingestion/ingestion.py

import sys
from ingestion.loaders.meta_blocks import META_BLOCKS


def run_cards():
    from ingestion.cards import load_cards
    print("Running card ingestion...")
    load_cards()
    print("Card ingestion complete.")


def run_decks():
    from ingestion.loaders.decks_loader import load_decks
    print("Running deck ingestion...")
    load_decks(META_BLOCKS)
    print("Deck ingestion complete.")


def run_all():
    print("Running full ingestion pipeline...")
    run_cards()
    run_decks()
    print("All ingestion tasks complete.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python ingestion/ingestion.py [cards|decks|all]")
        sys.exit(1)

    task = sys.argv[1].lower()

    if task == "cards":
        run_cards()
    elif task == "decks":
        run_decks()
    elif task == "all":
        run_all()
    else:
        print(f"Unknown task: {task}")
        print("Valid tasks: cards, decks, all")
        sys.exit(1)


if __name__ == "__main__":
    main()

