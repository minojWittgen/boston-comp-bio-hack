import asyncio
from types import SimpleNamespace

import pytest

from coordinator.providers import ModalEvidence


@pytest.mark.asyncio
async def test_cancelled_coordinator_cancels_its_modal_retrieval(monkeypatch):
    import modal
    cancelled = []
    async def get():
        await asyncio.sleep(20)
    async def cancel():
        cancelled.append(True)
    call = SimpleNamespace(get=SimpleNamespace(aio=get), cancel=SimpleNamespace(aio=cancel))
    async def spawn(*args):
        return call
    fn = SimpleNamespace(spawn=SimpleNamespace(aio=spawn))
    monkeypatch.setattr(modal.Function, "from_name", lambda *a, **kw: fn)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.02):
            await ModalEvidence().fetch("TYK2", "", "test-run")
    assert cancelled == [True]
