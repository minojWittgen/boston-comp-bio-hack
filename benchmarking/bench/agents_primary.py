"""PRIMARY suite systems.

  baseline     : a competent general-purpose research agent — same backbone model, the task text, tool
                 documentation, and a general research instruction. It receives NO checklist, NO workflow,
                 NO pre-extracted evidence. It does its own extraction, structuring, comparison, interpretation.
  integrated   : the team's integrated system (collector/extractor → normalization → coordinator), driven through
                 bench/integrated_adapter.py against the SAME corpus and tools. Raises until implemented.
  mock / mock-careless : deterministic report writers to exercise the runner and grader.

Whole-run measurement: every model call in either system must go through common.Usage (or be injected
into it by the adapter) — retrieval, extraction, planning, normalization, checking and revision included.
"""
from __future__ import annotations

import csv
import io
import json
import os
import statistics
from pathlib import Path

from common import BudgetExceeded, Usage
from primary_common import CORPUS_TOOL_SPECS, CorpusTools

MODEL = os.environ.get("XCTX_MODEL", "claude-sonnet-4-5")

SUBMIT_REPORT_SPEC = {
    "name": "submit_report",
    "description": "Deliver the final report. Call exactly once.",
    "input_schema": {"type": "object", "required": ["comparisons", "limitations", "unresolved", "report_markdown"],
                     "properties": {
                         "comparisons": {"type": "array", "items": {"type": "object", "required": ["comparison_id", "scope", "conclusion", "statement", "citations"],
                                                                     "properties": {"comparison_id": {"type": "string", "pattern": "^(in_vitro_vs_animal|in_vitro_vs_patient_rna|patient_rna_vs_patient_protein_within_person)(:[A-Za-z0-9_.-]+)?$"},
                                                                                    "scope": {"type": "object", "properties": {"species": {"type": "array", "items": {"type": "string"}}, "context": {"type": "array", "items": {"type": "string"}}, "modality": {"type": "array", "items": {"type": "string"}}}},
                                                                                    "conclusion": {"type": "string", "enum": ["supported", "opposed", "insufficient_evidence"]},
                                                                                    "statement": {"type": "string"},
                                                                                    "citations": {"type": "array", "items": {"type": "object", "required": ["file", "locator"], "properties": {"file": {"type": "string"}, "locator": {"type": "string", "description": "line:N | row:col=value[;col=value] | json:path | section:heading"}, "quote": {"type": "string"}}}},
                                                                                    "within_person": {"type": ["boolean", "null"]}}}},
                         "limitations": {"type": "array", "items": {"type": "string"}},
                         "unresolved": {"type": "array", "items": {"type": "string"}},
                         "report_markdown": {"type": "string"}}}}

GENERAL_INSTRUCTION = (
    "You are a careful computational biologist. Answer the research request in task.md using ONLY the files in the corpus. "
    "Read the methods before the numbers. Be explicit about species, tissue, contrast and endpoint when you compare results, "
    "and about who the participants are when you compare measurements within people. Cite the exact source location for every "
    "conclusion (file plus line, row, JSON path or section). Distinguish 'supported', 'opposed' and 'insufficient evidence'; a "
    "justified 'insufficient evidence' is a valid answer, and so is 'opposed'. State limitations and what remains unresolved. "
    "When finished, call submit_report once.")


