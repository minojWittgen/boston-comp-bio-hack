"""Display and model projections of pipeline packages; no biological verdicts."""
from __future__ import annotations

import copy
import json

STATUSES = {"ok", "not_found", "error", "skipped"}
SOURCE_LABELS = {
    "mygene": "Gene identity", "ensembl_orthology": "Ensembl orthology",
    "gtex": "GTEx", "impc": "IMPC", "opentargets": "Open Targets", "pubmed": "PubMed",
}
CONTEXT_GAPS = {
    "In vitro": "No culture-level assay or expression matrix is supplied by this pipeline.",
    "In vivo": "IMPC provides mouse phenotype records, not the specified pathway comparison.",
    "Patients": "GTEx is reference tissue expression. Matched patient assays and individual variation are unavailable.",
}


def source_records(package: dict):
    yield "mygene", "human", package["gene"]
    for name, record in package["sources"].items():
        if name == "ensembl_orthology":
            for species, item in record.items():
                yield name, species, item
        else:
            yield name, "", record


def validate_package(package: dict) -> dict:
    if not isinstance(package, dict) or package.get("schema_version") != "0.1":
        raise ValueError("Expected an evidence-pipeline package with schema_version 0.1.")
    for key in ("run", "gene", "sources", "summary"):
        if not isinstance(package.get(key), dict):
            raise ValueError(f"Package field {key!r} must be an object.")
    if not isinstance(package.get("missing"), list):
        raise ValueError("Package must include a missing-source list.")
    required = {"ensembl_orthology", "gtex", "impc", "opentargets", "pubmed"}
    if not required.issubset(package["sources"]):
        raise ValueError("Package does not contain the five pipeline source entries.")
    if not isinstance(package["sources"]["ensembl_orthology"], dict):
        raise ValueError("Orthology must be a species-to-result mapping.")
    for name, _, item in source_records(package):
        if not isinstance(item, dict) or item.get("status") not in STATUSES:
            raise ValueError(f"Invalid source result: {name}.")
        if item.get("data") is not None and not isinstance(item["data"], dict):
            raise ValueError(f"Invalid source data: {name}.")
    return package


def source_rows(package: dict) -> list[dict]:
    return [{"Source": SOURCE_LABELS.get(name, name), "Species": species.replace("_", " "),
             "Status": item["status"], "Retrieved": item.get("retrieved_at", ""),
             "Detail": item.get("error") or ""}
            for name, species, item in source_records(package)]


def model_evidence(package: dict) -> dict:
    """Bound large result arrays without silently pretending the extract is complete."""
    result = copy.deepcopy(validate_package(package))
    omitted = []

    def trim(value, path="package"):
        if isinstance(value, list):
            if len(value) > 12:
                omitted.append({"path": path, "total": len(value), "included": 12})
            return [trim(item, f"{path}[{i}]") for i, item in enumerate(value[:12])]
        if isinstance(value, dict):
            return {key: trim(item, f"{path}.{key}") for key, item in value.items()}
        return value

    result = trim(result)
    result["excerpt_notice"] = {"truncated_arrays": omitted,
                                "full_package": "Available in the evidence panel and JSON download."}
    result["comparison_gaps"] = CONTEXT_GAPS
    return result


def package_symbol(package: dict) -> str:
    return (package["gene"].get("data") or {}).get("symbol") or package["gene"].get("query", {}).get("symbol", "Unresolved")


def package_json(package: dict) -> str:
    return json.dumps(package, indent=2, ensure_ascii=False)
