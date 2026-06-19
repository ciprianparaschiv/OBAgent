"""Local backend for the browser UI.

Read-only and meant to run on YOUR machine: it reads the local PMS snapshot, so
the data never leaves the box (per CLAUDE.md). The UI itself (docs/index.html)
can be opened locally here or served from a hosted git URL pointing back at this
local API — hence CORS is open (the API is read-only and local-only).

Run:  studio-web            (-> http://127.0.0.1:8000)
      python -m studio_agent.web
"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .agent import run as agent_run
from .llm import model_name

# Single source of truth for the UI — same file GitHub Pages would serve.
_INDEX = Path(__file__).resolve().parents[2] / "docs" / "index.html"

app = FastAPI(title="Studio Staffing Agent (local, read-only)")

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


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX.read_text(encoding="utf-8")


@app.get("/config")
def config() -> JSONResponse:
    """Lightweight probe the UI uses to confirm the backend and show the model."""
    return JSONResponse({"ok": True, "model": model_name()})


@app.post("/ask")
async def ask(body: Ask) -> JSONResponse:
    trace: list[dict] = []
    try:
        answer = await agent_run(body.question, verbose=False, trace=trace)
        return JSONResponse({"answer": answer, "trace": trace})
    except Exception as exc:  # noqa: BLE001 - surface any error to the UI
        return JSONResponse({"error": str(exc)}, status_code=500)


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
