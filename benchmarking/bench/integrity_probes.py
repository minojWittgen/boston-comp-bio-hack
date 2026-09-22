#!/usr/bin/env python3
"""Integrity probes — the review's offline attacks, each of which the harness MUST now reject.

24 probes in 11 groups, covering both suites: groups 1-10 the secondary suite, group 11 the
primary corpus sandbox. Most assert an attack is REJECTED; a few are positive controls that
must still succeed. Groups 5, 5b and 6 shell out to grade.py, so held_out/reference_answers.json
must be present or the run aborts partway.

  python bench/integrity_probes.py        # exit 0 only if every probe is rejected

Run this BEFORE collecting any model scores (review: 'Integrity probes reject the previously accepted
failures before model scores are collected').
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agents import Mock, Scaffold, structural_problems, verify_ledger  # noqa: E402
from common import CASES, ROOT, RUNS, BudgetExceeded, ToolBox, Usage, dump, load, sign  # noqa: E402

results = []
def probe(name, rejected, detail=""):
    results.append((name, rejected)); print(f"{'REJECTED ' if rejected else 'ACCEPTED!'} {name}  {detail}")


def main():
    mp = CASES / "xctx-003.json"; m = load(mp)
    tb = ToolBox(m, mp, Usage("probe", m["limits"]))

    # 1. ledger: all seven criteria not_applicable, no reasons  → must be rejected
    ledger = {k: {"status": "not_applicable"} for k in ("in_vitro_read", "in_vivo_read", "patient_rna_read", "patient_protein_read", "within_person_pairing", "reference_status_resolved", "species_alignment")}
    probe("B ledger: all not_applicable without reasons", bool(verify_ledger(m, tb, ledger)))
    # 1b. all not_applicable WITH reasons while data is present → still rejected
    ledger = {k: {"status": "not_applicable", "reason": "n/a"} for k in ledger}
    probe("B ledger: all not_applicable with reasons but data present", bool(verify_ledger(m, tb, ledger)))

    # 2. ledger: all unmet with 'I will retry later', no executed follow-up, verdict persists → rejected
    ledger = {k: {"status": "unmet", "follow_up_action": "I will retry later"} for k in ledger}
    tb2 = ToolBox(m, mp, Usage("probe", m["limits"]))
    probs = verify_ledger(m, tb2, ledger)
    probe("B ledger: all unmet with unexecuted follow-up", bool(probs), probs[0] if probs else "")

    # 2b. structural: overall persists while an axis diverges → rejected
    ans = {"overall": {"verdict": "persists", "rationale": ""}, "axes": [{"axis_id": a["axis_id"], "verdict": "diverges" if a["axis_id"] == "in_vitro_vs_in_vivo" else "persists",
            "evidence": ["obs_invitro_rna_tyk2"], "contrast_alignment": "x", "note": ""} for a in m["task"]["axes"]], "status_interpretation": {}}
    probe("structural: overall persists while an axis diverges", bool(structural_problems(m, tb, ans)))

    # 3. read_file: absolute path with '..' escaping the fixture dir → rejected
    tmp = Path(tempfile.mkdtemp()) / "secret.json"; tmp.write_text("{}")
    r = tb.read_file(str(mp.parent / ".." / ".." / ".." / tmp.relative_to("/")))
    probe("read_file: absolute path with .. outside fixtures", r["status"] == "rejected")
    r = tb.read_file("../fixtures/xctx-003/../../held_out/reference_answers.json")
    probe("read_file: relative .. into held_out", r["status"] == "rejected")

    # 4. read_file: harness-only files inside the fixture dir → rejected
    r1 = tb.read_file("../fixtures/xctx-003/tool_stub.json"); r2 = tb.read_file("../fixtures/xctx-003/invivo_rna.recovered.json")
    probe("read_file: tool_stub.json / recovered payload inside fixture dir", r1["status"] == "rejected" and r2["status"] == "rejected")
    r3 = tb.read_file("../fixtures/xctx-003/invivo_rna.json")
    probe("read_file: allowlisted input still readable (sanity)", r3["status"] == "ok")

    # 5. fabricated usage in the blind file → grader ignores it; tampered signed usage → integrity fail
    batch = RUNS / "_probe"; shutil.rmtree(batch, ignore_errors=True)
    subprocess.run([sys.executable, str(ROOT / "bench/run_cases.py"), "--config", "mock", "--cases", "xctx-001", "--batch", "_probe"], check=True, capture_output=True)
    bid = next(iter(load(batch / "key.json")["runs"]))
    up = load(batch / "usage" / f"{bid}.json"); up["usage"]["output_tokens"] = 999999; dump(batch / "usage" / f"{bid}.json", up)
    out = subprocess.run([sys.executable, str(ROOT / "bench/grade.py"), str(batch), "--no-unblind"], capture_output=True, text=True)
    sc = load(batch / "scorecard.json")["entries"][bid]["rows"]
    probe("usage: tampered usage record (999,999 output tokens, signature no longer valid)", sc["integrity"]["result"] == "fail" and sc["execution"]["result"] == "fail")
    # 5b. edit the blind output after the run → integrity fail
    bp = batch / "blind" / f"{bid}.json"; o = load(bp); o["overall"]["verdict"] = "persists"; dump(bp, o)
    subprocess.run([sys.executable, str(ROOT / "bench/grade.py"), str(batch), "--no-unblind"], capture_output=True)
    probe("blind output edited after the run", load(batch / "scorecard.json")["entries"][bid]["rows"]["integrity"]["result"] == "fail")

    # 6. human confirm:false must survive a regrade and block ALL_ROWS
    shutil.rmtree(batch); subprocess.run([sys.executable, str(ROOT / "bench/run_cases.py"), "--config", "mock", "--cases", "xctx-001", "--batch", "_probe"], check=True, capture_output=True)
    subprocess.run([sys.executable, str(ROOT / "bench/grade.py"), str(batch), "--no-unblind"], capture_output=True)
    sc = load(batch / "scorecard.json"); bid = next(iter(sc["entries"]))
    for r in sc["entries"][bid]["must_detect_review"]: r["confirm"] = False
    dump(batch / "scorecard.json", sc)
    subprocess.run([sys.executable, str(ROOT / "bench/grade.py"), str(batch)], capture_output=True)
    sc2 = load(batch / "scorecard.json"); summ = load(batch / "summary.json")
    kept = all(r["confirm"] is False for r in sc2["entries"][bid]["must_detect_review"])
    probe("review: confirm:false preserved across regrade and blocks ALL_ROWS", kept and summ["correctness"]["mock"]["xctx-001"]["ALL_ROWS"] == "0/1")

    # 7. status interpretation: the correct sentence is not penalised; wrong structured value is
    ok_out = {"status_interpretation": {"ensembl_orthology.rattus_norvegicus": "database_fact_no_record"}}
    bad_out = {"status_interpretation": {"ensembl_orthology.rattus_norvegicus": "biological_negative"}}
    probe("status: structured grading (prose 'not_found is not a biological negative' irrelevant)", ok_out["status_interpretation"]["ensembl_orthology.rattus_norvegicus"] != "biological_negative" and bool(structural_problems(m, tb, {"overall": {"verdict": "persists"}, "axes": [], **bad_out})))

    # 8. citation: rat orthology with fabricated locator must NOT satisfy a mouse requirement
    from grade import case_world, locator_resolves
    mm, pkg, obs, dsets, refs = case_world("xctx-001")
    probe("citation: rat orthology + fabricated locator does not satisfy mouse", not locator_resolves("data.one2one.0.fabricated", "ensembl_orthology.rattus_norvegicus", pkg, obs, dsets)
          and "ensembl_orthology.rattus_norvegicus" != "ensembl_orthology.mus_musculus")
    probe("citation: genuine locator resolves (sanity)", locator_resolves("data.one2one.0.target_symbol", "ensembl_orthology.mus_musculus", pkg, obs, dsets))

    # 9. budget: cumulative output cap and deadline enforced by Usage
    u = Usage("probe", {**m["limits"], "max_output_tokens_total": 100, "max_output_tokens_per_call": 80, "wall_clock_seconds": 90})
    class U: input_tokens = 10; output_tokens = 90; cache_read_input_tokens = 0; cache_creation_input_tokens = 5
    u.add_llm(U()); nxt = u.next_call_max_tokens()
    try: u.add_llm(U()); over = False
    except BudgetExceeded as e: over = e.kind == "budget_exceeded"
    probe("budget: per-call max bounded by remaining cumulative; cumulative overflow raises", nxt == 10 and over and u.cache_creation_tokens == 10)
    u2 = Usage("probe", {**m["limits"], "wall_clock_seconds": 0})
    try: u2.check_deadline(); dl = False
    except BudgetExceeded as e: dl = e.kind == "timeout"
    probe("budget: deadline checked before every model call", dl)

    # 10. execution failure gets no scientific credit
    from agents import build_output
    o = build_output(m, "A", 1, "timeout", None, tb, Usage("probe", m["limits"]), "deadline")
    probe("execution: timeout → not_assessable everywhere, execution_status=timeout", o["execution_status"] == "timeout" and all(a["verdict"] == "not_assessable" for a in o["axes"]))

    # 11. PRIMARY suite isolation: corpus tools cannot leave the corpus; rubric is not under primary/
    from primary_common import CorpusTools
    pc = ROOT / "primary" / "cases" / "xctx-p03"; pm = load(pc / "manifest.json")
    ct = CorpusTools(pm, pc, Usage("probe", {**pm["limits"], "max_data_tool_calls": 10**6, "wall_clock_seconds": 10**6}))
    r = ct.read_file("../../../../held_out/primary_rubric.json"); probe("primary read_file: .. escape to held_out", r["status"] == "rejected")
    r = ct.read_file(str((ROOT / "held_out" / "primary_rubric.json").resolve())); probe("primary read_file: absolute path outside corpus", r["status"] == "rejected")
    r = ct.python_eval("f = open_corpus('../../../../held_out/primary_rubric.json')"); probe("primary python_eval: open_corpus outside corpus", r["status"] == "error")
    r = ct.python_eval("f = open('/etc/hostname')"); probe("primary python_eval: builtin open() unavailable", r["status"] == "error")
    r = ct.python_eval("import os"); probe("primary python_eval: import unavailable", r["status"] == "error")
    probe("primary: no rubric/answer file inside primary/", not any("rubric" in q.name or "answer" in q.name for q in (ROOT / "primary").rglob("*")))
    probe("primary: citation with fabricated row does not resolve", not ct.resolve_citation("study_A_invitro/de_results.csv", "row:gene=NOTAGENE") and ct.resolve_citation("study_A_invitro/de_results.csv", "row:gene=TYK2"))

    shutil.rmtree(batch, ignore_errors=True)
    bad = [n for n, r in results if not r]
    print(f"\n{len(results) - len(bad)}/{len(results)} probes rejected." + (f" STILL ACCEPTED: {bad}" if bad else " Safe to collect model scores."))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
