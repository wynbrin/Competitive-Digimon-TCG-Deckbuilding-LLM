"""Load per-format banlist / restriction entries from the flat file into Postgres.

Source of truth: data/banlist.txt (pipe-separated:
    block_id | status | card name | note).
Re-running syncs the table to the file (full replace). Ships empty until you
populate it from the official restriction lists.
"""

import os
from typing import List, Tuple

from psycopg2.extras import execute_values

from app.db.connection import get_connection

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BANLIST_FILE = os.path.join(BASE_DIR, "data", "banlist.txt")

VALID_STATUSES = {"banned", "restricted", "limited_2", "limited_3"}

# (block_id, card_name, status, note)
Entry = Tuple[str, str, str, str]


def parse_banlist(path: str = BANLIST_FILE) -> List[Entry]:
    entries: List[Entry] = []
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                print(f"WARNING: {path}:{lineno} skipped (need block_id|status|card): {line!r}")
                continue
            parts += [""] * (4 - len(parts))
            block_id, status, card_name, note = parts[:4]
            status = status.lower()
            if status not in VALID_STATUSES:
                print(f"WARNING: {path}:{lineno} unknown status {status!r}: {line!r}")
                continue
            entries.append((block_id, card_name, status, note or None))
    return entries


def load_banlist(path: str = BANLIST_FILE):
    entries = parse_banlist(path)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE banlist;")
            if entries:
                execute_values(
                    cur,
                    "INSERT INTO banlist (block_id, card_name, status, note) VALUES %s",
                    entries,
                )
        conn.commit()
        print(f"Synced {len(entries)} banlist entries.")
    finally:
        conn.close()
