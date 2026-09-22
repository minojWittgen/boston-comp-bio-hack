# Chat input and the team's investigation contract

The user writes a question. `POST /chat` wraps it in the team's canonical
`Submission(request=InvestigationRequest(question=...))`. The coordinator's
`ClaudePlanner` frames natural language using the visitor’s key and model from
`X-Anthropic-Api-Key` / `X-Anthropic-Model` headers. This bounded call finishes before
the job is submitted. Only the validated `ResearchPlan` travels to the worker, which
freezes it before collection and performs the coordinator’s own evidence checks. No second
intake model or scientific schema is maintained by the frontend.

```json
{"prompt": "Compare TYK2 RNA abundance in human cell cultures, mouse models and psoriasis patients."}
```

Include both model headers; missing settings return HTTP 422 before creating a job.
No shared environment model key is used. Provider errors are sanitized, and credentials
are never part of a Submission, RunState, worker argument, report or download.
The frontend keeps the key and model in session memory across tutorial/chat/MCP view
switches and provides a clear-key button. A new browser session starts without a key;
reloads and server restarts can end the session. The editable demo model default is
`claude-opus-5-5`, verified through the supplied demo account's model listing. There is
no automatic model fallback. Planning uses `tool_choice: auto` because some current
models reject forced tool choice. Strict tool inputs constrain the response shape, and
the coordinator still requires exactly one complete, validated research-plan tool result
before collection. Provider refusals stop the request and are shown explicitly; there
is no automatic retry, prompt change, or model switch.
Allow up to 90 seconds for the planning request. The response is HTTP 202:

```json
{"run_id": "<32-character identifier>", "status": "queued", "status_url": "/investigations/<id>"}
```

Poll the status URL at least three seconds apart. Inspect `status` separately from
`assessment.conclusion`. `report` contains the team's Markdown result; it is also
available from `GET /investigations/{run_id}/report`.

Live pipeline records remain **background references**, not the synthetic observations
that populate the tutorial. A live `partial / not_assessable` result with references
means collection returned data but the requested empirical comparison lacks observations.
The UI shows retrieved reference/observation counts separately from criteria met.

## Clarifying a question

```json
{"prompt": "Focus on skin tissue.", "previous_investigation_id": "<completed run id>"}
```

The adapter appends the clarification to the parent's original researcher-authored
question. It does not put previous evidence, reports or assistant conclusions into
intent planning. The new question receives a new run and plan; earlier states remain
unchanged. Replies while a job is running are rejected. The combined question must
fit the team's 6,000-character bound; individual chat messages are limited to 4,000.

The UI keeps conversation messages in the Streamlit session. Canonical saved runs
contain the research question, plan and results, not a separate chatbot message log.
Starting a real question after a synthetic example uses fresh intent, not fixture data.

## Structured integrations

Teammates can call `POST /investigations` with the exact nested `Submission` described
in [the coordinator guide](../coordinator/README.md). It includes:

- `request.question`, `genes`, `disease`, and `mode`;
- explicit `requirements`, `comparisons`, optional versioned `pathway` membership,
  and bounded `max_revisions`;
- separate `observations` with provenance, study/subject/specimen/time IDs, biological
  scope, observed directions and declared comparison bases.

Import `coordinator.models` in Python, or generate types from `/openapi.json`. Do not
send the previous draft's bare `intent`, `criteria`, numerical-measurement or
`criteria_confirmed` payload. There is no current "Use these criteria" command:
proposed scope is displayed as assumptions under the team's planning semantics.

The model can propose a research plan, but cannot supply `criteria_met`, fabricate
observations, or certify mappings and comparison bases. Those scientific boundaries
are enforced and documented by the coordinator. Its current checks compare declared
directions and metadata; they are not statistical inference or independent biological
validation. See [coordinator/AGENTS.md](../coordinator/AGENTS.md).

## MCP and synthetic examples

`start_investigation(request)` accepts a canonical nested Submission with explicit
requirements and gene scope, or an explicit demo object. Free-text chat objects are
not accepted over MCP: the host assistant frames the criteria with its own model. `get_investigation(investigation_id)` returns the same
canonical state as HTTP.

```json
{"request": {"demo": "cross-context-conflict"}}
```

HTTP clients can send `{"demo":"cross-context-conflict"}` to `/demos`. The other
supported fixture is `missing-evidence`. The server serves cached results generated from the team’s examples and directory
evidence provider, without spawning a worker or consuming the public live allowance. Fixture selection is explicit and labeled; an ordinary
chat or structured request never triggers this fallback.

Website planning needs a visitor’s API key and explicit model ID in Model settings.
Explicit criteria and the two fixtures need no model credentials. See [MCP setup](mcp.md).
The standalone team coordinator retains its own environment-based configuration;
the combined frontend/MCP deployment uses visitor-funded planning only.

## Public entry

The website opens in the tutorial, not a login or key-entry screen. Website chat is
an explicit optional path; the MCP path uses Claude Code or the Claude app directly.
The combined hosted API is public and stores new runs separately from former team
runs. Live starts share a limited demo allowance; cached tutorials remain available.
See [MCP setup](mcp.md) and the deployment limits in [README](../README.md).
