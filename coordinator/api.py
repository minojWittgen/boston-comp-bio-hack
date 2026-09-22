"""HTTP and MCP adapters share the exact same start/get service."""
from contextlib import asynccontextmanager
import hmac
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from mcp.server import MCPServer

from coordinator.models import InvestigationRequest


def create_app(service, token=None):
    token = os.environ.get("INVESTIGATION_API_TOKEN", "") if token is None else token
    mcp = MCPServer("cross-context-investigator", instructions=
        "Start a bounded biological investigation and poll its ID. Supply researcher-confirmed scientific criteria. "
        "A needs_input result requires a new request with confirmed criteria, not invented thresholds. "
        "Distinguish execution status from scientific findings; synthetic fixtures are not real biological evidence.")

    @mcp.tool(description="Start the shared coordinator in the background; returns an investigation ID immediately. "
              "Uses the same service as POST /investigations. Research criteria are immutable after submission. "
              "If criteria are absent or unconfirmed, the run stops as needs_input without analysis. "
              "Processed observations and sample maps are optional; missing contexts remain explicit gaps.", structured_output=True)
    async def start_investigation(request: InvestigationRequest) -> dict[str, Any]:
        return await service.start(request)

    @mcp.tool(description="Get progress, action trace, checked findings, evidence and terminal status for an investigation ID. "
              "Poll no faster than every 3 seconds. Terminal states: complete, partial, failed, needs_input. "
              "Complete execution can have inconclusive findings. Source retrieval alone does not validate a claim.", structured_output=True)
    async def get_investigation(investigation_id: str) -> dict[str, Any]:
        try:
            return await service.get(investigation_id)
        except KeyError:
            raise ValueError("Unknown or expired investigation") from None

    mcp_app = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                    json_response=True, host="0.0.0.0", max_request_body_size=2 * 1024 * 1024)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield
        if hasattr(service, "close"):
            await service.close()

    app = FastAPI(title="Cross-context investigation service", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def access(request: Request, call_next):
        if request.url.path != "/health":
            if token and not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
                return JSONResponse({"detail": "A valid investigation access token is required."}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            if request.method == "POST":
                content = await request.body()
                if len(content) > 2 * 1024 * 1024:
                    return JSONResponse({"detail": "Request exceeds 2 MB."}, status_code=413)
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "cross-context-investigator", "schema_version": "1.0"}

    @app.post("/investigations", status_code=202)
    async def start(request: InvestigationRequest):
        return await service.start(request)

    @app.get("/investigations/{run_id}")
    async def get(run_id: str):
        try:
            return await service.get(run_id)
        except KeyError:
            raise HTTPException(404, "Unknown or expired investigation") from None

    app.mount("/mcp", mcp_app)
    app.state.mcp = mcp
    return app


def local_app():
    from coordinator.service import local_service
    return create_app(local_service())
