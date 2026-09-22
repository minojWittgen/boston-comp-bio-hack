#!/usr/bin/env python3
"""Validate every case manifest and reference answer against the schemas.

Placeholders (<<...>>) in `limits` are tolerated with a warning until frozen.
Run from the xctx-eval/ directory:  python validate.py
"""
import json, sys, pathlib
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).parent
load = lambda p: json.loads(p.read_text())

manifest_schema = load(ROOT / "schema/case_manifest.schema.json")
ref_schema = load(ROOT / "schema/reference_answer.schema.json")
ok = True

for path in sorted((ROOT / "cases").glob("xctx-*.json")):
    m = load(path)
    # tolerate unfrozen limits
    unfrozen = [k for k, v in m.get("limits", {}).items() if isinstance(v, str) and v.startswith("<<")]
    if unfrozen:
        print(f"WARN {path.name}: limits not frozen: {unfrozen}")
        m["limits"] = {k: (1 if k in unfrozen else v) for k, v in m["limits"].items()}
    if m["case_id"] != "xctx-000" and "_note" in m:
        print(f"FAIL {path.name}: _note is only allowed on the dev example"); ok = False
    if m["case_id"] != "xctx-000" and m["mode"] != "eval":
        print(f"FAIL {path.name}: final cases must be mode=eval"); ok = False
    errs = list(Draft202012Validator(manifest_schema).iter_errors(m))
    for e in errs:
        print(f"FAIL {path.name}: {'/'.join(map(str, e.path))}: {e.message}"); ok = False
    if not errs:
        print(f"ok   {path.name}")

ref_path = ROOT / "held_out/reference_answers.json"
if ref_path.exists():
    ref = load(ref_path)
    case_ids = {p.stem for p in (ROOT / "cases").glob("xctx-*.json")}
    for entry in ref["cases"]:
        errs = list(Draft202012Validator(ref_schema).iter_errors(entry))
        for e in errs:
            print(f"FAIL reference {entry.get('case_id')}: {'/'.join(map(str, e.path))}: {e.message}"); ok = False
        if entry["case_id"] not in case_ids:
            print(f"FAIL reference {entry['case_id']}: no matching manifest"); ok = False
        if not errs:
            print(f"ok   reference {entry['case_id']} ({entry['situation']})")
else:
    print("note: held_out/ not present here (good, if the agent can read this tree)")

sys.exit(0 if ok else 1)
