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


@pytest.mark.asyncio
async def test_inline_package_avoids_external_volume_transfer(monkeypatch):
    import modal
    from tests.test_chat import package
    async def spawn(gene, disease, mode, run_id):
        async def get():
            return {"path": f"/data/runs/{run_id}/{gene}.json", "package": package()}
        return SimpleNamespace(get=SimpleNamespace(aio=get))
    monkeypatch.setattr(modal.Function, "from_name", lambda *a, **kw: SimpleNamespace(spawn=SimpleNamespace(aio=spawn)))
    def unexpected_volume(*a, **kw):
        raise AssertionError("Inline packages must not be downloaded again")
    monkeypatch.setattr(modal.Volume, "from_name", unexpected_volume)
    assert await ModalEvidence().fetch("TYK2", "psoriasis", "test-run") == package()
