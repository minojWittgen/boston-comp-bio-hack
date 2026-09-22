"""Extraction + normalization stage of the integrated system (corpus → coordinator EvidenceRecords).

This is the system's OWN extraction path (handoff §1). It is generic over the corpus conventions —
"a study directory = methods excerpt + result/metadata tables" — and knows nothing about case ids,
expected answers, or the rubric. It uses one model call per study to read the methods excerpt into
structured study metadata (species, context, tissue, condition, contrast, which table holds what),
using the frozen plan's requirement vocabulary as the normalization target; every numeric direction
is then computed deterministically from the tables. Missing metadata stays missing (None), so the
coordinator's checks can reject it — the adapter never invents fields to satisfy a check.

Normalization policy (explicit, per handoff §2/§5 review notes): `contrast` = direction-semantics class
(perturbed_vs_reference / reference_vs_perturbed / other); `endpoint` = the plan requirement's endpoint wording
(the coordinator treats endpoint as modality-agnostic and carries RNA/protein in `modality`, as in its own
example fixtures); the study's literal contrast text is preserved in `payload.contrast_text`. Whether such
records are comparable is still decided by the coordinator's checks (alignment basis, matched subjects,
normalization basis) — the extractor never sets those.

Every record carries provenance to the exact corpus location (`corpus://<file>#<locator>`), the
gene/entity, species, context, modality, study, subject/specimen/timepoint where available, and
the contrast (handoff §1 provenance list). Model calls go through the shared UsageClient.
"""
from __future__ import annotations

import csv
import io
import json
import statistics
from pathlib import Path

from integration.llm import structured

STUDY_METADATA_SCHEMA = {
    "type": "object",
    "required": ["study_id", "species", "context", "tissue", "condition", "contrast", "tables", "rna_protein_same_specimen", "normalization_basis_cross_modal", "notes"],
    "properties": {
        "study_id": {"type": "string"},
        "species": {"type": "string", "description": "canonical id of the MEASURED cells/tissue, e.g. homo_sapiens, mus_musculus"},
        "context": {"type": "string", "enum": ["in_vitro", "in_vivo", "patient"]},
        "host_species": {"type": ["string", "null"]},
        "tissue": {"type": ["string", "null"], "description": "use the plan requirement's tissue wording when the study matches that requirement"},
        "condition": {"type": ["string", "null"], "description": "use the plan requirement's condition wording when the study matches that requirement"},
        "contrast": {"type": "object", "required": ["case", "reference", "label"], "properties": {"case": {"type": "string"}, "reference": {"type": "string"},
                     "label": {"type": "string", "enum": ["perturbed_vs_reference", "reference_vs_perturbed", "other"],
                               "description": "NORMALIZATION POLICY: the contrast label encodes direction semantics only (perturbed/disease condition vs its reference). The specific perturbation is carried in `condition` and reconciled by the plan's context-alignment basis. This follows the coordinator's own fixture convention (one shared contrast string across contexts)."}}},
        "tables": {"type": "array", "items": {"type": "object", "required": ["file", "kind"], "properties": {
            "file": {"type": "string"},
            "kind": {"type": "string", "enum": ["differential_expression", "per_specimen_values", "specimen_metadata", "other"]},
            "modality": {"type": ["string", "null"], "enum": ["RNA", "protein", "phenotype", None]},
            "endpoint": {"type": ["string", "null"], "description": "use the plan requirement's endpoint wording when it matches"},
            "gene_column": {"type": ["string", "null"]}, "effect_column": {"type": ["string", "null"]}, "padj_column": {"type": ["string", "null"]},
            "gene_symbol_species": {"type": ["string", "null"]},
            "value_column": {"type": ["string", "null"]}, "specimen_column": {"type": ["string", "null"]},
            "participant_column": {"type": ["string", "null"]}, "timepoint_column": {"type": ["string", "null"]},
            "arm_column": {"type": ["string", "null"]}, "case_arm_value": {"type": ["string", "null"]}, "reference_arm_value": {"type": ["string", "null"]}}}},
        "rna_protein_same_specimen": {"type": "boolean", "description": "true ONLY if the methods state RNA and protein were measured on the same specimens"},
        "normalization_basis_cross_modal": {"type": ["string", "null"], "description": "a stated basis on which RNA and protein changes are comparable; null if the methods give none"},
        "notes": {"type": "string"}}}

EXTRACT_SYSTEM = (
    "You are the extraction stage of a cross-context evidence system. You receive ONE study's methods excerpt, "
    "the list of its data files with their header rows, and the frozen research plan's evidence requirements. "
    "Return structured study metadata ONLY from what the excerpt states. Do not infer participants, pairing, "
    "tissues or conditions that are not written. Where the study clearly matches a plan requirement, use that "
    "requirement's exact endpoint / condition / tissue wording so records normalize to the plan; otherwise use "
    "the study's own wording. Mark rna_protein_same_specimen true only if the text says both assays were run on "
    "the same specimens. Leave a field null when the excerpt does not state it.")

PADJ_ALPHA = 0.05


def _rows(text): return list(csv.DictReader(io.StringIO(text)))


def _direction(effect: float, padj: float | None) -> str:
    if padj is not None and padj > PADJ_ALPHA: return "unchanged"
    return "increase" if effect > 0 else ("decrease" if effect < 0 else "unchanged")


def _symbol_for(entity: str, species: str, packages: dict) -> str | None:
    """Map a plan gene to the symbol used in a table of `species`, using the pipeline's orthology output."""
    if species == "homo_sapiens": return entity
    pkg = packages.get(entity)
    if not pkg: return None
    ortho = pkg["sources"].get("ensembl_orthology", {}).get(species, {})
    one2one = (ortho.get("data") or {}).get("one2one", [])
    return one2one[0].get("target_symbol") if len(one2one) == 1 else None


