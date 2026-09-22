import unittest

from coordinator.checks import assess
from coordinator.models import (
    ComparisonSpec, EvidenceBundle, EvidenceRecord, EvidenceRequirement, Gap, ResearchPlan,
)


def requirement(id="rna", **updates):
    values = dict(id=id, title=id, entity="TP53", species="human", context="patient",
                  modality="RNA", endpoint="abundance")
    values.update(updates)
    return EvidenceRequirement(**values)


def record(id="r1", **updates):
    values = dict(id=id, source="fixture", provenance=["fixture:1"], entity="TP53",
                  species="human", context="patient", modality="RNA", endpoint="abundance",
                  level="observation", study_id="study1", subject_id="patient1",
                  specimen_id="sample1", timepoint="baseline", direction="increase",
                  contrast="disease_vs_control", comparability_key="TP53_abundance",
                  normalization_basis="prespecified disease/control direction comparison")
    values.update(updates)
    return EvidenceRecord(**values)


def plan(requirements=None, comparisons=None):
    return ResearchPlan(question="Is TP53 abundance concordant?", genes=["TP53"],
                        requirements=requirements if requirements is not None else [
                            requirement(), requirement("protein", modality="protein")],
                        comparisons=comparisons if comparisons is not None else [
                            ComparisonSpec(id="rna_protein", left="rna", right="protein")])


def evaluate(records, research_plan=None):
    return assess(research_plan or plan(), EvidenceBundle(records=records))


