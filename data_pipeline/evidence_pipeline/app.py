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
    import registry as R
    import sources as S
    from cache import JsonCache
    from invitro import enrich_invitro
    from package import build_package

    vol.reload()  # see cache entries written by other containers
    cache = JsonCache(ROOT)
    pkg = build_package(symbol, disease, mode, run_id, cache)
    enrich_invitro(pkg, mode, cache)  # add in-vitro context (HPA, DepMap)

    # patient/disease context: HPA cancer cohort-level background (disease-linked -> eval skips)
    ensg = (pkg["gene"].get("data") or {}).get("ensembl_primary")
    if mode == "eval" and not R.eval_allows("hpa_pathology"):
        rp = S.result("hpa_pathology", "skipped", {}, error=f"disabled in {mode} mode")
    elif not ensg:
        rp = S.result("hpa_pathology", "skipped", {}, error="no ensembl id")
    else:
        rp = cache.fetch("hpa_pathology", {"ensg": ensg}, lambda: S.hpa_pathology(ensg))
    pkg["sources"]["hpa_pathology"] = rp
    if rp["status"] != "ok":
        pkg["missing"].append({"source": "hpa_pathology", "sub": None,
                               "status": rp["status"], "reason": rp.get("error")})

    R.annotate_package(pkg)  # make species/context/modality explicit on every source
    out = Path(ROOT) / "runs" / run_id / f"{symbol}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pkg, indent=2))
    vol.commit()
    return {"symbol": symbol, "path": str(out), "package": pkg,
            "missing": [f"{m['source']}:{m['status']}" for m in pkg["missing"]]}


@app.function(image=image, volumes={ROOT: vol}, secrets=secrets,
              max_containers=8, timeout=1800)
def build_pathway(reactome_id: str, disease: str = "", mode: str = "explore",
                  run_id: str = "", members_evidence: bool = False) -> dict:
    """Pathway-level evidence: pathway-level info + (optional) member-gene evidence.

    Default is the cheap pathway-only view (a few Reactome calls): participants, pathway
    details (description, defining PubMed IDs, hierarchy, GO), and inferred mouse pathway.
    Set `members_evidence=True` to ALSO fan out build_one over member genes and aggregate
    per-context coverage (heavier). No summed score across genes (v3 §9) —
    aggregate_pathway rolls up counts only.
    """
    import json
    from pathlib import Path

    import pathway as PW

    vol.reload()
    pathway_res = PW.resolve_pathway(reactome_id)
    details_res = PW.pathway_details(reactome_id)
    mouse_res = PW.infer_mouse_pathway(reactome_id)
    genes = [g["symbol"] for g in (pathway_res.get("data") or {}).get("genes", [])]

    packages = []
    if members_evidence and genes:
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
                               packages, pathway_res, mouse_res, details_res)
    pkg["run"]["members_evidence"] = bool(members_evidence)
    out = Path(ROOT) / "runs" / run_id / f"pathway_{reactome_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pkg, indent=2))
    vol.commit()
    return {"reactome_id": reactome_id, "path": str(out),
            "members_evidence": bool(members_evidence),
            "n_participant_genes": len(genes), "n_built": len(packages),
            "pathway_details": details_res.get("data") if details_res.get("status") == "ok" else None,
            "summary": pkg["summary"], "missing": pkg["missing"]}


@app.local_entrypoint()
def pathway(reactome_id: str, disease: str = "", mode: str = "explore",
            members_evidence: bool = False):
    """Assess a pathway by Reactome id, e.g. --reactome-id R-HSA-5358508.

    Default is the pathway-only view (Reactome details, no gene fan-out — fast).
    Add --members-evidence to also fan out per-member gene evidence (heavier).
    """
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S") + f"-{mode}-pathway"
    result = build_pathway.remote(reactome_id, disease, mode, run_id, members_evidence)
    manifest = {"run_id": run_id, "mode": mode, "disease": disease, **result}
    local = Path("runs") / run_id
    local.mkdir(parents=True, exist_ok=True)
    (local / f"pathway_{reactome_id}.json").write_text(json.dumps(manifest, indent=2))
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
