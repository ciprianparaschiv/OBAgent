"""Integration tests for the PMS repository against the local snapshot."""

import pytest

from studio_agent import index, repository as repo


def test_lexical_search_scored_and_relevant():
    rows = repo.search_projects("landing page", limit=5, mode="lexical")
    assert rows, "expected matches for 'landing page'"
    assert all("score" in r and r["score"] > 0 for r in rows)
    assert all(r["match"] == "lexical" for r in rows)
    # Results should mention the query terms somewhere in the name (lexical).
    assert any("landing" in (r["name"] or "").lower() for r in rows)
    # Ordered by score descending.
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_search_empty_query_returns_nothing():
    assert repo.search_projects("   ") == []


def test_get_project_includes_people_and_lead():
    hit = repo.search_projects("landing page", limit=1, mode="lexical")[0]
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


def test_person_projects_ordered_by_recent_activity_with_last_worked():
    res = repo.list_person_projects(37, limit=50)  # user 37 has logged time
    projects = res["projects"]
    assert projects and all(p.get("last_worked") for p in projects)
    last = [p["last_worked"] for p in projects]
    assert last == sorted(last, reverse=True), "should be ordered by most recent activity"


def test_person_projects_since_days_window(monkeypatch):
    # Pin "now" to the snapshot's latest activity so the window is deterministic
    # regardless of when the test runs.
    latest = repo.query_one("SELECT MAX(timing_end) AS m FROM timing")["m"]
    monkeypatch.setattr(repo, "_now", lambda: float(latest))

    all_projects = repo.list_person_projects(37, limit=50)["projects"]
    win = repo.list_person_projects(37, since_days=7)

    assert win["window_days"] == 7 and win["since"]
    assert len(win["projects"]) <= len(all_projects)
    # Every windowed project's most recent activity is within the window.
    assert all(p["last_worked"] >= win["since"] for p in win["projects"])


def test_double_encoded_text_is_repaired():
    # Newer [RO] rows are UTF-8 stored into latin1 ("Levi’s" -> "Leviâ€™s").
    # The repository should repair the mojibake on the way out.
    rows = repo.search_projects("Levi Campaign Email", limit=10, mode="lexical")
    assert rows, "expected Levi campaign email projects"
    joined = " ".join(r["name"] for r in rows)
    assert "â€" not in joined, f"mojibake leaked through: {joined!r}"
    assert any("Levi’s" in r["name"] for r in rows)


# --- semantic search (skipped unless the local index is built) -------------

needs_index = pytest.mark.skipif(not index.available(), reason="semantic index not built")


@needs_index
def test_semantic_search_returns_scored_matches():
    rows = repo.search_projects("email newsletter design", limit=5, mode="semantic")
    assert rows, "expected semantic matches"
    assert all(r["match"] == "semantic" for r in rows)
    assert all(0.0 <= r["score"] <= 1.0001 for r in rows)
    scores = [r["score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


@needs_index
def test_semantic_finds_without_shared_keywords():
    # "video ads for social media" should surface social-creative/video work
    # even though the wording differs from project names.
    rows = repo.search_projects("promotional video clips for social media", limit=10, mode="semantic")
    blob = " ".join((r["name"] or "").lower() for r in rows)
    assert any(w in blob for w in ("social", "video", "creative", "ad"))


def test_search_auto_falls_back_to_lexical_without_index(monkeypatch):
    monkeypatch.setattr(index, "available", lambda: False)
    rows = repo.search_projects("landing page", limit=3, mode="auto")
    assert rows and all(r["match"] == "lexical" for r in rows)


def test_list_recent_projects_window(monkeypatch):
    # Pin "now" just past the newest creation date so the window is deterministic.
    latest = repo.query_one(
        "SELECT MAX(project_date) AS m FROM project WHERE project_deleted=0"
    )["m"]
    monkeypatch.setattr(repo, "_now", lambda: float(latest) + 1)
    res = repo.list_recent_projects(days=7)
    assert res["days"] == 7 and res["since"]
    assert res["projects"], "expected recently-created projects"
    dates = [p["date"] for p in res["projects"]]
    assert dates == sorted(dates, reverse=True), "newest first"
    assert all(p["date"] >= res["since"] for p in res["projects"])


def test_list_recent_projects_client_filter(monkeypatch):
    latest = repo.query_one(
        "SELECT MAX(project_date) AS m FROM project WHERE project_deleted=0"
    )["m"]
    monkeypatch.setattr(repo, "_now", lambda: float(latest) + 1)
    res = repo.list_recent_projects(days=3650, client="Logitech", limit=10)
    assert res["projects"], "expected Logitech projects in a 10-year window"
    assert all("logitech" in (p["client"] or "").lower() for p in res["projects"])


def test_recommend_staffing_ranks_with_evidence():
    res = repo.recommend_staffing("email marketing newsletter design", top_k=5)
    cands = res["candidates"]
    assert cands, "expected staffing candidates"
    assert res["similar_projects_considered"] > 0
    assert "availability" in res["note"].lower()
    # Ranked by score descending.
    scores = [c["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)
    # Each candidate has evidence and the expected fields.
    for c in cands:
        assert c["evidence"], "each candidate should cite similar projects"
        assert {"user_id", "name", "relevant_hours", "matched_projects", "last_worked"} <= c.keys()
        assert c["relevant_hours"] >= 0


def test_recommend_staffing_only_active_people():
    res = repo.recommend_staffing("landing page development", top_k=10)
    ids = [c["user_id"] for c in res["candidates"]]
    if ids:
        placeholders = ",".join(["%s"] * len(ids))
        rows = repo.query(
            f"SELECT user_id FROM user WHERE user_id IN ({placeholders}) "
            f"AND user_active=1 AND user_deleted=0",
            ids,
        )
        assert {r["user_id"] for r in rows} == set(ids), "only active, non-deleted users"


# --- Notion incoming briefs (skipped unless NOTION_TOKEN is configured) -----

from studio_agent import notion  # noqa: E402

needs_notion = pytest.mark.skipif(not notion.available(), reason="NOTION_TOKEN not set")


@needs_notion
def test_list_incoming_briefs_shape():
    briefs = notion.list_incoming_briefs(limit=5)
    assert isinstance(briefs, list)
    for b in briefs:
        assert {"id", "title", "status", "url"} <= b.keys()


@needs_notion
def test_get_brief_assembles_text():
    briefs = notion.list_incoming_briefs(limit=1)
    if not briefs:
        pytest.skip("no briefs available")
    d = notion.get_brief(briefs[0]["id"])
    assert d and "brief_text" in d and d["title"]
