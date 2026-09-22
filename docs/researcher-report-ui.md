# Researcher-facing reports

The website presents the research question, comparisons, source contents and missing
study information. It no longer uses coordinator status codes, evidence record IDs,
raw arrays or study-count ratios as the default report.

## What changed

- **Source search** says Finished, In progress, Some sources unavailable or Could not
  finish. A completed search can still lack the evidence needed for a comparison.
- **Answer to your question** describes agreement, disagreement, uncertainty or
  insufficient comparable evidence. The canonical scientific assessment is unchanged.
- **Comparisons** names the genes, contexts, species and modalities being compared and
  explains missing evidence in words.
- **Sources** shows source-specific summaries, actual returned measurements, cell-line
  names, PubMed article links, and study/participant/sample identifiers when supplied.
  Missing identifiers say **Not supplied by this source**. Internal evidence IDs are
  never substituted for study IDs. PubMed search hits are not screened study evidence.
- **What we need to answer** explains the requested measurements and whether the criteria
  came from the submitted request or were proposed by the model. A requested measurement
  is not a claim about what a source measured.
- Raw checks, events, internal IDs and the original JSON remain under **Technical details
  and original data**. The readable Markdown download uses the same presentation as the
  website; API/MCP contracts and the canonical report are unchanged.

Database links are constructed from identifiers or queries actually returned by each
source. They navigate to the source, rather than claiming a database landing page is an
experimental citation. Source versions and retrieval times are shown when supplied.
The current pipeline's database summaries remain background records. They do not gain
study-level or patient-level status because the UI makes them easier to read.

## Reopen a result without another model call

Append `?report=<investigation_id>` to the website URL, or use **Reopen this saved
report** below the result. This only retrieves an existing report; no key or new
collection is needed. The existing public-demo access policy still applies: anyone
with the report link can view it. Keys are not put in URLs or reports.

Saved MLH1 result from the earlier Opus test:

[Open the real MLH1 report](https://minoj--xctx-research-web.modal.run/?report=8f0a8c066be24a92918e7f3edd6fc07c)

It contains 11 background records. PubMed returned 20 identifiers from 3,229 matches;
Open Targets returned 25 associations from 1,181. Those search limits remain visible.
There are no normalized study observations for the requested cross-context comparison.

## Reproduce and verify

```bash
.venv/bin/python -m pytest tests coordinator/tests data_pipeline/tests -q
INVESTIGATION_API_URL=https://minoj--xctx-research-api.modal.run \
  .venv/bin/python -m streamlit run streamlit_app.py
```

Open the local website with the same `?report=` link. Tests cover source links, missing
and supplied identifiers, real numeric source fields, synthetic-result labeling,
collection failures versus evidence gaps, report exports, session switching, and
reopening reports without a paid model call. They use local fixtures and fake clients.
The combined suite passed **192 tests and 40 subtests** (one existing dependency deprecation warning).
The real saved MLH1 result was also replayed with Streamlit AppTest and in a browser.

The source adapters from main at `e77ec59` are included. The team updated the HPA test fixture
to the pipeline's explicit `has_cancer_rna` flag; an additional regression check confirms
that disease annotations alone are not labeled RNA. No scientific check was relaxed.

Before deployment, check that investigation workers are idle, then run:

```bash
.venv/bin/modal deploy --strategy recreate modal_app.py
```

Recreation restarts website sessions. Open the saved-report link to recover a result;
API keys remain session-only and may need to be entered again for new questions.
No pipeline deployment or paid model call is required for this UI update.
