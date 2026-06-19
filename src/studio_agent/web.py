"""Minimal LOCAL web UI for testing the agent in a browser.

Read-only, runs on localhost only — the PMS data never leaves this machine
(per CLAUDE.md). It's a thin shell over ``agent.run`` exactly like the CLI.

Run:  studio-web            (-> http://127.0.0.1:8000)
      python -m studio_agent.web
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .agent import run as agent_run
from .llm import model_name

app = FastAPI(title="Studio Staffing Agent (local, read-only)")


class Ask(BaseModel):
    question: str


PAGE = """\
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Studio Staffing Agent — local</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 780px; margin: 2rem auto; padding: 0 1rem; }
  h1 { font-size: 1.25rem; margin-bottom: .25rem; }
  .sub { color: #888; margin-top: 0; font-size: .85rem; }
  textarea { width: 100%; box-sizing: border-box; padding: .7rem; border-radius: 8px;
             border: 1px solid #8884; font: inherit; min-height: 4.5rem; }
  button { margin-top: .6rem; padding: .55rem 1.1rem; border: 0; border-radius: 8px;
           background: #2d6cdf; color: #fff; font: inherit; cursor: pointer; }
  button[disabled] { opacity: .5; cursor: default; }
  .examples { margin: .6rem 0 0; font-size: .85rem; }
  .examples a { color: #2d6cdf; cursor: pointer; text-decoration: underline; display: block; }
  #answer { white-space: pre-wrap; background: #8881; border-radius: 8px; padding: 1rem;
            margin-top: 1.2rem; min-height: 2rem; }
  #trace { font-size: .8rem; color: #888; margin-top: .6rem; }
  .ro { font-size: .75rem; color: #999; border-top: 1px solid #8883; margin-top: 2rem; padding-top: .6rem; }
</style></head><body>
<h1>Studio Staffing Agent</h1>
<p class="sub">local · read-only · model: __MODEL__</p>

<textarea id="q" placeholder="Ask in plain language…"></textarea>
<div class="examples">
  <a onclick="setq(this)">What past projects are most similar to an email marketing newsletter design for a tech brand, and who worked on them?</a>
  <a onclick="setq(this)">Find landing page projects for Logitech and who worked on them</a>
  <a onclick="setq(this)">What has Floris Olaru worked on recently?</a>
</div>
<button id="go" onclick="ask()">Ask</button>

<div id="trace"></div>
<div id="answer"></div>
<p class="ro">Read-only. Answers come only from the local PMS snapshot; a human makes every decision.</p>

<script>
function setq(a){ document.getElementById('q').value = a.textContent; }
async function ask(){
  const q = document.getElementById('q').value.trim();
  if(!q) return;
  const btn = document.getElementById('go'), ans = document.getElementById('answer'), tr = document.getElementById('trace');
  btn.disabled = true; ans.textContent = ''; tr.textContent = 'thinking…';
  try {
    const r = await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({question:q})});
    const d = await r.json();
    if(d.error){ ans.textContent = 'Error: ' + d.error; tr.textContent=''; }
    else {
      tr.textContent = (d.trace && d.trace.length)
        ? 'tools: ' + d.trace.map(t => t.tool + '(' + JSON.stringify(t.args) + ')').join('  →  ')
        : 'no tools called';
      ans.textContent = d.answer || '(no answer)';
    }
  } catch(e){ ans.textContent = 'Request failed: ' + e; tr.textContent=''; }
  btn.disabled = false;
}
document.getElementById('q').addEventListener('keydown', e => {
  if((e.metaKey||e.ctrlKey) && e.key === 'Enter') ask();
});
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE.replace("__MODEL__", model_name())


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
