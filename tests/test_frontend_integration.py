import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from coordinator.engine import Coordinator
from coordinator.evidence import DirectoryEvidenceProvider
from coordinator.models import RunState
from coordinator.planner import ExplicitPlanner
from coordinator.store import FileRunStore
from research_app.api import create_app
from research_app.presentation import assistant_summary, context_coverage
from research_app.service import ChatMessage, DemoRequest, EXAMPLES, RunService, demo_submission

MODEL_HEADERS = {'X-Anthropic-Api-Key': 'test-visitor-key', 'X-Anthropic-Model': 'test-model'}

class RecordingPlanner:
    def __init__(self):
        self.requests = []

    def plan(self, request):
        self.requests.append(request)
        plan = ExplicitPlanner().plan(demo_submission('missing-evidence').request)
        return plan.model_copy(update={'question': request.question})


def service(tmp_path, planner=None, provider=None, dispatch=None):
    engine = Coordinator(planner or ExplicitPlanner(), provider or DirectoryEvidenceProvider(EXAMPLES / 'packages'), FileRunStore(tmp_path))
    fake_planner = planner or RecordingPlanner()
    return RunService(engine, dispatch=dispatch, plan_chat=lambda request, credentials: fake_planner.plan(request))


def wait(service, run_id):
    for _ in range(200):
        state = service.get(run_id)
        if state.status in {'complete', 'partial', 'failed'}:
            return state
        time.sleep(.005)
    raise AssertionError('Job did not complete')


@pytest.mark.parametrize('name,status,conclusion', [
    ('missing-evidence', 'partial', 'not_assessable'),
    ('cross-context-conflict', 'complete', 'conflicting'),
])
def test_frontend_examples_use_real_coordinator_and_report(tmp_path, name, status, conclusion):
    svc = service(tmp_path)
    with TestClient(create_app(svc)) as client:
        response = client.post('/demos', json={'demo': name})
        assert response.status_code == 202
        state = wait(svc, response.json()['run_id'])
        assert (state.status, state.assessment.conclusion) == (status, conclusion)
        report = client.get(f'/investigations/{state.run_id}/report')
        assert report.text == state.report
        assert 'SYNTHETIC DEMO' in report.text
        assert RunState.model_validate(client.get(response.json()['status_url']).json()) == state
        cards = context_coverage(state)
        assert [r['total'] for r in cards] == [1, 1, 2]
        assert state.investigation.criteria_met == (status == 'complete')
        assert cards[2]['passed'] == sum(c.status == 'addressed' for c in state.investigation.coverage
                                       if c.requirement_id in {r.id for r in state.plan.requirements if r.context == 'patient'})
        summary = assistant_summary(state)
        assert ('Investigation complete' if status == 'complete' else 'Collection incomplete') in summary
        assert 'not enough comparable evidence' not in summary
        assert 'synthetic' in summary.lower()


def test_http_canonical_submission_auth_and_openapi(tmp_path):
    svc = service(tmp_path)
    with TestClient(create_app(svc, api_token='test-team-code')) as client:
        assert client.get('/health').status_code == 200
        assert client.post('/chat', json={'prompt': 'Investigate TYK2'}).status_code == 401
        assert client.post('/mcp', json={}).status_code == 401
        headers = {'Authorization': 'Bearer test-team-code'}
        spec = client.get('/openapi.json', headers=headers).json()
        assert spec['paths']['/investigations']['post']['requestBody']['content']['application/json']['schema']['$ref'].endswith('/Submission')
        payload = demo_submission('cross-context-conflict').model_dump(mode='json')
        assert client.post('/investigations', json=payload['request'], headers=headers).status_code == 422
        started = client.post('/investigations', json=payload, headers=headers)
        assert started.status_code == 202
        assert wait(svc, started.json()['run_id']).assessment.conclusion == 'conflicting'
        assert client.post('/demos', json={'demo': '../secret'}, headers=headers).status_code == 422


def test_chat_only_passes_researcher_intent_to_team_planner(tmp_path):
    planner = RecordingPlanner()
    svc = service(tmp_path, planner)
    initial = svc.chat(ChatMessage(prompt='Compare TYK2 RNA across biological contexts'))
    parent = wait(svc, initial['run_id'])
    followup = svc.chat(ChatMessage(prompt='Focus on skin tissue', previous_investigation_id=parent.run_id))
    child = wait(svc, followup['run_id'])
    assert child.request.question == parent.request.question + '\n\nResearcher clarification: Focus on skin tissue'
    assert planner.requests[1].question == child.request.question
    assert planner.requests[1].requirements == []
    assert planner.requests[1].comparisons == []
    assert parent.report not in child.request.question
    assert svc.get(parent.run_id) == parent
    svc.close()


def test_chat_refuses_pending_parent_and_never_silently_uses_fixture(tmp_path):
    svc = service(tmp_path, dispatch=lambda *args: None)
    pending = svc.chat(ChatMessage(prompt='Investigate TYK2 in psoriasis'))
    with pytest.raises(ValueError, match='finish'):
        svc.chat(ChatMessage(prompt='Focus on skin tissue', previous_investigation_id=pending['run_id']))
    with TestClient(create_app(svc)) as client:
        assert client.post('/chat', json={'prompt': 'Focus on skin', 'previous_investigation_id': 'a'*32}, headers=MODEL_HEADERS).status_code == 404
        assert client.get(f"/investigations/{pending['run_id']}/report").status_code == 409


def test_failed_planning_returns_visible_error_before_creating_job(tmp_path):
    from coordinator.planner import PlanningError
    class Fail:
        def plan(self, request):
            raise PlanningError('The research plan does not satisfy the required schema.')
    svc = service(tmp_path, Fail())
    with TestClient(create_app(svc)) as client:
        response = client.post('/chat', json={'prompt': 'Investigate TYK2 in psoriasis'}, headers=MODEL_HEADERS)
        assert response.status_code == 422
        assert 'required schema' in response.json()['detail']
        assert not list(tmp_path.glob('*.json'))


def test_dispatch_failure_is_persisted_and_returned(tmp_path):
    def fail(*args):
        raise RuntimeError('do not expose provider credential')
    svc = service(tmp_path, dispatch=fail)
    with TestClient(create_app(svc)) as client:
        assert client.post('/chat', json={'prompt': 'Investigate TYK2'}, headers=MODEL_HEADERS).status_code == 503
        saved = list(tmp_path.glob('*.json'))
        state = RunState.model_validate_json(saved[0].read_text())
        assert state.status == 'failed'
        assert 'credential' not in state.model_dump_json()


@pytest.mark.asyncio
async def test_mcp_and_frontend_share_canonical_results(tmp_path):
    svc = service(tmp_path)
    app = create_app(svc)
    async with Client(app.state.mcp) as client:
        assert {t.name for t in (await client.list_tools()).tools} == {'start_investigation', 'get_investigation'}
        started = await client.call_tool('start_investigation', {'request': {'demo': 'cross-context-conflict'}})
        assert not started.is_error
        run_id = started.structured_content['run_id']
        for _ in range(100):
            result = await client.call_tool('get_investigation', {'investigation_id': run_id})
            assert not result.is_error
            if result.structured_content['status'] == 'complete':
                break
            await asyncio.sleep(.01)
        assert result.structured_content == svc.get(run_id).model_dump(mode='json')
        assert result.structured_content['assessment']['conclusion'] == 'conflicting'
    svc.close()
