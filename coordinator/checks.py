"""Deterministic checks of declared, normalized evidence; not biological adjudication."""
from __future__ import annotations

from collections import Counter

from .models import (
    Assessment, CheckResult, ComparisonResult, ComparisonSpec, EvidenceBundle,
    EvidenceRecord, EvidenceRequirement, Gap, ResearchPlan,
)


_SCOPE = ("entity", "species", "context", "modality", "endpoint")
_CONTEXT_FIELDS = ("condition", "tissue", "host_species")
_MATCHED_SUBJECT = ("study_id", "subject_id", "specimen_id", "timepoint")


def _present(value: str | None) -> bool:
    return bool(value and value.strip())


def _qualifies(record: EvidenceRecord, requirement: EvidenceRequirement,
               duplicate_ids: set[str]) -> bool:
    return (
        record.level == "observation"
        and _present(record.id) and record.id not in duplicate_ids
        and _present(record.source) and _present(record.study_id)
        and any(_present(p) for p in record.provenance)
        and all(getattr(record, key) == getattr(requirement, key) for key in _SCOPE)
        and all(
            getattr(requirement, key) is None
            or (_present(getattr(requirement, key))
                and getattr(record, key) == getattr(requirement, key))
            for key in _CONTEXT_FIELDS
        )
    )


def _ids(records: list[EvidenceRecord]) -> list[str]:
    return sorted({r.id for r in records})


def _studies(records: list[EvidenceRecord]) -> set[str]:
    return {r.study_id for r in records if r.study_id}


def _pair_rejection(left: EvidenceRecord, right: EvidenceRecord,
                    spec: ComparisonSpec) -> str | None:
    if left.id == right.id:
        return "same evidence record on both sides"
    if left.endpoint != right.endpoint:
        return "different endpoints"
    if not _present(left.comparability_key) or not _present(right.comparability_key):
        return "missing comparability key"
    if left.comparability_key != right.comparability_key:
        return "different comparability keys"
    if not _present(left.contrast) or not _present(right.contrast):
        return "missing contrast"
    if left.contrast != right.contrast:
        return "different contrasts"
    if left.species != right.species and not _present(spec.cross_species_basis):
        return "missing declared cross-species basis"
    if left.modality != right.modality:
        if not _present(left.normalization_basis) or not _present(right.normalization_basis):
            return "missing cross-modal normalization basis"
        if left.normalization_basis != right.normalization_basis:
            return "different cross-modal normalization bases"
    for key in _CONTEXT_FIELDS:
        left_value, right_value = getattr(left, key), getattr(right, key)
        if left_value != right_value and not _present(spec.context_alignment_basis):
            mismatch = "missing" if not _present(left_value) or not _present(right_value) else "different"
            return f"{mismatch} {key} alignment without declared context-alignment basis"
    if spec.require_matched_subjects:
        if any(not _present(getattr(r, key))
               for r in (left, right) for key in _MATCHED_SUBJECT):
            return "missing study/subject/specimen/timepoint for subject matching"
        if any(getattr(left, key) != getattr(right, key) for key in _MATCHED_SUBJECT):
            return "unmatched study/subject/specimen/timepoint"
    if left.direction is None or right.direction is None:
        return "missing observed direction"
    return None


def _compare(spec: ComparisonSpec, requirements: dict[str, EvidenceRequirement],
             qualified: dict[str, list[EvidenceRecord]]) -> tuple[ComparisonResult, Gap | None]:
    left, right = qualified[spec.left], qualified[spec.right]
    pairs: list[tuple[EvidenceRecord, EvidenceRecord]] = []
    rejections: Counter[str] = Counter()
    for a in left:
        for b in right:
            reason = _pair_rejection(a, b, spec)
            if reason:
                rejections[reason] += 1
            else:
                pairs.append((a, b))

    matched_left = list({a.id: a for a, _ in pairs}.values())
    matched_right = list({b.id: b for _, b in pairs}.values())
    evidence_ids = _ids(matched_left + matched_right)
    coverage = (
        f"Comparable unique studies: {spec.left}={len(_studies(matched_left))}/"
        f"{requirements[spec.left].min_studies}, {spec.right}={len(_studies(matched_right))}/"
        f"{requirements[spec.right].min_studies}. "
        f"Qualified evidence IDs: {spec.left}={_ids(left)}, {spec.right}={_ids(right)}. "
        f"Compared evidence IDs: {evidence_ids}."
    )
    if rejections:
        coverage += " Excluded candidate pairs: " + "; ".join(
            f"{reason} ({count})" for reason, count in sorted(rejections.items())
        ) + ". Pair counts are not independent evidence counts."
    if _present(spec.context_alignment_basis):
        coverage += f" Context alignment basis is declared, not verified: {spec.context_alignment_basis!r}."
    for key in _CONTEXT_FIELDS:
        values = {getattr(r, key) for r in matched_left + matched_right}
        if any(_present(value) for value in values):
            labels = sorted(value if _present(value) else "<missing>" for value in values)
            coverage += f" Compared declared {key}: {labels}."

    enough = bool(pairs) and all(
        len(_studies(records)) >= requirements[req_id].min_studies
        for req_id, records in ((spec.left, matched_left), (spec.right, matched_right))
    )
    if not enough:
        detail = "No comparison meeting the declared evidence and comparability criteria. " + coverage
        # Missing records or fields can sometimes be retrieved without changing the plan.
        retryable = not left or not right or any(
            reason.startswith("missing ") and reason != "missing declared cross-species basis"
            for reason in rejections
        )
        return (
            ComparisonResult(id=spec.id, conclusion="not_assessable",
                             evidence_ids=evidence_ids, detail=detail),
            Gap(code="comparison_not_assessable", detail=f"{spec.id}: {detail}",
                retryable=retryable),
        )

    left_directions = {r.direction for r in matched_left}
    right_directions = {r.direction for r in matched_right}
    if "unchanged" in left_directions | right_directions:
        conclusion = "inconclusive"
        detail = "Unchanged observations do not establish directional corroboration. "
    elif len(left_directions) > 1 or len(right_directions) > 1:
        conclusion = "inconclusive"
        detail = "Heterogeneous observed directions are retained; no pooled agreement is inferred. "
    elif left_directions == right_directions:
        conclusion = "supported"
        detail = "Descriptive direction concordance for the declared endpoint in the compared subset. "
    else:
        conclusion = "conflicting"
        detail = "Opposing observed directions for the declared endpoint in the compared subset. "
    detail += coverage
    if not spec.require_matched_subjects:
        detail += " Subject pairing was not required; this is not within-person corroboration."
    if requirements[spec.left].species != requirements[spec.right].species:
        detail += f" Cross-species basis is declared, not verified: {spec.cross_species_basis!r}."
    return ComparisonResult(id=spec.id, conclusion=conclusion,
                            evidence_ids=evidence_ids, detail=detail), None


