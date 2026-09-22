"""Use the canonical coordinator schema at the frontend boundary."""
import requests

from coordinator.models import RunState, Submission
from research_app.service import ChatMessage, DemoRequest


class InvestigationClient:
    def __init__(self, url: str, token: str = ""):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _post(self, path, payload):
        response = requests.post(f"{self.url}{path}", json=payload, headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def start(self, submission: Submission | dict):
        validated = Submission.model_validate(submission)
        return self._post("/investigations", validated.model_dump(mode="json"))

    def chat(self, prompt: str, previous_investigation_id=None):
        return self._post("/chat", ChatMessage(prompt=prompt,
                          previous_investigation_id=previous_investigation_id).model_dump(mode="json"))

    def demo(self, name):
        return self._post("/demos", DemoRequest(demo=name).model_dump(mode="json"))

    def get(self, run_id: str) -> RunState:
        response = requests.get(f"{self.url}/investigations/{run_id}", headers=self.headers, timeout=15)
        response.raise_for_status()
        return RunState.model_validate(response.json())

    def report(self, run_id: str) -> str:
        response = requests.get(f"{self.url}/investigations/{run_id}/report", headers=self.headers, timeout=15)
        response.raise_for_status()
        return response.text
