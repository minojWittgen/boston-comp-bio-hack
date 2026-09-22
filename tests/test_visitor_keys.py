from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier
from unittest.mock import patch

import anthropic
from fastapi.testclient import TestClient
import httpx
from mcp import Client
import pytest

from coordinator.evidence import DirectoryEvidenceProvider
from coordinator.models import InvestigationRequest
from coordinator.planner import ExplicitPlanner
from coordinator.store import FileRunStore
from research_app.api import create_app
from research_app.client import InvestigationClient
from research_app.planning import PlanningCredentials, plan_with_credentials, public_coordinator
from research_app.service import EXAMPLES, RunService, demo_submission


def svc(tmp_path, **kwargs):
    engine = public_coordinator(FileRunStore(tmp_path))
    engine.provider = DirectoryEvidenceProvider(EXAMPLES / 'packages')
    return RunService(engine, **kwargs)


def credentials(key='visitor-test-key', model='visitor-test-model'):
    return PlanningCredentials.from_headers({'x-anthropic-api-key': key, 'x-anthropic-model': model})


def mock_provider(monkeypatch, handler):
    original = anthropic.Anthropic
    def factory(**kwargs):
        return original(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(anthropic, 'Anthropic', factory)


def plan_response(request):
    body = json.loads(request.content)
    intent = json.loads(body['messages'][0]['content'])['request']
    plan = ExplicitPlanner().plan(demo_submission('missing-evidence').request).model_dump(mode='json')
    plan['question'] = intent['question']
    return httpx.Response(200, json={
        'id': 'msg_test', 'type': 'message', 'role': 'assistant', 'model': body['model'],
        'content': [{'type': 'tool_use', 'id': 'tool_test', 'name': 'submit_research_plan', 'input': plan}],
        'stop_reason': 'tool_use', 'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 1},
    })


def test_missing_settings_never_use_host_key_or_create_job(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'host-key-must-not-be-used')
    monkeypatch.setenv('ANTHROPIC_MODEL', 'host-model')
    service = svc(tmp_path)
    with patch('anthropic.Anthropic', side_effect=AssertionError('Model must not be called')):
        with TestClient(create_app(service)) as client:
            for headers in ({}, {'X-Anthropic-Api-Key': 'visitor-test-key'}, {'X-Anthropic-Model': 'visitor-model'}):
                response = client.post('/chat', json={'prompt': 'Investigate TYK2'}, headers=headers)
                assert response.status_code == 422
                assert 'no shared model key' in response.json()['detail']
            response = client.post('/investigations', json={'request': {'question': 'Investigate TYK2'}})
            assert response.status_code == 422
            assert not list(tmp_path.glob('*.json'))


def test_concurrent_planning_uses_each_visitors_key_and_model(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'host-key')
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'host-token')
    monkeypatch.setenv('ANTHROPIC_MODEL', 'host-model')
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'https://unexpected.invalid')
    barrier, seen = Barrier(2), []
    def handler(request):
        seen.append((request.headers['x-api-key'], json.loads(request.content)['model']))
        assert request.url.host == 'api.anthropic.com'
        assert 'authorization' not in request.headers
        assert b'visitor-key' not in request.content
        barrier.wait(timeout=5)
        return plan_response(request)
    mock_provider(monkeypatch, handler)
    intent = InvestigationRequest(question='Compare TYK2 RNA across contexts')
    with ThreadPoolExecutor(2) as pool:
        plans = list(pool.map(lambda i: plan_with_credentials(intent, credentials(f'visitor-key-{i}', f'model-{i}')), range(2)))
    assert set(seen) == {('visitor-key-0', 'model-0'), ('visitor-key-1', 'model-1')}
    assert all(plan.question == intent.question for plan in plans)


def test_chat_only_dispatches_plan_and_research_data(tmp_path, monkeypatch):
    mock_provider(monkeypatch, plan_response)
    calls = []
    service = svc(tmp_path, dispatch=lambda *args: calls.append(args))
    with TestClient(create_app(service)) as client:
        response = client.post('/chat', json={'prompt': 'Compare TYK2 RNA across contexts'}, headers={
            'X-Anthropic-Api-Key': 'visitor-secret-not-in-jobs', 'X-Anthropic-Model': 'visitor-model'})
        assert response.status_code == 202
        assert len(calls) == 1
        run_id, submission, demo, plan = calls[0]
        assert demo is None and plan.question == submission.request.question
        assert 'visitor-secret' not in repr(calls)
        assert 'visitor-secret' not in client.get(response.json()['status_url']).text
        assert 'visitor-secret' not in (tmp_path / f'{run_id}.json').read_text()


