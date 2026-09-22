"""Display projections only. Scientific conclusions come from the coordinator."""
from coordinator.models import RunState

CONTEXT_LABELS = {"in_vitro": "In vitro", "in_vivo": "In vivo", "patient": "Patients"}


def context_coverage(state: RunState):
    checks = {check.id: check for check in state.assessment.checks} if state.assessment else {}
    requirements = state.plan.requirements if state.plan else state.request.requirements
    rows = []
    for context, label in CONTEXT_LABELS.items():
        scoped = [r for r in requirements if r.context == context]
        passed = sum(bool(checks.get(r.id) and checks[r.id].passed) for r in scoped)
        rows.append({"context": context, "label": label, "total": len(scoped), "passed": passed,
                     "detail": f"{passed} of {len(scoped)} evidence requirements met" if scoped else "No requirement specified; not assessed"})
    return rows


def is_synthetic(state: RunState):
    # A display label, not a selector that can route a real request to fixture data.
    return state.request.question.startswith("SYNTHETIC DEMO:") or bool(state.evidence and any(
        r.source == "synthetic-demonstration" or r.source.startswith("synthetic-")
        for r in state.evidence.records))


def assistant_summary(state: RunState):
    if state.status == "failed":
        return "I couldn’t finish this investigation. " + (state.error or "See the investigation activity for details.")
    if state.assessment is None:
        return "The investigation is still running."
    conclusion = state.assessment.conclusion.replace("_", " ")
    unmet = sum(c.required and not c.passed for c in state.assessment.checks)
    text = f"The investigation finished with **{state.status}** execution. The evidence conclusion is **{conclusion}**."
    if unmet:
        text += f" {unmet} required evidence checks remain unmet."
    if state.assessment.conclusion == "conflicting":
        text += " Comparable declared observations point in opposing directions; the disagreement is retained."
    elif state.assessment.conclusion == "not_assessable":
        text += " The available evidence does not establish the requested comparison."
    text += " These checks describe supplied observations and their declared metadata, not independent biological validation."
    if is_synthetic(state):
        text += " **This run uses synthetic demonstration data.**"
    return text
