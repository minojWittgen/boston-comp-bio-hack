# Demo story and walkthrough

## The story

A promising finding is a beginning. Where else does it hold?

A result in a cell culture can open a new biological question. Understanding what
it means for a living organism or a patient takes evidence from other experiments,
other measurements and other people. Species, tissues, disease conditions, treatments
and sample identity shape what a result means. DNA, RNA, protein and functional
experiments contribute different kinds of evidence.

Finding relevant publications is a starting point. Assessing a claim across contexts
also requires the underlying measurements, the study conditions and a justified way
to compare them. Our goal is an agent-guided workflow that follows a question into
published data and explains agreement, disagreement and missing evidence.

## The three pages

1. **Introduction** tells this story and offers a no-key guided example.
2. **Research workspace** contains **Guided examples**, **Ask your own question**, and
   **Use in Claude (MCP)**. A saved `?report=<id>` link opens directly here. API keys,
   model settings, the chosen example and the current report survive page changes
   within the same session. Reloads, server restarts and new sessions can clear keys.
3. **References & structure** introduces the shared architecture and investigation
   flow, then distinguishes methodological inspiration, sources queried by the
   pipeline, related systems reviewed as candidates, and implementation documentation.

The page copy lives in `research_app/site_pages.py`. Navigation and the workspace
live in `streamlit_app.py`. Report explanations remain projections of the canonical
coordinator results; changing wording does not change the saved plan or checks.

## A short presentation

Start with Introduction: **“One finding raises a question: where else does it hold?”**
Point to cell cultures, animal models and patients. Explain that the measurements and
experimental settings must be understood before evidence can be compared.

The introduction uses four diagrams in `research_app/intro_diagrams.py`:

1. **Paper-focused search versus evidence with context.** A workflow that stops at
   publication summaries can leave measured values, experimental conditions, species
   differences and patient variation out of view. This is a comparison of workflows,
   not a claim that all LLMs are restricted to papers. The prototype inspects source
   records and metadata; raw-data reanalysis remains further work.
2. **Cell cultures ↔ animal models ↔ patients.** Connections represent research
   questions requiring evidence, not automatic biological translation.
3. **Measurement × context map.** Select DNA, RNA, Protein or Function to highlight
   the corresponding research questions. The map is conceptual, not a live inventory
   of retrieved data. Each measurement retains its own biological meaning.
4. **Agreement, differences and gaps.** A useful report makes the next research
   question visible and keeps sources traceable.

The diagrams use local HTML/CSS and inline vector icons, with accessible text and
responsive layouts. They require no external assets, model calls or new dependencies.

Open **Explore a guided example**. The default example deliberately disagrees across
contexts. Show **Findings**, **Comparisons**, **Sources**, and **What we needed
to answer**. The supplied measurement comparison is expandable inside Comparisons;
disagreement is an informative outcome, not a failed search. Switch to
**Missing patient evidence** to show how the report explains missing source information.
Both examples are synthetic teaching cases, not biological findings.

For a live example, reopen an existing report with its saved link. No key or new
collection is needed. Show the returned database information and publication links,
then explain the source findings, their context, uncertainties and next steps.
Historical schema 0.1 reports preserve their original result and **Why this result?**
tab; they are not silently rescored. New schema 0.2 reports present source findings
first and keep optional study-measurement checks separate from research completion.
To start a new question, select **Ask your own question** and enter
your Anthropic API key and an available model ID in the sidebar.

Show **Use in Claude (MCP)** for the alternative entry point: an existing assistant
can call the same research tools. The server does not require a separate Anthropic
API key; the connected client's subscription or model charges still apply.

Finish with **References & structure** so people can inspect our rationale, sources
and code. Its two diagrams in `research_app/structure_diagrams.py` explain:

1. **One research system, two ways in.** Website chat and Claude MCP use the same
   coordinator, which collects gene evidence through the separately hosted pipeline
   and returns saved reports. Website chat uses the visitor's model key for planning;
   MCP accepts the connected assistant's structured scope. Source synthesis adds no
   post-retrieval model call. This follows the [integration guide](frontend-integration.md),
   [MCP guide](mcp.md) and [pipeline flow](../data_pipeline/PIPELINE.md).
2. **From a question to a report.** Define scope, collect sources, compare findings,
   review gaps and report next steps. Recoverable collection failures can trigger at
   most one retry within the budget. This follows the current
   [coordinator workflow](../coordinator/README.md#execution-and-scientific-meaning) and
   [investigation-first contract](investigation-first-handoff.md), rather than treating
   the broader design document as fully implemented.

The expandable scope note distinguishes gene collection from the pipeline's separate
pathway support and the future work of raw-data analysis and matched-patient comparisons.
The page remains readable offline without credentials, and the existing references
remain available below the architecture overview.

## What is implemented, and what comes next

The prototype plans research scope, retrieves context-tagged source information,
explains findings and differences, and produces traceable reports. Research completion
means the bounded source investigation is done, not that a biological claim is proven.
Database records contribute at their reported scope. Optional checks of separately
supplied study observations compare declared metadata and reported directions of change.
The pipeline does not automatically extract and harmonize real study observations.
The examples supply synthetic observations. The current behavior is documented in the
[investigation-first handoff](investigation-first-handoff.md).

Extracting measurements from real studies, harmonizing datasets, retaining participant
and specimen relationships, and running independently checked numerical analyses are
further work toward the broader design. A descriptive comparison is not proof of
causality, clinical efficacy or biological replication. More returned rows or portals
do not establish independent study populations.

## Attribution

- [Scientific design](../cross-context-biology-agent.md): rationale, evidence dimensions
  and candidate inventory. This is broader than the implemented prototype.
- [Coordinator build notes](plans/2026-09-22-coordinator-build.md): AutoSciRub procedures
  adapted in our own words from pinned upstream source. This change did not vendor its
  implementation code or use its full runtime. The UI links the preprint and these notes.
- [Anthropic agent architecture](https://www.anthropic.com/engineering/building-effective-agents)
  and [evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents):
  architectural and evaluation influences.
- [Pipeline flow](../data_pipeline/PIPELINE.md) and [source registry](../data_pipeline/tools.md):
  actual source roles and limitations. Open Targets may expose other providers' data;
  source overlap is not independent replication.
- Biomni, ToolUniverse and Open Targets MCP are reviewed related systems. Their listing
  does not mean those frameworks are integrated into this demo.

## Verification

```bash
.venv/bin/python -m pytest tests coordinator/tests data_pipeline/tests -q
```

Navigation tests cover offline public pages, entering the examples/chat, keeping API
settings and conversations across pages, preserving the chosen example, and opening a
saved report directly without a key or a new model call. No paid model calls are needed.
