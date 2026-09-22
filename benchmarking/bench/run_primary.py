#!/usr/bin/env python3
"""PRIMARY suite runner: same task + same corpus, each system on its own.

  python bench/run_primary.py --system baseline integrated --batch primary-final     # the pilot: 2 × 3 × 1
  python bench/run_primary.py --system integrated --cases xctx-p00 --batch calib-1    # public calibration run
  XCTX_FAKE_LLM=1 python bench/run_primary.py --system integrated mock --batch smoke-1  # offline harness check
  python bench/run_primary.py --system baseline --cases xctx-p00 --batch calib-2

Readiness (handoff §4): before any paid run the runner checks that every requested system is
implemented and configured (adapters importable, pipeline + coordinator importable, API key/model
set) and, for batches that will be graded, that held_out/primary_rubric.json exists and is frozen.
The offline stand-in (XCTX_FAKE_LLM=1) is refused unless the batch name starts with `smoke` or `calib`.
Results are saved incrementally: key.json is rewritten after every run, and an exception inside one
run is recorded as execution_status=error without losing the rest of the batch.

Layout (runs/<batch>/): blind/<id>.json · usage/<id>.json (harness-signed) · raw/<system>_<case>_<run>.json · key.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agents_primary import get_system  # noqa: E402
from common import HELD_OUT, ROOT, RUNS, dump, load, sha256_file, sign  # noqa: E402

PRIMARY = ROOT / "primary" / "cases"


def readiness(systems: list[str], batch: str, cases: list[Path]) -> list[str]:
    problems = []
    fake = os.environ.get("XCTX_FAKE_LLM") == "1"
    unscored = batch.startswith(("smoke", "calib"))
    if fake and not unscored:
        problems.append("XCTX_FAKE_LLM=1 is only allowed for batches named smoke*/calib*")
    for s in systems:
        if s == "integrated":
            try:
                from integrated_adapter import readiness as r
                problems += [f"integrated: {p}" for p in r()]
            except Exception as e:  # noqa: BLE001
                problems.append(f"integrated adapter not importable: {e!r}")
        elif s == "baseline" and not fake:
            if not os.environ.get("ANTHROPIC_API_KEY"): problems.append("baseline: ANTHROPIC_API_KEY unset")
            if not os.environ.get("XCTX_MODEL"): problems.append("baseline: XCTX_MODEL unset")
        elif s not in ("baseline", "integrated", "mock", "mock-careless"):
            problems.append(f"unknown system {s}")
    if not unscored:
        rp = HELD_OUT / "primary_rubric.json"
        if not rp.exists():
            problems.append("held_out/primary_rubric.json missing — scored batches cannot be graded")
        else:
            st = load(rp).get("_review_status", {})
            if not st.get("independently_reviewed") or not st.get("frozen_at"):
                problems.append("primary rubric is not marked independently_reviewed + frozen_at (held_out/primary_rubric.json → _review_status)")
        if any(c.name == "xctx-p00" for c in cases):
            problems.append("xctx-p00 is the calibration case; it is not scored (use a smoke*/calib* batch)")
    for c in cases:
        if any("rubric" in q.name or "answer" in q.name for q in c.rglob("*")): problems.append(f"{c.name}: answer material inside the case directory")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", nargs="+", required=True); ap.add_argument("--cases", nargs="*"); ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--batch", default="primary-" + dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    ap.add_argument("--force", action="store_true", help="skip readiness (never for scored runs)")
    a = ap.parse_args()
    cases = sorted(p for p in PRIMARY.iterdir() if p.is_dir() and (p / "manifest.json").exists())
    cases = [c for c in cases if (a.cases and c.name in a.cases) or (not a.cases and c.name not in ("xctx-p00",))]
    problems = readiness(a.system, a.batch, cases)
    if problems and not a.force:
        print("NOT READY:\n  - " + "\n  - ".join(problems)); sys.exit(2)
    out = RUNS / a.batch; secret = secrets.token_hex(16)
    key = {"_secret": secret, "suite": "primary", "fake_llm": os.environ.get("XCTX_FAKE_LLM") == "1", "runs": {}, "blinding_clues": {}}
    dump(out / "key.json", key)
    for sysname in a.system:
        system = get_system(sysname)
        for c in cases:
            m = load(c / "manifest.json")
            for r in range(1, a.reps + 1):
                try:
                    res = system.run(m, c, r)
                except Exception as e:  # noqa: BLE001  one failure must not lose the batch
                    res = {"case_id": m["case_id"], "system": sysname, "execution_status": "error", "comparisons": [], "limitations": [],
                           "unresolved": [f"EXECUTION error: runner caught {e!r}"[:300]], "report_markdown": "",
                           "_system_internal": {"actions": [], "usage": {"model": os.environ.get("XCTX_MODEL", "unknown"), "llm_calls": 0, "input_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0, "output_tokens": 0, "data_tool_calls": 0, "bookkeeping_calls": 0, "wall_clock_s": 0.0, "network_calls": 0, "estimated_cost_usd": None, "harness_signed": False}, "error": repr(e)[:500]}}
                dump(out / "raw" / f"{sysname}_{c.name}_{r}.json", res)
                bid = secrets.token_hex(4)
                blind = {k: v for k, v in res.items() if k != "_system_internal"}; blind["system"] = "BLIND"
                dump(out / "blind" / f"{bid}.json", blind)
                u = dict(res["_system_internal"]["usage"]); u["harness_signed"] = True
                dump(out / "usage" / f"{bid}.json", {"usage": u, "sig": sign(secret, u), "actions": res["_system_internal"].get("actions", [])})
                key["runs"][bid] = {"case_id": c.name, "system": sysname, "run": r, "blind_sha256": sha256_file(out / "blind" / f"{bid}.json"),
                                    "versions": res["_system_internal"].get("versions"), "model_inventory": res["_system_internal"].get("model_inventory")}
                dump(out / "key.json", key)   # incremental
                concl = {x["comparison_id"].split("_vs_")[-1][:14]: x["conclusion"][:9] for x in res["comparisons"]}
                print(f"{sysname:12s} {c.name}  {res['execution_status']:15s} {concl}  llm={u['llm_calls']} out_tok={u['output_tokens']} tools={u['data_tool_calls']} wall={u['wall_clock_s']}s")
    print(f"\n{len(key['runs'])} runs → {out}. Reviewer grades blind/ against the frozen rubric before key.json is opened.")


if __name__ == "__main__":
    main()
