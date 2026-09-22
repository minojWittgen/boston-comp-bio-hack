# Chat input and the team's investigation contract

The user writes a question. `POST /chat` wraps it in the team's canonical
`Submission(request=InvestigationRequest(question=...))`. The coordinator's
`AutoPlanner` selects `ClaudePlanner` for natural language, freezes the resulting
`ResearchPlan` before collection, and performs its own evidence checks. No second
intake model or scientific schema is maintained by the frontend.

```json
{"prompt": "Compare TYK2 RNA abundance in human cell cultures, mouse models and psoriasis patients."}
```

The response is HTTP 202:

```json
{"run_id": "<32-character identifier>", "status": "queued", "status_url": "/investigations/<id>"}
```

Poll the status URL at least three seconds apart. Inspect `status` separately from
`assessment.conclusion`. `report` contains the team's Markdown result; it is also
available from `GET /investigations/{run_id}/report`.

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

`start_investigation(request)` accepts a canonical nested Submission, a chat object,
or an explicit demo object. `get_investigation(investigation_id)` returns the same
canonical state as HTTP.

```json
{"request": {"demo": "cross-context-conflict"}}
```

HTTP clients can send `{"demo":"cross-context-conflict"}` to `/demos`. The other
supported fixture is `missing-evidence`. The server loads the team's examples and uses
its directory evidence provider. Fixture selection is explicit and labeled; an ordinary
chat or structured request never triggers this fallback.

Natural planning needs both `ANTHROPIC_API_KEY` and an explicitly configured
`ANTHROPIC_MODEL`. Explicit criteria and the two fixtures need no model credentials.