class CheckTests(unittest.TestCase):
    def test_valid_support(self):
        result = evaluate([record(), record("p1", modality="protein")])
        self.assertTrue(result.criteria_met)
        self.assertEqual(result.conclusion, "supported")
        self.assertEqual(result.comparisons[0].evidence_ids, ["p1", "r1"])
        self.assertTrue(any(g.code == "declared_metadata" for g in result.gaps))

    def test_duplicate_study_does_not_meet_two_study_requirement(self):
        research_plan = plan([requirement(min_studies=2)], [])
        result = evaluate([record(), record("r2")], research_plan)
        self.assertFalse(result.criteria_met)
        self.assertFalse(result.checks[0].passed)
        self.assertIn("1/2", result.checks[0].detail)

    def test_missing_modality_is_not_satisfied_by_more_rna(self):
        result = evaluate([record(), record("r2", study_id="study2")])
        self.assertFalse(result.criteria_met)
        self.assertEqual(result.conclusion, "not_assessable")
        self.assertEqual(result.checks[1].evidence_ids, [])

    def test_exact_scope_and_traceability_are_required(self):
        changes = [dict(entity="EGFR"), dict(species="mouse"), dict(context="in_vitro"),
                   dict(endpoint="activity"), dict(source=""), dict(study_id=None),
                   dict(provenance=[]), dict(provenance=[" "]), dict(id="")]
        for change in changes:
            with self.subTest(change=change):
                self.assertFalse(evaluate([record(**change)], plan([requirement()], [])).criteria_met)

    def test_empty_and_background_only_bundles_fail(self):
        for records in ([], [record(level="background")]):
            with self.subTest(records=records):
                self.assertFalse(evaluate(records, plan([requirement()], [])).criteria_met)

    def test_subject_matching_requires_all_four_identifiers(self):
        research_plan = plan(comparisons=[ComparisonSpec(
            id="paired", left="rna", right="protein", require_matched_subjects=True)])
        for change in (dict(subject_id="patient2"), dict(study_id="study2"),
                       dict(specimen_id="sample2"), dict(timepoint="followup"), dict(timepoint=None)):
            with self.subTest(change=change):
                result = evaluate([record(), record("p1", modality="protein", **change)], research_plan)
                self.assertTrue(all(c.passed for c in result.checks))
                self.assertFalse(result.criteria_met)
                self.assertEqual(result.comparisons[0].conclusion, "not_assessable")
        self.assertTrue(evaluate([record(), record("p1", modality="protein")], research_plan).criteria_met)

    def test_different_endpoints_cannot_be_corroboration(self):
        research_plan = plan([requirement(), requirement("protein", modality="protein", endpoint="activity")])
        result = evaluate([record(), record("p1", modality="protein", endpoint="activity")], research_plan)
        self.assertTrue(all(c.passed for c in result.checks))
        self.assertFalse(result.criteria_met)
        self.assertIn("different endpoints", result.comparisons[0].detail)

    def test_comparison_labels_and_crossmodal_basis_are_required(self):
        for change in (dict(comparability_key=None), dict(comparability_key="other"),
                       dict(contrast=None), dict(contrast="control_vs_disease"),
                       dict(normalization_basis=None), dict(normalization_basis="other method"),
                       dict(direction=None)):
            with self.subTest(change=change):
                result = evaluate([record(), record("p1", modality="protein", **change)])
                self.assertFalse(result.criteria_met)
                self.assertEqual(result.conclusion, "not_assessable")

    def test_cross_species_requires_declared_basis_and_actual_observations(self):
        requirements = [requirement(), requirement("mouse", species="mouse", context="in_vivo")]
        observations = [record(), record("m1", species="mouse", context="in_vivo")]
        research_plan = plan(requirements, [ComparisonSpec(id="species", left="rna", right="mouse")])
        self.assertFalse(evaluate(observations, research_plan).criteria_met)
        with_basis = plan(requirements, [ComparisonSpec(id="species", left="rna", right="mouse",
            cross_species_basis="curated ortholog mapping; declared corresponding abundance contrast")])
        self.assertTrue(evaluate(observations, with_basis).criteria_met)
        orthology_only = [record(), record("m1", species="mouse", context="in_vivo", level="background")]
        self.assertFalse(evaluate(orthology_only, with_basis).criteria_met)

    def test_genuine_conflict_can_complete_investigation(self):
        result = evaluate([record(), record("p1", modality="protein", direction="decrease")])
        self.assertTrue(result.criteria_met)
        self.assertEqual(result.conclusion, "conflicting")

    def test_unchanged_and_heterogeneous_results_are_inconclusive(self):
        cases = [[record(), record("p1", modality="protein", direction="unchanged")],
                 [record(), record("r2", direction="decrease", study_id="study2"),
                  record("p1", modality="protein")]]
        for records in cases:
            with self.subTest(records=records):
                result = evaluate(records)
                self.assertTrue(result.criteria_met)
                self.assertEqual(result.conclusion, "inconclusive")

    def test_no_comparisons_can_complete_evidence_collection_but_not_validate(self):
        result = evaluate([record()], plan([requirement()], []))
        self.assertTrue(result.criteria_met)
        self.assertEqual(result.conclusion, "not_assessable")

    def test_comparable_subset_must_meet_study_minimum(self):
        research_plan = plan([requirement(min_studies=2), requirement("protein", modality="protein")])
        result = evaluate([record(), record("r2", study_id="study2", contrast="other"),
                           record("p1", modality="protein")], research_plan)
        self.assertTrue(all(c.passed for c in result.checks))
        self.assertFalse(result.criteria_met)
        self.assertEqual(result.comparisons[0].evidence_ids, ["p1", "r1"])

    def test_duplicate_evidence_ids_are_ambiguous(self):
        result = evaluate([record(), record(study_id="study2")], plan([requirement()], []))
        self.assertFalse(result.criteria_met)
        self.assertTrue(any(g.code == "duplicate_evidence_ids" for g in result.gaps))

    def test_same_record_cannot_corroborate_itself(self):
        research_plan = plan([requirement(), requirement("second")], [
            ComparisonSpec(id="self_comparison", left="rna", right="second")])
        result = evaluate([record()], research_plan)
        self.assertTrue(all(c.passed for c in result.checks))
        self.assertFalse(result.criteria_met)
        self.assertIn("same evidence record", result.comparisons[0].detail)

    def test_collection_failure_is_not_duplicated_or_a_completion_gate(self):
        bundle = EvidenceBundle(records=[record(), record("p1", modality="protein")],
                                gaps=[Gap(code="fetch_failed", detail="An optional source failed.")])
        result = assess(plan(), bundle)
        self.assertTrue(result.criteria_met)
        self.assertFalse(any(g.code == "fetch_failed" for g in result.gaps))

    def test_missing_optional_evidence_does_not_block(self):
        result = evaluate([record()], plan([requirement(), requirement("optional", modality="protein", required=False)], []))
        self.assertTrue(result.criteria_met)

    def test_declared_context_requirements_match_exactly(self):
        for field, expected in (("condition", "disease"), ("tissue", "liver"), ("host_species", "mus_musculus")):
            research_plan = plan([requirement(**{field: expected})], [])
            for actual in (None, "other", ""):
                with self.subTest(field=field, actual=actual):
                    result = evaluate([record(**{field: actual})], research_plan)
                    self.assertFalse(result.criteria_met)
                    self.assertIn(f"{field}={expected!r}", result.checks[0].detail)
            self.assertTrue(evaluate([record(**{field: expected})], research_plan).criteria_met)

    def test_context_mismatch_or_one_sided_missing_needs_alignment_basis(self):
        for field, value in (("condition", "disease"), ("tissue", "liver"), ("host_species", "mus_musculus")):
            for other in (None, "other"):
                with self.subTest(field=field, other=other):
                    records = [record(**{field: value}), record("p1", modality="protein", **{field: other})]
                    result = evaluate(records)
                    self.assertTrue(all(c.passed for c in result.checks))
                    self.assertFalse(result.criteria_met)
                    self.assertEqual(result.conclusion, "not_assessable")
                    self.assertIn(field, result.comparisons[0].detail)
                    research_plan = plan(comparisons=[ComparisonSpec(
                        id="aligned", left="rna", right="protein",
                        context_alignment_basis="prespecified context comparison; metadata differences retained")])
                    aligned = evaluate(records, research_plan)
                    self.assertTrue(aligned.criteria_met)
                    self.assertIn("Context alignment basis is declared, not verified", aligned.comparisons[0].detail)
                    self.assertIn(f"Compared declared {field}", aligned.comparisons[0].detail)

    def test_alignment_basis_cannot_override_required_scope_or_subject_matching(self):
        comparisons = [ComparisonSpec(id="paired", left="rna", right="protein",
            require_matched_subjects=True, context_alignment_basis="prespecified context comparison")]
        research_plan = plan(comparisons=comparisons)
        unpaired = evaluate([record(condition="disease"), record("p1", modality="protein",
            condition="other", subject_id="patient2")], research_plan)
        self.assertFalse(unpaired.criteria_met)
        self.assertIn("unmatched study/subject/specimen/timepoint", unpaired.comparisons[0].detail)
        fixed_scope = plan([requirement(condition="disease"), requirement("protein", modality="protein")], comparisons)
        wrong_condition = evaluate([record(condition="other"), record("p1", modality="protein")], fixed_scope)
        self.assertFalse(wrong_condition.criteria_met)
        self.assertFalse(wrong_condition.checks[0].passed)

    def test_requirement_entity_must_be_declared_in_plan(self):
        with self.assertRaisesRegex(ValueError, "Requirement entities"):
            plan([requirement(entity="EGFR")], [])


if __name__ == "__main__":
    unittest.main()
