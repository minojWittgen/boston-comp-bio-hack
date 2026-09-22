"""Explain saved assessments from their criteria, evidence and accepted record IDs.

No new model call, rescore, invented citation, or modification of a frozen plan.
"""
from research_app.presentation import CONTEXT_LABELS, readable
from research_app.sources import source_view


def criteria_origin(state):
    if getattr(state, "investigation", None) is not None:
        return ("The research scope came from your submitted request." if state.request.requirements else
                "The model proposed this research scope from your question. The findings below explain what the retrieved sources address.")
    if state.request.requirements:
        return "The study minimum and scope below came from the submitted research request."
    return "The model proposed the study minimum and scope from your question; you did not explicitly choose these thresholds."


def _studies(records, ids):
    return len({r.study_id for r in records if r.id in ids and r.study_id})


def requirement_explanations(state):
    if not state.plan:
        return []
    investigation = getattr(state, "investigation", None)
    if investigation is not None:
        coverage = {c.requirement_id: c for c in investigation.coverage}
        return [{"id": r.id, "title": r.title, "required": r.required,
                 "scope": f"{r.entity}; {readable(r.species)}; {CONTEXT_LABELS[r.context]}; {r.modality}",
                 "measurement": readable(r.endpoint),
                 "status": coverage[r.id].status if r.id in coverage else "pending",
                 "detail": coverage[r.id].detail if r.id in coverage else "Coverage is being prepared.",
                 "evidence_ids": coverage[r.id].evidence_ids if r.id in coverage else []}
                for r in state.plan.requirements]
    checks = {c.id: c for c in state.assessment.checks} if state.assessment else {}
    records = state.evidence.records if state.evidence else []
    result = []
    for req in state.plan.requirements:
        check = checks.get(req.id)
        count = _studies(records, check.evidence_ids) if check else None
        scope = f"{req.entity}; {readable(req.species)}; {CONTEXT_LABELS[req.context]}; {req.modality}"
        for label, value in (("condition", req.condition), ("tissue", req.tissue), ("host species", req.host_species)):
            if value:
                scope += f"; {label}: {readable(value)}"
        result.append({"id": req.id, "title": req.title, "scope": scope, "measurement": readable(req.endpoint),
                       "minimum": req.min_studies, "qualifying_studies": count,
                       "passed": check.passed if check else None, "required": req.required})
    return result


def source_contributions(state):
    """What each reference establishes at its reported level, not a clinical inference."""
    result = []
    investigation = getattr(state, "investigation", None)
    findings = {f.evidence_id: f for f in investigation.findings} if investigation is not None else {}
    for record in (state.evidence.records if state.evidence else []):
        view = source_view(record)
        finding = findings.get(record.id)
        if investigation is not None:
            role = " ".join(finding.limitations) if finding and finding.limitations else view.limitation
        elif record.level == "observation":
            role = "A supplied study measurement; inclusion in a comparison depends on the saved checks."
        else:
            role = {
                "mygene": "Identifies the gene to look up. It does not measure expression.",
                "ensembl_orthology": "Identifies a related gene across species. Sequence identity is not an RNA-abundance measurement or an evidence-confidence score.",
                "gtex": "Provides tissue-level RNA reference values. This integration has not prepared them as traceable study observations for comparison.",
                "impc": "Provides mouse phenotype results, not RNA abundance. The study-specific source and comparison information still need to be prepared for the checker.",
                "opentargets": "Provides gene–disease associations, not comparable RNA measurements.",
                "pubmed": "Finds papers to review. Their study measurements have not been extracted or screened against this question.",
                "hpa_cell_lines": "Provides cell-culture summaries. Distribution categories and protein locations do not supply a study-level RNA contrast.",
                "opentargets_depmap": "Contains cell-line screen values, including expression where supplied. This integration has not prepared them as study observations with study IDs, source references and comparable outcome definitions. Expression units are not supplied.",
                "hpa_pathology": "Provides cancer-cohort categories and annotations, not the requested study-level RNA measurements and comparison groups.",
                "reactome_pathway": "Defines pathway membership and source coverage, not measured pathway activity.",
            }.get(record.source, view.limitation)
        result.append({"title": view.title, "finding": finding.summary if finding else view.summary, "role": role, "links": view.links,
                       "record_id": record.id, "entity": record.entity})
    return result


