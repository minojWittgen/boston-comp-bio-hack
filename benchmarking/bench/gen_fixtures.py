#!/usr/bin/env python3
"""Generate every manifest + fixture from bench/spec.json.

  python bench/gen_fixtures.py --stub                 # no network; synthetic packages in the real shape
  python bench/gen_fixtures.py --live --cache .cache  # run the real pipeline (needs XCTX_PIPELINE + network)
  python bench/gen_fixtures.py --from-package runs/<run_id>/TYK2.json   # use a frozen real package

Writes:
  fixtures/xctx-00N/{evidence_package.json, invitro_rna.json, patient_rna.json, patient_prot.json, tool_stub.json}
  fixtures/xctx-003/evidence_package.recovered.json
  fixtures/lit-NN/{evidence_package.json, narrative.json, tool_stub.json}   + cases/lit/lit-NN.json
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BENCHMARK, CASES, FIXTURES, ROOT, dump, import_pipeline, load  # noqa: E402

SPEC = load(Path(__file__).with_name("spec.json"))
NOW = dt.datetime.now(dt.timezone.utc).isoformat()

INSTRUCTION = ("Using only the evidence package and context datasets provided (and the listed tools "
               "if you judge more evidence is needed), decide whether the in-vitro finding described "
               "in the claim is corroborated across the in-vivo and patient contexts. Return one "
               "verdict from allowed_verdicts with cited evidence, caveats, and every action you took, "
               "in the shape given by output_schema.")


# ------------------------------------------------------------------ evidence packages
def sr(source, status, query, data=None, error=None, version=None, cache_hit=True):
    return {"source": source, "status": status, "query": query, "data": data, "error": error,
            "source_version": version, "retrieved_at": NOW, "cache_hit": cache_hit}


def stub_package(symbol, disease, mode, run_id, *, mouse="ok", impc="ok", gtex="ok", rat="not_found",
                 gtex_tissues=None, ensg=None, mouse_symbol=None):
    """Build a package THROUGH the repo's package.build_package with fetchers stubbed, so the shape is
    always the real one. Falls back to a hand-built package if the repo isn't importable."""
    ensg = ensg or SPEC["ensg"]
    mouse_symbol = mouse_symbol or SPEC["mouse_symbol"]
    tissues = gtex_tissues or SPEC["gtex_ok"]["tissues"]

    def ortho(sp):
        st = {"mus_musculus": mouse, "rattus_norvegicus": rat, "macaca_mulatta": "ok"}[sp]
        if st == "not_found":
            return sr("ensembl_orthology", "not_found", {"ensg": ensg, "target_species": sp}, {"orthologs": []})
        typ = "ortholog_one2many" if st == "one2many" else "ortholog_one2one"
        o = {"target_id": f"ENS{sp[:3].upper()}G0000000001", "species": sp, "type": typ,
             "perc_id_target": 80.0, "perc_id_source": 80.0,
             "target_symbol": mouse_symbol if sp == "mus_musculus" else symbol}
        orth = [o, {**o, "target_id": o["target_id"][:-1] + "2"}] if st == "one2many" else [o]
        return sr("ensembl_orthology", "ok", {"ensg": ensg, "target_species": sp},
                  {"orthologs": orth, "one2one": [x for x in orth if x["type"] == "ortholog_one2one"]})

    def gtex_fn(_):
        if gtex == "error":
            return sr("gtex", "error", {"ensg": ensg, "dataset": "gtex_v8"}, None,
                      "HTTPError('502 Server Error: Bad Gateway for url: https://gtexportal.org/api/v2/...')",
                      "gtex_v8", cache_hit=False)
        return sr("gtex", "ok", {"ensg": ensg, "dataset": "gtex_v8"},
                  {"gencodeId": f"{ensg}.12", "tissues": sorted(tissues, key=lambda r: -r["median_tpm"])}, None, "gtex_v8")

    def impc_fn(sym):
        if impc == "not_found":
            return sr("impc", "not_found", {"mouse_symbol": sym}, {"phenotyped": False})
        return sr("impc", "ok", {"mouse_symbol": sym},
                  {"phenotyped": True, "n_tests": 412, "hits": SPEC["impc_hits"]})

    gene = sr("mygene", "ok", {"symbol": symbol},
              {"symbol": symbol, "name": symbol, "entrez": 0, "ensembl_ids": [ensg],
               "ensembl_primary": ensg, "ambiguous": False})
    try:
        S, C, P = import_pipeline()
        import tempfile
        S.normalize_gene = lambda s: gene
        S.ensembl_orthologs = lambda e, sp: ortho(sp)
        S.gtex_expression = gtex_fn
        S.impc_phenotypes = impc_fn
        S.opentargets_target = lambda e: sr("opentargets", "ok", {"ensg": e}, {"id": e, "associatedDiseases": {"rows": []}})
        S.pubmed_search = lambda s, d: sr("pubmed", "ok", {"term": s}, {"count": 0, "pmids": []})
        return P.build_package(symbol, disease, mode, run_id, C.JsonCache(tempfile.mkdtemp()))
    except FileNotFoundError:
        print("  (pipeline repo not found; building package shape by hand)", file=sys.stderr)
        srcs = {"ensembl_orthology": {sp: ortho(sp) for sp in ("mus_musculus", "rattus_norvegicus", "macaca_mulatta")}}
        srcs["impc"] = impc_fn(mouse_symbol) if mouse == "ok" else sr("impc", "skipped", {}, None, f"no unique one2one mouse ortholog (mouse orthology {mouse})")
        srcs["gtex"] = gtex_fn(ensg)
        srcs["opentargets"] = sr("opentargets", "skipped", {}, None, "disabled in eval mode")
        srcs["pubmed"] = sr("pubmed", "skipped", {}, None, "disabled in eval mode")
        missing = [{"source": n, "sub": None, "status": r["status"], "reason": r.get("error")}
                   for n, r in srcs.items() if n != "ensembl_orthology" and r["status"] != "ok"]
        missing = [{"source": "ensembl_orthology", "sub": sp, "status": r["status"], "reason": r.get("error")}
                   for sp, r in srcs["ensembl_orthology"].items() if r["status"] != "ok"] + missing
        return {"schema_version": "0.1",
                "run": {"run_id": run_id, "mode": mode, "disease_query": disease,
                        "enabled_sources": ["ensembl_orthology", "gtex", "impc"], "built_at": NOW},
                "gene": gene, "sources": srcs, "summary": {}, "missing": missing}


