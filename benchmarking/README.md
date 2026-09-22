# benchmarking — the evaluation layer (xctx-eval)

A blinded A/B benchmark that measures whether an agent **reasons correctly** over the
evidence packages built by [`data_pipeline/`](../data_pipeline/README.md).

The pipeline layer retrieves facts and makes no judgments. This layer asks the question the
pipeline deliberately refuses to answer:

> Does an in-vitro finding about a gene still hold in vivo and in individual patients?

The benchmark is built around a specific worry: an agent can produce a confident, fluent,
**correct-sounding** answer while skipping the checks that would have changed it. So the
cases are constructed so that a careless agent and a careful agent reach *different*
verdicts, and the grader checks the reasoning — not just the verdict.

---

## The answer space

Four verdicts, defined in [`bench/common.py`](bench/common.py):

| Verdict | Meaning |
|---|---|
| `persists` | The in-vitro finding holds in the other contexts. |
| `partially_persists` | Holds on some axes, not others. |
| `diverges` | The other contexts contradict the in-vitro finding. |
| `not_comparable` | The comparison cannot validly be made at all. |

`not_comparable` is the one that matters most. It is the correct answer when the data
*look* comparable but aren't — and it is exactly the answer a fluent agent avoids.

Four source statuses, whose semantics the benchmark hinges on:

| Status | Means | Correct response |
|---|---|---|
| `ok` | Retrieved. | Use it. |
| `not_found` | **A database fact** — the record does not exist. | Do not retry. **Not** a biological negative. |
| `error` | A technical failure. | Retry it. |
| `skipped` | Disabled by `mode`. | Note as a caveat. |

Conflating `not_found` with "the gene is not expressed" is a graded failure.

---

## Layout

```
benchmarking/
├── schema/                        the contracts
│   ├── case_manifest.schema.json    what the agent receives   (identical shape for all cases)
│   ├── agent_output.schema.json     what the agent must return (identical for all configs)
│   └── reference_answer.schema.json what only the grader holds
├── cases/
│   ├── xctx-000.json              DEV EXAMPLE — mode: explore, never graded
│   ├── xctx-001.json  ─┐
│   ├── xctx-002.json   ├─ the three graded cases, mode: eval
│   ├── xctx-003.json  ─┘
│   └── lit/lit-01..09.json        literature layer, one per documented finding
├── fixtures/                      generated inputs (evidence packages + context datasets)
│   └── _template/                 skeletons used by the generator
├── bench/
│   ├── spec.json                  the single source of truth — gene, claim, limits
│   ├── gen_fixtures.py            generates every manifest and fixture from spec.json
│   ├── common.py                  ToolBox sandbox, Usage accounting, limits enforcement
│   ├── agents.py                  the configurations (A0, A, B, mock, mock-careless)
│   ├── run_cases.py               runs configs × cases × replicates, writes BLIND outputs
│   ├── grade.py                   grades blind, then unblinds
│   └── pipeline_bench.py          layer 0 — tests the pipeline, not the agent
├── benchmark/literature_cases.json  9 documented findings with known answers
├── harness/usage_capture.md       token-accounting contract (required for Configuration C)
├── validate.py                    schema + invariant checks
└── held_out/                      ← NOT IN GIT. See "The held-out key" below.
```

---

## Why the manifests are all the same shape

Every manifest — all four `xctx-*` and all nine `lit-*` — has byte-identical structure:
same keys, same tool list, same instruction, same `limits`. **Only the fixture contents
differ.** An agent cannot infer which trap it is facing from the manifest.

Three further anti-leak properties:

- **`mode: eval` on every graded case.** The pipeline skips `pubmed` and `opentargets`, so
  no answer can arrive through live literature. A benchmark whose answer is one PubMed
  query away measures retrieval, not reasoning.
- **`build_evidence_package` is available in every case** and served from a per-case
  `tool_stub.json` with no network. Calling it where it is unnecessary is therefore not
  itself a tell, and A/B/C observe identical tool behaviour.
