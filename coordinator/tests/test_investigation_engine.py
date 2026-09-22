"""Offline integration checks for research completion, not biological validation.

Fixtures below are deliberately synthetic source responses. They exercise the real
package adapter and coordinator without a model, network, or supplied observations.
"""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from coordinator.api import create_app
from coordinator.engine import Coordinator, plan_digest
from coordinator.models import (
    ComparisonSpec, EvidenceRecord, EvidenceRequirement, InvestigationRequest,
    Submission,
)
from coordinator.planner import ExplicitPlanner
from coordinator.store import FileRunStore


def source(name, data=None, status="ok", **extra):
    return {
        "source": name, "status": status, "query": {}, "data": data or {},
        "error": None, "source_version": "synthetic-v1",
        "retrieved_at": "2026-09-22T12:00:00Z",
        "provenance": [f"fixture://investigation/{name}"], **extra,
    }


def package(symbol="TYK2", disease="psoriasis", mode="explore", run_id="fixture-run"):
    return {
        "schema_version": "0.1",
        "run": {"run_id": run_id, "mode": mode, "disease_query": disease},
        "gene": source("mygene", {
            "symbol": symbol, "ensembl_primary": f"fixture-ensembl-{symbol}", "ambiguous": False,
        }, query={"symbol": symbol}),
        "sources": {
            "ensembl_orthology": {
                species: source("ensembl_orthology", {"orthologs": [{
                    "target_id": f"fixture-{species}-{symbol}", "species": species,
                    "type": "ortholog_one2one",
                }]})
                for species in ("mus_musculus", "rattus_norvegicus", "macaca_mulatta")
            },
            "gtex": source("gtex", {"tissues": [{"tissue": "Lung", "median_tpm": 5.2}]}),
            "impc": source("impc", {"phenotyped": True, "n_tests": 100, "hits": []}),
            "opentargets": source("opentargets", {"associatedDiseases": {
                "count": 1, "rows": [{"score": .7, "disease": {"id": "fixture-disease", "name": disease}}],
            }}),
            "pubmed": source("pubmed", {"count": 1, "pmids": ["12345"]}),
            "hpa_cell_lines": source("hpa_cell_lines", {
                "rna_summary": "Detected in many cell lines", "protein_location": ["nucleus"],
            }),
            "opentargets_depmap": source("opentargets_depmap", {
                "essentiality": [{"cellLine": "fixture-cell-line", "score": -.7}],
            }),
            "hpa_pathology": source("hpa_pathology", {
                "disease_involvement": ["breast cancer"],
                "cancer_rna_specificity": "Low cancer specificity", "has_cancer_rna": True,
                "has_disease_annotation": True,
            }),
        },
    }


def submission(*, genes=None, mode="explore", comparisons=False):
    genes = genes or ["TYK2"]
    requirements = [EvidenceRequirement(
        id=f"{gene}-patient", title=f"Investigate {gene} patient RNA", entity=gene,
        species="homo_sapiens", context="patient", modality="RNA", endpoint="expression",
        condition="psoriasis", tissue="skin", min_studies=2,
    ) for gene in genes]
    pairs = []
    if comparisons:
        requirements.insert(0, EvidenceRequirement(
            id="cell-line", title="Investigate human cell-line RNA", entity=genes[0],
            species="homo_sapiens", context="in_vitro", modality="RNA", endpoint="expression",
        ))
        pairs.append(ComparisonSpec(
            id="cell-line-vs-patient", left="cell-line", right=f"{genes[0]}-patient",
            require_matched_subjects=True,
        ))
    return Submission(request=InvestigationRequest(
        question="Investigate TYK2 findings across cell lines, mice, and psoriasis patients.",
        genes=genes, disease="psoriasis", mode=mode,
        requirements=requirements, comparisons=pairs,
    ))


class PackageProvider:
    def __init__(self, transform=None):
        self.calls = []
        self.returned = []
        self.transform = transform

    def fetch(self, symbol, disease, mode, run_id):
        self.calls.append((symbol, disease, mode, run_id))
        raw = package(symbol, disease, mode, run_id)
        if self.transform:
            raw = self.transform(raw, len(self.calls))
        self.returned.append(deepcopy(raw))
        return raw


def run_investigation(tmp_path, item=None, provider=None, budget_seconds=240):
    item = item or submission()
    provider = provider or PackageProvider()
    coordinator = Coordinator(ExplicitPlanner(), provider, FileRunStore(tmp_path), budget_seconds)
    result = coordinator.execute(coordinator.create(item).run_id, item)
    return coordinator, result


