"""Shared runtime for the xctx benchmark: paths, tool stub, usage accounting, limits.

Everything an agent configuration can touch goes through `ToolBox`, so A, B and C
see identical tool behaviour and every call is counted.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # xctx-eval/
CASES = ROOT / "cases"
FIXTURES = ROOT / "fixtures"
HELD_OUT = ROOT / "held_out"
RUNS = ROOT / "runs"
BENCHMARK = ROOT / "benchmark"

VERDICTS = ("persists", "partially_persists", "diverges", "not_comparable")
STATUSES = ("ok", "not_found", "error", "skipped")


def load(p: Path | str) -> dict:
    return json.loads(Path(p).read_text())


def dump(p: Path | str, obj) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2) + "\n")


def pipeline_path() -> Path:
    """Locate evidence_pipeline/ (sources.py, cache.py, package.py) from the hackathon repo."""
    env = os.environ.get("XCTX_PIPELINE")
    cands = [Path(env)] if env else []
    cands += [ROOT.parent / "data_pipeline" / "evidence_pipeline",
              ROOT.parent / "evidence_pipeline",
              Path.cwd() / "data_pipeline" / "evidence_pipeline"]
    for c in cands:
        if (c / "package.py").exists():
            return c
    raise FileNotFoundError("set XCTX_PIPELINE=/path/to/data_pipeline/evidence_pipeline")


def import_pipeline():
    p = str(pipeline_path())
    if p not in sys.path:
        sys.path.insert(0, p)
    import cache, package, sources  # noqa: E401  (bare-name imports, as the repo does)
    return sources, cache, package


class LimitExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    model: str
    input_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    network_calls: int = 0
    t0: float = field(default_factory=time.time)

    def add_llm(self, usage) -> None:
        """`usage` is the provider's usage object (Anthropic: input_tokens, output_tokens,
        cache_read_input_tokens). Sum, never estimate."""
        self.llm_calls += 1
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        self.input_tokens += (getattr(usage, "input_tokens", 0) or 0) + cr
        self.cache_read_tokens += cr
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0

    def dump(self) -> dict:
        return {"model": self.model, "input_tokens": self.input_tokens,
                "cache_read_tokens": self.cache_read_tokens, "output_tokens": self.output_tokens,
                "llm_calls": self.llm_calls, "tool_calls": self.tool_calls,
                "wall_clock_s": round(time.time() - self.t0, 1),
                "network_calls": self.network_calls}


class ToolBox:
    """The two tools a case exposes. Reads are sandboxed to the case's fixture dir;
    build_evidence_package is served from tool_stub.json so no network is touched."""

    def __init__(self, manifest: dict, manifest_path: Path, usage: Usage, limits: dict):
        self.m = manifest
        self.base = manifest_path.parent
        self.fixture_dir = (self.base / manifest["evidence_package"]["path"]).resolve().parent
        self.usage = usage
        self.limits = limits
        self.actions: list[dict] = []
        stub = (self.base / manifest["tools"]["stub_responses"]).resolve()
        self.stub = load(stub) if stub.exists() else {"build_evidence_package": {}}
        self._seq_pos: dict[str, int] = {}

    # -- accounting -------------------------------------------------------------
    def _count(self, tool: str, args: dict, status: str) -> None:
        self.usage.tool_calls += 1
        self.actions.append({"tool": tool, "args": args, "result_status": status})
        if self.usage.tool_calls > self.limits["max_tool_calls"]:
            raise LimitExceeded(f"max_tool_calls={self.limits['max_tool_calls']} exceeded")
        if time.time() - self.usage.t0 > self.limits["wall_clock_seconds"]:
            raise LimitExceeded("wall_clock_seconds exceeded")

    # -- tools ------------------------------------------------------------------
    def read_file(self, path: str) -> dict:
        target = (self.base / path).resolve() if not Path(path).is_absolute() else Path(path)
        if self.fixture_dir not in target.parents and target != self.fixture_dir:
            self._count("read_file", {"path": path}, "error")
            return {"status": "error", "error": "path outside case fixtures"}
        if not target.exists():
            self._count("read_file", {"path": path}, "not_found")
            return {"status": "not_found"}
        self._count("read_file", {"path": path}, "ok")
        return {"status": "ok", "content": load(target)}

    def build_evidence_package(self, symbol: str, disease: str = "", mode: str = "eval") -> dict:
        args = {"symbol": symbol, "disease": disease, "mode": mode}
        key = json.dumps(args, separators=(",", ":"), sort_keys=True)
        table = self.stub.get("build_evidence_package", {})
        entry = table.get(key) or table.get("default")
        if entry is None:
            self._count("build_evidence_package", args, "error")
            return {"status": "error", "error": "stub: no response configured"}
        if "sequence" in entry:
            i = self._seq_pos.get(key, 0)
            self._seq_pos[key] = i + 1
            name = entry["sequence"][min(i, len(entry["sequence"]) - 1)]
            pkg = load(self.fixture_dir / name)
            status = "ok" if pkg.get("gene", {}).get("status") == "ok" else pkg.get("gene", {}).get("status", "ok")
            self._count("build_evidence_package", args, status)
            return {"status": "ok", "package": pkg}
        self._count("build_evidence_package", args, entry.get("status", "error"))
        return entry

    def manifest_files(self) -> dict:
        """Everything the agent gets up front: manifest + evidence package + context datasets."""
        pkg = load((self.base / self.m["evidence_package"]["path"]).resolve())
        ctx = {d["id"]: load((self.base / d["path"]).resolve()) for d in self.m["context_datasets"]}
        return {"evidence_package": pkg, "context_datasets": ctx}


TOOL_SPECS = [
    {"name": "read_file",
     "description": "Read one JSON file from this case's fixture directory (paths as given in the manifest).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "build_evidence_package",
     "description": "Re-run the evidence pipeline for a gene. Returns the full evidence package. "
                    "Use it when a mandatory source in the provided package is `error` (technical "
                    "failure, retryable). `not_found` and `skipped` do not change on re-run.",
     "input_schema": {"type": "object",
                      "properties": {"symbol": {"type": "string"}, "disease": {"type": "string"},
                                     "mode": {"type": "string", "enum": ["explore", "eval"]}},
                      "required": ["symbol", "disease", "mode"]}},
]
