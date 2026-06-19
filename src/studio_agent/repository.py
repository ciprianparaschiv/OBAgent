"""Plain, framework-independent read queries over the PMS snapshot.

Data-model decisions (confirmed against the snapshot, see CLAUDE.md / inspection):
  * "Who worked on a project" = distinct users in ``timing`` (actual logged time),
    plus the project's ``project_users_responsable`` surfaced as the lead.
  * Discipline/type = ``worktype`` -> ``ptype`` (the ``project.project_type`` column
    is orphaned and unreliable).
  * Real projects = ``project_deleted = 0`` (``project_status`` is ~99% one value).

These functions return JSON-serialisable dicts and contain no MCP/agent concepts.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from .db import query, query_one

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _iso(ts: int | None) -> str | None:
    """Unix timestamp -> YYYY-MM-DD (the PMS stores dates as unix ints)."""
    if not ts:
        return None
    try:
        return _dt.datetime.fromtimestamp(int(ts), _dt.timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return None


def _hours(seconds: Any) -> float:
    # MySQL SUM() returns Decimal; coerce before arithmetic.
    return round(float(seconds or 0) / 3600.0, 1)


# Reusable correlated subqueries.
_DISCIPLINE_SQL = """
    (SELECT GROUP_CONCAT(DISTINCT pt.ptype_name ORDER BY pt.ptype_name SEPARATOR ', ')
       FROM worktype w JOIN ptype pt ON pt.ptype_id = w.ptype_id
      WHERE w.project_id = p.project_id)
"""

_PEOPLE_COUNT_SQL = """
    (SELECT COUNT(DISTINCT t.timing_user)
       FROM timing t WHERE t.timing_project = p.project_id)
