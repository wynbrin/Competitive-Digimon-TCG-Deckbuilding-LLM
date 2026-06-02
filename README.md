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
python scripts/embed_decks.py                        # build deck embeddings (semantic search)
python scripts/search_decks.py "red aggro Agumon"   # semantic deck search
python scripts/ask.py "tech cards for Imperialdramon?"  # LLM deckbuilding assistant
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
- `deck_embeddings` — pgvector embedding per deck for semantic search (populated by `embed_decks.py`)
- `formats` — the meta/format calendar (block_id, date range, region); maps a deck's date to its meta
- `banlist` — per-format banned/restricted cards (legality context for the assistant)

**Analytical views** (read-only, always live — defined in `schema/005_meta_stats.sql`):
- `v_archetype_card_usage` — per archetype, each card's inclusion % and avg copies (staples vs. tech)
- `v_archetype_meta_share` — archetype popularity within each block/format
- `v_archetype_overall` — archetype popularity across all blocks
- `v_archetype_performance` — 1st-place rate per archetype (note: source skews to winning lists)

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

## Meta Analysis

The views in `schema/005_meta_stats.sql` are **live** — they recompute on every
query, so after re-running `classify_decks.py` they reflect the new data with no
re-apply step. (Re-apply the file only if you change a view *definition*:
`docker exec -i digimon-db psql -U postgres -d digimon < schema/005_meta_stats.sql`)

Example queries:
```sql
-- Staples vs tech for an archetype (high % = core, mid % = flex/tech)
SELECT card_name, inclusion_pct, avg_copies
FROM v_archetype_card_usage
WHERE archetype_name = 'Imperialdramon'
ORDER BY inclusion_pct DESC;

-- What's popular in the current format
SELECT archetype_name, deck_count, block_share_pct
FROM v_archetype_meta_share
WHERE block_id = 'bt24_ex11'
ORDER BY deck_count DESC;

-- Which archetypes win most (caveat: source skews to top-cut lists)
SELECT archetype_name, deck_count, first_place_pct
FROM v_archetype_performance
WHERE deck_count >= 40
ORDER BY first_place_pct DESC;
```

> Note: `v_archetype_card_usage` groups by `card_id`, so different printings of a
> card (same name, different set number) appear as separate rows — intentional,
> since printings can differ in effect/level.

## Formats & Banlist

The **format calendar** lives in [data/formats.txt](data/formats.txt) — one line per
meta period (`block_id | name | region | start_date | end_date`). It powers two things:

- **Auto-assigning a meta to dated results.** `formats_loader.format_for_date(conn, date)`
  returns the `block_id` whose window contains a date — so any tournament result with a
  date can be placed in the right meta without manual tagging.
- **Human-readable meta names** in the assistant's context.

> The seeded dates are auto-derived from observed deck dates and are approximate —
> refine them against real set-release / banlist dates.

The **banlist** lives in [data/banlist.txt](data/banlist.txt)
(`block_id | status | card name | note`, where status is `banned` / `restricted` /
`limited_2` / `limited_3`). It ships empty — populate it from the official Bandai
restriction lists. When you ask the assistant with `--block`, the banlist for that
format is fed in as binding legality context (it won't recommend banned cards or
over-limit copies).

```powershell
python -m ingestion.loaders.ingestion formats   # sync the format calendar
python -m ingestion.loaders.ingestion banlist    # sync the banlist
```

## Deckbuilding Assistant (LLM)

`scripts/ask.py` retrieves grounding context (semantic deck search + meta-stat
views) and asks Claude (`claude-opus-4-8`) to answer using **only** that context —
it cites inclusion %, distinguishes staples from tech, and refuses to invent cards.

Setup (one-time): add your key to `.env` and install the SDK.
```
# .env
ANTHROPIC_API_KEY=sk-ant-...
```
```powershell
pip install anthropic        # or: conda env update -f environment.yml
```

Ask:
```powershell
python scripts/ask.py "What tech cards should I run in Imperialdramon right now?"
python scripts/ask.py "How do I build Puppets?" --block bt24_ex11
python scripts/ask.py "What beats Royal Knights?" --archetype "Royal Knights" --k 8
python scripts/ask.py "..." --show-context   # also print the retrieved context
```

> The assistant is grounded on tournament *placement* data, not head-to-head
> results — it answers matchup questions qualitatively, not with win rates.

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
- [x] **Meta stats** — card-inclusion rates, tech choices, meta share, and 1st-place rates per archetype/block (`schema/005_meta_stats.sql` views). True head-to-head matchup win rates are not derivable (source has placements, not match results).
- [x] **RAG retrieval** — pgvector deck embeddings (`embed_decks.py`) + semantic search (`search_decks.py`, `app/services/retrieval.py`)
- [x] **LLM assistant** — Claude (`claude-opus-4-8`) grounded on retrieved decks + meta stats (`scripts/ask.py`, `app/services/assistant.py`)

## Troubleshooting

**"psycopg2 not found"** — make sure you're using the conda `digimon` env, not `venv/`.

**Docker won't start** — check `docker-compose.yaml` and `.env` are in sync. Verify Docker is running.

**Decks missing cards** — run `python scripts/validate_decks.py` to check for orphans. Missing card definitions in the cards table will be flagged.

**Archetype loader hangs** — check that Docker is up and Postgres is accepting connections:
```powershell
docker exec digimon-db pg_isready
```
