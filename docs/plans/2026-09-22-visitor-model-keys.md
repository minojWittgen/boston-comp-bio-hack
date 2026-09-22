# Visitor-funded chat and model-free MCP

Approved direction: visitors enter their own model key in the frontend; the demo
owner must not pay for their model requests. Retain the shared access code for
hosting access, since Modal compute and evidence collection still cost the host.

## Implementation

- Add visible sidebar model settings: masked Anthropic API key, explicit model ID,
  and a clear-key action. Keep the key only in the current Streamlit session.
- Send the key/model in dedicated HTTP headers on `/chat` only. Use it for one
  bounded synchronous planning call; send only the validated plan to the background
  worker. Never put credentials in research contracts, saved runs, job arguments,
  logs, downloads, or process-wide environment variables.
- Do not fall back to a host model key. Integrated structured HTTP/MCP submissions
  require explicit criteria and use ExplicitPlanner. MCP hosts draft the criteria
  using their own model. Keep the existing tools and add a short connection guide.
- Preserve the canonical scientific schemas/checks. Extend the canonical API with
  an optional submission callback so adapter validation happens before job creation.
- Remove model-key requirements from the combined Modal deployment. Retain access
  authentication, bounded workers, persistent call IDs and reconciliation.

## Verification

Check missing/invalid credentials, absence of shared-key fallback, simultaneous
visitors with different keys, safe errors and artifacts, key-free MCP and synthetic
examples, frontend settings/clear behavior, and the coordinator/pipeline suites.
Verify deployment and actual HTTP/MCP transport separately; no paid model call
without a user-provided key. Document any unverified live-provider behavior.