def live_package(symbol, disease, mode, run_id, cache_dir):
    S, C, P = import_pipeline()
    return P.build_package(symbol, disease, mode, run_id, C.JsonCache(cache_dir))


def break_gtex(pkg):
    """Case 3: make gtex `error` the way the real pipeline would (not cached, retryable)."""
    p = copy.deepcopy(pkg)
    p["sources"]["gtex"] = sr("gtex", "error", p["sources"]["gtex"]["query"], None,
                              "HTTPError('502 Server Error: Bad Gateway for url: https://gtexportal.org/api/v2/...')",
                              "gtex_v8", cache_hit=False)
    if "gtex_top_tissues" in p.get("summary", {}):
        p["summary"]["gtex_top_tissues"] = []
    p["missing"] = [m for m in p["missing"] if m["source"] != "gtex"] + [
        {"source": "gtex", "sub": None, "status": "error", "reason": p["sources"]["gtex"]["error"]}]
    return p


def swap_gtex(pkg, tissues):
    p = copy.deepcopy(pkg)
    p["sources"]["gtex"]["data"]["tissues"] = sorted(tissues, key=lambda r: -r["median_tpm"])
    if "gtex_top_tissues" in p.get("summary", {}):
        p["summary"]["gtex_top_tissues"] = p["sources"]["gtex"]["data"]["tissues"][:5]
    return p


# ------------------------------------------------------------------ context fixtures
def samples(ids, effect, rng):
    out = []
    for pid in ids:
        base = rng.uniform(4, 6)
        out.append({"patient_id": pid, "condition": "nonlesional", "value": round(base, 3)})
        out.append({"patient_id": pid, "condition": "lesional", "value": round(base + effect["log2fc"] + rng.gauss(0, 0.15), 3)})
    return out


