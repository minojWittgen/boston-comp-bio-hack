# benchmarking — cross-context evidence evaluation (v4, handoff 2026-09-22)

Two suites, reported separately and never pooled.

| Suite | Question it answers | Input boundary | Systems | Deliverable |
|---|---|---|---|---|
| **PRIMARY** (`primary/`) | Does the integrated system produce more scientifically justified answers to the same research request than a competent general-purpose agent? | Same task + same frozen **source corpus** (methods excerpts, DE tables, specimen metadata, native API responses). Each system does its **own** extraction, structuring, comparison, interpretation. | `baseline` (general agent, same model) vs `integrated` (actual collector → normalization → coordinator) | Short report: conclusion per comparison + citations to source locations + limitations + unresolved |
| **SECONDARY** (`cases/`, `fixtures/`) | Given the same normalized observations, how does coordinator-level interpretation and checking compare to a baseline? | Shared, pre-normalized observation records + stubbed retrieval | `A0` / `A` / `B` (checklist scaffold, *not* the product) / `C` (coordinator adapter) | Per-axis verdicts |

The primary result is the headline. The secondary result diagnoses where a difference comes
from; **its score is never presented as the score of the full product.** Methodological
reference: AutoSciRub's paired comparison with a hidden external rubric and separate component
experiments — adopted as principles, not reproduced.

## Integrated system — how it is connected (handoff 2026-09-22 §1)

`bench/integrated_adapter.py` now runs the **actual** system end to end. Neither `data_pipeline/` nor
`coordinator/` is modified; the adapter only wires them to the frozen corpus.

```
task.md + corpus/ ─► DATA PIPELINE   real package.build_package → invitro.enrich_invitro → hpa_pathology
                                      → registry.annotate_package  (the same chain app.build_one runs)
                     (bench/integration/pipeline_provider.py: sources.http replayed from corpus/api/index.json
                      — recorded native responses for every request the pipeline makes in eval mode; 0 unrecorded)
                  ─► EXTRACTION       bench/integration/extractor.py: one model call per study reads methods.md into
                     + NORMALIZATION  structured metadata (species, context, tissue, condition, contrast class, which
                                      table holds what) using the frozen plan's vocabulary; directions computed from the
                                      tables; per-participant records with subject/specimen/visit; provenance to
                                      corpus://file#locator on every record; missing metadata stays None
                  ─► COORDINATOR      real ClaudePlanner (its own prompt, injected usage-counting client) → frozen plan
                                      → Coordinator.execute (collection via the same provider, checks, bounded retry,
                                      report) — the plan is passed through a FrozenPlanner so it is not paid for twice
                  ─► ENVELOPE         RunState mapped to schema/report.schema.json: supported→supported,
                                      conflicting→opposed, inconclusive/not_assessable→insufficient_evidence;
                                      citations come from record provenance; the coordinator's own report is the
                                      report_markdown; nothing is added or corrected
```

Every model call in every stage goes through one `UsageClient` bound to the run's deadline and budgets;
`_system_internal` carries versions (repo / data_pipeline / coordinator commits), stages, extraction trace,
replay log, model inventory and the full RunState. `harness/calibration_trace_offline.json` is the public
calibration trace (offline stand-in for the two model calls; every other stage real).

**What the connected system currently does on these cases** (offline calibration; real-model runs may differ):
the planner nulls any model-proposed cross-species / context-alignment basis (`coordinator/planner.py`,
`_annotate_inferences`) and the checker rejects pairs without one, so `in_vitro_vs_animal` and
`in_vitro_vs_patient_rna` come back **insufficient_evidence ("missing declared cross-species basis" /
"different condition alignment without declared context-alignment basis")**. The within-person axis is
assessed correctly (supported when biopsies are shared, insufficient when proteomics used a second
cohort). This is the coordinator's declared comparison policy showing through, not an adapter defect;
it is the coordinator owner's item in the handoff table. The adapter must not supply the missing basis.

