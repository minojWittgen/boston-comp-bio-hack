"""Researcher-facing projections. Never recompute or override scientific assessments."""
from coordinator.models import RunState

CONTEXT_LABELS = {"in_vitro": "Cell cultures", "in_vivo": "Animal models", "patient": "Patients", "reference": "Reference data"}
SPECIES_LABELS = {"homo_sapiens": "Human", "mus_musculus": "Mouse", "rattus_norvegicus": "Rat", "macaca_mulatta": "Rhesus macaque"}
CONCLUSIONS = {"supported": "Measurements agree in direction", "conflicting": "Measurements disagree", "inconclusive": "No clear agreement", "not_assessable": "Not enough comparable evidence"}
COLLECTION_PROBLEMS = {"collection_error", "budget_exhausted", "source_error", "source_missing", "malformed_source", "malformed_package", "unsupported_source"}
STAGES = {"queued": "Waiting to start", "planning": "Defining the research question", "feasibility": "Checking which sources can answer the question", "collecting": "Searching research databases", "assessing": "Checking whether the measurements can be compared", "revising": "Looking for missing evidence", "reporting": "Preparing your report", "finished": "Search finished", "failed": "Search could not finish"}
STAGES.update({"intent_and_criteria": "Defining the research question", "criteria_frozen": "Research criteria set",
               "feasibility_preflight": "Checking available sources", "evidence_collection": "Searching research databases",
               "feasibility_and_comparison": "Comparing the retrieved evidence", "verification": "Checking the comparison",
               "targeted_follow_up": "Looking for missing evidence"})


def readable(value):
    return SPECIES_LABELS.get(value, str(value).replace("_", " ")) if value is not None else "Not supplied"


def search_status(state):
    if state.status == "failed":
        return "Could not finish"
    if state.status not in {"complete", "partial"}:
        return "In progress"
    if state.error or (state.evidence and any(g.code in COLLECTION_PROBLEMS for g in state.evidence.gaps)):
        return "Some sources unavailable"
    return "Finished"


def context_coverage(state: RunState):
    investigation = getattr(state, "investigation", None)
    if investigation is not None:
        coverage = {c.requirement_id: c for c in investigation.coverage}
        requirements = state.plan.requirements if state.plan else state.request.requirements
        rows = []
        for context in ("in_vitro", "in_vivo", "patient"):
            scoped = [r for r in requirements if r.context == context]
            entries = [coverage[r.id] for r in scoped if r.id in coverage]
            addressed = sum(c.status == "addressed" for c in entries)
            limited = sum(c.status == "limited" for c in entries)
            detail = "Outside this question's scope." if not scoped else " ".join(c.detail for c in entries)
            rows.append({"context": context, "label": CONTEXT_LABELS[context], "total": len(scoped),
                         "passed": addressed, "addressed": addressed, "limited": limited,
                         "unavailable": sum(c.status == "unavailable" for c in entries),
                         "detail": detail or "Investigation coverage is being prepared."})
        return rows
    checks = {c.id: c for c in state.assessment.checks} if state.assessment else {}
    requirements = state.plan.requirements if state.plan else state.request.requirements
    rows = []
    for context in ("in_vitro", "in_vivo", "patient"):
        scoped = [r for r in requirements if r.context == context]
        passed = sum(bool(checks.get(r.id) and checks[r.id].passed) for r in scoped)
        if not scoped:
            detail = "Outside this question's scope."
        elif not state.assessment:
            detail = "Waiting for evidence checks."
        elif passed == len(scoped):
            detail = "Study measurements meet the requested evidence criteria."
        elif passed:
            detail = "Some requested study measurements are available. See the study minimum and missing information below."
        else:
            targets = "; ".join(f"{r.entity} {r.modality}: at least {r.min_studies} {'study' if r.min_studies == 1 else 'studies'}" for r in scoped)
            detail = "No requested measurement has enough qualifying study records. This plan asks for " + targets + "."
        rows.append({"context": context, "label": CONTEXT_LABELS[context], "total": len(scoped), "passed": passed, "detail": detail})
    return rows


def is_synthetic(state: RunState):
    return state.request.question.startswith("SYNTHETIC DEMO:") or bool(state.evidence and any(
        r.source == "synthetic-demonstration" or r.source.startswith("synthetic-") for r in state.evidence.records))


def assistant_summary(state: RunState):
    if state.status == "failed":
        return "The search could not finish. " + (state.error or "See the error below for details.")
    investigation = getattr(state, "investigation", None)
    if investigation is not None:
        text = "**Investigation complete.** " if investigation.criteria_met else "**Collection incomplete.** "
        text += f"The report brings together {len(investigation.findings)} source findings, comparisons and open questions."
        if is_synthetic(state):
            text += " **This is a synthetic teaching example, not a biological finding.**"
        return text
    if state.assessment is None:
        return "The search is still running."
    text = "The search finished. " if search_status(state) == "Finished" else "The search ended with some sources unavailable. "
    text += {
        "not_assessable": "**There is not enough comparable evidence to answer your question yet.** See “Why this result?” for what was found, the study minimum, and the data or plan issues preventing comparison. This does not mean relevant studies do not exist.",
        "conflicting": "**The compared measurements disagree in direction.** The report keeps that disagreement visible.",
        "inconclusive": "**The compared measurements show no clear agreement.** Mixed directions or unchanged measurements prevent a clear conclusion.",
        "supported": "**The compared measurements agree in direction.** This describes the supplied observations; it does not establish causality or clinical benefit.",
    }[state.assessment.conclusion]
    if is_synthetic(state):
        text += " **This is a synthetic teaching example, not a biological finding.**"
    return text


