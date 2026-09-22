"""Versioned research contracts. Scientific thresholds are supplied, never invented."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Context = Literal["in_vitro", "in_vivo", "patients"]
CONTEXTS = ("in_vitro", "in_vivo", "patients")
TERMINAL = {"complete", "partial", "failed", "needs_input"}


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Criterion(ContractModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    description: str = Field(min_length=1, max_length=1200)
    context: Context
    study_id: str = Field(min_length=1, max_length=100)
    species: str = Field(min_length=1, max_length=100)
    tissue: str = Field(min_length=1, max_length=100)
    feature: str = Field(min_length=1, max_length=80)
    modalities: list[Literal["RNA", "protein", "activity"]] = Field(min_length=1, max_length=3)
    quantity: Literal["abundance", "activity"]
    control: str = Field(min_length=1, max_length=100)
    treatment: str = Field(min_length=1, max_length=100)
    control_timepoint: str = Field(min_length=1, max_length=100)
    treatment_timepoint: str = Field(min_length=1, max_length=100)
    expected_direction: Literal["increase", "decrease"]
    min_abs_log2_fold_change: float = Field(gt=0, le=20)
    min_pairs: int = Field(ge=2, le=1000)
    confidence_level: float = Field(gt=0.5, lt=1)
    rationale: str = Field(min_length=1, max_length=2000)
    required: bool = True
    matched_modalities: bool = True
    method: Literal["paired_log2_ratio_t_interval"] = "paired_log2_ratio_t_interval"

    @model_validator(mode="after")
    def unique_modalities(self):
        if len(set(self.modalities)) != len(self.modalities):
            raise ValueError("Criterion modalities must be unique.")
        if self.control == self.treatment:
            raise ValueError("Control and treatment labels must differ.")
        return self


class Observation(ContractModel):
    id: str = Field(min_length=1, max_length=100)
    study_id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=1000)
    context: Context
    species: str = Field(min_length=1, max_length=100)
    host_species: str | None = Field(default=None, max_length=100)
    tissue: str = Field(min_length=1, max_length=100)
    feature: str = Field(min_length=1, max_length=80)
    modality: Literal["RNA", "protein", "activity", "DNA", "phosphorylation", "RT-qPCR", "functional"]
    quantity: Literal["abundance", "activity", "association", "other"]
    assay: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=100)
    condition: str = Field(min_length=1, max_length=100)
    subject_id: str | None = Field(default=None, max_length=100)
    specimen_id: str | None = Field(default=None, max_length=100)
    timepoint: str | None = Field(default=None, max_length=100)
    value: float = Field(gt=0)
    origin: Literal["processed_data", "synthetic_fixture"]


class SampleIdentity(ContractModel):
    observation_id: str
    subject_id: str = Field(min_length=1, max_length=100)
    specimen_id: str = Field(min_length=1, max_length=100)
    timepoint: str = Field(min_length=1, max_length=100)


class SampleMap(ContractModel):
    id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=1000)
    entries: list[SampleIdentity] = Field(min_length=1, max_length=3000)


class SpeciesMapping(ContractModel):
    species: str
    feature: str
    canonical_feature: str
    orthology_type: Literal["one_to_one", "one_to_many", "many_to_many", "unmapped"]
    source: str = Field(min_length=1, max_length=1000)
    reviewed: bool


class Budget(ContractModel):
    max_seconds: int = Field(default=180, ge=10, le=600)
    max_tool_calls: int = Field(default=10, ge=1, le=20)
    max_model_calls: int = Field(default=3, ge=0, le=5)
    max_output_tokens: int = Field(default=3000, ge=500, le=10000)
    max_total_tokens: int = Field(default=24000, ge=1000, le=100000)


class InvestigationRequest(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    intent: str = Field(min_length=3, max_length=4000)
    genes: list[str] = Field(default_factory=list, max_length=3)
    disease: str = Field(default="", max_length=200)
    criteria: list[Criterion] = Field(default_factory=list, max_length=12)
    criteria_confirmed: bool = False
    observations: list[Observation] = Field(default_factory=list, max_length=3000)
    available_sample_maps: list[SampleMap] = Field(default_factory=list, max_length=6)
    species_mappings: list[SpeciesMapping] = Field(default_factory=list, max_length=40)
    reference_packages: list[dict] = Field(default_factory=list, max_length=3)
    retrieve_reference: bool = True
    reference_required: bool = False
    budget: Budget = Field(default_factory=Budget)

    @model_validator(mode="after")
    def unique_ids(self):
        import re
        for values, label in (([c.id for c in self.criteria], "criterion"),
                              ([o.id for o in self.observations], "observation"),
                              ([m.id for m in self.available_sample_maps], "sample map")):
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate {label} IDs.")
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,39}", g) for g in self.genes):
            raise ValueError("Genes must be individual human gene symbols.")
        return self

    def digest(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()
