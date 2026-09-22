"""Modal deployment: background coordinator, shared REST/MCP, and optional Streamlit."""
import json
import os
from pathlib import Path
import subprocess

import modal

ROOT = Path(__file__).parent
image = (modal.Image.debian_slim(python_version="3.11")
         .pip_install_from_requirements(str(ROOT / "requirements.txt"))
         .add_local_dir(ROOT / "coordinator", "/workspace/coordinator", ignore=["__pycache__", "*.pyc"])
         .add_local_dir(ROOT / "research_app", "/workspace/research_app", ignore=["__pycache__", "*.pyc"])
         .add_local_dir(ROOT / "examples", "/workspace/examples", ignore=["__pycache__"])
         .add_local_file(ROOT / "streamlit_app.py", "/workspace/streamlit_app.py")
         .add_local_file(ROOT / ".streamlit/config.toml", "/workspace/.streamlit/config.toml")
         .env({"PYTHONPATH": "/workspace"}))
app = modal.App("xctx-research")
secrets = [modal.Secret.from_name(os.environ.get("COORDINATOR_SECRET_NAME", "xctx-research-secrets"),
                                 required_keys=["ANTHROPIC_API_KEY", "INVESTIGATION_API_TOKEN"])]
artifacts = modal.Volume.from_name("xctx-investigation-artifacts", create_if_missing=True)
settings = {"ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            "EVIDENCE_APP_NAME": os.environ.get("EVIDENCE_APP_NAME", "xctx-evidence"),
            "EVIDENCE_VOLUME_NAME": os.environ.get("EVIDENCE_VOLUME_NAME", "xctx-cache"),
            "EVIDENCE_ENVIRONMENT": os.environ.get("EVIDENCE_ENVIRONMENT", "")}


@app.function(image=image, secrets=secrets, env=settings, volumes={"/artifacts": artifacts},
              cpu=1, memory=2048, timeout=660, max_containers=4, retries=0)
async def run_investigation(run_id: str):
    from coordinator.engine import execute
    from coordinator.models import InvestigationRequest
    from coordinator.providers import ClaudeReasoner, ModalEvidence
    from coordinator.service import ModalStore
    store = ModalStore()
    state = await store.get(run_id)
    request = InvestigationRequest.model_validate(state["request"])
    final = await execute(state, store.put, ModalEvidence(), ClaudeReasoner(request.budget))
    await artifacts.reload.aio()
    path = Path("/artifacts") / f"{run_id}.json"
    path.write_text(json.dumps(final, indent=2, allow_nan=False))
    await artifacts.commit.aio()
    return {"id": run_id, "status": final["status"], "artifact_path": str(path)}


@app.function(image=image, secrets=secrets, env=settings, cpu=1, memory=1024,
              timeout=300, max_containers=2)
@modal.concurrent(max_inputs=30)
@modal.asgi_app()
def api():
    from coordinator.api import create_app
    from coordinator.service import ModalService
    token = os.environ.get("INVESTIGATION_API_TOKEN", "")
    if not token:
        raise RuntimeError("INVESTIGATION_API_TOKEN must be configured for the cloud service.")
    return create_app(ModalService(), token=token)


@app.function(image=image, secrets=secrets, cpu=1, memory=1024, timeout=3600,
              max_containers=1, scaledown_window=600)
@modal.concurrent(max_inputs=20)
@modal.web_server(8000, startup_timeout=60)
def web():
    endpoint = modal.Function.from_name("xctx-research", "api").get_web_url()
    if not endpoint:
        raise RuntimeError("Shared API endpoint is unavailable.")
    subprocess.Popen(["python", "-m", "streamlit", "run", "/workspace/streamlit_app.py",
                      "--server.port=8000", "--server.address=0.0.0.0", "--server.headless=true",
                      "--server.enableCORS=false", "--server.enableXsrfProtection=false"],
                     cwd="/workspace", env={**os.environ, "INVESTIGATION_API_URL": endpoint})
