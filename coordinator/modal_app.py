"""Deploy with: modal deploy -m coordinator.modal_app (from the repository root)."""
import os
import modal

app = modal.App("xctx-coordinator")
image = (modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("coordinator/requirements.txt")
    .add_local_python_source("coordinator")
    .add_local_dir("coordinator/prompts", remote_path="/root/coordinator/prompts"))
runtime_secret = modal.Secret.from_name("xctx-coordinator")


@app.function(image=image, secrets=[runtime_secret], timeout=600, retries=0, max_containers=4)
def investigate(run_id: str, submission: dict):
    from coordinator.models import Submission
    from coordinator.runtime import build_coordinator
    from coordinator.store import ModalRunStore
    engine = build_coordinator(ModalRunStore())
    return engine.execute(run_id, Submission.model_validate(submission)).model_dump(mode="json")


@app.function(image=image, secrets=[runtime_secret])
@modal.asgi_app()
def web():
    from coordinator.api import create_app
    from coordinator.jobs import reconcile_job
    from coordinator.runtime import build_coordinator
    from coordinator.store import ModalRunStore
    token = os.environ.get("COORDINATOR_API_TOKEN")
    if not token:
        raise RuntimeError("Set COORDINATOR_API_TOKEN in the xctx-coordinator secret before deployment")
    engine = build_coordinator(ModalRunStore())
    def dispatch(run_id, submission):
        call = investigate.spawn(run_id, submission.model_dump(mode="json"))
        try:
            engine.store.save_job(run_id, call.object_id)
        except Exception:
            call.cancel()
            raise

    return create_app(engine, dispatch=dispatch, api_token=token,
        refresh=lambda state: reconcile_job(state, engine.store))
