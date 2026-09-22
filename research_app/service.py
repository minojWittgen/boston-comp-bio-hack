"""Thin execution adapter around the team's coordinator; no scientific logic here."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from coordinator.engine import Coordinator
from coordinator.evidence import DirectoryEvidenceProvider
from coordinator.jobs import TERMINAL
from coordinator.models import InvestigationRequest, Submission
from coordinator.planner import ExplicitPlanner
from coordinator.runtime import build_coordinator

EXAMPLES = Path(__file__).resolve().parents[1] / "coordinator" / "examples"
DemoName = Literal["missing-evidence", "cross-context-conflict"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=5, max_length=4000)
    previous_investigation_id: str | None = None


class DemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    demo: DemoName


def demo_submission(name: DemoName) -> Submission:
    if name not in ("missing-evidence", "cross-context-conflict"):
        raise ValueError("Unknown demonstration")
    return Submission.model_validate_json((EXAMPLES / f"{name}.json").read_text())


def demo_coordinator(store):
    return Coordinator(ExplicitPlanner(), DirectoryEvidenceProvider(EXAMPLES / "packages"), store)


class RunService:
    def __init__(self, coordinator=None, dispatch=None, refresh=None):
        self.coordinator = coordinator or build_coordinator()
        self.cloud_dispatch = dispatch
        self.refresh = refresh
        self.executor = None if dispatch else ThreadPoolExecutor(max_workers=4, thread_name_prefix="investigation")
        self.futures = {}
        self.lock = Lock()

    def dispatch(self, run_id, submission, demo=None):
        if self.cloud_dispatch:
            return self.cloud_dispatch(run_id, submission, demo)
        engine = demo_coordinator(self.coordinator.store) if demo else self.coordinator
        future = self.executor.submit(engine.execute, run_id, submission)
        with self.lock:
            self.futures[run_id] = future
        def finished(_):
            with self.lock:
                self.futures.pop(run_id, None)
        future.add_done_callback(finished)

    def start(self, submission, demo=None):
        state = self.coordinator.create(submission)
        try:
            self.dispatch(state.run_id, submission, demo)
        except Exception:
            state.status, state.stage = "failed", "dispatch_failed"
            state.error = "Could not schedule the investigation"
            self.coordinator.store.save(state)
            raise RuntimeError(state.error) from None
        return {"run_id": state.run_id, "status": "queued", "status_url": f"/investigations/{state.run_id}"}

    def get(self, run_id):
        state = self.coordinator.store.get(run_id)
        return self.refresh(state) if self.refresh else state

    def chat(self, message: ChatMessage):
        question = message.prompt
        if message.previous_investigation_id:
            parent = self.get(message.previous_investigation_id)
            if parent.status not in TERMINAL:
                raise ValueError("Wait for the current investigation to finish before replying.")
            # Only researcher-authored intent goes back to the planner; never its evidence or conclusions.
            question = f"{parent.request.question}\n\nResearcher clarification: {message.prompt}"
        submission = Submission(request=InvestigationRequest(question=question))
        return self.start(submission)

    def demo(self, request: DemoRequest):
        return self.start(demo_submission(request.demo), demo=request.demo)

    def close(self):
        if self.executor:
            with self.lock:
                pending = list(self.futures.items())
            for run_id, future in pending:
                if future.cancel():
                    state = self.coordinator.store.get(run_id)
                    state.status, state.stage = "failed", "worker_stopped"
                    state.error = "Local server stopped before this job could start"
                    self.coordinator.store.save(state)
            self.executor.shutdown(wait=False, cancel_futures=True)
