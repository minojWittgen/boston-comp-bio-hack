# Research chat and the internal investigation contract

The user writes a research question, not JSON. The frontend sends the question to
`POST /chat`; a background worker uses Claude through the Anthropic SDK to extract
the intent, genes, disease and next feasible step. Modal hosts the service and
workers; it does not host Claude model weights. The Streamlit app has no model key
or independent research loop.

## From message to investigation

```text
Research message → Claude intake → validated internal request
                               ├─ missing intent → conversational clarification
                               ├─ gene question → background exploration + explicit gaps
                               └─ complete comparison rules → readable proposed criteria
                                                              ↓ researcher confirmation
                                          frozen contract → coordinator → checked report
```

Each message starts a new background job and returns an ID immediately. A reply
includes the previous job ID so the backend can retain the conversation and draft.
Previous runs remain unchanged. Intake drafts have `contract_hash: null`; a SHA-256
hash is assigned only when execution inputs have been assembled and frozen.

Example initial request:

```json
{
  "prompt": "What evidence connects TYK2 to psoriasis across cell experiments, animal models and patients?"
}
```

Example follow-up:

```json
{
  "prompt": "Focus on protein abundance in skin.",
  "previous_investigation_id": "<id returned by the previous request>"
}
```

Poll `GET /investigations/{id}` every three seconds. The `chat.messages` array contains
the conversation, `chat.reply` the latest assistant message, and the existing
`report`, `reference_packages`, `events`, and `usage` fields contain the research
result. The API rejects replies while the parent is still running. Conversations
are limited to 20 input/history messages and 24,000 characters before starting a
new conversation; each user prompt is limited to 4,000 characters.

The same MCP tool accepts either this prompt object or the full structured request:

```json
{"request": {"prompt": "Investigate TYK2 and psoriasis across biological contexts"}}
```

`start_investigation` returns the ID; `get_investigation` returns the same state
that the frontend reads. This remains a two-tool MCP adapter.

## What the contract contains

`coordinator/models.py` defines the authoritative, validated schema.

| Field | Meaning |
| --- | --- |
| `intent` | Research question framed from the conversation |
| `phase` | `exploration` for background evidence, or `validation` for numerical comparisons |
| `genes`, `disease` | Scope of reference retrieval; at most three gene symbols |
| `criteria` | Explicit study/context/species/tissue, feature, assay quantity/modalities, comparison conditions and times, expected direction, minimum effect, minimum biological pairs, confidence level, pairing rule and rationale |
| `criteria_confirmed` | Whether the researcher has approved the displayed comparison rules |
| `observations` | Source-linked processed measurements with context, measured/host species, assay/unit, subject, specimen and time identifiers |
| `species_mappings` | Declared orthology and review status |
| `available_sample_maps` | Declared metadata sources for recovering missing sample identity |
| `reference_packages` | Background packages supplied by a caller |
| `retrieve_reference`, `reference_required` | Retrieval choice and dependency status |
| `budget` | Wall-time, tool-call, model-call, output-token and total-token limits |

A gene-centered prompt can begin **exploration** immediately. All three scientific
contexts remain visible as `not_assessable` without suitable study comparisons.
The overall research result remains `partial` even when background collection
succeeds. Reference-source failures are preserved; required technical failures
produce failed execution, never a biological negative.

For **validation**, the intake model can propose complete rules from choices in the
conversation, but it cannot set authorization or generate observations. The server
renders the rules in ordinary language, including thresholds and the paired t
interval method. The exact reply **Use these criteria** confirms that pending draft
in a new run. Any other reply returns to intake. No criteria are silently changed
once execution begins. Missing choices are asked about in the conversation.

The current chat intake does not ingest measurement files. Teammates supply real
processed measurements, mappings and full comparison contracts through the
existing `POST /investigations` integration. Chat history is not a source of assay
values. Broad dataset discovery and raw-data processing remain separate adapters;
the gene pipeline is only background retrieval. See [coordinator.md](coordinator.md)
for the implemented numerical method and full scientific limitations.

## Model and demo behavior

Claude is called for conversational intake, optionally for choosing among eligible
tools, and for explaining the checked report. These calls share one per-run token
and call budget. The model cannot change computed statuses or cite unknown evidence
IDs. Free-text explanations still require scientific review.

The sidebar's **Try synthetic investigation** sends `demo: true`. The backend loads
the versioned fixture and preset criteria, performs real numerical calculations on
fabricated measurements, and labels the result synthetic. This works in explicit
local model-disabled mode without pretending an LLM was called. Ordinary chat in
that mode reports that the Claude connection is disabled. A demo cannot be mixed
into an existing conversation; start a new conversation first.

For live chat, the deployed `xctx-research-secrets` Modal secret needs
`ANTHROPIC_API_KEY` and `INVESTIGATION_API_TOKEN`. The latter protects both API/MCP
and the hosted frontend. Never commit their values. The local generated access code
is in the ignored `.env.demo` file when provisioned by the deployment operator.
