#!/usr/bin/env python3
"""Grade a batch of BLIND outputs, then unblind and summarise.

  python bench/grade.py runs/<batch>                 # auto rows + review list, then summary
  python bench/grade.py runs/<batch> --no-unblind    # stop before opening key.json

Auto-gradable rows are decided here (verdict, citations, tool-count rules, retrieval, schema,
limits). `must_detect` items are keyword-matched and flagged for a human to confirm; the
scorecard records both the auto result and the reviewer's override.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BENCHMARK, CASES, HELD_OUT, ROOT, dump, load  # noqa: E402

try:
    from jsonschema import Draft202012Validator
except ImportError:  # grading still works, completion row degrades to a structural check
    Draft202012Validator = None

OUT_SCHEMA = load(ROOT / "schema/agent_output.schema.json")


def text_of(o):
    return (o.get("rationale", "") + " " + " ".join(o.get("caveats", []))).lower()


def cites(o, source):
    return any(c["source"].split(".")[0] == source.split(".")[0] or c["source"] == source
               for c in o.get("evidence_cited", []))


def kw(text, *groups):
    """every group must match at least one of its alternatives"""
    return all(any(re.search(alt, text) for alt in g) for g in groups)


def validate_schema(o, limits):
    errs = []
    if Draft202012Validator:
        chk = dict(o); chk["configuration"] = "A"  # blind placeholder
        errs = [e.message for e in Draft202012Validator(OUT_SCHEMA).iter_errors(chk)]
    else:
        errs = [k for k in OUT_SCHEMA["required"] if k not in o]
    u = o["usage"]
    if u["tool_calls"] > limits["max_tool_calls"]:
        errs.append("max_tool_calls exceeded")
    if u["wall_clock_s"] > limits["wall_clock_seconds"]:
        errs.append("wall_clock exceeded")
    if u.get("network_calls", 0) > 0:
        errs.append("live network calls made")
    return errs


# ------------------------------------------------------------------ xctx cases
def grade_xctx(o, ref, limits):
    rows, review = {}, []
    t = text_of(o)
    sit = ref["situation"]
    ok_verdict = o["verdict"] in ref["accepted_verdicts"]

    # conclusion
    if sit == "invalid_patient_pairing":
        tie = kw(t, [r"patient[_ ]id", r"disjoint", r"different patients", r"not the same patients", r"pairing"])
        rows["conclusion"] = (ok_verdict and tie, "verdict ok" if ok_verdict else f"verdict={o['verdict']}" + ("" if tie else "; rationale does not tie to pairing"))
    else:
        rows["conclusion"] = (ok_verdict, "" if ok_verdict else f"verdict={o['verdict']} not in {ref['accepted_verdicts']}")

    # evidence: must_cite + must_not
    missing = [c["source"] for c in ref["must_cite"] if not cites(o, c["source"])]
    viol = []
    n_build = sum(1 for a in o["actions_taken"] if a["tool"] == "build_evidence_package")
    if sit == "recoverable_missing_then_disagreement" and n_build > 2:
        viol.append("build_evidence_package called >2 times")
    if sit == "invalid_patient_pairing":
        if o["verdict"] == "persists":
            viol.append("reported persists despite invalid pairing")
        if any("cohort_summary" in c["locator"] and c["supports"] == "comparability_check" for c in o["evidence_cited"]):
            viol.append("cited cohort_summary as evidence cohorts are the same")
    if sit == "recoverable_missing_then_disagreement" and o["verdict"] == "persists":
        viol.append("persists while mandatory source was error / contradicting")
    if kw(t, [r"not_found.*(negative|absent|no expression|not expressed)"]):
        viol.append("treated not_found as biological negative")
    rows["evidence"] = (not missing and not viol, "; ".join((["missing cites: " + ", ".join(missing)] if missing else []) + viol))

    # completion
    errs = validate_schema(o, limits)
    rows["completion"] = (not errs, "; ".join(errs))

    # case-3 extra rows
    if sit == "recoverable_missing_then_disagreement":
        retr = any(a["tool"] == "build_evidence_package" and a["args"].get("mode") == "eval"
                   and a["result_status"] == "ok" for a in o["actions_taken"]) and cites(o, "gtex")
        rows["retrieval"] = (retr, "" if retr else "no successful eval-mode re-run cited")
        rep = kw(t, [r"gtex"], [r"contradict", r"disagree", r"not expressed", r"against", r"low.*(skin|tissue)", r"tpm\s*=?\s*0"])
        rows["reporting_after_recovery"] = (rep, "" if rep else "recovered gtex disagreement not reported")

    # must_detect: keyword-assisted, human-confirmed
    for item in ref["must_detect"]:
        pats = ref.get("must_detect_keywords", {}).get(item, [])
        hit = any(re.search(p, t) for p in pats) if pats else None
        review.append({"item": item, "auto": hit, "confirm": None})
    return rows, review


# ------------------------------------------------------------------ literature rows
def grade_lit(o, row, limits):
    rows = {}
    ok = o["verdict"] == row["documented_verdict"]
    rows["conclusion"] = (ok, "" if ok else f"{o['verdict']} != {row['documented_verdict']}")
    mo = row["pipeline_checks"].get("mouse_orthology")
    if mo == "not_found":
        rows["status_semantics"] = (o["verdict"] == "not_comparable" and cites(o, "ensembl_orthology"),
                                    "no mouse ortholog must map to not_comparable with orthology cited")
    errs = validate_schema(o, limits)
    rows["completion"] = (not errs, "; ".join(errs))
    return rows, []


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--no-unblind", action="store_true")
    a = ap.parse_args()
    batch = Path(a.batch)

    refs = {c["case_id"]: c for c in load(HELD_OUT / "reference_answers.json")["cases"]}
    lit = {r["id"]: r for r in load(BENCHMARK / "literature_cases.json")["rows"]}
    limits_of = {p.stem: load(p)["limits"] for p in list(CASES.glob("*.json")) + list((CASES / "lit").glob("*.json"))}

    graded = {}
    for bp in sorted((batch / "blind").glob("*.json")):
        o = load(bp)
        cid = o["case_id"]
        if cid in refs:
            rows, review = grade_xctx(o, refs[cid], limits_of[cid])
        elif cid in lit:
            rows, review = grade_lit(o, lit[cid], limits_of[cid])
        else:
            continue
        graded[bp.stem] = {"case_id": cid, "rows": {k: {"result": "pass" if v[0] else "fail", "reason": v[1]} for k, v in rows.items()},
                           "must_detect_review": review, "usage": o["usage"], "verdict": o["verdict"]}
    dump(batch / "scorecard.json", {"entries": graded})
    print(f"graded {len(graded)} outputs -> {batch / 'scorecard.json'}")
    nrev = sum(1 for g in graded.values() for r in g["must_detect_review"] if r["auto"] is not True)
    if nrev:
        print(f"  {nrev} must_detect items need human confirmation (auto keyword miss or no keywords). Edit scorecard.json 'confirm' fields.")
    if a.no_unblind:
        return

    key = load(batch / "key.json")
    per = {}  # config -> case -> row -> [pass?]
    usage = {}  # config -> list of (tokens, all_pass, tool_calls)
    for bid, g in graded.items():
        k = key[bid]; cfg, cid = k["configuration"], k["case_id"]
        allpass = all(r["result"] == "pass" for r in g["rows"].values())
        for row, r in g["rows"].items():
            per.setdefault(cfg, {}).setdefault(cid, {}).setdefault(row, []).append(r["result"] == "pass")
        u = g["usage"]
        usage.setdefault(cfg, []).append((u["input_tokens"] + u["output_tokens"], allpass, u["tool_calls"], u["wall_clock_s"]))

    summary = {"correctness": {}, "efficiency": {}, "literature_by_bucket": {}}
    for cfg, cases in per.items():
        summary["correctness"][cfg] = {cid: {row: f"{sum(v)}/{len(v)}" for row, v in rows.items()} for cid, rows in cases.items()}
    for cfg, runs in usage.items():
        toks = [r[0] for r in runs]; passes = sum(1 for r in runs if r[1])
        summary["efficiency"][cfg] = {
            "runs": len(runs), "all_rows_pass": passes,
            "total_tokens_mean": round(statistics.mean(toks)), "total_tokens_median": round(statistics.median(toks)),
            "tokens_per_pass": round(sum(toks) / passes) if passes else "inf",
            "tool_calls_mean": round(statistics.mean(r[2] for r in runs), 2),
            "wall_clock_s_mean": round(statistics.mean(r[3] for r in runs), 1)}
    if "A" in usage and "B" in usage:
        summary["efficiency"]["b_over_a_token_ratio"] = round(
            summary["efficiency"]["B"]["total_tokens_mean"] / max(1, summary["efficiency"]["A"]["total_tokens_mean"]), 2)
    # literature agreement per bucket
    for cfg, cases in per.items():
        buckets = {}
        for cid, rows in cases.items():
            if cid in lit:
                b = lit[cid]["bucket"]; v = rows.get("conclusion", [])
                buckets.setdefault(b, [0, 0]); buckets[b][0] += sum(v); buckets[b][1] += len(v)
        if buckets:
            summary["literature_by_bucket"][cfg] = {b: f"{p}/{n}" for b, (p, n) in buckets.items()}
    dump(batch / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
