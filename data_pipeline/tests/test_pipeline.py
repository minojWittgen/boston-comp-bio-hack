"""Stub-based unit tests for the evidence pipeline.

No network: every source fetcher is monkeypatched. Covers the three invariants
that the pipeline must never break:
  1. the four SourceResult statuses flow through build_package correctly,
  2. the cache stores `ok`/`not_found` but never `error`,
  3. `--mode eval` marks pubmed and opentargets as `skipped`.
"""
import cache
import package
import sources as S


# --------------------------------------------------------------- helpers / stubs
ENSG = "ENSG00000000001"


def _gene_ok():
    return S.result("mygene", "ok", {"symbol": "GENE"}, data={
        "symbol": "GENE", "name": "n", "entrez": 1,
        "ensembl_ids": [ENSG], "ensembl_primary": ENSG, "ambiguous": False})


def _ortho_ok(sp):
    o = {"target_id": "ENSMUSG1", "species": sp, "type": "ortholog_one2one",
         "perc_id_target": 90, "perc_id_source": 90, "target_symbol": "Gene"}
    return S.result("ensembl_orthology", "ok", {"sp": sp},
                    data={"orthologs": [o], "one2one": [o]})


def stub_all_ok(monkeypatch):
    """Wire every fetcher to a successful result."""
    monkeypatch.setattr(S, "normalize_gene", lambda symbol: _gene_ok())
    monkeypatch.setattr(S, "ensembl_orthologs", lambda ensg, sp: _ortho_ok(sp))
    monkeypatch.setattr(S, "impc_phenotypes", lambda sym: S.result(
        "impc", "ok", {}, data={"phenotyped": True, "n_tests": 3, "hits": []}))
    monkeypatch.setattr(S, "gtex_expression", lambda ensg: S.result(
        "gtex", "ok", {}, data={"gencodeId": "g", "tissues": []}))
    monkeypatch.setattr(S, "opentargets_target", lambda ensg: S.result(
        "opentargets", "ok", {}, data={"id": ensg, "associatedDiseases": {"rows": []}}))
    monkeypatch.setattr(S, "pubmed_search", lambda symbol, disease: S.result(
        "pubmed", "ok", {}, data={"count": 5, "pmids": ["1"]}))


# ------------------------------------------------------------------- (1) statuses
def test_four_statuses_flow_through(monkeypatch, tmp_path):
    """ok / not_found / error / skipped each surface where expected."""
    stub_all_ok(monkeypatch)
    # rat has no ortholog record -> not_found (a database fact, not a failure)
    monkeypatch.setattr(S, "ensembl_orthologs", lambda ensg, sp:
        S.result("ensembl_orthology", "not_found", {"sp": sp}, data={"orthologs": []})
        if sp == "rattus_norvegicus" else _ortho_ok(sp))
    # gtex hits a technical failure -> error
    monkeypatch.setattr(S, "gtex_expression", lambda ensg:
        S.result("gtex", "error", {}, error="boom"))

    pkg = package.build_package("GENE", "psoriasis", "explore", "r",
                                cache.JsonCache(tmp_path))
    srcs = pkg["sources"]

    assert srcs["ensembl_orthology"]["mus_musculus"]["status"] == "ok"
    assert srcs["ensembl_orthology"]["rattus_norvegicus"]["status"] == "not_found"
    assert srcs["gtex"]["status"] == "error"
    # explore mode enables everything, so nothing here should be skipped
    statuses = {m["status"] for m in pkg["missing"]}
    assert "not_found" in statuses and "error" in statuses


def test_gene_normalization_failure_skips_downstream(monkeypatch, tmp_path):
    """If the gene can't be resolved, dependent sources are skipped, not errored."""
    stub_all_ok(monkeypatch)
    monkeypatch.setattr(S, "normalize_gene", lambda symbol:
        S.result("mygene", "error", {"symbol": symbol}, error="net"))

    pkg = package.build_package("GENE", "psoriasis", "explore", "r",
                                cache.JsonCache(tmp_path))
    assert pkg["sources"]["gtex"]["status"] == "skipped"
    assert pkg["sources"]["opentargets"]["status"] == "skipped"
    assert pkg["sources"]["ensembl_orthology"]["mus_musculus"]["status"] == "skipped"


# --------------------------------------------------------------- (2) cache rules
def test_cache_never_stores_error(tmp_path):
    c = cache.JsonCache(tmp_path)
    err = S.result("gtex", "error", {"ensg": ENSG}, error="boom")
    c.put("gtex", {"ensg": ENSG}, err)
    assert c.get("gtex", {"ensg": ENSG}) is None  # error not persisted


def test_cache_stores_ok_and_not_found(tmp_path):
    c = cache.JsonCache(tmp_path)
    for status in ("ok", "not_found"):
        q = {"ensg": ENSG, "s": status}
        c.put("gtex", q, S.result("gtex", status, q, data={"x": 1}))
        hit = c.get("gtex", q)
        assert hit is not None and hit["status"] == status and hit["cache_hit"] is True


def test_cache_fetch_skips_call_on_error_next_time(tmp_path):
    """An error result is returned but not cached, so fn runs again next call."""
    c = cache.JsonCache(tmp_path)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return S.result("gtex", "error", {}, error="boom")

    c.fetch("gtex", {"ensg": ENSG}, fn)
    c.fetch("gtex", {"ensg": ENSG}, fn)
    assert calls["n"] == 2  # not served from cache


# ------------------------------------------------------------------- (3) eval mode
def test_eval_mode_skips_pubmed_and_opentargets(monkeypatch, tmp_path):
    stub_all_ok(monkeypatch)
    pkg = package.build_package("GENE", "psoriasis", "eval", "r",
                                cache.JsonCache(tmp_path))
    assert pkg["sources"]["pubmed"]["status"] == "skipped"
    assert pkg["sources"]["opentargets"]["status"] == "skipped"
    assert set(pkg["run"]["enabled_sources"]) == {"ensembl_orthology", "gtex", "impc"}
    # eval still queries cross-species sources
    assert pkg["sources"]["gtex"]["status"] == "ok"
    assert pkg["sources"]["impc"]["status"] == "ok"


def test_eval_does_not_call_disabled_sources(monkeypatch, tmp_path):
    """eval mode must not even invoke pubmed/opentargets fetchers (answer leak)."""
    stub_all_ok(monkeypatch)
    called = {"pubmed": False, "ot": False}
    monkeypatch.setattr(S, "pubmed_search",
                        lambda s, d: called.__setitem__("pubmed", True))
    monkeypatch.setattr(S, "opentargets_target",
                        lambda e: called.__setitem__("ot", True))
    package.build_package("GENE", "psoriasis", "eval", "r", cache.JsonCache(tmp_path))
    assert called == {"pubmed": False, "ot": False}
