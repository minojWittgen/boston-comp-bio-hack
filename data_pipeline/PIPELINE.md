# Evidence Pipeline — Data Flow (Person A)

Turns a **gene** or a **pathway** into one deterministic, **context-tagged evidence
package** — the factual substrate Person B's coordinator reasons over. It makes **no
judgments and no scores** (v3 §9): every field is a retrieved fact or an explicit gap.

## Two ways in

| Level | Input | Command |
|-------|-------|---------|
| Gene | symbols | `modal run app.py --genes MLH1,MSH2 --disease "colorectal cancer"` |
| Pathway **A** | Reactome id | `modal run app.py::pathway --reactome-id R-HSA-5358508` |
| Pathway **B** | gene → its pathway | `modal run app.py::pathway --gene MLH1` |

## Flow

```mermaid
flowchart TD
    G([gene]) --> ONE
    RID([Reactome id]) --> RES
    GB([gene, entry B]) --> P4G["pathways_for_gene<br/>gene → its Reactome pathway(s)"]
    P4G -->|pick first, keep alternatives| RES["resolve_pathway<br/>participants + shared_participant flag"]
    RES --> FAN

    subgraph FAN ["fan out build_one over participant genes (Modal starmap)"]
        ONE["build_package (per gene)<br/>background: orthology · IMPC · GTEx · Open Targets · PubMed"]
        ONE --> IV["enrich_invitro<br/>+ HPA cell lines + DepMap"]
    end

    FAN --> AGG["aggregate_pathway<br/>counts only, grouped by context<br/>+ anchor gene (entry B)"]
    RES -.->|inferred, labeled| MOUSE["infer_mouse_pathway<br/>Reactome mouse (isInferred=true)"]
    MOUSE --> AGG
    AGG --> PKG([evidence package JSON<br/>on volume xctx-cache])
```

## Evidence organized by context — mirrors the v3 §1/§2 boxes

Tracked as **context × species × modality × individual**. Unavailable contexts stay as
**visible gaps** (v3 §1), never dropped.

```mermaid
flowchart TB
    subgraph VITRO ["IN VITRO — cell lines / organoids"]
        direction TB
        V1["species: human · culture/cell-line IDs"]
        V2["RNA — HPA cell-line nTPM (summary)"]
        V3["protein — HPA subcellular / class"]
        V4["functional — DepMap CRISPR fitness (isEssential, geneEffect)"]
    end
    subgraph VIVO ["IN VIVO — animal models"]
        direction TB
        M1["species: mouse/rat/macaque · orthology type kept"]
        M2["phenotype — IMPC (phenotyped? MP terms)"]
        M3["pathway — Reactome mouse inference (LABELED inferred)"]
        M4["DNA/RNA/protein — gap"]
    end
    subgraph PAT ["PATIENTS — human cohorts + individual variation"]
        direction TB
        P1["patient/specimen/time-point IDs — none"]
        P2["DNA | RNA | protein | clinical — GAP"]
        P3["needs GEO / CELLxGENE / GDC (download+analysis, out of scope)"]
    end
    HR["human reference (background): GTEx baseline · Open Targets association* · PubMed"]
    VITRO --> PKG([context-tagged package])
    VIVO --> PKG
    PAT --> PKG
    HR --> PKG
    classDef gap fill:#fff0df,stroke:#ba8140,color:#573b1d;
    class PAT gap;
```

\* Open Targets **association** = disease link; skipped in `eval` mode (leaks answers).
Baseline expression, HPA, and DepMap fitness are **not** association → kept in `eval`.

## Contract, independence, aggregation

- **Four statuses**, never conflated: `ok` / `not_found` (a database fact, not a
  biological negative) / `error` (never cached, retried) / `skipped`.
- **Independence** (v3 §3): sources declare `source_dependencies`; a direct IMPC query
  and Open Targets' IMPC-derived evidence share the `IMPC` provider and count **once**.
- **No scores** (v3 §9): pathway rollup is counts only — per-species ortholog coverage,
  IMPC phenotyped ratio, DepMap essential count, and **shared vs exclusive participants**
  (PCNA/RPA/POLD also in DNA replication → `shared_participant`; MLH1/MSH2 exclusive).
- **anchor** (entry B): the input gene surfaced within its own program, so a
  "known-target's program" claim is readable at a glance.

## Source contracts

[`tools.md`](tools.md) is auto-generated from `registry.py` (v3 §4.5) — one entry per
source with purpose, inputs, output meaning, limitations, failure behavior, version, and
its §6 evidence dimensions (role, origin, measured/inferred, species, context, modality,
dependencies).

## Verified (2026-09-22)
Live on Modal for **Mismatch Repair (R-HSA-5358508)** and entry B (`--gene MLH1` →
R-HSA-5358565): 15 / 14 participants built in one pass; in-vitro (HPA + DepMap, 7
essential), in-vivo (14 mouse one2one, IMPC 5/5 phenotyped, mouse inference labeled),
human reference (GTEx), patients = explicit gap; 9 shared / 6 exclusive. `pytest`: 23 passed.