def patient_fixture(dataset_id, modality, ids, effect, platform, rng):
    return {"dataset_id": dataset_id, "context": "patient", "modality": modality,
            "gene": SPEC["gene"], "disease": SPEC["disease"], "tissue": SPEC["tissue_gtex"],
            "cohort_summary": {"n_patients": SPEC["cohort"]["n_patients"], "age_mean": SPEC["cohort"]["age_mean"],
                               "sex_ratio_f": SPEC["cohort"]["sex_ratio_f"], "site": SPEC["cohort"]["site"],
                               "platform": platform},
            "effect": {"comparison": "lesional_vs_nonlesional", **effect},
            "samples": samples(ids, effect, rng)}


def invitro_fixture():
    iv = SPEC["invitro"]
    return {"dataset_id": "invitro_rna", "context": "in_vitro", "modality": "rna", "gene": SPEC["gene"],
            "model": iv["model"], "perturbation": iv["perturbation"],
            "effect": {"comparison": "treated_vs_control", "log2fc": iv["log2fc"], "padj": iv["padj"],
                       "direction": iv["direction"], "n_replicates": iv["n_replicates"]}}


def tool_stub(symbol, disease, sequence):
    key = json.dumps({"symbol": symbol, "disease": disease, "mode": "eval"}, separators=(",", ":"), sort_keys=True)
    return {"build_evidence_package": {key: {"sequence": sequence},
                                       "default": {"status": "error", "error": "stub: unexpected arguments"}}}


def manifest(case_id, mode, run_id, ctx, limits, note=None, fixture_dir=None):
    fd = fixture_dir or f"../fixtures/{case_id}"
    m = {"case_id": case_id, "schema_version": "1.0", "mode": mode}
    if note:
        m["_note"] = note
    m.update({
        "task": {"claim": SPEC["claim"], "instruction": INSTRUCTION,
                 "allowed_verdicts": ["persists", "partially_persists", "diverges", "not_comparable"],
                 "output_schema": "../schema/agent_output.schema.json"},
        "gene": {"symbol": SPEC["gene"], "disease": SPEC["disease"]},
        "evidence_package": {"path": f"{fd}/evidence_package.json", "run_id": run_id,
                             "produced_by": "xctx-evidence.build_package"},
        "context_datasets": ctx, "tools": {"available": ["read_file", "build_evidence_package"],
                                           "stub_responses": f"{fd}/tool_stub.json"},
        "limits": limits})
    return m


STD_CTX = lambda fd: [  # noqa: E731
    {"id": "invitro_rna", "context": "in_vitro", "modality": "rna", "path": f"{fd}/invitro_rna.json",
     "description": "Bulk/pseudobulk RNA from the in-vitro model named in the claim, treated vs control."},
    {"id": "patient_rna", "context": "patient", "modality": "rna", "path": f"{fd}/patient_rna.json",
     "description": "Per-sample RNA from patient tissue, lesional vs non-lesional, with cohort summary."},
    {"id": "patient_prot", "context": "patient", "modality": "protein", "path": f"{fd}/patient_prot.json",
     "description": "Per-sample protein from patient tissue, lesional vs non-lesional, with cohort summary."}]


def gen_cases(base_pkg, limits_final):
    g, d = SPEC["gene"], SPEC["disease"]
    P_IDS = [f"P{i:02d}" for i in range(1, SPEC["cohort"]["n_patients"] + 1)]
    Q_IDS = [f"Q{i:02d}" for i in range(1, SPEC["cohort"]["n_patients"] + 1)]
    plat_r, plat_p = SPEC["cohort"]["platform_rna"], SPEC["cohort"]["platform_prot"]

    recipes = {
        "xctx-000": dict(mode="explore", pkg=base_pkg, prot_ids=P_IDS, seq=["evidence_package.json"],
                         limits=SPEC["limits_dev"], note="DEVELOPMENT EXAMPLE ONLY. Freeze limits here; never graded."),
        "xctx-001": dict(mode="eval", pkg=base_pkg, prot_ids=P_IDS, seq=["evidence_package.json"], limits=limits_final),
        "xctx-002": dict(mode="eval", pkg=base_pkg, prot_ids=Q_IDS, seq=["evidence_package.json"], limits=limits_final),
        "xctx-003": dict(mode="eval", pkg=break_gtex(base_pkg), prot_ids=P_IDS,
                         seq=["evidence_package.recovered.json"], limits=limits_final),
    }
    for cid, r in recipes.items():
        rng = random.Random(cid)
        fdir = FIXTURES / cid
        pkg = copy.deepcopy(r["pkg"])
        pkg["run"]["mode"] = r["mode"]
        pkg["run"]["run_id"] = f"gen-{cid}"
        dump(fdir / "evidence_package.json", pkg)
        if cid == "xctx-003":
            dump(fdir / "evidence_package.recovered.json", swap_gtex(base_pkg, SPEC["gtex_contradicting"]["tissues"]))
        dump(fdir / "invitro_rna.json", invitro_fixture())
        dump(fdir / "patient_rna.json", patient_fixture("patient_rna", "rna", P_IDS, SPEC["patient_effect"], plat_r, rng))
        dump(fdir / "patient_prot.json", patient_fixture("patient_prot", "protein", r["prot_ids"], SPEC["protein_effect"], plat_p, rng))
        dump(fdir / "tool_stub.json", tool_stub(g, d, r["seq"]))
        dump(CASES / f"{cid}.json", manifest(cid, r["mode"], f"gen-{cid}", STD_CTX(f"../fixtures/{cid}"), r["limits"], r.get("note")))
        print(f"  wrote {cid}")


