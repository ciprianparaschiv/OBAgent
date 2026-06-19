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

## Data-model notes (phase one)

- `assignment` table is **empty** — "who worked on a project" is derived from
  `timing` (actual logged hours); `project.project_users_responsable` is the lead.
- Discipline/type comes from `worktype`→`ptype` (the `project.project_type` column
  is orphaned and unreliable).
- "Real" projects = `project_deleted = 0` (`project_status` is ~99% one value).
- Mixed text encodings: older rows are cp1252, newer `[RO]` rows are UTF-8 stored
  in latin1; the connector repairs the latter on read.
- "Similar" is currently lexical (name + description). Semantic/vector search is a
  later slice.

## Constraints

- Read-only throughout. Local DB user is granted `SELECT` only.
- Model accessed via an OpenAI-compatible interface; provider is swappable by
  config (cloud for dev, local open model for prod). No provider hard-coded.
- Real data (the `.sql` snapshot, any vector index) is gitignored and never
  leaves this machine.
