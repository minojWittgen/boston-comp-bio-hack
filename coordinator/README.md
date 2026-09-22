# Cross-context investigation coordinator

This service investigates what existing biological sources report about a question.
It collects source packages, explains their reported findings, compares species,
modalities and experimental contexts, and records unresolved questions and collection
limits. Investigation completion does **not** require proving a biological hypothesis.

The frontend, HTTP API, CLI and Modal worker share the same coordinator. Database
results (including GTEx medians, IMPC phenotypes, DepMap screens and HPA cohort
summaries) are usable findings at their reported scope. Their existing `background`
label is retained for compatibility; it does not exclude them from the investigation.
Source records are never silently promoted to normalized experimental observations.

## Execution and scientific meaning

```mermaid
flowchart TD
    Input[Research question and optional supplied observations] --> Intent[Define and freeze research scope]
    Intent --> Collect[Collect existing published source results]
    Collect --> Findings[Summarize findings with source records]
    Findings --> Compare[Explain species, modality and context differences]
    Compare --> Review[Account for scope, uncertainty and collection limits]
    Review --> Retry{Recoverable collection error and budget left?}
    Retry -->|Yes, at most once| Collect
    Retry -->|No| Report[Research report and next steps]
    Input --> Diagnostic[Optional supplied-observation checks]
    Diagnostic -. separate diagnostic, no completion gate .-> Report
```

`RunState.investigation` is the primary result in schema **0.2**. It contains grounded
`findings`, research `coverage`, descriptive `comparisons`, `limitations`, `next_steps`,
and deterministic research-completion `checks` / `criteria_met`.

| Execution status | Meaning |
| --- | --- |
| `queued` / `running` | Investigation has not finished. |
| `complete` | Bounded research work is accounted for, findings and limits are reported. Biology may remain unresolved. |
| `partial` | Collection or scope coverage remains incomplete; available findings are still reported. |
| `failed` | A planning, scheduling, execution or contract failure prevented the investigation. |

`coverage.status` (`addressed`, `limited`, `unavailable`) describes the material found
for a research question. It is **not** a true/false biological verdict. A search that
returns no hits can be a completed search when that outcome is recorded; it is not
proof that evidence does not exist. Technical errors, malformed packages, unsearched
entities and truncated collection remain visible limitations. No percentage is used
as a universal biological confidence score.

The original `assessment` field remains available for explicitly supplied observation
checks and historical clients. Its `criteria_met`, study minimum and `conclusion` do
**not** determine investigation completion. It does not count retrieved database
summaries as independent studies or independently certify their scientific validity.
Old saved states without `investigation` remain readable with their original meaning.

Species, host species, in-vitro/in-vivo/patient context and modality remain separate.
Cohort summaries cannot resolve individual patient variation. RNA, protein location,
sequence identity, CRISPR fitness and clinical outcomes retain their own meanings.
Describing them together does not establish equal effects or enable numeric pooling.

This patch uses deterministic, source-specific summaries and bounded technical retries.
It adds no post-retrieval model call, autonomous literature-reading tool, raw-data
analysis or discovery of new experiments. The existing provider still fetches genes;
versioned pathway membership remains scope, not activity. Multi-pathway execution
is not added here. These limits must stay visible in handoffs and benchmarking.

See [the investigation-first handoff](../docs/investigation-first-handoff.md) for
migration and benchmark changes.

## Run locally

