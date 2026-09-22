"""Small frontend API. Modal and local development share this route implementation."""
from __future__ import annotations

import os
import secrets
from collections.abc import Callable

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .models import RunState, Submission
from .runtime import build_coordinator


def create_app(coordinator=None, dispatch: Callable | None = None, api_token: str | None = None,
               refresh: Callable | None = None):
    coordinator = coordinator or build_coordinator()
    token = api_token if api_token is not None else os.environ.get("COORDINATOR_API_TOKEN")
    app = FastAPI(title="Cross-context investigation coordinator", version="0.1.0")
    origins = os.environ.get("XCTX_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    app.add_middleware(CORSMiddleware, allow_origins=origins.split(","),
        allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

    def authorize(authorization: str | None = Header(default=None)):
        if token and not secrets.compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
            raise HTTPException(401, "Invalid coordinator token")

    def read_run(run_id: str):
        try:
            state = coordinator.store.get(run_id)
            return refresh(state) if refresh else state
        except (KeyError, ValueError):
            raise HTTPException(404, "Investigation not found") from None

    @app.get("/health")
    def health():
        return {"status": "ok", "schema_version": "0.1"}

    @app.post("/investigations", status_code=202, dependencies=[Depends(authorize)])
    def start(submission: Submission, background: BackgroundTasks):
        state = coordinator.create(submission)
        if dispatch:
            try:
                dispatch(state.run_id, submission)
            except Exception:
                state.status, state.stage = "failed", "dispatch_failed"
                state.error = "Could not schedule the investigation"
                coordinator.store.save(state)
                raise HTTPException(503, "Could not schedule the investigation") from None
        else:
            background.add_task(coordinator.execute, state.run_id, submission)
        return {"run_id": state.run_id, "status": "queued",
                "status_url": f"/investigations/{state.run_id}"}

    @app.get("/investigations/{run_id}", response_model=RunState, dependencies=[Depends(authorize)])
    def get_run(run_id: str):
        return read_run(run_id)

    @app.get("/investigations/{run_id}/report", response_class=PlainTextResponse,
             dependencies=[Depends(authorize)])
    def get_report(run_id: str):
        state = read_run(run_id)
        if state.report is None:
            raise HTTPException(409, "No report is available; inspect the investigation status")
        return state.report

    return app
