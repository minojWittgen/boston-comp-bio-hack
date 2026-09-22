"""The frontend uses only the shared start/get API; no independent agent loop."""
import requests


class InvestigationClient:
    def __init__(self, url: str, token: str = ""):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def start(self, request: dict) -> dict:
        response = requests.post(f"{self.url}/investigations", json=request, headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def get(self, run_id: str) -> dict:
        response = requests.get(f"{self.url}/investigations/{run_id}", headers=self.headers, timeout=15)
        response.raise_for_status()
        return response.json()

    def chat(self, prompt: str, previous_investigation_id=None, demo=False) -> dict:
        response = requests.post(f"{self.url}/chat", json={"prompt": prompt,
                                 "previous_investigation_id": previous_investigation_id, "demo": demo},
                                 headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()
