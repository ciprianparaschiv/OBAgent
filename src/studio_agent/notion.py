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


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    p = row.get("properties", {})
    return {
        "id": row.get("id"),
        "title": _title(p) or "(untitled)",
        "status": _plain(p["Status"]) if "Status" in p else None,
        "priority": _plain(p["Priority"]) if "Priority" in p else None,
        "client": _plain(p[_CLIENT_FIELD]) if _CLIENT_FIELD in p else None,
        "assignee": _plain(p["Assignee"]) if "Assignee" in p else None,
        "created": (row.get("created_time") or "")[:10] or None,
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
            "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        }
        if status:
            payload["filter"] = {"property": "Status", "status": {"equals": status}}
        try:
            data = _post(f"/databases/{db}/query", payload)
        except httpx.HTTPError:
            continue  # a board may not be shared / may lack the property
        out.extend(_summary(r) for r in data.get("results", []))
    out.sort(key=lambda b: b.get("created") or "", reverse=True)
    return out[:limit]


def get_brief(page_id: str) -> dict[str, Any] | None:
    """Fetch one brief and assemble its descriptive text (for staffing)."""
    if not available():
        return None
    page = _get(f"/pages/{page_id}")
    p = page.get("properties", {})
    summary = _summary(page)

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