def requirement_rows(state):
    if not state.plan:
        return []
    investigation = getattr(state, "investigation", None)
    if investigation is not None:
        coverage = {c.requirement_id: c for c in investigation.coverage}
        return [{"Question to answer": r.title, "Gene / target": r.entity,
                 "Context": CONTEXT_LABELS[r.context], "Species": readable(r.species),
                 "Research topic": readable(r.endpoint),
                 "Evidence available": coverage[r.id].status.capitalize() if r.id in coverage else "Pending",
                 "What the sources answer": coverage[r.id].detail if r.id in coverage else "Coverage is being prepared.",
                 "Disease / condition": r.condition or "Not specified", "Tissue": r.tissue or "Not specified",
                 "Host species": readable(r.host_species) if r.host_species else "Not specified",
                 "Priority": "Required" if r.required else "Optional"} for r in state.plan.requirements]
    checks = {c.id: c for c in state.assessment.checks} if state.assessment else {}
    rows = []
    for r in state.plan.requirements:
        check = checks.get(r.id)
        status = "Not checked yet" if check is None else "Available" if check.passed else "More evidence needed"
        rows.append({"Question to answer": r.title, "Gene / target": r.entity,
                     "Context": CONTEXT_LABELS[r.context], "Species": readable(r.species),
                     "Measurement needed": readable(r.endpoint), "Evidence available": status,
                     "Disease / condition": r.condition or "Not specified", "Tissue": r.tissue or "Not specified",
                     "Host species": readable(r.host_species) if r.host_species else "Not specified",
                     "Study requirement": f"At least {r.min_studies} {'study' if r.min_studies == 1 else 'studies'} with distinct study IDs",
                     "Priority": "Required" if r.required else "Optional"})
    return rows


def comparison_views(state, *, observation_only=False):
    investigation = getattr(state, "investigation", None)
    if investigation is not None and not observation_only:
        specs = {c.id: c for c in state.plan.comparisons} if state.plan else {}
        requirements = {r.id: r for r in state.plan.requirements} if state.plan else {}
        records = state.evidence.records if state.evidence else []
        views = []
        for comparison in investigation.comparisons:
            spec = specs.get(comparison.id)
            title = f"{requirements[spec.left].title} ↔ {requirements[spec.right].title}" if spec else readable(comparison.id)
            ids = set(comparison.left_evidence_ids + comparison.right_evidence_ids)
            views.append({"id": comparison.id, "title": title, "conclusion": "What the sources show",
                          "detail": comparison.summary, "limitations": comparison.limitations,
                          "records": [r for r in records if r.id in ids]})
        return views
    if not state.plan or not state.assessment:
        return []
    requirements = {r.id: r for r in state.plan.requirements}
    checks = {c.id: c for c in state.assessment.checks}
    results = {c.id: c for c in state.assessment.comparisons}
    views = []
    for spec in state.plan.comparisons:
        result = results.get(spec.id)
        if result is None:
            continue
        left, right = requirements[spec.left], requirements[spec.right]
        def label(r):
            return f"{r.entity} · {CONTEXT_LABELS[r.context]} · {readable(r.species)} · {r.modality}"
        missing = [r.title for r in (left, right) if not checks.get(r.id) or not checks[r.id].passed]
        if result.conclusion == "not_assessable":
            detail = ("More study evidence is needed for: " + "; ".join(missing) + ".") if missing else "The available study measurements do not meet the matching criteria needed for this comparison."
            if left.species != right.species and not spec.cross_species_basis:
                detail += " A scientific basis for comparing these species has not been supplied."
            if spec.require_matched_subjects:
                detail += " This comparison also requires measurements from the same study, participant, sample and time point."
        else:
            detail = {"supported": "The compared observations change in the same direction.", "conflicting": "The compared observations change in opposing directions.", "inconclusive": "The compared observations contain mixed directions or unchanged measurements."}[result.conclusion]
            detail += " This is a descriptive comparison of supplied measurements."
            if not spec.require_matched_subjects:
                detail += " It does not establish agreement within the same individual."
        views.append({"id": spec.id, "title": f"{label(left)} ↔ {label(right)}", "conclusion": CONCLUSIONS[result.conclusion], "detail": detail,
                      "records": [r for r in (state.evidence.records if state.evidence else []) if r.id in result.evidence_ids]})
    return views


def collection_notes(state):
    """Surface retrieval limits without leaking raw exception payloads or internal IDs."""
    from research_app.sources import SOURCE_NAMES
    notes = []
    for gap in (state.evidence.gaps if state.evidence else []):
        source = SOURCE_NAMES.get(gap.source, readable(gap.source)) if gap.source else "Evidence collection"
        prefix = f"{source} ({gap.gene})" if gap.gene else source
        if gap.code in {"source_truncated", "source_may_be_truncated"}:
            text = "Only part of the source's results was retrieved. A missing entry does not mean no evidence exists."
        elif gap.code == "source_not_found":
            text = "No result was returned for this query. This is not proof of biological absence."
        elif gap.code in COLLECTION_PROBLEMS:
            text = "Could not provide usable results in this search. Coverage is incomplete."
        elif gap.code in {"ambiguous_gene", "gene_unresolved"}:
            text = "The gene identity needs review before interpreting this source."
        elif gap.code in {"source_skipped", "source_not_applicable"}:
            text = "This source was not searched for this request."
        elif gap.code == "pathway_background_only":
            text = "Pathway membership and source coverage were retrieved; these do not measure pathway activity."
        else:
            text = "The source has an additional interpretation limit. See the technical details before drawing a conclusion."
        note = f"{prefix}: {text}"
        if note not in notes:
            notes.append(note)
    return notes
