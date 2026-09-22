"""PRIMARY suite runtime: equivalent basic file / search / calculation access over a frozen corpus.

Both systems get exactly these tools (or, for the integrated system, an EvidenceProvider that can only
reach the same files). Every call is counted as a data-tool call; the deadline and budgets come from
common.Usage. Nothing outside `permitted_files` is readable; the rubric never lives under primary/.
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
from pathlib import Path

from common import Usage

MAX_READ_CHARS = 60_000
MAX_SEARCH_HITS = 60
PY_EVAL_TIMEOUT_S = 10


class CorpusTools:
    def __init__(self, manifest: dict, case_dir: Path, usage: Usage):
        self.m, self.usage = manifest, usage
        self.root = (case_dir / manifest["corpus_root"]).resolve()
        self.allow = {(self.root / f).resolve(): f for f in manifest["permitted_files"]}
        self.actions: list[dict] = []

    def _rec(self, tool, args, status):
        self.actions.append({"tool": tool, "args": args, "result_status": status, "kind": "data"})
        self.usage.add_tool("data")

    def _resolve(self, rel: str):
        p = Path(rel)
        t = (p if p.is_absolute() else self.root / p).resolve()
        return t if t in self.allow else None

    def list_files(self) -> dict:
        self._rec("list_files", {}, "ok")
        return {"status": "ok", "files": sorted(self.allow.values())}

    def read_file(self, path: str) -> dict:
        t = self._resolve(path)
        if t is None:
            self._rec("read_file", {"path": path}, "rejected"); return {"status": "rejected", "error": "not a permitted corpus file"}
        text = t.read_text()
        self._rec("read_file", {"path": path}, "ok")
        return {"status": "ok", "path": self.allow[t], "truncated": len(text) > MAX_READ_CHARS, "content": text[:MAX_READ_CHARS]}

    def search(self, pattern: str, path_glob: str = "*") -> dict:
        hits = []
        try:
            rx = re.compile(pattern, re.I)
        except re.error as e:
            self._rec("search", {"pattern": pattern}, "error"); return {"status": "error", "error": f"bad regex: {e}"}
        for t, rel in sorted(self.allow.items(), key=lambda kv: kv[1]):
            if not Path(rel).match(path_glob) and path_glob != "*": continue
            for i, line in enumerate(t.read_text().splitlines(), 1):
                if rx.search(line):
                    hits.append({"file": rel, "line": i, "text": line[:300]})
                    if len(hits) >= MAX_SEARCH_HITS: break
            if len(hits) >= MAX_SEARCH_HITS: break
        self._rec("search", {"pattern": pattern, "path_glob": path_glob}, "ok")
        return {"status": "ok", "hits": hits, "capped": len(hits) >= MAX_SEARCH_HITS}

    def python_eval(self, code: str) -> dict:
        """Calculation in an ISOLATED SUBPROCESS (handoff §4): `python -I`, an audit hook that refuses every
        file open outside the corpus and every network/subprocess event, a CPU/time limit, and no builtin open/import.
        Data access only via csv_rows(rel) / json_load(rel) / read_text(rel); helpers mean/median/stdev/math."""
        import subprocess, sys, tempfile
        payload = json.dumps({"code": code, "root": str(self.root), "allowed": sorted(self.allow.values())})
        try:
            r = subprocess.run([sys.executable, "-I", "-S", str(Path(__file__).with_name("_sandbox.py"))], input=payload, capture_output=True, text=True, timeout=PY_EVAL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self._rec("python_eval", {"code_chars": len(code)}, "error"); return {"status": "error", "error": f"time limit {PY_EVAL_TIMEOUT_S}s exceeded"}
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"status": "error", "error": (r.stderr or "no output")[:500]}
        except Exception:  # noqa: BLE001
            out = {"status": "error", "error": (r.stderr or r.stdout)[:500]}
        self._rec("python_eval", {"code_chars": len(code)}, out.get("status", "error"))
        return out

    # -- citation resolution (used by the grader) --------------------------------
    def resolve_citation(self, file: str, locator: str) -> bool:
        t = self._resolve(file)
        if t is None: return False
        text = t.read_text()
        m = re.match(r"^(line|row|json|section):(.*)$", locator.strip())
        if not m: return False
        kind, arg = m.group(1), m.group(2).strip()
        if kind == "line":
            return arg.isdigit() and 1 <= int(arg) <= len(text.splitlines())
        if kind == "section":
            return any(arg.lower() in ln.lower() for ln in text.splitlines() if ln.startswith("#"))
        if kind == "row":
            if not t.suffix == ".csv": return False
            conds = dict(kv.split("=", 1) for kv in arg.split(";") if "=" in kv)
            return any(all(r.get(k) == v for k, v in conds.items()) for r in csv.DictReader(io.StringIO(text)))
        if kind == "json":
            try: cur = json.loads(text)
            except Exception: return False
            for part in re.split(r"[./]", arg):
                if part == "": continue
                if isinstance(cur, list) and part.isdigit() and int(part) < len(cur): cur = cur[int(part)]
                elif isinstance(cur, dict) and part in cur: cur = cur[part]
                else: return False
            return True
        return False


CORPUS_TOOL_SPECS = [
    {"name": "list_files", "description": "List the permitted corpus files.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "read_file", "description": "Read a permitted corpus file (path relative to corpus/).", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "search", "description": "Regex search across permitted corpus files; returns file + line number + text.", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path_glob": {"type": "string"}}, "required": ["pattern"]}},
    {"name": "python_eval", "description": "Run a short Python snippet for calculation in an isolated sandbox (10 s limit). Available: csv_rows(rel) → list of dict rows, json_load(rel), read_text(rel), mean/median/stdev, math. Set `result` or print. No imports, no open(), no network, no files outside the corpus.",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
]
