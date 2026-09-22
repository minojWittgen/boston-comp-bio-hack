"""Explicit configuration; never silently fall back to synthetic evidence or an LLM."""
import os

from .engine import Coordinator
from .evidence import DirectoryEvidenceProvider, ModalEvidenceProvider
from .planner import ClaudePlanner, ExplicitPlanner
from .store import FileRunStore


class AutoPlanner:
    def plan(self, request):
        if request.requirements:
            return ExplicitPlanner().plan(request)
        return ClaudePlanner().plan(request)


def build_coordinator(store=None):
    directory = os.environ.get("XCTX_EVIDENCE_DIR")
    provider = DirectoryEvidenceProvider(directory) if directory else ModalEvidenceProvider()
    return Coordinator(AutoPlanner(), provider,
        store or FileRunStore(os.environ.get("XCTX_RUN_DIR", ".coordinator-runs")))
