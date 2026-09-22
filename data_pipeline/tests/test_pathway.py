"""Stub-based unit tests for the pathway extension and source registry.

No network: Reactome HTTP is monkeypatched; gene packages are synthetic dicts in
the shape build_package emits.
"""
import cache as C
import invitro as IV
import pathway as PW
import registry as R
import sources as S


# ------------------------------------------------------------------ Reactome fetchers
def _fake_http(entities_by_id):
    def http(method, url, **kw):
        for pid, ents in entities_by_id.items():
            if f"/participants/{pid}/" in url:
                return ents
        raise AssertionError(f"unexpected url {url}")
    return http


def test_resolve_pathway_filters_and_flags_shared(monkeypatch):
    target = [
        {"databaseName": "UniProt", "identifier": "P1", "geneName": ["MSH2"]},
        {"databaseName": "UniProt", "identifier": "P2", "geneName": ["PCNA"]},
        {"databaseName": "ChEBI", "identifier": "C1", "name": ["ATP"]},  # dropped
        {"databaseName": "UniProt", "identifier": "P2b", "geneName": ["PCNA"]},  # dup
    ]
    shared_ref = [{"databaseName": "UniProt", "identifier": "P2", "geneName": ["PCNA"]}]
    monkeypatch.setattr(PW, "reactome_version", lambda: "97")
    monkeypatch.setattr(S, "http", _fake_http({"R-HSA-T": target, "R-HSA-REF": shared_ref}))

    r = PW.resolve_pathway("R-HSA-T", shared_ref_id="R-HSA-REF")
    assert r["status"] == "ok" and r["source_version"] == "97"
    d = r["data"]
    assert d["n_genes"] == 2  # ChEBI dropped, PCNA deduped
    flags = {g["symbol"]: g["shared_participant"] for g in d["genes"]}
    assert flags == {"MSH2": False, "PCNA": True}
    assert d["n_shared_participant"] == 1


def test_resolve_pathway_empty_is_not_found(monkeypatch):
    monkeypatch.setattr(PW, "reactome_version", lambda: "97")
    monkeypatch.setattr(S, "http", _fake_http({"R-HSA-X": []}))
    r = PW.resolve_pathway("R-HSA-X", shared_ref_id=None)
    assert r["status"] == "not_found"


def test_pathways_for_gene_lists_candidates(monkeypatch):
    monkeypatch.setattr(PW, "reactome_version", lambda: "97")
    monkeypatch.setattr(S, "http", lambda m, u, **k: [
        {"stId": "R-HSA-5358565", "displayName": "MutSalpha"},
        {"stId": "R-HSA-5358606", "displayName": "MutSbeta"},
        {"stId": None, "displayName": "dropped"}])
    r = PW.pathways_for_gene("MLH1")
    assert r["status"] == "ok" and r["data"]["n"] == 2
    assert r["data"]["pathways"][0]["stId"] == "R-HSA-5358565"


def test_pathways_for_gene_empty_is_not_found(monkeypatch):
    monkeypatch.setattr(PW, "reactome_version", lambda: "97")
    monkeypatch.setattr(S, "http", lambda m, u, **k: [])
    assert PW.pathways_for_gene("NOPE")["status"] == "not_found"


def test_infer_mouse_pathway_labels_inferred(monkeypatch):
    monkeypatch.setattr(PW, "reactome_version", lambda: "97")
    monkeypatch.setattr(S, "http", lambda m, u, **k: {
        "stId": "R-MMU-5358508", "displayName": "Mismatch Repair",
        "speciesName": "Mus musculus", "isInferred": True, "releaseDate": "2026-06-17"})
    r = PW.infer_mouse_pathway("R-HSA-5358508")
    assert r["status"] == "ok"
    assert r["data"]["inferred"] is True
    assert r["data"]["label"] == PW.INFERRED_LABEL


def test_classify_ortholog():
    def ortho(status, types):
        return {"status": status, "data": {"orthologs": [{"type": t} for t in types]}}
    assert PW._classify_ortholog(ortho("ok", ["ortholog_one2one"])) == "one2one"
    assert PW._classify_ortholog(ortho("ok", ["ortholog_one2many"])) == "one2many"
    assert PW._classify_ortholog(ortho("ok", ["ortholog_many2many"])) == "many2many"
    assert PW._classify_ortholog(ortho("ok", [])) == "no_ortholog"
    assert PW._classify_ortholog({"status": "not_found"}) == "no_ortholog"
    assert PW._classify_ortholog({"status": "error"}) == "unavailable"  # not a negative


# ------------------------------------------------------------------ aggregation (no scores)
def _pkg(symbol, mouse_type, phenotyped):
    return {
        "gene": {"data": {"symbol": symbol}},
        "sources": {
            "ensembl_orthology": {
                "mus_musculus": {"status": "ok",
                                 "data": {"orthologs": [{"type": mouse_type}]}}},
            "impc": {"status": "ok", "data": {"phenotyped": phenotyped}},
        },
        "missing": [],
    }


