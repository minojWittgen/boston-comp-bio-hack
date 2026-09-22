"""Pathway-level extension (v3 §4.4 Reactome, §2 ALIGN SPECIES box).

Adds pathway-scoped retrieval and aggregation ON TOP OF the per-gene pipeline.
`package.build_package` is NOT modified — this module only reads its output.

Public functions (same four-status contract as sources.py; never raise):
  resolve_pathway(reactome_id)     -> participating human genes + Reactome DB version
  infer_mouse_pathway(reactome_id) -> computationally inferred mouse pathway (labeled)
  aggregate_pathway(...)           -> pathway rollup of per-gene packages (no scores)

v3 boundaries honored here:
  - Reactome inferred events in other species are labeled, never counted as
    independent experiments (§4.4).
  - No summed score or probability across genes (§9); only counts, lists, ratios.
"""
from __future__ import annotations

import requests

import sources as S

REACTOME = "https://reactome.org/ContentService"
MUS_MUSCULUS_DBID = 48892  # Reactome species dbId for Mus musculus
INFERRED_LABEL = "computationally inferred, not independent evidence"
# Default "shared" reference: a participant also in DNA Replication is not MMR-exclusive
# (e.g. PCNA, RPA, POLD, LIG1). Configurable per call.
SHARED_REF_DEFAULT = "R-HSA-69306"  # DNA Replication

_VERSION_CACHE: dict[str, str | None] = {}


def reactome_version() -> str | None:
    """Reactome graph-database release, e.g. '97'. Cached per process.

    This endpoint returns bare text; requesting application/json yields 406, so fetch
    it as text/plain rather than via S.http (which sends Accept: application/json).
    """
    if "v" not in _VERSION_CACHE:
        try:
            resp = requests.get(f"{REACTOME}/data/database/version",
                                headers={"Accept": "text/plain"}, timeout=S.TIMEOUT)
            resp.raise_for_status()
            _VERSION_CACHE["v"] = resp.text.strip()
        except Exception:  # noqa: BLE001  version is best-effort metadata
            _VERSION_CACHE["v"] = None
    return _VERSION_CACHE["v"]


def _status_404(e: Exception) -> bool:
    resp = getattr(e, "response", None)
    return isinstance(e, requests.HTTPError) and resp is not None and resp.status_code == 404


# ---------------------------------------------------------------- pathway participants
def _pathway_gene_symbols(reactome_id: str) -> set[str]:
    """Uppercased UniProt gene symbols for a pathway (used for overlap checks)."""
    ents = S.http("GET", f"{REACTOME}/data/participants/{reactome_id}/referenceEntities")
    out = set()
    for e in ents:
        if e.get("databaseName") == "UniProt":
            names = e.get("geneName") or e.get("name") or []
            if names:
                out.add(names[0].upper())
    return out


def resolve_pathway(reactome_id: str, shared_ref_id: str | None = SHARED_REF_DEFAULT) -> dict:
    """Human genes participating in a versioned Reactome pathway.

    Keeps only UniProt protein reference entities (drops ChEBI small molecules),
    deduplicates by gene symbol. Each gene is flagged `shared_participant` when it
    also participates in `shared_ref_id` (default DNA Replication) — i.e. it is not
    exclusive to this pathway. If the reference lookup fails, the flag is None
    (unknown) and resolution still succeeds.
    """
    q = {"reactome_id": reactome_id, "shared_ref_id": shared_ref_id}
    version = reactome_version()
    try:
        ents = S.http("GET", f"{REACTOME}/data/participants/{reactome_id}/referenceEntities")
        shared_set: set[str] | None = None
        if shared_ref_id:
            try:
                shared_set = _pathway_gene_symbols(shared_ref_id)
            except Exception:  # noqa: BLE001  best-effort; unknown flag on failure
                shared_set = None
        genes, seen = [], set()
        for e in ents:
            if e.get("databaseName") != "UniProt":
                continue
            names = e.get("geneName") or e.get("name") or []
            sym = names[0] if names else None
            if sym and sym.upper() not in seen:
                seen.add(sym.upper())
                shared = (sym.upper() in shared_set) if shared_set is not None else None
                genes.append({"symbol": sym, "uniprot": e.get("identifier"),
                              "shared_participant": shared})
        if not genes:
            return S.result("reactome_pathway", "not_found", q, data={"genes": []},
                            version=version)
        n_shared = sum(1 for g in genes if g["shared_participant"])
        return S.result("reactome_pathway", "ok", q, version=version, data={
            "reactome_id": reactome_id, "n_genes": len(genes),
            "n_shared_participant": n_shared,
            "shared_reference": ({"pathway": shared_ref_id,
                                  "label": "also participates in this pathway; not exclusive"}
                                 if shared_set is not None else None),
            "genes": genes})
    except Exception as e:  # noqa: BLE001
        if _status_404(e):
            return S.result("reactome_pathway", "not_found", q, version=version)
        return S.result("reactome_pathway", "error", q, error=repr(e), version=version)


