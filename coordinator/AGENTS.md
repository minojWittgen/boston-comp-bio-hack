# Coordinator handoff rules

These instructions cover `coordinator/`. Follow the repository's parent instructions
and the active task's scope and authorization. Coordinate changes to shared contracts
with the people working on the frontend, evidence integration, and scientific checks.

## Preserve the research contract

- `models.py` is the schema source of truth. The HTTP input is a nested `Submission`
  with `request` and optional `observations`, not a bare `InvestigationRequest`.
- Pass `request.mode` unchanged to collection. `eval` is a source-selection setting,
  not proof of held-out evaluation or a biomedical gold standard.
- Keep explicit question, genes, disease, requirements, comparisons, and supplied
  versioned pathway membership unchanged. Species, context, modality, endpoint,
  condition, tissue, host species, minimum study counts, and mandatory status are
  separate dimensions; do not silently relax one to make a run finish.
- Planning receives intent only, before evidence. Generated scope is an assumption
  requiring review. A model must not supply `criteria_met` or assert a validated
  orthology, context-alignment, or normalization basis.
- A plan's digest is frozen before collection. Follow-ups can retry collection under
  that plan; they must not rewrite the criteria after seeing the result.
- A pathway membership definition specifies scope, not measured activity. Do not turn
  a related gene, ortholog, RNA observation, or reference expression record into proof
  of pathway activation or conservation.

## Keep source meaning and result states separate

- Current pipeline packages adapt to `background` records. Do not relabel them as
  empirical `observation` records merely because fetching succeeded or a source has
  an in-vivo label. Preserve original raw payloads and provenance.
- A Modal collector response is a receipt; resolve and validate its package from the
  volume. Never trust a returned path without the request/path checks already present.
- Source absence, truncation, and technical errors are gaps, not biological negatives.
- Imported observations and comparison bases are declared metadata. Existing checks
  validate structure and consistency, not source truth, normalization validity,
  independence, statistical significance, causal claims, or clinical efficacy.
- `complete` is an execution/evidence-coverage status. `supported`, `conflicting`,
  `inconclusive`, and `not_assessable` are separate conclusions. A complete conflicting
  investigation is a valid result. Keep this distinction in APIs, tests, and UI text.
- Preserve study-based counts and evidence IDs; pair counts or duplicate rows are not
  independent replicates. Keep species separate from host species for xenografts.

## Module boundaries

| Responsibility | Files / interface |
| --- | --- |
| Shared schemas | `models.py`; coordinate any contract change before dependent edits. |
| Intent planning | `planner.py`, `prompts/intent.md`; `Planner.plan(request) -> ResearchPlan`. |
| Package retrieval and adaptation | `evidence.py`; `EvidenceProvider.fetch(...) -> dict`, `adapt_packages(...)`. |
| Declared-evidence checks | `checks.py`; `assess(plan, bundle) -> Assessment`. |
| Investigation lifecycle and reporting | `engine.py`; `Coordinator.create/execute`, `render_report`. |
| Configuration and persistence | `runtime.py`, `store.py`. |
| Frontend and cloud integration | `api.py`, `modal_app.py`, `jobs.py`; use `/openapi.json` for frontend types. |
| Offline demonstrations | `cli.py`, `examples/`, `tests/`. |

Read the relevant implementations before changing behavior; [`README.md`](README.md)
records the current handoff. Do not modify unrelated pipeline modules as part of a
coordinator-only task. Keep examples explicitly identifiable as demonstration fixtures.

## Development and verification

- Use the pinned `requirements.txt` in an isolated environment, such as `.venv`;
  install `requirements-dev.txt` for the offline tests. Keep run output outside the repository with
  `XCTX_RUN_DIR`; use an absolute `XCTX_EVIDENCE_DIR` for local package replay.
- Explicit requests must run without model credentials. Natural planning requires
  configured `ANTHROPIC_MODEL` and `ANTHROPIC_API_KEY`; never guess a fallback model or
  silently replace a failed model/provider call with fabricated evidence.
- Tests use fake model clients, provider handles, and declared fixtures. Do not add
  paid API calls or real deployment/network dependencies to the offline test suite.
- Test the behavior being changed, including preservation of scope and failure states.
  Run `python -m pytest coordinator/tests -q` for coordinated module integration.
- Verify both missing-evidence and conflicting-evidence examples after changes to
  contracts, checks, or orchestration. Do not claim those fixtures validate biology.
- Cloud changes must retain bounded calls, worker call-ID persistence, polling
  reconciliation, and authentication. Document any live verification actually performed;
  do not present fake-client tests as a verified deployment.
- Never store credentials in examples, reports, committed files, or error messages.
  Use configured environment variables and the named Modal secret.

## Attribution

The intent-before-evidence and criterion-verification procedure is informed by
[AutoSciRub commit 333a9e5](https://github.com/zjunlp/AutoSciRub/tree/333a9e5b7e405f54aca2e74d9c4f58aeece96332).
The coordinator uses original prompt/code rather than vendored AutoSciRub implementation.
Retain that distinction. Do not claim its results establish scientific accuracy or
reproduce AutoSciRub benchmark performance.
