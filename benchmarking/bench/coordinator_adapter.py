"""Configuration C — adapter for the team's ACTUAL coordinator (codex/investigation-coordinator).

Integration contract (from the 2026-09-22 review). Owner: coordinator integration.

  1. Invoke `Coordinator.create(...)` / `Coordinator.execute(...)` — never the B scaffold.
  2. Supply an `EvidenceProvider` backed by this benchmark's ToolBox so that:
       - the FIRST fetch returns the same initial package + datasets every other configuration received
         (`ToolBox.initial_inputs()`), and
       - any follow-up fetch goes through `ToolBox.fetch_dataset` / `ToolBox.build_evidence_package`
         (the simulated retrieval tools), NOT ModalEvidenceProvider or live APIs.
  3. Feed numeric context observations through `Submission.observations`; reference-package facts are background.
  4. Map the coordinator's result faithfully: `complete` is not `persists`; `inconclusive` is not
     `partially_persists`. Produce per-axis verdicts + explicit uncertainty in agent_output.schema.json.
  5. Inject the manifest's limits (cumulative output tokens, per-call max, deadline) into the planner and
     capture its usage into `Usage` (ClaudePlanner currently uses a 6,000-token per-call max and discards usage).
     If ExplicitPlanner is used, report it as a deterministic workflow with zero planner LLM calls.
  6. Record the coordinator commit hash and the frozen criteria/assessment in the trace (`_coordinator`).

Until this is implemented, `run()` raises so no C score can be produced by accident.
"""
from __future__ import annotations

import os
from pathlib import Path

from common import ToolBox, Usage


class CoordinatorAdapter:
    config = "C"

    def __init__(self):
        self.commit = os.environ.get("XCTX_COORDINATOR_COMMIT")  # record the pinned coordinator commit

    def run(self, manifest: dict, manifest_path: Path, run_idx: int) -> dict:
        usage = Usage(os.environ.get("XCTX_MODEL", "unknown"), manifest["limits"])
        tb = ToolBox(manifest, manifest_path, usage)
        # provider = BenchmarkEvidenceProvider(tb)      # first fetch → tb.initial_inputs(); retries → tb.fetch_dataset / tb.build_evidence_package
        # coord = Coordinator.create(planner=..., provider=provider, limits=manifest["limits"], usage_sink=usage)
        # result = coord.execute(Submission(claim=manifest["task"], observations=<normalized datasets>))
        # return build_output(manifest, "C", run_idx, "completed", map_result(result), tb, usage, None) | {"_coordinator": {...}}
        raise NotImplementedError("Configuration C: implement the coordinator adapter per the contract in this file's docstring.")
