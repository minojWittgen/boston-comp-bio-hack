# Evidence Pipeline (Person A)

Target-knowledge retrieval for the cross-context biology agent. Builds **deterministic,
context-tagged evidence packages** — the factual substrate Person B's agent reasons over
to produce a verdict. **This layer makes no judgments and computes no scores** (v3 §9):
every field is a retrieved fact or an explicit gap.

Two inputs:

| Input | Command | Output |
|-------|---------|--------|
| **Gene** | `modal run app.py::main --genes MLH1,MSH2 --disease "colorectal cancer"` | per-gene package **+ `reactome_pathways`: which pathways the gene is in and what each does** |
| **Pathway** | `modal run app.py::pathway --reactome-id R-HSA-5358508` | pathway-level rollup over all participant genes |

Natural flow: run a **gene** → read its `reactome_pathways` (pathway membership +
descriptions) → pick a pathway of interest → run that **pathway** id for the full rollup
(v3 §1/§8.2: "fix the pathway/program definition, then assess").

## The three contexts (v3 §1/§2)

Every evidence package tracks **context × species × modality × individual**. Unavailable
contexts stay as **visible gaps**, never silently dropped (v3 §1).

| Context | Sources | Modalities | Status |
|---------|---------|-----------|--------|
| **in vitro** | HPA cell lines, DepMap (Open Targets) | RNA, protein, CRISPR fitness | ✅ |
| **in vivo** | Ensembl orthology, IMPC, Reactome mouse inference* | phenotype/functional, orthology | ✅ |
| **human reference** | GTEx baseline, Open Targets association, PubMed | RNA, association, literature | ✅ |
| **patients** | — | individual variation | ⛔ **explicit gap** |

\* Reactome mouse pathway is **computationally inferred** and labeled as such — not an
independent cross-species experiment (v3 §4.4).

**Patients gap**: real per-patient/disease-cohort data (GEO / CELLxGENE Census / GDC)
needs dataset download+analysis, out of this retrieval layer's scope. The package marks
it explicitly (`summary.patients.status = "gap"`, `individual_variation = "not resolved"`)
with the unmet requirement and candidate sources.

## What Person B / Person C call

Same computation, two entry points:

### MCP tools (`mcp_server.py`, stdio)
- `build_evidence_package(symbol, disease, mode)` — one gene (includes `reactome_pathways`)
- `read_evidence_package(path)` — read a gene package using a receipt path issued in the same MCP session
- `build_pathway_evidence(reactome_id, disease, mode)` — one pathway

### Modal functions (deployed app `xctx-evidence`)
- `build_one(symbol, disease, mode, run_id)` — one gene → package
- `build_pathway(reactome_id, disease, mode, run_id)` — pathway fan-out → aggregate

```python
import modal
# one gene (package carries its pathway membership under sources.reactome_pathways)
modal.Function.from_name("xctx-evidence", "build_one").remote(
    "MLH1", "colorectal cancer", "explore", "run1")
```

Packages land on Modal volume `xctx-cache` under `runs/<run_id>/`.

## Sources & contracts

Every fetcher returns a `SourceResult` and **never raises**. Four statuses, never conflated:

| Status | Meaning |
|--------|---------|
| `ok` | record found |
| `not_found` | query succeeded, no record (a database fact, not a biological negative) |
| `error` | technical failure — never cached, retried next run |
| `skipped` | disabled by mode, or an upstream step failed |

**[`tools.md`](tools.md)** is the machine-readable contract for every source (purpose,
inputs, output meaning, limitations, failure behavior, version, and evidence dimensions) —
auto-generated from `registry.py` for the agent to read (v3 §4.5).

**Independence** (v3 §1/§3): sources declare `source_dependencies`; a direct IMPC query and
Open Targets' IMPC-derived evidence share the `IMPC` provider and are **not** counted as two
independent replications (`registry.independent_sources`).

**Modes**: `explore` runs everything. `eval` skips answer-leaking sources — Open Targets
**association** (disease link) and PubMed — but keeps baseline expression, HPA, and DepMap
fitness (not disease association, so no leak; v3 §5/§9).

## Pathway aggregation (no scores)

`build_pathway` resolves participants, fans out `build_one`, and rolls up **counts only**:
per-species ortholog coverage (one2one / one2many / many2many / no_ortholog), IMPC
phenotyped ratio, DepMap essential counts, and **shared vs exclusive participants**
(a gene also in DNA replication — PCNA, RPA, POLD — is flagged `shared_participant`, counted
separately from pathway-exclusive genes like MLH1, MSH2).

## Files

| Path | Role |
|------|------|
| `evidence_pipeline/sources.py` | per-source fetchers (Open Targets, Ensembl, GTEx, IMPC, PubMed, HPA, DepMap) |
| `evidence_pipeline/cache.py` | content-addressed cache (`ok`/`not_found` only) |
| `evidence_pipeline/package.py` | one gene → one package (pure Python, unchanged core) |
| `evidence_pipeline/invitro.py` | in-vitro enrichment (HPA + DepMap) layered onto a package |
| `evidence_pipeline/pathway.py` | Reactome participants / mouse inference / gene→pathway / aggregation |
| `evidence_pipeline/registry.py` | source registry (§4.5 + §6) + eval policy + independence + tools.md |
| `evidence_pipeline/app.py` | Modal app `xctx-evidence`: `build_one`, `build_pathway`, entrypoints |
| `mcp_server.py` | MCP tools for the agent |
| `tests/` | stub-based unit tests (no network) |

## Setup & test

```bash
pip install -r requirements.txt
modal setup                       # first time
modal deploy evidence_pipeline/app.py
pytest tests/ -v                  # 23 tests, no network
```

## Verified (2026-09-22)
Live on Modal. **Gene input** (`MLH1`): package carries `reactome_pathways` (7 pathways
with descriptions) plus in-vitro/in-vivo/human-reference evidence. **Pathway input**
(`R-HSA-5358508`): 15 participants built in one pass; in-vitro (HPA + DepMap, 7 essential),
in-vivo (14 mouse one2one, IMPC 5/5 phenotyped, mouse inference labeled), human-reference
(GTEx), patients marked as gap; 9 shared / 6 exclusive participants. `pytest`: 23 passed.

## Coordinator integration

`build_one` returns its archived JSON in a `package` field as well as the original
receipt (both unchanged), so it stays a drop-in for the coordinator's `ModalEvidence`
provider. The team coordinator currently validates the receipt and reads the committed
package from `xctx-cache`. The gene package read tool only accepts paths issued by its
own session; it does not read pathway receipts. All retrieved records remain background
evidence in the coordinator until an empirical observation adapter is provided; the new
`reactome_pathways` source rides along inside the package as more background.
