import asyncio
import copy

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from coordinator.api import create_app
from coordinator.models import ChatSubmission, IntakeDecision, InvestigationRequest
from coordinator.service import FileStore, LocalService
from examples.build_fixture import fixture


def package():
    record = {"status": "ok", "data": {}, "retrieved_at": "2026-09-22"}
    return {"schema_version": "0.1", "run": {"run_id": "reference-test"}, "gene": record,
            "sources": {"ensembl_orthology": {"mouse": record}, "gtex": record, "impc": record,
                        "opentargets": record, "pubmed": record}, "summary": {}, "missing": []}


class Evidence:
    def __init__(self):
        self.genes = []

    async def fetch(self, gene, disease, run_id):
        self.genes.append(gene)
        return package()


class Model:
    decision = {"intent": "Investigate TYK2 and psoriasis across contexts", "genes": ["TYK2"],
                "disease": "psoriasis", "next_step": "explore", "message": "I’ll first gather background evidence.", "criteria": []}

    def __init__(self, budget):
        self.calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    async def intake(self, messages, previous_request):
        self.calls += 1
        self.usage["input_tokens"] += 100
        return copy.deepcopy(self.decision)

    async def interpret(self, intent, findings, reference_packages):
        self.calls += 1
        return {"summary": "The evidence collected is background only; comparisons remain unavailable.",
                "interpretations": [{"criterion_id": f["criterion_id"], "finding": f["finding"],
                                     "explanation": "No study measurements supplied.", "evidence_ids": []} for f in findings],
                "reference_notes": []}


async def completed(service, run_id):
    for _ in range(200):
        state = await service.get(run_id)
        if state["status"] in {"complete", "partial", "failed", "needs_input"}:
            return state
        await asyncio.sleep(.01)
    raise AssertionError("Worker did not stop")


@pytest.mark.asyncio
async def test_prompt_builds_internal_contract_and_exploration_never_validates(tmp_path):
    provider = Evidence()
    service = LocalService(FileStore(tmp_path), provider, Model)
    initial = await service.start_chat(ChatSubmission(prompt="Investigate TYK2 in psoriasis"))
    assert initial["contract_hash"] is None
    state = await completed(service, initial["id"])
    assert state["request"]["intent"] == Model.decision["intent"]
    assert state["request"]["genes"] == ["TYK2"]
    assert state["contract_hash"] == InvestigationRequest.model_validate(state["request"]).digest()
    assert state["status"] == "partial"
    assert state["usage"]["model_calls"] == 2
    assert provider.genes == ["TYK2"]
    assert all(c["finding"] == "not_assessable" for c in state["report"]["contexts"].values())
    assert "no numerical biological claim" in state["chat"]["reply"]
    await service.close()


@pytest.mark.asyncio
async def test_clarification_keeps_conversation_without_executing_tools(tmp_path):
    class Clarify(Model):
        decision = {**Model.decision, "genes": [], "next_step": "clarify", "message": "Which gene or target do you mean?"}
    provider = Evidence()
    service = LocalService(FileStore(tmp_path), provider, Clarify)
    started = await service.start_chat(ChatSubmission(prompt="Investigate a signaling pathway"))
    state = await completed(service, started["id"])
    assert state["status"] == "needs_input"
    assert state["contract_hash"] is None
    assert not provider.genes
    service.reasoner_factory = Model
    next_run = await service.start_chat(ChatSubmission(prompt="TYK2 in psoriasis", previous_investigation_id=state["id"]))
    followup = await completed(service, next_run["id"])
    assert followup["status"] == "partial"
    assert followup["chat"]["parent_id"] == state["id"]
    assert followup["chat"]["messages"][0]["content"] == "Investigate a signaling pathway"
    assert (await service.get(state["id"])) == state  # A reply never mutates the previous result.
    await service.close()


@pytest.mark.asyncio
async def test_drafted_rules_need_explicit_confirmation_and_cannot_invent_data(tmp_path):
    class Draft(Model):
        decision = {**Model.decision, "next_step": "propose_criteria", "criteria": fixture()["criteria"]}
    service = LocalService(FileStore(tmp_path), Evidence(), Draft)
    started = await service.start_chat(ChatSubmission(prompt="Use the comparison rules described above"))
    draft = await completed(service, started["id"])
    assert draft["status"] == "needs_input"
    assert draft["chat"]["awaiting_confirmation"]
    assert not draft["request"]["criteria_confirmed"]
    assert draft["usage"]["tool_calls"] == 0
    confirmed = await service.start_chat(ChatSubmission(prompt="Use these criteria", previous_investigation_id=draft["id"]))
    final = await completed(service, confirmed["id"])
    assert final["request"]["criteria_confirmed"]
    assert final["request"]["criteria"] == draft["request"]["criteria"]
    assert final["request"]["observations"] == []
    assert final["status"] == "partial"
    assert all(c["finding"] == "not_assessable" for c in final["report"]["contexts"].values())
    malicious = {**Draft.decision, "observations": fixture()["observations"]}
    with pytest.raises(ValueError):
        IntakeDecision.model_validate(malicious)
    await service.close()


@pytest.mark.asyncio
async def test_disabled_model_is_explicit_and_demo_still_runs(tmp_path):
    service = LocalService(FileStore(tmp_path), reasoner_factory=None)
    started = await service.start_chat(ChatSubmission(prompt="Investigate TYK2"))
    failed = await completed(service, started["id"])
    assert failed["status"] == "failed"
    assert "disabled" in failed["chat"]["reply"]
    started = await service.start_chat(ChatSubmission(prompt="Show the synthetic investigation", demo=True))
    demo = await completed(service, started["id"])
    assert demo["status"] == "complete"
    assert demo["report"]["origins"] == ["synthetic_fixture"]
    assert "fabricated measurements" in demo["chat"]["reply"]
    assert demo["usage"]["model_calls"] == 0
    await service.close()


def test_chat_http_auth_and_parent_validation(tmp_path):
    service = LocalService(FileStore(tmp_path), reasoner_factory=None)
    with TestClient(create_app(service, token="test")) as client:
        assert client.post("/chat", json={"prompt": "hello"}).status_code == 401
        headers = {"Authorization": "Bearer test"}
        assert client.post("/chat", json={"prompt": "hi"}, headers=headers).status_code == 422
        assert client.post("/chat", json={"prompt": "hello", "previous_investigation_id": "bad"}, headers=headers).status_code == 404
        assert client.post("/chat", json={"prompt": "Show a demo", "demo": True}, headers=headers).status_code == 202


@pytest.mark.asyncio
async def test_mcp_accepts_same_prompt_request(tmp_path):
    service = LocalService(FileStore(tmp_path), Evidence(), Model)
    app = create_app(service)
    async with Client(app.state.mcp) as client:
        result = await client.call_tool("start_investigation", {"request": {"prompt": "Investigate TYK2 in psoriasis"}})
        assert not result.is_error
        state = await completed(service, result.structured_content["id"])
        assert state["status"] == "partial"
        assert state["request"]["phase"] == "exploration"
    await service.close()
