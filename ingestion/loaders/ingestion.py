# ingestion/loaders/ingestion.py

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


def run_archetypes():
    from ingestion.loaders.archetypes_loader import load_archetypes
    print("Running archetype ingestion...")
    load_archetypes()
    print("Archetype ingestion complete.")


def run_formats():
    from ingestion.loaders.formats_loader import load_formats
    print("Running format ingestion...")
    load_formats()
    print("Format ingestion complete.")


def run_banlist():
    from ingestion.loaders.banlist_loader import load_banlist
    print("Running banlist ingestion...")
    load_banlist()
    print("Banlist ingestion complete.")


def run_styles():
    from ingestion.loaders.styles_loader import load_styles
    print("Running style ingestion...")
    load_styles()
    print("Style ingestion complete.")


def run_all():
    print("Running full ingestion pipeline...")
    run_cards()
    run_decks()
    run_archetypes()
    run_styles()
    run_formats()
    run_banlist()
    print("All ingestion tasks complete.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python ingestion/ingestion.py [cards|decks|archetypes|styles|formats|banlist|all]")
        sys.exit(1)

    task = sys.argv[1].lower()

    if task == "cards":
        run_cards()
    elif task == "decks":
        run_decks()
    elif task == "archetypes":
        run_archetypes()
    elif task == "styles":
        run_styles()
    elif task == "formats":
        run_formats()
    elif task == "banlist":
        run_banlist()
    elif task == "all":
        run_all()
    else:
        print(f"Unknown task: {task}")
        print("Valid tasks: cards, decks, archetypes, styles, formats, banlist, all")
        sys.exit(1)


if __name__ == "__main__":
    main()

