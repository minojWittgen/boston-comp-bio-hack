"""One bounded investigation, shared by CLI, HTTP, and the Modal worker."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

from .checks import assess
from .evidence import adapt_packages
from .models import EvidenceBundle, Gap, RunState, Submission


def plan_digest(plan) -> str:
    return hashlib.sha256(json.dumps(plan.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


class Coordinator:
    def __init__(self, planner, provider, store, budget_seconds: float = 240):
        self.planner, self.provider, self.store = planner, provider, store
        self.budget_seconds = budget_seconds

    def create(self, submission: Submission) -> RunState:
        state = RunState(run_id=uuid.uuid4().hex, request=submission.request)
        self.store.save(state)
        return state

    def _event(self, state, stage, **detail):
        state.stage = stage
        state.events.append({"stage": stage, "at": datetime.now(timezone.utc).isoformat(), **detail})
        self.store.save(state)

    def execute(self, run_id: str, submission: Submission) -> RunState:
        state = self.store.get(run_id)
        if state.status != "queued":
            return state
        started = time.monotonic()
        try:
            if state.request != submission.request:
                raise ValueError("Submission does not match the queued request")
            state.status = "running"
            self._event(state, "intent_and_criteria")
            state.plan = self.planner.plan(state.request)
            state.plan_sha256 = plan_digest(state.plan)
            self._event(state, "criteria_frozen", plan_sha256=state.plan_sha256)
            self._event(state, "feasibility_preflight", supplied_observations=len(submission.observations),
                collector_capability="Reference knowledge only; observations require a separate declared input.")
            packages, fetch_gaps = {}, {}
            pending = list(state.plan.genes)
            budget_exhausted = False
            for attempt in range(state.request.max_revisions + 1):
                if not pending:
                    break
                state.attempts = attempt + 1
                self._event(state, "evidence_collection", attempt=state.attempts, genes=pending)
                for gene in pending:
                    if time.monotonic() - started >= self.budget_seconds:
                        budget_exhausted = True
                        fetch_gaps[gene] = Gap(code="budget_exhausted", gene=gene,
                            detail="No further collection started after the investigation budget expired.")
                        continue
                    try:
                        packages[gene] = self.provider.fetch(gene, state.plan.disease, state.request.mode, state.run_id)
                        fetch_gaps.pop(gene, None)
                    except Exception as exc:
                        fetch_gaps[gene] = Gap(code="collection_error", gene=gene,
                            retryable=not isinstance(exc, (ValueError, FileNotFoundError)),
                            detail=f"Collection failed ({type(exc).__name__}); no biological negative inferred.")
                state.evidence = adapt_packages(list(packages.values()))
                state.evidence.records.extend(submission.observations)
                state.evidence.gaps.extend(fetch_gaps.values())
                # Caller-provided observation identity must not overwrite a source record.
                ids = [r.id for r in state.evidence.records]
                if len(ids) != len(set(ids)):
                    raise ValueError("Evidence IDs collide; use unique observation IDs")
                self._event(state, "feasibility_and_comparison")
                state.assessment = assess(state.plan, state.evidence)
                self._event(state, "verification", criteria_met=state.assessment.criteria_met)
                if plan_digest(state.plan) != state.plan_sha256:
                    raise ValueError("Frozen research criteria changed during execution")
                pending = sorted({gap.gene for gap in state.evidence.gaps
                    if gap.retryable and gap.gene in state.plan.genes})
                if state.assessment.criteria_met or not pending or budget_exhausted:
                    break
                if attempt < state.request.max_revisions:
                    self._event(state, "targeted_follow_up", genes=pending,
                        reason="Retry technical collection failures; preserve scientific criteria.")
            state.status = "complete" if state.assessment and state.assessment.criteria_met else "partial"
            state.report = render_report(state)
            self._event(state, "finished", status=state.status)
        except Exception as exc:
            state.status = "failed"
            # Do not include upstream HTTP bodies/headers, which can contain credentials.
            state.error = str(exc)[:500] if isinstance(exc, ValueError) else f"{type(exc).__name__}: investigation execution failed"
            self._event(state, "failed", error=state.error)
        return state


def render_report(state: RunState) -> str:
    assessment = state.assessment
    lines = ["# Investigation", state.request.question, "",
        f"Execution: **{state.status}**",
        f"Evidence conclusion: **{assessment.conclusion}**", "",
        "These conclusions describe declared, comparable observations. They do not establish causality, clinical efficacy, or independently validate imported metadata.",
        "", "## Criteria"]
    for check in assessment.checks:
        lines.append(f"- {'Met' if check.passed else 'Unmet'} — {check.id}: {check.detail}")
        if check.evidence_ids:
            lines.append(f"  Evidence: {', '.join(check.evidence_ids)}")
    lines.extend(["", "## Comparisons"])
    for comparison in assessment.comparisons:
        lines.append(f"- {comparison.id}: **{comparison.conclusion}** — {comparison.detail}")
        if comparison.evidence_ids:
            lines.append(f"  Evidence: {', '.join(comparison.evidence_ids)}")
    if not assessment.comparisons:
        lines.append("No biological comparison was specified; evidence coverage alone is not validation.")
    lines.extend(["", "## Gaps and next steps"])
    for gap in state.evidence.gaps + assessment.gaps:
        lines.append(f"- {gap.code}: {gap.detail}")
    lines.extend(["", "## Interpretation limits"] + [f"- {c}" for c in state.plan.claims_to_avoid])
    return "\n".join(lines) + "\n"
