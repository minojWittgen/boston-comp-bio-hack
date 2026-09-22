"""Agent configurations.

  A0 vanilla    : plain Claude, NO tools — package + fixtures pasted in, one shot, submit_answer only.
  A  baseline   : one scaffold — system prompt, the two case tools, submit_answer.
  B  workflow   : A + an enforced criteria ledger. submit_answer is REJECTED until every
                  mandatory criterion is marked met, or marked unmet with a follow-up action
                  the agent actually took. Same model, same tools, same limits as A.
  mock          : deterministic, no LLM. Exercises the harness and the grader end to end.

Configuration C (external comparator) is not here: see harness/usage_capture.md for the
adapter contract — it must produce the same agent_output.schema.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from common import TOOL_SPECS, VERDICTS, LimitExceeded, ToolBox, Usage

MODEL = os.environ.get("XCTX_MODEL", "claude-sonnet-4-5")

SUBMIT_SPEC = {
    "name": "submit_answer",
    "description": "Submit the final verdict. Call exactly once, when done.",
    "input_schema": {
        "type": "object",
        "required": ["verdict", "rationale", "evidence_cited", "caveats"],
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "confidence": {"type": "number"},
            "rationale": {"type": "string"},
            "evidence_cited": {"type": "array", "items": {
                "type": "object", "required": ["source", "locator", "supports"],
                "properties": {"source": {"type": "string"}, "locator": {"type": "string"},
                               "supports": {"type": "string", "enum": ["claim", "against_claim", "comparability_check"]}}}},
            "caveats": {"type": "array", "items": {"type": "string"}},
        },
    },
}

# ---- B's ledger: generic, NOT case-specific (lives in the agent, never in a manifest) -----
CRITERIA = {
    "in_vitro_effect_located":      "The in-vitro effect for the claim's gene has been read and its direction noted.",
    "patient_effect_located":       "The patient-context effect has been read and its direction noted.",
    "mandatory_sources_ok":         "Every mandatory pipeline source (gtex, mouse orthology) has status ok — or was re-fetched if error.",
    "status_semantics_applied":     "not_found treated as a database fact, skipped-by-mode ignored, error treated as retryable.",
    "tissue_match_checked":         "The GTEx tissue used matches the claim's tissue (not just top-5 summary).",
    "sample_identity_checked":      "When two patient datasets are combined, their patient_ids overlap was verified.",
    "cross_species_checked":        "Ortholog type (one2one / one2many / none) was checked before using mouse evidence.",
}
MANDATORY = list(CRITERIA)

LEDGER_SPEC = {
    "name": "update_criteria",
    "description": "Record the status of each evaluation criterion. Call whenever a criterion's status changes.",
    "input_schema": {"type": "object", "required": ["criteria"], "properties": {"criteria": {
        "type": "object", "additionalProperties": {
            "type": "object", "required": ["status"],
            "properties": {"status": {"type": "string", "enum": ["met", "unmet", "not_applicable"]},
                           "evidence": {"type": "string"},
                           "follow_up_action": {"type": "string", "description": "for unmet: the tool call you will make / made"}}}}}},
}

SYSTEM_A = """You are assessing whether an in-vitro biological finding is corroborated across in-vivo and patient contexts.
You receive an evidence package produced by a deterministic pipeline (statuses: ok, not_found = database has no record, error = technical failure worth retrying, skipped = disabled or upstream failed) and context datasets. Read carefully, use tools if needed, then call submit_answer once.
Verdicts: persists / partially_persists / diverges / not_comparable."""

SYSTEM_B = SYSTEM_A + """

