#!/usr/bin/env python3
"""Grade a batch (v2). Auto rows + human-confirmed rows, then unblind and summarise with RAW COUNTS.

  python bench/grade.py runs/<batch> --no-unblind   # grade; fill `confirm` on must_detect items in scorecard.json
  python bench/grade.py runs/<batch>                # re-grade (preserving confirms), unblind, summary.json

Review fixes:
  §3  human `confirm` values persist across regrades; mandatory confirmations gate all_rows_pass;
      status interpretation graded structurally; citations validated for exact source + resolvable locator +
      declared support relation; execution failures get no scientific credit.
  §4  usage read ONLY from the harness-signed copy; a tampered blind file or usage file fails `integrity`.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BENCHMARK, CASES, HELD_OUT, SCHEMA, dump, load, sha256_file, sign  # noqa: E402

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None
OUT_SCHEMA = load(SCHEMA / "agent_output.schema.json")


# ------------------------------------------------------------------ helpers
def resolve(obj, path: str):
    """JSON-path-lite: a/b/0/c  or  a.b.c ; returns (found, value)"""
    cur = obj
    for part in re.split(r"[./]", path):
        if part == "": continue
        if isinstance(cur, list) and part.isdigit() and int(part) < len(cur): cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return False, None
    return True, cur


def case_world(cid):
    """Everything a citation may point to for this case: datasets (initial + recovered) and package."""
    mp = (CASES / f"{cid}.json") if (CASES / f"{cid}.json").exists() else (CASES / "lit" / f"{cid}.json")
    m = load(mp); base = mp.parent
    pkg = load((base / m["evidence_package"]["path"]).resolve()); fdir = (base / m["evidence_package"]["path"]).resolve().parent
    obs, dsets = {}, {}
    for d in m["datasets"]:
        f = load((base / d["path"]).resolve()); dsets[d["id"]] = f
        for o in f.get("observations", []): obs[o["observation_id"]] = o
    stub = (base / m["tools"]["stub_responses"]).resolve()
    if stub.exists():
        for name, e in load(stub).get("fetch_dataset", {}).items():
            for fn in e["sequence"]:
                for o in load(fdir / fn).get("observations", []): obs[o["observation_id"]] = o
    refs = {"gtex", "impc", "mygene", "opentargets", "pubmed"} | {f"ensembl_orthology.{s}" for s in ("mus_musculus", "rattus_norvegicus", "macaca_mulatta")}
    return m, pkg, obs, dsets, refs


def locator_resolves(loc, src, pkg, obs, dsets):
    if src in obs:
        if loc == src: return True
        return resolve(obs[src], loc[len(src) + 1:])[0] if loc.startswith(src + "/") else resolve(obs[src], loc)[0]
    if src in dsets:
        return loc == src or resolve(dsets[src], loc)[0]
    # reference key
    key = src.split(".")
    node = pkg["sources"].get(key[0]) if key[0] != "mygene" else pkg["gene"]
    if node is None: return False
    if len(key) > 1: node = node.get(key[1]) if isinstance(node, dict) else None
    if node is None: return False
    loc2 = re.sub(r"^sources\.?" + re.escape(src) + r"[./]?", "", loc)
    return loc2 == "" or resolve(node, loc2)[0]


# ------------------------------------------------------------------ grading one run
def grade_run(o, ref, m, pkg, obs, dsets, refs, usage_ok, usage, integrity_ok, prior_review):
    rows, review = {}, []
    executed = o["execution_status"] == "completed"
    # execution & integrity
    rows["integrity"] = (integrity_ok, "" if integrity_ok else "blind file or usage record altered / unsigned")
    lim = m["limits"]; over = []
    if usage:
        if usage["output_tokens"] > lim["max_output_tokens_total"]: over.append("output tokens over cumulative limit")
        if usage["data_tool_calls"] > lim["max_data_tool_calls"]: over.append("data-tool calls over limit")
        if usage["bookkeeping_calls"] > lim["max_bookkeeping_calls"]: over.append("bookkeeping calls over limit")
        if usage["wall_clock_s"] > lim["wall_clock_seconds"]: over.append("wall clock over deadline")
        if usage["network_calls"] > 0: over.append("live network calls")
    errs = [e.message for e in Draft202012Validator(OUT_SCHEMA).iter_errors({**o, "configuration": "A", "usage": usage or {}})] if (Draft202012Validator and usage) else []
    rows["execution"] = (executed and usage_ok and not over and not errs, "; ".join(([] if executed else [f"execution_status={o['execution_status']}"]) + over + errs[:3]))
    if not executed:
        for ax in ref["expected_axes"]: rows[f"axis:{ax}"] = (False, "no completed answer")
        for r in ("overall", "unsupported_corroboration", "citation_validity", "status_interpretation", "required_actions"): rows[r] = (False, "no completed answer")
        return rows, review

    axes = {a["axis_id"]: a for a in o["axes"]}
    # per-axis
    unsupported = []
    for ax, exp in ref["expected_axes"].items():
        a = axes.get(ax)
        if a is None: rows[f"axis:{ax}"] = (False, "axis missing"); unsupported.append(f"{ax} missing"); continue
        ok = a["verdict"] in exp["accepted_verdicts"] and a["verdict"] not in exp.get("forbidden_verdicts", [])
        need = set(exp["required_evidence"]); have = set(a["evidence"])
        why = []
        if not ok: why.append(f"verdict={a['verdict']}")
        if a["verdict"] != "not_assessable":
            if not need <= have: why.append(f"missing required evidence {sorted(need - have)}"); unsupported.append(f"{ax}: {a['verdict']} without {sorted(need - have)}")
            if not a.get("contrast_alignment"): why.append("no contrast_alignment"); unsupported.append(f"{ax}: verdict without alignment basis")
            bad = [e for e in have if e not in obs and e not in refs and e not in dsets]
            if bad: why.append(f"unknown evidence {bad}"); unsupported.append(f"{ax}: unknown evidence {bad}")
        if a["verdict"] in exp.get("forbidden_verdicts", []): unsupported.append(f"{ax}: forbidden verdict {a['verdict']}")
        rows[f"axis:{ax}"] = (ok and not why, "; ".join(why))
    # overall
    ov = o["overall"]["verdict"]
    cons = not (ov == "persists" and any(a["verdict"] == "diverges" for a in axes.values()))
    rows["overall"] = (ov in ref["accepted_overall"] and cons, "" if ov in ref["accepted_overall"] and cons else f"overall={ov}" + ("" if cons else " while an axis diverges"))
    if not cons: unsupported.append("overall persists while an axis diverges")
    rows["unsupported_corroboration"] = (not unsupported, "; ".join(unsupported))
    # citations
    cite_probs = []
    for c in o["evidence_cited"]:
        if c["source"] not in obs and c["source"] not in refs and c["source"] not in dsets: cite_probs.append(f"unknown source {c['source']}"); continue
        if not locator_resolves(c["locator"], c["source"], pkg, obs, dsets): cite_probs.append(f"locator does not resolve: {c['source']} @ {c['locator']}")
        if c["source"] in refs and c["supports"] in ("claim", "against_claim"): cite_probs.append(f"reference source {c['source']} cited as {c['supports']} (reference data is background)")
        if c["source"] in obs and c["supports"] in ("claim", "against_claim"):
            d = obs[c["source"]]["effect"]["direction"]; want = m["task"]["claim_contrast"]["direction"]
            if (c["supports"] == "claim") != (d == want): cite_probs.append(f"{c['source']} direction {d} cited as {c['supports']}")
    for mc in ref["must_cite"]:
        if not any(c["source"] == mc["source"] for c in o["evidence_cited"]): cite_probs.append(f"must_cite missing: {mc['source']}")
    rows["citation_validity"] = (not cite_probs, "; ".join(cite_probs))
    # status interpretation (structural)
    si = o["status_interpretation"]; sp = []
    for k, v in ref["status_interpretation_expected"].items():
        if si.get(k) != v: sp.append(f"{k}: got {si.get(k)}, expected {v}")
    if any(v == "biological_negative" for v in si.values()): sp.append("biological_negative used")
    rows["status_interpretation"] = (not sp, "; ".join(sp))
    # required / bounded actions
    ap = []
    for ra in ref["required_actions"]:
        n = sum(1 for a in o["actions_taken"] if a["tool"] == ra["tool"] and all(a["args"].get(k) == v for k, v in ra["args_subset"].items()))
        if n < ra.get("min_calls", 0): ap.append(f"{ra['tool']}{ra['args_subset']} called {n} < {ra['min_calls']}")
        if n > ra["max_calls"]: ap.append(f"{ra['tool']}{ra['args_subset']} called {n} > {ra['max_calls']}")
    rows["required_actions"] = (not ap, "; ".join(ap))
    # must_detect (keyword-assisted, human-confirmed, confirms preserved)
    text = (o["overall"]["rationale"] + " " + " ".join(o["caveats"]) + " " + " ".join(a["note"] for a in o["axes"])).lower()
    prior = {r["id"]: r.get("confirm") for r in prior_review}
    for item in ref["must_detect"]:
        auto = any(re.search(p, text) for p in item.get("keywords", [])) if item.get("keywords") else None
        review.append({"id": item["id"], "text": item["text"], "mandatory": item["mandatory"], "auto": auto, "confirm": prior.get(item["id"])})
    return rows, review


def all_pass(entry):
    if not all(r["result"] == "pass" for r in entry["rows"].values()): return False
    for r in entry["must_detect_review"]:
        if r["mandatory"] and r["confirm"] is not True: return False  # unconfirmed or confirm:false never counts
    return True


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("batch"); ap.add_argument("--no-unblind", action="store_true"); a = ap.parse_args()
    batch = Path(a.batch)
    refs = {c["case_id"]: c for c in load(HELD_OUT / "reference_answers.json")["cases"]}
    lit = {r["id"]: r for r in load(BENCHMARK / "literature_cases.json")["rows"]}
    key = load(batch / "key.json"); secret = key["_secret"]
    prior = load(batch / "scorecard.json")["entries"] if (batch / "scorecard.json").exists() else {}
    graded = {}
    for bp in sorted((batch / "blind").glob("*.json")):
        bid = bp.stem; k = key["runs"].get(bid, {}); cid = k.get("case_id")
        try: o = load(bp); cid = o.get("case_id", cid); malformed = None
        except Exception as e: o, malformed = None, f"unreadable output: {e!r}"[:200]  # noqa: BLE001
        integrity = k.get("blind_sha256") == sha256_file(bp)
        up = batch / "usage" / f"{bid}.json"; usage, usage_ok = None, False
        if up.exists():
            try:
                u = load(up); usage_ok = (sign(secret, u["usage"]) == u["sig"]) and u["usage"].get("harness_signed") is True
                usage = u["usage"] if usage_ok else None
            except Exception: usage, usage_ok = None, False  # noqa: BLE001
        integrity = integrity and usage_ok
        if cid in refs:
            m, pkg, obs, dsets, rk = case_world(cid)
            try:
                if malformed: raise ValueError(malformed)
                rows, review = grade_run(o, refs[cid], m, pkg, obs, dsets, rk, usage_ok, usage, integrity, prior.get(bid, {}).get("must_detect_review", []))
            except Exception as e:  # noqa: BLE001
                rows = {"integrity": (integrity, ""), "execution": (False, f"malformed answer: {e!r}"[:300])}
                for ax in refs[cid]["expected_axes"]: rows[f"axis:{ax}"] = (False, "malformed answer")
                for r in ("overall", "unsupported_corroboration", "citation_validity", "status_interpretation", "required_actions"): rows[r] = (False, "malformed answer")
                review = [{"id": it["id"], "text": it["text"], "mandatory": it["mandatory"], "auto": None, "confirm": None} for it in refs[cid]["must_detect"]]
            o = o or {"execution_status": "malformed", "overall": {"verdict": None}}
        elif cid in lit and o is not None:
            row = lit[cid]; ax = next((x for x in o.get("axes", []) if x.get("axis_id") == "literature_axis"), None)
            ok = o["execution_status"] == "completed" and ax is not None and ax["verdict"] == row["documented_verdict"].replace("not_comparable", "not_assessable")
            rows = {"integrity": (integrity, ""), "execution": (o["execution_status"] == "completed" and usage_ok, o["execution_status"]),
                    "axis:literature_axis": (ok, "" if ok else f"{ax and ax['verdict']} != {row['documented_verdict']}")}
            review = []
        else:
            continue
        graded[bid] = {"case_id": cid, "rows": {r: {"result": "pass" if v[0] else "fail", "reason": v[1]} for r, v in rows.items()},
                       "must_detect_review": review, "execution_status": o["execution_status"], "overall": o["overall"]["verdict"], "usage_verified": usage_ok}
    dump(batch / "scorecard.json", {"entries": graded})
    pending = sum(1 for g in graded.values() for r in g["must_detect_review"] if r["mandatory"] and r["confirm"] is None)
    print(f"graded {len(graded)} runs → {batch/'scorecard.json'}; {pending} mandatory must_detect items await human confirm (auto keyword hit is shown as a hint only)")
    if a.no_unblind: return
    if pending: print("NOTE: unconfirmed mandatory items count as NOT passed in the summary.")

    per, usage_by, summary_unverified = {}, {}, {}
    for bid, g in graded.items():
        k = key["runs"][bid]; cfg, cid = k["configuration"], k["case_id"]
        for r, v in g["rows"].items(): per.setdefault(cfg, {}).setdefault(cid, {}).setdefault(r, []).append(v["result"] == "pass")
        per[cfg][cid].setdefault("ALL_ROWS", []).append(all_pass(g))
        up = batch / "usage" / f"{bid}.json"
        if g.get("usage_verified") and up.exists(): usage_by.setdefault(cfg, []).append((load(up)["usage"], all_pass(g)))
        else: summary_unverified.setdefault(cfg, []).append(bid)
    summary = {"_read_me": "Raw counts (passes/runs). Repeats measure run variability, not more biological tasks. Execution failures are failures.",
               "correctness": {cfg: {cid: {r: f"{sum(v)}/{len(v)}" for r, v in rows.items()} for cid, rows in cases.items()} for cfg, cases in per.items()},
               "usage": {}, "usage_unavailable_runs": summary_unverified}
    for cfg, runs in usage_by.items():
        tot = [u["input_tokens"] + u["output_tokens"] for u, _ in runs]; passes = sum(1 for _, p in runs if p)
        summary["usage"][cfg] = {"runs": len(runs), "all_rows_pass": f"{passes}/{len(runs)}",
                                 "model": sorted({u["model"] for u, _ in runs}),
                                 "llm_calls_total": sum(u["llm_calls"] for u, _ in runs),
                                 "input_tokens_total": sum(u["input_tokens"] for u, _ in runs), "cache_read_total": sum(u["cache_read_tokens"] for u, _ in runs),
                                 "cache_creation_total": sum(u["cache_creation_tokens"] for u, _ in runs), "output_tokens_total": sum(u["output_tokens"] for u, _ in runs),
                                 "data_tool_calls_total": sum(u["data_tool_calls"] for u, _ in runs), "bookkeeping_calls_total": sum(u["bookkeeping_calls"] for u, _ in runs),
                                 "wall_clock_s_total": round(sum(u["wall_clock_s"] for u, _ in runs), 1),
                                 "tokens_median_per_run": round(statistics.median(tot)) if tot else 0,
                                 "tokens_per_passed_run": round(sum(tot) / passes) if passes else "no passes",
                                 "estimated_cost_usd_total": round(sum((u.get("estimated_cost_usd") or 0) for u, _ in runs), 4)}
    dump(batch / "summary.json", summary); print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
