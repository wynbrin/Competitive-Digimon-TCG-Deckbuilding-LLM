import requests
from psycopg2.extras import execute_values
from app.db.connection import get_connection

API_URL = "https://digimoncard.io/api-public/search.php"

def fetch_all_cards():
    params = {"series": "Digimon Card Game", "sort": "card_number", "sortdirection": "asc"}

    # Include a custom User-Agent header to prevent standard 403/400 blocks on cloud requests
    headers = {"User-Agent": "DigimonSequentialDataPipeline/1.0"}
    print("Fetching cards from DigimonCard.io...")

    response = requests.get(API_URL, params=params, headers=headers)
    response.raise_for_status()

    cards = response.json()
    print(f"Fetched {len(cards)} cards.")
    return cards

def ingest_cards(cards):
    conn = get_connection()
    cur = conn.cursor()

    rows = []
    for c in cards:
        rows.append((
            c.get("id"),
            c.get("name"),
            c.get("type"),
            int(c["level"]) if c.get("level") else None,
            int(c["play_cost"]) if c.get("play_cost") else None,
            int(c["evolution_cost"]) if c.get("evolution_cost") else None,
            [c["evolution_color"]] if c.get("evolution_color") else [],
            int(c["evolution_level"]) if c.get("evolution_level") else None,
            c.get("xros_req"),
            [x for x in [c.get("color"), c.get("color2")] if x],
            [x for x in [
                c.get("digi_type"),
                c.get("digi_type2"),
                c.get("digi_type3"),
                c.get("digi_type4")
            ] if x],
            c.get("form"),
            int(c["dp"]) if c.get("dp") else None,
            c.get("attribute"),
            c.get("rarity"),
            c.get("stage"),
            c.get("artist"),
            c.get("main_effect"),
            c.get("source_effect"),
            c.get("alt_effect"),
            c.get("link_requirements"),
            int(c["link_dp"]) if c.get("link_dp") else None,
            c.get("series"),
            c.get("pretty_url"),
            c.get("date_added"),
            c.get("tcgplayer_name"),
            c.get("tcgplayer_id"),
            c.get("set_name"),
            []  # tags placeholder
        ))

    execute_values(cur, """
        INSERT INTO cards (
            card_id, name, type, level, play_cost, evolution_cost,
            evolution_color, evolution_level, xros_req, color, digi_type,
            form, dp, attribute, rarity, stage, artist, main_effect,
            source_effect, alt_effect, link_requirements, link_dp, series,
            pretty_url, date_added, tcgplayer_name, tcgplayer_id, set_name, tags
        )
        VALUES %s
        ON CONFLICT (card_id) DO NOTHING
    """, rows)

    conn.commit()
    cur.close()
    conn.close()

def load_cards():
    print("Starting card ingestion...")
    cards = fetch_all_cards()
    ingest_cards(cards)
    print("Card ingestion complete.")
