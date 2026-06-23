"""Local backend for the browser UI.

Read-only and meant to run on YOUR machine: it reads the local PMS snapshot, so
the data never leaves the box (per CLAUDE.md). The UI itself (docs/index.html)
can be opened locally here or served from a hosted git URL pointing back at this
local API — hence CORS is open (the API is read-only and local-only).

Run:  studio-web            (-> http://127.0.0.1:8000)
      python -m studio_agent.web
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
import os
import secrets
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from . import analysis, notion, staffing
from .agent import run as agent_run
from .config import web_auth
from .llm import model_name

# Single source of truth for the UI — same file GitHub Pages would serve.
_INDEX = Path(__file__).resolve().parents[2] / "docs" / "index.html"


# --------------------------------------------------------------------------- #
# Incoming-brief watcher (read-only): polls Notion, pre-computes staffing.
# It only READS Notion + PMS and caches suggestions in memory — nothing is
# written or sent anywhere. Runs while the backend is up (hosting TBD).
# --------------------------------------------------------------------------- #

_triage: dict[str, dict] = {}
_watch = {"last_run": None, "last_error": None, "enabled": False, "ai_quota": None}

# Max briefs to (re)analyse with the LLM per poll, so a cold start doesn't burst
# the whole free-tier quota at once; the rest are picked up on later polls.
_MAX_AI_PER_POLL = 8


def _now_str() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


async def _poll_once(top_k: int = 3) -> None:
    """One read-only sweep: changed briefs -> two-tier staffing, cached.

    Per changed brief: read the thread, infer current discipline (LLM), and split
    into main (RO person already on it) + secondary (could take over).
    """
    analysis.reset_quota()  # retry once per poll; short-circuits after a 429
    briefs = await asyncio.to_thread(notion.list_incoming_briefs, 25)
    current = set()
    processed = 0
    for b in briefs:
        current.add(b["id"])
        cached = _triage.get(b["id"])
        if (
            cached
            and cached["brief"].get("status") == b.get("status")
            and cached["brief"].get("last_edited") == b.get("last_edited")
            and cached["brief"].get("messages") == b.get("messages")
        ):
            continue  # already triaged; status, last-edited and messages unchanged
        if processed >= _MAX_AI_PER_POLL:
            continue  # leave for a later poll (don't cache) to spread LLM/quota load
        processed += 1
        full = await asyncio.to_thread(notion.get_brief, b["id"])
        comments = (full or {}).get("comments") or []
        tri = await asyncio.to_thread(staffing.triage_brief, full or b, comments, top_k)
        _triage[b["id"]] = {
            "brief": b,
            "discipline": tri["discipline"],
            "main": tri["main"],
            "secondary": tri["secondary"],
            "computed_at": _now_str(),
        }
    for gone in set(_triage) - current:  # drop briefs no longer on the boards
        _triage.pop(gone, None)
    _watch["last_run"] = _now_str()
    _watch["ai_quota"] = analysis.quota_status()


async def _watch_loop(interval: int) -> None:
    while True:
        try:
            await _poll_once()
            _watch["last_error"] = None
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            _watch["last_error"] = str(exc)
        await asyncio.sleep(interval)


@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    task = None
    if notion.available():
        _watch["enabled"] = True
        interval = int(os.getenv("WATCH_INTERVAL_SECONDS", "300"))
        task = asyncio.create_task(_watch_loop(interval))
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Studio Staffing Agent (local, read-only)", lifespan=_lifespan)

# Open CORS: the API is read-only and bound to localhost; the page may be served
# from a hosted git URL (e.g. github.io) and still call back to this local API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Ask(BaseModel):
    question: str


_basic = HTTPBasic(auto_error=False)


def require_auth(creds: HTTPBasicCredentials | None = Depends(_basic)) -> None:
    """Enforce HTTP Basic Auth when WEB_AUTH_* is configured; no-op otherwise.

    Protects the data endpoints. The page (which holds no data) stays open so the
    login form can load; everything that touches the DB requires credentials.
    """
    expected = web_auth()
    if not expected:
        return
    user, pw = expected
    ok = creds is not None and secrets.compare_digest(
        creds.username, user
    ) and secrets.compare_digest(creds.password, pw)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX.read_text(encoding="utf-8")


@app.get("/config")
def config(_: None = Depends(require_auth)) -> JSONResponse:
    """Probe the UI uses to confirm the backend, auth, and show the model."""
    return JSONResponse({"ok": True, "model": model_name()})


@app.post("/ask")
async def ask(body: Ask, _: None = Depends(require_auth)) -> JSONResponse:
    trace: list[dict] = []
    try:
        answer = await agent_run(body.question, verbose=False, trace=trace)
        return JSONResponse({"answer": answer, "trace": trace})
    except Exception as exc:  # noqa: BLE001 - surface any error to the UI
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/incoming")
def incoming(_: None = Depends(require_auth)) -> JSONResponse:
    """The watcher's current triage: incoming briefs with pre-computed staffing."""
    items = sorted(
        _triage.values(), key=lambda x: x["brief"].get("created") or "", reverse=True
    )
    return JSONResponse(
        {
            "watching": _watch["enabled"],
            "last_run": _watch["last_run"],
            "error": _watch["last_error"],
            "ai_quota": _watch["ai_quota"],
            "count": len(items),
            "briefs": items,
        }
    )


@app.post("/incoming/refresh")
async def incoming_refresh(_: None = Depends(require_auth)) -> JSONResponse:
    """Force an immediate read-only poll (handy for testing/triage on demand)."""
    if not notion.available():
        return JSONResponse({"ok": False, "error": "Notion not configured."})
    try:
        await _poll_once()
        return JSONResponse({"ok": True, "count": len(_triage), "last_run": _watch["last_run"]})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
