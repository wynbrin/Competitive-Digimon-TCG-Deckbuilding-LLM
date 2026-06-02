# scripts/export_decks.py

import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)


import json
from app.db.connection import get_connection

def main():
    conn = get_connection()
    cur = conn.cursor()

    print("Exporting flattened decks...")

    # Fetch all decks
    cur.execute("""
        SELECT 
            id,
            block_id,
            deck_name,
            author,
            date_text,
            deck_date,
            country,
            placement,
            tournament,
            host
        FROM decks
        ORDER BY id;
    """)

    decks = cur.fetchall()
    export = []

    for deck in decks:
        deck_id = deck["id"]

        # Fetch cards for this deck
        cur.execute("""
            SELECT 
                dc.card_id,
                dc.quantity
            FROM deck_cards dc
            WHERE dc.deck_id = %s
            ORDER BY dc.card_id;
        """, (deck_id,))

        cards = cur.fetchall()

        # Flatten card list into {card_id: quantity}
        card_map = {row["card_id"]: row["quantity"] for row in cards}

        export.append({
            "id": deck["id"],
            "block_id": deck["block_id"],
            "deck_name": deck["deck_name"],
            "author": deck["author"],
            "date": deck["date_text"],
            "deck_date": deck["deck_date"].isoformat() if deck["deck_date"] else None,
            "country": deck["country"],
            "placement": deck["placement"],
            "tournament": deck["tournament"],
            "host": deck["host"],
            "cards": card_map
        })

    # Save export file
    with open("data/processed/decks_export_flat.json", "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2)

    conn.close()
    print("Flattened deck export complete.")

if __name__ == "__main__":
    main()