"""


# ---------------------------------------------------------------------------
# people
# ---------------------------------------------------------------------------


def find_people(name: str, limit: int = 8) -> list[dict[str, Any]]:
    """All users whose name contains ``name`` (active/non-deleted first)."""
    return query(
        """SELECT user_id, user_name, user_email, user_type, user_active, user_deleted
             FROM user
            WHERE user_name LIKE %s
            ORDER BY user_deleted ASC, user_active DESC, user_name ASC
            LIMIT %s""",
        (f"%{name}%", int(limit)),
    )


def resolve_person(name_or_id: str | int) -> dict[str, Any] | None:
    """Resolve to a single user, or None if 0 / genuinely ambiguous.

    Rules: id lookup is exact; a case-insensitive exact name match wins; a single
    partial match resolves; otherwise return None (caller can use ``find_people``
    to disambiguate).
    """
    if isinstance(name_or_id, int) or str(name_or_id).isdigit():
        return query_one(
            "SELECT user_id, user_name, user_email, user_type FROM user WHERE user_id=%s",
            (int(name_or_id),),
        )
    rows = find_people(name_or_id)
    exact = [r for r in rows if r["user_name"].lower() == str(name_or_id).lower()]
    if exact:
        return exact[0]
    return rows[0] if len(rows) == 1 else None


def list_people(limit: int = 100) -> list[dict[str, Any]]:
    return query(
        """SELECT u.user_id, u.user_name, u.user_email, ut.usertype_name AS role,
                  u.user_active, u.user_deleted
             FROM user u
             LEFT JOIN usertype ut ON ut.usertype_id = u.user_type
            ORDER BY u.user_deleted ASC, u.user_active DESC, u.user_name ASC
            LIMIT %s""",
        (int(limit),),
    )


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------


def search_projects(query_text: str, limit: int = 10) -> list[dict[str, Any]]:
    """Lexical search over project name + description.

    Phase-one similarity: scores each project by how many query terms appear in
    its name (weight 2) and description (weight 1). Semantic/vector search is a
    later slice.
    """
    terms = [t for t in query_text.split() if len(t) >= 2][:8]
    if not terms:
        return []

    score_parts, where_parts, params = [], [], []
    for t in terms:
        like = f"%{t}%"
        score_parts.append(
            "(CASE WHEN p.project_name LIKE %s THEN 2 ELSE 0 END)"
            " + (CASE WHEN p.project_description LIKE %s THEN 1 ELSE 0 END)"
        )
        params.extend([like, like])
        where_parts.append("(p.project_name LIKE %s OR p.project_description LIKE %s)")
        params.extend([like, like])

    score_sql = " + ".join(score_parts)
    where_sql = " OR ".join(where_parts)

    sql = f"""
        SELECT p.project_id,
               p.project_name      AS name,
               c.client_name       AS client,
               {_DISCIPLINE_SQL}   AS discipline,
               p.project_date      AS date_ts,
               {_PEOPLE_COUNT_SQL} AS people_count,
               ({score_sql})       AS score
          FROM project p
          LEFT JOIN client c ON c.client_id = p.project_client
         WHERE p.project_deleted = 0
           AND ({where_sql})
         ORDER BY score DESC, p.project_date DESC
         LIMIT %s
    """
    params.append(int(limit))
    rows = query(sql, params)
    for r in rows:
        r["date"] = _iso(r.pop("date_ts"))
    return rows


def get_project(project_id: int) -> dict[str, Any] | None:
    """Full details for one project, including everyone who logged time on it."""
    p = query_one(
        f"""SELECT p.project_id,
                   p.project_name        AS name,
                   p.project_description AS description,
                   c.client_id           AS client_id,
                   c.client_name         AS client,
                   {_DISCIPLINE_SQL}     AS discipline,
                   p.project_date        AS date_ts,
                   p.project_price       AS price,
                   p.project_users_responsable AS lead_user_id
              FROM project p
              LEFT JOIN client c ON c.client_id = p.project_client
             WHERE p.project_id = %s AND p.project_deleted = 0""",
        (int(project_id),),
    )
    if not p:
        return None
    p["date"] = _iso(p.pop("date_ts"))

    lead = query_one(
        "SELECT user_id, user_name FROM user WHERE user_id=%s",
        (p.get("lead_user_id") or 0,),
    )
    p["lead"] = lead["user_name"] if lead else None

    p["people"] = query(
        """SELECT u.user_id, u.user_name AS name,
                  COUNT(*) AS time_entries,
                  SUM(GREATEST(t.timing_end - t.timing_start, 0)) AS seconds
             FROM timing t
             JOIN user u ON u.user_id = t.timing_user
            WHERE t.timing_project = %s
            GROUP BY u.user_id, u.user_name
            ORDER BY seconds DESC""",
        (int(project_id),),
    )
    for person in p["people"]:
        person["hours"] = _hours(person.pop("seconds"))
        person["is_lead"] = person["user_id"] == p.get("lead_user_id")
    return p


def list_person_projects(name_or_id: str | int, limit: int = 25) -> dict[str, Any]:
    """A person's past projects: those they logged time on (and/or led)."""
    person = resolve_person(name_or_id)
    if not person:
        # Surface candidates so the caller (agent) can disambiguate.
        candidates = find_people(str(name_or_id)) if not str(name_or_id).isdigit() else []
        return {
            "person": None,
            "candidates": [
                {"user_id": c["user_id"], "name": c["user_name"]} for c in candidates
            ],
            "projects": [],
        }

    uid = person["user_id"]
    projects = query(
        f"""SELECT p.project_id,
                   p.project_name    AS name,
                   c.client_name     AS client,
                   {_DISCIPLINE_SQL} AS discipline,
                   p.project_date    AS date_ts,
                   COUNT(*)          AS time_entries,
                   SUM(GREATEST(t.timing_end - t.timing_start, 0)) AS seconds,
                   (p.project_users_responsable = %s) AS is_lead
              FROM timing t
              JOIN project p ON p.project_id = t.timing_project
              LEFT JOIN client c ON c.client_id = p.project_client
             WHERE t.timing_user = %s AND p.project_deleted = 0
             GROUP BY p.project_id, p.project_name, c.client_name, p.project_date,
                      p.project_users_responsable
             ORDER BY p.project_date DESC
             LIMIT %s""",
        (uid, uid, int(limit)),
    )
    for r in projects:
        r["date"] = _iso(r.pop("date_ts"))
        r["hours"] = _hours(r.pop("seconds"))
        r["is_lead"] = bool(r["is_lead"])
    return {
        "person": {
            "user_id": person["user_id"],
            "name": person["user_name"],
            "email": person.get("user_email"),
        },
        "projects": projects,
    }
