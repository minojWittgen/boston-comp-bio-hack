#!/usr/bin/env python3
"""PRIMARY suite grader: mechanical checks + a blind human review sheet, then unblind and summarise.

  python bench/grade_primary.py runs/<batch> --no-unblind   # writes review.json (blind); reviewer fills it in
  python bench/grade_primary.py runs/<batch>                # re-runs checks (preserving reviewer decisions), unblinds, summary.json

Mechanical rows (from the frozen rubric, never from a system's output):
  integrity, execution, conclusion:<comparison>, citations_resolve, unsupported_corroboration, task_completion
Human review (review.json, per run, blind): five research-quality dimensions scored 0|1|2, plus four
critical errors answered true|false, plus blinding clues. Reviewer decisions are preserved on regrade.

Research quality is the dimension score. The mechanical rows are objective checks, not a quality
score, and are reported separately — a run can be mechanically clean and still score 0 on relevance.
Critical errors are listed, never averaged: one invented citation is the finding, not a deduction.

Per docs/investigation-first-handoff.md, no credit is given for a system's own `criteria_met` flag,
a longer report, or a conclusive answer. A coordinator run is now routinely `complete` (research done)
while its biological `assessment.conclusion` is `not_assessable`; those are two different axes and
neither is scored from the other.

Usage is reported separately from research quality and comes only from the harness-signed record.
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
# Research-quality dimensions, scored 0 (absent/wrong) | 1 (partial) | 2 (adequate).
# Source: docs/investigation-first-handoff.md "Benchmark handoff". Replaces the previous four
# pass/fail dimensions, which assumed a biological verdict was the deliverable.
DIMS = ["relevant_findings", "faithfulness", "traceability", "context", "uncertainty"]
SCORES = (0, 1, 2)
# Tracked separately and never netted off against the dimension scores: one of these in an
# otherwise good report is the finding, not an average.
CRITICAL = ["invented_citation_or_value", "cohort_to_individual_claim",
            "orthology_to_conservation_claim", "technical_failure_as_biological_absence"]


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
        bid = bp.stem; k = key["runs"].get(bid, {}); cid = k.get("case_id")
        try:
            o = load(bp); cid = o.get("case_id", cid); malformed = None
        except Exception as e:  # noqa: BLE001  malformed JSON: failed run, stays in the denominator
            o, malformed = None, f"unreadable output: {e!r}"[:200]
        if cid not in rubric: continue
        integrity = k.get("blind_sha256") == sha256_file(bp)
        up = batch / "usage" / f"{bid}.json"; usage, usage_ok = None, False
        if up.exists():
            try:
                u = load(up); usage_ok = sign(secret, u["usage"]) == u["sig"] and u["usage"].get("harness_signed") is True
                usage = u["usage"] if usage_ok else None      # unverified usage is never used (§4)
            except Exception:  # noqa: BLE001
                usage, usage_ok = None, False
        case_dir = ROOT / "primary" / "cases" / cid; manifest = load(case_dir / "manifest.json")
        try:
            if malformed: raise ValueError(malformed)
            rows = grade(o, rubric[cid], case_dir, manifest, usage, usage_ok, integrity and usage_ok)
        except Exception as e:  # noqa: BLE001  any grading exception = failed run; other runs continue
            rows = {"integrity": (integrity and usage_ok, ""), "execution": (False, f"malformed answer: {e!r}"[:300])}
            for cc in rubric[cid]["expected"]: rows[f"conclusion:{cc}"] = (False, "malformed answer")
            for rr in ("citations_resolve", "unsupported_corroboration", "task_completion"): rows[rr] = (False, "malformed answer")
        mech[bid] = {"case_id": cid, "rows": {r: {"result": "pass" if v[0] else "fail", "reason": v[1]} for r, v in rows.items()}, "usage_verified": usage_ok}
        pr = prior.get(bid, {})
        review[bid] = {"case_id": cid, "purpose": rubric[cid]["purpose"], "review_prompts": rubric[cid].get("review_prompts", {}),
                       "_scale": "score each dimension 0 (absent/wrong) | 1 (partial) | 2 (adequate)",
                       "dimensions": {d: pr.get("dimensions", {}).get(d, {"score": None, "note": ""}) for d in DIMS},
                       "critical_errors": {c: pr.get("critical_errors", {}).get(c, {"present": None, "note": ""}) for c in CRITICAL},
                       "blinding_clues": pr.get("blinding_clues", ""), "reviewer": pr.get("reviewer", "")}
    dump(batch / "scorecard.json", {"mechanical": mech}); dump(batch / "review.json", review)
    pending = sum(1 for r in review.values() for d in r["dimensions"].values() if d.get("score") not in SCORES)
    pending += sum(1 for r in review.values() for c in r["critical_errors"].values() if not isinstance(c.get("present"), bool))
    print(f"mechanical checks → {batch/'scorecard.json'}; review sheet → {batch/'review.json'} ({pending} review decisions pending; "
          f"open blind/<id>.json + the corpus, set each dimension score to 0|1|2 and each critical error present true|false; record any blinding clues)")
    if a.no_unblind: return
    if pending: print("NOTE: unscored dimensions count as 0 and unanswered critical errors count as unresolved.")
    per, usage_by, unverified, scores, crits = {}, {}, {}, {}, {}
    for bid, g in mech.items():
        k = key["runs"][bid]; s, cid = k["system"], k["case_id"]
        rv = review[bid]
        dim = {d: (rv["dimensions"][d].get("score") if rv["dimensions"][d].get("score") in SCORES else 0) for d in DIMS}
        # a critical error is "clear" only when the reviewer explicitly answered false
        crit = {c: rv["critical_errors"][c].get("present") for c in CRITICAL}
        clean = all(v is False for v in crit.values())
        mech_ok = all(v["result"] == "pass" for v in g["rows"].values())
        for r, v in g["rows"].items(): per.setdefault(s, {}).setdefault(cid, {}).setdefault(r, []).append(v["result"] == "pass")
        per.setdefault(s, {}).setdefault(cid, {}).setdefault("ALL_MECHANICAL", []).append(mech_ok)
        for d in DIMS: scores.setdefault(s, {}).setdefault(cid, {}).setdefault(d, []).append(dim[d])
        for c in CRITICAL:
            if crit[c] is True: crits.setdefault(s, {}).setdefault(c, []).append(f"{cid}:{bid}")
        up = batch / "usage" / f"{bid}.json"
        if g["usage_verified"] and up.exists(): usage_by.setdefault(s, []).append((load(up)["usage"], mech_ok and clean))
        else: unverified.setdefault(s, []).append(bid)
    summary = {"_read_me": "PRIMARY suite (same task + same source corpus; each system extracts on its own). Raw counts. "
                           "One execution per case is a demonstration, not an estimate. Research quality is the five 0-2 "
                           "review dimensions; mechanical rows are objective checks, not a quality score. Critical errors "
                           "are listed separately and are never averaged away. No credit is given for a system's own "
                           "criteria_met flag, a longer report, or a conclusive answer. Usage totals include ONLY "
                           "harness-verified records.",
               "usage_unavailable_runs": unverified,
               "correctness": {s: {cid: {r: f"{sum(v)}/{len(v)}" for r, v in rows.items()} for cid, rows in cases.items()} for s, cases in per.items()},
               "review_scores": {s: {cid: {d: (f"{sum(v)}/{2 * len(v)}" if v else "0/0") for d, v in dims.items()}
                                     for cid, dims in cases.items()} for s, cases in scores.items()},
               "review_totals": {s: (lambda flat: {"score": f"{sum(flat)}/{2 * len(flat)}" if flat else "0/0"})(
                                     [x for cases_ in [cases] for dims in cases_.values() for v in dims.values() for x in v])
                                 for s, cases in scores.items()},
               "critical_errors": crits,
               "usage": {}, "blinding_clues": {bid: r["blinding_clues"] for bid, r in review.items() if r["blinding_clues"]}}
    for s, runs in usage_by.items():
        tot = [u["input_tokens"] + u["output_tokens"] for u, _ in runs]
        summary["usage"][s] = {"runs": len(runs), "mechanical_clean_runs": f"{sum(1 for _, p in runs if p)}/{len(runs)}", "models": sorted({u['model'] for u, _ in runs}),
                               "llm_calls": sum(u["llm_calls"] for u, _ in runs), "input_tokens": sum(u["input_tokens"] for u, _ in runs),
                               "cache_read": sum(u["cache_read_tokens"] for u, _ in runs), "cache_creation": sum(u["cache_creation_tokens"] for u, _ in runs),
                               "output_tokens": sum(u["output_tokens"] for u, _ in runs), "data_tool_calls": sum(u["data_tool_calls"] for u, _ in runs),
                               "wall_clock_s": round(sum(u["wall_clock_s"] for u, _ in runs), 1), "tokens_median_per_run": round(statistics.median(tot)) if tot else 0,
                               "estimated_cost_usd": round(sum((u.get("estimated_cost_usd") or 0) for u, _ in runs), 4)}
    dump(batch / "summary.json", summary); print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
