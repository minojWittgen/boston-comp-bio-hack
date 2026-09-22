"""PRIMARY suite — adapter for the team's ACTUAL integrated system (collector/extractor → normalization → coordinator).

Contract (updated review, 'Primary evaluation'):

  * Input boundary is the SAME as the baseline's: task.md + the permitted corpus files, reached through
    `primary_common.CorpusTools` (or an EvidenceProvider that can only read those files). Do NOT hand the
    system pre-extracted observations, an EvidenceRecord list, a checklist, or anything the baseline did not get.
  * The system performs its own extraction, structuring, comparison and interpretation. If the integrated
    extraction path does not exist yet, DO NOT fill the gap with hand-authored observations — run the
    secondary suite instead and say so (README: readiness condition).
  * Whole-run measurement: every model call in every stage (collector, extractor, planner, checker, reviser)
    must be added to the shared `Usage` (usage.add_llm(resp.usage)) with its model id; if stages use different
    models, record the full inventory in `_system_internal.model_inventory`.
  * Output: map the system's final report into schema/report.schema.json WITHOUT repairing it or adding
    evidence. `complete` is not `supported`; `inconclusive` is `insufficient_evidence` only if the system said so.
  * Record the coordinator/pipeline commit hashes in `_system_internal.versions`.

Until implemented, `run()` raises so no 'integrated' score can be produced by accident.
"""
from __future__ import annotations

import os
from pathlib import Path

from common import Usage
from primary_common import CorpusTools


class IntegratedSystemAdapter:
    system = "integrated"

    def __init__(self):
        self.versions = {"coordinator": os.environ.get("XCTX_COORDINATOR_COMMIT"), "data_pipeline": os.environ.get("XCTX_PIPELINE_COMMIT")}

    def run(self, manifest: dict, case_dir: Path, run_idx: int) -> dict:
        usage = Usage(os.environ.get("XCTX_MODEL", "unknown"), manifest["limits"])
        tools = CorpusTools(manifest, case_dir, usage)
        # provider = CorpusEvidenceProvider(tools)                       # reads ONLY permitted corpus files
        # extracted = Collector(provider, usage_sink=usage).extract(task=(case_dir / manifest["task_file"]).read_text())
        # coord = Coordinator.create(planner=..., limits=manifest["limits"], usage_sink=usage)
        # result = coord.execute(Submission(question=..., observations=extracted))
        # return envelope(manifest, "integrated", "completed", map_report(result), tools, usage, None)
        raise NotImplementedError("Integrated system adapter not implemented — see docstring. Do not substitute hand-authored observations.")
