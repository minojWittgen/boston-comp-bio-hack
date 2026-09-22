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
         .add_local_python_source("sources", "cache", "package"))
vol = modal.Volume.from_name("xctx-cache", create_if_missing=True)
ROOT = "/data"

# Optional: `modal secret create ncbi-api-key NCBI_API_KEY=...` (raises PubMed rate limit)
secrets = [modal.Secret.from_name("ncbi-api-key")] if os.environ.get("USE_NCBI_SECRET") else []


@app.function(image=image, volumes={ROOT: vol}, secrets=secrets,
              max_containers=8,  # stays under Ensembl/NCBI rate limits
              timeout=900)
def build_one(symbol: str, disease: str, mode: str, run_id: str) -> dict:
    from cache import JsonCache
    from package import build_package

    vol.reload()  # see cache entries written by other containers
    pkg = build_package(symbol, disease, mode, run_id, JsonCache(ROOT))
    out = Path(ROOT) / "runs" / run_id / f"{symbol}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pkg, indent=2))
    vol.commit()
    return {"symbol": symbol, "path": str(out),
            "missing": [f"{m['source']}:{m['status']}" for m in pkg["missing"]]}


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
            results.append({**r, "status": "built"})

    manifest = {"run_id": run_id, "mode": mode, "disease": disease, "genes": results}
    local = Path("runs") / run_id
    local.mkdir(parents=True, exist_ok=True)
    (local / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))
    print(f"\nPackages on volume 'xctx-cache' under runs/{run_id}/  "
          f"(modal volume get xctx-cache runs/{run_id} .)")
