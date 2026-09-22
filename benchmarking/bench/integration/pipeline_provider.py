"""Run the PRODUCTION data pipeline against recorded responses from the frozen corpus.

`CorpusPipelineProvider.fetch(symbol, disease, mode, run_id)` is a coordinator `EvidenceProvider`.
It executes the pipeline's own code — `package.build_package`, `invitro.enrich_invitro`,
`registry.annotate_package` — exactly as `app.build_one` does, with ONE runtime substitution:
`sources.http` is replaced (for the duration of the call, on the imported module object) by a
replay of the corpus's recorded native responses (`corpus/api/index.json`). No pipeline file is
edited. A request with no recording raises inside the fetcher, which the pipeline itself turns into
an `error` SourceResult — a faithful "collection failed" rather than an invented record.

Handoff §1: "Existing API collectors can use faithful recorded responses through a benchmark provider."
"""
from __future__ import annotations

import contextlib
import json
import sys
import tempfile
from pathlib import Path

from common import import_pipeline


class NoRecording(RuntimeError):
    pass


class RecordedHTTP:
    """Replay for `sources.http(method, url, *, params=None, json=None, max_tries=4)`."""

    def __init__(self, corpus_root: Path):
        self.root = Path(corpus_root).resolve()
        idx = json.loads((self.root / "api" / "index.json").read_text())
        self.entries = idx["requests"]
        self.log: list[dict] = []

    @staticmethod
    def _norm(params):
        return {k: str(v) for k, v in (params or {}).items()}

    def __call__(self, method, url, *, params=None, json=None, max_tries=4):  # noqa: A002
        for e in self.entries:
            if e["method"] != method or e["url"] != url:
                continue
            if method == "GET" and self._norm(e.get("params")) != self._norm(params):
                continue
            if method == "POST":
                body = json or {}
                if e.get("json_variables") is not None and body.get("variables") != e["json_variables"]:
                    continue
                if e.get("json_query_contains") and e["json_query_contains"] not in str(body.get("query", "")):
                    continue
            path = (self.root / e["file"]).resolve()
            if path.parent.parent != self.root and path.parent != self.root / "api":
                raise NoRecording("recording outside corpus")
            self.log.append({"method": method, "url": url, "params": params, "file": e["file"], "replayed": True})
            with path.open() as f:
                import json as _json
                return _json.load(f)
        self.log.append({"method": method, "url": url, "params": params, "file": None, "replayed": False})
        raise NoRecording(f"no recorded response for {method} {url} {params}")


class CorpusPipelineProvider:
    """EvidenceProvider backed by the real pipeline code + recorded corpus responses."""

    def __init__(self, corpus_root: Path, cache_dir: Path | None = None):
        self.corpus_root = Path(corpus_root).resolve()
        self.cache_dir = Path(cache_dir or tempfile.mkdtemp(prefix="xctx-bench-cache-"))
        self.replay = RecordedHTTP(self.corpus_root)
        self.packages: dict[str, dict] = {}

    def fetch(self, symbol: str, disease: str, mode: str, run_id: str) -> dict:
        S, C, P = import_pipeline()
        pipe_dir = Path(P.__file__).resolve().parent
        if str(pipe_dir) not in sys.path:
            sys.path.insert(0, str(pipe_dir))
        import invitro as IV  # noqa: E402  pipeline modules import each other by bare name
        import registry as R  # noqa: E402
        cache = C.JsonCache(self.cache_dir)
        with _patched(S, "http", self.replay):
            pkg = P.build_package(symbol, disease, mode, run_id, cache)   # real pipeline
            IV.enrich_invitro(pkg, mode, cache)                            # real in-vitro enrichment
            R.annotate_package(pkg)                                        # real §6 annotation
        # same validation the coordinator's own providers apply (imported, not re-implemented)
        try:
            from coordinator.evidence import _check_package_request
            _check_package_request(pkg, symbol, disease, mode, run_id)
        except ImportError:
            pass
        self.packages[symbol] = pkg
        return pkg


@contextlib.contextmanager
def _patched(module, name, value):
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)