- **The `read_file` sandbox** rejects any path outside that case's fixture directory, so no
  agent can read another case — or the held-out key.

---

## The three graded cases

Each is a specific, named failure mode. The "trap" column is what the fixtures do to you.

| Case | Situation | The trap | Accepted verdicts |
|---|---|---|---|
| `xctx-001` | `valid_corroboration` | None — the evidence genuinely lines up. This is the control that catches an agent biased toward finding problems. | `persists` |
| `xctx-002` | `invalid_patient_pairing` | Identical to 001 **except** `patient_prot` uses sample ids `Q01..Q12` while `patient_rna` uses `P01..P12`. The two patient datasets describe **disjoint people**, so cross-modality "confirmation" is an illusion. | `not_comparable`, `partially_persists` |
| `xctx-003` | `recoverable_missing_then_disagreement` | GTEx comes back `error` (not `not_found`). An agent that retries gets a **recovered** package whose GTEx *contradicts* the claim (Skin 0.1 TPM, Testis 21.0). An agent that does not retry never sees the disagreement. | `diverges`, `partially_persists` |

`xctx-002` is graded on reasoning, not just outcome: the conclusion row additionally
requires the rationale to actually reference the pairing problem. **The right verdict for
the wrong reason fails.** `xctx-003` is graded on five rows, with `retrieval` and
`reporting_after_recovery` kept separate so "never retried" and "retried but buried the
contradiction" stay distinguishable.

`xctx-000` is the dev example (`mode: explore`). It exists to freeze limits and to smoke-test
the harness, and is excluded from the `final` suite.

---

## The configurations

Defined in [`bench/agents.py`](bench/agents.py). All share one model (`XCTX_MODEL`, default
`claude-sonnet-4-5`), one tool sandbox, and one set of limits.

| Config | Tools | What it isolates |
|---|---|---|
| **A0** | none (`submit_answer` only); package pasted into the prompt | The floor. Plain Claude, one shot, no agency. |
| **A** | `read_file`, `build_evidence_package`, `submit_answer` | A conventional tool-using agent. |
| **B** | A + `update_criteria` | A **+ an explicit criteria ledger**. This is the variable under test. |
| **C** | external | A different stack entirely (e.g. Biomni), via your own adapter. |
| `mock` / `mock-careless` | — | Deterministic, no LLM. Harness smoke test. |

**What B actually adds.** B carries seven generic criteria *in the agent, never in a
manifest* (so they leak nothing case-specific):

```
in_vitro_effect_located     patient_effect_located     mandatory_sources_ok
status_semantics_applied    tissue_match_checked       sample_identity_checked
cross_species_checked
```

B's `submit_answer` is **rejected** unless every mandatory criterion is resolved — `met`,
`not_applicable`, or `unmet` *with a stated follow-up action*. The rejection returns
`{"accepted": false, "reason": "criteria not resolved: [...]"}` and the loop continues.

That is the whole hypothesis: `sample_identity_checked` is what catches `xctx-002`, and
`mandatory_sources_ok` is what forces the retry in `xctx-003`. B costs more tokens than A —
**that cost is the thing being measured**, and `b_over_a_token_ratio` is reported as-is.

> **Mock label inversion (deliberate, and easy to misread):** `Mock.config = "A" if careless
> else "B"`, so `mock-careless` reports itself as **A** and careful `mock` reports as **B**.
> The careful mock retries on `error`, checks patient-id overlap, and flags low tissue TPM;
> the careless mock does none of these and cites `cohort_summary` as a comparability check.
> Expect careful to pass and careless to fail 002/003 — that is the harness working.

---

## Running it

```bash
pip install -r bench/requirements.txt          # anthropic>=0.40, jsonschema
export XCTX_PIPELINE=/path/to/boston-comp-bio-hack/data_pipeline/evidence_pipeline
export ANTHROPIC_API_KEY=...                   # A0/A/B only; mocks need neither SDK nor key
export XCTX_MODEL=claude-sonnet-4-5            # must be the same for A and B
```

