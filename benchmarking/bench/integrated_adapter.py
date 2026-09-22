"""PRIMARY suite — adapter that runs the ACTUAL integrated system end to end.

    task.md + corpus ──► data pipeline (real build_package/enrich/annotate over recorded responses)
                     ──► extraction/normalization (integration/extractor.py, model-assisted, provenance-linked)
                     ──► real Coordinator (planner → frozen plan → collection → checks → report)
                     ──► report envelope (mapped, never repaired)

Neither data_pipeline/ nor coordinator/ is modified. Every model call (planner + extractor) goes through
one UsageClient bound to the benchmark's Usage/deadline. `_system_internal` carries the RunState, plan
digest, extraction trace, replay log, model inventory and code versions.

Environment
  XCTX_PIPELINE      path to data_pipeline/evidence_pipeline   (default: ../data_pipeline/evidence_pipeline)
  XCTX_REPO_ROOT     repo root that contains coordinator/       (default: ../)
  ANTHROPIC_API_KEY, XCTX_MODEL (or ANTHROPIC_MODEL)           required for scored runs
  XCTX_FAKE_LLM=1    offline stand-in (calibration/smoke batches only; runner refuses it otherwise)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from common import ROOT, BudgetExceeded, Usage, import_pipeline
from primary_common import CorpusTools

REPO_ROOT = Path(os.environ.get("XCTX_REPO_ROOT", ROOT.parent)).resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

AXIS_BY_SHAPE = {("in_vitro", "in_vivo", False): "in_vitro_vs_animal",
                 ("in_vitro", "patient", False): "in_vitro_vs_patient_rna",
                 ("patient", "patient", True): "patient_rna_vs_patient_protein_within_person"}
CONCLUSION_MAP = {"supported": "supported", "conflicting": "opposed", "inconclusive": "insufficient_evidence", "not_assessable": "insufficient_evidence"}


def readiness() -> list[str]:
    """Problems that must be empty before a paid integrated run starts."""
    problems = []
    try:
        import_pipeline()
    except Exception as e:  # noqa: BLE001
        problems.append(f"data pipeline not importable: {e}")
    try:
        import coordinator.engine  # noqa: F401
        import coordinator.planner  # noqa: F401
    except Exception as e:  # noqa: BLE001
        problems.append(f"coordinator not importable from {REPO_ROOT}: {e}")
    if os.environ.get("XCTX_FAKE_LLM") != "1":
        if not os.environ.get("ANTHROPIC_API_KEY"): problems.append("ANTHROPIC_API_KEY unset")
        if not (os.environ.get("XCTX_MODEL") or os.environ.get("ANTHROPIC_MODEL")): problems.append("XCTX_MODEL/ANTHROPIC_MODEL unset")
    return problems


def _git_rev(path: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:  # noqa: BLE001
        return None


class FrozenPlanner:
    """Returns the plan already produced (and paid for) by the system's planner, so Coordinator.execute
    does not plan twice. The digest the coordinator freezes is the same plan."""
    def __init__(self, plan): self.plan_obj = plan
    def plan(self, request): return self.plan_obj


class IntegratedSystemAdapter:
    system = "integrated"

    def run(self, manifest: dict, case_dir: Path, run_idx: int) -> dict:
        from agents_primary import envelope
        model = os.environ.get("XCTX_MODEL") or os.environ.get("ANTHROPIC_MODEL") or "unknown"
        usage = Usage(model, manifest["limits"]); tools = CorpusTools(manifest, case_dir, usage)
        internal = {"stages": [], "versions": {"repo": _git_rev(REPO_ROOT), "data_pipeline": _git_rev(REPO_ROOT / "data_pipeline"), "coordinator": _git_rev(REPO_ROOT / "coordinator")},
                    "fake_llm": os.environ.get("XCTX_FAKE_LLM") == "1"}
        status, err, ans, client, limitations = "no_answer", None, None, None, []
        try:
            from coordinator.engine import Coordinator
            from coordinator.models import InvestigationRequest, Submission, PathwayDefinition
            from coordinator.planner import ClaudePlanner
            from coordinator.store import FileRunStore
            from integration.extractor import extract_observations
            from integration.llm import FakeAnthropic, UsageClient
            from integration.pipeline_provider import CorpusPipelineProvider

            client = UsageClient(usage, inner=FakeAnthropic() if internal["fake_llm"] else None)
            task = (case_dir / manifest["task_file"]).read_text()
            ents = manifest.get("entities", {}); genes = ents.get("genes", [])
            pathway = None
            pw_files = [f for f in manifest["permitted_files"] if f.startswith("pathways/")]
            if len(pw_files) == 1:
                import json as _j; pw = _j.loads(tools.read_file(pw_files[0])["content"])
                pathway = PathwayDefinition(id=pw["id"], source=pw["source"], version=pw["version"], genes=pw["genes"])
            elif len(pw_files) > 1:
                limitations.append(f"coordinator request accepts a single pathway definition; {len(pw_files)} supplied — pathway-level scope not routed (handoff §5)")
            # -- stage 1: intent → frozen plan (the system's own planner; one model call)
            request = InvestigationRequest(question=task[:6000], genes=genes, disease="", mode="eval", pathway=pathway, max_revisions=1)
            plan = ClaudePlanner(model=model, client=client).plan(request)
            internal["stages"].append({"stage": "plan", "requirements": len(plan.requirements), "comparisons": len(plan.comparisons)})
            # -- stage 2: collection — REAL data pipeline over recorded responses
            provider = CorpusPipelineProvider(case_dir / manifest["corpus_root"])
            packages = {}
            for g in plan.genes:
                usage.check_deadline()
                try: packages[g] = provider.fetch(g, plan.disease, request.mode, "precollect")
                except Exception as e: internal["stages"].append({"stage": "collect", "gene": g, "error": repr(e)[:200]})  # noqa: BLE001
            internal["stages"].append({"stage": "collect", "genes": sorted(packages), "replayed_requests": len([r for r in provider.replay.log if r["replayed"]]), "unrecorded": [r["url"] for r in provider.replay.log if not r["replayed"]]})
            # -- stage 3: extraction + normalization (the system's own; model-assisted)
            observations, xtrace = extract_observations(tools, plan, packages, client, model)
            internal["stages"].append({"stage": "extract", "records": len(observations), "trace": xtrace})
            # -- stage 4: real coordinator run (plan frozen; collection via the same provider; checks; report)
            store = FileRunStore(tempfile.mkdtemp(prefix="xctx-coord-"))
            coord = Coordinator(FrozenPlanner(plan), provider, store, budget_seconds=max(1.0, usage.remaining_seconds()))
            sub = Submission(request=request, observations=observations)
            state = coord.execute(coord.create(sub).run_id, sub)
            usage.check_deadline()
            internal["run_state"] = state.model_dump(mode="json"); internal["plan_sha256"] = state.plan_sha256
            internal["stages"].append({"stage": "coordinate", "status": state.status, "conclusion": state.assessment.conclusion if state.assessment else None, "attempts": state.attempts})
            # -- stage 5: map to the public envelope (no repair)
            ans = _map(state, plan, limitations); status = "completed" if state.status in ("complete", "partial") else "error"
            if state.status == "failed": err = state.error
        except BudgetExceeded as e:
            status, err = e.kind, str(e)
        except Exception as e:  # noqa: BLE001
            status, err = "error", repr(e)[:500]
        internal["model_inventory"] = list(client.model_inventory) if client is not None else []
        out = envelope(manifest, self.system, status, ans, tools, usage, err, limitations)
        out["_system_internal"].update(internal)
        return out


def _map(state, plan, limitations: list[str]) -> dict:
    reqs = {r.id: r for r in plan.requirements}
    recs = {r.id: r for r in (state.evidence.records if state.evidence else [])}
    multi = len(plan.genes) > 1 or plan.pathway is not None
    comps = []
    for c in state.assessment.comparisons:
        spec = next(s for s in plan.comparisons if s.id == c.id); L, R = reqs[spec.left], reqs[spec.right]
        axis = AXIS_BY_SHAPE.get((L.context, R.context, spec.require_matched_subjects), c.id)
        cid = f"{axis}:{L.entity}" if multi and axis != c.id else axis
        cites = []
        for eid in c.evidence_ids:
            for p in getattr(recs.get(eid), "provenance", []):
                if p.startswith("corpus://") and "#" in p:
                    f, loc = p[len("corpus://"):].split("#", 1); cites.append({"file": f, "locator": loc})
        seen = set(); cites = [x for x in cites if not (tuple(x.items()) in seen or seen.add(tuple(x.items())))]
        # keep at least one citation per distinct file, then the first per-record locators, up to 40
        by_file = {}; [by_file.setdefault(x["file"], x) for x in cites]
        cites = list(by_file.values()) + [x for x in cites if x not in by_file.values()]
        comps.append({"comparison_id": cid, "scope": {"species": sorted({L.species, R.species}), "context": sorted({L.context, R.context}), "modality": sorted({L.modality.lower(), R.modality.lower()})},
                      "conclusion": CONCLUSION_MAP[c.conclusion], "statement": c.detail[:1500], "citations": cites[:40],
                      "within_person": (c.conclusion in ("supported", "conflicting")) if spec.require_matched_subjects else None})
    gaps = [f"{g.code}: {g.detail}" for g in (state.evidence.gaps if state.evidence else []) + state.assessment.gaps]
    return {"comparisons": comps, "limitations": limitations + [f"coordinator execution status: {state.status}"] + [g for g in gaps if g.startswith(("declared_metadata", "descriptive_only"))],
            "unresolved": [g for g in gaps if not g.startswith(("declared_metadata", "descriptive_only"))],
            "report_markdown": (state.report or "")[:60000]}
