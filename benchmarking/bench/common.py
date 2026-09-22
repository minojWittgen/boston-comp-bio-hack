"""Shared runtime (v2): paths, isolation, budgets, usage, tools.

Review fixes implemented here:
  §3  read_file resolves every path and enforces the manifest's explicit input_allowlist; harness-only
      files (tool_stub.json, *.recovered.json, *.original.json) are never readable, and `..` cannot escape.
  §4  Limits are declared as cumulative vs per-call; the deadline bounds EVERY model request; usage
      records input / cache_read / cache_creation / output tokens, llm calls, data-tool calls and
      bookkeeping calls separately; the harness (not the agent) writes and signs the usage record.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES, FIXTURES, HELD_OUT, RUNS, BENCHMARK, SCHEMA = (ROOT / p for p in ("cases", "fixtures", "held_out", "runs", "benchmark", "schema"))

VERDICTS = ("persists", "partially_persists", "diverges", "not_assessable")
AXES = ("in_vitro_vs_in_vivo", "in_vitro_vs_patient_rna", "patient_rna_vs_patient_protein_within_person", "literature_axis")
STATUS_INTERP = ("database_fact_no_record", "technical_failure_retryable", "disabled_by_mode", "upstream_failed", "biological_negative")
HARNESS_ONLY_SUFFIXES = ("tool_stub.json", ".recovered.json", ".original.json")

PRICE_PER_MTOK = {  # USD, edit for your model; used only for estimated_cost_usd
    "default": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_creation": 3.75}}


def load(p): return json.loads(Path(p).read_text())
def dump(p, obj):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(obj, indent=2) + "\n")
def sha256_file(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pipeline_path() -> Path:
    env = os.environ.get("XCTX_PIPELINE")
    cands = ([Path(env)] if env else []) + [ROOT.parent / "data_pipeline" / "evidence_pipeline", ROOT.parent / "evidence_pipeline",
                                             Path.cwd() / "data_pipeline" / "evidence_pipeline"]
    for c in cands:
        if (c / "package.py").exists():
            return c
    raise FileNotFoundError("set XCTX_PIPELINE=/path/to/data_pipeline/evidence_pipeline")


def import_pipeline():
    p = str(pipeline_path())
    if p not in sys.path:
        sys.path.insert(0, p)
    import cache, package, sources  # noqa: E401
    return sources, cache, package


# ------------------------------------------------------------------ budgets & usage
class BudgetExceeded(RuntimeError):
    def __init__(self, kind, msg): super().__init__(msg); self.kind = kind  # kind: timeout | budget_exceeded


@dataclass
class Usage:
    model: str
    limits: dict
    llm_calls: int = 0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    output_tokens: int = 0
    data_tool_calls: int = 0
    bookkeeping_calls: int = 0
    network_calls: int = 0
    t0: float = field(default_factory=time.monotonic)

    # -- deadline / budget (§4) ------------------------------------------------
    def remaining_seconds(self) -> float:
        return self.limits["wall_clock_seconds"] - (time.monotonic() - self.t0)

    def check_deadline(self):
        if self.remaining_seconds() <= 0:
            raise BudgetExceeded("timeout", "wall_clock_seconds deadline reached")

    def next_call_max_tokens(self) -> int:
        left = self.limits["max_output_tokens_total"] - self.output_tokens
        if left <= 0:
            raise BudgetExceeded("budget_exceeded", "max_output_tokens_total exhausted")
        return max(1, min(self.limits["max_output_tokens_per_call"], left))

    def add_llm(self, u):
        self.llm_calls += 1
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        cc = getattr(u, "cache_creation_input_tokens", 0) or 0
        self.input_tokens += (getattr(u, "input_tokens", 0) or 0) + cr + cc
        self.cache_read_tokens += cr; self.cache_creation_tokens += cc
        self.output_tokens += getattr(u, "output_tokens", 0) or 0
        if self.output_tokens > self.limits["max_output_tokens_total"]:
            raise BudgetExceeded("budget_exceeded", "max_output_tokens_total exceeded")

    def add_tool(self, kind: str):
        if kind == "data":
            self.data_tool_calls += 1
            if self.data_tool_calls > self.limits["max_data_tool_calls"]:
                raise BudgetExceeded("budget_exceeded", "max_data_tool_calls exceeded")
        else:
            self.bookkeeping_calls += 1
            if self.bookkeeping_calls > self.limits["max_bookkeeping_calls"]:
                raise BudgetExceeded("budget_exceeded", "max_bookkeeping_calls exceeded")
        self.check_deadline()

    def dump(self, signed=False) -> dict:
        pr = PRICE_PER_MTOK.get(self.model, PRICE_PER_MTOK["default"])
        plain_in = self.input_tokens - self.cache_read_tokens - self.cache_creation_tokens
        cost = (plain_in * pr["input"] + self.output_tokens * pr["output"] + self.cache_read_tokens * pr["cache_read"]
                + self.cache_creation_tokens * pr["cache_creation"]) / 1e6
        return {"model": self.model, "llm_calls": self.llm_calls, "input_tokens": self.input_tokens,
                "cache_read_tokens": self.cache_read_tokens, "cache_creation_tokens": self.cache_creation_tokens,
                "output_tokens": self.output_tokens, "data_tool_calls": self.data_tool_calls,
                "bookkeeping_calls": self.bookkeeping_calls, "wall_clock_s": round(time.monotonic() - self.t0, 1),
                "network_calls": self.network_calls, "estimated_cost_usd": round(cost, 4) if self.llm_calls else None,
                "harness_signed": signed}


def sign(secret: str, obj: dict) -> str:
    return hmac.new(secret.encode(), json.dumps(obj, sort_keys=True).encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ tools (isolated)
class ToolBox:
    """Exactly the tools a case exposes. Every call is counted and recorded."""

    def __init__(self, manifest: dict, manifest_path: Path, usage: Usage):
        self.m, self.usage = manifest, usage
        self.base = manifest_path.parent.resolve()
        self.fixture_dir = (self.base / manifest["evidence_package"]["path"]).resolve().parent
        self.allow = {(self.base / p).resolve() for p in manifest["input_allowlist"]}
        self.actions: list[dict] = []
        stub_path = (self.base / manifest["tools"]["stub_responses"]).resolve()
        self.stub = load(stub_path) if stub_path.exists() else {}
        self._seq: dict[str, int] = {}

    def _record(self, tool, args, status, kind="data"):
        self.actions.append({"tool": tool, "args": args, "result_status": status, "kind": kind})
        self.usage.add_tool(kind)

    # -- read_file: allowlist only --------------------------------------------
    def read_file(self, path: str) -> dict:
        p = Path(path)
        target = (p if p.is_absolute() else self.base / p).resolve()   # resolves `..` and symlinks
        if target not in self.allow or target.name.endswith(HARNESS_ONLY_SUFFIXES):
            self._record("read_file", {"path": path}, "rejected")
            return {"status": "rejected", "error": "not in input_allowlist", "allowed": list(self.m["input_allowlist"])}
        if not target.exists():
            self._record("read_file", {"path": path}, "not_found"); return {"status": "not_found"}
        self._record("read_file", {"path": path}, "ok")
        return {"status": "ok", "content": load(target)}

    # -- fetch_dataset: the declared retry path for unavailable datasets --------
    def fetch_dataset(self, dataset_id: str) -> dict:
        args = {"dataset_id": dataset_id}
        entry = self.stub.get("fetch_dataset", {}).get(dataset_id)
        if entry is None:
            declared = {d["id"] for d in self.m["datasets"]}
            st = "not_found" if dataset_id not in declared else "error"
            self._record("fetch_dataset", args, st)
            return {"status": st, "error": "no recovery available for this dataset" if st == "error" else "unknown dataset_id"}
        i = self._seq.get(dataset_id, 0); self._seq[dataset_id] = i + 1
        name = entry["sequence"][min(i, len(entry["sequence"]) - 1)]
        ds = load(self.fixture_dir / name)
        self._record("fetch_dataset", args, "ok")
        return {"status": "ok", "dataset": ds, "note": "recovered on retry; provenance.synthetic applies"}

    # -- build_evidence_package: stubbed pipeline re-run -------------------------
    def build_evidence_package(self, symbol: str, disease: str = "", mode: str = "eval") -> dict:
        args = {"symbol": symbol, "disease": disease, "mode": mode}
        key = json.dumps(args, separators=(",", ":"), sort_keys=True)
        table = self.stub.get("build_evidence_package", {})
        entry = table.get(key) or table.get("default")
        if entry is None or "sequence" not in entry:
            self._record("build_evidence_package", args, (entry or {}).get("status", "error"))
            return entry or {"status": "error", "error": "stub: no response configured"}
        i = self._seq.get(key, 0); self._seq[key] = i + 1
        pkg = load(self.fixture_dir / entry["sequence"][min(i, len(entry["sequence"]) - 1)])
        self._record("build_evidence_package", args, "ok")
        return {"status": "ok", "package": pkg}

    def bookkeeping(self, tool, args, status="ok"):
        self._record(tool, args, status, kind="bookkeeping")

    # -- what every configuration receives up front -----------------------------
    def initial_inputs(self) -> dict:
        pkg = load((self.base / self.m["evidence_package"]["path"]).resolve())
        ds = {d["id"]: load((self.base / d["path"]).resolve()) for d in self.m["datasets"]}
        return {"evidence_package": pkg, "datasets": ds}

    def known_evidence_ids(self) -> set[str]:
        """observation_ids + reference keys that a citation may legitimately point at."""
        ids = set()
        for d in self.m["datasets"]:
            ids.add(d["id"])
            f = load((self.base / d["path"]).resolve())
            for o in f.get("observations", []):
                ids.add(o["observation_id"])
        for name in self.stub.get("fetch_dataset", {}):
            for fn in self.stub["fetch_dataset"][name]["sequence"]:
                for o in load(self.fixture_dir / fn).get("observations", []):
                    ids.add(o["observation_id"])
        ids |= {"mygene", "gtex", "impc", "opentargets", "pubmed",
                "ensembl_orthology.mus_musculus", "ensembl_orthology.rattus_norvegicus", "ensembl_orthology.macaca_mulatta"}
        return ids


TOOL_SPECS = [
    {"name": "read_file", "description": "Re-read one of the input files listed in input_allowlist (paths as given in the manifest). Nothing else is readable.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "fetch_dataset", "description": "Retry delivery of a dataset whose status is `unavailable`. Retry policy: once per dataset. Returns the dataset file (observations included) or an error.",
     "input_schema": {"type": "object", "properties": {"dataset_id": {"type": "string"}}, "required": ["dataset_id"]}},
    {"name": "build_evidence_package", "description": "Re-run the reference pipeline for the gene (use only if a reference source has status `error`). Returns the full package.",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}, "disease": {"type": "string"}, "mode": {"type": "string", "enum": ["explore", "eval"]}}, "required": ["symbol", "disease", "mode"]}},
]
