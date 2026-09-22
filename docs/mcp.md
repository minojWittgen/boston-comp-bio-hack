# Use CoMEA directly inside Claude

Our MCP server is hosted on Modal. Claude Code, a terminal MCP client, or the Claude
app can call it directly. The website is an optional tutorial/chat interface.

**You do not need an Anthropic API key or team access code for the hosted MCP.**
Claude uses its own model to frame your question; our tools run the evidence workflow.
Your Claude plan or client model usage still applies. The server makes no model calls.

## Claude Code / terminal

```bash
claude mcp add --transport http cross-context-biology https://minoj--xctx-research-api.modal.run/mcp/
claude mcp get cross-context-biology
```

Open Claude Code, inspect `/mcp`, and enable the tools when asked. If using this repo,
its `.mcp.json` already declares the connector; approve that project configuration
instead of adding a duplicate. No local Python server or pipeline installation is
needed to connect to the hosted service.

The command and transport follow the [official Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).
Other terminal clients can use the same Streamable HTTP URL with authentication unset.

## Claude app / Desktop / web

1. Open **Customize → Connectors → Add custom connector**.
2. Name it **CoMEA** and enter:

   ```text
   https://minoj--xctx-research-api.modal.run/mcp/
   ```

3. Add the connector with no authentication, then enable it in your conversation.
   Organization accounts may require an owner to add it first.

Claude documents [remote custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)
and supports [servers with no authentication](https://claude.com/docs/connectors/building/authentication).
Availability also depends on your client's account and organization settings.

## Start with the tutorial

Paste this into Claude:

> Use CoMEA (the cross-context-biology MCP tools) to run the synthetic cross-context-conflict tutorial.
> Call start_investigation, then get_investigation, and explain why a complete
> investigation can have conflicting evidence.

The tool arguments for the first call are:

```json
{"request": {"demo": "cross-context-conflict"}}
```

Pass the returned `run_id` as `investigation_id` to `get_investigation`. Expect
`complete / conflicting`. The `missing-evidence` tutorial returns
`partial / not_assessable`. These cached fixtures need no live collection, API key
or detached worker, and remain available after the public live allowance closes.
The same cases appear on the [website](https://minoj--xctx-research-web.modal.run).

## Investigate a real question

> Help investigate TYK2 RNA abundance across human cell cultures, mouse models and
> psoriasis patients. Propose explicit evidence requirements and clarify the scope
> with me before starting. Do not invent observations or validated comparison bases.
> Call start_investigation and then get_investigation to report evidence and gaps.

The tools advertise typed schemas:

- `start_investigation`: accepts `{request, observations}`. Supply explicit
  `request.requirements` and genes (or versioned pathway genes). The host assistant
  drafts these from the researcher's intent; it must not invent empirical observations.
- `get_investigation`: takes `investigation_id`; returns the frozen plan, evidence,
  checks, separate execution/conclusion values and Markdown report. For live jobs,
  poll at least three seconds apart until `complete`, `partial` or `failed`.

Real source packages remain background references. Missing observations stay gaps.
Current comparisons use declared observations, not new statistical inference or
clinical validation. Public run IDs grant access to results; use public data.

The hosted demo has a limited live investigation allowance because Modal/evidence
compute still costs the owner. See [deployment limits](../README.md). If exhausted,
use the tutorial or deploy the same server in your own workspace.

## Optional website chat

Choose **Investigate with your key** on the website only if you want the server to
frame free text for you. That path asks for your Anthropic API key and model ID.
The tutorial and MCP paths never require this separate model key.
