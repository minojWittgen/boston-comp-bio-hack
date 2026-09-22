# benchmarking — cross-context evidence benchmark (v2, post-review 2026-09-22)

A small, fair comparison of *how an agent handles cross-context evidence*, built on the
[`data_pipeline`](../data_pipeline/README.md) evidence packages. It is **not** a SOTA claim
and does not evaluate computational analysis from raw data. What it can support after real
runs:

> "On three frozen cross-context evidence cases, configuration X achieved a/3 correct
> outcomes versus b/3 for the same Claude model with the same tools, instructions and
> budget; costs and failures are reported."

The pipeline layer retrieves facts and makes no judgments. This layer measures whether an
agent reasons over them correctly — and is built around one worry: an agent can produce a
confident, fluent, **correct-sounding** answer while skipping the checks that would have
changed it. So the cases are built so a careless and a careful agent reach *different*
answers, and grading is **structural** wherever it can be, not prose-matched.

## What changed after the review

| Review finding | Fix |
|---|---|
| §1 Claim was a pathway/state claim; case 3 misused GTEx abundance as contradiction | Claim is a **directional mRNA comparison** answered **per axis**. Case 3 recovers an **in-vivo observation with an opposing effect under a declared alignment basis**; GTEx is background only and never modified. Every case has in-vitro, **mouse in-vivo (species/tissue/endpoint/contrast)**, patient RNA and patient protein observations. Case 2 asks explicitly about **within-person** corroboration; disjoint participants → that axis `not_assessable`, other axes unaffected. Samples carry `participant_id` / `specimen_id` / `timepoint`; aggregates are computed from samples. |
| §2 B's ledger was self-reported | Ledger entries are **verified**: `met` needs evidence ids from the right context; `unmet` needs an **executed** follow-up; `not_applicable` needs a reason **and** passes an applicability check against the case. B is a scaffold experiment, labelled as such; the coordinator is configuration **C** via `bench/coordinator_adapter.py`. |
| §3 Grading & isolation defects | `read_file` enforces an explicit `input_allowlist` on resolved paths; harness files (`tool_stub.json`, `*.recovered.json`) are unreadable. Status interpretation is graded **structurally**. Citations are validated for **exact source + resolvable locator + support relation**. Human `confirm` values persist across regrades and mandatory ones gate `ALL_ROWS`. `execution_status` is separate; a timeout/no-answer gets **no** scientific credit. |
| §4 Budget | Limits are declared as **cumulative** vs **per-call**; the deadline bounds **every** model request; usage records input / cache-read / cache-creation / output tokens, LLM calls, data-tool calls and bookkeeping calls separately; the **harness** writes and HMAC-signs usage, the grader ignores the agent's copy; blind files are hashed. |
| §5 Fixture provenance | Every dataset and package carries `provenance` (`synthetic`, origin, modified fields, original path). Literature rows are labelled "judgment over supplied summaries" and reported separately. |

`bench/integrity_probes.py` reproduces the review's offline attacks (17 probes) and must
report all rejected before any model score is collected.

---

## What the agent is actually asked

One directional claim — *TYK2 mRNA is higher in IL-23-stimulated keratinocytes than in
controls* — and then **three separate questions** about whether that direction holds
elsewhere. Each is an **axis**, declared in `task.axes[]` with its own `question`, the
`datasets` it may draw on, and `requires_matched_participants`:

| Axis | Question |
|---|---|
| `in_vitro_vs_in_vivo` | Same direction in mouse imiquimod psoriasiform skin (IMQ vs vehicle)? |
| `in_vitro_vs_patient_rna` | Same direction in patient lesional vs non-lesional skin? |
| `patient_rna_vs_patient_protein_within_person` | **Within the same participants**, does the mRNA increase come with a protein increase? |

Answering per axis is the point: a single verdict lets an agent average away a real
disagreement. The agent returns an `overall` object **and** an `axes` array, and
`overall: persists` while any axis `diverges` is a structural failure.

### Verdicts

| Verdict | Meaning |
|---|---|
| `persists` | The direction holds on this axis. |
| `partially_persists` | Holds in part. |
| `diverges` | The counterpart contradicts the in-vitro direction. |
| `not_assessable` | The comparison cannot validly be made. |

