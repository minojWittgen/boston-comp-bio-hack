"""Page navigation must not lose credentials, reports or the selected demo."""
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_research_report import investigation_state, live_state


def test_intro_and_references_work_offline_and_open_the_requested_workspace():
    with patch('requests.get', side_effect=AssertionError('No backend needed')), \
         patch('requests.post', side_effect=AssertionError('No paid calls')):
        app = AppTest.from_file('../streamlit_app.py').run()
        assert not app.exception
        assert app.radio(key='page').value == 'intro'
        assert app.title[0].value == 'Follow the evidence across contexts.'
        assert not app.text_input and not app.chat_input and not app.metric
        next(b for b in app.button if b.label == 'Explore a guided example').click().run()
        assert not app.exception
        assert app.radio(key='page').value == 'research'
        assert [m.value for m in app.metric] == ['Finished', 'Complete']
        app.radio(key='tutorial_case').set_value('Missing patient evidence').run()
        app.radio(key='page').set_value('references').run()
        assert not app.exception and not app.text_input and not app.chat_input
        copy = '\n'.join(m.value for m in app.markdown)
        assert 'arxiv.org/abs/2608.31076' in copy
        assert '/blob/main/data_pipeline/PIPELINE.md' in copy
        assert '/blob/main/cross-context-biology-agent.md' in copy
        app.radio(key='page').set_value('research').run()
        assert app.radio(key='tutorial_case').value == 'Missing patient evidence'
        app.radio(key='page').set_value('intro').run()
        next(b for b in app.button if b.label == 'Ask your own research question').click().run()
        assert app.radio(key='experience').value == 'Investigate with your key'
        assert app.chat_input[0].disabled


@pytest.mark.parametrize('state_factory', [live_state, investigation_state])
def test_credentials_conversation_and_report_survive_page_and_mode_changes(state_factory):
    state = state_factory()
    expected_result = 'Complete' if state.investigation else 'Not enough comparable evidence'
    with patch('research_app.client.InvestigationClient.get', return_value=state) as get, \
         patch('research_app.client.InvestigationClient.chat', side_effect=AssertionError('No new run')):
        app = AppTest.from_file('../streamlit_app.py')
        app.query_params['report'] = state.run_id
        app.run()
        assert app.radio(key='page').value == 'research'
        assert get.call_count == 1
        app.text_input(key='visitor_api_key').set_value('test-session-key')
        app.text_input(key='visitor_model').set_value('test-model').run()
        for destination in ('intro', 'references'):
            app.radio(key='page').set_value(destination).run()
            assert not app.exception and not app.text_input and not app.chat_input
            assert app.query_params['report'] == [state.run_id]
            app.radio(key='page').set_value('research').run()
            assert not app.exception
            assert app.radio(key='experience').value == 'Investigate with your key'
            assert app.text_input(key='visitor_api_key').value == 'test-session-key'
            assert app.text_input(key='visitor_model').value == 'test-model'
            assert [m.value for m in app.metric] == ['Finished', expected_result]
            assert [t.label for t in app.tabs][-1] == 'What we needed to answer'
            assert get.call_count == 1
        app.radio(key='experience').set_value('Connect through MCP').run()
        app.radio(key='page').set_value('references').run()
        app.radio(key='page').set_value('research').run()
        assert app.radio(key='experience').value == 'Connect through MCP'
        app.radio(key='experience').set_value('Investigate with your key').run()
        assert app.text_input(key='visitor_api_key').value == 'test-session-key'
        assert get.call_count == 1
        assert len(app.chat_message) == 2


def test_a_new_saved_report_opens_from_the_introduction_without_a_key():
    with patch('research_app.client.InvestigationClient.get', return_value=live_state()) as get:
        app = AppTest.from_file('../streamlit_app.py').run()
        assert app.radio(key='page').value == 'intro'
        app.query_params['report'] = live_state().run_id
        app.run()
        assert not app.exception
        assert app.radio(key='page').value == 'research'
        assert app.radio(key='experience').value == 'Investigate with your key'
        assert app.chat_input[0].disabled
        assert get.call_count == 1
