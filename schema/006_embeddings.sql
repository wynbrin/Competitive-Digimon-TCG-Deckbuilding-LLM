-- 006_embeddings.sql
-- Vector embeddings of decks for semantic retrieval (RAG).
-- Requires the pgvector extension (the digimon-db image ships with it).
-- Dimension 384 matches the sentence-transformers model all-MiniLM-L6-v2.

CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS deck_embeddings CASCADE;

CREATE TABLE deck_embeddings (
    deck_id    INTEGER PRIMARY KEY REFERENCES decks(id) ON DELETE CASCADE,
    model      TEXT NOT NULL,            -- which model produced the vector
    embedding  vector(384) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- No ANN index needed at this scale (~5.6k rows; exact cosine is well under 10ms).
-- If the table grows large, add one, e.g.:
--   CREATE INDEX ON deck_embeddings USING hnsw (embedding vector_cosine_ops);
