"""Verify the canonical coordinator over a real MCP transport using an explicit fixture."""
import asyncio
import json
import os
import sys

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp/"
    token = os.environ.get("COORDINATOR_API_TOKEN") or os.environ.get("INVESTIGATION_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            listing = await client.list_tools()
            print("Tools:", ", ".join(t.name for t in listing.tools))
            start = await client.call_tool("start_investigation", {"request": {"demo": "cross-context-conflict"}})
            if start.is_error:
                raise RuntimeError(str(start.content))
            run_id = start.structured_content["run_id"]
            print("Investigation:", run_id)
            for _ in range(40):
                result = await client.call_tool("get_investigation", {"investigation_id": run_id})
                if result.is_error:
                    raise RuntimeError(str(result.content))
                state = result.structured_content
                if state["status"] in ("complete", "partial", "failed"):
                    conclusion = (state.get("assessment") or {}).get("conclusion")
                    print(json.dumps({"status": state["status"], "conclusion": conclusion, "error": state["error"]}, indent=2))
                    if (state["status"], conclusion) != ("complete", "conflicting"):
                        raise RuntimeError("Synthetic conflict fixture did not return the expected coordinator result")
                    return
                await asyncio.sleep(3)
            raise TimeoutError("Investigation did not finish within the polling limit")


if __name__ == "__main__":
    asyncio.run(main())
