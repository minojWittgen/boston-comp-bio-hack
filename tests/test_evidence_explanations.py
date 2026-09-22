from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from coordinator.checks import assess
from coordinator.models import (ComparisonSpec, EvidenceBundle, EvidenceRecord,
    EvidenceRequirement, InvestigationRequest, ResearchPlan, RunState)
from research_app.explanations import (comparison_explanations, criteria_origin,
    overview_explanation, requirement_explanations, source_contributions)
from research_app.report_ui import markdown_report
from research_app.sources import source_view


def state(records=(), minimum=1, paired=False, proposed=False):
    requirements = [EvidenceRequirement(id=c, title=f'MLH1 RNA in {c}', entity='MLH1',
                        species='homo_sapiens', context=c, modality='RNA', endpoint='RNA abundance',
                        min_studies=minimum if c == 'in_vitro' else 1)
                    for c in ['in_vitro', 'patient']]
    spec = ComparisonSpec(id='cells_vs_patients', left='in_vitro', right='patient', require_matched_subjects=paired)
    request = InvestigationRequest(question='SYNTHETIC DEMO: Compare MLH1 RNA in cells and patients',
                                   requirements=[] if proposed else requirements)
    plan = ResearchPlan(question=request.question, genes=['MLH1'], requirements=requirements, comparisons=[spec])
    evidence = EvidenceBundle(records=list(records))
    assessment = assess(plan, evidence)
    return RunState(run_id='a'*32, request=request, plan=plan, evidence=evidence, assessment=assessment,
                    status='complete' if assessment.criteria_met else 'partial')


def observation(id, study, context='in_vitro', **kwargs):
    return EvidenceRecord(id=id, source='synthetic-test', entity='MLH1', level='observation', study_id=study,
                          provenance=['https://example.org/study'], species='homo_sapiens', context=context,
                          modality='RNA', endpoint='RNA abundance', comparability_key='MLH1 RNA',
                          contrast='case versus control', direction='increase', **kwargs)


def reference(source, data, query=None, species='homo_sapiens'):
    return EvidenceRecord(id=source, source=source, entity='MLH1', species=species, level='background',
                          payload={'source_result': {'data': data, 'query': query or {}}})


def test_minimum_comes_from_saved_plan_and_is_not_number_of_rows():
    s = state([observation('a','study1'), observation('b','study1')], minimum=3, proposed=True)
    explanation = requirement_explanations(s)[0]
    assert explanation['minimum'] == 3
    assert explanation['qualifying_studies'] == 1
    assert not explanation['passed']
    assert 'model proposed' in criteria_origin(s)
    assert 'submitted research request' in criteria_origin(state())
    report = markdown_report(s)
    assert 'not a statistical sample-size calculation' in report
    assert 'minimum study count: 3; qualifying studies supplied: 1' in report


def test_numeric_database_data_stays_visible_without_counting_as_studies():
    s = state([reference('gtex', {'tissues': [{'tissue': 'Colon_Sigmoid', 'median_tpm': 23.9729}]}),
               reference('ensembl_orthology', {'orthologs': [{'target_symbol': 'Mlh1', 'target_id': 'ENSMUSG00000032498',
                         'species': 'mus_musculus', 'perc_id_target': 88.2895, 'perc_id_source': 88.7566}]},
                         {'target_species': 'mus_musculus'}, 'mus_musculus')], proposed=True)
    before = s.model_dump_json()
    findings = source_contributions(s)
    assert '23.97 TPM' in findings[0]['finding']
    assert '88.29%' in findings[1]['finding'] and '88.76%' in findings[1]['finding']
    assert 'not an RNA-abundance measurement' in findings[1]['role']
    assert all(r['qualifying_studies'] == 0 for r in requirement_explanations(s))
    text = overview_explanation(s)
    assert '2 reference records' in text and 'current evidence integration' in text
    assert 'More records of the same type alone' in text
    assert s.model_dump_json() == before


def test_scope_qualified_and_actually_comparable_studies_are_distinguished():
    a, b, p = observation('a','study1'), observation('b','study2'), observation('p','patients', context='patient')
    b.contrast = 'different comparison group'
    s = state([a,b,p], minimum=2)
    explanation = comparison_explanations(s)['cells_vs_patients']
    assert explanation['counts'][0]['Studies meeting scope and traceability'] == 2
    assert explanation['counts'][0]['Studies usable in this comparison'] == 1
    assert any('different reference or comparison groups' in r for r in explanation['reasons'])
    assert s.assessment.conclusion == 'not_assessable'


def test_sample_identity_is_only_required_for_matched_comparisons():
    s = state([observation('a','study1'), observation('p','study2', context='patient')])
    unpaired = comparison_explanations(s)['cells_vs_patients']
    assert 'not required' in unpaired['identity']
    assert s.assessment.conclusion == 'supported'
    paired = state(s.evidence.records, paired=True)
    details = comparison_explanations(paired)['cells_vs_patients']
    assert 'requires the same study, participant, sample and time point' in details['identity']
    assert any('information needed to match individuals is missing' in r for r in details['reasons'])


def test_differing_outcome_names_are_a_plan_problem_not_a_demand_for_more_studies():
    s = state()
    s.plan.requirements[1].endpoint = 'RNA abundance in patient tissue'
    s.plan.requirements[1].species = 'mus_musculus'
    before = s.model_dump_json()
    explanation = comparison_explanations(s)['cells_vs_patients']
    assert any('even enough studies would not make this plan comparable' in i for i in explanation['plan_issues'])
    assert any('No basis for comparing these species' in i for i in explanation['plan_issues'])
    assert s.model_dump_json() == before  # Never repair or rewrite a saved plan in the presenter.


def test_missing_direction_and_measurement_matching_reasons_are_readable():
    a, p = observation('a','study1'), observation('p','study2',context='patient')
    p.direction = None
    s = state([a,p])
    reasons = comparison_explanations(s)['cells_vs_patients']['reasons']
    assert reasons == ['A measured increase, decrease or unchanged result was not supplied.']
    assert 'Pair counts' not in markdown_report(s)


def test_why_tab_is_visible_without_a_model_call():
    s = state([reference('hpa_cell_lines', {'rna': {'cell_line_distribution': 'Detected in all'}})], proposed=True)
    with patch('research_app.client.InvestigationClient.get',return_value=s), \
         patch('research_app.client.InvestigationClient.chat',side_effect=AssertionError('No model calls')):
        app = AppTest.from_file('../streamlit_app.py')
        app.query_params['report'] = s.run_id
        app.run()
        assert not app.exception
        assert app.tabs[0].label == 'Why this result?'
        text = '\n'.join(m.value for m in list(app.markdown) + list(app.caption))
        assert 'not a scientific sample-size calculation' in text
        assert 'model proposed' in text
        assert 'current evidence integration' in text
        assert any('Finding in the returned data' in table.value.columns for table in app.table)
