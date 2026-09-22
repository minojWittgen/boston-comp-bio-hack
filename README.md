# Boston Computational Biology Hackathon — Team Workspace

Shared code and notes for our team's project at the [Boston Computational Biology Hackathon](https://luma.com/boston-comp-bio-hack), hosted by Anthropic, Modal, and Flagship Pioneering.

## Get started

```bash
git clone https://github.com/minojWittgen/boston-comp-bio-hack.git
cd boston-comp-bio-hack
git switch -c your-name/short-task
```

## Run the shared investigation service

This implementation is on `codex/coordinator-modal-mcp`, based on the team's
`jaeeun-wittgen/data-pipeline` branch. Check out this branch before following the
commands below while it is awaiting integration into `main`.

The coordinator, Streamlit frontend and MCP adapter share one investigation service.
The scientific scope is in [the canonical design](cross-context-biology-agent.md);
the implemented workflow and its limits are in [the coordinator guide](docs/coordinator.md).

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

For a local numerical demonstration without API credentials, start the service:

```bash
COORDINATOR_MODEL_ENABLED=0 python -m uvicorn coordinator.api:local_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal, with the virtual environment activated:

```bash
streamlit run streamlit_app.py
```

Open the displayed local URL, choose **Synthetic development example**, expand the
scientific criteria, confirm them, and start the investigation. The numerical
workflow executes; the report explicitly labels the data synthetic and the model
interpretation disabled. This is a software demonstration, not a real finding or
held-out evaluation. To run Claude locally, configure `ANTHROPIC_API_KEY` in the
server environment and omit `COORDINATOR_MODEL_ENABLED=0`. Live reference retrieval
also needs Modal access to the existing pipeline workspace.

## Deploy to Modal

1. Run `modal setup` and select the workspace/environment containing the existing
   `xctx-evidence` app and `xctx-cache` volume. The pipeline is maintained under
   [data_pipeline](data_pipeline/README.md).
2. In the Modal dashboard, create the secret **`xctx-research-secrets`** containing
   `ANTHROPIC_API_KEY` and a random `INVESTIGATION_API_TOKEN`. Keep values out of Git.
   Use the investigation token as the hosted frontend's team access code.
3. Deploy:

```bash
modal deploy modal_app.py
```

The deployment defines `run_investigation` (background worker), `api` (REST and MCP),
and `web` (Streamlit). Deployment prints the API and frontend URLs. The MCP URL is
the API URL followed by **`/mcp/`**. The frontend uses that same API; it has no separate
research or model loop.

Configuration overrides, set before deployment: `COORDINATOR_SECRET_NAME`,
`ANTHROPIC_MODEL`, `EVIDENCE_APP_NAME`, `EVIDENCE_VOLUME_NAME`, and
`EVIDENCE_ENVIRONMENT`. Run `modal deploy --env <environment> modal_app.py` when using
a non-default Modal environment. Workspaces are selected through the Modal profile.

## Use the API or MCP

`POST /investigations` starts a job; `GET /investigations/{id}` returns progress and
results. Both require a bearer token when one is configured. The complete request
example is [examples/development-investigation.json](examples/development-investigation.json).
Scientific criteria are immutable after submission. Requests without confirmed
criteria return a `needs_input` run; resubmit a new request after review.

The MCP exposes `start_investigation(request)` and `get_investigation(investigation_id)`.
It uses Streamable HTTP and the same bearer token. Test a real MCP connection:

```bash
# Set INVESTIGATION_API_TOKEN in your environment for a protected endpoint.
python scripts/smoke_mcp.py http://127.0.0.1:8000/mcp/
# Replace the local URL with the deployed API URL plus /mcp/ for the cloud test.
```

This tests a synthetic investigation through the actual MCP transport. Clients must
support bearer authorization headers. OAuth-only connector setup is not implemented;
Claude web/Science connectivity has not been verified. The bundled Python client is
the reference connection test.

## Verify

```bash
python -m pytest tests data_pipeline/tests -q
```

Tests cover numerical contrasts, missing contexts, incorrect patient pairing,
metadata recovery followed by disagreement, species mapping, assay meaning,
duplicate replicates, budgets, model citation/status checks, HTTP access, and MCP
sharing the same run state. Cloud credentials and live model calls require a separate
deployment smoke test.

## Work together

- Use GitHub Issues to record tasks, owners, and the next concrete step.
- Work on a branch and open a pull request when a change is ready to share.
- Ask the repository owner for collaborator access to push branches. Without write access, fork the repository and submit a pull request if it is public.
- Keep API keys in local environment variables or the deployment platform's secret store.
- Keep datasets, model weights, and generated results outside Git; document their source and retrieval steps.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow.

## Team decisions

- [ ] Choose a problem, intended user, and demo outcome.
- [ ] Add teammates as GitHub collaborators.
- [x] Choose the runtime and dependency setup (Python 3.11; pinned SDK dependencies).
- [ ] Set up shared Modal access and Claude API access as needed.
- [ ] Document the data source, evaluation method, and demo instructions.
- [ ] Agree on a license before distributing the project for reuse.
