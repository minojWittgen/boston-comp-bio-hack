import asyncio
import copy
import uuid

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from coordinator.api import create_app
from coordinator.engine import execute, initial_state, validate_interpretation
from coordinator.models import InvestigationRequest
from coordinator.service import FileStore, LocalService
from examples.build_fixture import fixture


async def run_case(payload, provider=None):
    request = InvestigationRequest.model_validate(payload)
    snapshots = []

    async def save(state):
        snapshots.append(copy.deepcopy(state))

    result = await execute(initial_state(str(uuid.uuid4()), request), save, provider)
    assert all(s["contract_hash"] == request.digest() for s in snapshots)
    return result


@pytest.mark.asyncio
async def test_valid_three_context_numerical_comparison():
    result = await run_case(fixture())
    assert result["status"] == "complete"
    assert set(result["report"]["contexts"]) == {"in_vitro", "in_vivo", "patients"}
    assert all(f["finding"] == "supported" for f in result["report"]["criteria"])
    calculation = result["report"]["criteria"][0]["calculations"][0]
    assert calculation["mean_log2_fold_change"] == pytest.approx(0.9951668101)
    assert calculation["n_pairs"] == 3
    assert len(calculation["individuals"]) == 3
    assert result["report"]["origins"] == ["synthetic_fixture"]


@pytest.mark.asyncio
async def test_invalid_patient_pairing_is_not_support():
    payload = fixture()
    for row in payload["observations"]:
        if row["context"] == "patients" and row["modality"] == "protein":
            row["subject_id"] += "-different-person"
            row["specimen_id"] += "-different-person"
    result = await run_case(payload)
    assert result["status"] == "partial"
    patient = result["report"]["criteria"][2]
    assert patient["finding"] == "not_assessable"
    assert patient["checks"][0]["code"] == "patient_pairing"


@pytest.mark.asyncio
async def test_recover_metadata_then_preserve_disagreement():
    payload = fixture()
    entries = []
    for row in payload["observations"]:
        if row["context"] == "patients":
            entries.append({"observation_id": row["id"], "subject_id": row["subject_id"],
                            "specimen_id": row["specimen_id"], "timepoint": row["timepoint"]})
            row["subject_id"] = None
            if row["modality"] == "protein" and row["condition"] == "exposed":
                row["value"] = 100 / row["value"]
    payload["available_sample_maps"] = [{"id": "map1", "source": "synthetic://sample-map", "entries": entries}]
    result = await run_case(payload)
    assert result["status"] == "complete"
    assert result["report"]["contexts"]["patients"]["finding"] == "conflicting"
    assert any(e["action"] == "read_sample_map" for e in result["events"])
    assert result["usage"]["tool_calls"] == 1
    assert result["request"]["observations"][-1]["subject_id"] is None
    assert result["report"]["observations"][-1]["subject_id"] is not None


@pytest.mark.asyncio
async def test_missing_context_stays_visible():
    payload = fixture()
    payload["criteria"] = payload["criteria"][:2]
    result = await run_case(payload)
    assert result["status"] == "partial"
    assert result["report"]["contexts"]["patients"]["finding"] == "not_assessable"


@pytest.mark.asyncio
async def test_unconfirmed_criteria_do_not_execute():
    payload = fixture()
    payload["criteria_confirmed"] = False
    result = await run_case(payload)
    assert result["status"] == "needs_input"
    assert result["usage"]["tool_calls"] == 0


@pytest.mark.asyncio
async def test_duplicate_replicates_rejected():
    payload = fixture()
    duplicate = copy.deepcopy(payload["observations"][0])
    duplicate["id"] = "copy-from-another-portal"
    duplicate["source"] = "synthetic://another-portal"
    payload["observations"].append(duplicate)
    result = await run_case(payload)
    assert result["report"]["criteria"][0]["finding"] == "not_assessable"
    assert result["report"]["criteria"][0]["checks"][0]["code"] == "independent_replicates"


@pytest.mark.asyncio
async def test_abundance_cannot_establish_activity():
    payload = fixture()
    payload["criteria"][0]["quantity"] = "activity"
    result = await run_case(payload)
    assert result["report"]["criteria"][0]["finding"] == "not_assessable"


@pytest.mark.asyncio
async def test_unreviewed_species_mapping_blocks_comparison():
    payload = fixture()
    payload["species_mappings"][0]["reviewed"] = False
    result = await run_case(payload)
    assert result["report"]["contexts"]["in_vivo"]["finding"] == "not_assessable"