`XCTX_PIPELINE` must point at the directory containing `package.py`. If unset, `common.py`
tries `../data_pipeline/evidence_pipeline`, `../evidence_pipeline`, and
`./data_pipeline/evidence_pipeline` before raising `FileNotFoundError`.

### 0. Generate everything from the spec

Edit `bench/spec.json` (gene, claim, disease), then pick exactly one source flag:

```bash
python bench/gen_fixtures.py --stub                       # no network, real package shape
python bench/gen_fixtures.py --live --cache .xctx-cache   # real pipeline, real APIs
python bench/gen_fixtures.py --from-package path/to.json  # reuse a package you already have
python validate.py
```

Optional: `--limits <json>` (defaults to `spec.json: limits_dev`), `--no-lit` to skip the
literature fixtures. This writes every `cases/*.json` and `fixtures/*/*` — **the manifests
are generated artifacts; edit `spec.json`, not them.**

### 1. Layer 0 — test the pipeline, not the agent

```bash
python bench/pipeline_bench.py --live --cache .xctx-cache
```

Checks the 9 literature rows' `pipeline_checks` (orthology status, IMPC, GTEx tissue
expectations) plus the leak invariant that `pubmed` and `opentargets` are `skipped` in eval
mode. Exits non-zero if any row fails. Run this first — if the substrate is wrong, agent
scores are meaningless.

### 2. Harness smoke test (no LLM, no key)

```bash
python bench/run_cases.py --config mock mock-careless --reps 1 --batch smoke
python bench/grade.py runs/smoke
```

### 3. Freeze the limits on the dev example

```bash
python bench/run_cases.py --config B --cases xctx-000 --suite all --batch dev
```

Limits are frozen on **B** (the more expensive configuration) and A gets the same budget, so
A is never starved. They are currently frozen at `max_tool_calls: 12`,
`max_output_tokens: 4000`, `wall_clock_seconds: 600` across all four xctx cases.

### 4. The timed evaluation

```bash
python bench/run_cases.py --config A0 A B --reps 3 --batch final
python bench/grade.py runs/final --no-unblind   # then fill 'confirm' fields in scorecard.json
python bench/grade.py runs/final                # unblind → summary.json
```

### 5. Literature layer

```bash
python bench/run_cases.py --config A B --suite lit --batch lit
python bench/grade.py runs/lit
```

**Suite note:** `--suite final` globs `cases/*.json` minus `xctx-000`; `--suite all` is the
same glob *including* `xctx-000`; `--suite lit` uses `cases/lit/*.json`. `all` and `final`
differ only by the dev example.

---

## How grading works

### Blind by construction

`run_cases.py` writes two things per run:

- `runs/<batch>/raw/<config>_<case>_<run>.json` — the full trace, including `usage` and B's
  `_ledger`.
- `runs/<batch>/blind/<8-hex>.json` — the same output with `configuration` and `_ledger`
  **stripped** and `configuration` forced to `"BLIND"`.

The `blind_id → {case_id, configuration, run}` mapping goes to `runs/<batch>/key.json`.
`grade.py` builds `scorecard.json` from the blind files alone and does not open `key.json`
until you re-run it without `--no-unblind`.

> This is **procedural** blinding, not enforced. Nothing stops a grader from opening
> `key.json` early, and `usage.model` (`"mock"` vs a Claude id) leaks configuration identity
> into the blind files. It is a discipline, not a guarantee — treat it accordingly.

### The graded rows

| Row | Passes when |
|---|---|
| `conclusion` | Verdict is in `accepted_verdicts`. For `xctx-002`, the rationale must *also* reference the pairing problem. |
| `evidence` | Every `must_cite` source is cited **and** no violation fired (see below). |
| `completion` | Output validates against `agent_output.schema.json`, and `tool_calls`, `wall_clock_s`, and `network_calls` are all within limits. |
| `retrieval` | *(xctx-003 only)* A `build_evidence_package` call with `mode="eval"` returned `ok`, **and** GTEx is cited. |
| `reporting_after_recovery` | *(xctx-003 only)* The text mentions GTEx *together with* a disagreement term. |

