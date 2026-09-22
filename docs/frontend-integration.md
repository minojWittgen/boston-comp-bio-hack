# Frontend/backend integration handoff

## Integration decision

Use the system on `codex/investigation-coordinator` (currently `f7578e7`) as the
scientific backend. Its `coordinator/` directory is imported unchanged. Replace the
earlier frontend branch's separate numerical coordinator with thin adapters around
this implementation. The old engine, examples and tests remain available in Git
history at `09505fc`; they are not a second runtime option.

The user approved connecting the team's first draft and adapting the UI to its
contract. No model weights are hosted: the team's ClaudePlanner calls the Anthropic
SDK for intent planning. The remainder is the team's deterministic research workflow.

## Boundaries for future updates

| Layer | Owner/interface | Integration behavior |
| --- | --- | --- |
| Scientific schema | `coordinator/models.py` | Import `Submission`, `RunState`, requirements and evidence types directly |
| Planning/research/checks | `coordinator/` | No frontend copies or rewritten conclusions |
| HTTP core | `coordinator.api.create_app` | Keep its submission, state and Markdown-report routes |
| Chat/MCP additions | `research_app/api.py` | Add `/chat`, explicit `/demos`, and `/mcp/` to the canonical app |
| Dispatch | `research_app/service.py` | Create canonical jobs and call the same engine locally or on Modal |
| Rendering | `research_app/presentation.py`, `streamlit_app.py` | Display coverage, assumptions, comparisons and provenance |
| Cloud deployment | root `modal_app.py` | Team engine + existing job reconciliation + frontend/MCP adapters |

Pull updates from the team's coordinator branch and run its tests plus the integration
tests. Keep shared schema changes in `coordinator/models.py`; update UI projections when
needed. Preserve `coordinator/AGENTS.md` and the team's scientific limitations. There is
no need to port changes into a second planner or checker.

The newer pathway/in-vitro pipeline on `jaeeun-wittgen/data-pipeline` was inspected but
is not merged by this frontend integration. Its new formats need the coordinator team's
adapter review; this integration does not silently treat those background records as
empirical observations or invent pathway membership.

## UI semantics

The coordinator's context name is `patient` (singular). The frontend labels it
“Patients” and always displays in vitro, in vivo and patient coverage. A context with
no scoped requirement says it was not assessed; the frontend does not add requirements
or fabricate a conclusion for that context.

Execution `complete` can accompany evidence `conflicting`, `inconclusive`, or (when
only coverage is checked) `not_assessable`. Display both values from the backend.
Context cards count passed requirements; they never label background retrieval as
support. Show the actual comparison conclusions and evidence IDs separately.

The Research plan tab exposes generated assumptions for review in plain language.
It is read-only; a chat clarification creates a new run. It does not claim the user
approved machine-proposed scope. The old JSON upload/editor and automatic numerical
fold-change display were removed because they do not describe this backend.

Evidence records remain split by `level=observation` or `level=background`, preserving
species, host, context, modality, endpoint, study and individual identifiers. The full
record and raw source payload can be inspected; full original packages are included in
the JSON download. Markdown reports are returned by the team's report renderer.

A failed run may have no plan, evidence, assessment or report. Show the error and event
history without assuming a report exists. Do not silently substitute fixtures or make
a new model decision when planning fails.

## Jobs and access

Local jobs run in a bounded four-thread executor and write atomic snapshots using the
team's FileRunStore. A server restart does not resume an active local job; use a new
conversation. Cloud jobs use the team's ModalRunStore and persist each detached call ID.
The same `reconcile_job` implementation runs on state/report polling, so provider polling
failures are not mistaken for biological or worker failure.

The integrated API protects chat, MCP, schema and investigation routes with the same
token; `/health` is public and does not indicate model readiness. Prefer
`COORDINATOR_API_TOKEN`; the previous `INVESTIGATION_API_TOKEN` alias is accepted only
when the canonical name is absent. The frontend keeps credentials server-side.

## Verified in this integration

- Canonical nested HTTP submission and unchanged RunState/Markdown report.
- Both synthetic examples through the actual coordinator, local API and Streamlit UI.
- `complete / conflicting` and `partial / not_assessable` shown distinctly.
- Authentication, invalid schemas, unknown/pending parents, failed planning/scheduling.
- Follow-up questions include only researcher-authored text in new planner input.
- MCP uses the same jobs/results; actual local Streamable HTTP smoke test.
- Coordinator and pipeline offline suites, plus adapter-specific tests.

Live Claude execution and the integrated cloud deployment are not verified. The Modal
workspace lacks `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`. Existing pipeline deployment
verification from the preceding turn does not verify this new cloud coordinator.