@pytest.mark.parametrize('status,kind', [(401, 'authentication_error'), (429, 'rate_limit_error'), (400, 'invalid_request_error'), (403, 'permission_error'), (404, 'not_found_error')])
def test_provider_error_does_not_echo_secret_or_save_job(tmp_path, monkeypatch, status, kind):
    def handler(request):
        return httpx.Response(status, json={'type': 'error', 'error': {'type': kind, 'message': 'visitor-secret-here'}})
    mock_provider(monkeypatch, handler)
    with TestClient(create_app(svc(tmp_path))) as client:
        response = client.post('/chat', json={'prompt': 'Investigate TYK2'}, headers={
            'X-Anthropic-Api-Key': 'visitor-secret-here', 'X-Anthropic-Model': 'test-model'})
        assert response.status_code == 422
        assert 'visitor-secret-here' not in response.text
        assert not list(tmp_path.glob('*.json'))


@pytest.mark.asyncio
async def test_structured_mcp_needs_no_key_and_never_calls_model(tmp_path, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'host-key-must-not-be-used')
    service = svc(tmp_path)
    app = create_app(service)
    try:
        with patch('anthropic.Anthropic', side_effect=AssertionError('No model calls from MCP')):
            async with Client(app.state.mcp) as client:
                tools = (await client.list_tools()).tools
                schema = json.dumps(tools[0].input_schema)
                assert 'api_key' not in schema and 'ChatMessage' not in schema
                result = await client.call_tool('start_investigation', {'request': demo_submission('cross-context-conflict').model_dump(mode='json')})
                assert not result.is_error
                # Wait for the actual coordinator rather than just checking tool schema.
                import asyncio
                for _ in range(100):
                    state = service.get(result.structured_content['run_id'])
                    if state.status in {'complete', 'partial', 'failed'}:
                        break
                    await asyncio.sleep(.01)
                assert (state.status, state.assessment.conclusion) == ('complete', 'conflicting')
                rejected = await client.call_tool('start_investigation', {'request': {'request': {'question': 'Investigate TYK2'}}})
                assert rejected.is_error
                rejected = await client.call_tool('start_investigation', {'request': {'prompt': 'Investigate TYK2'}})
                assert rejected.is_error
    finally:
        service.close()


def test_client_sends_key_only_on_chat_and_refuses_insecure_destinations(monkeypatch):
    calls = []
    class Response:
        is_redirect = False
        def raise_for_status(self): pass
        def json(self): return {'run_id': 'a' * 32}
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr('requests.post', post)
    client = InvestigationClient('https://research.example', 'team-code')
    client.chat('Investigate TYK2', api_key='visitor-key', model='model')
    client.demo('missing-evidence')
    assert calls[0][1]['headers']['X-Anthropic-Api-Key'] == 'visitor-key'
    assert calls[0][1]['allow_redirects'] is False
    assert 'visitor-key' not in json.dumps(calls[0][1]['json'])
    assert 'X-Anthropic-Api-Key' not in calls[1][1]['headers']
    assert 'X-Anthropic-Api-Key' not in client.headers
    with pytest.raises(ValueError, match='HTTPS'):
        InvestigationClient('http://public.example').chat('Investigate TYK2', api_key='visitor-key', model='model')


def test_streamlit_model_settings_are_session_scoped_and_can_be_cleared(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv('COORDINATOR_API_TOKEN', raising=False)
    monkeypatch.delenv('INVESTIGATION_API_TOKEN', raising=False)
    first = AppTest.from_file('../streamlit_app.py').run()
    assert not first.exception
    first.radio(key='page').set_value('research').run()
    first.radio(key='experience').set_value('Investigate with your key').run()
    assert first.chat_input[0].disabled
    first.text_input(key='visitor_api_key').set_value('visitor-key-one')
    first.text_input(key='visitor_model').set_value('visitor-model').run()
    assert not first.chat_input[0].disabled
    for destination in ('Connect through MCP', 'Try the tutorial'):
        first.radio(key='experience').set_value(destination).run()
        assert not first.text_input
        first.radio(key='experience').set_value('Investigate with your key').run()
        assert first.text_input(key='visitor_api_key').value == 'visitor-key-one'
        assert first.text_input(key='visitor_model').value == 'visitor-model'
        assert not first.chat_input[0].disabled
    second = AppTest.from_file('../streamlit_app.py').run()
    second.radio(key='page').set_value('research').run()
    second.radio(key='experience').set_value('Investigate with your key').run()
    assert second.text_input(key='visitor_api_key').value == ''
    next(b for b in first.button if b.label == 'Clear API key').click().run()
    assert first.text_input(key='visitor_api_key').value == ''
    assert first.chat_input[0].disabled
    first.radio(key='experience').set_value('Connect through MCP').run()
    assert not first.text_input
    assert any('claude mcp add --transport http' in code.value for code in first.code)
    first.radio(key='experience').set_value('Investigate with your key').run()
    assert first.text_input(key='visitor_api_key').value == ''
    assert first.chat_input[0].disabled
