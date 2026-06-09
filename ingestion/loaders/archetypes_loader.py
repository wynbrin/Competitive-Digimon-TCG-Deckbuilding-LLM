"""Load archetypes from the flat text source into Postgres.

Source of truth: data/archetypes.txt, one archetype per line:

    Royal Knights: Magnamon, UlforceVeedramon, Omnimon, ...

The text file stays the human-editable source; this loader parses it,
normalizes each keyword for matching, and populates two flat tables
(archetypes, archetype_keywords). Re-running is idempotent.
"""

import os
import re
import unicodedata
from typing import List, Tuple

from psycopg2.extras import execute_values

from app.db.connection import get_connection

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ARCHETYPES_FILE = os.path.join(BASE_DIR, "data", "archetypes.txt")


# A parsed archetype: (slug, display name, [(keyword, keyword_norm), ...])
Archetype = Tuple[str, str, List[Tuple[str, str]]]


def normalize(text: str) -> str:
    """Lowercase, strip accents, and collapse punctuation/whitespace to single spaces.

    The same function is applied to card names at match time, so
    "T.K. Takaishi" and "t k takaishi" compare equal.
    """
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def slugify(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def parse_archetypes(path: str = ARCHETYPES_FILE) -> List[Archetype]:
    """Parse the flat text file into archetypes, tolerating source noise
    (trailing/double spaces, empty entries from double commas, mixed casing)."""
    entries: List[Archetype] = []
    used_slugs = {}

    with open(path, encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                # A non-blank line without a colon is almost always a wrapped
                # archetype line — warn rather than silently dropping it.
                print(
                    f"WARNING: {path}:{lineno} has no ':' and was skipped "
                    f"(wrapped line?): {line!r}"
                )
                continue

            name_part, kw_part = line.split(":", 1)  # split on first colon only
            name = name_part.strip()
            if not name:
                continue

            keywords: List[Tuple[str, str]] = []
            seen_norm = set()
            for raw in kw_part.split(","):
                keyword = raw.strip()
                if not keyword:
                    continue  # drops empties from "ACE,," etc.
                norm = normalize(keyword)
                if not norm or norm in seen_norm:
                    continue  # drop blanks and intra-archetype duplicates
                seen_norm.add(norm)
                keywords.append((keyword, norm))

            slug = slugify(name)
            if slug in used_slugs:
                used_slugs[slug] += 1
                slug = f"{slug}_{used_slugs[slug]}"
            else:
                used_slugs[slug] = 1

            entries.append((slug, name, keywords))

    return entries


def load_archetypes(path: str = ARCHETYPES_FILE, prune: bool = True):
    """Sync the archetype tables to the source file.

    The text file is the single source of truth, so by default this makes the
    DB exactly mirror it: archetypes and keywords are upserted, and any rows no
    longer present in the file are removed (set ``prune=False`` for additive-only).
    Existing archetype ids are preserved across re-runs (matched by slug).
    """
    entries = parse_archetypes(path)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            total_keywords = 0
            seen_slugs = []
            for slug, name, keywords in entries:
                cur.execute(
                    """
                    INSERT INTO archetypes (slug, name)
                    VALUES (%s, %s)
                    ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id;
                    """,
                    (slug, name),
                )
                archetype_id = cur.fetchone()["id"]
                seen_slugs.append(slug)

                norms = [norm for _, norm in keywords]
                if prune:
                    # Drop keywords that were removed from this archetype's line.
                    cur.execute(
                        """
                        DELETE FROM archetype_keywords
                        WHERE archetype_id = %s
                          AND NOT (keyword_norm = ANY(%s));
                        """,
                        (archetype_id, norms),
                    )

                if keywords:
                    execute_values(
                        cur,
                        """
                        INSERT INTO archetype_keywords (archetype_id, keyword, keyword_norm)
                        VALUES %s
                        ON CONFLICT (archetype_id, keyword_norm)
                        DO UPDATE SET keyword = EXCLUDED.keyword
                        """,
                        [(archetype_id, kw, norm) for kw, norm in keywords],
                    )
                    total_keywords += len(keywords)

            removed = 0
            if prune:
                # Drop archetypes no longer present in the file.
                cur.execute(
                    "DELETE FROM archetypes WHERE NOT (slug = ANY(%s));",
                    (seen_slugs,),
                )
                removed = cur.rowcount

        conn.commit()
        msg = f"Synced {len(entries)} archetypes ({total_keywords} keywords)"
        msg += f"; removed {removed} stale archetype(s)." if prune else "."
        print(msg)
    finally:
        conn.close()
