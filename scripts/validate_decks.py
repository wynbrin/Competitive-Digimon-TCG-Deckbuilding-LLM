# scripts/validate_decks.py

import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from app.db.connection import get_connection

def main():
    conn = get_connection()
    cur = conn.cursor()

    print("Validating deck ingestion...")

    # 1. Decks with no cards
    cur.execute("""
        SELECT d.id, d.deck_name
        FROM decks d
        LEFT JOIN deck_cards dc ON dc.deck_id = d.id
        GROUP BY d.id
        HAVING COUNT(dc.id) = 0;
    """)
    empty = cur.fetchall()

    if empty:
        print("⚠ Decks with no cards:")
        for row in empty:
            print("  -", row["id"], row["deck_name"])
    else:
        print("✓ All decks have cards.")

    # 2. Cards that don't exist in cards table
    cur.execute("""
        SELECT DISTINCT dc.card_id
        FROM deck_cards dc
        LEFT JOIN cards c ON c.card_id = dc.card_id
        WHERE c.card_id IS NULL;
    """)
    missing = cur.fetchall()

    if missing:
        print("⚠ Missing card definitions:")
        for row in missing:
            print("  -", row["card_id"])
    else:
        print("✓ All deck cards exist in cards table.")

    conn.close()
    print("Validation complete.")

if __name__ == "__main__":
    main()

