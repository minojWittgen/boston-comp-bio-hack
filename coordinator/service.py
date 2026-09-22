"""Start/get application service with local and Modal job runners."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from coordinator.engine import execute, initial_state, now
from coordinator.models import InvestigationRequest, TERMINAL
from coordinator.providers import ClaudeReasoner, ModalEvidence


def valid_run_id(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise KeyError("Unknown investigation") from None
    return value


def receipt(state):
    return {k: state[k] for k in ("id", "status", "created_at", "contract_hash")}


class FileStore:
    def __init__(self, directory="runs/coordinator"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    async def put(self, state):
        path = self.directory / f"{valid_run_id(state['id'])}.json"
        temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temp.write_text(json.dumps(state, indent=2, allow_nan=False))
        temp.replace(path)

    async def get(self, run_id):
        path = self.directory / f"{valid_run_id(run_id)}.json"
        if not path.exists():
            raise KeyError("Unknown investigation")
        return json.loads(path.read_text())


class LocalService:
    def __init__(self, store=None, provider=None, reasoner_factory=ClaudeReasoner):
        self.store = store or FileStore()
        self.provider = provider or ModalEvidence()
        self.reasoner_factory = reasoner_factory
        self.tasks = set()

    async def start(self, request: InvestigationRequest):
        state = initial_state(str(uuid.uuid4()), request)
        await self.store.put(state)
        reasoner = self.reasoner_factory(request.budget) if self.reasoner_factory else None
        task = asyncio.create_task(execute(state, self.store.put, self.provider, reasoner))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return receipt(state)

    async def get(self, run_id):
        state = await self.store.get(run_id)
        updated = datetime.fromisoformat(state["updated_at"])
        limit = state["request"]["budget"]["max_seconds"] + 30
        if state["status"] not in TERMINAL and (datetime.now(timezone.utc) - updated).total_seconds() > limit:
            state.update(status="failed", stage="finished", updated_at=now())
            state["errors"].append({"stage": "worker", "reason": "Worker heartbeat expired; execution may have been interrupted."})
            await self.store.put(state)
        return state

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


class ModalStore:
    def __init__(self):
        import modal
        self.states = modal.Dict.from_name("xctx-investigations", create_if_missing=True)

    async def put(self, state):
        await self.states.put.aio(state["id"], state)

    async def get(self, run_id):
        state = await self.states.get.aio(valid_run_id(run_id))
        if state is None:
            raise KeyError("Unknown or expired investigation")
        return state


class ModalService:
    def __init__(self):
        self.store = ModalStore()

    async def start(self, request):
        import modal
        state = initial_state(str(uuid.uuid4()), request)
        await self.store.put(state)
        try:
            worker = modal.Function.from_name(os.environ.get("COORDINATOR_APP_NAME", "xctx-research"), "run_investigation")
            call = await worker.spawn.aio(state["id"])
            await self.store.states.put.aio(f"call:{state['id']}", call.object_id)
        except Exception as exc:
            state.update(status="failed", stage="finished", updated_at=now())
            state["errors"].append({"stage": "dispatch", "reason": str(exc)[:500]})
            await self.store.put(state)
        return receipt(state)

    async def get(self, run_id):
        import modal
        state = await self.store.get(run_id)
        call_id = await self.store.states.get.aio(f"call:{run_id}")
        if state["status"] not in TERMINAL and call_id:
            try:
                await modal.FunctionCall.from_id(call_id).get.aio(timeout=0)
                state = await self.store.get(run_id)
            except TimeoutError:
                pass
            except Exception as exc:
                state = await self.store.get(run_id)
                if state["status"] not in TERMINAL:
                    state.update(status="failed", stage="finished", updated_at=now())
                    state["errors"].append({"stage": "worker", "reason": str(exc)[:500]})
                    await self.store.put(state)
        return state


def local_service():
    enabled = os.environ.get("COORDINATOR_MODEL_ENABLED", "1") != "0"
    return LocalService(reasoner_factory=ClaudeReasoner if enabled else None)
