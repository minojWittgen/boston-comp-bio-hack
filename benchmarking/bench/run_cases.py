#!/usr/bin/env python3
"""Run one or more configurations over the cases, N replicates each, writing BLIND outputs.

  python bench/run_cases.py --config A B --reps 3                # final 3 cases
  python bench/run_cases.py --config mock mock-careless --reps 1 # harness smoke test
  python bench/run_cases.py --config B --cases xctx-000          # dev example (freeze limits)
  python bench/run_cases.py --config A B --suite lit             # literature rows

Outputs:
  runs/<batch>/blind/<blind_id>.json       configuration + _ledger stripped — what the grader sees
  runs/<batch>/key.json                    blind_id -> (case, configuration, run); grader opens AFTER grading
  runs/<batch>/raw/<config>_<case>_<run>.json   full trace incl. usage + ledger
"""
from __future__ import annotations

import argparse
import datetime as dt
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agents import get_agent  # noqa: E402
from common import CASES, RUNS, dump, load  # noqa: E402


def case_paths(suite: str, only: list[str] | None):
    d = CASES / "lit" if suite == "lit" else CASES
    paths = sorted(p for p in d.glob("*.json"))
    if suite == "final":
        paths = [p for p in paths if p.stem != "xctx-000"]
    if only:
        paths = [p for p in paths if p.stem in only]
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", nargs="+", required=True, help="A B mock mock-careless")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--suite", choices=["final", "all", "lit"], default="final")
    ap.add_argument("--cases", nargs="*")
    ap.add_argument("--batch", default=dt.datetime.now().strftime("%Y%m%dT%H%M%S"))
    a = ap.parse_args()

    out = RUNS / a.batch
    key = {}
    for cfg in a.config:
        agent = get_agent(cfg)
        for mp in case_paths(a.suite, a.cases):
            m = load(mp)
            for r in range(1, a.reps + 1):
                res = agent.run(m, mp, r)
                dump(out / "raw" / f"{cfg}_{m['case_id']}_{r}.json", res)
                bid = secrets.token_hex(4)
                blind = {k: v for k, v in res.items() if k not in ("configuration", "_ledger")}
                blind["configuration"] = "BLIND"
                dump(out / "blind" / f"{bid}.json", blind)
                key[bid] = {"case_id": m["case_id"], "configuration": cfg, "run": r}
                u = res["usage"]
                print(f"{cfg:14s} {m['case_id']}  run{r}  verdict={res['verdict']:18s} "
                      f"tokens={u['input_tokens'] + u['output_tokens']:6d} tools={u['tool_calls']}")
    dump(out / "key.json", key)
    print(f"\nbatch {a.batch}: {len(key)} blind outputs in {out / 'blind'}  (key in key.json — grade first, open after)")


if __name__ == "__main__":
    main()