def assess(plan: ResearchPlan, bundle: EvidenceBundle) -> Assessment:
    """Check fixed criteria and descriptive directions without revising the research plan.

    Scope labels, source provenance, normalization, and comparison bases are supplied
    declarations. This checks their structure/consistency, not the source's truth or
    the validity of an experimental design, effect estimate, or pathway-activity call.
    """
    # Collection gaps remain on the bundle; these are assessment-derived gaps only.
    gaps: list[Gap] = []
    duplicate_ids = {key for key, count in Counter(r.id for r in bundle.records).items() if count > 1}
    if duplicate_ids:
        gaps.append(Gap(code="duplicate_evidence_ids", detail=(
            f"Ambiguous duplicate evidence IDs excluded: {sorted(duplicate_ids)}."
        )))
    requirements = {r.id: r for r in plan.requirements}
    qualified = {
        r.id: [record for record in bundle.records if _qualifies(record, r, duplicate_ids)]
        for r in plan.requirements
    }
    checks: list[CheckResult] = []
    for requirement in plan.requirements:
        records = qualified[requirement.id]
        studies = sorted(_studies(records))
        passed = len(studies) >= requirement.min_studies
        scope_fields = _SCOPE + tuple(
            key for key in _CONTEXT_FIELDS if getattr(requirement, key) is not None
        )
        detail = (
            f"Exact declared scope: " + ", ".join(
                f"{key}={getattr(requirement, key)!r}" for key in scope_fields
            ) + f". Qualified unique studies: {len(studies)}/{requirement.min_studies}; "
            f"study IDs={studies}; evidence IDs={_ids(records)}. "
            "Requires observation level, unique nonempty evidence ID, source, provenance and study ID. "
            "Study IDs are counted once; distinct IDs do not prove independent cohorts."
        )
        checks.append(CheckResult(id=requirement.id, passed=passed,
                                  required=requirement.required, evidence_ids=_ids(records), detail=detail))
        if not passed:
            gaps.append(Gap(code="missing_required_evidence" if requirement.required else "missing_optional_evidence",
                            detail=f"{requirement.id}: {detail}", gene=requirement.entity,
                            retryable=True))

    comparisons: list[ComparisonResult] = []
    for spec in plan.comparisons:
        comparison, gap = _compare(spec, requirements, qualified)
        comparisons.append(comparison)
        if gap:
            gaps.append(gap)

    mandatory_met = all(c.passed for c in checks if c.required)
    comparison_met = all(c.conclusion != "not_assessable" for c in comparisons)
    conclusions = {c.conclusion for c in comparisons}
    if not mandatory_met or not comparisons or not comparison_met:
        conclusion = "not_assessable"
    elif "conflicting" in conclusions:
        conclusion = "conflicting"
    elif "inconclusive" in conclusions:
        conclusion = "inconclusive"
    else:
        conclusion = "supported"

    gaps.extend([
        Gap(code="declared_metadata", detail=(
            "Scope (including condition, tissue and host species), observation labels, study identities, "
            "provenance, comparison keys and bases are declared "
            "normalized inputs. Structural checks do not verify source accuracy, cohort independence, "
            "normalization validity or biological comparability."
        )),
        Gap(code="descriptive_only", detail=(
            "Supported means descriptive direction concordance only. Abundance is not pathway activity; "
            "orthology is not conserved activity; cohort agreement is not within-patient agreement. "
            "No statistical significance, causal mechanism, clinical efficacy or general biological validation is established."
        )),
    ])
    return Assessment(checks=checks, comparisons=comparisons, conclusion=conclusion,
                      criteria_met=mandatory_met and comparison_met, gaps=gaps)