def extract_observations(tools, plan, packages: dict, client, model: str) -> tuple[list[dict], list[dict]]:
    """Returns (EvidenceRecord dicts, stage_trace)."""
    files = tools.list_files()["files"]
    studies = sorted({f.split("/")[0] for f in files if f.endswith("/methods.md")})
    genes = list(plan.genes)
    reqs = [r.model_dump() for r in plan.requirements]
    records, trace = [], []
    for sd in studies:
        data_files = [f for f in files if f.startswith(sd + "/") and not f.endswith("methods.md")]
        heads = {f: tools.read_file(f)["content"].splitlines()[0] for f in data_files if f.endswith(".csv")}
        methods = tools.read_file(f"{sd}/methods.md")["content"]
        meta = structured(client, model=model, stage=f"extract:{sd}", system=EXTRACT_SYSTEM,
                          user={"study_dir": sd, "methods_text": methods, "data_files": data_files, "csv_headers": heads, "plan_requirements": reqs},
                          tool_name="study_metadata", schema=STUDY_METADATA_SCHEMA)
        trace.append({"study": sd, "metadata": meta})
        spec_tab = next((t for t in meta["tables"] if t["kind"] == "specimen_metadata"), None)
        specimens = _rows(tools.read_file(spec_tab["file"])["content"]) if spec_tab else []
        by_spec = {s[spec_tab["specimen_column"]]: s for s in specimens} if spec_tab else {}
        for t in meta["tables"]:
            if t["kind"] == "differential_expression":
                rows = _rows(tools.read_file(t["file"])["content"])
                for g in genes:
                    sym = _symbol_for(g, t.get("gene_symbol_species") or meta["species"], packages)
                    row = next((r for r in rows if sym and r.get(t["gene_column"]) == sym), None)
                    if row is None:
                        trace.append({"study": sd, "gene": g, "note": f"no row for symbol {sym!r} in {t['file']}"}); continue
                    eff = float(row[t["effect_column"]]); padj = float(row[t["padj_column"]]) if t.get("padj_column") else None
                    records.append(_record(f"obs-{sd}-{g}", sd, g, meta, t, direction=_direction(eff, padj),
                                           provenance=[f"corpus://{t['file']}#row:{t['gene_column']}={sym}", f"corpus://{sd}/methods.md#section:methods"],
                                           payload={"symbol_in_table": sym, "effect": eff, "padj": padj, "effect_column": t["effect_column"]}))
            elif t["kind"] == "per_specimen_values" and spec_tab:
                rows = _rows(tools.read_file(t["file"])["content"])
                for g in genes:
                    sym = _symbol_for(g, meta["species"], packages)
                    per = {}
                    for r in rows:
                        if r.get(t["gene_column"]) != sym: continue
                        s = by_spec.get(r[t["specimen_column"]])
                        if not s: continue
                        pid = s.get(spec_tab["participant_column"]); arm = s.get(spec_tab["arm_column"])
                        key = "case" if arm == spec_tab["case_arm_value"] else ("reference" if arm == spec_tab["reference_arm_value"] else None)
                        if pid and key:
                            per.setdefault(pid, {})[key] = (float(r[t["value_column"]]), r[t["specimen_column"]], s.get(spec_tab["timepoint_column"]))
                    diffs = []
                    for pid, v in sorted(per.items()):
                        if {"case", "reference"} <= v.keys():
                            d = v["case"][0] - v["reference"][0]; diffs.append(d)
                            records.append(_record(f"obs-{sd}-{g}-{t['modality']}-{pid}", sd, g, meta, t, direction=_direction(d, None),
                                                   subject_id=pid, specimen_id=v["case"][1], timepoint=v["case"][2],
                                                   provenance=[f"corpus://{t['file']}#row:{t['specimen_column']}={v['case'][1]};{t['gene_column']}={sym}",
                                                               f"corpus://{spec_tab['file']}#row:{spec_tab['participant_column']}={pid}", f"corpus://{sd}/methods.md#section:methods"],
                                                   payload={"paired_difference": round(d, 4), "case_specimen": v["case"][1], "reference_specimen": v["reference"][1]}))
                    if diffs:
                        records.append(_record(f"obs-{sd}-{g}-{t['modality']}-aggregate", sd, g, meta, t, direction=_direction(statistics.mean(diffs), None),
                                               provenance=[f"corpus://{t['file']}#row:{t['gene_column']}={sym}", f"corpus://{sd}/methods.md#section:methods"],
                                               payload={"n_participants": len(diffs), "mean_paired_difference": round(statistics.mean(diffs), 4), "aggregate_of": "per-participant paired differences"}))
    return records, trace


def _record(rid, study, entity, meta, table, *, direction, provenance, payload, subject_id=None, specimen_id=None, timepoint=None) -> dict:
    return {"id": rid, "source": f"corpus:{study}", "source_version": None, "retrieved_at": None, "provenance": provenance,
            "entity": entity, "species": meta["species"], "context": meta["context"], "modality": table.get("modality"),
            "endpoint": table.get("endpoint"), "condition": meta.get("condition"), "tissue": meta.get("tissue"), "host_species": meta.get("host_species"),
            "level": "observation", "study_id": meta["study_id"], "subject_id": subject_id, "specimen_id": specimen_id, "timepoint": timepoint,
            "direction": direction, "contrast": meta["contrast"]["label"], "unit": "direction",
            "comparability_key": f"{entity}|{table.get('endpoint')}",
            "normalization_basis": meta.get("normalization_basis_cross_modal"),
            "payload": {**payload, "contrast_text": f"{meta['contrast']['case']} vs {meta['contrast']['reference']}", "extractor_notes": meta.get("notes")}}
