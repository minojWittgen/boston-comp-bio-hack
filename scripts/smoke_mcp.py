"""Exercise a real remote MCP connection with clearly synthetic development data."""
import asyncio
import json
import os
from pathlib import Path
import sys

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp/"
    token = os.environ.get("INVESTIGATION_API_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = json.loads((Path(__file__).resolve().parents[1] / "examples/development-investigation.json").read_text())
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with Client(streamable_http_client(url, http_client=http)) as client:
            tools = await client.list_tools()
            print("Tools:", ", ".join(t.name for t in tools.tools))
            start = await client.call_tool("start_investigation", {"request": request})
            if start.is_error:
                raise RuntimeError(str(start.content))
            run_id = start.structured_content["id"]
            print("Investigation:", run_id)
            for _ in range(80):
                result = await client.call_tool("get_investigation", {"investigation_id": run_id})
                if result.is_error:
                    raise RuntimeError(str(result.content))
                state = result.structured_content
                if state["status"] in ("complete", "partial", "failed", "needs_input"):
                    print(json.dumps({"status": state["status"], "contexts": state["report"].get("contexts"), "errors": state["errors"]}, indent=2))
                    if state["status"] != "complete":
                        raise RuntimeError("Synthetic investigation did not complete; inspect the reported errors.")
                    return
                await asyncio.sleep(3)
            raise TimeoutError("Investigation did not finish within the client polling limit.")


if __name__ == "__main__":
    asyncio.run(main())
