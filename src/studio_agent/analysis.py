"""Message-meaning inference via the model (provider-agnostic).

The one place we deliberately use the LLM for judgment: reading a task's comment
thread to decide its CURRENT discipline. A task can start as design and move to
development once designs are approved and need building — that's a meaning call,
not a keyword match, so the model does it.

Runs in the watcher, only when a thread changes (cached upstream). On quota
exhaustion (Gemini free tier) it falls back to the board discipline and records a
message so the UI can surface it.
"""

from __future__ import annotations

from typing import Any

from .llm import make_client, model_name

# Module-level quota state, surfaced to the UI.
_quota = {"exceeded": False, "message": None}


def quota_status() -> dict[str, Any]:
    return dict(_quota)


def reset_quota() -> None:
    """Optimistically clear the flag (call once per poll) so we retry after a
    possible reset, while still short-circuiting within a poll once we 429."""
    _quota["exceeded"] = False


def _is_quota_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    s = str(exc).lower()
    return "ratelimit" in name or "429" in s or "quota" in s or "resource_exhausted" in s


def infer_discipline(
    title: str, board_discipline: str | None, comments: list[dict[str, Any]]
) -> str | None:
    """Current discipline ("design"|"development") from the thread's meaning.

    Falls back to ``board_discipline`` if the model is unsure, errors, or the
    free-tier quota is exhausted (the latter also sets quota_status()).
    """
    # Already over quota this poll → don't keep hammering; use the board value.
    if _quota["exceeded"]:
        return board_discipline

    thread = "\n".join(
        f"- {c.get('author') or '?'}: {(c.get('text') or '')[:300]}"
        for c in (comments or [])[-12:]
    )
    prompt = (
        f"Task title: {title}\n"
        f"Initial discipline (from the board it was filed under): "
        f"{board_discipline or 'unknown'}\n"
        f"Comment thread (oldest to newest):\n{thread or '(no comments yet)'}\n\n"
        "A task can start as DESIGN and later become DEVELOPMENT once the designs "
        "are approved and need to be built/coded. Based on what the conversation "
        "is asking for RIGHT NOW, what is the current discipline?\n"
        "Answer with exactly one word: design or development."
    )
    try:
        client = make_client()
        resp = client.chat.completions.create(
            model=model_name(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        _quota["exceeded"] = False
        _quota["message"] = None
        ans = (resp.choices[0].message.content or "").strip().lower()
        if "develop" in ans:
            return "development"
        if "design" in ans:
            return "design"
        return board_discipline
    except Exception as exc:  # noqa: BLE001
        if _is_quota_error(exc):
            _quota["exceeded"] = True
            _quota["message"] = (
                "AI message analysis paused — Gemini free-tier quota reached; "
                "using the board's discipline until it resets."
            )
        return board_discipline
