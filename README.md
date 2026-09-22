# Boston Computational Biology Hackathon — Team Workspace

Research chat, API and MCP for the team's cross-context investigation coordinator.
Scientific behavior comes from [`coordinator/`](coordinator/README.md), integrated from
`codex/investigation-coordinator` at `f7578e7`. Frontend and transport adapters live in
`research_app/`; there is one planner, evidence adapter, checker and research engine.

The coordinator compares **declared observations**. It currently does not generate
experimental measurements or run a new statistical analysis. Real empirical data
still needs the team's observation/analysis adapter. Source retrieval is background,
not biological validation.

## Run the integrated app locally

From this branch (`codex/coordinator-modal-mcp`):

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
XCTX_RUN_DIR=/tmp/xctx-investigations .venv/bin/python -m uvicorn research_app.api:create_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
.venv/bin/python -m streamlit run streamlit_app.py
```

Open **http://127.0.0.1:8501**. The sidebar offers two explicit synthetic examples:

| Example | Execution | Evidence conclusion |
| --- | --- | --- |
| Disagreement across contexts | complete | conflicting |
| Missing observations | partial | not_assessable |

Both run the team's coordinator with its own declared fixtures and directory provider.
They require no model credentials and do not contact live sources. An ordinary chat
request never silently falls back to these fixtures.

For real free-text questions, configure `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` in the
API server environment. The model is explicitly selected; there is no default model.
Leave `XCTX_EVIDENCE_DIR` unset to use the Modal evidence collector. Modal authentication
and access to `xctx-evidence` / `xctx-cache` are also required for live collection.
For an intentional local replay, use an absolute `XCTX_EVIDENCE_DIR` with packages that
match the request's gene, disease and mode. See the [coordinator guide](coordinator/README.md).

## Integration contract

- `POST /investigations` accepts the team's nested **`Submission`**: `request` and
  optional `observations`. It returns `run_id`, `status`, and `status_url`.
- `POST /chat` accepts `prompt` and optional `previous_investigation_id`. It wraps
  researcher-authored text in a canonical request and uses the same coordinator.
- `GET /investigations/{run_id}` returns the canonical **`RunState`** unchanged.
- `GET /investigations/{run_id}/report` returns Markdown, or HTTP 409 before available.
- `POST /demos` explicitly selects one of the two documented synthetic fixtures.
- `/mcp/` exposes `start_investigation` and `get_investigation` over Streamable HTTP.
- `/openapi.json` and `coordinator/models.py` are the contract sources of truth.

The Python frontend imports these schemas directly; it does not maintain a copy.
The UI shows execution status, scientific conclusion, all three contexts, proposed
scope/assumptions, criterion evidence IDs, provenance, gaps and activity separately.
It provides Markdown and full-evidence downloads. No contract JSON editor is needed.

Read the [frontend/backend integration guide](docs/frontend-integration.md),
[chat contract guide](docs/chat-and-contract.md), and
[team coordinator handoff](coordinator/README.md).

## Deploy the integrated frontend and backend on Modal

The existing pipeline must be available in the selected workspace: app `xctx-evidence`,
function `build_one`, volume `xctx-cache`.

Configure Modal secret **`xctx-research-secrets`** with:

- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL` (an explicitly chosen provider model)
- `COORDINATOR_API_TOKEN` (a random shared team access code)

The earlier `INVESTIGATION_API_TOKEN` name remains supported if the canonical token
name is absent. Keep its value out of Git. The generated local access code, if present,
is in the ignored `.env.demo` file. `COORDINATOR_SECRET_NAME=xctx-coordinator` can select
the team's existing secret instead. A deployment-time `ANTHROPIC_MODEL` can explicitly
override the secret's model setting.

```bash
.venv/bin/modal deploy modal_app.py
```

The integrated app is **`xctx-research`**, with `api` (canonical HTTP + chat/MCP),
`run_investigation` (team coordinator in a detached worker), and `web` (Streamlit).
The frontend finds this deployment's API automatically. The MCP URL is the printed API
URL plus `/mcp/`. Cloud calls preserve worker IDs and the team's polling reconciliation.
Finished artifacts also go to `xctx-investigation-artifacts`.

The separate `coordinator/modal_app.py` remains the team's standalone HTTP deployment.
Use the root `modal_app.py` for this combined chat/MCP frontend. Both run the same engine.
The hosted UI and API require the same team access code; this is shared demo access,
not per-user authorization or OAuth. OAuth-only MCP clients need a separate adapter.

**This integration has been verified locally; the integrated cloud app is not deployed.**
As of this handoff, the workspace's model key and model setting are still missing.

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
