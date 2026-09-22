"""Agent configurations (v2, post-review).

  A0  no-tool baseline      : same model, same instructions + checklist (prose), no tools, one submit.
  A   tool baseline          : A0 + read_file / fetch_dataset / build_evidence_package.
  B   enforced checklist     : A + update_criteria ledger whose entries are VERIFIED against evidence ids and
                               recorded actions before submit_answer is accepted. This is a scaffold experiment.
                               It is NOT the team's coordinator and must never be reported as its score.
  C   coordinator adapter    : bench/coordinator_adapter.py — invokes Coordinator.create/execute through an
                               EvidenceProvider backed by this ToolBox. Registered here; raises until implemented.
  mock / mock-careless       : deterministic, no LLM; harness + grader checks only.

All LLM configurations share one scaffold, one system prompt, one budget, one deadline.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from common import AXES, STATUS_INTERP, TOOL_SPECS, VERDICTS, BudgetExceeded, ToolBox, Usage

MODEL = os.environ.get("XCTX_MODEL", "claude-sonnet-4-5")

AXIS_SCHEMA = {"type": "object", "required": ["axis_id", "verdict", "evidence", "contrast_alignment", "note"],
               "properties": {"axis_id": {"type": "string", "enum": list(AXES)}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                              "evidence": {"type": "array", "items": {"type": "string"}},
                              "contrast_alignment": {"type": ["string", "null"]}, "note": {"type": "string"}}}
SUBMIT_SPEC = {
    "name": "submit_answer", "description": "Submit the final per-axis and overall verdicts. Call once.",
    "input_schema": {"type": "object", "required": ["overall", "axes", "evidence_cited", "status_interpretation", "caveats"],
                     "properties": {
                         "overall": {"type": "object", "required": ["verdict", "rationale"],
                                     "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)}, "confidence": {"type": "number"}, "rationale": {"type": "string"}}},
                         "axes": {"type": "array", "items": AXIS_SCHEMA},
                         "evidence_cited": {"type": "array", "items": {"type": "object", "required": ["source", "locator", "supports"],
                                                                        "properties": {"source": {"type": "string"}, "locator": {"type": "string"},
                                                                                       "supports": {"type": "string", "enum": ["claim", "against_claim", "comparability_check", "background"]}}}},
                         "status_interpretation": {"type": "object", "additionalProperties": {"type": "string", "enum": list(STATUS_INTERP)}},
                         "caveats": {"type": "array", "items": {"type": "string"}}}}}

# ---- B's verifiable ledger (§2). Each criterion says what evidence can satisfy it and when N/A is legitimate.
CRITERIA = {
    "in_vitro_read":            {"text": "Origin in-vitro observation read.",                      "from_context": ["in_vitro"], "na_if_missing_context": "in_vitro"},
    "in_vivo_read":             {"text": "In-vivo observation read (fetch_dataset if unavailable).", "from_context": ["in_vivo"],  "na_if_missing_context": "in_vivo",  "follow_up": "fetch_dataset"},
    "patient_rna_read":         {"text": "Patient RNA observation read.",                          "from_context": ["patient:rna"], "na_if_missing_context": "patient:rna"},
    "patient_protein_read":     {"text": "Patient protein observation read.",                      "from_context": ["patient:protein"], "na_if_missing_context": "patient:protein"},
    "within_person_pairing":    {"text": "participant_id overlap between the two patient datasets verified.", "from_context": ["patient:rna", "patient:protein"], "na_if_no_matched_axis": True},
    "reference_status_resolved": {"text": "Every non-ok reference source interpreted; `error` retried via build_evidence_package.", "from_context": ["reference"], "follow_up": "build_evidence_package"},
    "species_alignment":        {"text": "Mouse ortholog type checked before using in-vivo evidence.", "from_context": ["reference:orthology"], "na_if_missing_context": "in_vivo"},
}
LEDGER_SPEC = {
    "name": "update_criteria",
    "description": "Record criterion status WITH the observation_ids / reference keys that satisfy it. Bookkeeping call (counted separately).",
    "input_schema": {"type": "object", "required": ["criteria"], "properties": {"criteria": {"type": "object", "additionalProperties": {
        "type": "object", "required": ["status"],
        "properties": {"status": {"type": "string", "enum": ["met", "unmet", "not_applicable"]},
                       "evidence_ids": {"type": "array", "items": {"type": "string"}},
                       "reason": {"type": "string"},
                       "follow_up_action": {"type": "string", "description": "for unmet: the tool you called, e.g. fetch_dataset:invivo_rna"}}}}}}}


def system_prompt(manifest: dict) -> str:
    cl = "\n".join(f"{i+1}. {c}" for i, c in enumerate(manifest["task"]["checklist"]))
    return ("You assess whether a directional gene-expression finding holds across experimental contexts. "
            "Answer each declared axis separately; verdict vocabulary: persists / partially_persists / diverges / not_assessable. "
            "Reference sources (GTEx, orthology, IMPC) are background, not disease-contrast observations. "
            "Statuses: ok; not_found = database has no record; error = technical, retryable; skipped = disabled by mode or upstream failed. None is a biological negative.\n\n"
            f"Checklist (apply every item):\n{cl}\n\nRetry policy: {manifest['tools']['retry_policy']}\n"
            "When done, call submit_answer exactly once.")


# ------------------------------------------------------------------ ledger verification (B only)
def ctx_of(manifest: dict, tb: ToolBox) -> dict[str, set[str]]:
    """evidence id → context tags it can satisfy"""
    tags: dict[str, set[str]] = {}
    for d in manifest["datasets"]:
        key = d["context"] if d["context"] != "patient" else f"patient:{d['modality']}"
        tags.setdefault(d["id"], set()).add(key)
        f = json.loads((tb.base / d["path"]).resolve().read_text())
        for o in f.get("observations", []):
            tags.setdefault(o["observation_id"], set()).add(key)
    for name, entry in tb.stub.get("fetch_dataset", {}).items():
        d = next(x for x in manifest["datasets"] if x["id"] == name)
        key = d["context"] if d["context"] != "patient" else f"patient:{d['modality']}"
        for fn in entry["sequence"]:
            for o in json.loads((tb.fixture_dir / fn).read_text()).get("observations", []):
                tags.setdefault(o["observation_id"], set()).add(key)
    for k in ("gtex", "impc", "mygene", "opentargets", "pubmed"):
        tags.setdefault(k, set()).add("reference")
    for sp in ("mus_musculus", "rattus_norvegicus", "macaca_mulatta"):
        tags.setdefault(f"ensembl_orthology.{sp}", set()).update({"reference", "reference:orthology"})
    return tags


def verify_ledger(manifest, tb: ToolBox, ledger: dict) -> list[str]:
    tags = ctx_of(manifest, tb)
    present_ctx = {t for s in tags.values() for t in s}
    matched_axis = any(a["requires_matched_participants"] for a in manifest["task"]["axes"])
    executed = {(a["tool"], json.dumps(a["args"], sort_keys=True)) for a in tb.actions if a["kind"] == "data" and a["result_status"] in ("ok", "error", "not_found")}
    executed_tools = {t for t, _ in executed}
    problems = []
    for cid, rule in CRITERIA.items():
        e = ledger.get(cid)
        if not e:
            problems.append(f"{cid}: not recorded"); continue
        st = e.get("status")
        if st == "met":
            ids = e.get("evidence_ids") or []
            if not ids: problems.append(f"{cid}: met without evidence_ids"); continue
            bad = [i for i in ids if i not in tags]
            if bad: problems.append(f"{cid}: unknown evidence ids {bad}"); continue
            need = set(rule["from_context"])
            have = set().union(*(tags[i] for i in ids))
            if not need & have: problems.append(f"{cid}: evidence {ids} is not from {sorted(need)}"); continue
            if cid == "within_person_pairing" and not (need <= have):
                problems.append(f"{cid}: needs evidence from BOTH patient datasets")
        elif st == "unmet":
            fu = e.get("follow_up_action", "")
            tool = rule.get("follow_up")
            if not tool: problems.append(f"{cid}: unmet but no follow-up tool is defined for it; resolve or justify not_applicable")
            elif tool not in executed_tools or not fu.startswith(tool):
                problems.append(f"{cid}: unmet — follow-up '{tool}' has not actually been executed")
        elif st == "not_applicable":
            if not e.get("reason"): problems.append(f"{cid}: not_applicable without reason"); continue
            if rule.get("na_if_no_matched_axis") and matched_axis:
                problems.append(f"{cid}: not_applicable rejected — an axis requires matched participants")
            miss = rule.get("na_if_missing_context")
            if miss and miss in present_ctx:
                problems.append(f"{cid}: not_applicable rejected — {miss} data is present in this case")
            if cid == "reference_status_resolved":
                problems.append(f"{cid}: not_applicable rejected — reference package is always present")
        else:
            problems.append(f"{cid}: bad status {st}")
    return problems


def structural_problems(manifest, tb: ToolBox, ans: dict) -> list[str]:
    """Rules every configuration should follow; B enforces them at submit, the grader checks them for all."""
    known = tb.known_evidence_ids(); p = []
    declared = {a["axis_id"] for a in manifest["task"]["axes"]}
    got = {a["axis_id"] for a in ans.get("axes", [])}
    if declared - got: p.append(f"axes missing: {sorted(declared - got)}")
    for a in ans.get("axes", []):
        bad = [e for e in a.get("evidence", []) if e not in known]
        if bad: p.append(f"{a['axis_id']}: unknown evidence {bad}")
        if a["verdict"] != "not_assessable" and not a.get("evidence"): p.append(f"{a['axis_id']}: verdict without evidence")
        if a["verdict"] != "not_assessable" and not a.get("contrast_alignment"): p.append(f"{a['axis_id']}: verdict without contrast_alignment")
    if any(a["verdict"] == "diverges" for a in ans.get("axes", [])) and ans["overall"]["verdict"] == "persists":
        p.append("overall persists while an axis diverges")
    if any(v == "biological_negative" for v in ans.get("status_interpretation", {}).values()):
        p.append("a reference status was interpreted as a biological negative")
    return p


# ------------------------------------------------------------------ LLM scaffold
class Scaffold:
    def __init__(self, config: str):
        assert config in ("A0", "A", "B"); self.config = config

    def run(self, manifest: dict, manifest_path: Path, run_idx: int) -> dict:
        import anthropic
        client = anthropic.Anthropic()
        usage = Usage(MODEL, manifest["limits"])
        tb = ToolBox(manifest, manifest_path, usage)
        tools = ([] if self.config == "A0" else TOOL_SPECS) + [SUBMIT_SPEC] + ([LEDGER_SPEC] if self.config == "B" else [])
        ledger: dict = {}
        init = tb.initial_inputs()
        messages = [{"role": "user", "content": json.dumps({
            "task": manifest["task"], "gene": manifest["gene"], "datasets_declared": manifest["datasets"],
            "evidence_package": init["evidence_package"], "datasets": init["datasets"],
            "input_allowlist": manifest["input_allowlist"]})}]
        answer, status, err = None, "no_answer", None
        try:
            for _ in range(30):
                usage.check_deadline()
                resp = client.messages.create(model=MODEL, max_tokens=usage.next_call_max_tokens(), system=system_prompt(manifest),
                                              tools=tools, messages=messages, timeout=max(1.0, usage.remaining_seconds()))
                usage.add_llm(resp.usage)
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for block in resp.content:
                    if block.type != "tool_use": continue
                    out = self._dispatch(manifest, block.name, block.input, tb, ledger)
                    if block.name == "submit_answer" and out.get("accepted"):
                        answer = block.input
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out)})
                if answer is not None:
                    status = "completed"; break
                if not results:
                    messages.append({"role": "user", "content": "Call submit_answer now."}); continue
                messages.append({"role": "user", "content": results})
        except BudgetExceeded as e:
            status, err = e.kind, str(e)
        except Exception as e:  # noqa: BLE001  (API timeout → timeout; anything else → error)
            status = "timeout" if "timeout" in type(e).__name__.lower() or "Timeout" in str(e) else "error"
            err = repr(e)
        return build_output(manifest, self.config, run_idx, status, answer, tb, usage, err, ledger)

    def _dispatch(self, manifest, name, args, tb: ToolBox, ledger: dict) -> dict:
        if name == "read_file": return tb.read_file(**args)
        if name == "fetch_dataset": return tb.fetch_dataset(**args)
        if name == "build_evidence_package": return tb.build_evidence_package(**args)
        if name == "update_criteria":
            ledger.update(args["criteria"]); tb.bookkeeping("update_criteria", {"keys": sorted(args["criteria"])})
            return {"ok": True, "recorded": sorted(args["criteria"])}
        if name == "submit_answer":
            if self.config == "B":
                probs = verify_ledger(manifest, tb, ledger) + structural_problems(manifest, tb, args)
                unmet = [k for k, v in ledger.items() if v.get("status") == "unmet"]
                if unmet and args["overall"]["verdict"] == "persists":
                    probs.append(f"overall persists with unmet criteria {unmet}")
                if probs:
                    tb.bookkeeping("submit_answer", {"rejected": True}, "rejected")
                    return {"accepted": False, "problems": probs}
            return {"accepted": True}
        return {"status": "error", "error": f"unknown tool {name}"}


def build_output(manifest, config, run_idx, status, ans, tb: ToolBox, usage: Usage, err, ledger=None):
    declared = [a["axis_id"] for a in manifest["task"]["axes"]]
    if status != "completed" or ans is None:
        ans = {"overall": {"verdict": "not_assessable", "rationale": f"EXECUTION {status}: {err or 'no answer submitted'}"},
               "axes": [{"axis_id": a, "verdict": "not_assessable", "evidence": [], "contrast_alignment": None, "note": "no answer"} for a in declared],
               "evidence_cited": [], "status_interpretation": {}, "caveats": []}
    out = {"case_id": manifest["case_id"], "configuration": config, "run": run_idx, "execution_status": status,
           "overall": ans["overall"], "axes": ans["axes"], "evidence_cited": ans.get("evidence_cited", []),
           "status_interpretation": ans.get("status_interpretation", {}), "caveats": ans.get("caveats", []),
           "actions_taken": tb.actions, "usage": usage.dump(signed=False)}
    if ledger: out["_ledger"] = ledger
    return out


# ------------------------------------------------------------------ mocks (no LLM)
class Mock:
    def __init__(self, careless=False): self.careless = careless; self.config = "mock-careless" if careless else "mock"

    def run(self, manifest, manifest_path, run_idx):
        usage = Usage("mock", manifest["limits"]); tb = ToolBox(manifest, manifest_path, usage)
        init = tb.initial_inputs(); ds = init["datasets"]; pkg = init["evidence_package"]
        cited, caveats, axes = [], [], []
        # recovery
        for d in manifest["datasets"]:
            if d["status"] == "unavailable" and not self.careless:
                r = tb.fetch_dataset(d["id"])
                if r.get("status") == "ok": ds[d["id"]] = r["dataset"]; caveats.append(f"{d['id']} was unavailable; recovered via fetch_dataset")
        si = {}
        for m in pkg.get("missing", []):
            k = m["source"] + (f".{m['sub']}" if m.get("sub") else "")
            si[k] = {"not_found": "database_fact_no_record", "error": "technical_failure_retryable", "skipped": "disabled_by_mode"}[m["status"]]
        def first(did): return (ds.get(did, {}).get("observations") or [None])[0]
        iv = first("invitro_rna")
        for ax in manifest["task"]["axes"]:
            aid = ax["axis_id"]
            if aid == "literature_axis":
                n = ds["narrative"]; txt = (n["in_vivo_finding"] + " " + n["patient_finding"]).lower()
                mo = pkg["sources"]["ensembl_orthology"]["mus_musculus"]["status"]
                v = ("not_assessable" if mo == "not_found" and "no " in n["in_vivo_finding"].lower() else
                     "diverges" if any(w in txt for w in ("artifact", "absent", "does not transfer")) else
                     "partially_persists" if any(w in txt for w in ("fetal", "rarely", "immature")) else "persists")
                axes.append({"axis_id": aid, "verdict": v, "evidence": ["narrative", "ensembl_orthology.mus_musculus"], "contrast_alignment": "as summarised", "note": "mock"}); continue
            other = first(ax["datasets"][1])
            if other is None:
                axes.append({"axis_id": aid, "verdict": "not_assessable", "evidence": [], "contrast_alignment": None, "note": f"{ax['datasets'][1]} unavailable"}); continue
            if ax["requires_matched_participants"]:
                a = {s["participant_id"] for s in first(ax["datasets"][0]).get("samples", [])}
                b = {s["participant_id"] for s in other.get("samples", [])}
                ev = [first(ax["datasets"][0])["observation_id"], other["observation_id"]]
                if self.careless or a & b:
                    axes.append({"axis_id": aid, "verdict": "persists", "evidence": ev, "contrast_alignment": "same participants, same visit, lesional vs non-lesional", "note": "cohort summaries match" if self.careless else f"{len(a & b)} shared participants"})
                    cited.append({"source": other["observation_id"], "locator": f"{other['observation_id']}/cohort_summary" if self.careless else f"{other['observation_id']}/samples", "supports": "comparability_check"})
                else:
                    axes.append({"axis_id": aid, "verdict": "not_assessable", "evidence": ev, "contrast_alignment": None, "note": "participant_ids disjoint (P* vs Q*): independent cohorts agree in direction but within-person corroboration cannot be assessed"})
                    for oid in ev: cited.append({"source": oid, "locator": f"{oid}/samples", "supports": "comparability_check"})
                    caveats.append("patient_rna and patient_prot participant_ids are disjoint; cohort summaries identical; within-person axis not assessable")
                continue
            same = iv["effect"]["direction"] == other["effect"]["direction"]
            basis = other["contrast"].get("alignment_basis")
            axes.append({"axis_id": aid, "verdict": "persists" if same else "diverges", "evidence": [iv["observation_id"], other["observation_id"]],
                         "contrast_alignment": basis or "unspecified", "note": f"{iv['effect']['direction']} vs {other['effect']['direction']}"})
            cited.append({"source": other["observation_id"], "locator": f"{other['observation_id']}/effect", "supports": "claim" if same else "against_claim"})
        cited.append({"source": iv["observation_id"], "locator": f"{iv['observation_id']}/effect", "supports": "claim"}) if iv else None
        cited.append({"source": "gtex", "locator": "sources.gtex.data.tissues", "supports": "background"})
        vs = [a["verdict"] for a in axes]
        overall = ("diverges" if all(v == "diverges" for v in vs) else "partially_persists" if "diverges" in vs or ("not_assessable" in vs and not self.careless)
                   else "persists" if all(v in ("persists", "not_assessable") for v in vs) else "partially_persists")
        if self.careless and "not_assessable" in vs: overall = "persists"
        ans = {"overall": {"verdict": overall, "rationale": "mock"}, "axes": axes, "evidence_cited": cited, "status_interpretation": si, "caveats": caveats}
        return build_output(manifest, self.config, run_idx, "completed", ans, tb, usage, None)


def get_agent(name: str):
    if name == "C":
        from coordinator_adapter import CoordinatorAdapter
        return CoordinatorAdapter()
    return {"A0": lambda: Scaffold("A0"), "A": lambda: Scaffold("A"), "B": lambda: Scaffold("B"),
            "mock": lambda: Mock(False), "mock-careless": lambda: Mock(True)}[name]()
