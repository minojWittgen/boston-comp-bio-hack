"""Build one evidence-package JSON for one gene. Pure Python: runs locally or inside Modal."""
from __future__ import annotations

import sources as S
from cache import JsonCache

SCHEMA_VERSION = "0.1"
ORTHO_SPECIES = ["mus_musculus", "rattus_norvegicus", "macaca_mulatta"]

# eval mode: turn off sources that could leak known answers for benchmark targets
MODES = {
    "explore": {"ensembl_orthology", "gtex", "impc", "opentargets", "pubmed"},
    "eval": {"ensembl_orthology", "gtex", "impc"},
}


def skipped(source: str, reason: str) -> dict:
    return S.result(source, "skipped", {}, error=reason)


def build_package(symbol: str, disease: str, mode: str, run_id: str, cache: JsonCache) -> dict:
    enabled = MODES[mode]
    srcs: dict[str, dict] = {}

    gene = cache.fetch("mygene", {"symbol": symbol}, lambda: S.normalize_gene(symbol))
    ensg = (gene.get("data") or {}).get("ensembl_primary")
    upstream_fail = None if ensg else f"gene normalization {gene['status']}"

    # orthology, one call per species
    ortho = {}
    for sp in ORTHO_SPECIES:
        if "ensembl_orthology" not in enabled:
            ortho[sp] = skipped("ensembl_orthology", f"disabled in {mode} mode")
        elif upstream_fail:
            ortho[sp] = skipped("ensembl_orthology", upstream_fail)
        else:
            ortho[sp] = cache.fetch("ensembl_orthology", {"ensg": ensg, "sp": sp},
                                    lambda sp=sp: S.ensembl_orthologs(ensg, sp))
    srcs["ensembl_orthology"] = ortho

    # IMPC depends on a mouse ortholog symbol; use one2one only, record why if absent
    mouse = ortho["mus_musculus"]
    one2one = (mouse.get("data") or {}).get("one2one", [])
    mouse_sym = one2one[0].get("target_symbol") if len(one2one) == 1 else None
    if "impc" not in enabled:
        srcs["impc"] = skipped("impc", f"disabled in {mode} mode")
    elif not mouse_sym:
        srcs["impc"] = skipped("impc", f"no unique one2one mouse ortholog (mouse orthology {mouse['status']})")
    else:
        srcs["impc"] = cache.fetch("impc", {"mouse_symbol": mouse_sym},
                                   lambda: S.impc_phenotypes(mouse_sym))

    for name, fn in [("gtex", lambda: S.gtex_expression(ensg)),
                     ("opentargets", lambda: S.opentargets_target(ensg))]:
        if name not in enabled:
            srcs[name] = skipped(name, f"disabled in {mode} mode")
        elif upstream_fail:
            srcs[name] = skipped(name, upstream_fail)
        else:
            srcs[name] = cache.fetch(name, {"ensg": ensg}, fn)

    if "pubmed" not in enabled:
        srcs["pubmed"] = skipped("pubmed", f"disabled in {mode} mode")
    else:
        srcs["pubmed"] = cache.fetch("pubmed", {"symbol": symbol, "disease": disease},
                                     lambda: S.pubmed_search(symbol, disease))

    return {
        "schema_version": SCHEMA_VERSION,
        "run": {"run_id": run_id, "mode": mode, "disease_query": disease,
                "enabled_sources": sorted(enabled), "built_at": S.now()},
        "gene": gene,
        "sources": srcs,
        "summary": summarize(srcs),
        "missing": list_missing(srcs),
    }


def summarize(srcs: dict) -> dict:
    """Deterministic digest for the agent. No interpretation, only counts and flags."""
    def data(x):
        return x.get("data") or {}

    ortho = {sp: {"status": r["status"],
                  "n_orthologs": len(data(r).get("orthologs", [])),
                  "n_one2one": len(data(r).get("one2one", []))}
             for sp, r in srcs["ensembl_orthology"].items()}
    impc = srcs["impc"]
    gtex = srcs["gtex"]
    ot = srcs["opentargets"]
    return {
        "orthology": ortho,
        "impc": {"status": impc["status"], "phenotyped": data(impc).get("phenotyped"),
                 "n_phenotype_hits": len(data(impc).get("hits", []))},
        "gtex_top_tissues": data(gtex).get("tissues", [])[:5],
        "opentargets_top_diseases": [
            {"id": r["disease"]["id"], "name": r["disease"]["name"], "score": r["score"],
             # datasource provenance behind each association (europepmc, impc, eva, gwas...)
             "datasources": [ds["id"] for ds in (r.get("datasourceScores") or [])]}
            for r in (data(ot).get("associatedDiseases") or {}).get("rows", [])[:5]],
        "pubmed_count": data(srcs["pubmed"]).get("count"),
    }


def list_missing(srcs: dict) -> list[dict]:
    out = []
    for name, r in srcs.items():
        items = r.items() if name == "ensembl_orthology" else [(None, r)]
        for sub, x in items:
            if x["status"] != "ok":
                out.append({"source": name, "sub": sub, "status": x["status"],
                            "reason": x.get("error")})
    return out
