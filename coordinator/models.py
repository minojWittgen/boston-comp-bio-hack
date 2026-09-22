"""Shared contracts. Data collection status and scientific conclusions are separate."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvidenceRequirement(Contract):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    entity: str = Field(min_length=1, description="Exact queried gene symbol from ResearchPlan.genes, or its supplied pathway ID. Keep this stable across species; put species in species and unverified ortholog aliases in assumptions, never in entity.")
    species: str = Field(min_length=1)
    context: Literal["in_vitro", "in_vivo", "patient", "reference"]
    modality: Literal["DNA", "RNA", "protein", "phenotype", "clinical"]
    endpoint: str = Field(min_length=1)
    condition: str | None = None
    tissue: str | None = None
    host_species: str | None = None
    min_studies: int = Field(default=1, ge=1, le=10, description="Minimum for optional supplied-observation diagnostics; not an investigation completion threshold.")
    required: bool = True


class ComparisonSpec(Contract):
    id: str = Field(min_length=1)
    left: str = Field(min_length=1, description="Evidence requirement ID")
    right: str = Field(min_length=1, description="Evidence requirement ID")
    require_matched_subjects: bool = False
    cross_species_basis: str | None = None
    context_alignment_basis: str | None = None


class PathwayDefinition(Contract):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)
    genes: list[str] = Field(min_length=1, max_length=10)


class InvestigationRequest(Contract):
    question: str = Field(min_length=5, max_length=6000)
    genes: list[str] = Field(default_factory=list, max_length=10)
    disease: str = ""
    mode: Literal["explore", "eval"] = "explore"
    requirements: list[EvidenceRequirement] = Field(default_factory=list, max_length=30)
    comparisons: list[ComparisonSpec] = Field(default_factory=list, max_length=20)
    pathway: PathwayDefinition | None = None
    max_revisions: int = Field(default=1, ge=0, le=1)


class ResearchPlan(Contract):
    question: str = Field(min_length=5)
    genes: list[str] = Field(min_length=1, max_length=10)
    disease: str = ""
    requirements: list[EvidenceRequirement] = Field(min_length=1, max_length=30, description="Research scope to discuss, including known gaps; not a requirement to prove a biological effect.")
    comparisons: list[ComparisonSpec] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list)
    claims_to_avoid: list[str] = Field(default_factory=lambda: [
        "Source retrieval is not biological validation.",
        "Orthology is not conserved pathway activity.",
        "Unpaired cohorts cannot establish within-patient agreement.",
        "Descriptive agreement does not establish causality or clinical efficacy.",
    ])
    pathway: PathwayDefinition | None = None

    @model_validator(mode="after")
    def validate_references(self):
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)) or not any(r.required for r in self.requirements):
            raise ValueError("Requirements need unique IDs and at least one mandatory criterion")
        comparisons = [c.id for c in self.comparisons]
        if len(comparisons) != len(set(comparisons)):
            raise ValueError("Comparison IDs must be unique")
        allowed_entities = set(self.genes) | ({self.pathway.id} if self.pathway else set())
        if any(r.entity not in allowed_entities for r in self.requirements):
            raise ValueError("Requirement entities must be declared genes or the supplied pathway ID")
        for c in self.comparisons:
            if c.left not in ids or c.right not in ids or c.left == c.right:
                raise ValueError("Comparisons must reference two distinct existing requirements")
        return self


class EvidenceRecord(Contract):
    id: str
    source: str
    source_version: str | None = None
    retrieved_at: str | None = None
    provenance: list[str] = Field(default_factory=list)
    entity: str
    species: str | None = None
    context: Literal["in_vitro", "in_vivo", "patient", "reference"] | None = None
    modality: Literal["DNA", "RNA", "protein", "phenotype", "clinical"] | None = None
    endpoint: str | None = None
    condition: str | None = None
    tissue: str | None = None
    host_species: str | None = None
    level: Literal["background", "observation"] = "background"
    study_id: str | None = None
    subject_id: str | None = None
    specimen_id: str | None = None
    timepoint: str | None = None
    direction: Literal["increase", "decrease", "unchanged"] | None = None
    contrast: str | None = None
    unit: str | None = None
    comparability_key: str | None = None
    normalization_basis: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class Gap(Contract):
    code: str
    detail: str
    source: str | None = None
    gene: str | None = None
    retryable: bool = False


class EvidenceBundle(Contract):
    records: list[EvidenceRecord] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    package_count: int = 0
    raw_packages: list[dict[str, Any]] = Field(default_factory=list)


class Submission(Contract):
    request: InvestigationRequest
    observations: list[EvidenceRecord] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_observations(self):
        ids = [r.id for r in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("Observation IDs must be unique")
        return self


class CheckResult(Contract):
    id: str
    passed: bool
    required: bool = True
    evidence_ids: list[str] = Field(default_factory=list)
    detail: str


Conclusion = Literal["supported", "conflicting", "inconclusive", "not_assessable"]


class ComparisonResult(Contract):
    id: str
    conclusion: Conclusion
    evidence_ids: list[str] = Field(default_factory=list)
    detail: str


class Assessment(Contract):
    checks: list[CheckResult]
    comparisons: list[ComparisonResult]
    conclusion: Conclusion
    criteria_met: bool
    gaps: list[Gap] = Field(default_factory=list)


class ResearchFinding(Contract):
    evidence_id: str
    entity: str
    source: str
    summary: str
    limitations: list[str] = Field(default_factory=list)


class ResearchCoverage(Contract):
    requirement_id: str
    status: Literal["addressed", "limited", "unavailable"]
    evidence_ids: list[str] = Field(default_factory=list)
    detail: str


class ResearchComparison(Contract):
    id: str
    left_evidence_ids: list[str] = Field(default_factory=list)
    right_evidence_ids: list[str] = Field(default_factory=list)
    summary: str
    limitations: list[str] = Field(default_factory=list)


class InvestigationAssessment(Contract):
    """Research completion and grounded synthesis, independent of biological proof."""
    criteria_met: bool
    checks: list[CheckResult] = Field(default_factory=list)
    findings: list[ResearchFinding] = Field(default_factory=list)
    coverage: list[ResearchCoverage] = Field(default_factory=list)
    comparisons: list[ResearchComparison] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    completion_reason: str


class RunState(Contract):
    schema_version: str = "0.2"
    run_id: str
    status: Literal["queued", "running", "complete", "partial", "failed"] = "queued"
    stage: str = "queued"
    request: InvestigationRequest
    plan: ResearchPlan | None = None
    plan_sha256: str | None = None
    evidence: EvidenceBundle | None = None
    assessment: Assessment | None = None
    investigation: InvestigationAssessment | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    attempts: int = 0
    report: str | None = None
    error: str | None = None
