"""Modal fan-out: gene list -> one evidence-package JSON per gene + a run manifest.

  modal run app.py --genes TYK2,CD28,IL23R --disease psoriasis --mode explore
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import modal

app = modal.App("xctx-evidence")
image = (modal.Image.debian_slim(python_version="3.11")
         .pip_install("requests")
         .add_local_python_source("sources", "cache", "package", "pathway",
                                  "registry", "invitro"))
vol = modal.Volume.from_name("xctx-cache", create_if_missing=True)
ROOT = "/data"

# Optional: `modal secret create ncbi-api-key NCBI_API_KEY=...` (raises PubMed rate limit)
secrets = [modal.Secret.from_name("ncbi-api-key")] if os.environ.get("USE_NCBI_SECRET") else []


@app.function(image=image, volumes={ROOT: vol}, secrets=secrets,
              max_containers=8,  # stays under Ensembl/NCBI rate limits
              timeout=900)
def build_one(symbol: str, disease: str, mode: str, run_id: str) -> dict:
    from cache import JsonCache
    from invitro import enrich_invitro
    from package import build_package

    vol.reload()  # see cache entries written by other containers
    cache = JsonCache(ROOT)
    pkg = build_package(symbol, disease, mode, run_id, cache)
    enrich_invitro(pkg, mode, cache)  # add in-vitro context (HPA, DepMap)
    out = Path(ROOT) / "runs" / run_id / f"{symbol}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pkg, indent=2))
    vol.commit()
    return {"symbol": symbol, "path": str(out), "package": pkg,
            "missing": [f"{m['source']}:{m['status']}" for m in pkg["missing"]]}


@app.function(image=image, volumes={ROOT: vol}, secrets=secrets,
              max_containers=8, timeout=1800)
def build_pathway(reactome_id: str = "", disease: str = "", mode: str = "explore",
                  run_id: str = "", gene: str = "") -> dict:
    """Pathway-level evidence: resolve participants, fan out build_one, aggregate.

    Two entry points (v3 §1/§8.2):
      A) reactome_id given -> assess that pathway directly.
      B) gene given        -> resolve the gene's Reactome pathway(s), assess the first,
                              and return the alternatives so the caller can pick another.
    No summed score across genes (v3 §9) — aggregate_pathway rolls up counts only.
    """
    import json
    from pathlib import Path

    import pathway as PW

    vol.reload()

    # entry B: gene -> its pathway (choose the first, expose alternatives)
    resolved_from = None
    if not reactome_id and gene:
        gp = PW.pathways_for_gene(gene)
        cands = (gp.get("data") or {}).get("pathways", [])
        if not cands:
            return {"gene": gene, "reactome_id": None, "n_participant_genes": 0,
                    "n_built": 0, "summary": {}, "missing": [
                        {"source": "reactome_gene_pathways", "status": gp["status"],
                         "reason": gp.get("error") or f"no human pathway for {gene}"}]}
        reactome_id = cands[0]["stId"]
        resolved_from = {"gene": gene, "chosen_pathway": reactome_id,
                         "alternatives": cands}

    pathway_res = PW.resolve_pathway(reactome_id)
    mouse_res = PW.infer_mouse_pathway(reactome_id)
    genes = [g["symbol"] for g in (pathway_res.get("data") or {}).get("genes", [])]

    packages = []
    if genes:
        args = [(g, disease, mode, run_id) for g in genes]
        # aggregate from the returned packages (one shot, no volume round-trip)
        for g, r in zip(genes, build_one.starmap(args, return_exceptions=True)):
            if isinstance(r, Exception) or not isinstance(r, dict):
                continue
            pkg = r.get("package")
            if pkg:
                pkg["_symbol"] = g
                packages.append(pkg)

    pkg = PW.aggregate_pathway(reactome_id, disease, mode, run_id,
                               packages, pathway_res, mouse_res,
                               anchor_gene=gene or None)
    out = Path(ROOT) / "runs" / run_id / f"pathway_{reactome_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pkg, indent=2))
    vol.commit()
    return {"reactome_id": reactome_id, "resolved_from_gene": resolved_from,
            "path": str(out), "n_participant_genes": len(genes),
            "n_built": len(packages), "anchor": pkg.get("anchor"),
            "summary": pkg["summary"], "missing": pkg["missing"]}


@app.local_entrypoint()
def pathway(reactome_id: str = "", disease: str = "", mode: str = "explore",
            gene: str = ""):
    """Assess a pathway. Give EITHER --reactome-id R-HSA-... OR --gene SYMBOL."""
    if not reactome_id and not gene:
        raise ValueError("provide --reactome-id R-HSA-... or --gene SYMBOL")
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S") + f"-{mode}-pathway"
    result = build_pathway.remote(reactome_id, disease, mode, run_id, gene)
    manifest = {"run_id": run_id, "mode": mode, "disease": disease, **result}
    local = Path("runs") / run_id
    local.mkdir(parents=True, exist_ok=True)
    chosen = result.get("reactome_id") or "unresolved"  # entry B resolves it remotely
    (local / f"pathway_{chosen}.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    print(f"\nPathway package on volume 'xctx-cache' under runs/{run_id}/  "
          f"(modal volume get xctx-cache runs/{run_id} .)")


@app.local_entrypoint()
def main(genes: str, disease: str = "", mode: str = "explore"):
    gene_list = [g.strip() for g in genes.split(",") if g.strip()]
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S") + f"-{mode}"
    args = [(g, disease, mode, run_id) for g in gene_list]

    results = []
    for g, r in zip(gene_list, build_one.starmap(args, return_exceptions=True)):
        if isinstance(r, Exception):
            results.append({"symbol": g, "status": "failed", "error": repr(r)})
        else:
            results.append({**{k: v for k, v in r.items() if k != "package"},
                            "status": "built"})

    manifest = {"run_id": run_id, "mode": mode, "disease": disease, "genes": results}
    local = Path("runs") / run_id
    local.mkdir(parents=True, exist_ok=True)
    (local / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    print(f"\nPackages on volume 'xctx-cache' under runs/{run_id}/  "
          f"(modal volume get xctx-cache runs/{run_id} .)")
