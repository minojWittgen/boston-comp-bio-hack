#!/usr/bin/env python3
"""Run configurations over cases, N replicates, writing BLIND outputs + harness-owned usage.

  python bench/run_cases.py --config A B --reps 1 --batch final          # the candidate demo: 2 × 3 × 1
  python bench/run_cases.py --config mock mock-careless --batch smoke
  python bench/run_cases.py --config B --suite all --cases xctx-000 --batch dev
  python bench/run_cases.py --config A B --suite lit --batch lit

Layout:
  runs/<batch>/blind/<id>.json   configuration + _ledger stripped; usage REMOVED (agent self-report is not trusted)
  runs/<batch>/usage/<id>.json   usage as measured by the harness, HMAC-signed with the batch secret
  runs/<batch>/raw/<config>_<case>_<run>.json   full trace
  runs/<batch>/key.json          blind id → (case, configuration, run) + secret + sha256 of each blind file
"""
from __future__ import annotations

import argparse
import datetime as dt
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agents import get_agent  # noqa: E402
from common import CASES, RUNS, dump, load, sha256_file, sign  # noqa: E402


def case_paths(suite, only):
    d = CASES / "lit" if suite == "lit" else CASES
    paths = sorted(d.glob("*.json"))
    if suite == "final": paths = [p for p in paths if p.stem != "xctx-000"]
    if only: paths = [p for p in paths if p.stem in only]
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", nargs="+", required=True)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--suite", choices=["final", "all", "lit"], default="final")
    ap.add_argument("--cases", nargs="*")
    ap.add_argument("--batch", default=dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    a = ap.parse_args()
    out = RUNS / a.batch; secret = secrets.token_hex(16); key = {"_secret": secret, "runs": {}}
    for cfg in a.config:
        agent = get_agent(cfg)
        for mp in case_paths(a.suite, a.cases):
            m = load(mp)
            for r in range(1, a.reps + 1):
                res = agent.run(m, mp, r)
                dump(out / "raw" / f"{cfg}_{m['case_id']}_{r}.json", res)
                bid = secrets.token_hex(4)
                blind = {k: v for k, v in res.items() if k not in ("configuration", "_ledger", "_coordinator", "usage")}
                blind["configuration"] = "BLIND"
                dump(out / "blind" / f"{bid}.json", blind)
                u = dict(res["usage"]); u["harness_signed"] = True
                dump(out / "usage" / f"{bid}.json", {"usage": u, "sig": sign(secret, u)})
                key["runs"][bid] = {"case_id": m["case_id"], "configuration": cfg, "run": r, "blind_sha256": sha256_file(out / "blind" / f"{bid}.json")}
                print(f"{cfg:14s} {m['case_id']}  run{r}  {res['execution_status']:16s} overall={res['overall']['verdict']:18s} "
                      f"out_tok={u['output_tokens']:5d} data_tools={u['data_tool_calls']} wall={u['wall_clock_s']}s")
    dump(out / "key.json", key)
    print(f"\nbatch {a.batch}: {len(key['runs'])} runs → {out}. Grade blind first; key.json is opened only by grade.py after grading.")


if __name__ == "__main__":
    main()
