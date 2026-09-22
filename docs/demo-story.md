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
3. **References** distinguishes methodological inspiration, sources queried by the
   pipeline, related systems reviewed as candidates, and implementation documentation.

The page copy lives in `research_app/site_pages.py`. Navigation and the workspace
live in `streamlit_app.py`. Report explanations remain projections of the canonical
coordinator results; changing wording does not change the saved plan or checks.

## A short presentation

Start with Introduction: **“One finding raises a question: where else does it hold?”**
Point to cell cultures, animal models and patients. Explain that the measurements and
experimental settings must be understood before evidence can be compared.

Open **Explore a guided example**. The default example deliberately disagrees across
contexts. Show **Why this result?**, **Comparisons**, **Sources**, and **What we needed
to answer**. Disagreement is an informative outcome, not a failed search. Switch to
**Missing patient evidence** to show how the report explains an unanswered question.
Both examples are synthetic teaching cases, not biological findings.

For a live example, reopen an existing report with its saved link. No key or new
collection is needed. Show the returned database information and publication links,
then explain why reference material may still be insufficient for the requested
study comparison. To start a new question, select **Ask your own question** and enter
your Anthropic API key and an available model ID in the sidebar.

Show **Use in Claude (MCP)** for the alternative entry point: an existing assistant
can call the same research tools. The server does not require a separate Anthropic
API key; the connected client's subscription or model charges still apply.

Finish with **References** so people can inspect our rationale, sources and code.

## What is implemented, and what comes next

The prototype plans evidence requirements, retrieves context-tagged source information,
checks separately supplied study observations and produces traceable reports. Current
comparisons check declared metadata and reported directions of change. Live source
retrieval currently returns background/reference records; it does not automatically
extract and harmonize real study observations. The examples supply synthetic observations.

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
