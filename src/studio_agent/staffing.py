"""Two-tier staffing for an incoming brief.

  * main      — the Romanian person already on this task (from the comment
                authors), matched to the task's current discipline.
  * secondary — experienced RO alternatives who could take it over.

Discipline is the model's read of the thread (design may have become development);
"who already responded" is matched deterministically from comment authors. The
Notion assignee is the AU owner and is never a pick here.
"""

from __future__ import annotations

from typing import Any

from . import analysis
from . import repository as repo


def triage_brief(
    brief: dict[str, Any], comments: list[dict[str, Any]], top_k: int = 5
) -> dict[str, Any]:
    board_discipline = brief.get("discipline")
    title = brief.get("title", "")
    discipline = analysis.infer_discipline(title, board_discipline, comments) or board_discipline

    people = repo.active_people_by_name()

    # RO responders = comment authors who are our people, ordered by how much
    # they've engaged (number of comments), then first-seen.
    counts: dict[str, int] = {}
    order: list[str] = []
    for c in comments or []:
        key = repo._norm_name(c.get("author"))
        if key in people:
            counts[key] = counts.get(key, 0) + 1
            if key not in order:
                order.append(key)
    responders = [
        people[k] for k in sorted(counts, key=lambda k: (-counts[k], order.index(k)))
    ]

    # Main = responders whose discipline matches the task's current discipline.
    # (If it has moved to development but only a designer responded, main is empty
    # and we lean on the secondary developers.)
    main = [p for p in responders if not discipline or p["discipline"] == discipline]
    main_ids = {p["user_id"] for p in main}

    rec = repo.recommend_staffing(
        brief.get("brief_text") or title, top_k=top_k + len(main_ids), discipline=discipline
    )
    secondary = [c for c in rec["candidates"] if c["user_id"] not in main_ids][:top_k]

    return {
        "discipline": discipline,
        "main": [{"name": p["name"], "role": p["role"]} for p in main],
        "secondary": [{"name": c["name"], "role": c.get("role")} for c in secondary],
    }