Run these commands from the repository root. Runtime package versions are pinned in
[`requirements.txt`](requirements.txt); use an isolated environment.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r coordinator/requirements.txt
export XCTX_EVIDENCE_DIR="$PWD/coordinator/examples/packages"
export XCTX_RUN_DIR="/tmp/xctx-investigations"
.venv/bin/python -m uvicorn coordinator.api:create_app --factory --host 127.0.0.1 --port 8000
```

`XCTX_EVIDENCE_DIR` above resolves to an absolute directory of `<gene>.json` packages.
The directory provider replays those files and preserves their original provenance.
Packages must match the requested gene, disease, and collection mode. Run snapshots go
to the external `XCTX_RUN_DIR`, not the repository. If `XCTX_EVIDENCE_DIR` is unset, the
runtime uses the existing Modal evidence collector; there is no silent fixture fallback.

`request.mode` is `explore` by default and can be `eval`; it is passed unchanged to the
collector. It controls source selection only. `eval` does not establish an independent
held-out evaluation or a biomedical gold standard.

Explicit requests with `requirements` and `genes` (or supplied versioned pathway genes)
need no model credentials. Requests without requirements use `ClaudePlanner` and require
both `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` in the environment. The model name is never
guessed. Planning makes one strict schema-tool call with automatic tool choice, disables SDK
retries, and has a 60-second provider timeout. This supports models that reject forced
tool choice. The response must still contain exactly one complete, schema-valid research
plan; text-only, truncated, and multiple-tool responses are rejected without starting
collection. The SDK transforms the tool schema for provider compatibility; the original
Pydantic schema and scope-preservation checks still validate the response. Provider
refusals are reported explicitly, without retrying or changing models. There is no paid
model call in the offline test suite.

Replay the two supplied demonstrations using the same environment variables:

```bash
.venv/bin/python -m coordinator.cli coordinator/examples/missing-evidence.json
.venv/bin/python -m coordinator.cli coordinator/examples/cross-context-conflict.json
```

These are software demonstration fixtures, not biological findings. Both include explicit collection limits; inspect `investigation` for research completion and
`assessment` only for the separate supplied-observation diagnostic. The CLI prints the full `RunState` JSON. Its exit status is nonzero
only for `failed`; callers must inspect the result to distinguish partial evidence from
completed comparison.

## Frontend API contract

Use **`GET /openapi.json`** as the schema source for generated frontend types. The source
of truth is [`models.py`](models.py); do not maintain a separate handwritten request
schema. FastAPI also serves interactive documentation at `/docs`.

| Endpoint | Contract |
| --- | --- |
| `GET /health` | Service health and schema version; not scientific readiness. |
| `POST /investigations` | Accepts a nested `Submission`; returns HTTP 202 with `run_id`, `status`, and `status_url`. |
| `GET /investigations/{run_id}` | Returns the complete `RunState`, including stage, events, frozen plan, evidence, assessment, and error/report when available. |
| `GET /investigations/{run_id}/report` | Returns plain text containing Markdown; returns HTTP 409 before a report is available. |

The POST body has **`request` and `observations` at its top level**. Do not POST the
request fields directly. For example, this explicit request needs no model:

```json
{
  "request": {
    "question": "Is EGFR RNA abundance increased in human lung tumor samples?",
    "genes": ["EGFR"],
    "disease": "lung adenocarcinoma",
    "requirements": [
      {
        "id": "patient-rna",
        "title": "Patient tumor RNA observation",
        "entity": "EGFR",
        "species": "homo_sapiens",
        "context": "patient",
        "modality": "RNA",
        "endpoint": "RNA abundance change versus paired normal",
        "condition": "tumor",
        "tissue": "lung",
        "min_studies": 1,
        "required": true
      }
    ],
    "comparisons": [],
    "max_revisions": 1
  },
  "observations": []
}
```

Empty observations are valid input and will not be replaced with invented findings.
For a complete working fixture request, submit one of the demonstration files:

```bash
curl -X POST http://127.0.0.1:8000/investigations \
  -H 'Content-Type: application/json' \
  --data-binary @coordinator/examples/cross-context-conflict.json
```

When `COORDINATOR_API_TOKEN` is configured, all investigation endpoints require
`Authorization: Bearer <token>`. Local development can omit it; Modal deployment requires
it. `XCTX_ALLOWED_ORIGINS` accepts comma-separated frontend origins and defaults to
`http://localhost:3000,http://127.0.0.1:3000`. Poll until a terminal status and display
the investigation findings, coverage, limitations and next steps first; expose optional
observation diagnostics separately. A failed run may have no report; show its `error` and event history.

