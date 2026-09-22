from types import SimpleNamespace
import modal

from coordinator.jobs import reconcile_job
from coordinator.models import InvestigationRequest, RunState


class Store:
    def __init__(self):
        self.state = RunState(run_id="a" * 32, request=InvestigationRequest(question="A test question"), status="running")

    def get_job(self, run_id):
        return "fc-test"

    def get(self, run_id):
        return self.state.model_copy(deep=True)

    def save(self, state):
        self.state = state


def resolver(error=None, payload=None):
    def get(timeout):
        assert timeout == 0
        if error:
            raise error
        return payload
    return lambda _: SimpleNamespace(get=get)


def test_hard_worker_timeout_becomes_terminal():
    store = Store()
    result = reconcile_job(store.state, store, resolver(modal.exception.FunctionTimeoutError("timeout")))
    assert result.status == "failed"
    assert result.stage == "worker_failed"


def test_pending_job_and_transient_observation_errors_stay_running():
    for error in [TimeoutError(), modal.exception.ConnectionError("temporarily offline")]:
        store = Store()
        assert reconcile_job(store.state, store, resolver(error)).status == "running"


def test_async_worker_crash_does_not_leave_permanent_running():
    store = Store()
    assert reconcile_job(store.state, store, resolver(RuntimeError("crashed"))).status == "failed"


def test_worker_final_result_restores_terminal_snapshot():
    store = Store()
    final = store.state.model_copy(update={"status": "partial", "stage": "finished"})
    assert reconcile_job(store.state, store, resolver(payload=final.model_dump())).status == "partial"


def test_wrong_worker_result_is_rejected():
    store = Store()
    wrong = store.state.model_copy(update={"run_id": "b" * 32, "status": "complete"})
    assert reconcile_job(store.state, store, resolver(payload=wrong.model_dump())).status == "failed"