`xctx-p04` (two genes + two pathway definitions) currently ends in `execution_status=error`:
`InvestigationRequest.pathway` holds one definition and the planner refuses a pathway request without
membership — the §5 single-pathway limitation, reported as such.

## Primary suite

```
primary/cases/xctx-p0N/
├── task.md                     the research request (identical wording across cases)
├── manifest.json               permitted_files, tools, limits — no answers
└── corpus/                     PROVENANCE.json (synthetic, labelled), README_CORPUS.md,
    ├── study_A_invitro/        methods.md, de_results.csv
    ├── study_B_mouse_imq/      methods.md, de_results.csv, animals.csv        ← measured animal evidence
    ├── study_C_patient_cohort/ methods.md, specimens.csv, rna_log2cpm.csv, protein_npx.csv
    └── api/                    mygene / ensembl homology / gtex / impc — native-shaped, background only
```

| Case | Purpose | Correct scoped answer |
|---|---|---|
| xctx-p01 | scoped agreement — catch unjustified abstention | all three comparisons supported; within-person established from `specimens.csv` |
| xctx-p02 | animal-context disagreement | mouse IMQ Tyk2 **opposed** under a valid comparison; patient support retained |
| xctx-p03 | invalid within-person matching | within-person **insufficient_evidence** (protein participants Q01..Q12 ≠ P01..P12); population-level findings preserved |

Both systems get: `task.md`, the corpus, and equivalent basic access (`list_files`, `read_file`,
`search`, `python_eval` restricted to the corpus). The baseline gets a competent general research
instruction and tool docs — **no checklist, no workflow, no pre-extracted evidence**. The whole run
is measured (every model call, every stage, every model id) into a harness-signed usage record.

Grading (`held_out/primary_rubric.json`, frozen, independently reviewed, never under `primary/`):
mechanical rows (integrity, execution, conclusion per comparison, citations resolve to real file
locations, unsupported corroboration, task completion) plus **blind human review**.

**Research quality is the review score, not the mechanical rows.** Per
[`docs/investigation-first-handoff.md`](../docs/investigation-first-handoff.md), each run is scored
blind on five dimensions, **0** (absent/wrong) · **1** (partial) · **2** (adequate):

| Dimension | Question |
|---|---|
| `relevant_findings` | Does it use the available evidence to address the question? |
| `faithfulness` | Do values, units and claims match the cited source material? |
| `traceability` | Can material claims be traced to actual returned records? |
| `context` | Are species, modality, in-vitro/in-vivo/patient and cohort/individual distinctions preserved? |
| `uncertainty` | Does it explain disagreement, missing information and realistic next steps? |

Four **critical errors** are answered true/false and reported *separately* — never averaged away,
because one of them in an otherwise polished report is the finding: invented citation or value,
cohort-to-individual claim, orthology-to-conservation claim, and technical failure presented as
biological absence.

No credit for JSON, for declaring criteria met, for tool use, for a longer report, for a conclusive
answer, or for abstaining when the evidence is assessable. Reviewer decisions and blinding clues are
preserved across regrades.

### Two axes, since coordinator RunState 0.2

The coordinator now reports **research completion** and **biological assessment** separately, and a
run is routinely `complete` *and* `not_assessable` at the same time. That is the expected steady
state, not a contradiction:

- `status` / `investigation.*` — was the bounded research work done, and what was covered
  (`addressed` · `limited` · `unavailable` per requirement).
- `assessment.conclusion` — the optional supplied-observation diagnostic. It no longer gates status
  or retries, and **must not be read as the score for the whole investigation.**

The benchmark records both (`_system_internal.stages[].coordinate`) and scores neither from the
other. `investigation.criteria_met` is a system's own claim about itself and earns nothing.