# ------------------------------------------------------------------ literature rows
def gen_literature(mode_fn, limits_final):
    lit = load(BENCHMARK / "literature_cases.json")
    for row in lit["rows"]:
        cid = row["id"]
        fdir = FIXTURES / cid
        pc = row.get("pipeline_checks", {})
        pkg = mode_fn(row["human_symbol"], "", cid, pc)
        dump(fdir / "evidence_package.json", pkg)
        dump(fdir / "narrative.json", {
            "dataset_id": "narrative", "context": "literature", "gene": row["human_symbol"],
            "program": row["gene_or_program"], "axis": row["axis"],
            "in_vitro_finding": row["in_vitro_finding"], "in_vivo_finding": row["in_vivo_finding"],
            "patient_finding": row["patient_finding"]})
        dump(fdir / "tool_stub.json", tool_stub(row["human_symbol"], "", ["evidence_package.json"]))
        m = manifest(cid, "eval", cid, [
            {"id": "narrative", "context": "in_vitro", "modality": "narrative", "path": f"../../fixtures/{cid}/narrative.json",
             "description": "Reported findings for this gene/program in each context, as text."}],
            limits_final, fixture_dir=f"../../fixtures/{cid}")
        m["task"]["claim"] = (f"The in-vitro finding for {row['gene_or_program']} ({row['human_symbol']}) "
                              f"persists across the {row['axis'].replace('_', ' ')} axis.")
        m["gene"] = {"symbol": row["human_symbol"], "disease": ""}
        dump(CASES / "lit" / f"{cid}.json", m)
        print(f"  wrote {cid} ({row['bucket']})")


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--stub", action="store_true", help="synthetic packages in the real shape (no network)")
    src.add_argument("--live", action="store_true", help="run the real pipeline (network)")
    src.add_argument("--from-package", help="frozen real package for the Step-1 gene")
    ap.add_argument("--cache", default=".xctx-cache")
    ap.add_argument("--limits", help="JSON with frozen max_tool_calls/max_output_tokens/wall_clock_seconds")
    ap.add_argument("--no-lit", action="store_true")
    a = ap.parse_args()

    limits_final = load(a.limits) if a.limits else SPEC["limits_dev"]
    g, d = SPEC["gene"], SPEC["disease"]
    if a.from_package:
        base = load(a.from_package)
    elif a.live:
        base = live_package(g, d, "eval", "gen-live", a.cache)
    else:
        base = stub_package(g, d, "eval", "gen-stub")

    print("cases:")
    gen_cases(base, limits_final)
    if not a.no_lit:
        print("literature:")
        if a.live:
            fn = lambda sym, dis, rid, pc: live_package(sym, dis, "eval", rid, a.cache)  # noqa: E731
        else:
            fn = lambda sym, dis, rid, pc: stub_package(  # noqa: E731
                sym, dis, "eval", rid, mouse=pc.get("mouse_orthology", "ok"),
                impc=pc.get("impc", "ok"), ensg=f"ENSG_{sym}", mouse_symbol=sym.capitalize(),
                gtex_tissues=pc.get("gtex_tissues") or SPEC["gtex_ok"]["tissues"])
        gen_literature(fn, limits_final)
    print("done. held_out/ is untouched — keep it out of the agent's reach.")


if __name__ == "__main__":
    main()
