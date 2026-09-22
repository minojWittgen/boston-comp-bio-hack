# Frontend/backend integration handoff

## Integration decision

Use the system on `codex/investigation-coordinator` (currently `f7578e7`) as the
scientific backend. Its scientific engine, planner and schemas are unchanged.
`coordinator/api.py` has optional submission and read callbacks so the integrated app
can validate requests before creating a job and serve cached tutorials through the same
state/report routes; standalone behavior is unchanged. Replace the
earlier frontend branch's separate numerical coordinator with thin adapters around
this implementation. The old engine, examples and tests remain available in Git
history at `09505fc`; they are not a second runtime option.

The user approved connecting the team's first draft and adapting the UI to its
contract. No model weights are hosted: the team's ClaudePlanner calls the Anthropic
SDK for intent planning. The combined app now injects a visitor-specific SDK client
for each website chat request. It ignores host model credentials, and passes only
the resulting validated plan into background execution. MCP requires explicit criteria
from the connected assistant and never calls a model. The remainder is the team’s
deterministic research workflow.

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

The newer pathway/in-vitro pipeline from `jaeeun-wittgen/data-pipeline` is included
from shared `main` at `41e488d`. The coordinator remains unchanged: its adapter retains
unknown source payloads as background and reports unsupported-source gaps. HPA cell-line
summaries and Open Targets DepMap now have explicit background adapters: both retain
in-vitro human context, HPA's combined RNA/localization summary has no single assigned
modality, and DepMap remains a CRISPR fitness reference rather than RNA abundance.
The team's HPA pathology adapter retains patient-context cohort RNA as background,
without inventing patient identities or matched observations. Native
pathway-package orchestration and the new source semantics still need coordinator
adapter work; merging the code does not promote retrieved records to observations or
invent versioned pathway membership.

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

The user requested an open tutorial and direct Claude MCP connection. The combined
Modal deployment is now explicitly public (`api_token=""`), and no longer mounts the
old access-code secret. Local/standalone APIs still support optional bearer-token auth.
The public run store is `xctx-public-investigations`, separate from former team runs.
No listing endpoint exists; knowing a public run ID permits retrieving its result.

The default view is **Try the tutorial**. Its two fixture results are computed by the
canonical coordinator, cached in process and copied per read; no API/worker is needed.
MCP and `/demos` serve the same cached cases. A new optional canonical read callback
allows their IDs through both state and Markdown-report routes.

**Investigate with your key** exposes the existing chat and key settings. **Connect
through MCP** supplies exact Claude Code commands and Claude app setup instructions.
The server uses Streamable HTTP without authentication; no separate model key is needed.

Visitor model keys are password inputs in the
Streamlit session. `/chat` receives them in dedicated headers and uses them only for
one bounded planning call; they never enter worker arguments or saved runs. The
model setting has no environment fallback. Clearing the key prevents further chat
calls until it is reentered. It does not cancel an already submitted investigation.

The SDK client is per request, uses the official Anthropic endpoint, and closes after
planning. Never set process-wide environment variables for visitor credentials.
The frontend refuses to send keys over non-local HTTP or follow redirects. Do not
enable request-header logging on the API or reverse proxy. Missing settings and safe
provider errors return HTTP 422 without creating a job.

Public live starts share an atomic 12-slot allowance in a dedicated Modal Dict;
exhaustion returns HTTP 429 / an MCP tool error before a worker is created. A capacity
check before chat planning avoids charging a visitor when the allowance is already
exhausted; a concurrent request can still take the final slot during planning. The
fixed default window ends 2026-09-29 00:00 UTC, before the initial reservations can
expire from seven days of inactivity. There is no automatic daily renewal. See README
for owner overrides and limits; tutorials remain usable after the live allowance ends.

## Verified in this integration

- Canonical nested HTTP submission and unchanged RunState/Markdown report.
- Both synthetic examples through the actual coordinator, local API and Streamlit UI.
- `complete / conflicting` and `partial / not_assessable` shown distinctly.
- Authentication, invalid schemas, unknown/pending parents, failed planning/scheduling.
- Follow-up questions include only researcher-authored text in new planner input.
- MCP uses the same jobs/results; actual local Streamable HTTP smoke test.
- Coordinator and pipeline offline suites, plus adapter-specific tests.

Visitor-key tests cover concurrent SDK clients, missing-key refusal even with host
credentials set, sanitized provider errors, credential-free dispatch and saved state,
key-free structured MCP, and isolated/clearable frontend settings. Live Claude calls
require a visitor key and are not claimed by the offline test suite. Cloud deployment
and transport checks are documented separately when performed.