Violations that fail the `evidence` row: more than 2 `build_evidence_package` calls;
`persists` on the pairing case; citing `cohort_summary` as a `comparability_check`;
`persists` while a mandatory source errored or contradicted; and treating `not_found` as a
biological negative.

`must_detect` items are **not** auto-graded. They are keyword-matched into a
`must_detect_review` list with `confirm: null`, and a human fills those fields in
`scorecard.json` between the two `grade.py` runs. Auto-matching is a hint, not a verdict.

### `summary.json`

Three keys:

- **`correctness`** — `config → case_id → row → "P/N"` across replicates.
- **`efficiency`** — per config: `runs`, `all_rows_pass`, mean/median tokens,
  `tokens_per_pass`, `tool_calls_mean`, `wall_clock_s_mean`; plus `b_over_a_token_ratio`.
- **`literature_by_bucket`** — `config → bucket → "P/N"` on the `conclusion` row.

Efficiency is reported as **tokens per _passed_ case**, where `all_rows_pass` counts runs in
which *every* row passed. A configuration that is cheap because it answers quickly and wrongly
scores badly here by design — that is the point of the denominator.

---

## The literature layer

`benchmark/literature_cases.json` holds 9 findings with verdicts documented in the
published literature, each with sources, and `pipeline_checks` consumed by both
`pipeline_bench.py` and `gen_fixtures.py`.

| Bucket | Rows |
|---|---|
| `diverges` | lit-01 FOS (dissociation IEG artifact), lit-02 HSPA1A, lit-09 NOS2 (mouse vs human) |
| `partially_persists` | lit-03 MYH7, lit-04 TNNI3, lit-05 DCX |
| `persists` | lit-06 PTPRC, lit-07 EPCAM |
| `not_comparable` | lit-08 CXCL8 (no mouse ortholog) |

The bucket imbalance is deliberate. Results are reported **per bucket** precisely so that a
system which always answers `persists` scores visibly badly instead of hiding behind an
aggregate. lit-08 is graded with an extra `status_semantics` row: `not_comparable` alone is
not enough, it must also cite `ensembl_orthology`.

---

## The held-out key

`held_out/` contains `reference_answers.json` (accepted verdicts, `must_cite`/`must_detect`/
`must_not`, fixture recipes) and `scorecard_template.json`. **It is not in this repository
and must never be committed** — it is listed in `.gitignore`, and publishing it to a public
repo would invalidate every blinded run.

> **Placement matters.** `common.py` sets `HELD_OUT = ROOT / "held_out"`, i.e.
> `benchmarking/held_out/`. The files must sit **inside this directory, untracked** — not in
> a parent directory. There is no environment variable to point elsewhere, so if they live
> anywhere else `grade.py` fails with `FileNotFoundError` on
> `held_out/reference_answers.json`. Generating, running, and `validate.py` all work without
> it; only grading needs it.

`validate.py` prints `note: held_out/ not present here (good...)` when it is absent, which is
the expected state for a clone.

---

## Configuration C (external comparator)

C is intentionally **not** in `agents.py`. Drive it with your own adapter that writes the
`runs/<batch>/blind` + `key.json` layout using `agent_output.schema.json`; `grade.py` then
treats it like any other configuration. See [`harness/usage_capture.md`](harness/usage_capture.md)
for the token-accounting contract — tokens must come from the provider's usage object or a
logging proxy, **never** estimated from a printed transcript.

Report C honestly: if `network_calls > 0` it saw live literature that eval mode hides from A
and B, so its correctness rows must be labelled *"not comparable, saw live literature."* If
the model differs, it is a different-stack comparison, not an apples-to-apples one.

---

## Validating

```bash
python validate.py
```

Checks manifests against `case_manifest.schema.json` and, if present, held-out entries
against `reference_answer.schema.json`. Beyond the schemas it enforces: `_note` only on
`xctx-000`, `mode == "eval"` on every non-dev case, and warns on unfrozen `<<...>>`
placeholder limits. Exits non-zero on failure.