def test_aggregate_pathway_rolls_up_counts_only():
    pathway_res = S.result("reactome_pathway", "ok", {}, data={"genes": [
        {"symbol": "MSH2", "shared_participant": False},
        {"symbol": "PCNA", "shared_participant": True},
        {"symbol": "POLD1", "shared_participant": True}]})
    mouse_res = S.result("reactome_orthology", "ok", {}, data={"inferred": True})
    pkgs = [_pkg("MSH2", "ortholog_one2one", True),
            _pkg("PCNA", "ortholog_one2many", False),
            _pkg("POLD1", "ortholog_one2one", True)]

    agg = PW.aggregate_pathway("R-HSA-T", "cancer", "explore", "run1",
                               pkgs, pathway_res, mouse_res)
    s = agg["summary"]
    assert s["n_genes"] == 3
    assert s["participants"]["n_shared_participant"] == 2
    assert s["participants"]["n_exclusive"] == 1
    mm = s["in_vivo"]["orthology"]["mus_musculus"]
    assert mm["n_one2one"] == 2 and mm["n_one2many"] == 1
    impc = s["in_vivo"]["impc"]
    assert impc["n_phenotyped"] == 2 and impc["phenotyped_ratio"] == 2 / 3


# ------------------------------------------------------------------ registry (§4.5/§6/§9)
def test_evidence_dimensions_present_for_all_sources():
    for sid in R.SOURCES:
        dims = R.evidence_dimensions(sid)
        assert dims["evidence_role"] == "background"
        assert set(dims) >= {"result_origin", "measured_vs_inferred", "species",
                             "context", "modality", "source_dependencies"}


def test_independent_sources_dedupes_shared_providers():
    out = R.independent_sources(["impc", "opentargets_association", "gtex"])
    # IMPC appears in both impc and opentargets -> counted once
    assert out["providers"]["IMPC"] == ["impc", "opentargets_association"]
    assert out["providers"]["GTEx"] == ["opentargets_association", "gtex"]


def test_eval_policy_association_leaks_baseline_allowed():
    assert R.eval_allows("opentargets_association") is False  # disease link leaks
    assert R.eval_allows("gtex") is True                      # baseline expression ok
    assert R.eval_allows("pubmed") is False


def test_render_tools_md_covers_every_source():
    md = R.render_tools_md()
    for sid in R.SOURCES:
        assert f"## {sid}" in md
    assert "Purpose" in md and "Source dependencies" in md


def test_invitro_sources_registered_and_allowed_in_eval():
    for sid in ("hpa_rna", "hpa_protein", "opentargets_depmap"):
        assert R.SOURCES[sid]["context"] == "in_vitro"
        assert R.eval_allows(sid) is True  # not disease association


# ------------------------------------------------------------------ in-vitro enrichment
def test_enrich_invitro_attaches_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "hpa_cell_lines", lambda e: S.result(
        "hpa_cell_lines", "ok", {}, data={"rna": {}, "protein": {}}))
    monkeypatch.setattr(S, "opentargets_depmap", lambda e: S.result(
        "opentargets_depmap", "ok", {}, data={"isEssential": True, "n_tissues": 3}))
    pkg = {"gene": {"data": {"ensembl_primary": "ENSG1"}}, "sources": {}, "missing": []}
    IV.enrich_invitro(pkg, "eval", C.JsonCache(tmp_path))
    assert pkg["sources"]["hpa_cell_lines"]["status"] == "ok"
    assert pkg["sources"]["opentargets_depmap"]["data"]["isEssential"] is True


def test_enrich_invitro_skips_without_ensg(tmp_path):
    pkg = {"gene": {"data": {}}, "sources": {}, "missing": []}
    IV.enrich_invitro(pkg, "explore", C.JsonCache(tmp_path))
    assert pkg["sources"]["hpa_cell_lines"]["status"] == "skipped"
    assert pkg["sources"]["opentargets_depmap"]["status"] == "skipped"


def test_aggregate_in_vitro_counts():
    def pkg(sym, essential):
        return {"gene": {"data": {"symbol": sym}},
                "sources": {"ensembl_orthology": {}, "impc": {"status": "skipped"},
                            "hpa_cell_lines": {"status": "ok", "data": {"rna": {}}},
                            "opentargets_depmap": {"status": "ok",
                                                   "data": {"isEssential": essential}}}}
    pathway_res = S.result("reactome_pathway", "ok", {}, data={"genes": []})
    mouse_res = S.result("reactome_orthology", "ok", {}, data={"inferred": True})
    agg = PW.aggregate_pathway("R-HSA-T", "d", "explore", "r",
                               [pkg("MLH1", True), pkg("MSH2", False)],
                               pathway_res, mouse_res)
    iv = agg["summary"]["in_vitro"]
    assert iv["hpa"]["n_genes"] == 2
    assert iv["depmap"]["n_genes_with_data"] == 2 and iv["depmap"]["n_essential"] == 1
    assert iv["depmap"]["essential_genes"] == ["MLH1"]


def test_pathways_for_gene_attaches_descriptions(monkeypatch):
    """Gene → its pathways, each with a 'what it does' description (batched)."""
    monkeypatch.setattr(PW, "reactome_version", lambda: "97")
    monkeypatch.setattr(S, "http", lambda m, u, **k: [
        {"stId": "R-HSA-5358565", "displayName": "MutSalpha"}])
    monkeypatch.setattr(PW, "_pathway_descriptions",
                        lambda ids: {"R-HSA-5358565": "MSH2:MSH6 binds mismatches."})
    r = PW.pathways_for_gene("MLH1")
    assert r["status"] == "ok"
    p = r["data"]["pathways"][0]
    assert p["name"] == "MutSalpha"
    assert p["description"] == "MSH2:MSH6 binds mismatches."
