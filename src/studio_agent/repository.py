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
import time as _time
from typing import Any

from .db import query, query_one


def _now() -> float:
    """Current unix time (wall clock). Isolated for clarity/testing."""
    return _time.time()

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


# Mojibake markers from UTF-8 text mistakenly stored in a latin1 column
# (e.g. "Levi’s" -> "Leviâ€™s"). Older rows are correctly cp1252 and are left
# alone; the cp1252->utf-8 round-trip below self-validates, so clean text that
# merely contains one of these bytes (a lone Romanian "â") fails the decode and
# passes through unchanged.
_MOJIBAKE_MARKERS = ("â€", "Ã", "Â", "â‚¬")


def _clean_text(s: Any) -> Any:
    if not isinstance(s, str) or not any(m in s for m in _MOJIBAKE_MARKERS):
        return s
    try:
        return s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _deep_clean(obj: Any) -> Any:
    """Recursively repair double-encoded text in a result structure."""
    if isinstance(obj, str):
        return _clean_text(obj)
    if isinstance(obj, list):
        return [_deep_clean(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _deep_clean(v) for k, v in obj.items()}
    return obj


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


def lexical_search_projects(query_text: str, limit: int = 10) -> list[dict[str, Any]]:
    """Keyword search over project name + description.

    Scores each project by how many query terms appear in its name (weight 2) and
    description (weight 1). Used directly, or as a fallback when no semantic index
    is built. See ``search_projects`` for the dispatcher.
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
        r["match"] = "lexical"
    return _deep_clean(rows)


def _projects_by_ids(ids: list[int]) -> dict[int, dict[str, Any]]:
    """Fetch display rows for the given project ids (non-deleted only)."""
    if not ids:
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    rows = query(
        f"""SELECT p.project_id,
                   p.project_name      AS name,
                   c.client_name       AS client,
                   {_DISCIPLINE_SQL}   AS discipline,
                   p.project_date      AS date_ts,
                   {_PEOPLE_COUNT_SQL} AS people_count
              FROM project p
              LEFT JOIN client c ON c.client_id = p.project_client
             WHERE p.project_deleted = 0 AND p.project_id IN ({placeholders})""",
        ids,
    )
    return {r["project_id"]: r for r in rows}


def semantic_search_projects(query_text: str, limit: int = 10) -> list[dict[str, Any]]:
    """Embedding-based similarity over project text (needs a built index).

    Returns [] if no index is present so the caller can fall back to lexical.
    """
    from . import index

    hits = index.search(query_text, limit=limit)
    if not hits:
        return []
    by_id = _projects_by_ids([pid for pid, _ in hits])
    out: list[dict[str, Any]] = []
    for pid, score in hits:  # already ordered best-first
        row = by_id.get(pid)
        if not row:  # project deleted since the index was built
            continue
        row = dict(row)
        row["date"] = _iso(row.pop("date_ts"))
        row["score"] = round(score, 4)
        row["match"] = "semantic"
        out.append(row)
    return _deep_clean(out)


def search_projects(
    query_text: str, limit: int = 10, mode: str = "auto"
) -> list[dict[str, Any]]:
    """Find projects similar to the query.

    ``mode``: "auto" (semantic if an index is built, else lexical), "semantic",
    or "lexical". Results carry a ``match`` field indicating which was used.
    """
    from . import index

    want_semantic = mode == "semantic" or (mode == "auto" and index.available())
    if want_semantic:
        results = semantic_search_projects(query_text, limit)
        if results or mode == "semantic":
            return results
    return lexical_search_projects(query_text, limit)


def projects_for_index() -> list[dict[str, Any]]:
    """Text corpus for the semantic index: id + cleaned name/description."""
    rows = query(
        """SELECT project_id, project_name AS name, project_description AS descr
             FROM project
            WHERE project_deleted = 0"""
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        name = _clean_text(r["name"] or "")
        descr = _clean_text(r["descr"] or "")
        text = f"{name}. {descr}".strip()
        if text and text != ".":
            out.append({"project_id": r["project_id"], "text": text})
    return out


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
    return _deep_clean(p)


def list_person_projects(
    name_or_id: str | int,
    limit: int = 25,
    since_days: int | None = None,
) -> dict[str, Any]:
    """A person's projects, ordered by most recent activity (when they logged time).

    ``since_days``: if set, only include projects the person logged time on within
    the last N days, and window the hours/entries to that period (so "last 7 days"
    -> since_days=7). Each project includes ``last_worked`` (date of their most
    recent time entry) and ``date`` (the project's creation date).
    """
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
    # Time window: relative to wall-clock now (in prod this tracks the live clock;
    # for a fresh snapshot the latest activity is ~now). Filtering on timing_end
    # both selects projects worked in the window and windows the hours/entries.
    params: list[Any] = [uid, uid]
    window_clause = ""
    cutoff: int | None = None
    if since_days is not None:
        cutoff = int(_now() - int(since_days) * 86400)
        window_clause = "AND t.timing_end >= %s"
        params.append(cutoff)
    params.append(int(limit))

    projects = query(
        f"""SELECT p.project_id,
                   p.project_name    AS name,
                   c.client_name     AS client,
                   {_DISCIPLINE_SQL} AS discipline,
                   p.project_date    AS date_ts,
                   COUNT(*)          AS time_entries,
                   SUM(GREATEST(t.timing_end - t.timing_start, 0)) AS seconds,
                   MAX(t.timing_end) AS last_ts,
                   (p.project_users_responsable = %s) AS is_lead
              FROM timing t
              JOIN project p ON p.project_id = t.timing_project
              LEFT JOIN client c ON c.client_id = p.project_client
             WHERE t.timing_user = %s AND p.project_deleted = 0
                   {window_clause}
             GROUP BY p.project_id, p.project_name, c.client_name, p.project_date,
                      p.project_users_responsable
             ORDER BY last_ts DESC
             LIMIT %s""",
        params,
    )
    for r in projects:
        r["date"] = _iso(r.pop("date_ts"))
        r["last_worked"] = _iso(r.pop("last_ts"))
        r["hours"] = _hours(r.pop("seconds"))
        r["is_lead"] = bool(r["is_lead"])
    result: dict[str, Any] = {
        "person": {
            "user_id": person["user_id"],
            "name": person["user_name"],
            "email": person.get("user_email"),
        },
        "projects": projects,
    }
    if since_days is not None:
        result["window_days"] = int(since_days)
        result["since"] = _iso(cutoff)
    return _deep_clean(result)
