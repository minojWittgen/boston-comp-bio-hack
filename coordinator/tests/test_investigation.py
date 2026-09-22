"""Offline investigation tests using real package adaptation, not invented verdicts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from coordinator.evidence import adapt_packages
from coordinator.investigation import investigate
from coordinator.models import EvidenceBundle, EvidenceRequirement, Gap, ResearchPlan, Submission
from coordinator.tests.test_evidence import package, source


def plan(**updates):
    values = dict(question="Investigate TYK2 across species and patient contexts.", genes=["TYK2"], requirements=[
        EvidenceRequirement(id="patient", title="Patient RNA", entity="TYK2", species="homo_sapiens",
                            context="patient", modality="RNA", endpoint="relative_abundance", condition="psoriasis", tissue="skin"),
        EvidenceRequirement(id="mouse", title="Mouse RNA", entity="TYK2", species="mus_musculus",
                            context="in_vivo", modality="RNA", endpoint="relative_abundance"),
    ], comparisons=[dict(id="mouse_patient", left="mouse", right="patient")])
    values.update(updates)
    return ResearchPlan.model_validate(values)


def test_adapted_measurements_are_useful_without_promotion_or_mutation():
    raw = package()
    raw["sources"]["hpa_cell_lines"] = source("hpa_cell_lines", {
        "rna": {"cell_line_distribution": "Detected in many", "cell_line_specific_ntpm": "A549: 12.34"},
        "protein": {"subcellular_location": ["Nucleoplasm"]}})
    raw["sources"]["hpa_pathology"] = source("hpa_pathology", {
        "cancer_rna_distribution": "Detected in all", "cancer_rna_specificity": "Low cancer specificity",
        "has_cancer_rna": True, "disease_involvement": ["breast cancer"]})
    raw["sources"]["opentargets_depmap"] = source("opentargets_depmap", {
        "n_tissues": 1, "tissues": [{"tissueName": "Lung", "screens": [{"cellLineName": "A549", "geneEffect": -0.71234, "expression": 7.891}]}]})
    raw["sources"]["impc"]["data"]["hits"] = [{"mp_term_name": "abnormal immune response", "p_value": .000013}]
    bundle = adapt_packages([raw])
    before = bundle.model_dump()
    research_plan = plan()
    result = investigate(research_plan, bundle)
    assert result.criteria_met
    assert len(result.findings) == len(bundle.records)
    summaries = {f.source: f.summary for f in result.findings}
    assert "5.2 TPM" in summaries["gtex"]
    assert "0.7" in summaries["opentargets"]
    assert "1.3e-05" in summaries["impc"]
    assert "12.34" in summaries["hpa_cell_lines"]
    assert "-0.71234" in summaries["opentargets_depmap"] and "7.891" in summaries["opentargets_depmap"]
    assert "12345" in summaries["pubmed"]
    assert "breast cancer" in summaries["hpa_pathology"]
    assert bundle.model_dump() == before
    assert all(r.level == "background" and r.direction is None and r.subject_id is None for r in bundle.records)
    patient = next(c for c in result.coverage if c.requirement_id == "patient")
    assert patient.status == "limited" and "condition" in patient.detail and "tissue" in patient.detail
    ids = {r.id: r for r in bundle.records}
    comparison = result.comparisons[0]
    assert {ids[i].source for i in comparison.left_evidence_ids} == {"impc"}
    assert {ids[i].source for i in comparison.right_evidence_ids} == {"hpa_pathology"}
    assert "abnormal immune response" in comparison.summary and "breast cancer" in comparison.summary


def test_unrelated_species_is_limited_not_matched_scope():
    bundle = adapt_packages([package()])
    exact_mouse = next(r for r in bundle.records if r.source == "impc")
    bundle.records = [exact_mouse]
    result = investigate(plan(), bundle)
    patient = next(c for c in result.coverage if c.requirement_id == "patient")
    assert patient.status == "limited"
    assert "species: requested homo_sapiens, returned mus_musculus" in patient.detail


def test_every_planned_gene_needs_research():
    result = investigate(plan(genes=["TYK2", "STAT3"]), adapt_packages([package()]))
    assert not result.criteria_met
    assert "STAT3" in result.completion_reason


@pytest.mark.parametrize("gap", [
    Gap(code="source_error", detail="service down", gene="TYK2", source="gtex", retryable=True),
    Gap(code="source_missing", detail="required source envelope absent", gene="TYK2", source="gtex"),
    Gap(code="unsupported_source", detail="no source adapter", gene="TYK2", source="new_source"),
    Gap(code="budget_exhausted", detail="call budget reached", gene="TYK2"),
])
def test_technical_and_unsupported_results_stay_partial_but_findings_survive(gap):
    bundle = adapt_packages([package()])
    bundle.gaps.append(gap)
    result = investigate(plan(), bundle)
    assert not result.criteria_met and result.findings
    assert any(gap.code in s for s in result.next_steps)


def test_bounded_results_complete_with_honest_search_limits():
    raw = package()
    raw["sources"]["pubmed"]["data"]["count"] = 800
    raw["sources"]["opentargets"]["data"]["associatedDiseases"]["count"] = 300
    bundle = adapt_packages([raw])
    result = investigate(plan(), bundle)
    assert result.criteria_met
    assert any("source_truncated" in s for s in result.limitations)
    assert any("paginate" in s for s in result.next_steps)
    assert "800" in next(f.summary for f in result.findings if f.source == "pubmed")


@pytest.mark.parametrize("status,complete", [("not_found", True), ("skipped", False), ("error", False)])
def test_explicit_no_hits_are_distinct_from_unperformed_and_failed_searches(status, complete):
    raw = package()
    for name, value in raw["sources"].items():
        if name == "ensembl_orthology":
            for item in value.values():
                item.update(status=status, data={})
        else:
            value.update(status=status, data={})
    result = investigate(plan(), adapt_packages([raw]))
    assert result.criteria_met is complete
    assert all(c.status == "unavailable" and not c.evidence_ids for c in result.coverage)
    assert any(f"source_{status}" in s for s in result.limitations)
    assert "Neither is a biological negative" in " ".join(result.limitations)


def test_empty_bundle_never_completes():
    assert not investigate(plan(), EvidenceBundle()).criteria_met


def test_supplied_opposing_observations_and_patient_identity_stay_visible():
    path = Path(__file__).parents[1] / "examples" / "cross-context-conflict.json"
    submission = Submission.model_validate(json.loads(path.read_text()))
    request = submission.request
    research_plan = ResearchPlan(question=request.question, genes=request.genes, disease=request.disease,
                                 requirements=request.requirements, comparisons=request.comparisons)
    bundle = EvidenceBundle(records=submission.observations)
    original = deepcopy(bundle.model_dump())
    result = investigate(research_plan, bundle)
    assert result.criteria_met
    comparison = next(c for c in result.comparisons if c.id == "vitro_to_vivo")
    assert "increase" in comparison.summary and "decrease" in comparison.summary
    paired = next(c for c in result.comparisons if c.id == "patient_multimodal")
    assert any("no pairing is inferred" in text for text in paired.limitations)
    assert bundle.model_dump() == original
    assert "biological verdict" in result.completion_reason


def test_versioned_member_based_pathway_research_can_complete_without_activity_claim():
    pathway = dict(id="R-HSA-1234", source="Reactome", version="90", genes=["TYK2"])
    requirement = EvidenceRequirement(id="pathway", title="Patient pathway RNA", entity=pathway["id"],
                                      species="homo_sapiens", context="patient", modality="RNA", endpoint="pathway_activity")
    research_plan = plan(pathway=pathway, requirements=[requirement], comparisons=[])
    result = investigate(research_plan, adapt_packages([package()]))
    assert result.criteria_met
    assert result.coverage[0].status == "limited"
    assert "version 90" in result.coverage[0].detail
    assert "does not measure pathway activity" in result.coverage[0].detail
    assert all(f.entity == "TYK2" for f in result.findings)
    missing_member = research_plan.model_copy(update={"pathway": research_plan.pathway.model_copy(update={"genes": ["TYK2", "STAT3"]})})
    assert not investigate(missing_member, adapt_packages([package()])).criteria_met
