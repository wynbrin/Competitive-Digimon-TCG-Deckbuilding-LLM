"""Load strategic styles from the flat text source into Postgres.

Source of truth: data/styles.txt, one style per line:

    text       | Source Stripping : your opponent s digivolution cards, ...
    structural | Board Spam :

The text file stays the human-editable source; this loader parses it,
normalizes each signal phrase for matching, and populates two flat tables
(styles, style_signals). Re-running is idempotent and mirrors the file
(adds, edits, deletions all reflected; ids stay stable, matched by slug).

Mirrors ingestion/loaders/archetypes_loader.py, with two differences:
  * a leading "kind" field ('text' | 'structural'); and
  * 'structural' styles carry no signals (scored from composition instead).
"""

import os
from typing import List, Tuple

from psycopg2.extras import execute_values

from app.db.connection import get_connection
# Reuse the exact normalization applied to card text at match time.
from ingestion.loaders.archetypes_loader import normalize, slugify

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STYLES_FILE = os.path.join(BASE_DIR, "data", "styles.txt")

VALID_KINDS = {"text", "structural"}

# A parsed style: (slug, display name, kind, [(signal, signal_norm), ...])
Style = Tuple[str, str, str, List[Tuple[str, str]]]


def parse_styles(path: str = STYLES_FILE) -> List[Style]:
    """Parse the flat text file into styles, tolerating source noise
    (comments, trailing/double spaces, empty entries from double commas)."""
    entries: List[Style] = []
    used_slugs = {}

    with open(path, encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" not in line:
                print(
                    f"WARNING: {path}:{lineno} has no '|' (kind | Name : ...) "
                    f"and was skipped: {line!r}"
                )
                continue

            kind_part, rest = line.split("|", 1)
            kind = kind_part.strip().lower()
            if kind not in VALID_KINDS:
                print(
                    f"WARNING: {path}:{lineno} has unknown kind {kind!r} "
                    f"(expected text|structural) and was skipped."
                )
                continue

            # The signal list is optional (structural styles omit it).
            name_part, _, sig_part = rest.partition(":")
            name = name_part.strip()
            if not name:
                continue

            signals: List[Tuple[str, str]] = []
            seen_norm = set()
            for raw in sig_part.split(","):
                signal = raw.strip()
                if not signal:
                    continue  # drops empties from "a,,b" etc.
                norm = normalize(signal)
                if not norm or norm in seen_norm:
                    continue  # drop blanks and intra-style duplicates
                seen_norm.add(norm)
                signals.append((signal, norm))

            if kind == "structural" and signals:
                print(
                    f"WARNING: {path}:{lineno} structural style {name!r} lists "
                    f"signals; ignoring them (structural styles score from "
                    f"composition)."
                )
                signals = []

            slug = slugify(name)
            if slug in used_slugs:
                used_slugs[slug] += 1
                slug = f"{slug}_{used_slugs[slug]}"
            else:
                used_slugs[slug] = 1

            entries.append((slug, name, kind, signals))

    return entries


def load_styles(path: str = STYLES_FILE, prune: bool = True):
    """Sync the style tables to the source file.

    The text file is the single source of truth, so by default this makes the
    DB exactly mirror it: styles and signals are upserted, and any rows no
    longer present in the file are removed (set ``prune=False`` for additive-only).
    Existing style ids are preserved across re-runs (matched by slug).
    """
    entries = parse_styles(path)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            total_signals = 0
            seen_slugs = []
            for slug, name, kind, signals in entries:
                cur.execute(
                    """
                    INSERT INTO styles (slug, name, kind)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (slug)
                    DO UPDATE SET name = EXCLUDED.name, kind = EXCLUDED.kind
                    RETURNING id;
                    """,
                    (slug, name, kind),
                )
                style_id = cur.fetchone()["id"]
                seen_slugs.append(slug)

                norms = [norm for _, norm in signals]
                if prune:
                    # Drop signals removed from this style's line (and all
                    # signals if it became structural).
                    cur.execute(
                        """
                        DELETE FROM style_signals
                        WHERE style_id = %s
                          AND NOT (signal_norm = ANY(%s));
                        """,
                        (style_id, norms),
                    )

                if signals:
                    execute_values(
                        cur,
                        """
                        INSERT INTO style_signals (style_id, signal, signal_norm)
                        VALUES %s
                        ON CONFLICT (style_id, signal_norm)
                        DO UPDATE SET signal = EXCLUDED.signal
                        """,
                        [(style_id, sig, norm) for sig, norm in signals],
                    )
                    total_signals += len(signals)

            removed = 0
            if prune:
                # Drop styles no longer present in the file.
                cur.execute(
                    "DELETE FROM styles WHERE NOT (slug = ANY(%s));",
                    (seen_slugs,),
                )
                removed = cur.rowcount

        conn.commit()
        msg = f"Synced {len(entries)} styles ({total_signals} signals)"
        msg += f"; removed {removed} stale style(s)." if prune else "."
        print(msg)
    finally:
        conn.close()
