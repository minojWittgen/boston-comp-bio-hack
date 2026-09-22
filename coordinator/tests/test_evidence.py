from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from coordinator.evidence import DirectoryEvidenceProvider, ModalEvidenceProvider, adapt_packages


def source(name, data=None, status="ok", **kwargs):
    return {"source": name, "status": status, "query": {}, "data": data or {},
            "error": None, "source_version": None, "retrieved_at": "2026-09-22T12:00:00Z", **kwargs}


def package():
    return {
        "schema_version": "0.1",
        "run": {"run_id": "run-1", "mode": "explore", "disease_query": "psoriasis"},
        "gene": source("mygene", {"symbol": "TYK2", "ensembl_primary": "ENSG00000105397",
                                    "ambiguous": False}, query={"symbol": "TYK2"}),
        "sources": {
            "ensembl_orthology": {sp: source("ensembl_orthology", {"orthologs": [
                {"target_id": "ortholog-id", "species": sp, "type": "ortholog_one2one"}
            ]}) for sp in ("mus_musculus", "rattus_norvegicus", "macaca_mulatta")},
            "gtex": source("gtex", {"tissues": [{"tissue": "Lung", "median_tpm": 5.2}]}, source_version="gtex_v8"),
            "impc": source("impc", {"phenotyped": True, "n_tests": 100, "hits": []}),
            "opentargets": source("opentargets", {"associatedDiseases": {"count": 1, "rows": [
                {"score": .7, "disease": {"id": "EFO_0000676", "name": "psoriasis"}}
            ]}}),
            "pubmed": source("pubmed", {"count": 1, "pmids": ["12345"]}),
        },
    }


def test_successful_sources_remain_background_not_observations():
    raw = package()
    bundle = adapt_packages([raw])
    assert bundle.package_count == 1 and len(bundle.records) == 8
    assert not bundle.gaps
    assert {r.level for r in bundle.records} == {"background"}
    assert all(r.study_id is None and r.subject_id is None and r.specimen_id is None for r in bundle.records)
    assert all(r.direction is None and not r.provenance for r in bundle.records)
    records = {r.source: r for r in bundle.records}
    assert (records["gtex"].context, records["gtex"].unit) == ("reference", "TPM")
    assert (records["impc"].context, records["impc"].modality) == ("in_vivo", "phenotype")
    assert records["impc"].species == "mus_musculus"
    assert records["gtex"].species == "homo_sapiens"
    assert records["pubmed"].species is None
    assert records["gtex"].payload["source_result"] == raw["sources"]["gtex"]
    raw["sources"]["gtex"]["data"]["tissues"].clear()
    assert records["gtex"].payload["source_result"]["data"]["tissues"]


def test_cell_line_sources_keep_mixed_modality_and_fitness_as_background():
    raw = package()
    raw['sources']['hpa_cell_lines'] = source('hpa_cell_lines', {'rna_summary': 'detected', 'protein_location': ['nucleus']})
    raw['sources']['opentargets_depmap'] = source('opentargets_depmap', {'essentiality': [{'cellLine': 'example', 'score': -0.7}]})
    raw['sources']['hpa_pathology'] = source('hpa_pathology', {'cancer_expression': {'breast cancer': 'example cohort summary'}})
    bundle = adapt_packages([raw])
    records = {r.source: r for r in bundle.records}
    assert not bundle.gaps
    hpa, depmap = records['hpa_cell_lines'], records['opentargets_depmap']
    assert hpa.context == depmap.context == 'in_vitro'
    assert hpa.species == depmap.species == 'homo_sapiens'
    assert hpa.modality is None and depmap.modality is None
    patient = records['hpa_pathology']
    assert patient.context == 'patient' and patient.modality == 'RNA'
    for record in (hpa, depmap, patient):
        assert record.level == 'background'
        assert record.direction is None and record.study_id is None and record.subject_id is None
        assert record.payload['source_result'] == raw['sources'][record.source]


def test_statuses_are_distinct_and_only_error_is_retryable():
    raw = package()
    for name, status in (("gtex", "error"), ("pubmed", "not_found"), ("opentargets", "skipped")):
        raw["sources"][name] = source(name, status=status, error="reason")
    del raw["sources"]["impc"]
    bundle = adapt_packages([raw])
    gaps = {g.code: g for g in bundle.gaps}
    assert set(gaps) == {"source_error", "source_not_found", "source_skipped", "source_missing"}
    assert [g.code for g in bundle.gaps if g.retryable] == ["source_error"]
    assert not {"gtex", "pubmed", "opentargets", "impc"} & {r.source for r in bundle.records}


