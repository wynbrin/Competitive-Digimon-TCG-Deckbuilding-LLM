import os
import json
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass, asdict
from typing import List, Dict, Any

from app.db.connection import get_connection

import re
import unicodedata
import hashlib
from datetime import datetime, date as date_type
from typing import Optional

def ensure_dir(path: str):
    """Create directory if it doesn't exist, safely."""
    os.makedirs(path, exist_ok=True)


def safe_filename(name: str, block_id: str = "") -> str:
    # Normalize Unicode to remove accents, weird characters
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode()

    # Replace illegal filesystem characters
    name = re.sub(r'[\\/*?:"<>|]', "_", name)

    # Replace spaces with underscores
    name = name.replace(" ", "_")

    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)

    # Trim length (Windows-safe)
    MAX_LEN = 80
    short = name[:MAX_LEN].rstrip("_")

    # Add a hash suffix to guarantee uniqueness
    hash_suffix = hashlib.md5(name.encode()).hexdigest()[:8]

    if block_id:
        return f"{block_id}_{short}_{hash_suffix}"
    return f"{short}_{hash_suffix}"



# -----------------------------
# Data Models
# -----------------------------

@dataclass
class DeckCard:
    card_id: str
    quantity: int


@dataclass
class DeckEntry:
    block_id: str
    deck_name: str
    date: str
    country: str
    author: str
    placement: str
    tournament: str
    host: str
    checksum: str
    cards: List[DeckCard]
    raw_dg: str
    source_url: str


# -----------------------------
# Helpers
# -----------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.text


def parse_deckinfo_link(href: str) -> Dict[str, Any]:
    parsed = urlparse(href)
    qs = parse_qs(parsed.query if parsed.query else href.split("?", 1)[-1])

    def get(key: str) -> str:
        return qs.get(key, [""])[0]

    return {
        "deck_name": get("dn"),
        "date": get("date"),
        "country": get("cn"),
        "author": get("au"),
        "placement": get("pl"),
        "tournament": get("tn"),
        "host": get("hs"),
        "decklist_raw": get("dg"),
        "checksum": get("cs"),
    }


def decode_decklist(dg: str) -> List[DeckCard]:
    cards = []
    if not dg:
        return cards

    matches = re.findall(r"(\d+)n([A-Z0-9-]+)", dg)
    for qty, card_id in matches:
        cards.append(DeckCard(card_id=card_id, quantity=int(qty)))

    return cards


def parse_deck_date(date_str: str) -> Optional[date_type]:
    """Parse the scraped date string into a date. Source uses US M/D/Y."""
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def deck_content_hash(deck: "DeckEntry") -> str:
    """Stable hash of a deck's identifying fields, used to dedup re-ingestion."""
    key = "|".join([
        deck.block_id or "",
        deck.deck_name or "",
        deck.date or "",
        deck.author or "",
        deck.placement or "",
        deck.tournament or "",
        deck.raw_dg or "",
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# -----------------------------
# Scraper
# -----------------------------

def scrape_meta_block_page(url: str, block_id: str) -> List[DeckEntry]:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    deck_entries = []

    for a in soup.select("a[href^='deckinfo2']"):
        href = a.get("href", "").strip()
        if not href:
            continue

        meta = parse_deckinfo_link(href)
        cards = decode_decklist(meta["decklist_raw"])

        deck_entries.append(
            DeckEntry(
                block_id=block_id,
                deck_name=meta["deck_name"],
                date=meta["date"],
                country=meta["country"],
                author=meta["author"],
                placement=meta["placement"],
                tournament=meta["tournament"],
                host=meta["host"],
                checksum=meta["checksum"],
                cards=cards,
                raw_dg=meta["decklist_raw"],
                source_url=url,
            )
        )

    return deck_entries


# -----------------------------
# Database Insertion
# -----------------------------

def insert_deck(conn, deck: DeckEntry) -> Optional[int]:
    """Insert a deck, skipping if it was already ingested.

    Returns the new deck id, or None if a deck with the same content_hash
    already exists (ON CONFLICT DO NOTHING returns no row).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO decks (block_id, deck_name, date_text, deck_date, country, author, placement, tournament, host, checksum, content_hash, raw_dg, source_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (content_hash) DO NOTHING
            RETURNING id;
            """,
            (
                deck.block_id,
                deck.deck_name,
                deck.date,
                parse_deck_date(deck.date),
                deck.country,
                deck.author,
                deck.placement,
                deck.tournament,
                deck.host,
                deck.checksum,
                deck_content_hash(deck),
                deck.raw_dg,
                deck.source_url,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        return row["id"] if row else None


def insert_deck_cards(conn, deck_id: int, cards: List[DeckCard]):
    with conn.cursor() as cur:
        for card in cards:
            cur.execute(
                """
                INSERT INTO deck_cards (deck_id, card_id, quantity)
                VALUES (%s, %s, %s);
                """,
                (deck_id, card.card_id, card.quantity),
            )
        conn.commit()


# -----------------------------
# File Output
# -----------------------------



BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

RAW_DIR = os.path.join(BASE_DIR, "data", "raw", "decks")
PROC_DIR = os.path.join(BASE_DIR, "data", "processed", "decks")


os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(PROC_DIR, exist_ok=True)

def save_raw_json(deck: DeckEntry):
    ensure_dir(RAW_DIR)
    filename = safe_filename(deck.deck_name, deck.block_id) + ".json"
    path = os.path.join(RAW_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(deck), f, indent=2)



def save_processed_json(deck_id: int, deck: DeckEntry):
    ensure_dir(PROC_DIR)
    filename = safe_filename(deck.deck_name, deck.block_id) + f"_{deck_id}.json"
    path = os.path.join(PROC_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(deck), f, indent=2)



# -----------------------------
# Orchestrator
# -----------------------------

def load_decks(meta_blocks: List[Dict[str, str]]):
    conn = get_connection()
    ensure_dir(RAW_DIR)
    ensure_dir(PROC_DIR)

    for block in meta_blocks:
        block_id = block["block_id"]
        url = block["url"]

        print(f"Scraping block {block_id} from {url}...")

        decks = scrape_meta_block_page(url, block_id)
        print(f"  Found {len(decks)} decks.")

        for deck in decks:
            
            try:
                deck_id = insert_deck(conn, deck)
                if deck_id is None:
                    # Already ingested (matching content_hash) — skip.
                    continue
                insert_deck_cards(conn, deck_id, deck.cards)

                save_raw_json(deck)
                save_processed_json(deck_id, deck)

            except Exception as e:
                print(f"  ⚠ Error ingesting deck {deck.deck_name}: {e}")
                continue


        print(f"  Finished block {block_id}")

    conn.close()
