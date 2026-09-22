# Boston Computational Biology Hackathon — Team Workspace

Research chat, API and MCP for the team's cross-context investigation coordinator.
Scientific behavior comes from [`coordinator/`](coordinator/README.md), integrated from
`codex/investigation-coordinator` at `f7578e7`. Frontend and transport adapters live in
`research_app/`; there is one scientific planner, evidence adapter, checker and research engine.

The coordinator investigates existing source findings across species, experimental
contexts and modalities. It reports what was found, how results differ, source links,
uncertainty and next research steps. **Completing the investigation does not require a
conclusive biological verdict.** Existing database summaries are used at their stated
scope; raw-data analysis is not required for this report.

Schema 0.2 makes `RunState.investigation` the primary result. The earlier
`assessment` remains a separate diagnostic for explicitly supplied observations.
See the [implementation and benchmark handoff](docs/investigation-first-handoff.md).

## Try it without setup

Open the [hosted app](https://minoj--xctx-research-web.modal.run). **Introduction**
explains the scientific rationale. **Research workspace** contains **Guided examples**,
**Ask your own question**, and **Use in Claude (MCP)**. **References** credits the methods,
data sources and reviewed tools, with links to the project's Markdown documentation.
No access code or API key is needed to explore the story, examples or references.
Only website chat needs your own API key; MCP uses your connected assistant's model.
See the [demo story and walkthrough](docs/demo-story.md).

```bash
claude mcp add --transport http cross-context-biology https://minoj--xctx-research-api.modal.run/mcp/
claude mcp get cross-context-biology
```

Claude app users can add that URL under Customize → Connectors → Add custom connector.
The hosted MCP requires no authentication. This repository also includes a `.mcp.json`
configuration for Claude Code; approve it when the client asks. See [MCP setup](docs/mcp.md).

## Run the integrated app locally

From the repository root after pulling `main`:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
XCTX_RUN_DIR=/tmp/xctx-investigations .venv/bin/python -m uvicorn research_app.api:create_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
.venv/bin/python -m streamlit run streamlit_app.py
```

Open **http://127.0.0.1:8501**, then choose **Explore a guided example**. There are two explicit synthetic cases:

| Example | Investigation | Optional measurement comparison |
| --- | --- | --- |
| Disagreement across contexts | Complete | Measurements disagree |
| Missing patient evidence | Collection incomplete | Not enough comparable evidence |

Both use cached outputs from the team's coordinator and its declared fixtures.
The tutorial works with only Streamlit running: it needs no backend, credentials or
live collection. An ordinary chat
request never silently falls back to these fixtures.

For real free-text questions, enter **your Anthropic API key and model ID** in the
**Ask your own question** sidebar under **Your API key · website chat**. Each visitor pays for their own planning
calls. The combined app never falls back to a host model key, even if one exists in
the environment. Keys stay in the visitor’s session and the planning HTTP request;
they are excluded from background jobs, stored investigations and downloads. Use
**Clear API key** when finished. The model field is prefilled with `claude-opus-5-5`
and can be changed to a model available to your Anthropic account. Credentials and
the selected conversation survive page changes within the same session. Saved report
links open directly in the research workspace without a key or a new model call.
Leave `XCTX_EVIDENCE_DIR` unset to use the Modal evidence collector. Modal authentication
and access to `xctx-evidence` / `xctx-cache` are also required for live collection.
For an intentional local replay, use an absolute `XCTX_EVIDENCE_DIR` with packages that
match the request's gene, disease and mode. See the [coordinator guide](coordinator/README.md).

## Integration contract

- `POST /investigations` accepts the team's nested **`Submission`**: `request` and
  optional `observations`. The combined app requires explicit `request.requirements`
  and genes (or versioned pathway genes), so structured requests never call a model.
  It returns `run_id`, `status`, and `status_url`.
- `POST /chat` accepts `prompt` and optional `previous_investigation_id`. It wraps
  researcher-authored text in a canonical request and uses the same coordinator.
  Supply `X-Anthropic-Api-Key` and `X-Anthropic-Model` headers on this route only.
  Planning completes before HTTP 202; allow up to 90 seconds for the request.
- `GET /investigations/{run_id}` returns the canonical **`RunState`** unchanged.
- `GET /investigations/{run_id}/report` returns Markdown, or HTTP 409 before available.
- `POST /demos` selects one of two cached synthetic fixtures without creating a worker
  or consuming the public live-run allowance. Its returned status can already be terminal.
- `/mcp/` exposes `start_investigation` and `get_investigation` over Streamable HTTP.
  The connected assistant supplies explicit criteria; no separate model key is needed.
  See the [MCP introduction and connection guide](docs/mcp.md).
- `/openapi.json` and `coordinator/models.py` are the contract sources of truth.

The Python frontend imports these schemas directly; it does not maintain a copy.
The UI shows research findings, all three contexts, scope/assumptions, source evidence
IDs, provenance, uncertainty, next steps and activity. Optional observation diagnostics
remain separate from investigation completion.
It provides Markdown and full-evidence downloads. No contract JSON editor is needed.

Read the [frontend/backend integration guide](docs/frontend-integration.md),
[chat contract guide](docs/chat-and-contract.md), and
[team coordinator handoff](coordinator/README.md).
The [September 22 demo handoff](docs/demo-handoff-2026-09-22.md) records the fixes,
exact live checks, known limits, and commands to reproduce this deployment.

## Deploy the integrated frontend and backend on Modal

The existing pipeline must be available in the selected workspace: app `xctx-evidence`,
function `build_one`, volume `xctx-cache`.

The combined demo requires no shared model key or access-code secret. Website chat
uses visitor credentials; MCP uses the connected assistant's model. Former secrets
can remain in the workspace, but this deployment does not attach them.

```bash
.venv/bin/modal deploy --strategy recreate modal_app.py
```

The integrated app is **`xctx-research`**, with `api` (canonical HTTP + chat/MCP),
`run_investigation` (team coordinator in a detached worker), and `web` (Streamlit).
The frontend finds this deployment's API automatically. The MCP URL is the printed API
URL plus `/mcp/`. Cloud calls preserve worker IDs and the team's polling reconciliation.
Finished artifacts also go to `xctx-investigation-artifacts`.

`recreate` restarts existing containers. Wait for running investigations to finish
before deployment; active website sessions must reload. This prevents an old Streamlit
WebSocket from blocking replacement while the website is capped at one container.

The separate `coordinator/modal_app.py` remains the team's standalone HTTP deployment.
Use the root `modal_app.py` for this combined chat/MCP frontend. Both run the same engine.
The combined deployment is public. Old team runs remain in `xctx-investigations`;
new public runs use `xctx-public-investigations`. Run IDs grant access to their results,
so use public research questions/data. There is no account-based privacy or run listing.
Standalone/local API deployments can still explicitly configure a bearer token.

**Visitors fund website model calls; Modal hosting and evidence collection still use
the deployment owner's account.** The public deployment permits **12 live starts**
by default, shared by chat, structured HTTP and MCP. Atomic reservations in
`xctx-public-run-budget` survive redeployments. Tutorials use cached fixtures and do
not consume this allowance or launch detached workers.

The live allowance closes at **2026-09-29 00:00 UTC**; tutorials remain available.
This fixed window prevents Modal Dict's seven-day inactivity expiry from reopening
the allowance after the hackathon. The owner can explicitly configure
`XCTX_PUBLIC_RUN_LIMIT` and `XCTX_PUBLIC_UNTIL` when deploying, or set the limit to zero
to stop new live runs. Extending beyond the initial window requires accounting for
Dict expiry; this is a demo allowance, not a durable billing system. Reservations
are not refunded on worker/dispatch failure. Existing runs can still be read.
These controls bound new investigations, not all public HTTP hosting costs.

The model has no shared-key fallback. A paid live model call still requires a visitor's
key. The MCP host's own subscription/usage charges are separate.

## Verify

```bash
.venv/bin/python -m pytest tests coordinator/tests data_pipeline/tests -q
.venv/bin/python scripts/smoke_mcp.py http://127.0.0.1:8000/mcp/
```

The MCP smoke test explicitly runs the synthetic conflict fixture and expects
`complete / conflicting`. Tests do not call paid models or claim scientific validation.

## Work together

Use feature branches and pull requests. Keep keys and generated data out of Git.
The team's [canonical scientific design](cross-context-biology-agent.md) defines the
broader research scope; the current gene pipeline and declared-observation checks
are only the implemented adapters. See [CONTRIBUTING.md](CONTRIBUTING.md).
