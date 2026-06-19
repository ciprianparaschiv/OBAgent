"""Deterministic proof of the phase-one slice, through the MCP server.

Runs the same tool pipeline the agent would drive — search_projects, then
get_project on the closest matches — and prints the similar past projects and
who worked on them. No model/API key required: this proves the data path and the
MCP layer. For the natural-language version, use:  studio-agent "..."

Usage:  python scripts/prove_slice.py ["a project brief in plain words"]
"""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DEFAULT_EXAMPLE = "a Meta ads landing page for a consumer health brand"


def _payload(res):
    sc = res.structuredContent
    if isinstance(sc, dict) and set(sc.keys()) == {"result"}:
        return sc["result"]
    return sc


async def main(example: str) -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "studio_agent.mcp_server"]
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            print(f'\nQ: "What past projects are most similar to: {example}"')
            print('   "and who worked on them?"\n')

            hits = _payload(await s.call_tool("search_projects", {"query": example, "limit": 5}))
            if not hits:
                print("No similar projects found.")
                return

            print(f"Top {len(hits)} similar past projects:\n")
            for h in hits:
                detail = _payload(await s.call_tool("get_project", {"project_id": h["project_id"]}))
                people = detail.get("people", []) if detail else []
                who = ", ".join(
                    f"{p['name']} ({p['hours']}h{', lead' if p['is_lead'] else ''})"
                    for p in people
                ) or "no logged time"
                print(f"• #{h['project_id']}  {h['name']}")
                print(f"    client: {h['client']}  |  {h['discipline']}  |  {h['date']}  |  match score {h['score']}")
                print(f"    worked on it: {who}\n")

            # Aggregate the people across the matches — the staffing signal.
            tally: dict[str, float] = {}
            for h in hits:
                detail = _payload(await s.call_tool("get_project", {"project_id": h["project_id"]}))
                for p in (detail.get("people", []) if detail else []):
                    tally[p["name"]] = tally.get(p["name"], 0.0) + p["hours"]
            ranked = sorted(tally.items(), key=lambda kv: kv[1], reverse=True)
            print("People with the most relevant experience (hours across these projects):")
            for name, hrs in ranked[:5]:
                print(f"   - {name}: {round(hrs,1)}h")


if __name__ == "__main__":
    example = " ".join(sys.argv[1:]).strip() or DEFAULT_EXAMPLE
    asyncio.run(main(example))
