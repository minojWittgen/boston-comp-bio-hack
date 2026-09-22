"""Deploy the chat/MCP adapters around the team's canonical coordinator."""
import os
from pathlib import Path
import subprocess

import modal

ROOT = Path(__file__).parent
image = (modal.Image.debian_slim(python_version="3.11")
         .pip_install_from_requirements(str(ROOT / "coordinator/requirements.txt"))
         .pip_install_from_requirements(str(ROOT / "requirements-ui.txt"))
         .env({"PYTHONPATH": "/workspace"})
         .add_local_dir(ROOT / "coordinator", "/workspace/coordinator", ignore=["__pycache__", "*.pyc", "tests"])
         .add_local_dir(ROOT / "research_app", "/workspace/research_app", ignore=["__pycache__", "*.pyc"])
         .add_local_file(ROOT / "streamlit_app.py", "/workspace/streamlit_app.py")
         .add_local_file(ROOT / ".streamlit/config.toml", "/workspace/.streamlit/config.toml"))
app = modal.App("xctx-research")
# Only a team access token is required. Model calls use visitor credentials in /chat.
secrets = [modal.Secret.from_name(os.environ.get("COORDINATOR_SECRET_NAME", "xctx-research-secrets"))]
artifacts = modal.Volume.from_name("xctx-investigation-artifacts", create_if_missing=True)


@app.function(image=image, volumes={"/artifacts": artifacts},
              cpu=1, memory=2048, timeout=600, max_containers=4, retries=0)
def run_investigation(run_id: str, submission: dict, demo: str | None = None, plan: dict | None = None):
    from coordinator.models import ResearchPlan, Submission
    from coordinator.store import ModalRunStore
    from research_app.planning import public_coordinator, with_prepared_plan
    from research_app.service import demo_coordinator, demo_submission
    store = ModalRunStore()
    parsed = Submission.model_validate(submission)
    if demo and parsed != demo_submission(demo):
        raise ValueError("Demonstration input must match the declared server fixture")
    engine = demo_coordinator(store) if demo else public_coordinator(store)
    if plan is not None:
        if demo:
            raise ValueError("Demonstrations use only their explicit fixture plan")
        engine = with_prepared_plan(engine, parsed.request, ResearchPlan.model_validate(plan))
    final = engine.execute(run_id, parsed)
    artifacts.reload()
    (Path("/artifacts") / f"{run_id}.json").write_text(final.model_dump_json(indent=2))
    artifacts.commit()
    # The team's job reconciler expects the canonical terminal RunState.
    return final.model_dump(mode="json")


@app.function(image=image, secrets=secrets, cpu=1, memory=1024,
              timeout=300, max_containers=2)
@modal.concurrent(max_inputs=30)
@modal.asgi_app()
def api():
    from coordinator.jobs import reconcile_job
    from coordinator.store import ModalRunStore
    from research_app.api import create_app, configured_token
    from research_app.planning import public_coordinator
    from research_app.service import RunService
    token = configured_token()
    if not token:
        raise RuntimeError("Configure COORDINATOR_API_TOKEN (or INVESTIGATION_API_TOKEN) before deployment")
    engine = public_coordinator(ModalRunStore())
    def dispatch(run_id, submission, demo=None, plan=None):
        call = run_investigation.spawn(run_id, submission.model_dump(mode="json"), demo,
                                      plan.model_dump(mode="json") if plan is not None else None)
        try:
            engine.store.save_job(run_id, call.object_id)
        except Exception:
            call.cancel()
            raise
    service = RunService(engine, dispatch=dispatch, refresh=lambda state: reconcile_job(state, engine.store))
    return create_app(service, api_token=token)


@app.function(image=image, secrets=secrets, cpu=1, memory=1024, timeout=3600,
              max_containers=1, scaledown_window=600)
@modal.concurrent(max_inputs=20)
@modal.web_server(8000, startup_timeout=60)
def web():
    endpoint = modal.Function.from_name("xctx-research", "api").get_web_url()
    if not endpoint:
        raise RuntimeError("Shared API endpoint is unavailable")
    subprocess.Popen(["python", "-m", "streamlit", "run", "/workspace/streamlit_app.py",
                      "--server.port=8000", "--server.address=0.0.0.0", "--server.headless=true"],
                     cwd="/workspace", env={**os.environ, "INVESTIGATION_API_URL": endpoint})
