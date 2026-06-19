"""Integration tests for the PMS repository against the local snapshot."""

from studio_agent import repository as repo


def test_search_projects_scored_and_relevant():
    rows = repo.search_projects("landing page", limit=5)
    assert rows, "expected matches for 'landing page'"
    assert all("score" in r and r["score"] > 0 for r in rows)
    # Results should mention the query terms somewhere in the name (lexical).
    assert any("landing" in (r["name"] or "").lower() for r in rows)
    # Ordered by score descending.
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_search_empty_query_returns_nothing():
    assert repo.search_projects("   ") == []


def test_get_project_includes_people_and_lead():
    hit = repo.search_projects("landing page", limit=1)[0]
    proj = repo.get_project(hit["project_id"])
    assert proj is not None
    assert proj["project_id"] == hit["project_id"]
    assert "people" in proj and isinstance(proj["people"], list)
    # Everyone who worked has a non-negative hours figure.
    assert all(p["hours"] >= 0 for p in proj["people"])


def test_get_project_unknown_id_returns_none():
    assert repo.get_project(999_999_999) is None


def test_list_person_projects_by_id():
    # user 35 (Radu Manastireanu) is known to have logged time.
    res = repo.list_person_projects(35)
    assert res["person"] and res["person"]["user_id"] == 35
    assert res["projects"], "expected past projects for user 35"
    assert all("hours" in p and "is_lead" in p for p in res["projects"])


def test_ambiguous_person_returns_candidates():
    res = repo.list_person_projects("Radu")
    assert res["person"] is None
    assert len(res["candidates"]) > 1
    assert all("user_id" in c and "name" in c for c in res["candidates"])


def test_resolve_person_exact_name_wins():
    p = repo.resolve_person("Radu Manastireanu")
    assert p is not None and p["user_id"] == 35


def test_latin1_text_decodes_to_unicode():
    # project 13449 stores a cp1252 right single quote; must come back as U+2019.
    proj = repo.get_project(13449)
    assert proj is not None
    assert "’" in proj["name"], f"expected smart quote in {proj['name']!r}"


def test_double_encoded_text_is_repaired():
    # Newer [RO] rows are UTF-8 stored into latin1 ("Levi’s" -> "Leviâ€™s").
    # The repository should repair the mojibake on the way out.
    rows = repo.search_projects("Levi Campaign Email", limit=10)
    assert rows, "expected Levi campaign email projects"
    joined = " ".join(r["name"] for r in rows)
    assert "â€" not in joined, f"mojibake leaked through: {joined!r}"
    assert any("Levi’s" in r["name"] for r in rows)
