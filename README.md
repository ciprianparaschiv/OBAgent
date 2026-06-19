# Studio Staffing Agent — phase one (read-only)

A read-only AI agent over the studio's PMS (legacy PHP + MySQL). It answers
questions about past projects and who worked on them, and advises on staffing.
It only observes — no writes to any system in this phase.

See [CLAUDE.md](CLAUDE.md) for architecture principles.

## Layout

```
src/studio_agent/
  config.py        # env-based config (DB + OpenAI-compatible model); no secrets in code
  db.py            # read-only MySQL connector (PyMySQL)
  repository.py    # plain, framework-independent queries (search/details/person history)
  mcp_server.py    # custom MCP server exposing the PMS as read-only tools
  llm.py           # provider-agnostic OpenAI-compatible client
  agent.py         # minimal agent loop (thin, replaceable shell)
scripts/
  import_snapshot.sh  # spin up local MySQL + import the snapshot
tests/             # connector tests
```

## Quick start

```bash
# 1. Local MySQL (Docker) + import the snapshot
./scripts/import_snapshot.sh official_project_new.sql

# 2. Python env
uv venv --python 3.12 && uv pip install -e ".[dev]"

# 3. Config
cp .env.example .env   # fill in OPENAI_API_KEY

# 4. Run tests
uv run pytest
```

> Note: on this machine MySQL runs via Homebrew (`mysql@8.0`), because Docker Hub
> pulls are blocked by Docker Desktop's hub-proxy. `docker-compose.yml` is kept
> for environments where the registry is reachable; `import_snapshot.sh` auto-picks
> the backend (`BACKEND=brew|docker` to force one).

## Prove the slice

Deterministic proof (no API key needed) — runs the tool pipeline through the MCP
server and shows similar past projects + who worked on them:

```bash
.venv/bin/python scripts/prove_slice.py "a Meta ads landing page for a health brand"
```

Natural-language version via the model (needs `OPENAI_API_KEY` in `.env`):

```bash
studio-agent "what past projects are most similar to an email newsletter design for a tech brand, and who worked on them?"
```

Browser UI (the database always stays on your machine):

```bash
studio-web        # then open http://127.0.0.1:8000
```

The UI is a static page (`docs/`). It can be opened locally (above) or served
from a hosted git URL (GitHub Pages) — in which case it calls back to your
**local** `studio-web` backend (set the "Local API" box on the page). The page
holds no data; the backend reads the local snapshot. CORS is open because the
API is read-only and localhost-bound.

> GitHub Pages publishes from a private repo only on a paid plan; on Free the
> repo must be public. The deploy workflow is in `.github/workflows/pages.yml`.

Dev model is set by config only (provider-agnostic). The current default is
Google Gemini's free tier (`gemini-2.5-flash`, free key from
https://aistudio.google.com/apikey); swap to Anthropic / Groq / a local Ollama
server by editing the three `OPENAI_*` lines in `.env` — no code change.

## Data-model notes (phase one)

- `assignment` table is **empty** — "who worked on a project" is derived from
  `timing` (actual logged hours); `project.project_users_responsable` is the lead.
- Discipline/type comes from `worktype`→`ptype` (the `project.project_type` column
  is orphaned and unreliable).
- "Real" projects = `project_deleted = 0` (`project_status` is ~99% one value).
- Mixed text encodings: older rows are cp1252, newer `[RO]` rows are UTF-8 stored
  in latin1; the connector repairs the latter on read.
- "Similar" uses **semantic** search when the local index is built (meaning-based,
  via local embeddings), falling back to lexical keyword search otherwise. Each
  result carries a `match` field showing which was used.

## Semantic index (optional)

```bash
uv pip install -e ".[index]"   # local embeddings (sentence-transformers); no API key
studio-index                   # build index/ from the snapshot (gitignored, ~53MB)
```

The index is built locally and never leaves the machine. Without it, search
falls back to keyword matching automatically.

## Constraints

- Read-only throughout. Local DB user is granted `SELECT` only.
- Model accessed via an OpenAI-compatible interface; provider is swappable by
  config (cloud for dev, local open model for prod). No provider hard-coded.
- Real data (the `.sql` snapshot, any vector index) is gitignored and never
  leaves this machine.