class GeneralAgent:
    system = "baseline"

    def run(self, manifest: dict, case_dir: Path, run_idx: int) -> dict:
        import anthropic
        client = anthropic.Anthropic()
        usage = Usage(MODEL, manifest["limits"]); tools = CorpusTools(manifest, case_dir, usage)
        task = (case_dir / manifest["task_file"]).read_text()
        messages = [{"role": "user", "content": task + "\n\nCorpus files:\n" + "\n".join(f"- {f}" for f in manifest["permitted_files"])}]
        answer, status, err = None, "no_answer", None
        try:
            for _ in range(40):
                usage.check_deadline()
                resp = client.messages.create(model=MODEL, max_tokens=usage.next_call_max_tokens(), system=GENERAL_INSTRUCTION,
                                              tools=CORPUS_TOOL_SPECS + [SUBMIT_REPORT_SPEC], messages=messages,
                                              timeout=max(1.0, usage.remaining_seconds()))
                usage.add_llm(resp.usage)
                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for b in resp.content:
                    if b.type != "tool_use": continue
                    if b.name == "submit_report": answer = b.input; out = {"accepted": True}
                    elif b.name == "list_files": out = tools.list_files()
                    elif b.name == "read_file": out = tools.read_file(**b.input)
                    elif b.name == "search": out = tools.search(**b.input)
                    elif b.name == "python_eval": out = tools.python_eval(**b.input)
                    else: out = {"status": "error", "error": "unknown tool"}
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out)})
                if answer is not None: status = "completed"; break
                if not results: messages.append({"role": "user", "content": "Call submit_report now."}); continue
                messages.append({"role": "user", "content": results})
        except BudgetExceeded as e:
            status, err = e.kind, str(e)
        except Exception as e:  # noqa: BLE001
            status = "timeout" if "timeout" in type(e).__name__.lower() else "error"; err = repr(e)
        return envelope(manifest, self.system, status, answer, tools, usage, err)


def envelope(manifest, system, status, ans, tools: CorpusTools, usage: Usage, err, limitations=None):
    if status != "completed" or ans is None:
        # limitations known before the failure (e.g. an unroutable request shape) are still reported;
        # without them a failed run shows only a raw exception repr and cannot be read by a reviewer.
        ans = {"comparisons": [], "limitations": list(limitations or []),
               "unresolved": [f"EXECUTION {status}: {err or 'no report submitted'}"], "report_markdown": ""}
    return {"case_id": manifest["case_id"], "system": system, "execution_status": status,
            "comparisons": ans["comparisons"], "limitations": ans["limitations"], "unresolved": ans["unresolved"],
            "report_markdown": ans["report_markdown"],
            "_system_internal": {"actions": tools.actions, "usage": usage.dump(signed=False), "error": err}}


