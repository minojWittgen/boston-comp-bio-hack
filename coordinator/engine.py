"""Criterion-driven coordinator shared by every interface. No UI or transport logic."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime, timezone
from importlib.metadata import version
import platform
import time

from coordinator.checks import assess
from coordinator.models import CONTEXTS, InvestigationRequest, Observation
from research_app.evidence import validate_package


def now():
    return datetime.now(timezone.utc).isoformat()


def initial_state(run_id: str, request: InvestigationRequest) -> dict:
    return {"schema_version": "1.0", "id": run_id, "status": "queued", "stage": "queued",
            "created_at": now(), "updated_at": now(), "contract_hash": request.digest(),
            "request": request.model_dump(mode="json"), "events": [], "reference_packages": [],
            "software": {"python": platform.python_version(), **{name: version(name) for name in
                         ("scipy", "pydantic", "anthropic", "mcp", "modal")}},
            "report": None, "errors": [], "usage": {"tool_calls": 0, "model_calls": 0,
                                                     "input_tokens": 0, "output_tokens": 0}}


def validate_interpretation(value, findings, packages=()):
    expected = {f["criterion_id"]: f for f in findings}
    items = value.get("interpretations")
    if not isinstance(value.get("summary"), str) or not isinstance(items, list):
        raise ValueError("Invalid model interpretation schema.")
    if len(items) != len(expected) or {x.get("criterion_id") for x in items} != set(expected):
        raise ValueError("Model interpretation omitted or duplicated criteria.")
    for item in items:
        source = expected[item["criterion_id"]]
        if item.get("finding") != source["finding"]:
            raise ValueError("Model attempted to change a checked finding.")
        if not isinstance(item.get("explanation"), str) or not isinstance(item.get("evidence_ids"), list):
            raise ValueError("Invalid evidence explanation.")
        if not set(item["evidence_ids"]).issubset(source["evidence_ids"]):
            raise ValueError("Model cited evidence outside the checked comparison.")
        if source["calculations"] and not item["evidence_ids"]:
            raise ValueError("Interpretation of a calculated finding must cite evidence.")
    allowed_refs = {(p["run"]["run_id"], source) for p in packages for source in ["mygene", *p["sources"]]}
    for note in value.get("reference_notes", []):
        if (note.get("package_run_id"), note.get("source")) not in allowed_refs:
            raise ValueError("Model cited a reference source that was not retrieved.")
    return value


async def execute(state: dict, save, provider, reasoner=None) -> dict:
    request = InvestigationRequest.model_validate(state["request"])
    frozen_hash = request.digest()
    started = time.monotonic()
    observations = list(request.observations)
    findings = []
    attempted = set()
    reference_failures = []

    async def checkpoint(stage, action, detail, **extra):
        state.update(stage=stage, updated_at=now())
        state["events"].append({"at": now(), "stage": stage, "action": action, "detail": detail, **extra})
        if reasoner:
            state["usage"].update(model_calls=reasoner.calls, **reasoner.usage)
        await save(copy.deepcopy(state))

    def evaluate():
        return [assess(c, observations, request.species_mappings) for c in request.criteria]

    async def collect(gene):
        state["usage"]["tool_calls"] += 1
        await checkpoint("collecting", "retrieve_reference", f"Retrieve background evidence for {gene}", gene=gene)
        try:
            pkg = await provider.fetch(gene, request.disease, state["id"])
            validate_package(pkg)
            state["reference_packages"].append(pkg)
            unavailable = [m for m in pkg["missing"] if m["status"] in ("error", "skipped")]
            if pkg["gene"]["status"] == "error":
                unavailable.append({"source": "mygene", "status": "error"})
            if unavailable:
                reference_failures.extend(unavailable)
            await checkpoint("collecting", "reference_received", "Package read; retrieved records are background evidence, not assay comparisons.",
                             gene=gene, missing=pkg["missing"])
        except Exception as exc:
            reference_failures.append({"gene": gene, "status": "error", "reason": str(exc)[:500]})
            await checkpoint("collecting", "tool_error", str(exc)[:500], gene=gene)

    async def workflow():
        nonlocal findings, observations
        state["status"] = "running"
        await checkpoint("criteria", "contract_recorded", "Inputs and scientific rules recorded before execution.", contract_hash=frozen_hash)
        if request.phase == "validation" and (not request.criteria or not request.criteria_confirmed):
            state["status"] = "needs_input"
            state["report"] = {"execution_status": "needs_input", "required_input":
                "Supply and confirm criteria: study/context/species, assay meaning, paired comparison, biological replicates, thresholds and confidence level. Resubmit as a new investigation.",
                "contexts": {c: {"finding": "not_assessable", "reason": "Scientific comparison rules have not been confirmed."} for c in CONTEXTS}}
            await checkpoint("criteria", "confirmation_required", "No scientific thresholds were invented and no analysis was started.")
            return
        findings = evaluate()
        await checkpoint("feasibility", "check_inputs", "Checked availability, sample identity, assay compatibility and species mappings.",
                         unmet=[{"criterion_id": f["criterion_id"], "checks": f["checks"]} for f in findings if f["finding"] == "not_assessable"])
        for pkg in request.reference_packages:
            state["reference_packages"].append(validate_package(pkg))
        actions = [{"id": f"reference:{g}", "type": "reference", "gene": g,
                    "reason": "Retrieve available background evidence; does not substitute for missing assays."}
                   for g in request.genes if request.retrieve_reference]
        while True:
            gaps = [{"criterion_id": f["criterion_id"], "checks": f["checks"]} for f in findings if f["finding"] == "not_assessable"]
            missing_ids = {o.id for o in observations if not o.subject_id or not o.specimen_id or not o.timepoint}
            recoveries = [{"id": f"sample_map:{m.id}", "type": "sample_map", "map_id": m.id,
                           "reason": "Recover missing subject/specimen/time metadata from a declared source."}
                          for m in request.available_sample_maps if any(e.observation_id in missing_ids for e in m.entries)]
            eligible = [a for a in [*recoveries, *actions] if a["id"] not in attempted]
            if not eligible or state["usage"]["tool_calls"] >= request.budget.max_tool_calls:
                break
            chosen = eligible[0]
            reason = chosen["reason"]
            # Reserve one model call for interpretation. Only eligible actions may be selected.
            if reasoner and len(eligible) > 1 and reasoner.calls < request.budget.max_model_calls - 1:
                try:
                    decision = await reasoner.choose(request.intent, eligible, gaps)
                    chosen = next(a for a in eligible if a["id"] == decision["action_id"])
                    reason = decision["reason"]
                except Exception as exc:
                    await checkpoint("planning", "planner_fallback", f"Using the first eligible action after model selection failed: {str(exc)[:300]}")
            attempted.add(chosen["id"])
            await checkpoint("planning", "select_tool", reason, selection=chosen)
            if chosen["type"] == "reference":
                await collect(chosen["gene"])
            else:
                state["usage"]["tool_calls"] += 1
                sample_map = next(m for m in request.available_sample_maps if m.id == chosen["map_id"])
                entries = {}
                for e in sample_map.entries:
                    if e.observation_id in entries:
                        raise ValueError("Sample map contains duplicate observation identifiers.")
                    entries[e.observation_id] = e
                updated = []
                for o in observations:
                    entry = entries.get(o.id)
                    fields = o.model_dump()
                    if entry:
                        for key in ("subject_id", "specimen_id", "timepoint"):
                            if fields[key] and fields[key] != getattr(entry, key):
                                raise ValueError("Sample map conflicts with existing identity; criteria or data must not be silently changed.")
                            fields[key] = fields[key] or getattr(entry, key)
                    updated.append(Observation.model_validate(fields))
                observations = updated
                await checkpoint("follow_up", "read_sample_map", "Applied declared metadata without changing existing IDs or measurements.",
                                 map_id=sample_map.id, source=sample_map.source)
            findings = evaluate()
            await checkpoint("checking", "recheck_criteria", "Rechecked the same frozen criteria after tool execution.",
                             findings=[{"id": f["criterion_id"], "finding": f["finding"]} for f in findings])
        await checkpoint("comparison", "numerical_checks", "Calculated paired subject-level contrasts; preserved individual results and all contexts.")
        state["report"] = make_report(request, findings, observations, reference_failures)
        if request.phase == "exploration":
            state["report"]["next_steps"] = [
                "Provide study measurements and define the comparison, biological replicates, effect threshold and confidence level before numerical validation.",
                "Keep in vitro, in vivo and patient evidence separate, with measured species, assay meaning and sample identity preserved."]
        remaining_reference = request.retrieve_reference and any(f"reference:{g}" not in attempted for g in request.genes)
        if request.reference_required and (reference_failures or remaining_reference or not state["reference_packages"]):
            state["report"]["execution_status"] = "failed" if any(f.get("status") == "error" for f in reference_failures) else "partial"
        if reasoner:
            try:
                interpretation = await reasoner.interpret(request.intent, findings, state["reference_packages"])
                state["report"]["interpretation"] = validate_interpretation(interpretation, findings, state["reference_packages"])
                state["report"]["interpretation_status"] = "generated; criterion statuses and evidence IDs checked; prose needs scientific review"
            except Exception as exc:
                state["report"]["interpretation_status"] = "unavailable"
                if state["report"]["execution_status"] != "failed":
                    state["report"]["execution_status"] = "partial"
                state["errors"].append({"stage": "interpretation", "reason": str(exc)[:500]})
        else:
            state["report"]["interpretation_status"] = "disabled; numerical workflow only"
        if request.digest() != frozen_hash:
            raise RuntimeError("Scientific contract changed during execution.")
        state["status"] = state["report"]["execution_status"]
        await checkpoint("finished", "final_checks", "Checked frozen contract, required comparisons, source dependencies, and terminal execution status.")

    try:
        async with asyncio.timeout(request.budget.max_seconds):
            await workflow()
    except TimeoutError:
        state["status"] = "partial"
        state["report"] = make_report(request, findings, observations, reference_failures)
        state["report"]["execution_status"] = "partial"
        state["errors"].append({"stage": state["stage"], "reason": "Execution time limit reached; unfinished work is not a biological negative."})
    except Exception as exc:
        state["status"] = "failed"
        state["report"] = make_report(request, findings, observations, reference_failures)
        state["report"]["execution_status"] = "failed"
        state["errors"].append({"stage": state["stage"], "reason": str(exc)[:1000]})
    state["elapsed_seconds"] = round(time.monotonic() - started, 3)
    await checkpoint("finished" if state["status"] != "needs_input" else "criteria", "stopped", state["status"])
    return state


def make_report(request, findings, observations, reference_failures):
    contexts = {}
    for context in CONTEXTS:
        relevant = [f for f in findings if f["context"] == context]
        statuses = {f["finding"] for f in relevant}
        finding = ("not_assessable" if not relevant or "not_assessable" in statuses else
                   "conflicting" if "conflicting" in statuses else
                   "inconclusive" if "inconclusive" in statuses else "supported")
        contexts[context] = {"finding": finding, "criterion_ids": [f["criterion_id"] for f in relevant],
                             "reason": "See individual criteria; raw assay units were not pooled." if relevant else "No criterion or completed analysis for this required context."}
    missing_contexts = [c for c in CONTEXTS if not any(f["context"] == c for f in findings)]
    unresolved = [f["criterion_id"] for f in findings if f["required"] and f["finding"] == "not_assessable"]
    studies = sorted({f["study_id"] for f in findings if f["calculations"]})
    return {"execution_status": "partial" if missing_contexts or unresolved else "complete",
            "intent": request.intent, "phase": request.phase, "contract_hash": request.digest(), "contexts": contexts,
            "criteria": findings, "unmet_required_criteria": unresolved, "missing_contexts": missing_contexts,
            "independent_study_ids": studies, "reference_failures": reference_failures,
            "origins": sorted({o.origin for o in observations}),
            "observations": [o.model_dump(mode="json") for o in observations],
            "species_mappings": [m.model_dump(mode="json") for m in request.species_mappings],
            "limitations": ["Only paired positive processed abundance/activity measurements are implemented in this adapter.",
                            "Student t intervals assume independent subjects and approximately normal log2 ratios; assumptions need researcher review.",
                            "Small samples and unadjusted multiple comparisons do not establish population-level validation.",
                            "Reference database records are background; repeated portals or criteria do not create independent replications.",
                            "No causal, clinical efficacy, or calibrated translation-probability claim is made."]}
