"""One model client for every stage of the integrated system, with usage captured into common.Usage.

`UsageClient` wraps an Anthropic client so that ANY `messages.create` call — including the
coordinator's ClaudePlanner, which accepts an injected client — is counted, bounded by the
remaining deadline, and recorded with its model id. `structured()` is the helper the extraction
stage uses for one forced-tool structured call.
"""
from __future__ import annotations

import json
import os
from typing import Any

from common import BudgetExceeded, Usage


class _Messages:
    def __init__(self, inner, usage: Usage, inventory: list):
        self._inner, self._usage, self._inventory = inner, usage, inventory

    def create(self, **kw):
        self._usage.check_deadline()
        kw.setdefault("timeout", max(1.0, self._usage.remaining_seconds()))
        kw["max_tokens"] = min(int(kw.get("max_tokens", 4096)), self._usage.next_call_max_tokens())
        stage = kw.pop("_stage", "unlabelled")
        resp = self._inner.messages.create(**kw)
        self._usage.add_llm(resp.usage)
        self._inventory.append({"stage": stage, "model": kw.get("model")})
        return resp


class UsageClient:
    """Duck-types the parts of anthropic.Anthropic that the coordinator and extractor use."""

    def __init__(self, usage: Usage, inner=None):
        if inner is None:
            from anthropic import Anthropic
            inner = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=0)
        self.model_inventory: list[dict] = []
        self.messages = _Messages(inner, usage, self.model_inventory)


def structured(client, *, model: str, stage: str, system: str, user: Any, tool_name: str, schema: dict, max_tokens: int = 3000) -> dict:
    """One forced-schema call. Returns the tool input dict or raises ValueError."""
    resp = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": user if isinstance(user, str) else json.dumps(user, ensure_ascii=False)}],
                                  tools=[{"name": tool_name, "description": f"Return {tool_name}", "input_schema": schema}],
                                  tool_choice={"type": "tool", "name": tool_name, "disable_parallel_tool_use": True},
                                  _stage=stage) if isinstance(client, UsageClient) else client.messages.create(
                                  model=model, max_tokens=max_tokens, system=system,
                                  messages=[{"role": "user", "content": user if isinstance(user, str) else json.dumps(user, ensure_ascii=False)}],
                                  tools=[{"name": tool_name, "description": f"Return {tool_name}", "input_schema": schema}],
                                  tool_choice={"type": "tool", "name": tool_name, "disable_parallel_tool_use": True})
    blocks = [b for b in getattr(resp, "content", []) if getattr(b, "type", None) == "tool_use"]
    if len(blocks) != 1 or blocks[0].name != tool_name:
        raise ValueError(f"{stage}: model did not return exactly one {tool_name} tool call")
    return blocks[0].input


class FakeAnthropic:
    """OFFLINE STAND-IN for harness/calibration runs only (never for scored runs).

    It answers the two structured calls the integrated path makes — the coordinator's planning call
    and the extractor's study-metadata call — from the *inputs it is given* (methods text, the
    request), not from any answer key. It is deliberately naive: it does not read result tables and
    it does not know which case it is in. `run_primary.py` refuses `--system integrated` with this
    stand-in unless the batch name starts with `calib`/`smoke`.
    """

    class _Usage:
        input_tokens = 0; output_tokens = 0; cache_read_input_tokens = 0; cache_creation_input_tokens = 0

    class _Block:
        def __init__(self, name, inp): self.type, self.name, self.input = "tool_use", name, inp

    class _Resp:
        def __init__(self, block): self.content, self.stop_reason, self.usage = [block], "tool_use", FakeAnthropic._Usage()

    def __init__(self): self.messages = self

    def create(self, **kw):
        tool = kw["tools"][0]["name"]; user = kw["messages"][0]["content"]
        if tool == "submit_research_plan":
            return self._Resp(self._Block(tool, _fake_plan(json.loads(user))))
        if tool == "study_metadata":
            return self._Resp(self._Block(tool, _fake_study_metadata(json.loads(user))))
        raise ValueError(f"FakeAnthropic: unknown tool {tool}")