# ---------------------------------------------------------------- gene → its pathways (+ what each does)
def _pathway_descriptions(ids: list[str]) -> dict[str, str | None]:
    """Batch-fetch 'what each pathway does' (Reactome summation) in one POST."""
    if not ids:
        return {}
    try:
        resp = requests.post(f"{REACTOME}/data/query/ids", data=",".join(ids),
                             headers={"Content-Type": "text/plain",
                                      "Accept": "application/json"}, timeout=S.TIMEOUT)
        resp.raise_for_status()
        out: dict[str, str | None] = {}
        for e in resp.json():
            summ = e.get("summation") or []
            out[e.get("stId")] = (summ[0].get("text") if summ else None)
        return out
    except Exception:  # noqa: BLE001  descriptions are best-effort
        return {}


def pathways_for_gene(symbol: str) -> dict:
    """Which human Reactome pathways a gene is in, and what each pathway does.

    Attached to a gene's evidence so a reader can see the gene's pathway membership
    and a short description of each pathway (Reactome summation), fetched in one batch.
    """
    q = {"symbol": symbol}
    version = reactome_version()
    try:
        d = S.http("GET", f"{REACTOME}/data/mapping/UniProt/{symbol}/pathways",
                   params={"species": "9606"})
        pathways = [{"stId": p.get("stId"), "name": p.get("displayName")}
                    for p in (d or []) if p.get("stId")]
        if not pathways:
            return S.result("reactome_gene_pathways", "not_found", q, version=version)
        descs = _pathway_descriptions([p["stId"] for p in pathways])
        for p in pathways:
            p["description"] = descs.get(p["stId"])
        return S.result("reactome_gene_pathways", "ok", q, version=version,
                        data={"symbol": symbol, "n": len(pathways), "pathways": pathways})
    except Exception as e:  # noqa: BLE001
        if _status_404(e):
            return S.result("reactome_gene_pathways", "not_found", q, version=version)
        return S.result("reactome_gene_pathways", "error", q, error=repr(e), version=version)


# ---------------------------------------------------------------- mouse inference (labeled)
def infer_mouse_pathway(reactome_id: str) -> dict:
    """Reactome's computationally inferred mouse pathway for a human pathway.

    Labeled `inferred`; this is NOT an independent cross-species observation (§4.4).
    """
    q = {"reactome_id": reactome_id, "species_dbid": MUS_MUSCULUS_DBID}
    version = reactome_version()
    try:
        d = S.http("GET", f"{REACTOME}/data/orthology/{reactome_id}/species/{MUS_MUSCULUS_DBID}")
        if not isinstance(d, dict) or not d.get("stId"):
            return S.result("reactome_orthology", "not_found", q, version=version)
        return S.result("reactome_orthology", "ok", q, version=version, data={
            "mouse_stId": d.get("stId"),
            "display_name": d.get("displayName"),
            "species": d.get("speciesName"),
            "inferred": bool(d.get("isInferred", True)),
            "release_date": d.get("releaseDate"),
            "label": INFERRED_LABEL})
    except Exception as e:  # noqa: BLE001
        if _status_404(e):
            return S.result("reactome_orthology", "not_found", q, version=version)
        return S.result("reactome_orthology", "error", q, error=repr(e), version=version)


# ---------------------------------------------------------------- aggregation (no scores)
ORTHO_CLASSES = ["one2one", "one2many", "many2many", "no_ortholog", "unavailable"]


def _classify_ortholog(ortho_result: dict) -> str:
    """One gene's ortholog relationship to one species, from its SourceResult."""
    status = ortho_result.get("status")
    if status == "not_found":
        return "no_ortholog"
    if status != "ok":
        return "unavailable"  # error / skipped — not a biological negative
    types = {o.get("type") for o in (ortho_result.get("data") or {}).get("orthologs", [])}
    if "ortholog_one2one" in types:
        return "one2one"
    if "ortholog_one2many" in types:
        return "one2many"
    if "ortholog_many2many" in types:
        return "many2many"
    return "no_ortholog"


