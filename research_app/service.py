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
from research_app.planning import plan_with_credentials, public_coordinator, with_prepared_plan

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
    def __init__(self, coordinator=None, dispatch=None, refresh=None, plan_chat=None, budget=None):
        self.coordinator = coordinator or public_coordinator()
        self.plan_chat = plan_chat or plan_with_credentials
        self.budget = budget
        self.cloud_dispatch = dispatch
        self.refresh = refresh
        self.executor = None if dispatch else ThreadPoolExecutor(max_workers=4, thread_name_prefix="investigation")
        self.futures = {}
        self.lock = Lock()

    def dispatch(self, run_id, submission, demo=None, plan=None):
        if self.cloud_dispatch:
            return self.cloud_dispatch(run_id, submission, demo, plan)
        engine = demo_coordinator(self.coordinator.store) if demo else self.coordinator
        if plan is not None:
            engine = with_prepared_plan(engine, submission.request, plan)
        future = self.executor.submit(engine.execute, run_id, submission)
        with self.lock:
            self.futures[run_id] = future
        def finished(_):
            with self.lock:
                self.futures.pop(run_id, None)
        future.add_done_callback(finished)

    def start(self, submission, demo=None, plan=None):
        if plan is None and not submission.request.requirements:
            raise ValueError("Supply explicit research requirements for model-free HTTP/MCP use, or use website chat with your own model key.")
        if plan is None:
            ExplicitPlanner().plan(submission.request)
        if self.budget:
            self.budget.reserve()
        state = self.coordinator.create(submission)
        try:
            self.dispatch(state.run_id, submission, demo, plan)
        except Exception:
            state.status, state.stage = "failed", "dispatch_failed"
            state.error = "Could not schedule the investigation"
            self.coordinator.store.save(state)
            raise RuntimeError(state.error) from None
        return {"run_id": state.run_id, "status": "queued", "status_url": f"/investigations/{state.run_id}"}

    def get(self, run_id):
        from research_app.tutorials import tutorial_for_id
        example = tutorial_for_id(run_id)
        if example is not None:
            return example
        state = self.coordinator.store.get(run_id)
        return self.refresh(state) if self.refresh else state

    def chat(self, message: ChatMessage, credentials=None):
        question = message.prompt
        if message.previous_investigation_id:
            parent = self.get(message.previous_investigation_id)
            if parent.status not in TERMINAL:
                raise ValueError("Wait for the current investigation to finish before replying.")
            # Only researcher-authored intent goes back to the planner; never its evidence or conclusions.
            question = f"{parent.request.question}\n\nResearcher clarification: {message.prompt}"
        submission = Submission(request=InvestigationRequest(question=question))
        if self.budget:
            self.budget.check()
        # Planning finishes in this HTTP request; no secret is sent to a job or store.
        plan = self.plan_chat(submission.request, credentials)
        return self.start(submission, plan=plan)

    def demo(self, request: DemoRequest):
        from research_app.tutorials import tutorial
        state = tutorial(request.demo)
        return {"run_id": state.run_id, "status": state.status,
                "status_url": f"/investigations/{state.run_id}"}

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
