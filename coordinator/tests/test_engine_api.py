from fastapi.testclient import TestClient

from coordinator.api import create_app
from coordinator.engine import Coordinator, plan_digest
from coordinator.evidence import adapt_packages
from coordinator.models import (EvidenceBundle, EvidenceRecord, EvidenceRequirement,
    Gap, InvestigationRequest, ResearchPlan, Submission)
from coordinator.planner import ExplicitPlanner
from coordinator.store import FileRunStore
from coordinator.tests.test_evidence import package


def submission():
    return Submission(request=InvestigationRequest(question="Is the measured signal present?", genes=["TYK2"],
        requirements=[EvidenceRequirement(id="r1", title="Patient RNA", entity="TYK2",
            species="homo_sapiens", context="patient", modality="RNA", endpoint="expression")]))


def observation():
    return EvidenceRecord(id="observed-1", source="synthetic-test", provenance=["fixture://study-1"],
        entity="TYK2", species="homo_sapiens", context="patient", modality="RNA", endpoint="expression",
        level="observation", study_id="study-1", subject_id="person-1", specimen_id="sample-1", timepoint="baseline")


class Provider:
    def __init__(self, always_fail=False):
        self.calls = 0
        self.always_fail = always_fail

    def fetch(self, symbol, disease, mode, run_id):
        self.calls += 1
        if self.always_fail:
            raise TimeoutError("example upstream credential must not appear in output")
        return {"attempt": self.calls}


def engine(tmp_path, provider=None, planner=None):
    return Coordinator(planner or ExplicitPlanner(), provider or Provider(), FileRunStore(tmp_path))


def test_retry_preserves_criteria_and_recovers_only_technical_gap(tmp_path, monkeypatch):
    def adapt(packages):
        if packages[0]["attempt"] == 1:
            return EvidenceBundle(gaps=[Gap(code="source_error", gene="TYK2", retryable=True, detail="Timeout")])
        return adapt_packages([package()])
    monkeypatch.setattr("coordinator.engine.adapt_packages", adapt)
    run = engine(tmp_path)
    item = submission()
    result = run.execute(run.create(item).run_id, item)
    assert result.status == "complete"
    assert result.attempts == 2
    assert result.plan_sha256 == plan_digest(ExplicitPlanner().plan(item.request))
    assert result.investigation.criteria_met
    assert result.assessment.conclusion == "not_assessable"  # coverage is not a biological comparison
    assert not result.assessment.criteria_met  # source investigation does not require observations
    assert any(e["stage"] == "targeted_follow_up" for e in result.events)


def test_unavailable_required_evidence_stops_after_one_revision(tmp_path):
    provider = Provider(always_fail=True)
    run = engine(tmp_path, provider)
    item = submission()
    result = run.execute(run.create(item).run_id, item)
    assert result.status == "partial"
    assert provider.calls == 2
    assert not result.assessment.criteria_met
    assert "credential" not in result.model_dump_json()


def test_frozen_plan_mutation_is_a_failure(tmp_path, monkeypatch):
    run = engine(tmp_path)
    item = submission()
    monkeypatch.setattr("coordinator.engine.adapt_packages", lambda _: EvidenceBundle())
    from coordinator.checks import assess
    def mutating_assessment(plan, bundle):
        result = assess(plan, bundle)
        plan.requirements[0].required = False
        return result
    monkeypatch.setattr("coordinator.engine.assess", mutating_assessment)
    result = run.execute(run.create(item).run_id, item)
    assert result.status == "failed"
    assert "Frozen" in result.error


def test_budget_prevents_new_fetches_and_never_claims_complete(tmp_path):
    run = engine(tmp_path)
    run.budget_seconds = 0
    item = submission()
    result = run.execute(run.create(item).run_id, item)
    assert run.provider.calls == 0
    assert result.status == "partial"
    assert result.evidence.gaps[0].code == "budget_exhausted"


def test_explicit_collection_mode_is_preserved(tmp_path, monkeypatch):
    calls = []
    provider = Provider()
    def fetch(symbol, disease, mode, run_id):
        calls.append(mode)
        return {}
    provider.fetch = fetch
    monkeypatch.setattr("coordinator.engine.adapt_packages", lambda _: EvidenceBundle())
    run = engine(tmp_path, provider)
    item = submission()
    item.request.mode = "eval"
    assert run.execute(run.create(item).run_id, item).status == "partial"
    assert calls == ["eval"]


def test_api_start_poll_report_and_token(tmp_path, monkeypatch):
    monkeypatch.setattr("coordinator.engine.adapt_packages", lambda _: EvidenceBundle())
    client = TestClient(create_app(engine(tmp_path), api_token="test-token"))
    assert client.get("/health").status_code == 200
    assert client.post("/investigations", json=submission().model_dump()).status_code == 401
    headers = {"Authorization": "Bearer test-token"}
    response = client.post("/investigations", headers=headers, json=submission().model_dump())
    assert response.status_code == 202
    result = client.get(response.json()["status_url"], headers=headers)
    assert result.status_code == 200
    assert result.json()["status"] == "partial"
    assert result.json()["plan_sha256"]
    assert client.get(response.json()["status_url"] + "/report", headers=headers).status_code == 200
    assert client.get("/investigations/invalid", headers=headers).status_code == 404


def test_api_invalid_schema_and_failed_dispatch(tmp_path):
    def fail_dispatch(*_):
        raise RuntimeError("unavailable")
    client = TestClient(create_app(engine(tmp_path), dispatch=fail_dispatch))
    assert client.post("/investigations", json={"request": {"question": "x"}}).status_code == 422
    assert client.post("/investigations", json=submission().model_dump()).status_code == 503
    saved = list(tmp_path.glob("*.json"))
    assert len(saved) == 1
    assert '"dispatch_failed"' in saved[0].read_text()
