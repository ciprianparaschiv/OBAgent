# Project: Studio Staffing Agent (read-only, phase one)

## What we're building
A read-only AI agent that connects a model to our studio's tools and project
history. It answers questions about past work and recommends who to staff on
incoming projects. It only observes and advises — a human makes every decision.
No writing to any system in this phase.

## Architecture principles
- Python.
- The model is a swappable component. Talk to it through an OpenAI-compatible
  interface so we can switch between a cloud model (dev) and a local open model
  (production) with a config change. Never hard-code a provider.
- Build data connectors as MCP servers. Custom MCP server for our in-house PMS;
  prefer existing MCP servers for third-party tools.
- Keep our own logic (normalization, staffing reasoning, instructions) as plain,
  framework-independent code. Any agent framework is a thin, replaceable shell.
  Do NOT use the Claude Agent SDK — it ties us to one model and we're going local.
- Secrets in environment variables, never committed. Real data and the vector
  index are gitignored and never leave this machine.

## Data sources and roles
- PMS: legacy PHP app on a MySQL database, hosted on cPanel. System of record for
  projects, people, assignments. READ-ONLY. For now we develop against a LOCAL
  copy imported from a database snapshot — no connection to production yet. A live
  read-only connection (SSH tunnel or Remote MySQL) comes later.
- Notion: live comms with our Australia team; where incoming projects appear.
- Asana: legacy historical archive.
- Dropbox: project assets.
- Leave planner: who is present on a given day.
  (Availability = leave planner [present?] + PMS active assignments [loaded?].)

## Working style
- Build in small vertical slices; one thing working end-to-end before widening.
- Commit in small steps. Write tests as you go, especially around connectors.
- Ask before anything that writes, deletes, or touches production. This phase is
  read-only throughout.