# ------------------------------------------------------------------ mocks
class MockPrimary:
    """Reads the corpus the way a diligent (or careless) analyst would; used for harness/grader checks only."""
    def __init__(self, careless=False): self.careless = careless; self.system = "mock-careless" if careless else "mock"

    def run(self, manifest, case_dir, run_idx):
        usage = Usage("mock", manifest["limits"]); t = CorpusTools(manifest, case_dir, usage)
        def rows(rel): return list(csv.DictReader(io.StringIO(t.read_file(rel)["content"])))
        a = next(r for r in rows("study_A_invitro/de_results.csv") if r["gene"] == "TYK2")
        b = next(r for r in rows("study_B_mouse_imq/de_results.csv") if r["gene"] == "Tyk2")
        spec = rows("study_C_patient_cohort/specimens.csv"); rna = rows("study_C_patient_cohort/rna_log2cpm.csv"); prot = rows("study_C_patient_cohort/protein_npx.csv")
        by_spec = {s["specimen_id"]: s for s in spec}
        def paired(values, key, target):
            d = {}
            for r in values:
                if r[key] != target: continue
                s = by_spec[r["specimen_id"]]; d.setdefault(s["participant_id"], {})[s["site_type"]] = float(r["log2cpm" if key == "gene" else "npx"])
            diffs = [v["lesional"] - v["nonlesional"] for v in d.values() if {"lesional", "nonlesional"} <= v.keys()]
            return set(d), statistics.mean(diffs) if diffs else None
        pr, dr = paired(rna, "gene", "TYK2"); pp, dp = paired(prot, "assay_target", "TYK2")
        up_a = float(a["log2FoldChange"]) > 0; up_b = float(b["log2FoldChange"]) > 0
        comps = [
            {"comparison_id": "in_vitro_vs_animal", "scope": {"species": ["Homo sapiens", "Mus musculus"], "context": ["in_vitro", "in_vivo"], "modality": ["rna"]},
             "conclusion": "supported" if up_a == up_b else "opposed",
             "statement": f"Study A TYK2 log2FC {a['log2FoldChange']} (IL-23 vs vehicle); study B Tyk2 log2FC {b['log2FoldChange']} (mouse IMQ vs vehicle dorsal skin, day 6). Same endpoint (mRNA), psoriasis-like inflammatory contrast in keratinocyte-rich tissue; one2one ortholog.",
             "citations": [{"file": "study_A_invitro/de_results.csv", "locator": "row:gene=TYK2"}, {"file": "study_B_mouse_imq/de_results.csv", "locator": "row:gene=Tyk2"},
                           {"file": "study_B_mouse_imq/methods.md", "locator": "section:methods"}, {"file": "api/ensembl_homology_TYK2_mus_musculus.json", "locator": "json:data/0/homologies/0/type"}]},
            {"comparison_id": "in_vitro_vs_patient_rna", "scope": {"species": ["Homo sapiens"], "context": ["in_vitro", "patient"], "modality": ["rna"]},
             "conclusion": "supported" if (dr or 0) > 0 else "opposed",
             "statement": f"Paired lesional−non-lesional TYK2 log2CPM mean difference {dr:.2f} across {len(pr)} participants.",
             "citations": [{"file": "study_C_patient_cohort/rna_log2cpm.csv", "locator": "row:gene=TYK2;specimen_id=S-P01-L"}, {"file": "study_C_patient_cohort/specimens.csv", "locator": "row:specimen_id=S-P01-L"}]},
        ]
        overlap = pr & pp
        if self.careless or overlap:
            comps.append({"comparison_id": "patient_rna_vs_patient_protein_within_person", "scope": {"species": ["Homo sapiens"], "context": ["patient"], "modality": ["rna", "protein"]},
                          "conclusion": "supported", "within_person": True,
                          "statement": f"Protein lesional−non-lesional mean NPX difference {dp:.2f}; RNA difference {dr:.2f}." + ("" if overlap else " Cohort summaries identical, so treated as the same participants."),
                          "citations": [{"file": "study_C_patient_cohort/protein_npx.csv", "locator": "row:assay_target=TYK2"}, {"file": "study_C_patient_cohort/methods.md", "locator": "section:Study C"}]
                                        + ([] if self.careless else [{"file": "study_C_patient_cohort/specimens.csv", "locator": "row:specimen_id=S-P01-L"}])})
        else:
            comps.append({"comparison_id": "patient_rna_vs_patient_protein_within_person", "scope": {"species": ["Homo sapiens"], "context": ["patient"], "modality": ["rna", "protein"]},
                          "conclusion": "insufficient_evidence", "within_person": False,
                          "statement": f"RNA specimens map to participants {sorted(pr)[0]}..{sorted(pr)[-1]} and protein specimens to {sorted(pp)[0]}..{sorted(pp)[-1]} (specimens.csv): no shared participant_id, so within-person corroboration cannot be established. Population-level: both increase in lesional skin (independent groups).",
                          "citations": [{"file": "study_C_patient_cohort/specimens.csv", "locator": "row:specimen_id=T-Q01-L"}, {"file": "study_C_patient_cohort/specimens.csv", "locator": "row:specimen_id=S-P01-L"}, {"file": "study_C_patient_cohort/protein_npx.csv", "locator": "row:assay_target=TYK2"}]})
        ans = {"comparisons": comps, "limitations": ["synthetic corpus; single gene; GTEx/IMPC used as background only"],
               "unresolved": [] if overlap or self.careless else ["within-person RNA–protein relationship (no shared participants)"],
               "report_markdown": "# Report\n" + "\n".join(f"- **{c['comparison_id']}**: {c['conclusion']} — {c['statement']}" for c in comps)}
        return envelope(manifest, self.system, "completed", ans, t, usage, None)


def get_system(name: str):
    if name == "integrated":
        from integrated_adapter import IntegratedSystemAdapter
        return IntegratedSystemAdapter()
    return {"baseline": GeneralAgent, "mock": lambda: MockPrimary(False), "mock-careless": lambda: MockPrimary(True)}[name]()