def overview_explanation(state):
    records = state.evidence.records if state.evidence else []
    observations = [r for r in records if r.level == "observation"]
    if state.status == "failed":
        return "The search did not finish. The returned material cannot be treated as a completed evidence review."
    investigation = getattr(state, "investigation", None)
    if investigation is not None:
        return (investigation.completion_reason + " "
                f"The investigation explains {len(investigation.findings)} retrieved findings, their source coverage and limitations. "
                "Database results contribute at their reported level; uncertainty remains visible in the findings and next steps.")
    if not state.assessment:
        return "The evidence checks have not finished yet."
    if records and not observations:
        return (f"We retrieved {len(records)} reference records, including any database measurements and article searches shown below. "
                "None was supplied to the comparison as a study observation. This is a limitation of the current evidence integration, "
                "not a finding that relevant studies do not exist or that the biology disagrees. More records of the same type alone will not complete the comparison.")
    if not records:
        return "No evidence records were available to assess. Check the source-search limitations below before interpreting this as a research gap."
    return ("The result comes from the study observations accepted by the saved scope and comparison checks. "
            "The study counts below refer to distinct supplied study IDs, not database rows, papers found by a search, or participants.")


def plan_issues(state, spec):
    """Surface a structural blocker; never rewrite measurement names or assert equivalence."""
    reqs = {r.id: r for r in state.plan.requirements}
    left, right = reqs[spec.left], reqs[spec.right]
    issues = []
    if left.endpoint != right.endpoint:
        issues.append("The plan uses different measurement names on the two sides. The current checker requires an exact match, "
                      "so even enough studies would not make this plan comparable. Review whether the measurements are scientifically equivalent "
                      "and correct the plan before starting a new investigation; this saved result has not been changed.")
    if left.species != right.species and not spec.cross_species_basis:
        issues.append("No basis for comparing these species was supplied in the plan. A related gene and high sequence identity alone do not establish comparable expression.")
    return issues


def comparison_explanations(state):
    if not state.plan or not state.assessment:
        return {}
    reqs = {r.id: r for r in state.plan.requirements}
    checks = {c.id: c for c in state.assessment.checks}
    comparisons = {c.id: c for c in state.assessment.comparisons}
    records = state.evidence.records if state.evidence else []
    explanations = {}
    for spec in state.plan.comparisons:
        result = comparisons.get(spec.id)
        if not result:
            continue
        left, right = reqs[spec.left], reqs[spec.right]
        sides = []
        for req in (left, right):
            check = checks.get(req.id)
            accepted = set(check.evidence_ids) if check else set()
            sides.append({"Context / measurement": req.title, "Minimum studies in this plan": req.min_studies,
                          "Studies meeting scope and traceability": _studies(records, accepted),
                          "Studies usable in this comparison": _studies(records, accepted & set(result.evidence_ids))})
        requirements = ["Study observations for the requested gene, species, context and measurement, with a study ID and a source reference.",
                        "Measurements of the same outcome, using a shared comparison group (for example, disease versus control), with a reported increase, decrease or unchanged result."]
        if left.modality != right.modality:
            requirements.append("A declared common normalization method for the different measurement types.")
        if any(getattr(left, k) != getattr(right, k) for k in ("condition", "tissue", "host_species")):
            requirements.append("A declared justification for aligning different or unspecified disease, tissue or host-species settings.")
        if spec.require_matched_subjects:
            identity = "This comparison requires the same study, participant, sample and time point on both sides."
        else:
            identity = "Participant and sample IDs are not required by this run's comparison rule. It compares across studies, not within the same individual. Study IDs and source references are still required."
        explanations[spec.id] = {"counts": sides, "needs": requirements, "identity": identity,
                                 "plan_issues": plan_issues(state, spec),
                                 "reasons": _pair_reasons(result.detail)}
    return explanations


# Translate only rejection reasons emitted by the saved assessment. Do not re-assess pairs.
_PAIR_REASONS = {
    "same evidence record on both sides": "The same record cannot corroborate itself.",
    "different endpoints": "The measurements have different outcome names; review and align their scientific meaning first.",
    "missing comparability key": "The records do not declare which measurements are comparable.",
    "different comparability keys": "The records describe different comparison definitions.",
    "missing contrast": "The reference or comparison group is missing.",
    "different contrasts": "The measurements use different reference or comparison groups.",
    "missing declared cross-species basis": "A basis for comparing the species was not supplied.",
    "missing cross-modal normalization basis": "A method for normalizing across measurement types was not supplied.",
    "different cross-modal normalization bases": "The measurements use different normalization methods.",
    "missing study/subject/specimen/timepoint for subject matching": "Study, participant, sample or time-point information needed to match individuals is missing.",
    "unmatched study/subject/specimen/timepoint": "The study, participant, sample or time point differs between the measurements.",
    "missing observed direction": "A measured increase, decrease or unchanged result was not supplied.",
}
for _field, _label in (("condition", "disease or condition"), ("tissue", "tissue"), ("host_species", "host species")):
    for _kind in ("missing", "different"):
        _PAIR_REASONS[f"{_kind} {_field} alignment without declared context-alignment basis"] = f"The {_label} differs or is missing, and no justification for comparing those settings was supplied."


def _pair_reasons(detail):
    section = detail.partition("Excluded candidate pairs: ")[2].partition(". Pair counts")[0]
    return [text for reason, text in _PAIR_REASONS.items() if f"{reason} (" in section]
