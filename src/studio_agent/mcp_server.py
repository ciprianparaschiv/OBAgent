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
    """Find past projects whose name/description match the query text.

    Phase-one (lexical) similarity. Returns project_id, name, client, discipline,
    date, people_count and a relevance score, best matches first. Use this to find
    projects similar to a brief, then call get_project for the people who worked on
    the closest matches.
    """
    return repo.search_projects(query, limit=limit)


@mcp.tool()
def get_project(project_id: int) -> dict[str, Any] | None:
    """Full details for one project, including the client, discipline, the lead,
    and everyone who logged time on it (with hours). Returns null if not found."""
    return repo.get_project(project_id)


@mcp.tool()
def list_person_projects(person: str, limit: int = 25) -> dict[str, Any]:
    """A person's past projects (those they logged time on), most recent first.

    ``person`` may be a user id or a name. If the name is ambiguous, returns
    ``person: null`` with a ``candidates`` list to disambiguate; call again with a
    full name or the user id.
    """
    return repo.list_person_projects(person, limit=limit)


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
