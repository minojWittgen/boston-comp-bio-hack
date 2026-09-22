"""Use the canonical coordinator schema at the frontend boundary."""
import requests
from urllib.parse import urlsplit

from coordinator.models import RunState, Submission
from research_app.service import ChatMessage, DemoRequest


class InvestigationClient:
    def __init__(self, url: str, token: str = ""):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _post(self, path, payload, *, model_headers=None):
        if model_headers:
            url = urlsplit(self.url)
            if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}):
                raise ValueError("Visitor model keys require HTTPS (except local development).")
        response = requests.post(f"{self.url}{path}", json=payload,
                                 headers={**self.headers, **(model_headers or {})},
                                 timeout=90 if model_headers else 30, allow_redirects=False)
        if response.is_redirect:
            raise ValueError("The research service must use its direct URL, without redirects.")
        response.raise_for_status()
        return response.json()

    def start(self, submission: Submission | dict):
        validated = Submission.model_validate(submission)
        return self._post("/investigations", validated.model_dump(mode="json"))

    def chat(self, prompt: str, previous_investigation_id=None, *, api_key="", model=""):
        return self._post("/chat", ChatMessage(prompt=prompt,
                          previous_investigation_id=previous_investigation_id).model_dump(mode="json"),
                          model_headers={"X-Anthropic-Api-Key": api_key.strip(), "X-Anthropic-Model": model.strip()})

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
