# benchmarking — cross-context evidence evaluation (v3, handoff 2026-09-22)

Two suites, reported separately and never pooled.

| Suite | Question it answers | Input boundary | Systems | Deliverable |
|---|---|---|---|---|
| **PRIMARY** (`primary/`) | Does the integrated system produce more scientifically justified answers to the same research request than a competent general-purpose agent? | Same task + same frozen **source corpus** (methods excerpts, DE tables, specimen metadata, native API responses). Each system does its **own** extraction, structuring, comparison, interpretation. | `baseline` (general agent, same model) vs `integrated` (actual collector → normalization → coordinator) | Short report: conclusion per comparison + citations to source locations + limitations + unresolved |
| **SECONDARY** (`cases/`, `fixtures/`) | Given the same normalized observations, how does coordinator-level interpretation and checking compare to a baseline? | Shared, pre-normalized observation records + stubbed retrieval | `A0` / `A` / `B` (checklist scaffold, *not* the product) / `C` (coordinator adapter) | Per-axis verdicts |

The primary result is the headline. The secondary result diagnoses where a difference comes
from; **its score is never presented as the score of the full product.** Methodological
reference: AutoSciRub's paired comparison with a hidden external rubric and separate component
experiments — adopted as principles, not reproduced.

## Readiness condition (read before running the primary suite)

The reviewed coordinator accepts normalized observations and does not extract them from source
material. `bench/integrated_adapter.py` raises until the integrated extraction path exists.
**If it is not ready, run the secondary suite and report its narrower scope. Do not fill the gap
with hand-authored observations for our side.**

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
locations, unsupported corroboration, task completion) plus **blind human review** on four
dimensions — scoped conclusion correctness, evidence correctness, comparability & uncertainty,
task completion. Reviewer decisions and blinding clues are preserved. No credit for JSON, for
declaring criteria met, for tool use, or for abstaining when the evidence is assessable.

```bash
pip install -r bench/requirements.txt
export ANTHROPIC_API_KEY=...  XCTX_MODEL=claude-sonnet-4-5
export XCTX_PIPELINE=/path/to/data_pipeline/evidence_pipeline     # secondary suite only

python bench/gen_primary.py                 # corpus for p00..p03 (synthetic, labelled)
python validate.py
python bench/integrity_probes.py            # 24 probes; must end "Safe to collect model scores."

python bench/run_primary.py --system mock mock-careless --batch primary-smoke     # harness check, no LLM
python bench/grade_primary.py runs/primary-smoke --no-unblind

python bench/run_primary.py --system baseline --cases xctx-p00 --batch primary-dev   # feasibility under the 90 s deadline
# if the dev case cannot finish meaningfully, reduce task scope for BOTH systems before freezing; never after seeing scores

python bench/run_primary.py --system baseline integrated --batch primary-final       # the pilot: 2 × 3 × 1
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

## Handoff acceptance checklist

- [x] Primary and secondary suites are named and reported separately.
- [ ] The primary runner invokes the actual integrated system (`bench/integrated_adapter.py` — integration owner).
- [x] Both primary systems receive the same task and source access; neither receives a privately prepared evidence advantage.
- [ ] The external rubric is independently reviewed and frozen (`held_out/primary_rubric.json` → `_review_status`).
- [x] GTEx contradiction error and grader/isolation/budget defects corrected and regression-checked (`bench/integrity_probes.py`).
- [x] Inputs preserve species, modality, experimental context and participant/specimen/visit distinctions; synthetic changes are labelled.
- [x] Execution failures, scientific uncertainty and unsupported claims are scored distinctly.
- [ ] Results disclose case count, model and code versions, actual usage, and whether extraction was automated or supplied (fill in at report time).

Coverage: single gene (TYK2), bulk RNA (in vitro, mouse in vivo, patient) and Olink protein
(patient); human + mouse; 2D keratinocyte culture, mouse IMQ skin, paired patient skin biopsies.
Not covered: DNA, single-cell, clinical endpoints, other organs, open-web discovery, raw-sequencing analysis.
