# Evidence Pipeline — Data Flow (Person A)

Turns a **gene** or a **pathway** into one deterministic, **context-tagged evidence
package** — the factual substrate Person B's coordinator reasons over. It makes **no
judgments and no scores** (v3 §9): every field is a retrieved fact or an explicit gap.

## Two ways in

| Input | Command | Output |
|-------|---------|--------|
| **Gene** | `modal run app.py::main --genes MLH1,MSH2 --disease "colorectal cancer"` | per-gene evidence package |
| **Pathway** | `modal run app.py::pathway --reactome-id R-HSA-5358508` | pathway-level info — members, description, defining PMIDs, hierarchy, GO, mouse inference |

> Optional: `--members-evidence` also fans out per-member gene evidence and aggregates
> it by context (heavier; rarely needed — the default pathway view stays gene-fan-out-free).

## Flow

```mermaid
flowchart TD
    G([gene input]) --> ONE["build_one<br/>build_package (orthology · IMPC · GTEx · Open Targets · PubMed)<br/>+ enrich_invitro (HPA · DepMap) + HPA pathology"]
    ONE --> GPKG([gene package JSON])

    RID([pathway id input]) --> PW["resolve_pathway (participants + shared_participant)<br/>+ pathway_details (description · defining PMIDs · hierarchy · GO)<br/>+ infer_mouse_pathway (labeled)"]
    PW --> PPKG([pathway package JSON — pathway-level info, no gene fan-out])
    PW -.->|optional: --members-evidence| FAN["fan out build_one over members →<br/>aggregate_pathway (counts by context, no scores)"]
    FAN -.-> PPKG
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
    subgraph PAT ["PATIENTS — disease cohorts (cohort-level)"]
        direction TB
        P1["cohort background — HPA pathology (TCGA): disease involvement, cancer RNA"]
        P2["individual variation (patient/specimen IDs) — GAP"]
        P3["per-patient / matched needs GEO / CELLxGENE / GDC (out of scope)"]
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

## Source contracts

[`tools.md`](tools.md) is auto-generated from `registry.py` (v3 §4.5) — one entry per
source with purpose, inputs, output meaning, limitations, failure behavior, version, and
its §6 evidence dimensions (role, origin, measured/inferred, species, context, modality,
dependencies).

## Verified (2026-09-22)
Live on Modal — **gene input** (`MLH1`): in-vitro / in-vivo / human-reference evidence
built (PubMed PMIDs surfaced as provenance). **Pathway input** (`R-HSA-5358508`, default):
pathway-level info — 15 participants, description, 7 defining PMIDs, hierarchy
(`Mismatch Repair > DNA Repair`), GO, mouse inference — no gene fan-out. With
`--members-evidence`: in-vitro (HPA + DepMap, 7 essential), in-vivo (14 mouse one2one,
IMPC 5/5), human reference (GTEx), patients HPA cohort-level; 9 shared / 6 exclusive.
`pytest`: 29 passed.
