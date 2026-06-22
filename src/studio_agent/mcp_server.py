"""Read-only MCP server exposing the in-house PMS.

A thin shell over ``repository`` (all real logic lives there). Exposes three
read-only tools over stdio:

  * search_projects        - lexical search over name + description
  * get_project            - full details incl. everyone who logged time + lead
  * list_person_projects   - a person's past projects (by name or id)

Run:  studio-mcp           (or: python -m studio_agent.mcp_server)
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import repository as repo

mcp = FastMCP("studio-pms")


@mcp.tool()
def search_projects(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Find past projects most similar to a brief or description.

    Uses semantic (meaning-based) search when the local index is built, otherwise
    keyword search; the ``match`` field shows which. Returns project_id, name,
    client, discipline, date, people_count and a relevance score, best first. Use
    this to find projects similar to a brief, then call get_project for the people
    who worked on the closest matches.
    """
    return repo.search_projects(query, limit=limit)


@mcp.tool()
def recommend_staffing(brief: str, top_k: int = 5) -> dict[str, Any]:
    """Suggest who to staff on an incoming project brief, from PMS experience.

    Finds similar past projects and ranks currently-active people by relevant
    experience (hours on similar work, weighted by similarity and recency, plus a
    lead bonus). Returns a shortlist, each with evidence (the similar projects they
    worked on, hours, similarity). IMPORTANT: this reflects experience only — it
    does NOT know who is available or on leave; always present it as advice for a
    human to decide, and say availability wasn't considered.
    """
    return repo.recommend_staffing(brief, top_k=top_k)


@mcp.tool()
def list_recent_projects(
    days: int = 7, client: str | None = None, limit: int = 20
) -> dict[str, Any]:
    """List projects created recently (by creation date), newest first.

    Use for "what was created today / this week / this month" and "what's new for
    client X". Map the question to ``days`` (today = 1, this week = 7, this month
    = 30). ``client`` optionally filters by client name. Returns project_id, name,
    client, discipline, date (created) and people_count (who's logged time so far).
    """
    return repo.list_recent_projects(days=days, client=client, limit=limit)


@mcp.tool()
def get_project(project_id: int) -> dict[str, Any] | None:
    """Full details for one project, including the client, discipline, the lead,
    and everyone who logged time on it (with hours). Returns null if not found."""
    return repo.get_project(project_id)


@mcp.tool()
def list_person_projects(
    person: str, limit: int = 25, since_days: int | None = None
) -> dict[str, Any]:
    """A person's projects, ordered by most recent activity (when they logged time).

    ``person`` may be a user id or a name. If the name is ambiguous, returns
    ``person: null`` with a ``candidates`` list to disambiguate; call again with a
    full name or the user id.

    For recency questions ("what has X worked on lately / in the last week"), set
    ``since_days`` (e.g. 7 for the last week, 30 for the last month). Results are
    then limited to projects worked on in that window, with hours windowed to it.
    Each project includes ``last_worked`` (date of their most recent time entry).
    """
    return repo.list_person_projects(person, limit=limit, since_days=since_days)


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
