"""Research reports must expose real provenance without presenting diagnostics as findings."""
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from coordinator.models import (EvidenceBundle, EvidenceRecord, Gap, InvestigationAssessment,
    ResearchComparison, ResearchCoverage, ResearchFinding, RunState)
from research_app.presentation import assistant_summary, comparison_views, context_coverage, search_status
from research_app.report_ui import markdown_report
from research_app.sources import MISSING, safe_url, source_view
from research_app.tutorials import tutorial


def record(source, data=None, query=None, **kwargs):
    return EvidenceRecord(id='internal-record-id', source=source, entity='MLH1',
                          payload={'source_result': {'data': data or {}, 'query': query or {}}}, **kwargs)


def live_state():
    state = tutorial('missing-evidence')
    state.investigation = None  # Historical reports preserve their original interpretation.
    state.run_id = 'f' * 32
    state.request.question = 'Compare gene RNA in cells, mice and patients'
    state.plan.question = state.request.question
    state.evidence = EvidenceBundle(records=[
        record('pubmed', {'count': 3229, 'pmids': ['42770890', '20301390']}, {'term': 'MLH1 colorectal cancer'}),
        record('hpa_pathology', {'cancer_rna_distribution': 'Detected in all'}, {'ensg': 'ENSG00000076242'}),
        record('opentargets_depmap', {'n_tissues': 1, 'tissues': [{'tissueName': 'colon', 'screens': [
            {'cellLineName': 'HT29', 'geneEffect': -.1, 'expression': 4.2}]}]}, {'ensg': 'ENSG00000076242'}),
    ])
    for item in state.evidence.records:
        item.id = item.source
    return state


def investigation_state():
    state = live_state()
    state.status = 'complete'
    state.investigation = InvestigationAssessment(
        criteria_met=True, completion_reason='The requested sources were investigated and their limits documented.',
        findings=[ResearchFinding(evidence_id=r.id, entity=r.entity, source=r.source,
                    summary=source_view(r).summary, limitations=[source_view(r).limitation]) for r in state.evidence.records],
        coverage=[ResearchCoverage(requirement_id=r.id, status='addressed' if r.context == 'in_vitro' else 'limited',
                    evidence_ids=[state.evidence.records[2].id] if r.context == 'in_vitro' else [],
                    detail='Cell-line screens are available.' if r.context == 'in_vitro' else 'Retrieved categories provide partial context; matching cohorts remain an open question.')
                  for r in state.plan.requirements],
        comparisons=[ResearchComparison(id=state.plan.comparisons[0].id,
                    left_evidence_ids=['opentargets_depmap'], right_evidence_ids=['hpa_pathology'],
                    summary='Cell-line screens report expression 4.2; patient results report cancer-cohort categories.',
                    limitations=['These endpoints do not share a measurement scale.'])],
        limitations=['Patient matching has not been established.'], next_steps=['Inspect the retrieved study links.'])
    return state


def test_partial_evidence_does_not_mean_a_failed_search():
    state = live_state()
    assert search_status(state) == 'Finished'
    assert 'not enough comparable evidence' in assistant_summary(state)
    state.evidence.gaps.append(Gap(code='collection_error', detail='Internal exception'))
    assert search_status(state) == 'Some sources unavailable'
    assert 'some sources unavailable' in assistant_summary(state)
    assert 'Internal exception' not in assistant_summary(state)
    state.status = 'failed'
    assert search_status(state) == 'Could not finish'


def test_identifiers_and_links_are_from_supplied_source_data():
    view = source_view(live_state().evidence.records[0])
    assert '2 article identifiers from 3229 search matches' in view.summary
    assert any(url == 'https://pubmed.ncbi.nlm.nih.gov/42770890/' for _, url, _ in view.links)
    assert 'not screened studies' in view.limitation
    assert view.identities['Study ID'] == MISSING  # PMID hits are not qualified studies.
    assert view.identities['Participant / subject ID'] == MISSING
    assert 'internal-record-id' not in str(view)
    missing = source_view(record('gtex'))
    assert missing.links == []  # Never construct a gene URL from a guessed ID.
    assert 'Gene' not in missing.identities


def test_source_measurements_are_visible_without_becoming_validated_observations():
    state = live_state()
    before = state.model_dump_json()
    depmap = source_view(state.evidence.records[2])
    assert depmap.table[0]['Cell line'] == 'HT29'
    assert depmap.table[0]['CRISPR gene-effect score'] == -.1
    assert 'required by this question' not in depmap.limitation
    assert 'expression units' in depmap.limitation
    assert depmap.identities['Study ID'] == MISSING
    pathology = source_view(state.evidence.records[1])
    assert 'cohort' in pathology.limitation and 'not resolved' in pathology.limitation
    assert state.model_dump_json() == before


def test_study_and_sample_ids_are_preserved_when_supplied():
    view = source_view(record('lab', study_id='study-12', subject_id='patient-7', specimen_id='sample-9',
                              timepoint='day 1', level='observation', endpoint='RNA abundance', direction='increase',
                              provenance=['https://example.org/study/12']))
    assert view.identities == {'Study ID': 'study-12', 'Participant / subject ID': 'patient-7',
                               'Sample / specimen ID': 'sample-9', 'Time point': 'day 1'}
    assert view.links == [('Supplied source link 1', 'https://example.org/study/12', 'supplied')]
    assert view.facts['Measured outcome'] == 'RNA abundance'


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'https://user:secret@example.org', 'http://example.org', 'https://[invalid', 'https://example.org/\npath'])
def test_only_safe_https_source_links_are_clickable(url):
    assert safe_url(url) is None
    assert not source_view(record('lab', provenance=[url])).links