def test_raw_packages_preserve_failed_skipped_and_missing_metadata_for_audit():
    raw = package()
    raw["sources"]["gtex"] = source("gtex", status="error", query={"ensg": "ENSG00000105397"},
                                     error="upstream unavailable", source_version="gtex_v8")
    raw["sources"]["opentargets"] = source("opentargets", status="skipped", error="disabled in eval")
    raw["sources"]["impc"] = source("impc", {"phenotyped": False}, status="not_found")
    malformed_envelope = {"path": "/data/receipt.json", "missing": ["gtex:error"]}
    bundle = adapt_packages([raw, malformed_envelope])
    assert bundle.raw_packages == [raw, malformed_envelope]
    assert bundle.raw_packages[0]["sources"]["impc"]["data"] == {"phenotyped": False}
    assert bundle.raw_packages[0]["sources"]["gtex"]["retrieved_at"] == "2026-09-22T12:00:00Z"
    raw["sources"]["gtex"]["error"] = "changed after adaptation"
    malformed_envelope["missing"].clear()
    assert bundle.raw_packages[0]["sources"]["gtex"]["error"] == "upstream unavailable"
    assert bundle.raw_packages[1]["missing"] == ["gtex:error"]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), {"not-json"}])
def test_non_json_package_content_is_not_retained_or_adapted(invalid):
    raw = package()
    raw["sources"]["gtex"]["data"]["invalid"] = invalid
    bundle = adapt_packages([raw])
    assert not bundle.raw_packages and not bundle.records
    assert bundle.package_count == 1
    assert len(bundle.gaps) == 1 and bundle.gaps[0].code == "malformed_package"
    assert not bundle.gaps[0].retryable


def test_malformed_receipt_source_and_ambiguous_gene_are_explicit_gaps():
    raw = package()
    raw["gene"]["data"]["ambiguous"] = True
    raw["sources"]["gtex"] = {"status": "ok", "data": []}
    bundle = adapt_packages([{"path": "/data/a.json"}, raw, None])
    assert {g.code for g in bundle.gaps} == {"malformed_package", "ambiguous_gene", "malformed_source"}
    assert not any(g.retryable for g in bundle.gaps)
    assert all(r.level == "background" for r in bundle.records)


def test_ids_are_content_stable_and_truncation_is_visible():
    original = package()
    replay = deepcopy(original)
    replay["run"]["run_id"] = "another-run"
    replay["sources"]["gtex"]["retrieved_at"] = "later"
    replay["sources"]["gtex"]["cache_hit"] = True
    assert len(adapt_packages([original, replay]).records) == 8
    replay["sources"]["gtex"]["data"]["tissues"][0]["median_tpm"] = 10
    replay["sources"]["opentargets"]["data"]["associatedDiseases"]["count"] = 100
    replay["sources"]["pubmed"]["data"]["count"] = 25
    replay["sources"]["impc"]["data"]["hits"] = [{"mp_term_id": "MP:1"}] * 500
    bundle = adapt_packages([original, replay])
    assert len(bundle.records) == 12
    assert {(g.source, g.code) for g in bundle.gaps} == {
        ("opentargets", "source_truncated"), ("pubmed", "source_truncated"),
        ("impc", "source_may_be_truncated")}


def test_preserves_provided_provenance_without_inventing_study():
    raw = package()
    raw["sources"]["gtex"]["provenance"] = ["https://example.org/source-record"]
    record = next(r for r in adapt_packages([raw]).records if r.source == "gtex")
    assert record.provenance == ["https://example.org/source-record"]
    assert record.study_id is None


def test_directory_replay_checks_context_and_preserves_original_run(tmp_path):
    (tmp_path / "TYK2.json").write_text(json.dumps(package()))
    provider = DirectoryEvidenceProvider(tmp_path)
    assert provider.fetch("TYK2", "psoriasis", "explore", "replay-2")["run"]["run_id"] == "run-1"
    with pytest.raises(ValueError, match="mode or disease"):
        provider.fetch("TYK2", "asthma", "explore", "replay-2")
    with pytest.raises(ValueError, match="path component"):
        provider.fetch("../TYK2", "psoriasis", "explore", "replay-2")


