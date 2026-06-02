# Digimon TCG LLM — Data Pipeline

Scrape and ingest Digimon TCG tournament decks, cards, and archetypes into a PostgreSQL database for meta-analysis and RAG-based deckbuilding assistant.

## Quick Start

### 1. Setup (one-time)
```bash
# Copy the environment template and fill in your secrets (already done; see .env)
cp .env.example .env

# Install dependencies (conda)
conda env create -f environment.yml
conda activate digimon
```

### 2. Start Docker
```bash
docker-compose up -d
```

### 3. Run the pipeline
From **VS Code Command Palette** (`Ctrl+Shift+P`):
- **Task: Run Task** → pick one:
  - *Migrate: Reset schema* — recreate all tables
  - *Ingest: All* — scrape cards, decks, archetypes
  - *Ingest: Archetypes only* — just reload archetypes from `data/archetypes.txt`
  - *Validate: Decks integrity* — check for orphaned cards

Or from the terminal:
```powershell
python scripts/migrate.py                           # reset schema
python scripts/ingest_all.py                        # scrape + load everything
python -m ingestion.loaders.ingestion archetypes    # just archetypes
python scripts/classify_decks.py                    # label decks by archetype
python scripts/validate_decks.py                    # check data integrity
```

## Database

**Connection:** `localhost:5432`, user `postgres`, password in `.env`

**Schema:**
- `cards` — all ~8k Digimon TCG cards (from digimoncard.io API)
- `decks` — tournament decklists (from digimonmeta.com)
- `deck_cards` — one row per card in each deck
- `archetypes` — archetype taxonomy
- `archetype_keywords` — signal keywords for each archetype
- `deck_archetypes` — classification results: which archetype(s) each deck matches (populated by `classify_decks.py`)

Watch changes live with **SQLTools** (VS Code extension, configured) or `docker exec -it digimon-db psql -U postgres -d digimon`.

## Editing Archetypes

Archetypes live in [data/archetypes.txt](data/archetypes.txt) — one line per archetype:
```
Royal Knights: Magnamon, UlforceVeedramon, Omnimon, Alphamon, ...
```

Edit the file, then:
```powershell
python -m ingestion.loaders.ingestion archetypes
```

The loader will sync the database: adds, edits, deletions all mirror the file. Archetype IDs stay stable (matched by slug).

## Project Structure

```
app/
  db/
    connection.py       — Postgres connection setup (reads .env)
  models/               — (TBD) database models / ORM
  routes/               — (TBD) FastAPI endpoints
  services/             — (TBD) business logic

ingestion/
  cards.py              — Fetch + ingest cards from digimoncard.io
  loaders/
    archetypes_loader.py  — Parse archetypes.txt → DB
    decks_loader.py       — Scrape + ingest tournament decks
    ingestion.py          — Orchestrator (run cards/decks/archetypes/all)
    meta_blocks.py        — Meta block definitions (date ranges for tournaments)

schema/
  001_cards.sql         — Cards table
  002_decks.sql         — Decks + deck_cards tables
  003_archetypes.sql    — Archetypes + keywords tables

scripts/
  migrate.py            — Apply SQL migrations
  ingest_all.py         — Run full pipeline
  validate_decks.py     — Check for orphaned cards, empty decks
  export_decks.py       — Export decks as JSON
  reset_db.py           — Drop and recreate the database

data/
  archetypes.txt        — Source of truth for archetype taxonomy
  processed/            — Aggregated outputs (decks_export.json, etc.)
```

## Next Steps

- [x] **Deck classifier** — match deck cards against archetype keywords to label each deck (`scripts/classify_decks.py`). Unmatched decks reveal archetypes missing from `archetypes.txt`.
- [ ] **Meta stats** — card-inclusion rates, tech choices, matchup win rates per archetype/block
- [ ] **RAG retrieval** — pgvector embeddings of decks + retrieval layer
- [ ] **LLM assistant** — Claude API with retrieved decks + meta stats as context

## Troubleshooting

**"psycopg2 not found"** — make sure you're using the conda `digimon` env, not `venv/`.

**Docker won't start** — check `docker-compose.yaml` and `.env` are in sync. Verify Docker is running.

**Decks missing cards** — run `python scripts/validate_decks.py` to check for orphans. Missing card definitions in the cards table will be flagged.

**Archetype loader hangs** — check that Docker is up and Postgres is accepting connections:
```powershell
docker exec digimon-db pg_isready
```
