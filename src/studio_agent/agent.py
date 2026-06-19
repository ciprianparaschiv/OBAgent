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
import json
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
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "studio_agent.mcp_server"]
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


async def run(question: str, *, verbose: bool = True) -> str:
    """Answer a plain-language question using the model + PMS tools."""
    client = make_client()
    model = model_name()

    async with connect_tools() as tools:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
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
