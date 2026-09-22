# Coordinator implementation

The frontend/backend branch now uses the team's implementation from
`codex/investigation-coordinator`; it replaces this branch's earlier draft engine.

- [Canonical coordinator behavior, schema and scientific limits](../coordinator/README.md)
- [Shared-module handoff rules](../coordinator/AGENTS.md)
- [Frontend/backend integration and verification](frontend-integration.md)
- [Chat-to-Submission contract](chat-and-contract.md)

The authoritative schema is `coordinator/models.py`. Submit a nested `Submission`
containing `request` and optional `observations`; consume a `RunState` with `plan`,
`evidence`, `assessment`, `events`, and a Markdown `report`. The implementation checks
declared observation coverage and comparability. It does not perform the superseded
draft's paired numerical t-interval workflow.
