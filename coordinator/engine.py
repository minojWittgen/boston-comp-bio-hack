"""One bounded investigation, shared by CLI, HTTP, and the Modal worker."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

from .checks import assess
from .evidence import adapt_packages
from .investigation import investigate
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
                collector_capability="Investigate published database results and source metadata; preserve species, context, modality and unresolved questions.",
                completion_basis="Research coverage, source traceability and disclosed limitations; no biological verdict is required.")
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
                state.investigation = investigate(state.plan, state.evidence)
                # Optional observation diagnostics keep their original scientific meaning.
                # They never decide whether a source-based investigation is complete.
                state.assessment = assess(state.plan, state.evidence)
                self._event(state, "verification", criteria_met=state.investigation.criteria_met,
                    completion_basis="investigation", observation_criteria_met=state.assessment.criteria_met)
                if plan_digest(state.plan) != state.plan_sha256:
                    raise ValueError("Frozen research criteria changed during execution")
                pending = sorted({gap.gene for gap in state.evidence.gaps
                    if gap.retryable and gap.gene in state.plan.genes})
                if not pending or budget_exhausted:
                    break
                if attempt < state.request.max_revisions:
                    self._event(state, "targeted_follow_up", genes=pending,
                        reason="Fill recoverable collection gaps under the unchanged research scope.")
            state.status = "complete" if state.investigation and state.investigation.criteria_met else "partial"
            state.report = render_report(state)
            self._event(state, "finished", status=state.status)
        except Exception as exc:
            state.status = "failed"
            # Do not include upstream HTTP bodies/headers, which can contain credentials.
            state.error = str(exc)[:500] if isinstance(exc, ValueError) else f"{type(exc).__name__}: investigation execution failed"
            self._event(state, "failed", error=state.error)
        return state


def render_report(state: RunState) -> str:
    if state.investigation is not None:
        return render_investigation_report(state)
    # Historical states retain their original observation-check interpretation.
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


def render_investigation_report(state: RunState) -> str:
    """A grounded research report shared by API, CLI and website export."""
    research = state.investigation
    records = {r.id: r for r in state.evidence.records} if state.evidence else {}
    requirements = {r.id: r for r in state.plan.requirements} if state.plan else {}

    def text(value):
        value = str(value).replace("\n", " ")
        for char in ("\\", "[", "]", "*", "_", "<", ">", "`", "|"):
            value = value.replace(char, "\\" + char)
        return value

    lines = ["# Research investigation", "", text(state.request.question), "",
        f"Investigation: **{state.status}**", "", text(research.completion_reason), "",
        "Completion describes the bounded investigation, not proof of a biological hypothesis.",
        "", "## Findings from the retrieved sources", ""]
    for finding in research.findings:
        lines.extend([f"### {text(finding.entity)} · {text(finding.source)}", "",
            text(finding.summary), "", f"Evidence record: {text(finding.evidence_id)}"])
        record = records.get(finding.evidence_id)
        if record:
            dimensions = "; ".join(f"{key}: {text(getattr(record, key) or 'not supplied')}"
                for key in ("species", "context", "modality", "endpoint", "condition", "tissue", "host_species"))
            lines.append(dimensions)
            lines.extend(f"Source reference: {text(p)}" for p in record.provenance)
            source_result = record.payload.get("source_result", {})
            if isinstance(source_result, dict) and source_result.get("query"):
                lines.append("Source query: " + text(json.dumps(source_result["query"], ensure_ascii=False, sort_keys=True)))
            lines.append(f"Source release: {text(record.source_version or 'not supplied')}; retrieved: {text(record.retrieved_at or 'not supplied')}")
        lines.extend(f"- Interpretation limit: {text(note)}" for note in finding.limitations)
        lines.append("")
    if not research.findings:
        lines.extend(["No usable findings were returned by this search. This is not evidence of biological absence.", ""])
    lines.extend(["## Research scope reviewed", "",
        "Addressed means material in the requested scope was reviewed; it does not certify the requested biological effect.", ""])
    for coverage in research.coverage:
        req = requirements.get(coverage.requirement_id)
        title = req.title if req else coverage.requirement_id
        lines.append(f"- **{text(title)} — {coverage.status}:** {text(coverage.detail)}")
        if coverage.evidence_ids:
            lines.append("  Related records: " + ", ".join(text(item) for item in coverage.evidence_ids))
    lines.extend(["", "## Comparison across research contexts", ""])
    for comparison in research.comparisons:
        lines.extend([f"### {text(comparison.id)}", "", text(comparison.summary), "",
            "Left records: " + (", ".join(text(i) for i in comparison.left_evidence_ids) or "none returned"),
            "Right records: " + (", ".join(text(i) for i in comparison.right_evidence_ids) or "none returned")])
        lines.extend(f"- {text(note)}" for note in comparison.limitations)
        lines.append("")
    if not research.comparisons:
        lines.extend(["No cross-context comparison was requested; the source findings above remain available for review.", ""])
    lines.extend(["## Uncertainty and search limitations", ""])
    limits = list(research.limitations)
    if state.evidence:
        limits.extend(f"{g.source or 'Collection'} ({g.gene or 'scope'}): {g.detail}" for g in state.evidence.gaps)
    for limit in dict.fromkeys(limits):
        lines.append(f"- {text(limit)}")
    if not limits:
        lines.append("No collection problem was recorded. Scientific interpretation still depends on the reported study context.")
    lines.extend(["", "## Next research steps", ""])
    lines.extend(f"- {text(step)}" for step in research.next_steps)
    if not research.next_steps:
        lines.append("Review the cited findings and refine the question if additional context is needed.")
    if state.assessment and any(r.level == "observation" for r in records.values()):
        lines.extend(["", "## Optional supplied-observation diagnostics", "",
            "These checks apply only to explicitly supplied observations. They do not control investigation completion.",
            "Declared-observation comparison: " + state.assessment.conclusion])
        lines.extend(f"- {text(c.id)}: {c.conclusion} — {text(c.detail)}" for c in state.assessment.comparisons)
    if state.plan and state.plan.assumptions:
        lines.extend(["", "## Intent assumptions", ""])
        lines.extend(f"- {text(note)}" for note in state.plan.assumptions)
    return "\n".join(lines) + "\n"
