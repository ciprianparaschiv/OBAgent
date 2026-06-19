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

## Constraints

- Read-only throughout. Local DB user is granted `SELECT` only.
- Model accessed via an OpenAI-compatible interface; provider is swappable by
  config (cloud for dev, local open model for prod). No provider hard-coded.
- Real data (the `.sql` snapshot, any vector index) is gitignored and never
  leaves this machine.
