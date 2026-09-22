"""Chat and MCP adapters added to the canonical coordinator HTTP application."""
from contextlib import asynccontextmanager
import hmac
import os
from typing import Any

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from mcp.server import MCPServer
from pydantic import ValidationError

from coordinator.api import create_app as coordinator_app
from coordinator.models import Submission
from research_app.service import ChatMessage, DemoRequest, RunService


def configured_token():
    return os.environ.get("COORDINATOR_API_TOKEN") or os.environ.get("INVESTIGATION_API_TOKEN", "")


def create_app(service=None, api_token=None):
    service = service or RunService()
    token = configured_token() if api_token is None else api_token
    app = coordinator_app(service.coordinator, dispatch=service.dispatch,
                          api_token=token, refresh=service.refresh)
    mcp = MCPServer("cross-context-investigator", instructions=
        "Start a research investigation and poll the returned run_id. Use a prompt, a nested Submission, or an "
        "explicit synthetic demo request. Research planning and checks use the same coordinator as the frontend. "
        "Execution status and assessment.conclusion are separate: complete can mean conflicting. "
        "Generated plan assumptions need researcher review. Reference records are background, not observations.")

    @mcp.tool(structured_output=True, description=
              "Start a background job. Pass {prompt, previous_investigation_id?}, a nested {request, observations} "
              "Submission, or {demo: 'missing-evidence' | 'cross-context-conflict'} for labeled synthetic fixtures. "
              "Returns run_id and status_url. A prompt is framed by the team's ClaudePlanner.")
    async def start_investigation(request: Submission | ChatMessage | DemoRequest) -> dict[str, Any]:
        handler = service.chat if isinstance(request, ChatMessage) else service.demo if isinstance(request, DemoRequest) else service.start
        return await run_in_threadpool(handler, request)

    @mcp.tool(structured_output=True, description=
              "Retrieve the canonical RunState, including plan, evidence, assessment, gaps, events and Markdown report. "
              "Poll at least three seconds apart until complete, partial or failed; inspect assessment.conclusion separately.")
    async def get_investigation(investigation_id: str) -> dict[str, Any]:
        try:
            return (await run_in_threadpool(service.get, investigation_id)).model_dump(mode="json")
        except (KeyError, ValueError):
            raise ValueError("Investigation not found") from None

    @asynccontextmanager
    async def lifespan(_):
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            service.close()

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def access(request: Request, call_next):
        if request.url.path != "/health":
            if token and not hmac.compare_digest(request.headers.get("authorization", "").encode(), f"Bearer {token}".encode()):
                return JSONResponse({"detail": "A valid team access code is required."}, status_code=401)
            if request.method == "POST" and len(await request.body()) > 2 * 1024 * 1024:
                return JSONResponse({"detail": "Request exceeds 2 MB."}, status_code=413)
        return await call_next(request)

    @app.post("/chat", status_code=202)
    def chat(message: ChatMessage):
        try:
            return service.chat(message)
        except ValidationError as exc:
            raise HTTPException(422, "The combined research question is too long; start a new conversation.") from exc
        except KeyError:
            raise HTTPException(404, "Previous investigation not found") from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        except RuntimeError:
            raise HTTPException(503, "Could not schedule the investigation") from None

    @app.post("/demos", status_code=202)
    def demo(request: DemoRequest):
        try:
            return service.demo(request)
        except RuntimeError:
            raise HTTPException(503, "Could not schedule the demonstration") from None

    app.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/", stateless_http=True,
              json_response=True, host="0.0.0.0", max_request_body_size=2 * 1024 * 1024))
    app.state.mcp = mcp
    app.state.service = service
    return app
