"""One bounded numerical adapter: paired sample-level log2 ratios.

Assumes positive processed abundance/activity measurements and independent biological
subjects with approximately normal log2 ratios. No pooled raw-assay scores, causal
claims, cell-level pseudoreplication, or population validation are produced.
"""
from __future__ import annotations

from collections import defaultdict
import math
import statistics

from scipy.stats import t

from coordinator.models import Criterion, Observation, SpeciesMapping


def assess(criterion: Criterion, observations: list[Observation], mappings: list[SpeciesMapping]) -> dict:
    c = criterion
    base = {"criterion_id": c.id, "context": c.context, "species": c.species,
            "study_id": c.study_id, "modalities": c.modalities, "required": c.required,
            "finding": "not_assessable", "checks": [], "calculations": [],
            "evidence_ids": [], "sources": [], "method": c.method,
            "scope": "Specified within-study paired contrasts; no causal or clinical validation."}

    def stop(code, detail):
        base["checks"].append({"code": code, "passed": False, "detail": detail})
        return base

    selected = []
    for o in observations:
        if (o.context, o.study_id, o.species, o.tissue) != (c.context, c.study_id, c.species, c.tissue):
            continue
        if o.modality not in c.modalities or o.condition not in (c.control, c.treatment):
            continue
        if o.feature == c.feature and c.species.lower() in ("human", "homo_sapiens", "homo sapiens"):
            selected.append(o)
        else:
            matches = [m for m in mappings if (m.species, m.feature, m.canonical_feature) == (o.species, o.feature, c.feature)]
            if len(matches) != 1 or not matches[0].reviewed or matches[0].orthology_type != "one_to_one":
                return stop("species_mapping", f"No unique reviewed one-to-one mapping for {o.feature} to {c.feature}.")
            selected.append(o)
    if not selected:
        return stop("measurements_missing", "No eligible processed measurements for this study, tissue, species and context.")
    base["evidence_ids"] = [o.id for o in selected]
    base["sources"] = sorted({o.source for o in selected})
    base["origins"] = sorted({o.origin for o in selected})
    base["measured_species"] = sorted({o.species for o in selected})
    base["host_species"] = sorted({o.host_species for o in selected if o.host_species})
    if len(base["origins"]) != 1:
        return stop("mixed_origins", "Synthetic and real measurements cannot be combined in a comparison.")
    if len({o.host_species for o in selected}) != 1:
        return stop("host_context", "Measurements have inconsistent host-species contexts.")
    if any(o.quantity != c.quantity for o in selected):
        return stop("assay_meaning", "Measured quantity does not match the criterion; abundance cannot establish activity.")
    if c.quantity == "activity" and c.modalities != ["activity"]:
        return stop("assay_meaning", "Activity requires explicitly identified activity measurements in this adapter.")
    if any(not o.subject_id or not o.specimen_id or not o.timepoint for o in selected):
        return stop("sample_identity", "Subject, specimen or time-point metadata is missing; a supplied sample map may recover it.")
    for o in selected:
        expected_time = c.control_timepoint if o.condition == c.control else c.treatment_timepoint
        if o.timepoint != expected_time:
            return stop("timepoint", f"Observation {o.id} does not match the predeclared condition/time-point comparison.")
    groups = defaultdict(dict)
    specimen_owners = {}
    for o in selected:
        key = (o.subject_id, o.condition)
        if key in groups[o.modality]:
            return stop("independent_replicates", "Repeated measurements for one subject/condition require a separate aggregation method.")
        groups[o.modality][key] = o
        specimen_key = o.specimen_id
        owner = (o.subject_id, o.condition, o.timepoint)
        if specimen_key in specimen_owners and specimen_owners[specimen_key] != owner:
            return stop("specimen_identity", "A specimen identifier maps to conflicting subjects, conditions or time points.")
        specimen_owners[specimen_key] = owner
    if set(groups) != set(c.modalities):
        return stop("modalities_missing", "At least one required measurement type is unavailable.")
    first = groups[c.modalities[0]]
    if c.matched_modalities:
        for modality in c.modalities[1:]:
            other = groups[modality]
            if set(other) != set(first):
                return stop("patient_pairing", "Modalities contain different biological subjects or conditions; within-person agreement cannot be assessed.")
            if any((first[k].specimen_id, first[k].timepoint) != (other[k].specimen_id, other[k].timepoint) for k in first):
                return stop("patient_pairing", "Modalities do not share specimen/time-point identifiers; within-person agreement cannot be assessed.")
    statuses = []
    for modality in c.modalities:
        data = groups[modality]
        if len({o.unit for o in data.values()}) != 1 or len({o.assay for o in data.values()}) != 1:
            return stop("assay_units", "Each modality's paired comparison requires consistent assay and units.")
        subjects = sorted({key[0] for key in data})
        if any((subject, c.control) not in data or (subject, c.treatment) not in data for subject in subjects):
            return stop("paired_contrast", "Control/treatment measurements are missing for at least one subject; no silent complete-case filtering.")
        if len(subjects) < c.min_pairs:
            return stop("replicate_count", f"{len(subjects)} independent pairs available; {c.min_pairs} required.")
        individuals = [{"subject_id": s, "control_specimen": data[s, c.control].specimen_id,
                        "treatment_specimen": data[s, c.treatment].specimen_id,
                        "log2_fold_change": math.log2(data[s, c.treatment].value) - math.log2(data[s, c.control].value),
                        "evidence_ids": [data[s, c.control].id, data[s, c.treatment].id]}
                       for s in subjects]
        effects = [r["log2_fold_change"] for r in individuals]
        mean = statistics.mean(effects)
        sem = statistics.stdev(effects) / math.sqrt(len(effects))
        margin = float(t.ppf((1 + c.confidence_level) / 2, len(effects) - 1)) * sem
        lower, upper = mean - margin, mean + margin
        sign = 1 if c.expected_direction == "increase" else -1
        aligned_low, aligned_high = (lower, upper) if sign == 1 else (-upper, -lower)
        finding = ("supported" if aligned_low > c.min_abs_log2_fold_change else
                   "conflicting" if aligned_high < -c.min_abs_log2_fold_change else "inconclusive")
        statuses.append(finding)
        base["calculations"].append({"modality": modality, "n_pairs": len(subjects),
            "mean_log2_fold_change": mean, "interval": [lower, upper], "confidence_level": c.confidence_level,
            "interval_method": "Student t interval over independent subject-level log2 ratios",
            "assumptions": "Independent biological subjects; approximately normal log2 ratios. No multiple-testing adjustment.",
            "finding": finding, "individuals": individuals})
    base["finding"] = ("conflicting" if "conflicting" in statuses else
                       "supported" if all(s == "supported" for s in statuses) else "inconclusive")
    base["checks"].append({"code": "comparison_executed", "passed": True,
                           "detail": "Required inputs passed structural checks; numerical results computed against fixed thresholds."})
    base["pairing_scope"] = "matched specimens" if c.matched_modalities else "separate modality cohorts; no within-person corroboration"
    return base
