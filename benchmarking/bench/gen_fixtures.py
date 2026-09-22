#!/usr/bin/env python3
"""Generate every manifest + fixture from bench/spec.json (v2, post-review).

  python bench/gen_fixtures.py --stub                        # no network; synthetic package in the real shape
  python bench/gen_fixtures.py --live --cache .xctx-cache    # real pipeline (XCTX_PIPELINE + network)
  python bench/gen_fixtures.py --from-package runs/<id>/TYK2.json
  python bench/gen_fixtures.py ... --limits final            # use spec.limits_final for xctx-001..003

Design (review §1, §5):
  * The claim is a directional mRNA comparison; axes are answered separately.
  * Every case has in-vitro, in-vivo (mouse, with species/tissue/endpoint/contrast), patient RNA and
    patient protein observations. Patient samples carry participant_id, specimen_id, timepoint.
  * Case 3's recoverable required observation is the IN-VIVO dataset (status unavailable); the
    recovered observation has an OPPOSING effect under a declared comparable contrast. GTEx is untouched.
  * The evidence package is never modified. If it were, _provenance.modified_fields would say so and
    the original would be kept beside it.
  * Every dataset carries provenance.synthetic. Nothing in a fixture is presented as real data.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BENCHMARK, CASES, FIXTURES, dump, import_pipeline, load  # noqa: E402

SPEC = load(Path(__file__).with_name("spec.json"))
NOW = dt.datetime.now(dt.timezone.utc).isoformat()
ORIGIN = "bench/gen_fixtures.py from bench/spec.json (synthetic)"

INSTRUCTION = ("Answer each axis in task.axes separately with a verdict, the observation_ids / reference keys "
               "it rests on, and the contrast-alignment basis. Then give an overall verdict consistent with the "
               "axes. Use only the provided datasets and evidence package, plus the listed tools under the stated "
               "retry policy. Report how you interpreted every non-ok reference-source status. Call submit_answer once.")
RETRY_POLICY = ("If a dataset marked required has status `unavailable`, call fetch_dataset(dataset_id) exactly once. "
                "If a reference source in the evidence package has status `error`, you may call build_evidence_package "
                "once. `not_found` and `skipped` do not change on retry.")


# ------------------------------------------------------------------ evidence package (reference context)
def sr(source, status, query, data=None, error=None, version=None, cache_hit=True):
    return {"source": source, "status": status, "query": query, "data": data, "error": error,
            "source_version": version, "retrieved_at": NOW, "cache_hit": cache_hit}


def stub_package(symbol, disease, mode, run_id, *, mouse="ok", impc="ok", rat="not_found",
                 gtex_tissues=None, ensg=None, mouse_symbol=None):
    ensg = ensg or SPEC["ensg"]; mouse_symbol = mouse_symbol or SPEC["mouse_symbol"]
    tissues = gtex_tissues or SPEC["gtex_reference"]["tissues"]

    def ortho(sp):
        st = {"mus_musculus": mouse, "rattus_norvegicus": rat, "macaca_mulatta": "ok"}[sp]
        if st == "not_found":
            return sr("ensembl_orthology", "not_found", {"ensg": ensg, "target_species": sp}, {"orthologs": []})
        typ = "ortholog_one2many" if st == "one2many" else "ortholog_one2one"
        o = {"target_id": f"ENS{sp[:3].upper()}G0000000001", "species": sp, "type": typ, "perc_id_target": 80.0,
             "perc_id_source": 80.0, "target_symbol": mouse_symbol if sp == "mus_musculus" else symbol}
        orth = [o, {**o, "target_id": o["target_id"][:-1] + "2"}] if st == "one2many" else [o]
        return sr("ensembl_orthology", "ok", {"ensg": ensg, "target_species": sp},
                  {"orthologs": orth, "one2one": [x for x in orth if x["type"] == "ortholog_one2one"]})

    gene = sr("mygene", "ok", {"symbol": symbol}, {"symbol": symbol, "name": symbol, "entrez": 0,
                                                    "ensembl_ids": [ensg], "ensembl_primary": ensg, "ambiguous": False})
    gtex = sr("gtex", "ok", {"ensg": ensg, "dataset": "gtex_v8"},
              {"gencodeId": f"{ensg}.12", "tissues": sorted(tissues, key=lambda r: -r["median_tpm"])}, None, "gtex_v8")
    impc_r = (sr("impc", "not_found", {"mouse_symbol": mouse_symbol}, {"phenotyped": False}) if impc == "not_found"
              else sr("impc", "ok", {"mouse_symbol": mouse_symbol}, {"phenotyped": True, "n_tests": 412, "hits": SPEC["impc_hits"]}))
    try:
        S, C, P = import_pipeline()
        import tempfile
        S.normalize_gene = lambda s: gene
        S.ensembl_orthologs = lambda e, sp: ortho(sp)
        S.gtex_expression = lambda e: gtex
        S.impc_phenotypes = lambda sym: impc_r
        S.opentargets_target = lambda e: sr("opentargets", "ok", {"ensg": e}, {"id": e, "associatedDiseases": {"rows": []}})
        S.pubmed_search = lambda s, d: sr("pubmed", "ok", {"term": s}, {"count": 0, "pmids": []})
        pkg = P.build_package(symbol, disease, mode, run_id, C.JsonCache(tempfile.mkdtemp()))
    except FileNotFoundError:
        print("  (pipeline repo not found; building package shape by hand)", file=sys.stderr)
        srcs = {"ensembl_orthology": {sp: ortho(sp) for sp in ("mus_musculus", "rattus_norvegicus", "macaca_mulatta")}}
        srcs["impc"] = impc_r if mouse == "ok" else sr("impc", "skipped", {}, None, f"no unique one2one mouse ortholog (mouse orthology {mouse})")
        srcs["gtex"] = gtex
        srcs["opentargets"] = sr("opentargets", "skipped", {}, None, "disabled in eval mode")
        srcs["pubmed"] = sr("pubmed", "skipped", {}, None, "disabled in eval mode")
        missing = [{"source": "ensembl_orthology", "sub": sp, "status": r["status"], "reason": r.get("error")}
                   for sp, r in srcs["ensembl_orthology"].items() if r["status"] != "ok"]
        missing += [{"source": n, "sub": None, "status": r["status"], "reason": r.get("error")}
                    for n, r in srcs.items() if n != "ensembl_orthology" and r["status"] != "ok"]
        pkg = {"schema_version": "0.1", "run": {"run_id": run_id, "mode": mode, "disease_query": disease,
                                                "enabled_sources": ["ensembl_orthology", "gtex", "impc"], "built_at": NOW},
               "gene": gene, "sources": srcs, "summary": {}, "missing": missing}
    pkg["_provenance"] = {"origin": "stub: build_package with stubbed fetchers (values synthetic)", "synthetic": True,
                          "modified_fields": [], "original_path": None}
    return pkg


def live_package(symbol, disease, mode, run_id, cache_dir):
    S, C, P = import_pipeline()
    pkg = P.build_package(symbol, disease, mode, run_id, C.JsonCache(cache_dir))
    pkg["_provenance"] = {"origin": f"live build_package run {run_id}", "synthetic": False, "modified_fields": [], "original_path": None}
    return pkg


# ------------------------------------------------------------------ observation datasets
def paired_samples(rng, participants, spec_prefix, log2fc, noise=0.15, base=(4.0, 6.0)):
    """Per-specimen values; the aggregate effect is COMPUTED from them (review: no repeated aggregate)."""
    samples, deltas = [], []
    for pid in participants:
        b = rng.uniform(*base); d = log2fc + rng.gauss(0, noise)
        samples.append({"participant_id": pid, "specimen_id": f"{spec_prefix}-{pid}-NL", "timepoint": "baseline", "arm": "reference", "value": round(b, 3)})
        samples.append({"participant_id": pid, "specimen_id": f"{spec_prefix}-{pid}-L", "timepoint": "baseline", "arm": "case", "value": round(b + d, 3)})
        deltas.append(d)
    return samples, round(statistics.mean(deltas), 3)


def dataset(dataset_id, context, species, modality, obs, status="available", reason=None, modified=None):
    return {"dataset_id": dataset_id, "status": status, "unavailable_reason": reason, "context": context,
            "species": species, "modality": modality,
            "provenance": {"synthetic": True, "origin": ORIGIN, "modified_fields": modified or [], "original_path": None},
            "observations": obs}


def obs_invitro():
    iv = SPEC["invitro"]
    return {"observation_id": "obs_invitro_rna_tyk2", "gene": SPEC["gene"], "tissue": "epidermal keratinocytes (2D culture)",
            "model_or_cohort": iv["model"],
            "contrast": {"name": "treated_vs_control", "case": iv["perturbation"], "reference": iv["reference"], "alignment_basis": None},
            "endpoint": "mRNA abundance (log2 CPM)", "method": iv["method"],
            "effect": {"log2fc": iv["log2fc"], "padj": iv["padj"], "direction": "up", "n_case": iv["n_case"], "n_reference": iv["n_reference"], "aggregate_of": None}}


def obs_invivo(oppose: bool):
    v = SPEC["invivo"]; l2 = v["log2fc_oppose"] if oppose else v["log2fc_agree"]
    return {"observation_id": "obs_invivo_rna_tyk2_imq", "gene": SPEC["mouse_symbol"], "tissue": v["tissue"],
            "model_or_cohort": v["model"],
            "contrast": {"name": "imq_vs_vehicle", "case": "imiquimod-treated dorsal skin, day 6", "reference": v["reference"], "alignment_basis": v["alignment_basis"]},
            "endpoint": "mRNA abundance (log2 CPM)", "method": v["method"],
            "effect": {"log2fc": l2, "padj": v["padj"], "direction": "down" if l2 < 0 else "up", "n_case": v["n_case"], "n_reference": v["n_reference"], "aggregate_of": None}}


def obs_patient(rng, modality, participants, spec_prefix):
    p = SPEC["patient_rna"] if modality == "rna" else SPEC["patient_prot"]
    samples, l2 = paired_samples(rng, participants, spec_prefix, p["log2fc"])
    return {"observation_id": f"obs_patient_{modality}_tyk2", "gene": SPEC["gene"], "tissue": SPEC["tissue_human"],
            "model_or_cohort": p["cohort"],
            "contrast": {"name": "lesional_vs_nonlesional", "case": "lesional plaque biopsy", "reference": "non-lesional biopsy, same participant, same visit",
                         "alignment_basis": "disease-vs-reference tissue contrast in the target organ; endpoint comparable to the in-vitro mRNA endpoint" if modality == "rna" else None},
            "endpoint": "mRNA abundance (log2 CPM)" if modality == "rna" else "protein abundance (Olink NPX, log2 scale)",
            "method": p["method"],
            "effect": {"log2fc": l2, "padj": p["padj"], "direction": "up" if l2 > 0 else "down", "n_case": len(participants), "n_reference": len(participants), "aggregate_of": "samples"},
            "samples": samples, "cohort_summary": dict(SPEC["cohort_summary"])}


# ------------------------------------------------------------------ manifests
def manifest(case_id, mode, run_id, datasets, limits, fd, note=None, claim=None, axes=None, gene=None):
    m = {"case_id": case_id, "schema_version": "2.0", "mode": mode}
    if note: m["_note"] = note
    files = [f"{fd}/evidence_package.json"] + [d["path"] for d in datasets]
    m.update({
        "task": {"claim": claim or SPEC["claim"], "claim_contrast": SPEC["claim_contrast"], "axes": axes or SPEC["axes"],
                 "instruction": INSTRUCTION, "checklist": SPEC["checklist"], "output_schema": "../schema/agent_output.schema.json"},
        "gene": gene or {"symbol": SPEC["gene"], "disease": SPEC["disease"]},
        "evidence_package": {"path": f"{fd}/evidence_package.json", "run_id": run_id, "produced_by": "xctx-evidence.build_package", "role": "reference_context"},
        "datasets": datasets, "input_allowlist": files,
        "tools": {"available": ["read_file", "fetch_dataset", "build_evidence_package"], "stub_responses": f"{fd}/tool_stub.json", "retry_policy": RETRY_POLICY},
        "limits": limits})
    return m


def ds_entry(fd, i, ctx, species, mod, status="available", required=True):
    return {"id": i, "context": ctx, "species": species, "modality": mod, "path": f"{fd}/{i}.json", "status": status, "required": required}


def tool_stub(symbol, disease, fetch_map):
    key = json.dumps({"symbol": symbol, "disease": disease, "mode": "eval"}, separators=(",", ":"), sort_keys=True)
    return {"_note": "HARNESS-ONLY. Not in input_allowlist; read_file refuses it.",
            "fetch_dataset": {k: {"sequence": v} for k, v in fetch_map.items()},
            "build_evidence_package": {key: {"sequence": ["evidence_package.json"]}, "default": {"status": "error", "error": "stub: unexpected arguments"}}}


def gen_cases(base_pkg, limits_final):
    g, d = SPEC["gene"], SPEC["disease"]
    P = [f"P{i:02d}" for i in range(1, 13)]; Q = [f"Q{i:02d}" for i in range(1, 13)]
    recipes = {
        "xctx-000": dict(mode="explore", invivo="agree", prot_ids=P, prot_prefix="S", limits=SPEC["limits_dev"], note="DEVELOPMENT EXAMPLE ONLY. Check feasibility of the deadline here; never graded."),
        "xctx-001": dict(mode="eval", invivo="agree", prot_ids=P, prot_prefix="S", limits=limits_final),
        "xctx-002": dict(mode="eval", invivo="agree", prot_ids=Q, prot_prefix="T", limits=limits_final),
        "xctx-003": dict(mode="eval", invivo="unavailable_then_oppose", prot_ids=P, prot_prefix="S", limits=limits_final),
    }
    for cid, r in recipes.items():
        rng = random.Random(cid); fdir = FIXTURES / cid; fd = f"../fixtures/{cid}"
        pkg = copy.deepcopy(base_pkg); pkg["run"]["mode"] = r["mode"]; pkg["run"]["run_id"] = f"gen-{cid}"
        dump(fdir / "evidence_package.json", pkg)
        dump(fdir / "invitro_rna.json", dataset("invitro_rna", "in_vitro", "Homo sapiens", "rna", [obs_invitro()]))
        if r["invivo"] == "agree":
            dump(fdir / "invivo_rna.json", dataset("invivo_rna", "in_vivo", "Mus musculus", "rna", [obs_invivo(False)]))
            invivo_status, fetch_map = "available", {}
        else:
            dump(fdir / "invivo_rna.json", dataset("invivo_rna", "in_vivo", "Mus musculus", "rna", [], status="unavailable",
                                                   reason="retrieval error: object-store timeout fetching invivo_rna (transient, retryable)"))
            dump(fdir / "invivo_rna.recovered.json", dataset("invivo_rna", "in_vivo", "Mus musculus", "rna", [obs_invivo(True)]))
            invivo_status, fetch_map = "unavailable", {"invivo_rna": ["invivo_rna.recovered.json"]}
        dump(fdir / "patient_rna.json", dataset("patient_rna", "patient", "Homo sapiens", "rna", [obs_patient(rng, "rna", P, "S")]))
        dump(fdir / "patient_prot.json", dataset("patient_prot", "patient", "Homo sapiens", "protein", [obs_patient(rng, "protein", r["prot_ids"], r["prot_prefix"])]))
        dump(fdir / "tool_stub.json", tool_stub(g, d, fetch_map))
        datasets = [ds_entry(fd, "invitro_rna", "in_vitro", "Homo sapiens", "rna"),
                    ds_entry(fd, "invivo_rna", "in_vivo", "Mus musculus", "rna", status=invivo_status),
                    ds_entry(fd, "patient_rna", "patient", "Homo sapiens", "rna"),
                    ds_entry(fd, "patient_prot", "patient", "Homo sapiens", "protein")]
        dump(CASES / f"{cid}.json", manifest(cid, r["mode"], f"gen-{cid}", datasets, r["limits"], fd, r.get("note")))
        print(f"  wrote {cid}")


def gen_literature(pkg_fn, limits):
    lit = load(BENCHMARK / "literature_cases.json")
    for row in lit["rows"]:
        cid = row["id"]; fdir = FIXTURES / cid; fd = f"../../fixtures/{cid}"
        dump(fdir / "evidence_package.json", pkg_fn(row["human_symbol"], cid, row.get("pipeline_checks", {})))
        dump(fdir / "narrative.json", {"dataset_id": "narrative", "status": "available", "context": "literature",
                                       "provenance": {"synthetic": False, "origin": "already-interpreted findings summarised from the cited papers; tests judgment over supplied summaries, NOT reproduction from raw data"},
                                       "gene": row["human_symbol"], "program": row["gene_or_program"], "axis": row["axis"],
                                       "in_vitro_finding": row["in_vitro_finding"], "in_vivo_finding": row["in_vivo_finding"], "patient_finding": row["patient_finding"]})
        dump(fdir / "tool_stub.json", tool_stub(row["human_symbol"], "", {}))
        datasets = [{"id": "narrative", "context": "literature", "species": "Homo sapiens", "modality": "narrative", "path": f"{fd}/narrative.json", "status": "available", "required": True}]
        axes = [{"axis_id": "literature_axis", "question": f"On the {row['axis'].replace('_', ' ')} axis, does the in-vitro finding for {row['gene_or_program']} persist? Answer from the supplied summaries.",
                 "datasets": ["narrative"], "requires_matched_participants": False}]
        m = manifest(cid, "eval", cid, datasets, limits, fd,
                     claim=f"[Literature summary case] {row['in_vitro_finding']}", axes=axes,
                     gene={"symbol": row["human_symbol"], "disease": ""})
        m["task"]["claim_contrast"] = {"gene": row["human_symbol"], "endpoint": "as described in narrative", "direction": "up", "origin_dataset": "narrative"}
        dump(CASES / "lit" / f"{cid}.json", m)
        print(f"  wrote {cid} ({row['bucket']})")


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--stub", action="store_true"); src.add_argument("--live", action="store_true"); src.add_argument("--from-package")
    ap.add_argument("--cache", default=".xctx-cache")
    ap.add_argument("--limits", choices=["dev", "final"], default="final")
    ap.add_argument("--no-lit", action="store_true")
    a = ap.parse_args()
    limits = SPEC["limits_final"] if a.limits == "final" else SPEC["limits_dev"]
    g, d = SPEC["gene"], SPEC["disease"]
    if a.from_package:
        base = load(a.from_package)
        base.setdefault("_provenance", {"origin": f"frozen package {a.from_package}", "synthetic": False, "modified_fields": [], "original_path": a.from_package})
    elif a.live:
        base = live_package(g, d, "eval", "gen-live", a.cache)
    else:
        base = stub_package(g, d, "eval", "gen-stub")
    print("cases:"); gen_cases(base, limits)
    if not a.no_lit:
        print("literature:")
        if a.live:
            fn = lambda sym, rid, pc: live_package(sym, "", "eval", rid, a.cache)  # noqa: E731
        else:
            fn = lambda sym, rid, pc: stub_package(sym, "", "eval", rid, mouse=pc.get("mouse_orthology", "ok"), impc=pc.get("impc", "ok"),  # noqa: E731
                                                  ensg=f"ENSG_{sym}", mouse_symbol=sym.capitalize(), gtex_tissues=pc.get("gtex_tissues") or SPEC["gtex_reference"]["tissues"])
        gen_literature(fn, limits)
    print("done. held_out/ untouched.")


if __name__ == "__main__":
    main()