def _fake_plan(intent: dict) -> dict:
    """A plan built ONLY from the request text: entities present in the question, one requirement per
    context/modality mentioned, comparisons mirroring the numbered items in the request."""
    req = intent["request"]; q = req["question"]
    genes = intent.get("effective_explicit_genes") or req.get("genes") or []
    if not genes:
        import re
        genes = [g for g in re.findall(r"\b[A-Z][A-Z0-9]{2,7}\b", q) if g in ("TYK2", "IL17A")]
    reqs, comps = [], []
    for g in genes:
        reqs += [
            {"id": f"vitro_rna_{g}", "title": "in-vitro RNA", "entity": g, "species": "homo_sapiens", "context": "in_vitro", "modality": "RNA", "endpoint": "relative_abundance", "condition": "IL-23 stimulation", "tissue": "keratinocytes", "host_species": None, "min_studies": 1, "required": True},
            {"id": f"vivo_rna_{g}", "title": "animal RNA", "entity": g, "species": "mus_musculus", "context": "in_vivo", "modality": "RNA", "endpoint": "relative_abundance", "condition": "imiquimod psoriasiform inflammation", "tissue": "skin", "host_species": "mus_musculus", "min_studies": 1, "required": True},
            {"id": f"patient_rna_{g}", "title": "patient RNA", "entity": g, "species": "homo_sapiens", "context": "patient", "modality": "RNA", "endpoint": "relative_abundance", "condition": "psoriasis lesional vs non-lesional", "tissue": "skin", "host_species": None, "min_studies": 1, "required": True},
            {"id": f"patient_prot_{g}", "title": "patient protein", "entity": g, "species": "homo_sapiens", "context": "patient", "modality": "protein", "endpoint": "relative_abundance", "condition": "psoriasis lesional vs non-lesional", "tissue": "skin", "host_species": None, "min_studies": 1, "required": True}]
        comps += [
            {"id": f"in_vitro_vs_animal:{g}", "left": f"vitro_rna_{g}", "right": f"vivo_rna_{g}", "require_matched_subjects": False,
             "cross_species_basis": "one2one ortholog per recorded Ensembl homology", "context_alignment_basis": "IL-23-driven keratinocyte stimulation vs IMQ psoriasiform skin: same inflammatory axis, same endpoint"},
            {"id": f"in_vitro_vs_patient_rna:{g}", "left": f"vitro_rna_{g}", "right": f"patient_rna_{g}", "require_matched_subjects": False, "cross_species_basis": None,
             "context_alignment_basis": "stimulated keratinocytes vs lesional skin: disease-relevant stimulation vs disease tissue"},
            {"id": f"patient_rna_vs_patient_protein_within_person:{g}", "left": f"patient_rna_{g}", "right": f"patient_prot_{g}", "require_matched_subjects": True, "cross_species_basis": None, "context_alignment_basis": None}]
    return {"question": q, "genes": genes, "disease": req.get("disease", ""), "requirements": reqs, "comparisons": comps,
            "assumptions": ["FAKE planner (offline stand-in): scope derived from request text only"], "pathway": req.get("pathway")}


def _fake_study_metadata(payload: dict) -> dict:
    """Naive metadata from the methods text: keyword matches only."""
    t = payload["methods_text"].lower(); files = payload["data_files"]
    species = "mus_musculus" if "mus musculus" in t or "mouse" in t else "homo_sapiens"
    context = "in_vivo" if species == "mus_musculus" else ("patient" if "participant" in t or "biopsies" in t else "in_vitro")
    contrast = {"case": "IMQ", "reference": "vehicle", "label": "perturbed_vs_reference"} if "imiquimod" in t else (
        {"case": "lesional", "reference": "non-lesional", "label": "perturbed_vs_reference"} if "lesional" in t else {"case": "IL-23", "reference": "vehicle", "label": "perturbed_vs_reference"})
    tissue = "skin" if "skin" in t else ("keratinocytes" if "keratinocyte" in t else None)
    condition = "imiquimod psoriasiform inflammation" if "imiquimod" in t else ("psoriasis lesional vs non-lesional" if "lesional" in t else "IL-23 stimulation")
    tables = []
    for f in files:
        if f.endswith("de_results.csv"):
            tables.append({"file": f, "kind": "differential_expression", "modality": "RNA", "endpoint": "relative_abundance", "gene_column": "gene", "effect_column": "log2FoldChange", "padj_column": "padj", "gene_symbol_species": species})
        elif f.endswith("rna_log2cpm.csv"):
            tables.append({"file": f, "kind": "per_specimen_values", "modality": "RNA", "endpoint": "relative_abundance", "gene_column": "gene", "value_column": "log2cpm", "specimen_column": "specimen_id"})
        elif f.endswith("protein_npx.csv"):
            tables.append({"file": f, "kind": "per_specimen_values", "modality": "protein", "endpoint": "relative_abundance", "gene_column": "assay_target", "value_column": "npx", "specimen_column": "specimen_id"})
        elif f.endswith("specimens.csv"):
            tables.append({"file": f, "kind": "specimen_metadata", "specimen_column": "specimen_id", "participant_column": "participant_id", "timepoint_column": "visit", "arm_column": "site_type", "case_arm_value": "lesional", "reference_arm_value": "nonlesional"})
    within_person_supported = ("split" in t and "share" in t)
    return {"study_id": payload["study_dir"], "species": species, "context": context, "host_species": species if context == "in_vivo" else None,
            "tissue": tissue, "condition": condition, "contrast": contrast, "tables": tables,
            "rna_protein_same_specimen": within_person_supported, "normalization_basis_cross_modal": "within-participant paired lesional vs non-lesional on log2 scales" if within_person_supported else None,
            "notes": "FAKE extractor (offline stand-in): keyword heuristics over methods text only"}
