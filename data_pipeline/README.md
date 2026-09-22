# Evidence Pipeline

Target-knowledge retrieval for the cross-context biology agent. Given **one human
gene symbol**, it queries five sources and returns **one deterministic
evidence-package JSON** — the factual substrate the AI agent reasons over. It makes
**judgments nowhere**: every field is a retrieved fact or an explicit gap.

Sources: **Open Targets** (GraphQL), **Ensembl** orthology (REST), **GTEx v8**,
**IMPC** (Solr), **PubMed** (E-utilities). Gene IDs are normalized via **MyGene**.

See [`PIPELINE.md`](PIPELINE.md) for the full data-flow diagrams.

## What the backend / AI-agent side calls

Two entry points, same computation:

### 1. MCP tool (for the agent)
`mcp_server.py` exposes one stdio tool:

```
build_evidence_package(symbol: str, disease: str = "", mode: str = "explore") -> dict
```

It calls the deployed Modal function and returns a **build receipt**:
`{ "symbol", "path", "missing" }` — where `path` is the package location on the
`xctx-cache` Modal volume and `missing` lists any source not `ok`.

```bash
python mcp_server.py        # serves the tool over stdio
```

Register it with your MCP client (Claude Desktop / agent runtime) pointing at
`python /path/to/data_pipeline/mcp_server.py`.

### 2. Modal function (for backend / batch)
The app is deployed as **`xctx-evidence`** with function **`build_one`**. Call it
directly from Python, or fan out a gene list from the CLI:

```python
import modal
build_one = modal.Function.from_name("xctx-evidence", "build_one")
receipt = build_one.remote("TYK2", "psoriasis", "explore", run_id="...")
```

```bash
cd evidence_pipeline
modal run app.py --genes TYK2,CD28 --disease psoriasis --mode explore
# packages land on volume xctx-cache under runs/<run_id>/<gene>.json
modal volume get xctx-cache runs/<run_id> .      # pull results locally
```

## Output shape

Each package (`runs/<run_id>/<gene>.json` on the volume) contains:

- `gene` — normalized identity (symbol, Ensembl ID, entrez)
- `sources` — raw per-source results, each tagged with one of four statuses
- `summary` — counts and top items only, **no interpretation**
- `missing` — every source that was not `ok`, with its status and reason

### The four statuses (never conflated)
| Status | Meaning |
|--------|---------|
| `ok` | record found |
| `not_found` | query succeeded, source has no record (a database fact, **not** a biological negative) |
| `error` | technical failure — never cached, retried next run |
| `skipped` | disabled by mode, or an upstream step failed |

**Modes**: `explore` queries all five sources. `eval` disables PubMed and Open
Targets (both `skipped`) so benchmark answers cannot leak; cross-species sources
(orthology, GTEx, IMPC) stay on.

## Setup

```bash
pip install -r requirements.txt
modal setup                                   # first time only
# optional, raises PubMed rate limit:
#   modal secret create ncbi-api-key NCBI_API_KEY=...   then run with USE_NCBI_SECRET=1
modal deploy evidence_pipeline/app.py         # publishes xctx-evidence / build_one
```

## Files
| Path | Role |
|------|------|
| `evidence_pipeline/sources.py` | per-source fetchers; never raise, always return a `SourceResult` |
| `evidence_pipeline/cache.py` | content-addressed JSON cache (`ok`/`not_found` only) |
| `evidence_pipeline/package.py` | one gene → one evidence package (pure Python, runs without Modal) |
| `evidence_pipeline/app.py` | Modal app `xctx-evidence`; `build_one` fanned out with `starmap` |
| `mcp_server.py` | MCP tool `build_evidence_package` → deployed `build_one` |
| `tests/` | stub-based unit tests (status branches, cache rules, eval gating) |

## Tests

```bash
pytest tests/ -v      # 7 tests, no network (all fetchers stubbed)
```

## Verified (2026-09-22)
Ran live against all five APIs and through Modal:

| Gene | explore | eval |
|------|---------|------|
| TYK2 | all 5 sources `ok`, `missing=[]` | PubMed + Open Targets `skipped` |
| CD28 | rat ortholog `not_found` (legit), rest `ok`; mouse one2one → IMPC | + PubMed + Open Targets `skipped` |

## Notes / limitations
- `mcp` resolves to 2.x here, where `FastMCP` was renamed `MCPServer`; the server uses
  the new API (see the fallback note atop `mcp_server.py` for mcp 1.x).
- The MCP tool returns a receipt with the volume path, not the full package body; pull
  the package from the volume (or read it backend-side) to consume the evidence.
- Out of scope by design: drug-response prediction and imputing missing data. Missing
  data is reported explicitly, never inferred.