def test_directory_rejects_symlink_escape(tmp_path):
    fixture_root = tmp_path / "fixtures"
    fixture_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(package()))
    (fixture_root / "TYK2.json").symlink_to(outside)
    with pytest.raises(ValueError, match="inside"):
        DirectoryEvidenceProvider(fixture_root).fetch("TYK2", "psoriasis", "explore", "run-1")


def modal_stubs(receipt=None, raw=None):
    calls, reads = [], []

    def spawn(*args):
        calls.append(args)

        def get(*, timeout):
            assert timeout == 120
            return receipt if receipt is not None else {"symbol": "TYK2", "path": "/data/runs/run-1/TYK2.json", "missing": []}

        return SimpleNamespace(get=get)

    def read_file(path):
        reads.append(path)
        content = json.dumps(package() if raw is None else raw).encode()
        return iter((content[:30], content[30:]))

    return SimpleNamespace(spawn=spawn), SimpleNamespace(read_file=read_file), calls, reads


def test_modal_resolves_receipt_to_full_package():
    function, volume, calls, reads = modal_stubs()
    result = ModalEvidenceProvider(function=function, volume=volume).fetch("TYK2", "psoriasis", "explore", "run-1")
    assert result == package()
    assert calls == [("TYK2", "psoriasis", "explore", "run-1")]
    assert reads == ["runs/run-1/TYK2.json"]


@pytest.mark.parametrize("path", [
    "/etc/passwd", "/data/runs/other/TYK2.json", "/data/runs/run-1/BRCA1.json",
    "/data/runs/run-1/../run-1/TYK2.json", "runs/run-1/TYK2.json",
    "/data/runs/run-1/TYK2.json/extra", "/data/runs/run-1//TYK2.json",
])
def test_modal_rejects_wrong_receipt_before_volume_read(path):
    function, volume, _, reads = modal_stubs({"symbol": "TYK2", "path": path})
    with pytest.raises(ValueError, match="Receipt"):
        ModalEvidenceProvider(function=function, volume=volume).fetch("TYK2", "psoriasis", "explore", "run-1")
    assert reads == []


def test_modal_rejects_bad_inputs_before_remote_call_and_stale_content():
    function, volume, calls, _ = modal_stubs()
    provider = ModalEvidenceProvider(function=function, volume=volume)
    with pytest.raises(ValueError, match="path component"):
        provider.fetch("TYK2", "psoriasis", "explore", "../../outside")
    assert calls == []
    raw = package()
    raw["run"]["run_id"] = "wrong-run"
    function, volume, _, _ = modal_stubs(raw=raw)
    with pytest.raises(ValueError, match="run_id"):
        ModalEvidenceProvider(function=function, volume=volume).fetch("TYK2", "psoriasis", "explore", "run-1")


def test_modal_rejects_wrong_receipt_symbol_before_reading():
    function, volume, _, reads = modal_stubs({"symbol": "BRCA1", "path": "/data/runs/run-1/TYK2.json"})
    with pytest.raises(ValueError, match="Receipt"):
        ModalEvidenceProvider(function=function, volume=volume).fetch("TYK2", "psoriasis", "explore", "run-1")
    assert reads == []


@pytest.mark.parametrize("section,key,value", [
    ("run", "mode", "eval"), ("run", "disease_query", "asthma"),
    ("gene", "query", {"symbol": "BRCA1"}),
])
def test_modal_rejects_package_for_different_query(section, key, value):
    raw = package()
    raw[section][key] = value
    function, volume, _, _ = modal_stubs(raw=raw)
    with pytest.raises(ValueError, match="does not match"):
        ModalEvidenceProvider(function=function, volume=volume).fetch("TYK2", "psoriasis", "explore", "run-1")


def test_modal_timeout_cancels_only_its_call():
    cancelled = []

    def get(*, timeout):
        assert timeout == 3
        raise TimeoutError("not finished")

    call = SimpleNamespace(get=get, cancel=lambda: cancelled.append(True))
    function = SimpleNamespace(spawn=lambda *args: call)
    provider = ModalEvidenceProvider(function=function, volume=object(), timeout_seconds=3)
    with pytest.raises(TimeoutError, match="not finished"):
        provider.fetch("TYK2", "psoriasis", "explore", "run-1")
    assert cancelled == [True]


def test_non_scalar_status_is_a_contract_gap_not_a_crash():
    raw = package()
    raw["sources"]["gtex"]["status"] = ["ok"]
    assert "malformed_source" in {g.code for g in adapt_packages([raw]).gaps}
