#!/usr/bin/env python3
"""Layer 0: is the PIPELINE producing what the literature rows expect?

Run this before grading any agent — an agent can't be blamed for a package that's wrong.

  python bench/pipeline_bench.py --live --cache .xctx-cache   # real APIs (needs XCTX_PIPELINE)
  python bench/pipeline_bench.py --from-dir fixtures          # check already-generated packages
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BENCHMARK, FIXTURES, import_pipeline, load  # noqa: E402


def check(pkg: dict, pc: dict) -> list[str]:
    fails = []
    mo = pkg["sources"]["ensembl_orthology"]["mus_musculus"]
    exp = pc.get("mouse_orthology")
    if exp == "not_found" and mo["status"] != "not_found":
        fails.append(f"mouse orthology expected not_found, got {mo['status']}")
    elif exp == "ok" and mo["status"] != "ok":
        fails.append(f"mouse orthology expected ok, got {mo['status']}")
    elif exp == "one2many":
        n121 = len((mo.get("data") or {}).get("one2one", []))
        if mo["status"] != "ok" or n121 == 1:
            fails.append(f"mouse orthology expected ok with no unique one2one, got status={mo['status']} n_one2one={n121}")
    if pc.get("rat_orthology") and pkg["sources"]["ensembl_orthology"]["rattus_norvegicus"]["status"] != pc["rat_orthology"]:
        fails.append("rat orthology status mismatch")
    impc = pkg["sources"]["impc"]["status"]
    if pc.get("impc") not in (None, "any") and impc != pc["impc"]:
        fails.append(f"impc expected {pc['impc']}, got {impc}")
    g = pkg["sources"]["gtex"]
    if g["status"] == "ok":
        tissues = g["data"]["tissues"]
        top = tissues[0]["tissue"] if tissues else ""
        if pc.get("gtex_top_tissue_contains") and pc["gtex_top_tissue_contains"].lower() not in top.lower():
            fails.append(f"gtex top tissue expected to contain {pc['gtex_top_tissue_contains']}, got {top}")
        if pc.get("gtex_low_in"):
            v = next((t["median_tpm"] for t in tissues if t["tissue"] == pc["gtex_low_in"]), None)
            if v is None or v > 2:
                fails.append(f"gtex expected low in {pc['gtex_low_in']}, got {v}")
        if pc.get("gtex_low_everywhere") and tissues and tissues[0]["median_tpm"] > 5:
            fails.append(f"gtex expected low everywhere, top={tissues[0]}")
    else:
        fails.append(f"gtex status {g['status']}: {g.get('error')}")
    # invariant: eval mode never carries opentargets/pubmed data
    for s in ("opentargets", "pubmed"):
        if pkg["run"]["mode"] == "eval" and pkg["sources"][s]["status"] != "skipped":
            fails.append(f"LEAK: {s} is {pkg['sources'][s]['status']} in eval mode")
    return fails


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--live", action="store_true")
    g.add_argument("--from-dir")
    ap.add_argument("--cache", default=".xctx-cache")
    a = ap.parse_args()
    rows = load(BENCHMARK / "literature_cases.json")["rows"]
    bad = 0
    for row in rows:
        if a.live:
            S, C, P = import_pipeline()
            pkg = P.build_package(row["human_symbol"], "", "eval", "pipeline-bench", C.JsonCache(a.cache))
        else:
            pkg = load(Path(a.from_dir) / row["id"] / "evidence_package.json")
        fails = check(pkg, row["pipeline_checks"])
        bad += bool(fails)
        print(f"{'FAIL' if fails else 'ok  '} {row['id']} {row['human_symbol']:8s} {row['bucket']:18s} {'; '.join(fails)}")
    print(f"\n{len(rows) - bad}/{len(rows)} rows match pipeline expectations")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
