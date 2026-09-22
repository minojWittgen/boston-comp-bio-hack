"""Research reports must expose real provenance without presenting diagnostics as findings."""
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from coordinator.models import EvidenceBundle, EvidenceRecord, Gap
from research_app.presentation import assistant_summary, comparison_views, search_status
from research_app.report_ui import markdown_report
from research_app.sources import MISSING, safe_url, source_view
from research_app.tutorials import tutorial


def record(source, data=None, query=None, **kwargs):
    return EvidenceRecord(id='internal-record-id', source=source, entity='MLH1',
                          payload={'source_result': {'data': data or {}, 'query': query or {}}}, **kwargs)


def live_state():
    state = tutorial('missing-evidence')
    state.run_id = 'f' * 32
    state.request.question = 'Compare gene RNA in cells, mice and patients'
    state.plan.question = state.request.question
    state.evidence = EvidenceBundle(records=[
        record('pubmed', {'count': 3229, 'pmids': ['42770890', '20301390']}, {'term': 'MLH1 colorectal cancer'}),
        record('hpa_pathology', {'cancer_rna_distribution': 'Detected in all'}, {'ensg': 'ENSG00000076242'}),
        record('opentargets_depmap', {'n_tissues': 1, 'tissues': [{'tissueName': 'colon', 'screens': [
            {'cellLineName': 'HT29', 'geneEffect': -.1, 'expression': 4.2}]}]}, {'ensg': 'ENSG00000076242'}),
    ])
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
