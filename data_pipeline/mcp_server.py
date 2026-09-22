"""MCP server exposing the evidence pipeline as one tool.

Wraps the deployed Modal function `xctx-evidence / build_one` so a coordinating
agent can request an evidence package for a single gene over MCP (stdio).

Note: `requirements.txt` pins `mcp`, which resolves to mcp 2.x here, where the
old `FastMCP` class was renamed to `MCPServer` (same decorator/run API). If you
are on mcp 1.x, replace the import with
`from mcp.server.fastmcp import FastMCP as MCPServer`.

Run locally:  python mcp_server.py         (stdio transport)
Prereq:       `modal deploy app.py` so `xctx-evidence` is live.
"""
from __future__ import annotations

import datetime as dt

import modal
from mcp.server.mcpserver import MCPServer

APP_NAME = "xctx-evidence"
FUNCTION_NAME = "build_one"
VALID_MODES = {"explore", "eval"}

server = MCPServer("xctx-evidence")


@server.tool(
    description="Build a target-knowledge evidence package for one human gene by "
    "fanning out to Open Targets, Ensembl orthology, GTEx, IMPC, and PubMed. "
    "mode='explore' queries all sources; mode='eval' skips PubMed and Open "
    "Targets to avoid leaking benchmark answers. Returns a build receipt: the "
    "gene symbol, the package path on the 'xctx-cache' Modal volume, and the "
    "list of sources that were not 'ok' (missing)."
)
def build_evidence_package(symbol: str, disease: str = "", mode: str = "explore") -> dict:
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}")
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S") + f"-{mode}-mcp"
    build_one = modal.Function.from_name(APP_NAME, FUNCTION_NAME)
    return build_one.remote(symbol, disease, mode, run_id)


@server.tool(
    description="Build a PATHWAY-level evidence package. Give EITHER a Reactome stable "
    "id (reactome_id='R-HSA-...') to assess that pathway directly, OR a gene symbol "
    "(gene='MLH1') to resolve the gene's Reactome pathway(s) and assess the first "
    "(alternatives are returned). Resolves participating human genes, fans out the "
    "per-gene pipeline, and aggregates by species/context — counts only, no summed "
    "score (v3 §9). mode='explore' runs all sources; mode='eval' skips answer-leaking "
    "sources (disease association, literature) but keeps baseline/fitness evidence. "
    "Returns a receipt: reactome_id, resolved_from_gene, package path, per-context "
    "summary, and missing."
)
def build_pathway_evidence(reactome_id: str = "", disease: str = "",
                           mode: str = "explore", gene: str = "") -> dict:
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}")
    if not reactome_id and not gene:
        raise ValueError("provide reactome_id='R-HSA-...' or gene='SYMBOL'")
    run_id = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%S") + f"-{mode}-pathway-mcp"
    build_pathway = modal.Function.from_name(APP_NAME, "build_pathway")
    return build_pathway.remote(reactome_id, disease, mode, run_id, gene)


if __name__ == "__main__":
    server.run(transport="stdio")
