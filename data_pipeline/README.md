# Evidence Pipeline (Person A)

Target-knowledge retrieval for the cross-context biology agent. Builds **deterministic,
context-tagged evidence packages** — the factual substrate Person B's agent reasons over
to produce a verdict. **This layer makes no judgments and computes no scores** (v3 §9):
every field is a retrieved fact or an explicit gap.

Two levels of input:

| Level | Input | Command |
|-------|-------|---------|
| **Gene** | gene symbols | `modal run app.py --genes MLH1,MSH2 --disease "colorectal cancer"` |
| **Pathway A** | Reactome id | `modal run app.py::pathway --reactome-id R-HSA-5358508` |
| **Pathway B** | gene → its pathway | `modal run app.py::pathway --gene MLH1` |

Pathway is the top-level unit (v3 §1/§8.2: "fix the pathway/program definition, then
assess"). Entry B anchors on a known target gene, resolves its Reactome pathway(s), and
surfaces that gene within its program (`anchor` block).

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
- `build_evidence_package(symbol, disease, mode)` — one gene
- `build_pathway_evidence(reactome_id | gene, disease, mode)` — one pathway

### Modal functions (deployed app `xctx-evidence`)
- `build_one(symbol, disease, mode, run_id)` — one gene → package
- `build_pathway(reactome_id, disease, mode, run_id, gene)` — pathway fan-out → aggregate

```python
import modal
modal.Function.from_name("xctx-evidence", "build_pathway").remote(
    "", "colorectal cancer", "explore", "run1", "MLH1")   # entry B
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
Live end-to-end for **Mismatch Repair (R-HSA-5358508)** and via entry B (`--gene MLH1` →
R-HSA-5358565): 14 participants built in one pass; in-vitro (HPA + DepMap, 7 essential),
in-vivo (13/14 mouse one2one, IMPC 4/4 phenotyped, mouse inference labeled), human-reference
(GTEx), patients marked as gap; 9 shared / 5 exclusive participants. `pytest`: 23 passed.
