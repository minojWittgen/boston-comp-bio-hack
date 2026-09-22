#!/usr/bin/env python3
"""PRIMARY suite grader: mechanical checks + a blind human review sheet, then unblind and summarise.

  python bench/grade_primary.py runs/<batch> --no-unblind   # writes review.json (blind); reviewer fills it in
  python bench/grade_primary.py runs/<batch>                # re-runs checks (preserving reviewer decisions), unblinds, summary.json

Mechanical rows (from the frozen rubric, never from a system's output):
  integrity, execution, conclusion:<comparison>, citations_resolve, unsupported_corroboration, task_completion
Human rows (review.json, per run, blind): the four scoring dimensions, each pass/fail + note, plus blinding clues.
Final per-run pass requires every mechanical row AND all four human rows. Reviewer decisions are preserved on regrade.
Usage is reported separately from scientific quality and comes only from the harness-signed record.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HELD_OUT, ROOT, SCHEMA, Usage, dump, load, sha256_file, sign  # noqa: E402
from primary_common import CorpusTools  # noqa: E402

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None
REPORT_SCHEMA = load(SCHEMA / "report.schema.json")
DIMS = ["scoped_conclusion_correctness", "evidence_correctness", "comparability_and_uncertainty", "task_completion"]


def grade(o, rub, case_dir, manifest, usage, usage_ok, integrity_ok):
    rows, unsupported = {}, []
    rows["integrity"] = (integrity_ok, "" if integrity_ok else "blind file or usage record altered/unsigned")
    lim = manifest["limits"]; over = []
    if usage:
        if usage["output_tokens"] > lim["max_output_tokens_total"]: over.append("output tokens over cumulative limit")
        if usage["data_tool_calls"] > lim["max_data_tool_calls"]: over.append("data-tool calls over limit")
        if usage["wall_clock_s"] > lim["wall_clock_seconds"]: over.append("wall clock over deadline")
    errs = [e.message for e in Draft202012Validator(REPORT_SCHEMA).iter_errors({**o, "system": "x"})] if Draft202012Validator else []
    done = o["execution_status"] == "completed"
    rows["execution"] = (done and usage_ok and not over and not errs, "; ".join(([] if done else [o["execution_status"]]) + over + errs[:2]))
    if not done:
        for cid in rub["expected"]: rows[f"conclusion:{cid}"] = (False, "no report")
        rows["citations_resolve"] = (False, "no report"); rows["unsupported_corroboration"] = (False, "no report"); rows["task_completion"] = (False, "no report")
        return rows
    tools = CorpusTools(manifest, case_dir, Usage("grader", {**lim, "max_data_tool_calls": 10**6, "max_bookkeeping_calls": 10**6, "wall_clock_seconds": 10**6}))
    comps = {c["comparison_id"]: c for c in o["comparisons"]}
    text_all = lambda c: (c["statement"] + " " + o["report_markdown"]).lower()  # noqa: E731
    for cid, exp in rub["expected"].items():
        c = comps.get(cid)
        if c is None: rows[f"conclusion:{cid}"] = (False, "comparison missing"); continue
        why = []
        if c["conclusion"] != exp["conclusion"]: why.append(f"{c['conclusion']} != {exp['conclusion']}")
        if c["conclusion"] in exp.get("forbidden", []): unsupported.append(f"{cid}: forbidden '{c['conclusion']}'")
        if "within_person" in exp and c.get("within_person") != exp["within_person"]: why.append(f"within_person={c.get('within_person')} expected {exp['within_person']}")
        cited = {x["file"] for x in c["citations"]}
        miss = [f for f in exp.get("must_cite_files", []) if f not in cited]
        if miss: why.append(f"must cite {miss}")
        if c["conclusion"] != "insufficient_evidence" and not c["citations"]: unsupported.append(f"{cid}: {c['conclusion']} with no citation")
        for pat in exp.get("must_mention", []):
            if not re.search(pat, text_all(c)): why.append(f"does not mention /{pat}/")
        rows[f"conclusion:{cid}"] = (not why, "; ".join(why))
    bad = [f"{x['file']}@{x['locator']}" for c in o["comparisons"] for x in c["citations"] if not tools.resolve_citation(x["file"], x["locator"])]
    rows["citations_resolve"] = (not bad, "; ".join(bad[:5]))
    for rule in rub.get("unsupported_corroboration_rules", []):
        if rule == "within_person=true" and comps.get("patient_rna_vs_patient_protein_within_person", {}).get("within_person") is True: unsupported.append(rule)
        if rule == "in_vitro_vs_animal marked supported" and comps.get("in_vitro_vs_animal", {}).get("conclusion") == "supported": unsupported.append(rule)
        if rule == "within-person comparison marked supported" and comps.get("patient_rna_vs_patient_protein_within_person", {}).get("conclusion") == "supported": unsupported.append(rule)
    rows["unsupported_corroboration"] = (not unsupported, "; ".join(unsupported))
    missing_comp = [cid for cid in rub["expected"] if cid not in comps]
    rows["task_completion"] = (not missing_comp and bool(o["report_markdown"].strip()) and isinstance(o["limitations"], list),
                               "; ".join((["missing comparisons: " + ", ".join(missing_comp)] if missing_comp else []) + ([] if o["report_markdown"].strip() else ["empty report"])))
    return rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("batch"); ap.add_argument("--no-unblind", action="store_true"); a = ap.parse_args()
    batch = Path(a.batch); key = load(batch / "key.json"); secret = key["_secret"]
    rubric = {c["case_id"]: c for c in load(HELD_OUT / "primary_rubric.json")["cases"]}
    prior = load(batch / "review.json") if (batch / "review.json").exists() else {}
    review, mech = {}, {}
    for bp in sorted((batch / "blind").glob("*.json")):
        bid = bp.stem; o = load(bp); cid = o["case_id"]
        if cid not in rubric: continue
        k = key["runs"][bid]; integrity = k["blind_sha256"] == sha256_file(bp)
        up = batch / "usage" / f"{bid}.json"; usage, usage_ok = None, False
        if up.exists():
            u = load(up); usage = u["usage"]; usage_ok = sign(secret, usage) == u["sig"] and usage.get("harness_signed") is True
        case_dir = ROOT / "primary" / "cases" / cid; manifest = load(case_dir / "manifest.json")
        rows = grade(o, rubric[cid], case_dir, manifest, usage, usage_ok, integrity and usage_ok)
        mech[bid] = {"case_id": cid, "rows": {r: {"result": "pass" if v[0] else "fail", "reason": v[1]} for r, v in rows.items()}}
        pr = prior.get(bid, {})
        review[bid] = {"case_id": cid, "purpose": rubric[cid]["purpose"], "review_prompts": rubric[cid].get("review_prompts", {}),
                       "dimensions": {d: pr.get("dimensions", {}).get(d, {"result": None, "note": ""}) for d in DIMS},
                       "blinding_clues": pr.get("blinding_clues", ""), "reviewer": pr.get("reviewer", "")}
    dump(batch / "scorecard.json", {"mechanical": mech}); dump(batch / "review.json", review)
    pending = sum(1 for r in review.values() for d in r["dimensions"].values() if d["result"] is None)
    print(f"mechanical checks → {batch/'scorecard.json'}; review sheet → {batch/'review.json'} ({pending} dimension decisions pending; open blind/<id>.json + the corpus, fill result pass|fail + note; record any blinding clues)")
    if a.no_unblind: return
    if pending: print("NOTE: pending review decisions count as NOT passed.")
    per, usage_by = {}, {}
    for bid, g in mech.items():
        k = key["runs"][bid]; s, cid = k["system"], k["case_id"]
        allp = all(v["result"] == "pass" for v in g["rows"].values()) and all(review[bid]["dimensions"][d]["result"] == "pass" for d in DIMS)
        for r, v in g["rows"].items(): per.setdefault(s, {}).setdefault(cid, {}).setdefault(r, []).append(v["result"] == "pass")
        for d in DIMS: per[s][cid].setdefault(f"review:{d}", []).append(review[bid]["dimensions"][d]["result"] == "pass")
        per[s][cid].setdefault("ALL", []).append(allp)
        up = batch / "usage" / f"{bid}.json"
        if up.exists(): usage_by.setdefault(s, []).append((load(up)["usage"], allp))
    summary = {"_read_me": "PRIMARY suite (same task + same source corpus; each system extracts on its own). Raw counts. One execution per case is a demonstration, not an estimate. Scientific quality and usage are reported separately.",
               "correctness": {s: {cid: {r: f"{sum(v)}/{len(v)}" for r, v in rows.items()} for cid, rows in cases.items()} for s, cases in per.items()},
               "usage": {}, "blinding_clues": {bid: r["blinding_clues"] for bid, r in review.items() if r["blinding_clues"]}}
    for s, runs in usage_by.items():
        tot = [u["input_tokens"] + u["output_tokens"] for u, _ in runs]
        summary["usage"][s] = {"runs": len(runs), "ALL_pass": f"{sum(1 for _, p in runs if p)}/{len(runs)}", "models": sorted({u['model'] for u, _ in runs}),
                               "llm_calls": sum(u["llm_calls"] for u, _ in runs), "input_tokens": sum(u["input_tokens"] for u, _ in runs),
                               "cache_read": sum(u["cache_read_tokens"] for u, _ in runs), "cache_creation": sum(u["cache_creation_tokens"] for u, _ in runs),
                               "output_tokens": sum(u["output_tokens"] for u, _ in runs), "data_tool_calls": sum(u["data_tool_calls"] for u, _ in runs),
                               "wall_clock_s": round(sum(u["wall_clock_s"] for u, _ in runs), 1), "tokens_median_per_run": round(statistics.median(tot)) if tot else 0,
                               "estimated_cost_usd": round(sum((u.get("estimated_cost_usd") or 0) for u, _ in runs), 4)}
    dump(batch / "summary.json", summary); print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
