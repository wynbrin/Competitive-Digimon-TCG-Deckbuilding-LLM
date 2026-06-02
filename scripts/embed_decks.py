# scripts/embed_decks.py
"""Compute and store an embedding for every deck (for semantic retrieval).

Builds a text representation of each deck (archetype + card list), embeds it
with a local sentence-transformer, and upserts into deck_embeddings.
Re-running refreshes embeddings in place.

Usage:
    python scripts/embed_decks.py
"""

import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)

from psycopg2.extras import execute_values

from app.db.connection import get_connection
from app.services.retrieval import (
    MODEL_NAME,
    fetch_deck_texts,
    embed_texts,
    to_pgvector,
)


def main():
    conn = get_connection()
    try:
        print("Building deck texts...")
        deck_texts = fetch_deck_texts(conn)
        print(f"  {len(deck_texts)} decks to embed")

        ids = [d for d, _ in deck_texts]
        texts = [t for _, t in deck_texts]

        print("Embedding (first run downloads the model)...")
        vectors = embed_texts(texts)

        rows = [
            (deck_id, MODEL_NAME, to_pgvector(vec))
            for deck_id, vec in zip(ids, vectors)
        ]

        print("Writing embeddings...")
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO deck_embeddings (deck_id, model, embedding)
                VALUES %s
                ON CONFLICT (deck_id)
                DO UPDATE SET model = EXCLUDED.model,
                              embedding = EXCLUDED.embedding,
                              created_at = NOW()
                """,
                rows,
                template="(%s, %s, %s::vector)",
            )
        conn.commit()
        print(f"Done. Embedded {len(rows)} decks with '{MODEL_NAME}'.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
