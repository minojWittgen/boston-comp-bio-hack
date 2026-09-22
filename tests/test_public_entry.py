from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Lock
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest
from streamlit.testing.v1 import AppTest

from research_app.api import create_app
from research_app.budget import PublicRunBudget, RunLimitError
from research_app.service import RunService, demo_submission
from research_app.tutorials import tutorial
from tests.test_visitor_keys import svc


class AtomicSlots:
    def __init__(self):
        self.entries, self.lock = {}, Lock()

    def get(self, key):
        with self.lock:
            return self.entries.get(key)

    def put(self, key, value, *, skip_if_exists):
        assert skip_if_exists
        with self.lock:
            if key in self.entries:
                return False
            self.entries[key] = value
            return True


def test_public_budget_survives_recreation_and_concurrent_starts():
    slots = AtomicSlots()
    def reserve(_):
        try:
            PublicRunBudget(slots, limit=3).reserve()
            return True
        except RunLimitError:
            return False
    with ThreadPoolExecutor(12) as executor:
        assert sum(executor.map(reserve, range(30))) == 3
    assert len(slots.entries) == 3
    with pytest.raises(RunLimitError):
        PublicRunBudget(slots, limit=3).check()
    PublicRunBudget(slots, limit=4).reserve()  # An explicit owner increase permits one more.
    assert len(slots.entries) == 4


def test_closed_public_window_does_not_reopen_when_storage_expires():
    now = datetime.now(timezone.utc)
    budget = PublicRunBudget(AtomicSlots(), expires_at=now - timedelta(seconds=1))
    for operation in (budget.check, budget.reserve):
        with pytest.raises(RunLimitError):
            operation()


def test_exhausted_allowance_blocks_live_before_planning_but_not_tutorials(tmp_path):
    service = svc(tmp_path, budget=PublicRunBudget(AtomicSlots(), limit=0))
    with TestClient(create_app(service, api_token='')) as client:
        with patch('anthropic.Anthropic', side_effect=AssertionError('No paid call when exhausted')):
            response = client.post('/chat', json={'prompt': 'Investigate TYK2'}, headers={
                'X-Anthropic-Api-Key': 'visitor-key', 'X-Anthropic-Model': 'model'})
            assert response.status_code == 429
            response = client.post('/investigations', json=demo_submission('missing-evidence').model_dump(mode='json'))
            assert response.status_code == 429
        assert not list(tmp_path.glob('*.json'))
        for demo in ('missing-evidence', 'cross-context-conflict'):
            response = client.post('/demos', json={'demo': demo})
            assert response.status_code == 202
            state = client.get(response.json()['status_url']).json()
            assert state['status'] in {'complete', 'partial'}
            assert client.get(response.json()['status_url'] + '/report').status_code == 200
        assert not service.futures
        assert not list(tmp_path.glob('*.json'))


def test_tutorial_cache_returns_isolated_snapshots():
    first = tutorial('cross-context-conflict')
    first.events.clear()
    first.request.question = 'Changed in one session'
    second = tutorial('cross-context-conflict')
    assert second.events
    assert second.request.question != first.request.question


def test_public_app_explicitly_ignores_previous_server_token(tmp_path, monkeypatch):
    monkeypatch.setenv('INVESTIGATION_API_TOKEN', 'old-private-token')
    with TestClient(create_app(svc(tmp_path), api_token='')) as client:
        assert client.get('/openapi.json').status_code == 200
        assert client.post('/demos', json={'demo': 'missing-evidence'}).status_code == 202
        assert client.post('/chat', json={'prompt': 'Investigate TYK2'}).status_code == 422


def test_tutorial_and_mcp_are_accessible_without_backend_or_credentials(monkeypatch):
    monkeypatch.setenv('INVESTIGATION_API_TOKEN', 'old-private-token')
    with patch('requests.post', side_effect=AssertionError('Tutorial must not contact backend')), \
         patch('requests.get', side_effect=AssertionError('Tutorial must not contact backend')):
        app = AppTest.from_file('../streamlit_app.py').run()
        assert not app.exception
        assert app.radio(key='experience').value == 'Try the tutorial'
        assert not app.text_input and not app.chat_input
        assert [metric.value for metric in app.metric] == ['Complete', 'Conflicting']
        assert len(app.get('download_button')) == 2
        next(r for r in app.radio if r.label == 'Tutorial case').set_value('Missing patient evidence').run()
        assert not app.exception
        assert [metric.value for metric in app.metric] == ['Partial', 'Not Assessable']
        app.radio(key='experience').set_value('Connect through MCP').run()
        assert not app.exception and not app.text_input
        assert any('claude mcp add --transport http' in code.value for code in app.code)
        app.radio(key='experience').set_value('Investigate with your key').run()
        assert not app.exception
        assert [field.label for field in app.text_input] == ['Your Anthropic API key', 'Anthropic model ID']
        assert app.chat_input[0].disabled
