"""Generate a clearly synthetic development example; not a held-out evaluation."""
import json
from pathlib import Path


def fixture():
    request = {"intent": "DEVELOPMENT FIXTURE: assess paired RNA/protein abundance changes for a synthetic target across three contexts.",
               "genes": [], "retrieve_reference": False, "criteria_confirmed": True,
               "criteria": [], "observations": [], "species_mappings": [],
               "budget": {"max_seconds": 90, "max_tool_calls": 10, "max_model_calls": 3, "max_output_tokens": 3000}}
    for context, species, feature in [("in_vitro", "human", "DEMO1"), ("in_vivo", "mouse", "Demo1"), ("patients", "human", "DEMO1")]:
        study = f"synthetic-{context}"
        request["criteria"].append({"id": context, "description": "Synthetic paired abundance comparison; no biological claim.",
            "context": context, "study_id": study, "species": species, "tissue": "synthetic_tissue", "feature": "DEMO1",
            "modalities": ["RNA", "protein"], "quantity": "abundance", "control": "baseline", "treatment": "exposed",
            "control_timepoint": "t0", "treatment_timepoint": "t1", "expected_direction": "increase",
            "min_abs_log2_fold_change": 0.25, "min_pairs": 3, "confidence_level": 0.95,
            "rationale": "Demonstration-only rule fixed before generating this fixture; not a scientific threshold for real data."})
        for n, ratio in enumerate([1.8, 2.0, 2.2], start=1):
            for modality in ("RNA", "protein"):
                for condition, timepoint, value in [("baseline", "t0", 10), ("exposed", "t1", 10 * ratio)]:
                    request["observations"].append({"id": f"{context}-{n}-{modality}-{condition}", "study_id": study,
                        "source": "synthetic://development-example", "context": context, "species": species,
                        "host_species": species if context == "in_vivo" else None, "tissue": "synthetic_tissue", "feature": feature,
                        "modality": modality, "quantity": "abundance", "assay": f"synthetic_{modality}_assay", "unit": "arbitrary_positive_units",
                        "condition": condition, "subject_id": f"{context}-subject-{n}", "specimen_id": f"{context}-specimen-{n}-{timepoint}",
                        "timepoint": timepoint, "value": value, "origin": "synthetic_fixture"})
    request["species_mappings"] = [{"species": "mouse", "feature": "Demo1", "canonical_feature": "DEMO1",
        "orthology_type": "one_to_one", "source": "synthetic://reviewed-mapping", "reviewed": True}]
    return request


if __name__ == "__main__":
    Path(__file__).with_name("development-investigation.json").write_text(json.dumps(fixture(), indent=2) + "\n")