def strict_observation(item):
    # One simple declared observation satisfies the optional old structural check.
    item.request.requirements[0].min_studies = 1
    requirement = item.request.requirements[0]
    return EvidenceRecord(
        id="synthetic-observation", source="synthetic-study", provenance=["fixture://study"],
        entity=requirement.entity, species=requirement.species, context=requirement.context,
        modality=requirement.modality, endpoint=requirement.endpoint,
        condition=requirement.condition, tissue=requirement.tissue,
        level="observation", study_id="synthetic-study-1",
    )


def test_real_adapter_source_findings_complete_without_observations(tmp_path):
    item = submission()
    provider = PackageProvider()
    _, result = run_investigation(tmp_path, item, provider)

    assert item.observations == []
    assert result.status == "complete"
    assert result.investigation.criteria_met
    assert result.investigation.completion_reason
    assert result.assessment is None or not result.assessment.criteria_met
    assert {record.level for record in result.evidence.records} == {"background"}
    evidence_ids = {record.id for record in result.evidence.records}
    assert result.investigation.findings
    assert all(finding.evidence_id in evidence_ids for finding in result.investigation.findings)
    gtex = next(f for f in result.investigation.findings if f.source == "gtex")
    assert "5.2" in gtex.summary
    assert "5.2" in result.report and "TPM" in result.report
    assert result.investigation.limitations
    assert result.investigation.next_steps
    assert result.evidence.raw_packages == provider.returned
    assert result.plan_sha256 == plan_digest(ExplicitPlanner().plan(item.request))


def test_unavailable_biology_is_documented_without_blocking_completed_search(tmp_path):
    def no_hits(raw, _):
        for name, response in raw["sources"].items():
            if name == "ensembl_orthology":
                for species in response:
                    response[species] = source(name, status="not_found")
            else:
                raw["sources"][name] = source(name, status="not_found")
        return raw

    _, result = run_investigation(tmp_path, provider=PackageProvider(no_hits))
    assert result.status == "complete"
    assert result.attempts == 1
    assert result.investigation.criteria_met
    coverage = result.investigation.coverage[0]
    assert coverage.status == "unavailable"
    assert coverage.detail
    assert not coverage.evidence_ids
    assert result.investigation.limitations and result.investigation.next_steps
    assert "source_not_found" in {gap.code for gap in result.evidence.gaps}
    assert result.assessment is None or result.assessment.conclusion == "not_assessable"


def test_bounded_source_results_complete_with_visible_search_limits(tmp_path):
    def bounded(raw, _):
        raw["sources"]["pubmed"]["data"]["count"] = 1000
        raw["sources"]["opentargets"]["data"]["associatedDiseases"]["count"] = 250
        return raw

    _, result = run_investigation(tmp_path, provider=PackageProvider(bounded))
    assert result.status == "complete"
    assert result.attempts == 1
    assert result.investigation.criteria_met
    assert "source_truncated" in {gap.code for gap in result.evidence.gaps}
    assert result.investigation.limitations
    assert "1000" in result.report and "250" in result.report


@pytest.mark.parametrize("recover", [True, False])
def test_technical_retry_is_not_suppressed_by_passing_observation_diagnostic(tmp_path, recover):
    def fail_source(raw, attempt):
        if attempt == 1 or not recover:
            raw["sources"]["gtex"] = source("gtex", status="error", error="synthetic timeout")
        return raw

    item = submission()
    item.observations = [strict_observation(item)]
    provider = PackageProvider(fail_source)
    _, result = run_investigation(tmp_path, item, provider)
    assert result.assessment is None or result.assessment.criteria_met
    assert len(provider.calls) == result.attempts == 2
    assert any(event["stage"] == "targeted_follow_up" for event in result.events)
    assert result.status == ("complete" if recover else "partial")
    assert result.investigation.criteria_met is recover
    if not recover:
        assert "source_error" in {gap.code for gap in result.evidence.gaps}
        assert result.investigation.completion_reason


def test_exhausted_budget_stays_partial_despite_passing_observation_diagnostic(tmp_path):
    item = submission()
    item.observations = [strict_observation(item)]
    coordinator, result = run_investigation(tmp_path, item, budget_seconds=0)
    assert not coordinator.provider.calls
    assert result.status == "partial"
    assert not result.investigation.criteria_met
    assert "budget_exhausted" in {gap.code for gap in result.evidence.gaps}


@pytest.mark.parametrize("failure", ["source_missing", "malformed_source", "malformed_package"])
def test_broken_source_contract_does_not_become_completed_no_hit_search(tmp_path, failure):
    def broken(raw, _):
        if failure == "source_missing":
            del raw["sources"]["gtex"]
        elif failure == "malformed_source":
            raw["sources"]["gtex"]["status"] = "unknown"
        else:
            raw = {"receipt": "/not/an/evidence/package"}
        return raw

    _, result = run_investigation(tmp_path, provider=PackageProvider(broken))
    assert result.status == "partial"
    assert not result.investigation.criteria_met
    assert failure in {gap.code for gap in result.evidence.gaps}


