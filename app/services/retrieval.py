"""Semantic retrieval over decks using sentence-transformer embeddings + pgvector.

Embeddings are local (no API key). The same model embeds both decks (at index
time) and free-text queries (at search time), so similarity is comparable.

Reused by scripts/embed_decks.py (indexing) and scripts/search_decks.py (search),
and later by the Claude generation layer.
"""

from typing import List, Tuple, Optional

MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim; must match vector(384) in schema 006
EMBED_DIM = 384

_model = None


def get_model():
    """Lazily load the embedding model (import is heavy; only load when needed)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print(f"Loading embedding model '{MODEL_NAME}'...")
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_texts(texts: List[str]):
    """Return a list of normalized embedding vectors (lists of float)."""
    model = get_model()
    vecs = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=len(texts) > 200,
        normalize_embeddings=True,  # cosine distance works on unit vectors
    )
    return [v.tolist() for v in vecs]


def to_pgvector(vec: List[float]) -> str:
    """Format a Python float list as a pgvector literal: '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def deck_text(archetype: Optional[str], block_id: str, cardlist: str) -> str:
    """Build the text representation of a deck that gets embedded.

    Most-included cards come first (see SQL ordering) so the defining cards
    survive the model's token-length truncation.
    """
    label = archetype or "Unknown archetype"
    return f"{label} deck (format {block_id}). Cards: {cardlist}"


def fetch_deck_texts(conn) -> List[Tuple[int, str]]:
    """Return [(deck_id, text), ...] for every deck that has cards."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                d.id,
                a.name AS archetype,
                d.block_id,
                string_agg(dc.quantity || 'x ' || c.name, ', '
                           ORDER BY dc.quantity DESC, c.name) AS cardlist
            FROM decks d
            LEFT JOIN deck_archetypes da ON da.deck_id = d.id AND da.is_primary
            LEFT JOIN archetypes a       ON a.id = da.archetype_id
            JOIN deck_cards dc           ON dc.deck_id = d.id
            JOIN cards c                 ON c.card_id = dc.card_id
            GROUP BY d.id, a.name, d.block_id;
            """
        )
        return [
            (r["id"], deck_text(r["archetype"], r["block_id"], r["cardlist"]))
            for r in cur.fetchall()
        ]


def search_decks(conn, query: str, k: int = 5, block_id: Optional[str] = None):
    """Embed `query` and return the k most similar decks (cosine), best first."""
    qvec = to_pgvector(embed_texts([query])[0])

    sql = """
        SELECT
            d.id,
            a.name AS archetype,
            d.block_id,
            d.deck_name,
            d.placement,
            1 - (e.embedding <=> %s::vector) AS similarity,
            string_agg(dc.quantity || 'x ' || c.name, ', '
                       ORDER BY dc.quantity DESC, c.name) AS cardlist
        FROM deck_embeddings e
        JOIN decks d            ON d.id = e.deck_id
        LEFT JOIN deck_archetypes da ON da.deck_id = d.id AND da.is_primary
        LEFT JOIN archetypes a  ON a.id = da.archetype_id
        JOIN deck_cards dc      ON dc.deck_id = d.id
        JOIN cards c            ON c.card_id = dc.card_id
        {where}
        GROUP BY d.id, a.name, d.block_id, d.deck_name, d.placement, e.embedding
        ORDER BY e.embedding <=> %s::vector
        LIMIT %s;
    """
    params = [qvec]
    where = ""
    if block_id:
        where = "WHERE d.block_id = %s"
        params.append(block_id)
    params += [qvec, k]

    with conn.cursor() as cur:
        cur.execute(sql.format(where=where), params)
        return cur.fetchall()