## Module responsibilities and integration interfaces

| Module / owner | Interface | Boundary |
| --- | --- | --- |
| `models.py` / shared contracts | `Submission`, `InvestigationRequest`, `ResearchPlan`, `EvidenceRecord`, `RunState` | All API and worker schemas; coordinate changes across teams. Extra fields are rejected. |
| `planner.py`, `prompts/intent.md` / intent planning | `Planner.plan(request) -> ResearchPlan`; `ExplicitPlanner`; `ClaudePlanner(model=None, client=None)` | Intent only; no evidence input. Exact structured scope is preserved. |
| `evidence.py` / collection integration | `EvidenceProvider.fetch(symbol, disease, mode, run_id) -> dict`; `adapt_packages(packages) -> EvidenceBundle` | Resolve real packages, preserve raw payload/provenance, retain collection gaps. |
| `investigation.py` / research synthesis | `investigate(plan, bundle) -> InvestigationAssessment` | Use returned findings, preserve scope differences, account for collection limits; determine research completion. |
| `checks.py` / declared-evidence checks | `assess(plan, bundle) -> Assessment` | Deterministic scope and comparability checks; never modify criteria or infer missing evidence. |
| `engine.py` / orchestration | `Coordinator.create(submission)`; `execute(run_id, submission)`; `render_report(state)` | Freeze plan, persist events, collect, synthesize, independently check optional observations, bounded technical retry, report. |
| `runtime.py` / configuration | `build_coordinator(store=None)`; `AutoPlanner.plan(request)` | Explicit criteria choose the model-free planner; evidence directory selects replay. |
| `store.py` / persistence | `save(state)`, `get(run_id)`; Modal job ID storage | Atomic local JSON snapshots or shared Modal Dict. |
| `api.py` / frontend integration | `create_app(coordinator=None, dispatch=None, api_token=None, refresh=None)` | HTTP submission, polling, reports, authentication, and CORS. |
| `modal_app.py`, `jobs.py` / cloud runtime | `investigate`, `web`, `reconcile_job(state, store)` | Detached cloud execution and worker-result reconciliation during polling. |
| `cli.py` / local demonstrations | `python -m coordinator.cli <submission.json>` | The same engine with a JSON submission file. |

The planner rejects changes to explicit question, genes, disease, requirements,
comparisons, and versioned pathway membership. Natural-language gene extraction only
accepts symbols literally present in the question. Generated criteria are marked as
assumptions; free-text interpretation completeness is not independently verified.
Model-proposed cross-species or context-alignment bases are retained only as unverified
assumptions, with the executable comparison basis left null. Explicit user-supplied
bases are preserved, but their scientific validity is not thereby certified.

The engine permits at most one follow-up because `max_revisions` is limited to 0 or 1.
Its default 240-second budget prevents starting further collections once exhausted;
it is not a hard wall-clock limit for an already running call. The Modal evidence
provider allows 120 seconds for a collector call and attempts cancellation on timeout.
The coordinator Modal worker has a separate 600-second timeout and no automatic retry.

## Modal deployment handoff

The coordinator expects an existing evidence deployment:

- Modal app `xctx-evidence`, function `build_one`.
- Existing volume `xctx-cache` holding `runs/{run_id}/{symbol}.json`.
- A Modal secret named `xctx-coordinator` containing `ANTHROPIC_API_KEY`,
  `ANTHROPIC_MODEL`, and `COORDINATOR_API_TOKEN`; optionally `XCTX_ALLOWED_ORIGINS`.

From the repository root, with Modal authentication already configured:

```bash
.venv/bin/python -m modal deploy -m coordinator.modal_app
```

