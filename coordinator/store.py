"""Run snapshots: atomic local files, or a shared Modal Dict for the demo service."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Protocol

from .models import RunState


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid investigation ID")
    return run_id


class RunStore(Protocol):
    def save(self, state: RunState) -> None: ...
    def get(self, run_id: str) -> RunState: ...


class FileRunStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, state: RunState) -> None:
        name = validate_run_id(state.run_id)
        temporary = self.root / f".{name}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, self.root / f"{name}.json")

    def get(self, run_id: str) -> RunState:
        try:
            return RunState.model_validate_json(
                (self.root / f"{validate_run_id(run_id)}.json").read_text(encoding="utf-8")
            )
        except FileNotFoundError as exc:
            raise KeyError(run_id) from exc


class ModalRunStore:
    def __init__(self, name: str = "xctx-investigations"):
        import modal
        self.data = modal.Dict.from_name(name, create_if_missing=True)

    def save(self, state: RunState) -> None:
        self.data[validate_run_id(state.run_id)] = state.model_dump(mode="json")

    def get(self, run_id: str) -> RunState:
        return RunState.model_validate(self.data[validate_run_id(run_id)])

    def save_job(self, run_id: str, call_id: str) -> None:
        self.data[f"job:{validate_run_id(run_id)}"] = call_id

    def get_job(self, run_id: str) -> str | None:
        return self.data.get(f"job:{validate_run_id(run_id)}")