def test_context_comparison_is_descriptive_and_preserves_unpaired_source_scope(tmp_path):
    item = submission(comparisons=True)
    _, result = run_investigation(tmp_path, item)
    assert result.status == "complete"
    comparison = result.investigation.comparisons[0]
    assert comparison.id == "cell-line-vs-patient"
    assert comparison.summary and comparison.limitations
    records = {record.id: record for record in result.evidence.records}
    assert comparison.left_evidence_ids and comparison.right_evidence_ids
    assert all(records[eid].context == "in_vitro" for eid in comparison.left_evidence_ids)
    assert all(records[eid].context == "patient" for eid in comparison.right_evidence_ids)
    assert all(record.subject_id is None and record.specimen_id is None
               and record.direction is None for record in records.values())
    assert result.plan.comparisons[0].require_matched_subjects is True
    assert result.assessment is None or result.assessment.conclusion == "not_assessable"
    assert next(record for record in records.values() if record.source == "impc").species == "mus_musculus"
    assert next(record for record in records.values() if record.source == "gtex").species == "homo_sapiens"
    assert {coverage.requirement_id for coverage in result.investigation.coverage} == {
        requirement.id for requirement in item.request.requirements
    }
    # A completed search cannot imply the requested psoriasis / skin / two-study
    # patient contrast was established by a cancer cohort background record.
    patient_coverage = next(c for c in result.investigation.coverage if c.requirement_id == "TYK2-patient")
    assert patient_coverage.status == "limited"


def test_multigene_collection_preserves_intent_mode_and_source_values(tmp_path):
    item = submission(genes=["TYK2", "JAK1"], mode="eval")
    provider = PackageProvider()
    _, result = run_investigation(tmp_path, item, provider)
    assert result.status == "complete"
    assert [call[:3] for call in provider.calls] == [
        ("TYK2", "psoriasis", "eval"), ("JAK1", "psoriasis", "eval"),
    ]
    assert result.request == item.request
    assert result.plan.requirements == item.request.requirements
    assert result.plan.question == item.request.question
    assert result.evidence.raw_packages == provider.returned
    assert {finding.entity for finding in result.investigation.findings} == {"TYK2", "JAK1"}
    for record in result.evidence.records:
        if record.source == "gtex":
            assert record.payload["source_result"]["data"]["tissues"][0]["median_tpm"] == 5.2


def test_api_returns_completed_research_and_separate_observational_diagnostic(tmp_path):
    coordinator = Coordinator(ExplicitPlanner(), PackageProvider(), FileRunStore(tmp_path))
    client = TestClient(create_app(coordinator))
    item = submission()
    response = client.post("/investigations", json=item.model_dump())
    assert response.status_code == 202
    result = client.get(response.json()["status_url"])
    assert result.status_code == 200
    payload = result.json()
    assert payload["status"] == "complete"
    assert payload["investigation"]["criteria_met"] is True
    assert payload["investigation"]["findings"]
    assert payload["assessment"] is None or payload["assessment"]["criteria_met"] is False
    report = client.get(response.json()["status_url"] + "/report")
    assert report.status_code == 200
    assert "5.2" in report.text


def test_computed_source_investigation_reaches_primary_web_report(tmp_path):
    from streamlit.testing.v1 import AppTest
    from research_app.presentation import assistant_summary, comparison_views, context_coverage
    from research_app.report_ui import markdown_report

    _, result = run_investigation(tmp_path, submission(comparisons=True))
    before = result.model_dump_json()
    assert "Investigation complete" in assistant_summary(result)
    assert context_coverage(result)[2]["limited"] == 1
    assert comparison_views(result)[0]["detail"] == result.investigation.comparisons[0].summary
    assert "5.2" in markdown_report(result)
    with patch("research_app.client.InvestigationClient.get", return_value=result), \
         patch("research_app.client.InvestigationClient.chat", side_effect=AssertionError("No model call")):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[2] / "streamlit_app.py"))
        app.query_params["report"] = result.run_id
        app.run()
        assert not app.exception
        assert [metric.value for metric in app.metric] == ["Finished", "Complete"]
        assert [tab.label for tab in app.tabs] == ["Findings", "Comparisons", "Sources", "Research scope"]
        visible = "\n".join(item.value for item in list(app.markdown) + list(app.caption))
        assert "5.2" in visible and "TPM" in visible
        assert not app.text_input[0].value
    assert result.model_dump_json() == before
