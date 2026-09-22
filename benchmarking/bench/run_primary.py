#!/usr/bin/env python3
"""PRIMARY suite runner: same task + same corpus, each system on its own.

  python bench/run_primary.py --system baseline integrated --batch primary-final     # the pilot: 2 × 3 × 1
  python bench/run_primary.py --system mock mock-careless --batch primary-smoke
  python bench/run_primary.py --system baseline --cases xctx-p00 --batch primary-dev  # feasibility under the deadline

Outputs (runs/<batch>/):
  blind/<id>.json   report envelope with `system` → BLIND and `_system_internal` stripped
  usage/<id>.json   harness-measured usage, HMAC-signed (the system's self-report is never graded)
  raw/<system>_<case>.json  full trace
  key.json          id → (case, system) + secret + sha256 of each blind file; blinding_clues recorded by the reviewer
"""
from __future__ import annotations

import argparse
import datetime as dt
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agents_primary import get_system  # noqa: E402
from common import ROOT, RUNS, dump, load, sha256_file, sign  # noqa: E402

PRIMARY = ROOT / "primary" / "cases"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", nargs="+", required=True); ap.add_argument("--cases", nargs="*"); ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--batch", default="primary-" + dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    a = ap.parse_args()
    cases = sorted(p for p in PRIMARY.iterdir() if p.is_dir() and (p / "manifest.json").exists())
    cases = [c for c in cases if (a.cases and c.name in a.cases) or (not a.cases and c.name != "xctx-p00")]
    out = RUNS / a.batch; secret = secrets.token_hex(16); key = {"_secret": secret, "suite": "primary", "runs": {}, "blinding_clues": {}}
    for sysname in a.system:
        system = get_system(sysname)
        for c in cases:
            m = load(c / "manifest.json")
            for r in range(1, a.reps + 1):
                res = system.run(m, c, r)
                dump(out / "raw" / f"{sysname}_{c.name}_{r}.json", res)
                bid = secrets.token_hex(4)
                blind = {k: v for k, v in res.items() if k != "_system_internal"}; blind["system"] = "BLIND"
                dump(out / "blind" / f"{bid}.json", blind)
                u = dict(res["_system_internal"]["usage"]); u["harness_signed"] = True
                dump(out / "usage" / f"{bid}.json", {"usage": u, "sig": sign(secret, u), "actions": res["_system_internal"]["actions"]})
                key["runs"][bid] = {"case_id": c.name, "system": sysname, "run": r, "blind_sha256": sha256_file(out / "blind" / f"{bid}.json")}
                concl = {x["comparison_id"].split("_vs_")[-1][:12]: x["conclusion"][:9] for x in res["comparisons"]}
                print(f"{sysname:12s} {c.name}  {res['execution_status']:15s} {concl}  out_tok={u['output_tokens']} tools={u['data_tool_calls']} wall={u['wall_clock_s']}s")
    dump(out / "key.json", key)
    print(f"\n{len(key['runs'])} runs → {out}. Reviewer grades blind/ against the frozen rubric before key.json is opened.")


if __name__ == "__main__":
    main()