The app is named `xctx-coordinator`. It uses the pinned runtime requirements, includes
the planner prompt, runs up to four investigation worker containers, and stores state
in the shared `xctx-investigations` Modal Dict. Leave `XCTX_EVIDENCE_DIR` unset for real
collector integration; a local replay path does not automatically exist in the image.

The collector returns a receipt. `ModalEvidenceProvider` validates the exact requested
gene/run path, reads the committed JSON from `xctx-cache`, and validates the package
against the requested gene, disease, mode, and run. A receipt alone is not evidence.

Dispatch saves the detached worker's call ID. Subsequent state/report polls reconcile
that call non-blockingly: pending work stays running, a valid terminal result updates
the snapshot, and a terminated or timed-out worker becomes failed. A temporary failure
to contact Modal does not prove worker failure. Reconciliation occurs during polling
and needs the saved call ID; it is not an independent background monitoring service.

**Live Modal deployment and live model/provider execution have not been verified in
this handoff.** Local fake-provider tests exercise the contracts and failure paths.

## Scientific limits that integrations must retain

Current source packages contain identifier normalization, sequence orthology, GTEx
reference tissue medians, descriptive mouse knockout phenotypes, Open Targets
associations, and PubMed search identifiers/counts. The adapter labels all of these
records `background`, even where a source describes an in-vivo phenotype. They do not
fulfil this coordinator's `observation` requirements. A database miss, omitted row, or
failed request is never interpreted as a biological negative.

Caller-supplied `observations` provide the empirical side of this demonstration.
Qualification requires exact declared entity/species/context/modality/endpoint,
specified condition/tissue/host fields, provenance, source, a study ID, and unique
evidence identity. Comparisons also check endpoint, contrast, comparability key, and
relevant pairing or declared alignment bases. Multiple rows from one study do not
increase the study count; distinct supplied study IDs do not prove cohort independence.

These checks establish **structural consistency of supplied metadata**, not source
truth, valid effect estimation, verified normalization, study quality, or scientifically
valid cross-context alignment. `supported` means descriptive agreement in observed
direction within the eligible subset. It is not significance, causality, clinical
efficacy, or a proof of biological conservation. Supplied versioned pathway membership
defines a gene scope; it does not measure pathway activity. RNA abundance, protein
abundance, and protein activity remain different endpoints.

## Remaining team integration slots

1. **Frontend:** generate types from `/openapi.json`; submit nested `Submission`; show
   events, scope assumptions, criterion evidence IDs, terminal status, conclusion, and
   gaps without equating “complete” with biological support.
2. **Observed-data adapter:** connect one real public dataset or analysis artifact to
   `EvidenceRecord`, with traceable study/assay/contrast/direction and explicit context,
   measured species, tissue, condition, and host where applicable. Do not promote a
   search result or abstract into a measured observation automatically.
3. **Analysis worker:** provide the actual data processing or statistical calculation
   producing those observations. This coordinator currently neither computes a gene
   program nor runs single-cell or bulk differential analysis.
4. **Scientific review:** verify study provenance, independence, comparisons, and
   normalization before treating imported metadata as evidence. Future typed validation
   artifacts can replace the current declared-basis strings through an agreed schema
   change.
5. **Cloud acceptance:** verify the existing collector/volume, configured secret,
   authenticated API, detached execution, and terminal-state polling with a real run.

Install the development requirements and run offline checks:

```bash
.venv/bin/python -m pip install -r coordinator/requirements-dev.txt
.venv/bin/python -m pytest coordinator/tests -q
```

The intent-first criteria and separate verification procedure are informed by
[AutoSciRub at commit 333a9e5](https://github.com/zjunlp/AutoSciRub/tree/333a9e5b7e405f54aca2e74d9c4f58aeece96332).
This is an adaptation of procedures using an original prompt and application code;
no AutoSciRub code or skill text is vendored. It does not implement the complete
AutoSciRub system or inherit any reported scientific accuracy or benchmark performance.