You must track these criteria with update_criteria before submitting:
""" + "\n".join(f"- {k}: {v}" for k, v in CRITERIA.items()) + """
submit_answer will be rejected until every criterion is met, not_applicable with a reason, or unmet with a follow-up action you have already taken. An unmet criterion that cannot be resolved must appear in caveats and must cap the verdict at not_comparable or partially_persists."""


# ------------------------------------------------------------------ LLM scaffold
class Scaffold:
    def __init__(self, config: str):
        assert config in ("A0", "A", "B")
        self.config = config

    def run(self, manifest: dict, manifest_path: Path, run_idx: int) -> dict:
        import anthropic  # lazy: mock config needs no SDK
        client = anthropic.Anthropic()
        limits = manifest["limits"]
        usage = Usage(MODEL)
        tb = ToolBox(manifest, manifest_path, usage, limits)
        tools = ([] if self.config == "A0" else TOOL_SPECS) + [SUBMIT_SPEC] + ([LEDGER_SPEC] if self.config == "B" else [])
        ledger: dict = {}
        upfront = tb.manifest_files()
        messages = [{"role": "user", "content": json.dumps({
            "claim": manifest["task"]["claim"], "instruction": manifest["task"]["instruction"],
            "gene": manifest["gene"], "evidence_package": upfront["evidence_package"],
            "context_datasets": upfront["context_datasets"],
            "files_readable_with_read_file": [d["path"] for d in manifest["context_datasets"]] + [manifest["evidence_package"]["path"]],
        })}]
        answer, error = None, None
        try:
            for _ in range(40):
                resp = client.messages.create(
                    model=MODEL, max_tokens=limits["max_output_tokens"],
                    system=SYSTEM_B if self.config == "B" else SYSTEM_A,
                    tools=tools, messages=messages)
                usage.add_llm(resp.usage)
                if usage.output_tokens > limits["max_output_tokens"] * 4:
                    raise LimitExceeded("max_output_tokens (cumulative) exceeded")
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue
                    out = self._dispatch(block.name, block.input, tb, ledger)
                    if block.name == "submit_answer" and out.get("accepted"):
                        answer = block.input
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(out)})
                if answer is not None:
                    break
                if not results:  # model stopped without submitting
                    messages.append({"role": "user", "content": "Call submit_answer now."})
                    continue
                messages.append({"role": "user", "content": results})
        except LimitExceeded as e:
            error = str(e)
        return _output(manifest, self.config, run_idx, answer, tb, usage, error, ledger)

    def _dispatch(self, name, args, tb: ToolBox, ledger: dict) -> dict:
        if name == "read_file":
            return tb.read_file(**args)
        if name == "build_evidence_package":
            return tb.build_evidence_package(**args)
        if name == "update_criteria":
            ledger.update(args["criteria"])
            return {"ok": True, "ledger": ledger}
        if name == "submit_answer":
            if self.config == "B":
                bad = [k for k in MANDATORY if ledger.get(k, {}).get("status") not in ("met", "not_applicable", "unmet")]
                bad += [k for k in MANDATORY if ledger.get(k, {}).get("status") == "unmet"
                        and not ledger[k].get("follow_up_action")]
                if bad:
                    return {"accepted": False, "reason": f"criteria not resolved: {bad}. Resolve them (use tools if needed) then resubmit."}
            return {"accepted": True}
        return {"status": "error", "error": f"unknown tool {name}"}


def _output(manifest, config, run_idx, answer, tb: ToolBox, usage: Usage, error, ledger=None):
    out = {"case_id": manifest["case_id"], "configuration": config, "run": run_idx,
           "verdict": (answer or {}).get("verdict", "not_comparable"),
           "confidence": (answer or {}).get("confidence"),
           "rationale": (answer or {}).get("rationale", f"NO ANSWER: {error}" if error else "NO ANSWER"),
           "evidence_cited": (answer or {}).get("evidence_cited", []),
           "caveats": (answer or {}).get("caveats", []) + ([f"harness: {error}"] if error else []),
           "actions_taken": tb.actions, "usage": usage.dump()}
    if out["confidence"] is None:
        del out["confidence"]
    if ledger:
        out["_ledger"] = ledger  # stripped before grading; kept in the raw trace
    return out


# ------------------------------------------------------------------ mock (no LLM)
class Mock:
    """Does the right thing deterministically, with a `careless` flag that mimics baseline
    failure modes (ignores patient ids, never retries). Lets you test grading without spend."""

    def __init__(self, careless: bool = False):
        self.careless = careless
        self.config = "A" if careless else "B"

    def run(self, manifest, manifest_path, run_idx):
        usage = Usage("mock")
        tb = ToolBox(manifest, manifest_path, usage, manifest["limits"])
        up = tb.manifest_files()
        pkg, ctx = up["evidence_package"], up["context_datasets"]
        cited, caveats = [], []
        verdict = "persists"
        tissue = None
        for d in ctx.values():
            tissue = tissue or d.get("tissue")
        # -- mandatory source check + recovery
        if pkg["sources"]["gtex"]["status"] == "error" and not self.careless:
            r = tb.build_evidence_package(manifest["gene"]["symbol"], manifest["gene"]["disease"], "eval")
            if r.get("status") == "ok":
                pkg = r["package"]
                caveats.append("gtex was `error` in the provided package; re-ran pipeline and recovered it")
        # -- narrative (literature) cases: verdict from text, crude but deterministic
        if "narrative" in ctx:
            n = ctx["narrative"]
            txt = (n["in_vivo_finding"] + " " + n["patient_finding"]).lower()
            mo = pkg["sources"]["ensembl_orthology"]["mus_musculus"]["status"]
            if "no " in n["in_vivo_finding"].lower() and mo == "not_found":
                verdict = "not_comparable"
            elif any(w in txt for w in ("artifact", "absent", "does not transfer", "divergent")):
                verdict = "diverges"
            elif any(w in txt for w in ("fetal", "rarely reaches", "immature", "not reach")):
                verdict = "partially_persists"
            cited.append({"source": "narrative", "locator": "in_vivo_finding", "supports": "claim" if verdict == "persists" else "against_claim"})
            cited.append({"source": "ensembl_orthology.mus_musculus", "locator": f"status={mo}", "supports": "comparability_check"})
            return _output(manifest, self.config, run_idx, {"verdict": verdict, "rationale": "mock", "evidence_cited": cited, "caveats": caveats}, tb, usage, None)
        # -- numeric cases
        iv, pr, pp = ctx["invitro_rna"], ctx["patient_rna"], ctx["patient_prot"]
        cited += [{"source": "invitro_rna", "locator": "effect.log2fc", "supports": "claim"},
                  {"source": "patient_rna", "locator": "effect.log2fc", "supports": "claim"}]
        if pkg["sources"]["gtex"]["status"] == "ok":
            t = {r["tissue"]: r["median_tpm"] for r in pkg["sources"]["gtex"]["data"]["tissues"]}
            tpm = t.get(tissue, 0)
            cited.append({"source": "gtex", "locator": f"{tissue} median_tpm={tpm}", "supports": "claim" if tpm >= 1 else "against_claim"})
            if tpm < 1 and not self.careless:
                verdict = "diverges"
                caveats.append(f"recovered gtex shows {tissue} median_tpm={tpm}: gene not expressed in the claim's tissue, contradicting the claim")
        else:
            verdict = "not_comparable"
            caveats.append("gtex still not ok; cannot assess tissue expression")
        ids_r = {s["patient_id"] for s in pr["samples"]}
        ids_p = {s["patient_id"] for s in pp["samples"]}
        if self.careless:
            cited.append({"source": "patient_prot", "locator": "effect.log2fc", "supports": "claim"})
            cited.append({"source": "patient_prot", "locator": "cohort_summary", "supports": "comparability_check"})
        elif ids_r & ids_p:
            cited.append({"source": "patient_prot", "locator": "samples[].patient_id", "supports": "comparability_check"})
            caveats.append("patient_rna and patient_prot share patient_ids; pairing is valid")
        else:
            cited.append({"source": "patient_rna", "locator": "samples[].patient_id", "supports": "comparability_check"})
            cited.append({"source": "patient_prot", "locator": "samples[].patient_id", "supports": "comparability_check"})
            caveats.append("patient_ids in patient_rna and patient_prot are disjoint although cohort_summary matches; RNA-protein agreement is not within-patient corroboration")
            if verdict == "persists":
                verdict = "not_comparable"
        if not self.careless:
            caveats.append("pubmed and opentargets are skipped by eval mode and were not used")
        return _output(manifest, self.config, run_idx,
                       {"verdict": verdict, "rationale": "mock deterministic reasoning",
                        "evidence_cited": cited, "caveats": caveats}, tb, usage, None)


def get_agent(name: str):
    return {"A0": lambda: Scaffold("A0"), "A": lambda: Scaffold("A"), "B": lambda: Scaffold("B"),
            "mock": lambda: Mock(False), "mock-careless": lambda: Mock(True)}[name]()
