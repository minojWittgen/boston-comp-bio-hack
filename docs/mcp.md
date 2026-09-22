# Use Cross-context through MCP

Cross-context exposes the research workflow to an existing assistant. Your assistant
frames the research question into explicit criteria; the server collects background
evidence, checks declared observations, and returns a report with provenance and gaps.

**No separate Anthropic API key is needed for these MCP tools.** The server does not
call a model through MCP. Your assistant's own subscription or model usage charges
still apply. Hosting and evidence collection also have costs for the deployment owner,
so the hosted server retains its team access code.

## Connect

Use a client that supports **Streamable HTTP**, custom MCP servers and bearer tokens.
The connection URL is the deployed API URL followed by `/mcp/`; the website's MCP
introduction shows the exact URL. For local development use:

```text
http://127.0.0.1:8000/mcp/
```

If the service requires a team access code, configure the header:

```text
Authorization: Bearer <team-access-code>
```

This access code is not a model API key. Keep credentials out of prompts and tool
arguments. Clients that require OAuth instead of bearer tokens need an OAuth adapter;
this prototype does not provide one. A remote client cannot reach your localhost URL.

## Ask your assistant

> Help investigate TYK2 RNA abundance across human cell cultures, mouse models and
> psoriasis patients. Propose explicit evidence requirements and clarify the scope
> with me before starting. Do not invent observations or validated comparison bases.
> Call start_investigation and then get_investigation to report evidence and gaps.

The server advertises two tools with typed schemas:

- `start_investigation`: accepts a canonical `{request, observations}` Submission.
  `request.requirements` and genes (or versioned pathway genes) are required for
  model-free planning. The host assistant creates this structure from the user's intent.
- `get_investigation`: accepts `investigation_id` and returns the canonical state,
  frozen plan, evidence, checks, separate execution/conclusion values and Markdown report.
  Poll at least three seconds apart until `complete`, `partial` or `failed`.

Start a labeled, synthetic demonstration without source retrieval or any model call:

```json
{"request": {"demo": "cross-context-conflict"}}
```

Use that as the arguments for `start_investigation`; pass its `run_id` as
`investigation_id` to `get_investigation`. Expect execution `complete` and evidence
conclusion `conflicting`. The other fixture is `missing-evidence`.

For real requests, source packages are background references, not experimental
measurements. Missing observations remain gaps. The current server compares supplied,
declared observations; it does not fabricate them or establish clinical efficacy.

## Website chat

The website is an alternative interface. It needs the visitor's Anthropic API key and
model ID because the server performs one bounded planning call on that visitor's behalf.
Enter these in **Model settings**, not in chat. No owner model key is used as fallback.
The resulting research engine and reports are the same as those used by MCP.