@pytest.mark.asyncio
async def test_same_symbol_does_not_bypass_species_mapping():
    payload = fixture()
    for row in payload["observations"]:
        if row["species"] == "mouse":
            row["feature"] = "DEMO1"
    payload["species_mappings"] = []
    result = await run_case(payload)
    assert result["report"]["contexts"]["in_vivo"]["finding"] == "not_assessable"


@pytest.mark.asyncio
async def test_insufficient_time_is_partial_and_preserves_completed_checks(monkeypatch):
    import coordinator.engine as engine
    original_timeout = asyncio.timeout
    monkeypatch.setattr(engine.asyncio, "timeout", lambda seconds: original_timeout(0.02))
    class Slow:
        async def fetch(self, *args):
            await asyncio.sleep(1)
    payload = fixture()
    payload.update(retrieve_reference=True, genes=["TYK2"])
    result = await run_case(payload, Slow())
    assert result["status"] == "partial"
    assert result["report"]["criteria"][0]["calculations"]
    assert "time limit" in result["errors"][0]["reason"]


@pytest.mark.asyncio
async def test_technical_retrieval_error_is_failed_when_required():
    class Broken:
        async def fetch(self, *args):
            raise RuntimeError("source offline")
    payload = fixture()
    payload.update(retrieve_reference=True, reference_required=True, genes=["TYK2"])
    result = await run_case(payload, Broken())
    assert result["status"] == "failed"
    assert result["report"]["contexts"]["patients"]["finding"] == "supported"
    assert result["report"]["reference_failures"][0]["status"] == "error"


@pytest.mark.asyncio
async def test_tool_budget_stops_follow_up_without_hiding_gap():
    payload = fixture()
    # Two separate maps needed; one operation allowed.
    maps = []
    for row in payload["observations"][:2]:
        maps.append({"id": row["id"], "source": "synthetic://map", "entries": [
            {"observation_id": row["id"], "subject_id": row["subject_id"], "specimen_id": row["specimen_id"], "timepoint": row["timepoint"]}]})
        row["subject_id"] = None
    payload["available_sample_maps"] = maps
    payload["budget"]["max_tool_calls"] = 1
    result = await run_case(payload)
    assert result["status"] == "partial"
    assert result["usage"]["tool_calls"] == 1


@pytest.mark.asyncio
async def test_model_cannot_change_findings_or_invent_citations():
    result = await run_case(fixture())
    findings = result["report"]["criteria"]
    valid = {"summary": "Synthetic example", "interpretations": [
        {"criterion_id": f["criterion_id"], "finding": f["finding"], "explanation": "Conditional sample-level support.", "evidence_ids": f["evidence_ids"][:1]}
        for f in findings]}
    assert validate_interpretation(valid, findings) == valid
    invalid = copy.deepcopy(valid)
    invalid["interpretations"][0]["evidence_ids"] = ["invented"]
    with pytest.raises(ValueError):
        validate_interpretation(invalid, findings)
    invalid = copy.deepcopy(valid)
    invalid["interpretations"][0]["finding"] = "conflicting"
    with pytest.raises(ValueError):
        validate_interpretation(invalid, findings)


def test_http_auth_schema_and_round_trip(tmp_path):
    service = LocalService(FileStore(tmp_path), reasoner_factory=None)
    with TestClient(create_app(service, token="test-access")) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/investigations", json=fixture()).status_code == 401
        headers = {"Authorization": "Bearer test-access"}
        assert client.post("/investigations", json={"intent": "x"}, headers=headers).status_code == 422
        started = client.post("/investigations", json=fixture(), headers=headers)
        assert started.status_code == 202
        run_id = started.json()["id"]
        for _ in range(30):
            state = client.get(f"/investigations/{run_id}", headers=headers).json()
            if state["status"] == "complete":
                break
        assert state["status"] == "complete"
        assert client.get("/investigations/not-an-id", headers=headers).status_code == 404


@pytest.mark.asyncio
async def test_mcp_and_http_share_state(tmp_path):
    service = LocalService(FileStore(tmp_path), reasoner_factory=None)
    app = create_app(service)
    async with Client(app.state.mcp) as client:
        listing = await client.list_tools()
        assert {t.name for t in listing.tools} == {"start_investigation", "get_investigation"}
        started = await client.call_tool("start_investigation", {"request": fixture()})
        assert not started.is_error
        run_id = started.structured_content["id"]
        for _ in range(30):
            output = await client.call_tool("get_investigation", {"investigation_id": run_id})
            if output.structured_content["status"] == "complete":
                break
            await asyncio.sleep(0.01)
        assert output.structured_content == await service.get(run_id)
        assert output.structured_content["status"] == "complete"
    await service.close()