`not_assessable` (v1 called it `not_comparable`) is the one that matters. It is correct when
the data *look* comparable but aren't — and it is exactly the answer a fluent agent avoids.
A non-`not_assessable` verdict **must** carry evidence ids and a stated
`contrast_alignment`; asserting agreement without declaring what makes the two contrasts
comparable is a graded failure.

### Source statuses, interpreted structurally

`status_interpretation` is now a **map** (`source_key → enum`), not prose:

| Value | Means |
|---|---|
| `database_fact_no_record` | The record does not exist. Do not retry. |
| `technical_failure_retryable` | Transient — retry it. |
| `disabled_by_mode` | Turned off by `mode`. |
| `upstream_failed` | A dependency failed. |
| `biological_negative` | **Never valid here.** Emitting it fails the row outright. |

This closes a v1 hole: writing "not_found is not a biological negative" in the prose no
longer earns credit if the structured map says otherwise (probe 7).

### Execution vs abstention

`execution_status` ∈ `completed · no_answer · timeout · budget_exceeded · error`. Anything
other than `completed` gets **no scientific credit on any row** — the axes are forced to
`not_assessable` and mean nothing. A run that times out cannot look like principled caution.

---

## Layout

```
benchmarking/
├── schema/            case_manifest · observation · agent_output · reference_answer
├── cases/             xctx-000 (dev) · xctx-001..003 (frozen) · lit/lit-01..09
├── fixtures/          generated: evidence_package.json + observation datasets + harness-only stubs
├── benchmark/literature_cases.json   9 documented genes (summary-judgment layer)
├── bench/
│   ├── spec.json            Step-1 decisions (the only file to edit)
│   ├── gen_fixtures.py      spec → manifests + fixtures (stub | live | frozen package)
│   ├── common.py            isolation, budgets, signed usage, tools
│   ├── agents.py            A0 / A / B scaffolds + mocks
│   ├── coordinator_adapter.py   configuration C contract (raises until implemented)
│   ├── run_cases.py         blind runner
│   ├── grade.py             grader → scorecard.json / summary.json (raw counts)
│   ├── pipeline_bench.py    layer 0: pipeline vs literature expectations
│   └── integrity_probes.py  must pass before scoring
├── held_out/          reference answers — GRADER ONLY, git-ignored
└── validate.py
```

Manifests are **generated artifacts**. Edit `bench/spec.json` and regenerate; do not hand-edit
`cases/` or `fixtures/`.

## The cases

All manifests share an identical shape — same keys, same tools, same checklist. Only fixture
contents differ, so the situation under test is not inferable from the manifest.

| Case | `situation` | What the fixtures do |
|---|---|---|
| `xctx-000` | `dev_example` | Dev/explore case, `limits_dev` (180 s). Never graded. |
| `xctx-001` | `genuine_scoped_agreement` | The evidence genuinely agrees. The control that catches an agent biased toward finding problems. |
| `xctx-002` | `invalid_within_person_pairing` | `patient_prot` uses participant ids `Q01..Q12` where `patient_rna` uses `P01..P12` — **disjoint people**. The within-person axis is `not_assessable`; the other two axes are unaffected and must still be answered. |
| `xctx-003` | `recoverable_required_observation_changes_axis` | `invivo_rna` ships `status: unavailable` with a retryable reason. An agent that calls `fetch_dataset` once receives a recovered observation with the **opposite** direction (`log2fc: -0.8`) under a declared alignment basis. An agent that does not retry never sees it. **GTEx is untouched.** |

`xctx-002` is the scoping test: the careless move is to let one bad axis collapse the whole
answer, or to "confirm" across modalities that describe different people. `xctx-003` is the
retry test — and note the payload lives in `invivo_rna.recovered.json`, which `read_file`
**refuses**, so it can only be reached through the declared retry path.

## Configurations

| | Model | Instructions + checklist | Tools | Enforcement |
|---|---|---|---|---|
| A0 | same | same (prose) | none | none |
| A  | same | same (prose) | read_file · fetch_dataset · build_evidence_package | none |
| B  | same | same (prose) | same + update_criteria | verified ledger gates submit |
| C  | same | same | same (via EvidenceProvider) | the actual coordinator |

