"""Grounded research summaries; completion is not a biological verdict.

This module interprets only the material already in an EvidenceBundle. It does
not fetch articles, infer experimental measurements, or run the legacy scientific
observation checks. Source payloads and declared observation metadata remain the
audit trail; the bounded previews below never replace those records.
"""
from __future__ import annotations

import json
from typing import Any

from .models import (
    CheckResult, EvidenceBundle, EvidenceRecord, EvidenceRequirement, Gap,
    InvestigationAssessment, ResearchComparison, ResearchCoverage, ResearchFinding,
    ResearchPlan,
)


def _obj(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _shown(value: Any, limit: int = 260) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return "not supplied"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + "… [preview; full value in evidence record]"


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _preview(items: list[str], total: int) -> str:
    if not items:
        return ""
    suffix = f" Showing {len(items)} of {total} returned rows; all rows remain in the evidence record." if total > len(items) else ""
    return " " + "; ".join(items) + "." + suffix


def _scope(record: EvidenceRecord | EvidenceRequirement) -> str:
    values = [f"species={record.species or 'unspecified'}", f"context={record.context or 'unspecified'}",
              f"modality={record.modality or 'unspecified'}", f"endpoint={record.endpoint or 'unspecified'}"]
    for name in ("condition", "tissue", "host_species"):
        if getattr(record, name):
            values.append(f"{name}={getattr(record, name)}")
    return ", ".join(values)


def _finding(record: EvidenceRecord) -> ResearchFinding:
    result = _obj(record.payload.get("source_result"))
    data = _obj(result.get("data"))
    query = _obj(result.get("query"))
    limits = [str(record.payload["limitation"])] if record.payload.get("limitation") else []
    source = record.source
    if record.level == "observation":
        summary = (f"Supplied observation: {record.entity}; {_scope(record)}; reported direction={record.direction or 'unspecified'}; "
                   f"contrast={record.contrast or 'unspecified'}; unit={record.unit or 'unspecified'}.")
        identifiers = [f"{key}={getattr(record, key)}" for key in ("study_id", "subject_id", "specimen_id", "timepoint")
                       if getattr(record, key) is not None]
        if identifiers:
            summary += " Declared identities: " + ", ".join(identifiers) + "."
        if record.payload:
            summary += " Supplied values: " + _shown(record.payload) + "."
        limits.append("Supplied observations and their identities are declarations, not independently verified measurements; opposing directions remain visible without a biological verdict.")
        return ResearchFinding(evidence_id=record.id, entity=record.entity, source=source,
                               summary=summary, limitations=_unique(limits))

    if source == "mygene":
        text = (f"Gene identity: {_shown(data.get('symbol'))}; name={_shown(data.get('name'))}; "
                f"Ensembl={_shown(data.get('ensembl_primary'))}; ambiguity flag={_shown(data.get('ambiguous'))}.")
    elif source == "ensembl_orthology":
        rows = _rows(data.get("orthologs"))
        text = f"Returned {len(rows)} ortholog records for {_shown(query.get('target_species') or record.species)}."
        text += _preview([f"{_shown(r.get('target_symbol') or r.get('target_id'))}: relationship={_shown(r.get('type'))}, "
                          f"target sequence identity={_shown(r.get('perc_id_target'))}%, source sequence identity={_shown(r.get('perc_id_source'))}%"
                          for r in rows[:3]], len(rows))
        limits.append("Sequence identity percentages are sequence comparisons, not probabilities, RNA measurements, or evidence of conserved activity.")
    elif source == "gtex":
        rows = _rows(data.get("tissues"))
        text = f"Returned reference RNA medians for {len(rows)} tissue groups."
        text += _preview([f"{_shown(r.get('tissue'))}: {_shown(r.get('median_tpm'))} TPM" for r in rows[:3]], len(rows))
        limits.append("Tissue medians are not disease-versus-control changes or individual patient measurements.")
    elif source == "impc":
        rows = _rows(data.get("hits"))
        text = (f"Mouse knockout phenotype records: {len(rows)}; reported tests={_shown(data.get('n_tests'))}; "
                f"phenotyped={_shown(data.get('phenotyped'))}.")
        text += _preview([f"{_shown(r.get('mp_term_name') or r.get('mp_term_id'))}: reported p-value={_shown(r.get('p_value'))}, "
                          f"sex={_shown(r.get('sex'))}, zygosity={_shown(r.get('zygosity'))}" for r in rows[:3]], len(rows))
        limits.append("A phenotype annotation is not an animal RNA or protein measurement; zero returned hits is not proof of no phenotype.")
    elif source == "opentargets":
        associations = _obj(data.get("associatedDiseases"))
        rows = _rows(associations.get("rows"))
        text = f"Returned {len(rows)} disease association rows of {_shown(associations.get('count'))} reported."
        text += _preview([f"{_shown(_obj(r.get('disease')).get('name') or _obj(r.get('disease')).get('id'))}: "
                          f"association score={_shown(r.get('score'))}" for r in rows[:3]], len(rows))
        limits.append("Association scores are rankings, not probabilities or treatment effects; rows may concern other diseases.")
    elif source == "pubmed":
        ids = data.get("pmids") if isinstance(data.get("pmids"), list) else []
        text = (f"Literature search reported {_shown(data.get('count'))} matches and returned {len(ids)} identifiers; "
                f"query={_shown(query.get('term'))}; PMID preview={_shown(ids[:5])}.")
        limits.append("Article contents, study design, and experimental measurements were not extracted from these identifiers.")
    elif source == "hpa_cell_lines":
        rna, protein = _obj(data.get("rna")), _obj(data.get("protein"))
        text = (f"Cell-line RNA distribution={_shown(rna.get('cell_line_distribution') or data.get('rna_summary'))}; "
                f"specific RNA (nTPM)={_shown(rna.get('cell_line_specific_ntpm'))}; "
                f"protein location={_shown(protein.get('subcellular_location') or data.get('protein_location'))}.")
        limits.append("RNA distribution and protein location are different endpoints, not paired quantitative RNA/protein measurements.")
    elif source == "hpa_pathology":
        text = (f"Cancer cohort background: RNA distribution={_shown(data.get('cancer_rna_distribution'))}; "
                f"RNA specificity={_shown(data.get('cancer_rna_specificity'))}; "
                f"disease annotations={_shown(data.get('disease_involvement'))}.")
        limits.append("Cohort summaries do not provide individual patient identities, variation, or matched RNA/protein samples.")
    elif source == "opentargets_depmap":
        screens = [(t.get("tissueName"), s) for t in _rows(data.get("tissues")) for s in _rows(t.get("screens"))]
        text = f"Returned {len(screens)} cell-line screens; tissue groups={_shown(data.get('n_tissues'))}."
        text += _preview([f"{_shown(s.get('cellLineName'))} ({_shown(t)}): gene-effect score={_shown(s.get('geneEffect'))}, "
                          f"RNA expression={_shown(s.get('expression'))} (units not supplied)" for t, s in screens[:3]], len(screens))
        # Retain useful summaries for older adapter-compatible packages as well.
        if not screens and data.get("essentiality") is not None:
            text += " Supplied essentiality fields=" + _shown(data["essentiality"]) + "."
        limits.append("CRISPR fitness and RNA expression are separate endpoints; repeated cell lines are not independent studies.")
    elif source == "reactome_pathway":
        package = _obj(record.payload.get("pathway_package"))
        pathway = _obj(_obj(package.get("pathway")).get("data"))
        members = _rows(pathway.get("genes"))
        text = (f"Pathway membership: {record.entity}; name={_shown(pathway.get('name') or pathway.get('display_name'))}; "
                f"{len(members)} supplied member entries. Member preview={_shown([r.get('symbol') for r in members[:5]])}. "
                f"Reported coverage summary={_shown(package.get('summary'))}.")
        limits.append("Pathway membership and member-source coverage do not measure pathway activity or cross-context preservation.")
    else:
        text = f"Uninterpreted source fields={_shown(data or record.payload)}."
        limits.append("No source-specific interpretation is implemented; these fields need review.")
    if not data and source != "reactome_pathway":
        limits.append("This source supplied no readable data fields; retrieval success alone does not establish a finding.")
    summary = f"{record.entity}: {text}"
    return ResearchFinding(evidence_id=record.id, entity=record.entity, source=source,
                           summary=summary, limitations=_unique(limits))


def _differences(requirement: EvidenceRequirement, record: EvidenceRecord) -> list[str]:
    differences = []
    for name in ("entity", "species", "context", "modality", "endpoint", "condition", "tissue", "host_species"):
        wanted, actual = getattr(requirement, name), getattr(record, name)
        if wanted is not None and wanted != actual:
            differences.append(f"{name}: requested {wanted}, returned {actual or 'unspecified'}")
    return differences


def _related(requirement: EvidenceRequirement, record: EvidenceRecord, plan: ResearchPlan) -> bool:
    if record.entity == requirement.entity:
        return True
    pathway = plan.pathway
    return bool(pathway and requirement.entity == pathway.id and record.entity in pathway.genes)


def _coverage(requirement: EvidenceRequirement, bundle: EvidenceBundle, plan: ResearchPlan) -> ResearchCoverage:
    related = [r for r in bundle.records if r.source != "mygene" and _related(requirement, r, plan)]
    exact = [r for r in related if not _differences(requirement, r)]
    contextual = [r for r in related if r.entity == requirement.entity and r.species == requirement.species
                  and r.context == requirement.context]
    relevant_gaps = [g for g in bundle.gaps if g.gene == requirement.entity or g.gene is None]
    if exact:
        status, records = "addressed", exact
        detail = (f"Reviewed {len(exact)} records matching the declared scope ({_scope(requirement)}). "
                  "Addressed means the scope was reviewed, not that a biological claim was proven. "
                  "Background and supplied-observation labels remain unchanged.")
    elif related:
        status, records = "limited", contextual or sorted(related, key=lambda r: len(_differences(requirement, r)))
        reasons = _unique([reason for r in records for reason in _differences(requirement, r)])
        detail = (f"Reviewed {len(records)} related records, but none matches every declared scope field ({_scope(requirement)}). "
                  "Related records are not evidence that the requested scope was measured. Differences: " + "; ".join(reasons) + ".")
    else:
        status, records = "unavailable", []
        detail = f"No record covers the requested entity and scope ({requirement.entity}; {_scope(requirement)})."
    if relevant_gaps:
        detail += " Recorded source outcomes: " + "; ".join(f"{g.code}: {g.detail}" for g in relevant_gaps) + "."
    if not exact:
        detail += " This is a research limit, not evidence of biological absence."
    if plan.pathway and requirement.entity == plan.pathway.id:
        detail += (f" Pathway scope uses supplied membership from {plan.pathway.source} version {plan.pathway.version}; "
                   "member-based source research does not measure pathway activity.")
    return ResearchCoverage(requirement_id=requirement.id, status=status,
                            evidence_ids=[r.id for r in records], detail=detail)


_DOCUMENTED_OUTCOMES = {
    "source_not_found", "source_skipped", "pathway_background_only", "pathway_not_found", "pathway_skipped",
    "pathway_mouse_inference_not_found", "pathway_mouse_inference_skipped",
    "pathway_member_not_found", "pathway_member_skipped",
    # Top-N and capped searches are valid bounded investigations, not exhaustive reviews.
    "source_truncated", "source_may_be_truncated",
}


def _blocking(gap: Gap) -> bool:
    # Unknown limitations are not silently accepted as successful research. New
    # provider outcomes need an explicit interpretation here before completion.
    return gap.retryable or gap.code not in _DOCUMENTED_OUTCOMES


def _investigated_entities(bundle: EvidenceBundle) -> set[str]:
    # Identifier-only material plus skipped downstream queries is not a completed
    # investigation. Explicit no-hit searches are work performed, not negatives.
    entities = {r.entity for r in bundle.records if r.source != "mygene" and
                (r.level == "observation" or _obj(_obj(r.payload.get("source_result")).get("data"))
                 or _obj(r.payload.get("pathway_package")))}
    entities.update(g.gene for g in bundle.gaps if g.gene and g.code in {"source_not_found", "pathway_not_found"})
    return entities


def _comparisons(plan: ResearchPlan, bundle: EvidenceBundle, coverage: list[ResearchCoverage]) -> list[ResearchComparison]:
    requirements = {r.id: r for r in plan.requirements}
    covered = {r.requirement_id: r for r in coverage}
    by_id = {r.id: r for r in bundle.records}
    comparisons = []
    for spec in plan.comparisons:
        left, right = requirements[spec.left], requirements[spec.right]
        lc, rc = covered[spec.left], covered[spec.right]
        summary = (f"{left.title} ({left.entity}; {_scope(left)}): {lc.status}, {len(lc.evidence_ids)} referenced records. "
                   f"{right.title} ({right.entity}; {_scope(right)}): {rc.status}, {len(rc.evidence_ids)} referenced records.")
        limits = ["This comparison describes the available sources; it does not establish biological agreement, conserved activity, causality, or efficacy."]
        if lc.status != "addressed" or rc.status != "addressed":
            limits.append("One or both sides lack records matching all declared scope fields. Related records may overlap across sides and are not independent or matched evidence.")
        for side, cov, req in (("Left", lc, left), ("Right", rc, right)):
            records = [by_id[eid] for eid in cov.evidence_ids]
            exact_observations = [r for r in records if r.level == "observation" and not _differences(req, r)]
            if exact_observations:
                summary += f" {side} supplied directions:" + _preview([
                    f"{r.id}={r.direction or 'unspecified'} (contrast={r.contrast or 'unspecified'})"
                    for r in exact_observations[:5]], len(exact_observations))
                limits.append("Supplied observation directions, normalization, and study identities have not been independently verified; direction differences are reported without adjudication.")
            elif records:
                actual_scopes = _unique([f"{r.source}: {_scope(r)}" for r in records])
                summary += f" {side} available material: " + "; ".join(actual_scopes) + "."
            if records:
                summary += f" {side} source findings:" + _preview(
                    [f"[{r.id}] {_finding(r).summary}" for r in records[:2]], len(records))
        if left.entity != right.entity:
            limits.append("The two sides concern different declared entities; they are not biological replicates or evidence of the same molecular effect.")
        if left.species != right.species:
            limits.append("Species remain separate. Orthology or sequence identity alone does not establish a conserved response.")
        if left.modality != right.modality:
            limits.append("Modalities remain separate endpoints; RNA, protein, fitness, and phenotype values are not interchangeable activity scores.")
        if left.context != right.context or left.host_species != right.host_species or left.condition != right.condition or left.tissue != right.tissue:
            limits.append("Context, tissue, condition, and host differences are retained; no shared normalization or comparable exposure is inferred.")
        if spec.cross_species_basis or spec.context_alignment_basis:
            limits.append("Any comparison basis supplied in the plan is a user declaration, not a validated biological alignment.")
        if spec.require_matched_subjects:
            limits.append("Matched-subject comparison was requested. Cohort summaries cannot establish pairing; supplied subject/sample IDs require separate verification, and no pairing is inferred here.")
        comparisons.append(ResearchComparison(id=spec.id, left_evidence_ids=lc.evidence_ids,
                                              right_evidence_ids=rc.evidence_ids, summary=summary,
                                              limitations=_unique(limits)))
    return comparisons


def investigate(plan: ResearchPlan, bundle: EvidenceBundle) -> InvestigationAssessment:
    """Summarize sources and account for research scope without qualifying biology."""
    findings = [_finding(record) for record in bundle.records]
    coverage = [_coverage(requirement, bundle, plan) for requirement in plan.requirements]
    investigated = _investigated_entities(bundle)
    if plan.pathway and set(plan.pathway.genes).issubset(investigated):
        # Membership is an explicit input, not a discovered activity measurement.
        # The current provider retrieves members; research can finish at that scope.
        investigated.add(plan.pathway.id)
    expected = set(plan.genes) | {r.entity for r in plan.requirements}
    missing = sorted(expected - investigated)
    blockers = [gap for gap in bundle.gaps if _blocking(gap)]
    checks = [
        CheckResult(id="research_performed", passed=bool(investigated),
                    evidence_ids=[r.id for r in bundle.records if r.source != "mygene"],
                    detail="Research material or completed no-hit searches must exist; identifier-only, all-skipped, or empty collections are insufficient."),
        CheckResult(id="planned_entities_accounted", passed=not missing,
                    detail="Every planned entity has source research or a completed no-hit search; a supplied versioned pathway can be accounted for through all of its member searches." if not missing else
                    "No research material or completed no-hit search for: " + ", ".join(missing) + "."),
        CheckResult(id="retrieval_integrity", passed=not blockers,
                    detail="No unaccounted retrieval failures or unsupported results; bounded search limits remain explicit." if not blockers else
                    "Incomplete retrieval: " + "; ".join(f"{g.code}: {g.detail}" for g in blockers) + "."),
    ]
    for requirement, scope in zip(plan.requirements, coverage):
        checks.append(CheckResult(id=f"research_scope:{requirement.id}", passed=requirement.entity in investigated,
                                  required=requirement.required, evidence_ids=scope.evidence_ids,
                                  detail=f"Scope review is {scope.status}. Gaps are reported; this check does not require biological proof or a minimum number of studies."))
    limitations = [
        "Research completion means source material and research gaps were accounted for, not that a molecular effect was confirmed.",
        "Database measurements and summaries are usable research findings at their reported scope. The background label distinguishes them from separately supplied normalized observations; it does not mean non-empirical or unusable.",
        "This step does not extract additional empirical observations or independently validate source measurements.",
        "Source not_found means no returned database record; skipped means no query was performed. Neither is a biological negative.",
    ]
    limitations += [f"{g.code}: {g.detail}" for g in bundle.gaps]
    limitations += [f"{c.requirement_id}: {c.status}; requested scope has no exact matching record." for c in coverage if c.status != "addressed"]
    if plan.assumptions:
        limitations += ["Unverified planning assumption: " + value for value in plan.assumptions]
    limitations += plan.claims_to_avoid
    if plan.pathway:
        limitations.append(f"{plan.pathway.id}: supplied {plan.pathway.source} membership version {plan.pathway.version} defines the member-based investigation scope, not measured pathway activity or preservation.")
    next_steps = []
    for gap in blockers:
        action = "Retry" if gap.retryable else "Resolve"
        next_steps.append(f"{action} {gap.code} for {gap.gene or 'the investigation'} / {gap.source or 'collection'}: {gap.detail}")
    for gap in bundle.gaps:
        if gap.code in {"source_truncated", "source_may_be_truncated"}:
            next_steps.append(f"Expand or paginate the bounded {gap.source or 'source'} search for {gap.gene or 'the investigation'} if exhaustive coverage is needed: {gap.detail}")
    for entity in missing:
        next_steps.append(f"Collect source material or record an explicit completed no-hit search for {entity}; skipped queries do not satisfy this step.")
    for requirement, scope in zip(plan.requirements, coverage):
        if scope.status != "addressed":
            next_steps.append(f"For {requirement.id}, obtain or review evidence specific to {requirement.entity} ({_scope(requirement)}) if a biological comparison is needed; current evidence remains {scope.status}.")
    if any(c.require_matched_subjects for c in plan.comparisons):
        next_steps.append("For requested matched comparisons, obtain study, subject, specimen, and time-point provenance before assessing within-subject agreement.")
    met = all(check.passed for check in checks if check.required)
    reason = ("Investigation completed: every planned entity was researched and source outcomes, descriptive comparisons, and scope limits were reported. No biological verdict is implied."
              if met else "Investigation remains partial: " + " ".join(check.detail for check in checks[:3] if not check.passed))
    return InvestigationAssessment(criteria_met=met, checks=checks, findings=findings, coverage=coverage,
                                   comparisons=_comparisons(plan, bundle, coverage), limitations=_unique(limitations),
                                   next_steps=_unique(next_steps), completion_reason=reason)
