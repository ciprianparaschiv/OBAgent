"""Minimal agent loop: an OpenAI-compatible model + the PMS MCP tools.

This is deliberately a thin, replaceable shell (per CLAUDE.md):
  * the model is reached via the provider-agnostic client in ``llm``;
  * the data tools come from our MCP server, discovered at runtime;
  * the staffing/reasoning instructions live in SYSTEM_PROMPT.

Swapping the agent framework or the model provider should not require touching
the connector or the repository.

Run:  studio-agent "what past projects are like X and who worked on them?"
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .llm import make_client, model_name

SYSTEM_PROMPT = """\
You are a read-only staffing assistant for a design/development studio. You help \
people understand past project history and suggest who has relevant experience. \
You only observe and advise; a human makes every decision.

Answer ONLY from the PMS tools provided — never invent projects, people, clients, \
or hours. If the tools return nothing, say so.

To answer "what past projects are similar to X and who worked on them":
  1. Call search_projects with the key terms from X.
  2. For the most relevant matches, call get_project to see who logged time (and \
the lead).
  3. Summarise the closest projects with their client, date and discipline, and \
list the people who worked on them (with hours where useful). Reference projects \
by name and id.

For recency questions ("what has X worked on lately / in the last week / this \
month"), call list_person_projects with since_days (7 = last week, 30 = last \
month); it returns only projects worked in that window, ordered by most recent \
activity, with a last_worked date. State the window you used.

For "what projects were created today / this week / this month" or "what's new \
for client X", call list_recent_projects with days (today = 1, week = 7, month = \
30) and an optional client filter. These are projects by creation date (newest \
first); people_count is how many have logged time so far (often 0 if brand new).

For staffing questions ("who should we put on this", "who's best for <brief>", \
"recommend people for …"), call recommend_staffing with the brief. Present the \
ranked people with their evidence (the similar projects, hours). ALWAYS add that \
this is based on past experience only and does NOT account for availability or \
leave — a human makes the final call.

If a person's name is ambiguous, the tool returns candidates — pick the most \
likely or ask which one. Keep answers concise and grounded in the data."""

MAX_STEPS = 6


# --------------------------------------------------------------------------- #
# MCP tool bridge
# --------------------------------------------------------------------------- #


class MCPTools:
    """Discovers the PMS MCP tools and adapts them to OpenAI tool-calling."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session
        self._openai_tools: list[dict[str, Any]] = []

    async def load(self) -> None:
        listed = await self.session.list_tools()
        self._openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                },
            }
            for t in listed.tools
        ]

    @property
    def openai_tools(self) -> list[dict[str, Any]]:
        return self._openai_tools

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        res = await self.session.call_tool(name, arguments)
        return json.dumps(_normalise(res), default=str, ensure_ascii=False)


def _normalise(res: Any) -> Any:
    """Flatten an MCP CallToolResult into plain JSON data.

    FastMCP wraps some returns as ``{"result": ...}``; unwrap that. Fall back to
    the text content blocks if there's no structured content.
    """
    sc = getattr(res, "structuredContent", None)
    if isinstance(sc, dict):
        if set(sc.keys()) == {"result"}:
            return sc["result"]
        return sc
    blocks = [json.loads(c.text) for c in res.content if getattr(c, "text", None)]
    return blocks if len(blocks) != 1 else blocks[0]


@asynccontextmanager
async def connect_tools():
    """Spawn the PMS MCP server over stdio and yield a ready MCPTools."""
    # Pass our full environment so the subprocess uses the same profile
    # (STUDIO_ENV_FILE), DB creds, etc. — otherwise stdio defaults to a minimal
    # env and the MCP server would silently fall back to the snapshot .env.
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "studio_agent.mcp_server"],
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = MCPTools(session)
            await tools.load()
            yield tools


# --------------------------------------------------------------------------- #
# agent loop
# --------------------------------------------------------------------------- #


async def run(
    question: str,
    *,
    verbose: bool = True,
    trace: list[dict[str, Any]] | None = None,
) -> str:
    """Answer a plain-language question using the model + PMS tools.

    If ``trace`` is provided, each tool call is appended as
    ``{"tool": name, "args": {...}}`` (handy for surfacing in a UI).
    """
    client = make_client()
    model = model_name()

    today = _dt.datetime.now().strftime("%Y-%m-%d")
    async with connect_tools() as tools:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nToday's date is {today}."},
            {"role": "user", "content": question},
        ]

        for _ in range(MAX_STEPS):
            # The OpenAI SDK is synchronous; keep the event loop free.
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model=model,
                messages=messages,
                tools=tools.openai_tools,
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                return msg.content or ""

            # Record the assistant turn (with its tool calls) verbatim.
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )

            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments or "{}")
                if verbose:
                    print(f"  → {tc.function.name}({json.dumps(args)})", file=sys.stderr)
                if trace is not None:
                    trace.append({"tool": tc.function.name, "args": args})
                result = await tools.call(tc.function.name, args)
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )

        return "Stopped after too many tool steps without a final answer."


def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print('Usage: studio-agent "your question"', file=sys.stderr)
        raise SystemExit(2)
    print(asyncio.run(run(question)))


if __name__ == "__main__":
    main()
