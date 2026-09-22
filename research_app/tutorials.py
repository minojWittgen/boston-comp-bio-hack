"""Cached, explicitly synthetic walkthroughs; no credentials or live workers."""
from functools import lru_cache
from hashlib import sha256

from coordinator.models import RunState

TUTORIAL_IDS = {name: sha256(f"xctx-tutorial-v1:{name}".encode()).hexdigest()[:32]
                for name in ("cross-context-conflict", "missing-evidence")}


class MemoryStore:
    def __init__(self):
        self.states = {}

    def save(self, state):
        self.states[state.run_id] = RunState.model_validate(state.model_dump(mode="json"))

    def get(self, run_id):
        return self.states[run_id].model_copy(deep=True)


@lru_cache(maxsize=2)
def _template(name):
    from research_app.service import demo_coordinator, demo_submission
    submission = demo_submission(name)
    store = MemoryStore()
    state = RunState(run_id=TUTORIAL_IDS[name], request=submission.request)
    store.save(state)
    demo_coordinator(store).execute(state.run_id, submission)
    return store.get(state.run_id)


def tutorial(name):
    if name not in TUTORIAL_IDS:
        raise ValueError("Unknown tutorial")
    return _template(name).model_copy(deep=True)


def tutorial_for_id(run_id):
    return next((tutorial(name) for name, value in TUTORIAL_IDS.items() if value == run_id), None)
