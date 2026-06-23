"""Read-only Notion connector for incoming project briefs.

Reads the team's brief/task boards in Notion (the RO Design / Development task
lists). READ-ONLY: only Notion's query and retrieve endpoints are used — no
create/update/delete — and the integration token itself is granted "Read
content" only. Disabled (returns empty) when no token is configured.

This is a plain, framework-independent connector; the agent reaches it through
the MCP server, and the staffing logic lives in ``repository``.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import notion_settings

_API = "https://api.notion.com/v1"
_VERSION = "2022-06-28"

# Property names on the brief cards we assemble into a brief (best-effort; missing
# ones are skipped). The title property is detected by type, not name.
_BRIEF_FIELDS = (
    "Brief Overview",
    "Description",
    "Target Audience",
    "Copy and Content",
    "Dimensions/Project Specs",
    "Special Functionality",
    "Type",
)
_CLIENT_FIELD = "Harvest Time Tracking Project Name"

# Known RO boards -> discipline (the most reliable signal for a brief). Keys are
# database ids with dashes stripped. Unknown boards fall back to text inference.
_BOARD_DISCIPLINE = {
    "14b35e677f07802eb271e98a8240e65e": "design",       # RO Design - Task List
    "14b35e677f07805183c6db499173f309": "development",  # RO Development - Task List
}


def _board_discipline(db_id: str | None) -> str | None:
    return _BOARD_DISCIPLINE.get((db_id or "").replace("-", "").lower())


# A task with this many comments (messages) is treated as a returning/iterative
# task (back-and-forth), in addition to the "flipped back to To Do" signal.
_RETURNING_MIN_MESSAGES = 2
_comments_disabled = False  # set once if the integration lacks "Read comments"


def _is_returning(status: str | None, assignee: str | None, messages: int | None) -> bool:
    if assignee and status == "To Do":
        return True
    return messages is not None and messages >= _RETURNING_MIN_MESSAGES


def comment_count(page_id: str) -> int | None:
    """Number of comments (messages) on a page, or None if unavailable.

    Requires the integration's "Read comments" capability. On 403 we stop trying
    for this process so we don't spam failing calls.
    """
    global _comments_disabled
    if _comments_disabled or not available() or not page_id:
        return None
    try:
        data = _get(f"/comments?block_id={page_id}&page_size=100")
        return len(data.get("results", []))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            _comments_disabled = True
        return None
    except httpx.HTTPError:
        return None


def available() -> bool:
    return bool(notion_settings().token)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {notion_settings().token}",
        "Notion-Version": _VERSION,
        "Content-Type": "application/json",
    }


def _dbs() -> list[str]:
    return [d.strip() for d in notion_settings().briefs_dbs.split(",") if d.strip()]


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = httpx.post(f"{_API}{path}", headers=_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def _get(path: str) -> dict[str, Any]:
    r = httpx.get(f"{_API}{path}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _plain(prop: dict[str, Any]) -> Any:
    """Extract a human-readable value from a Notion property object."""
    t = prop.get("type")
    if t in ("rich_text", "title"):
        return "".join(x.get("plain_text", "") for x in prop.get(t, [])).strip()
    if t == "select":
        return (prop.get("select") or {}).get("name")
    if t == "status":
        return (prop.get("status") or {}).get("name")
    if t == "multi_select":
        return ", ".join(o.get("name", "") for o in prop.get("multi_select", []))
    if t == "people":
        return ", ".join(p.get("name", "") for p in prop.get("people", []))
    if t == "date":
        return (prop.get("date") or {}).get("start")
    if t == "url":
        return prop.get("url")
    if t == "unique_id":
        u = prop.get("unique_id") or {}
        pre = u.get("prefix") or ""
        return f"{pre}{u.get('number')}" if u.get("number") is not None else None
    return None


def _title(props: dict[str, Any]) -> str:
    for p in props.values():
        if p.get("type") == "title":
            return "".join(x.get("plain_text", "") for x in p.get("title", [])).strip()
    return ""


def _summary(
    row: dict[str, Any], discipline: str | None = None, messages: int | None = None
) -> dict[str, Any]:
    p = row.get("properties", {})
    status = _plain(p["Status"]) if "Status" in p else None
    assignee = _plain(p["Assignee"]) if "Assignee" in p else None
    return {
        "id": row.get("id"),
        "title": _title(p) or "(untitled)",
        "status": status,
        "priority": _plain(p["Priority"]) if "Priority" in p else None,
        "client": _plain(p[_CLIENT_FIELD]) if _CLIENT_FIELD in p else None,
        "assignee": assignee or None,
        "created": (row.get("created_time") or "")[:10] or None,
        "last_edited": (row.get("last_edited_time") or "")[:16] or None,
        # Number of comments (messages); None if "Read comments" isn't granted.
        "messages": messages,
        # Returning/iterative: flipped back to "To Do" while assigned, OR has a
        # back-and-forth comment thread.
        "returning": _is_returning(status, assignee, messages),
        # Discipline from the board (set by the caller); None if unknown.
        "discipline": discipline,
        "url": row.get("url"),
    }


def list_incoming_briefs(limit: int = 15, status: str | None = None) -> list[dict[str, Any]]:
    """Recent brief cards across the configured boards, newest first."""
    if not available():
        return []
    out: list[dict[str, Any]] = []
    for db in _dbs():
        payload: dict[str, Any] = {
            "page_size": min(max(limit, 1), 50),
            # Sort by last edited so returning tasks (status flipped back to "To
            # Do", which edits the card) resurface alongside brand-new briefs.
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        }
        if status:
            payload["filter"] = {"property": "Status", "status": {"equals": status}}
        try:
            data = _post(f"/databases/{db}/query", payload)
        except httpx.HTTPError:
            continue  # a board may not be shared / may lack the property
        disc = _board_discipline(db)
        out.extend(
            _summary(r, disc, comment_count(r.get("id"))) for r in data.get("results", [])
        )
    out.sort(key=lambda b: b.get("created") or "", reverse=True)
    return out[:limit]


def get_brief(page_id: str) -> dict[str, Any] | None:
    """Fetch one brief and assemble its descriptive text (for staffing)."""
    if not available():
        return None
    page = _get(f"/pages/{page_id}")
    p = page.get("properties", {})
    parent_db = (page.get("parent") or {}).get("database_id")
    summary = _summary(page, _board_discipline(parent_db), comment_count(page_id))

    parts: list[str] = []
    title = summary["title"]
    if title and title != "(untitled)":
        parts.append(title)
    for field in _BRIEF_FIELDS:
        if field in p:
            val = _plain(p[field])
            if val:
                parts.append(f"{field}: {val}")
    summary["brief_text"] = "\n".join(parts)
    return summary
