"""Short previews preserve the full evidence and distinguish scope from conclusions."""
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from research_app.presentation import assistant_summary
from research_app.report_outline import comparison_outline, context_outline, named_references, preview_records
from research_app.report_ui import markdown_report
from research_app.tutorials import tutorial
from tests.test_research_report import investigation_state


def test_preview_is_bounded_and_covers_distinct_entities_and_contexts():
    state = investigation_state()
    original = state.evidence.records[2]
    for i in range(10):
        state.evidence.records.append(original.model_copy(update={'id': f'record-{i}', 'entity': f'GENE{i}', 'context': 'in_vitro'}))
    before = state.model_dump_json()
    preview = preview_records(state)
    assert len(preview) == 3
    assert original in preview  # Prioritize the record matching a requested scope.
    assert len({(r.entity, r.context) for r in preview}) == 3
    assert state.model_dump_json() == before


def test_context_and_comparison_previews_do_not_use_a_biological_verdict():
    state = investigation_state()
    before = state.model_dump_json()
    outline = context_outline(state)
    assert 'matching sources' in outline[0]['detail']
    assert 'related evidence only' in outline[2]['detail']
    assert all(len(row['detail']) < 160 for row in outline)
    sides = comparison_outline(state, state.investigation.comparisons[0])
    assert len(sides) == 2
    assert sides[0]['Source records'] == 1
    assert 'Sources match the requested scope' in sides[0]['Source coverage']
    assert 'Related evidence' in sides[1]['Source coverage']
    assert 'not_assessable' not in str(sides)
    assert state.model_dump_json() == before


def test_internal_references_become_names_without_changing_numbers_or_study_ids():
    state = investigation_state()
    record = state.evidence.records[0]
    req = state.plan.requirements[0]
    text = f'For {req.id}, inspect [{record.id}]. {record.id}=increase; PMID 42770890, 5.2 TPM.'
    named = named_references(state, text)
    assert f'For {req.title},' in named
    assert 'PubMed' in named and f'[{record.id}]' not in named
    assert 'direction=increase' in named
    assert 'PMID 42770890, 5.2 TPM.' in named


def test_short_report_keeps_full_findings_and_limits_available_without_model_calls():
    state = investigation_state()
    state.investigation.limitations += ['An additional specific limitation.', 'A final specific limitation.']
    before = state.model_dump_json()
    with patch('research_app.client.InvestigationClient.get', return_value=state), \
         patch('research_app.client.InvestigationClient.chat', side_effect=AssertionError('No model call')):
        app = AppTest.from_file('../streamlit_app.py')
        app.query_params['report'] = state.run_id
        app.run()
        assert not app.exception
        assert all(not e.proto.expanded for e in app.expander)
        text = '\n'.join(x.value for x in list(app.markdown) + list(app.caption))
        for finding in state.investigation.findings:
            assert finding.summary in text
        for note in state.investigation.limitations + state.investigation.next_steps:
            assert note in text
        assert any(e.label.startswith('What remains uncertain ·') for e in app.expander)
        assert any('PMID 42770890' in b.label for b in app.get('link_button'))
        assert '4.2' in markdown_report(state) and 'HT29' in markdown_report(state)
        assert len(assistant_summary(state)) < 240
        assert state.model_dump_json() == before


def test_comparison_picker_keeps_every_requested_comparison_accessible():
    state = tutorial('cross-context-conflict')
    with patch('research_app.client.InvestigationClient.get', return_value=state):
        app = AppTest.from_file('../streamlit_app.py')
        app.query_params['report'] = state.run_id
        app.run()
        selector = next(s for s in app.selectbox if s.label == 'Choose a comparison')
        assert len(selector.options) == len(state.investigation.comparisons)
        for comparison in state.investigation.comparisons:
            selector.set_value(comparison.id).run()
            assert not app.exception
            assert named_references(state, comparison.summary) in '\n'.join(x.value for x in app.markdown)