def aggregate_pathway(reactome_id: str, disease: str, mode: str, run_id: str,
                      gene_packages: list[dict], pathway_result: dict,
                      mouse_result: dict) -> dict:
    """Roll up per-gene evidence packages to the pathway level.

    NO summed score or probability (v3 §9). Only counts, gene lists and a phenotyped
    coverage ratio. `gene_packages` are full outputs of `package.build_package`.
    """
    pkgs = [p for p in gene_packages if p]
    symbols = [p["gene"].get("data", {}).get("symbol") or p.get("_symbol") for p in pkgs]

    # per-species orthology breakdown
    species_set: list[str] = []
    for p in pkgs:
        for sp in (p["sources"].get("ensembl_orthology") or {}):
            if sp not in species_set:
                species_set.append(sp)

    orthology = {}
    for sp in species_set:
        buckets = {c: [] for c in ORTHO_CLASSES}
        for p in pkgs:
            sym = p["gene"].get("data", {}).get("symbol")
            r = p["sources"]["ensembl_orthology"].get(sp, {})
            buckets[_classify_ortholog(r)].append(sym)
        orthology[sp] = {
            "n_genes": len(pkgs),
            "n_one2one": len(buckets["one2one"]),
            "n_one2many": len(buckets["one2many"]),
            "n_many2many": len(buckets["many2many"]),
            "n_no_ortholog": len(buckets["no_ortholog"]),
            "n_unavailable": len(buckets["unavailable"]),
            "genes": buckets}

    def _sym(p):
        return p["gene"].get("data", {}).get("symbol")

    def _src(p, name):
        return p["sources"].get(name) or {}

    # IMPC phenotyped coverage (counts + ratio; a coverage fraction, not a score)
    impc_ok = [p for p in pkgs if _src(p, "impc").get("status") == "ok"]
    impc_phenotyped = [p for p in impc_ok
                       if (_src(p, "impc").get("data") or {}).get("phenotyped")]
    n_ok = len(impc_ok)
    impc = {
        "n_genes_queried": n_ok,
        "n_phenotyped": len(impc_phenotyped),
        "phenotyped_ratio": (len(impc_phenotyped) / n_ok) if n_ok else None,
        "phenotyped_genes": [_sym(p) for p in impc_phenotyped],
        "note": "coverage over genes with an IMPC statistical-result query; not a score"}

    # in-vitro coverage: HPA cell-line RNA/protein + DepMap CRISPR fitness (counts only)
    hpa_ok = [p for p in pkgs if _src(p, "hpa_cell_lines").get("status") == "ok"]
    depmap_ok = [p for p in pkgs if _src(p, "opentargets_depmap").get("status") == "ok"]
    depmap_essential = [p for p in depmap_ok
                        if (_src(p, "opentargets_depmap").get("data") or {}).get("isEssential") is True]
    in_vitro = {
        "hpa": {"n_genes": len(hpa_ok), "genes": [_sym(p) for p in hpa_ok],
                "modalities": ["rna", "protein"]},
        "depmap": {"n_genes_with_data": len(depmap_ok),
                   "n_essential": len(depmap_essential),
                   "essential_genes": [_sym(p) for p in depmap_essential],
                   "note": "CRISPR fitness dependency, not pathway expression"}}

    # shared vs exclusive participants (from Reactome resolution, counted separately)
    resolved = (pathway_result.get("data") or {}).get("genes", [])
    shared = [g["symbol"] for g in resolved if g.get("shared_participant") is True]
    exclusive = [g["symbol"] for g in resolved if g.get("shared_participant") is False]
    unknown = [g["symbol"] for g in resolved if g.get("shared_participant") is None]
    participants = {
        "n_total": len(resolved),
        "n_shared_participant": len(shared),
        "n_exclusive": len(exclusive),
        "n_unknown": len(unknown),
        "shared_reference": (pathway_result.get("data") or {}).get("shared_reference"),
        "shared_genes": shared, "exclusive_genes": exclusive,
        "note": "shared = also in the reference pathway (e.g. DNA replication); "
                "not exclusive to this pathway"}

    return {
        "schema_version": "0.1-pathway",
        "run": {"run_id": run_id, "mode": mode, "disease_query": disease,
                "reactome_id": reactome_id, "built_at": S.now()},
        "pathway": pathway_result,
        "mouse_inference": mouse_result,
        "genes": [s for s in symbols if s],
        "summary": {
            "n_genes": len(pkgs),
            "participants": participants,
            # evidence grouped by v3 experimental context (§1)
            "in_vitro": in_vitro,
            "in_vivo": {"orthology": orthology, "impc": impc,
                        "mouse_pathway_inference": {
                            "status": mouse_result.get("status"),
                            "inferred": (mouse_result.get("data") or {}).get("inferred"),
                            "label": (mouse_result.get("data") or {}).get("label")}},
            "human_reference": {
                "note": "GTEx baseline + Open Targets association live in each gene "
                        "package; association is skipped in eval mode"},
            # v3 §1: an unavailable context is a VISIBLE gap with its requirement unmet
            "patients": {
                "status": "gap",
                "requirement": "human patient/disease cohorts with individual variation "
                               "(patient + specimen + time-point IDs; DNA/RNA/protein/"
                               "functional)",
                "why_gap": "requires dataset download/analysis, not a lightweight lookup; "
                           "out of the target-knowledge retrieval scope (Person A)",
                "individual_variation": "not resolved",
                "candidate_sources": ["GEO", "CELLxGENE Census", "NCI GDC",
                                      "Expression Atlas (differential)"]}},
        "missing": _pathway_missing(pathway_result, mouse_result, pkgs),
    }


def _pathway_missing(pathway_result, mouse_result, pkgs) -> list[dict]:
    out = []
    for name, r in [("reactome_pathway", pathway_result),
                    ("reactome_orthology", mouse_result)]:
        if r.get("status") != "ok":
            out.append({"source": name, "status": r["status"], "reason": r.get("error")})
    n_gene_issues = sum(1 for p in pkgs if p.get("missing"))
    if n_gene_issues:
        out.append({"source": "per_gene", "status": "partial",
                    "reason": f"{n_gene_issues}/{len(pkgs)} genes have non-ok sources"})
    return out
