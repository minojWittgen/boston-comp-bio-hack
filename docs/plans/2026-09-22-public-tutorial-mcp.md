# Public tutorial and direct Claude MCP access

The user wants an open first visit with three choices: tutorial without credentials,
optional website chat using their own Anthropic key, and the full remote MCP workflow
inside Claude Code or the Claude app. The former access-code landing screen is removed.

- Default to the tutorial and preserve the existing evidence/plan/report presentation.
  Cache both labeled synthetic cases locally; browsing them needs neither API access,
  model credentials, live collection nor a background worker.
- Show model settings only in the website-chat path. Preserve request-scoped visitor
  keys, no owner-key fallback, clear-key behavior and unchanged scientific schemas.
- Publish the remote MCP endpoint without authentication so supported Claude clients
  can connect directly. Add exact Claude Code and Claude app instructions and a
  credential-free project `.mcp.json` configuration.
- Use a separate public run-store namespace, leaving former team runs inaccessible
  from the public endpoint. Public run IDs grant access to their results; no sensitive
  data should be submitted to this prototype.
- Limit cloud live starts to 12 total by default, persisted in a separate Modal Dict
  with atomic slot reservation. It does not reset on redeployment or a
  new day. The allowance ends at 2026-09-29 00:00 UTC, before the first Dict
  reservation could expire after seven inactive days. The owner may explicitly
  extend the limit/window; tutorials remain available indefinitely. Tutorials bypass
  this limit and run from fixtures. Keep worker timeouts and reduce idle retention.
  This bounds investigation starts, not all hosting costs from public HTTP traffic.
- Verify public entry with an old token still present, tutorials with no backend,
  optional key gating only for live chat, quota concurrency and persistence, old-run
  separation, anonymous MCP tools, native Claude Code connectivity and deployment.
