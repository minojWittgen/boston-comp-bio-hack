# Evidence Pipeline — Data Flow

Person A's pipeline turns **one human gene symbol** into **one evidence-package JSON**
by querying five target-knowledge sources, caching every result, and fanning the work
out across Modal containers. The LLM coordinator never touches the network — it only
reads the deterministic package these tools produce.

## Status contract

Every source fetcher returns a `SourceResult` and **never raises**. Exactly four statuses:

| Status | Meaning | Cached? |
|--------|---------|---------|
| `ok` | record found | ✅ |
| `not_found` | query succeeded, source has no record (a database fact, not a biological negative) | ✅ |
| `error` | technical failure (network, schema drift, rate limit) | ❌ never |
| `skipped` | disabled by mode, or an upstream step failed | n/a |

## Per-gene source flow (`package.build_package`)

```mermaid
flowchart TD
    IN([symbol, disease, mode, run_id]) --> NORM["MyGene<br/>normalize_gene(symbol)"]
    NORM -->|ok → ENSG| GATE{ensembl_primary<br/>resolved?}
    NORM -->|error / not_found| GATE
    GATE -->|no ENSG| SKIP["downstream sources → skipped<br/>(reason: gene normalization failed)"]

    GATE -->|ENSG ok| ORTHO
    subgraph ORTHO ["Ensembl orthology — one call per species"]
        MM["mus_musculus"]
        RN["rattus_norvegicus"]
        MC["macaca_mulatta"]
    end

    MM -->|"unique one2one<br/>mouse symbol?"| IMPCGATE{exactly one<br/>one2one ortholog?}
    IMPCGATE -->|yes| IMPC["IMPC<br/>statistical-result: phenotyped?<br/>genotype-phenotype: hits"]
    IMPCGATE -->|no| IMPCSKIP["IMPC → skipped<br/>(no unique one2one ortholog)"]

    GATE -->|ENSG ok| GTEX["GTEx v8<br/>reference/gene → gencodeId<br/>median expression by tissue"]
    GATE -->|ENSG ok| OT["Open Targets GraphQL<br/>target + associatedDiseases"]
    IN --> PUBMED["PubMed E-utilities<br/>esearch: symbol[tiab] AND disease"]

    ORTHO --> ASM
    IMPC --> ASM
    IMPCSKIP --> ASM
    GTEX --> ASM
    OT --> ASM
    PUBMED --> ASM
    SKIP --> ASM

    ASM["assemble package<br/>gene · sources · summary · missing"] --> OUT([evidence_package JSON])

    classDef skip fill:#eee,stroke:#999,color:#666;
    class SKIP,IMPCSKIP skip;
```

**Mode gating** — `--mode eval` disables `pubmed` and `opentargets` (both become `skipped`)
so benchmark answers cannot leak; cross-species sources (orthology, GTEx, IMPC) stay on.

## Cache layer (`cache.JsonCache`)

```mermaid
flowchart LR
    REQ["fetch(source, query, fn)"] --> HIT{cache hit?}
    HIT -->|yes| RET["return cached<br/>(cache_hit=true)"]
    HIT -->|no| CALL["call fn() → SourceResult"]
    CALL --> STORE{status in<br/>ok / not_found?}
    STORE -->|yes| WRITE["content-addressed write<br/>sha256(source+query+version)"]
    STORE -->|no error| PASS["return, do NOT store<br/>(retries next run)"]
    WRITE --> RET2["return fresh"]
```

Content-addressed by `sha256({source, query, CACHE_VERSION})`; writes are atomic
(`tmp` + `os.replace`). Bump `CACHE_VERSION` when a fetcher's output shape changes.

## Fan-out & serving (`app.py`, `mcp_server.py`)

```mermaid
flowchart TD
    CLI["modal run app.py<br/>--genes TYK2,CD28 --disease psoriasis --mode explore"]
    MCP["MCP tool<br/>build_evidence_package(symbol, disease, mode)"]

    CLI -->|starmap over genes| FN
    MCP -->|"Function.from_name('xctx-evidence','build_one').remote()"| FN

    subgraph MODAL ["Modal app: xctx-evidence (max 8 containers)"]
        FN["build_one(symbol, disease, mode, run_id)"]
        FN --> BP["build_package()"]
        BP --> VOL[("Volume xctx-cache<br/>cache/… + runs/&lt;run_id&gt;/&lt;gene&gt;.json")]
    end

    FN --> MAN["local runs/&lt;run_id&gt;/manifest.json<br/>(per-gene status + missing)"]
    VOL --> DOWN["modal volume get xctx-cache runs/&lt;run_id&gt;"]
```

Containers `vol.reload()` before reading and `vol.commit()` after writing, so cache
entries are shared across the fan-out. Optional `ncbi-api-key` secret raises the PubMed
rate limit when `USE_NCBI_SECRET=1`.

## Verified end-to-end (2026-09-22)

| Gene | explore | eval | Notes |
|------|---------|------|-------|
| TYK2 | all 5 sources `ok`, `missing=[]` | pubmed/opentargets `skipped` | GTEx, IMPC (24 hits), Open Targets all live |
| CD28 | rat ortholog `not_found` (legit), rest `ok` | + pubmed/opentargets `skipped` | mouse one2one → IMPC (4 hits) |

Both genes ran through Modal; packages landed on the `xctx-cache` volume under
`runs/20260922T154435-explore/` and `runs/20260922T154534-eval/`.