All configurations get an **identical** system prompt, built by `system_prompt(manifest)` from
the manifest's own `task.checklist` and `tools.retry_policy`. B's only differences are the
extra tool and the submit gate — so the comparison isolates *enforcement*, not wording.

**B's verified ledger.** Seven criteria (`in_vitro_read`, `in_vivo_read`, `patient_rna_read`,
`patient_protein_read`, `reference_status_resolved`, `within_person_pairing`,
`species_alignment`) must each resolve before `submit_answer` is accepted — and each
resolution is **machine-checked**, not taken on trust:

- `met` → needs evidence ids that actually exist and come from the right context
  (`within_person_pairing` needs ids from **both** patient datasets).
- `unmet` → the criterion's follow-up tool must appear in the **executed** actions. Promises
  don't count.
- `not_applicable` → needs a reason *and* must pass an applicability check.
  `reference_status_resolved` can never be N/A.

**Configuration C** is the team's real coordinator, wired through
`bench/coordinator_adapter.py`. Its `run()` deliberately raises `NotImplementedError` until
the contract in that file's docstring is implemented, so no C score can be produced by
accident. The demo comparison is **A vs C** (or A vs B if C is not integrated in time — then
say so). A0 is secondary: it cannot recover an unavailable dataset, so it does not isolate
workflow quality.

## Isolation and tools

Three tools, all served offline from a per-case `tool_stub.json`:

- **`read_file`** — checks the **resolved** path against the manifest's explicit
  `input_allowlist`. Anything else, plus any file ending `tool_stub.json`, `.recovered.json`
  or `.original.json`, returns `status: "rejected"`. `..` traversal and symlinks cannot escape.
- **`fetch_dataset(dataset_id)`** — the *declared* retry path for a dataset whose status is
  `unavailable`. This is how xctx-003's recovery is reached.
- **`build_evidence_package`** — available in every case, so calling it where it is
  unnecessary is not itself a tell, and every configuration sees identical tool behaviour.

Budgets are split into cumulative and per-call (`limits_final`: 6 data-tool calls, 10
bookkeeping calls, 5 000 cumulative output tokens, 2 000 per call, **90 s**). The deadline is
checked before *every* model request, and `BudgetExceeded` carries a `kind`
(`timeout` / `budget_exceeded`) that maps straight to `execution_status`.

## Integrity

Blinding in v1 was procedural. In v2 it is enforced:

- The agent's self-reported `usage` is **stripped** from the blind file. The harness writes its
  own measurement to `runs/<batch>/usage/<id>.json`, HMAC-signed with a per-batch secret held
  in `key.json`. The grader uses only the signed copy.
- Each blind file is hashed (`blind_sha256` in `key.json`), so editing an answer after the run
  is detected.
- Either failure sets the `integrity` row to fail.

```bash
python bench/integrity_probes.py
```

17 probes in 10 groups, each reproducing an attack the harness must reject: blanket
`not_applicable` ledgers, unexecuted follow-ups, inconsistent roll-ups, four `read_file`
escapes (including `../../held_out/reference_answers.json`), usage tampering, post-run answer
edits, regrade-resets of human confirmations, prose-vs-structural status, fabricated citation
locators, both budget limits, and timeout credit. Two are positive controls that must *pass*.
Exits non-zero unless it ends `Safe to collect model scores.`

> Probes 5, 5b and 6 shell out to `grade.py`, so **`held_out/` must be in place** or they
> abort partway. See below.

## Running

```bash
pip install -r bench/requirements.txt            # anthropic>=0.40, jsonschema, requests
export XCTX_PIPELINE=/path/to/data_pipeline/evidence_pipeline
export ANTHROPIC_API_KEY=...   XCTX_MODEL=claude-sonnet-4-5

python bench/gen_fixtures.py --stub            # or --live --cache .xctx-cache / --from-package <frozen>
python validate.py
python bench/pipeline_bench.py --from-dir fixtures
python bench/integrity_probes.py               # must end "Safe to collect model scores."

python bench/run_cases.py --config mock mock-careless --batch smoke && python bench/grade.py runs/smoke
python bench/run_cases.py --config B --suite all --cases xctx-000 --batch dev      # feasibility under the 90 s deadline

# the demo: 2 configurations × 3 cases × 1 run, hard 90 s deadline per run
python bench/run_cases.py --config A B --reps 1 --batch final
python bench/grade.py runs/final --no-unblind      # set `confirm` on mandatory must_detect items in scorecard.json
python bench/grade.py runs/final                   # unblind → summary.json
```