```bash
pip install -r bench/requirements.txt
export ANTHROPIC_API_KEY=...  XCTX_MODEL=claude-sonnet-4-5
export XCTX_PIPELINE=/path/to/data_pipeline/evidence_pipeline     # default: ../data_pipeline/evidence_pipeline
export XCTX_REPO_ROOT=/path/to/repo                                # default: ../ (must contain coordinator/)
# Both defaults resolve inside this repository — `data_pipeline/` and `coordinator/` are siblings
# of `benchmarking/` on main, so neither variable needs setting for an in-repo run.

python bench/gen_primary.py                 # corpus for p00..p04 (synthetic, labelled) incl. recorded API responses
python validate.py
python bench/integrity_probes.py            # 35 probes; must end "Safe to collect model scores."

python bench/run_primary.py --system mock mock-careless --batch primary-smoke     # harness check, no LLM
python bench/grade_primary.py runs/primary-smoke --no-unblind

XCTX_FAKE_LLM=1 python bench/run_primary.py --system integrated mock --batch smoke-1   # offline: whole chain, no model
python bench/run_primary.py --system integrated baseline --cases xctx-p00 --batch calib-1   # PUBLIC CALIBRATION RUN (paid)
# measure runtime here; if it does not fit the limits, reduce scope for BOTH systems in bench/spec.json before freezing

python bench/run_primary.py --system baseline integrated --batch primary-final       # the pilot: 2 × 3 × 1 (+ p04 if claiming §5)
python bench/grade_primary.py runs/primary-final --no-unblind    # reviewer fills runs/primary-final/review.json blind
python bench/grade_primary.py runs/primary-final                 # unblind → summary.json
```

Claim template after real runs: *"On three frozen cross-context research tasks, starting from the
same source material, our integrated system achieved X/3 correctly scoped outcomes versus Y/3 for a
general-purpose agent using the same Claude model and resource limits; costs and failures are
reported."* Three cases × one execution is a demonstration, not an estimate. Recovery behaviour is
**not** measured by these three cases; report it only if the secondary suite's declared recovery
case (xctx-003) is actually run.

## Secondary suite (component test)

Shared normalized observations (`schema/observation.schema.json`), stubbed retrieval, per-axis
verdicts, verified checklist ledger for `B`, coordinator adapter contract for `C`
(`bench/coordinator_adapter.py`). Cases: xctx-001 scoped agreement, xctx-002 invalid within-person
pairing, xctx-003 recoverable required in-vivo observation that flips an axis.

```bash
python bench/gen_fixtures.py --stub          # or --live / --from-package
python bench/run_cases.py --config A B --batch secondary-final   # or A C once the adapter exists
python bench/grade.py runs/secondary-final --no-unblind && python bench/grade.py runs/secondary-final
```

Claim template: *"Given the same normalized observations, we compared coordinator-level
interpretation and checking against a baseline."* It does not measure extraction, evidence
discovery, or the integrated product.

## Held-out material (needed before anything can be graded)

Two files, both **git-ignored and never committed** — publishing either invalidates the runs:

| File | Used by | Status |
|---|---|---|
| `held_out/reference_answers.json` | `bench/grade.py`, integrity probe groups 5/5b/6 | must match the v2+ schema (`expected_axes`, `accepted_overall`, `required_actions`, `forbidden`, `status_interpretation_expected`) — a v1 key fails validation |
| `held_out/primary_rubric.json` | `bench/grade_primary.py` | not yet written; the acceptance checklist box for it is still open |

> **Placement matters.** `common.py` sets `HELD_OUT = ROOT / "held_out"`, i.e.
> `benchmarking/held_out/`. Both files must sit **inside this directory, untracked** — not in a
> parent. There is no environment variable to point elsewhere, so anywhere else and
> `grade.py`, `grade_primary.py` and `integrity_probes.py` all fail with `FileNotFoundError`.
> Generating, validating and *running* both suites work without them; only grading and the
> probes need them.

Neither generator writes these files — `gen_fixtures.py` prints "held_out/ untouched" and
`gen_primary.py` prints "Rubric lives in held_out/primary_rubric.json — never inside
primary/". They are hand-maintained and independently reviewed by design.

Token accounting for both suites is specified in [`harness/usage_capture.md`](harness/usage_capture.md).

## What the 22 Sep review found and where it is fixed

