# Investigation-first coordinator — integration handoff

## Why this changes

The previous engine always adapted collected database results to `background`, then
required `observation` records for successful completion. Ordinary chat supplies no
observations. Useful retrieved results therefore ended in an insufficient-evidence
verdict even when source collection worked. This was the wrong product contract.

The coordinator's job is to investigate: state what sources report, relate findings
across requested species, modalities and situations, preserve provenance, explain
differences and uncertainty, and identify useful next steps. Biological uncertainty
is an expected research result, not an automatic failed investigation.

## Architecture and compatibility

1. Plan intent before collection; preserve requested entities and biological axes.
2. Collect the existing data-pipeline packages without changing their format.
3. Produce source-grounded findings from returned values and metadata.
4. Map findings to research scope; distinguish directly covered scope from related
   material and unavailable information. Include source and collection limits.
5. Compare contexts descriptively. Do not silently treat RNA, protein location,
   CRISPR fitness, orthology and patient outcomes as interchangeable measurements.
6. Retry recoverable collection failures at most once, within the existing budget.
7. Return the investigation report even when the biological question is unresolved.

The intent-before-evidence separation was informed by
[AutoSciRub, pinned source](https://github.com/zjunlp/AutoSciRub/tree/333a9e5b7e405f54aca2e74d9c4f58aeece96332).
This implementation is original code; it does not reproduce that project's controller
or benchmark scores. Research completion is our product contract, not a claim copied
from that benchmark.

### API consumers

`Submission` and pipeline packages are unchanged. `RunState` schema 0.2 adds:

| Field | Use |
| --- | --- |
| `investigation.findings` | Source-specific summaries linked by `evidence_id` to preserved records and raw payloads. |
| `investigation.coverage` | Per-question `addressed`, `limited` or `unavailable`, with reasons and related record IDs. |
| `investigation.comparisons` | Descriptive cross-context summaries, left/right record IDs and interpretation limits. |
| `investigation.limitations` / `next_steps` | Uncertainty, collection limits and follow-up research needs. |
| `investigation.checks` / `criteria_met` | Whether the bounded research work was completed; not whether a hypothesis is true. |
| `investigation.completion_reason` | Human-readable explanation of completion or incomplete work. |

`status` uses investigation completion. `assessment` retains the previous optional
supplied-observation diagnostics with unchanged semantics; it no longer gates status
or retries. Do not use `assessment.criteria_met` as the score or success flag for the
whole investigation. Saved 0.1 states still deserialize and display their old meaning;
rerun a question to obtain the new report. No stored old result is silently rescored.

The data-pipeline team needs no output migration for this fix. Existing source values,
species, contexts, collection statuses and raw packages remain intact. `background`
is not renamed to `observation`. Existing per-member pathway status aggregation and
multi-pathway execution limitations are not repaired by this coordinator change.

## Benchmark handoff — a short research-quality evaluation

Keep the same questions, underlying source material/tool access, model and budget for
our system and a competent simple-agent baseline. Let each system structure evidence
independently. Our intermediate JSON is not a required format for baseline reasoning.
Score the final report plus its source trace; an export adapter can expose both as text
and source references without changing either system's internal reasoning.

For a ten-to-twenty-minute smoke evaluation, use a small fixed set of cases:

- Existing numeric database results with no normalized observations: the report must
  explain useful returned values, with correct units and source scope.
- Human cells, animal phenotype and human cohort results: preserve species, assay and
  situation differences; do not infer individual-patient agreement.
- Mixed or conflicting supplied findings: retain disagreement rather than force a verdict.
- No results versus a source timeout: distinguish a completed no-hit query from an
  incomplete search; neither proves biological absence.

Blind-score each case on five dimensions, 0 (absent/wrong), 1 (partial), 2 (adequate):

1. Relevant findings: uses available evidence to address the question.
2. Faithfulness: values, units and claims match the cited source material.
3. Traceability: material claims can be traced to actual returned records or sources.
4. Context: preserves species, modality, in-vitro/in-vivo/patient and cohort/individual distinctions.
5. Uncertainty: explains disagreement, missing information and realistic next steps.

Keep critical errors visible separately: invented citation/value, cohort-to-individual
claim, orthology-to-conservation claim, and technical failure presented as biological
absence. Record runtime and tool usage as descriptive measures. Do not give automatic
credit for our own `criteria_met` flag, a longer report, or a conclusive answer.

This small evaluation can demonstrate useful behavior and a baseline difference on
these cases. It cannot establish SOTA performance or broad scientific accuracy.
The benchmark owner should update result extraction and rubrics; this coordinator
branch does not silently rewrite the independently developed benchmark branch.

## Scope of this urgent fix

Source-specific synthesis is deterministic and offline-testable. No extra model call
or paid API is added. This is not yet autonomous full-text literature review, numerical
cross-study harmonization, new wet-lab validation or raw-data reanalysis. The iteration
still retries technical failures with existing tools; additional scientific searches
require further retrieval tools. Findings and those limits are reported together.

## Verification

- Integrated offline suite: **231 passed, 40 subtests passed**; one dependency
  deprecation warning. Coordinator, frontend/API/MCP and unchanged pipeline tests ran together.
- Real code path exercised with clearly synthetic pipeline-shaped responses:
  package → adapter → coordinator → API → Streamlit report. A returned **5.2 TPM**
  value appears in the report without supplying any observation record.
- Covered no-hit searches, source timeouts/recovery, malformed responses, top-N limits,
  budget exhaustion, multiple genes, context mismatch, raw-payload preservation,
  separately supplied contradictory observations and versioned pathway member scope.
- Old observation checks still run and retain their old outcomes. Their failures no
  longer decide research completion, and their successes cannot suppress source retries.
- This is software verification, not a biological benchmark or live external-data/
  model/deployment test. No paid model call or Modal redeployment was used for validation.

Deploy both the coordinator backend and report frontend from the same revision.
For the integrated app the existing command is `modal deploy --strategy recreate modal_app.py`.
Old saved reports retain their old results; start a new investigation to use schema 0.2.
The separate data-pipeline deployment does not need to change for this patch.
