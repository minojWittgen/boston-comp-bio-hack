# Capturing `usage` fairly across A0, A, B and C

Updated for v2 (post-review 2026-09-22). The principle is unchanged — **sum the provider's
`usage` object, never estimate from text** — but who does the summing changed.

## The harness measures, the agent does not

In v1 the agent's output carried its own `usage` block and the grader trusted it. It no
longer does:

- `run_cases.py` **strips** `usage` from the blind file entirely. A fabricated count is not
  caught and penalised — it is simply never read.
- The harness writes its own measurement to `runs/<batch>/usage/<blind_id>.json` as
  `{"usage": u, "sig": sign(secret, u)}`, HMAC-SHA256 over the canonical JSON with a
  per-batch secret stored in `key.json` under `_secret`.
- The grader recomputes that signature. A mismatch, or a missing `harness_signed: true`,
  fails the `integrity` row. The blind answer file is separately protected by
  `blind_sha256`.

So there is nothing to implement for A0/A/B — `bench/common.py:Usage` already does it. What
matters is not breaking it: any new LLM call must go through `usage.add_llm(resp)`, and any
tool call through `tb._record(...)` so it lands in the right bucket.

## What `Usage` records

`Usage(model, limits)` tracks, and `dump(signed=True)` emits:

| Field | Note |
|---|---|
| `llm_calls` | Model requests. |
| `input_tokens` | **Includes** `cache_read_input_tokens`. |
| `cache_read_tokens` | Broken out separately. |
| `cache_creation_tokens` | New in v2 — cache writes are billed too. |
| `output_tokens` | Cumulative; bounded by `max_output_tokens_total`. |
| `data_tool_calls` | `read_file` · `fetch_dataset` · `build_evidence_package`. |
| `bookkeeping_calls` | `update_criteria` — B's ledger traffic, counted separately so it cannot hide inside the data budget. |
| `wall_clock_s` | `time.monotonic()`, not wall time. |
| `network_calls` | Must be 0 for A0/A/B. Any non-zero fails `execution`. |
| `estimated_cost_usd` | From `PRICE_PER_MTOK`. |
| `harness_signed` | Must be `true`. |

Splitting data from bookkeeping calls is the fairness fix: B makes more calls *by design*,
and burying them in one counter would either flatter B or penalise it arbitrarily.

## Budgets are enforced, not just reported

`Usage` raises `BudgetExceeded` with a `kind` that maps straight onto `execution_status`:

- `check_deadline()` before **every** model request → `kind="timeout"`
- `next_call_max_tokens()` bounds the per-call max by what remains of the cumulative budget
- `add_llm()` on cumulative output overflow → `kind="budget_exceeded"`
- `add_tool()` on either `max_data_tool_calls` or `max_bookkeeping_calls`

A run that trips any of these is a **failure**, not an abstention: it gets no credit on any
scientific row. Do not "rescue" such a run by rerunning it silently — report it.

**Do not trim B's prompt to make its numbers look better.** B's extra prompt and extra calls
are the cost being measured. Report them as they fall.

## Configuration C (the team's coordinator)

C is no longer a generic external comparator; it is the team's own coordinator, wired through
[`../bench/coordinator_adapter.py`](../bench/coordinator_adapter.py), whose `run()` raises
until the contract in its docstring is implemented. For usage specifically:

- Inject the manifest's `limits` into the planner — cumulative output tokens, per-call max,
  and the deadline. `ClaudePlanner` currently hard-codes a 6 000-token per-call max and
  **discards usage**; that must be captured into `Usage` instead.
- If `ExplicitPlanner` is used, report it as a deterministic workflow with **zero** planner
  LLM calls rather than leaving the field blank.
- Record the coordinator commit hash (`XCTX_COORDINATOR_COMMIT`) in the trace under
  `_coordinator`, which `run_cases.py` strips from blind outputs.

Token capture, in order of preference:

1. C exposes a usage callback or log → sum it exactly as above.
2. C lets you inject the LLM client → wrap it with the accumulator.
3. Neither → put a logging proxy in front of `base_url` and sum `usage` from the proxied
   responses.

Never count tokens in a printed transcript. That misses system prompts and tool results,
which are usually most of the bill.

Also record, for C only:

- **`network_calls`** — if C reaches PubMed / Open Targets / UniProt live, it has seen
  evidence the benchmark deliberately withholds from A0/A/B. Its correctness rows must then
  be labelled *"not comparable, saw live literature."*
- **`model`** — if it differs from A/B, every C number is a different-stack number. Say so
  once, up front, and do not argue from them.
- Whether C could read `held_out/`. It must not; probe 3b covers the `read_file` path.

## What to put in the write-up

Take the numbers from `summary.json` — don't recompute them. Per configuration and case it
reports raw counts (`passes/runs`) for `integrity`, `execution`, each `axis:<id>`, `overall`,
`unsupported_corroboration`, `citation_validity`, `status_interpretation`,
`required_actions`, and `ALL_ROWS`; plus per-config totals for LLM calls, every token
category, data-tool and bookkeeping calls, wall clock, `tokens_median_per_run`,
`tokens_per_passed_run`, and `estimated_cost_usd_total`.

Report raw counts, not percentages — three cases and one replicate do not support a rate.
Timeouts are failures. Repeats measure run variability, not more biological tasks.

The claim you can support is *"on three frozen cases, X got a/3 and Y got b/3 under the same
model, tools, instructions and budget, at these costs."* The claim you cannot support is that
either is better in general, or that a different-stack comparison is like-for-like.

> Note: v1's `b_over_a_token_ratio` no longer exists in `summary.json`. If you want it,
> compute it from `output_tokens_total` and say which runs it covers.