@pytest.mark.parametrize('source', ['mygene', 'ensembl_orthology', 'gtex', 'impc', 'opentargets', 'pubmed', 'hpa_cell_lines', 'hpa_pathology', 'opentargets_depmap', 'unrecognized'])
def test_missing_source_fields_never_invent_an_identity_or_break_the_report(source):
    view = source_view(record(source, {'tissues': None, 'orthologs': None, 'pmids': None}))
    assert all(kind == 'definition' for _, _, kind in view.links)
    assert view.identities['Study ID'] == MISSING


def test_readable_report_and_comparisons_keep_science_but_remove_internal_diagnostics():
    state = tutorial('cross-context-conflict')
    state.investigation = None
    before = state.model_dump_json()
    views = comparison_views(state)
    assert any(v['conclusion'] == 'Measurements disagree' for v in views)
    report = markdown_report(state)
    assert 'synthetic teaching example' in report
    for hidden in ['Qualified evidence IDs', 'Comparable unique studies:', '0/1', 'evidence_ids', '[]']:
        assert hidden not in report
    assert state.model_dump_json() == before
    report = markdown_report(live_state())
    assert 'https://pubmed.ncbi.nlm.nih.gov/42770890/' in report
    assert 'Participant / subject ID' in report and MISSING in report


def test_saved_report_renders_links_and_reopens_without_key_or_new_run():
    state = live_state()
    with patch('research_app.client.InvestigationClient.get', return_value=state) as get, \
         patch('research_app.client.InvestigationClient.chat', side_effect=AssertionError('No model call')):
        app = AppTest.from_file('../streamlit_app.py')
        app.query_params['report'] = state.run_id
        app.run()
        assert not app.exception
        assert [m.value for m in app.metric] == ['Finished', 'Not enough comparable evidence']
        assert [t.label for t in app.tabs] == ['Why this result?', 'Comparisons', 'Sources', 'What we needed to answer']
        assert any('PMID 42770890' in link.label for link in app.get('link_button'))
        assert any('Participant / subject ID: Not supplied' in text.value for text in app.text)
        assert not app.text_input[0].value
        assert app.chat_input[0].disabled
        assert get.call_count == 1
        app.radio(key='experience').set_value('Connect through MCP').run()
        app.radio(key='experience').set_value('Investigate with your key').run()
        assert not app.exception and get.call_count == 1
        app.button(key='new_conversation').click().run()  # Clear the saved report link.
        assert not app.query_params.get('report')
        assert not app.metric


def test_invalid_report_link_does_not_trigger_a_request():
    with patch('research_app.client.InvestigationClient.get', side_effect=AssertionError('Invalid ID must not be fetched')):
        app = AppTest.from_file('../streamlit_app.py')
        app.query_params['report'] = '../private'
        app.run()
        assert not app.exception
        assert app.radio(key='page').value == 'intro'


def test_investigation_findings_drive_summary_coverage_and_export():
    state = investigation_state()
    before = state.model_dump_json()
    assert state.assessment.conclusion == 'not_assessable'
    summary = assistant_summary(state)
    assert 'Investigation complete' in summary
    assert 'not enough comparable evidence' not in summary
    assert context_coverage(state)[0]['passed'] == 1
    assert 'Cell-line screens' in context_coverage(state)[0]['detail']
    assert comparison_views(state)[0]['detail'] == state.investigation.comparisons[0].summary
    report = markdown_report(state)
    from coordinator.engine import render_report
    assert report.startswith(render_report(state).rstrip())
    assert '4.2' in report and 'HT29' in report
    assert 'https://pubmed.ncbi.nlm.nih.gov/42770890/' in report
    assert 'Patient matching has not been established.' in report
    assert 'Inspect the retrieved study links.' in report
    assert state.model_dump_json() == before


def test_new_report_reopens_without_model_and_keeps_legacy_verdict_secondary():
    state = investigation_state()
    with patch('research_app.client.InvestigationClient.get', return_value=state), \
         patch('research_app.client.InvestigationClient.chat', side_effect=AssertionError('No model call')):
        app = AppTest.from_file('../streamlit_app.py')
        app.query_params['report'] = state.run_id
        app.run()
        assert not app.exception
        assert [m.value for m in app.metric] == ['Finished', 'Complete']
        assert [tab.label for tab in app.tabs] == ['Findings', 'Comparisons', 'Sources', 'What we needed to answer']
        visible = '\n'.join(item.value for item in list(app.markdown) + list(app.caption))
        assert 'expression 4.2' in visible
        assert 'not enough comparable evidence' not in visible.lower()
        assert any('PMID 42770890' in link.label for link in app.get('link_button'))


def test_incomplete_investigation_and_old_saved_schema_remain_distinct():
    state = investigation_state()
    state.status = 'partial'
    state.investigation.criteria_met = False
    state.investigation.completion_reason = 'One required source failed during collection.'
    assert 'Collection incomplete' in assistant_summary(state)
    raw = live_state().model_dump(mode='json')
    raw.pop('investigation')
    raw['schema_version'] = '0.1'
    legacy = RunState.model_validate(raw)
    assert legacy.investigation is None
    assert 'not enough comparable evidence' in assistant_summary(legacy)


def test_optional_observation_comparison_stays_secondary():
    state = tutorial('cross-context-conflict')
    assert state.investigation is not None and state.assessment.conclusion == 'conflicting'
    assert any(v['conclusion'] == 'Measurements disagree' for v in comparison_views(state, observation_only=True))
    with patch('research_app.client.InvestigationClient.get', return_value=state):
        app = AppTest.from_file('../streamlit_app.py')
        app.query_params['report'] = state.run_id
        app.run()
        assert not app.exception
        assert [m.value for m in app.metric] == ['Finished', 'Complete']
        assert any(e.label == 'Optional comparison of supplied study observations' for e in app.expander)