The smoke test is the quickest check that the harness discriminates: careful `mock` should
answer `persists / partially_persists / partially_persists` and `mock-careless` `persists`
three times.

## Grading

`grade.py` builds `scorecard.json` from the blind files alone; it opens `key.json` only on the
second run, without `--no-unblind`.

| Row | Passes when |
|---|---|
| `integrity` | Blind hash matches **and** the usage signature verifies. |
| `execution` | `execution_status == completed`, no limit overrun, no live network, schema-valid. |
| `axis:<axis_id>` | Verdict accepted and not forbidden; if not `not_assessable`, required evidence ids present (exact, no substitutes) and `contrast_alignment` non-empty. |
| `overall` | In `accepted_overall` **and** consistent with the axes. |
| `unsupported_corroboration` | No claim rests on evidence that doesn't support it. |
| `citation_validity` | Every citation has a known source, a **resolvable** locator, and a consistent support relation. Reference keys cited as `claim`/`against_claim` fail — they are background. |
| `status_interpretation` | Structural match against expected; any `biological_negative` fails. |
| `required_actions` | Declared tool calls occurred within their min/max. |
| `ALL_ROWS` | Every row above passed **and** every mandatory `must_detect` item is human-confirmed. |

`must_detect` items are **not** auto-graded. Keyword matching is a hint (`auto`); a human sets
`confirm` in `scorecard.json` between the two `grade.py` runs. Confirmations carry over across
regrades, and both `false` and *unset* block `ALL_ROWS`.

`summary.json` reports raw counts (`passes/runs`) per configuration and case, plus per-config
totals: LLM calls, every token category, data-tool and bookkeeping calls, wall clock,
`tokens_per_passed_run`, and estimated cost. Timeouts are failures. Repeats measure run
variability, not more biological tasks.

## The held-out key

`held_out/` holds `reference_answers.json` and `scorecard_template.json`. It is **git-ignored
and must never be committed** — publishing it would invalidate every blinded run.

> **Placement matters.** `common.py` sets `HELD_OUT = ROOT / "held_out"`, i.e.
> `benchmarking/held_out/`. The files must sit **inside this directory, untracked** — not in a
> parent. There is no environment variable to point elsewhere, so anywhere else and both
> `grade.py` and `integrity_probes.py` fail with `FileNotFoundError`. Generating, validating
> and running all work without it; only grading and the probes need it.
>
> The v2 schema is **not** backward compatible: a reference answer now requires
> `expected_axes`, `accepted_overall`, `required_actions`, `forbidden`,
> `status_interpretation_expected`, and the new `situation` names. A v1 key will fail
> validation. `gen_fixtures.py` deliberately leaves `held_out/` untouched, so the key is
> hand-maintained.

`validate.py` prints `note: held_out/ absent here (correct for an agent-visible checkout)`
when it is missing — the expected state for a clone.

## The literature layer

`benchmark/literature_cases.json` holds 9 genes whose cross-context behaviour is documented,
run as a single `literature_axis`. These are **judgment over supplied summaries**, not
reproduction from raw data, and are reported separately for that reason.

| Bucket | Rows |
|---|---|
| `diverges` | lit-01 FOS (dissociation IEG artifact), lit-02 HSPA1A, lit-09 NOS2 |
| `partially_persists` | lit-03 MYH7, lit-04 TNNI3, lit-05 DCX |
| `persists` | lit-06 PTPRC, lit-07 EPCAM |
| `not_comparable` → graded as `not_assessable` | lit-08 CXCL8 (no mouse ortholog) |

The bucket imbalance is deliberate: a system that always answers `persists` should score
visibly badly rather than hide behind an aggregate.

## Coverage statement (say this on the slide)

Three synthetic cases; modalities: bulk RNA (in vitro, mouse in vivo, patient), Olink protein
(patient); contexts: 2D keratinocyte culture, mouse IMQ skin, paired patient skin biopsies;
species: human, mouse. Not covered: DNA, single-cell, clinical endpoints, other organs,
rat/NHP data.
