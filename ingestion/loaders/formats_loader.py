"""Load the format calendar from the flat file into Postgres, and assign decks
to a format by date.

Source of truth: data/formats.txt (pipe-separated:
    block_id | name | region | start_date | end_date).
Re-running syncs the table to the file (upsert + prune).
"""

import os
from datetime import datetime, date as date_type
from typing import List, Optional, Tuple

from app.db.connection import get_connection

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FORMATS_FILE = os.path.join(BASE_DIR, "data", "formats.txt")

# (block_id, name, region, start_date, end_date)
Format = Tuple[str, str, Optional[str], Optional[date_type], Optional[date_type]]


def _parse_date(s: str) -> Optional[date_type]:
    s = (s or "").strip()
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_formats(path: str = FORMATS_FILE) -> List[Format]:
    formats: List[Format] = []
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2 or not parts[0]:
                print(f"WARNING: {path}:{lineno} skipped (need at least block_id|name): {line!r}")
                continue
            parts += [""] * (5 - len(parts))  # pad to 5 fields
            block_id, name, region, start_s, end_s = parts[:5]
            formats.append(
                (block_id, name, region or None, _parse_date(start_s), _parse_date(end_s))
            )
    return formats


def load_formats(path: str = FORMATS_FILE, prune: bool = True):
    formats = parse_formats(path)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            seen = []
            for block_id, name, region, start_date, end_date in formats:
                cur.execute(
                    """
                    INSERT INTO formats (block_id, name, region, start_date, end_date)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (block_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        region = EXCLUDED.region,
                        start_date = EXCLUDED.start_date,
                        end_date = EXCLUDED.end_date;
                    """,
                    (block_id, name, region, start_date, end_date),
                )
                seen.append(block_id)

            removed = 0
            if prune and seen:
                cur.execute("DELETE FROM formats WHERE NOT (block_id = ANY(%s));", (seen,))
                removed = cur.rowcount
        conn.commit()
        msg = f"Synced {len(formats)} formats"
        msg += f"; removed {removed} stale." if prune else "."
        print(msg)
    finally:
        conn.close()


def format_for_date(conn, on_date: date_type, region: Optional[str] = None) -> Optional[str]:
    """Return the block_id of the format in effect on `on_date`.

    Picks the most recent format whose window contains the date; if none
    contains it, falls back to the most recent format that had already started.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT block_id FROM formats
            WHERE start_date IS NOT NULL AND start_date <= %s
              AND (end_date IS NULL OR %s <= end_date)
              AND (%s::text IS NULL OR region = %s)
            ORDER BY start_date DESC
            LIMIT 1;
            """,
            (on_date, on_date, region, region),
        )
        row = cur.fetchone()
        if row:
            return row["block_id"]

        cur.execute(
            """
            SELECT block_id FROM formats
            WHERE start_date IS NOT NULL AND start_date <= %s
              AND (%s::text IS NULL OR region = %s)
            ORDER BY start_date DESC
            LIMIT 1;
            """,
            (on_date, region, region),
        )
        row = cur.fetchone()
        return row["block_id"] if row else None