| Finding | Fix (file) |
|---|---|
| Case 3 misused GTEx abundance as contradiction; claim was a pathway/state claim | Directional mRNA claim; opposition comes from a measured mouse endpoint under a declared comparison; GTEx background only (`bench/spec.json`, `bench/gen_primary.py`, `bench/gen_fixtures.py`) |
| Within-person question implicit; participant vs specimen identity conflated | Task asks it explicitly; `specimens.csv` / `samples[]` carry participant, specimen, visit; aggregates computed from samples |
| Self-reported ledger accepted N/A and "retry later" | Verified ledger: evidence ids from the right context, executed follow-ups, applicability checks (`bench/agents.py`) |
| Path escape, harness files readable | Resolved-path allowlist; harness files unreadable; corpus tools sandboxed incl. `python_eval` (`bench/common.py`, `bench/primary_common.py`) |
| Keyword grading penalised correct prose; rat citation satisfied mouse; confirms overwritten; runtime failure credited as abstention | Structured status grading; exact source + resolvable locator + support relation; reviewer decisions preserved and gating; `execution_status` separate (`bench/grade.py`, `bench/grade_primary.py`) |
| Budget: 4× cumulative slack, fabricated usage accepted, no per-call deadline, cache tokens missing | Cumulative + per-call limits, deadline on every request, cache-read/creation counted, harness-signed usage, blind-file hashes (`bench/common.py`) |
| Fixture provenance and literature scope | `provenance` on every record; `PROVENANCE.json` per corpus; literature layer labelled summary-judgment |

## Handoff checklist (2026-09-22 implementation handoff)

| § | Item | Status |
|---|---|---|
| 1 | `integrated_adapter.py` invokes the actual pipeline and coordinator | done — `bench/integration/`, no pipeline/coordinator edits |
| 1 | Pipeline data access bound to the frozen corpus via recorded responses | done — `corpus/api/index.json`, 0 unrecorded requests on every case |
| 1 | Real extraction / normalization path (no hand-authored observations) | done — `extractor.py`; generic over corpus conventions; model-assisted; provenance on every record |
| 1 | Provenance through every stage; missing stays missing | done |
| 1 | Coordinator follow-up fed back | coordinator retries collection through the same provider; observations are a fixed Submission (coordinator contract) |
| 1 | Faithful envelope mapping; complete ≠ supported | done — `_map()` |
| 1 | Versions + every model call recorded | done — `versions`, `model_inventory`, single `UsageClient` |
| 1 | One public calibration run with a full-stage trace | offline trace committed (`harness/calibration_trace_offline.json`); **paid calibration run still to do** |
| 2 | Same question / corpus / limits / model; no pre-extracted input | done — limits in `bench/spec.json` apply to both |
| 3 | Rubric independently reviewed and frozen | **open** — `held_out/primary_rubric.json → _review_status` (runner refuses scored batches until set) |
| 3 | Correct / careless / malformed answers get intended outcomes; incomplete review cannot pass | done — probes 13, review gating |
| 4 | `python_eval` isolation | done — subprocess, audit hook, CPU/time limit (`bench/_sandbox.py`) |
| 4 | Malformed output handled in both graders | done |
| 4 | Unverified usage excluded from totals | done — `usage_unavailable_runs` |
| 4 | Readiness checks + incremental saving | done — `run_primary.py`, `run_cases.py` |
| 4 | p03 cohort description | done — methods state a second cohort; identical description ≠ identity is the rubric item |
| 5 | Mixed-input case (2 genes, 2 pathways) | corpus + rubric entry (needs independent review) added; **coordinator single-pathway contract is the blocker** |
| 6 | Short scored evaluation | after 1 (paid calibration) and 3 |

Coverage: single gene (TYK2), bulk RNA (in vitro, mouse in vivo, patient) and Olink protein
(patient); human + mouse; 2D keratinocyte culture, mouse IMQ skin, paired patient skin biopsies.
Not covered: DNA, single-cell, clinical endpoints, other organs, open-web discovery, raw-sequencing analysis.
