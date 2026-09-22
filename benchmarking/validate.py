#!/usr/bin/env python3
"""Validate manifests (numeric + literature), observation datasets, and reference answers."""
import json, pathlib, sys
from jsonschema import Draft202012Validator as V

ROOT = pathlib.Path(__file__).parent
load = lambda p: json.loads(p.read_text())
MS, OS, RS = (V(load(ROOT / "schema" / f)) for f in ("case_manifest.schema.json", "observation.schema.json", "reference_answer.schema.json"))
ok = True
def fail(msg):
    global ok; ok = False; print("FAIL", msg)

for mp in sorted(list((ROOT / "cases").glob("xctx-*.json")) + list((ROOT / "cases" / "lit").glob("lit-*.json"))):
    m = load(mp); errs = list(MS.iter_errors(m))
    for e in errs: fail(f"{mp.name}: {'/'.join(map(str, e.path))}: {e.message}")
    if m["case_id"] != "xctx-000" and "_note" in m: fail(f"{mp.name}: _note only on dev example")
    if m["case_id"] != "xctx-000" and m["mode"] != "eval": fail(f"{mp.name}: final cases must be eval mode")
    allow = {(mp.parent / p).resolve() for p in m["input_allowlist"]}
    for d in m["datasets"]:
        p = (mp.parent / d["path"]).resolve()
        if p not in allow: fail(f"{mp.name}: dataset {d['id']} not in input_allowlist")
        if d["modality"] != "narrative":
            f = load(p)
            for e in OS.iter_errors(f): fail(f"{p.name}: {'/'.join(map(str, e.path))}: {e.message}")
            if f["status"] != d["status"]: fail(f"{mp.name}: {d['id']} status mismatch manifest={d['status']} file={f['status']}")
            if not f["provenance"]["synthetic"] and "synthetic" not in f["provenance"]["origin"]: pass
            for o in f.get("observations", []):
                if o["effect"].get("aggregate_of") == "samples" and not o.get("samples"): fail(f"{p.name}: {o['observation_id']} claims aggregate_of samples but has none")
    for p in (mp.parent / m["evidence_package"]["path"]).resolve().parent.iterdir():
        if p.name.endswith(("tool_stub.json", ".recovered.json", ".original.json")) and p.resolve() in allow: fail(f"{mp.name}: harness file {p.name} is in input_allowlist")
    pkg = load((mp.parent / m["evidence_package"]["path"]).resolve())
    if "_provenance" not in pkg: fail(f"{mp.name}: evidence package lacks _provenance")
    elif pkg["_provenance"].get("modified_fields") and not pkg["_provenance"].get("original_path"): fail(f"{mp.name}: package modified but no original kept")
    if not errs: print("ok  ", mp.name)

for mp in sorted((ROOT / "primary" / "cases").glob("*/manifest.json")):
    m = load(mp); c = mp.parent
    for f in m["permitted_files"]:
        if not (c / m["corpus_root"] / f).exists(): fail(f"primary {m['case_id']}: permitted file missing {f}")
    if not (c / m["task_file"]).exists(): fail(f"primary {m['case_id']}: task file missing")
    if m["case_id"] != "xctx-p00" and "_note" in m: fail(f"primary {m['case_id']}: _note only on dev example")
    if any("rubric" in q.name or "answer" in q.name for q in c.rglob("*")): fail(f"primary {m['case_id']}: answer material inside the case directory")
    for k in ("max_data_tool_calls", "max_output_tokens_total", "max_output_tokens_per_call", "wall_clock_seconds"):
        if k not in m["limits"]: fail(f"primary {m['case_id']}: limits.{k} missing")
    print("ok   primary", m["case_id"])

rp = ROOT / "held_out" / "reference_answers.json"
if rp.exists():
    ids = {p.stem for p in (ROOT / "cases").glob("xctx-*.json")}
    for c in load(rp)["cases"]:
        for e in RS.iter_errors(c): fail(f"reference {c['case_id']}: {'/'.join(map(str, e.path))}: {e.message}")
        if c["case_id"] not in ids: fail(f"reference {c['case_id']}: no manifest")
        else: print("ok   reference", c["case_id"], f"({c['situation']})")
else:
    print("note: held_out/ absent here (correct for an agent-visible checkout)")
sys.exit(0 if ok else 1)
