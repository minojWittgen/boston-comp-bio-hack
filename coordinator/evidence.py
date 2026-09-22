"""Read pipeline packages and preserve their limited, background-only meaning.

The pipeline's Modal function returns a receipt, not the evidence itself. Providers
resolve that receipt; adaptation never treats retrieval success as validation.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import suppress
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Protocol

from .models import EvidenceBundle, EvidenceRecord, Gap


class EvidenceProvider(Protocol):
    def fetch(self, symbol: str, disease: str, mode: str, run_id: str) -> dict: ...


def _validate_request(symbol: str, disease: str, mode: str, run_id: str) -> None:
    for name, value in (("symbol", symbol), ("run_id", run_id)):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
            raise ValueError(f"{name} must be a safe single path component")
    if not isinstance(disease, str) or not isinstance(mode, str) or mode not in {"explore", "eval"}:
        raise ValueError("disease must be text and mode must be explore or eval")


def _check_package_request(package: Any, symbol: str, disease: str, mode: str,
                           run_id: str | None = None) -> dict:
    if not isinstance(package, dict):
        raise ValueError("Evidence package must be a JSON object, not a receipt")
    run, gene = package.get("run"), package.get("gene")
    if not isinstance(run, dict) or not isinstance(gene, dict) or not isinstance(package.get("sources"), dict):
        raise ValueError("Evidence package requires run, gene, and sources objects")
    query = gene.get("query")
    if not isinstance(query, dict) or query.get("symbol") != symbol:
        raise ValueError("Evidence package gene does not match requested symbol")
    if run.get("mode") != mode or run.get("disease_query") != disease:
        raise ValueError("Evidence package mode or disease does not match request")
    if run_id is not None and run.get("run_id") != run_id:
        raise ValueError("Evidence package run_id does not match requested run")
    return package


class DirectoryEvidenceProvider:
    """Replay <symbol>.json fixtures without rewriting their original provenance."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def fetch(self, symbol: str, disease: str, mode: str, run_id: str) -> dict:
        _validate_request(symbol, disease, mode, run_id)
        path = (self.root / f"{symbol}.json").resolve()
        if path.parent != self.root:
            raise ValueError("Fixture must remain inside its configured directory")
        package = json.loads(path.read_text(encoding="utf-8"))
        # A replay has its own original run ID, but must match the biological query.
        return _check_package_request(package, symbol, disease, mode)


class ModalEvidenceProvider:
    """Call the existing deployment and read its committed package from the volume.

    Modal is imported only when used. Optional handles allow testing without an
    account or network. Volume.read_file yields bytes and uses volume-relative paths.
    """

    def __init__(self, *, function: Any = None, volume: Any = None,
                 timeout_seconds: float = 120):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self.function = function
        self.volume = volume
        self.timeout_seconds = timeout_seconds

    def fetch(self, symbol: str, disease: str, mode: str, run_id: str) -> dict:
        _validate_request(symbol, disease, mode, run_id)
        if self.function is None or self.volume is None:
            import modal

            if self.function is None:
                self.function = modal.Function.from_name("xctx-evidence", "build_one")
            if self.volume is None:
                self.volume = modal.Volume.from_name("xctx-cache", create_if_missing=False)
        call = self.function.spawn(symbol, disease, mode, run_id)
        try:
            receipt = call.get(timeout=self.timeout_seconds)
        except TimeoutError:
            # Cancel this input, not shared containers, and preserve the timeout.
            with suppress(Exception):
                call.cancel()
            raise
        expected = f"/data/runs/{run_id}/{symbol}.json"
        if not isinstance(receipt, dict) or receipt.get("symbol") != symbol or receipt.get("path") != expected:
            raise ValueError("Receipt must identify the exact requested run and gene path")
        # Construct this path from validated inputs; never pass a receipt path through.
        content = b"".join(self.volume.read_file(f"runs/{run_id}/{symbol}.json"))
        package = json.loads(content)
        return _check_package_request(package, symbol, disease, mode, run_id)


_SPECIES = {
    "mus_musculus": "mus_musculus",
    "rattus_norvegicus": "rattus_norvegicus",
    "macaca_mulatta": "macaca_mulatta",
}
_SOURCES = ("ensembl_orthology", "gtex", "impc", "opentargets", "pubmed")
# Optional background sources: interpreted when present, but not required (no gap if absent).
_OPTIONAL_SOURCES = frozenset({"hpa_cell_lines", "opentargets_depmap", "hpa_pathology"})
_LIMITS = {
    "mygene": "Identifier normalization is not an experimental observation.",
    "ensembl_orthology": "Sequence orthology does not measure expression or conserved pathway activity.",
    "gtex": "Healthy reference tissue medians; no donor-level or disease-contrast expression is supplied.",
    "impc": "Descriptive mouse knockout phenotypes; no transcriptomic program, treatment efficacy, or patient data.",
    "opentargets": "Gene-level association scores; not source-level evidence, disease-filtered results, or causal proof.",
    "pubmed": "Search counts and identifiers only; article contents and experimental evidence were not retrieved.",
    "hpa_cell_lines": "Cell-line RNA/protein summaries; in-vitro background, not per-replicate variation.",
    "opentargets_depmap": "CRISPR fitness dependency across cancer cell lines; not pathway expression.",
    "hpa_pathology": "Cohort-level cancer/disease background (TCGA-derived); no per-patient variation or matched measurements.",
}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _gap(bundle: EvidenceBundle, code: str, detail: str, source: str | None = None,
         gene: str | None = None, retryable: bool = False) -> None:
    bundle.gaps.append(Gap(code=code, detail=detail, source=source, gene=gene, retryable=retryable))


def _source_ok(bundle: EvidenceBundle, value: Any, source: str, gene: str,
               subkey: str | None = None) -> bool:
    label = f"{source}/{subkey}" if subkey else source
    if not isinstance(value, dict) or value.get("source") != source:
        _gap(bundle, "malformed_source", f"{label}: expected a matching SourceResult object", source, gene)
        return False
    status = value.get("status")
    if isinstance(status, str) and status in {"not_found", "error", "skipped"}:
        meanings = {"not_found": "No database record; not a biological negative",
                    "error": "Technical retrieval failure", "skipped": "Source was not queried"}
        reason = _text(value.get("error"))
        detail = f"{label}: {meanings[status]}" + (f" ({reason})" if reason else "")
        _gap(bundle, f"source_{status}", detail, source, gene, retryable=status == "error")
        return False
    if status != "ok" or not isinstance(value.get("data"), dict) or not isinstance(value.get("query"), dict):
        _gap(bundle, "malformed_source", f"{label}: invalid status, data, or query", source, gene)
        return False
    return True


def _record(entity: str, source: str, value: dict, run: dict,
            subkey: str | None = None) -> EvidenceRecord:
    # Operational metadata must not change the identity of identical evidence.
    identity = {"gene": entity, "source": source, "subkey": subkey,
                "query": value["query"], "data": value["data"],
                "source_version": value.get("source_version")}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True,
                                       allow_nan=False).encode()).hexdigest()[:24]
    metadata: dict[str, Any] = {}
    if source == "mygene":
        metadata = {"species": "homo_sapiens", "context": "reference", "endpoint": "gene_identifier"}
    elif source == "ensembl_orthology":
        metadata = {"species": _SPECIES.get(subkey), "context": "reference", "endpoint": "orthology"}
    elif source == "gtex":
        metadata = {"species": "homo_sapiens", "context": "reference", "modality": "RNA",
                    "endpoint": "tissue_median_expression", "unit": "TPM",
                    "normalization_basis": "GTEx tissue median TPM"}
    elif source == "impc":
        metadata = {"species": "mus_musculus", "context": "in_vivo", "modality": "phenotype",
                    "endpoint": "knockout_phenotype"}
    elif source == "opentargets":
        metadata = {"species": "homo_sapiens", "context": "reference", "endpoint": "target_disease_association"}
    elif source == "pubmed":
        metadata = {"endpoint": "literature_search"}
    elif source == "hpa_cell_lines":
        # neutral in-vitro background; do not name RNA when only protein localization is present
        metadata = {"species": "homo_sapiens", "context": "in_vitro",
                    "endpoint": "cell_line_background"}
    elif source == "opentargets_depmap":
        metadata = {"species": "homo_sapiens", "context": "in_vitro",
                    "endpoint": "crispr_fitness_essentiality"}
    elif source == "hpa_pathology":
        # cohort disease background; only label RNA when cancer RNA fields are present
        pdata = value.get("data") if isinstance(value.get("data"), dict) else {}
        metadata = {"species": "homo_sapiens", "context": "patient",
                    "endpoint": "cancer_cohort_background"}
        if pdata.get("has_cancer_rna"):
            metadata["modality"] = "RNA"
    explicit = value.get("provenance", [])
    provenance = [p for p in explicit if _text(p)] if isinstance(explicit, list) else []
    return EvidenceRecord(
        id=f"evidence-{digest}", source=source, entity=entity, level="background",
        source_version=_text(value.get("source_version")),
        retrieved_at=_text(value.get("retrieved_at")), provenance=provenance,
        payload={"source_result": deepcopy(value), "run": deepcopy(run), "subkey": subkey,
                 "limitation": _LIMITS.get(source, "Unrecognised source; retained as background only.")},
        **metadata,
    )


def _note_truncation(bundle: EvidenceBundle, source: str, value: dict, gene: str) -> None:
    data = value["data"]
    if source == "opentargets":
        associations = data.get("associatedDiseases")
        total = associations.get("count") if isinstance(associations, dict) else None
        rows = associations.get("rows") if isinstance(associations, dict) else None
    elif source == "pubmed":
        total, rows = data.get("count"), data.get("pmids")
    else:
        total, rows = None, None
    if isinstance(total, int) and isinstance(rows, list) and total > len(rows):
        _gap(bundle, "source_truncated", f"{source}: returned {len(rows)} of {total} records; absence from the list is not absence of evidence", source, gene)
    if source == "impc" and isinstance(data.get("hits"), list) and len(data["hits"]) >= 500:
        _gap(bundle, "source_may_be_truncated", "IMPC returned the 500-row limit; phenotype hit coverage may be incomplete", source, gene)


def _adapt_pathway_package(package: dict, bundle: EvidenceBundle, seen: set[str], index: int) -> None:
    """Adapt a pathway package (schema 0.1-pathway) as BACKGROUND.

    Preserves the pathway id and coverage summary; never promotes membership/coverage
    counts to measured pathway activity. This handles the pipeline's pathway builder
    output so it is not rejected as malformed. The full multi-pathway request/collection
    route remains a separate coordinator integration.
    """
    pathway = package.get("pathway") if isinstance(package.get("pathway"), dict) else None
    summary = package.get("summary") if isinstance(package.get("summary"), dict) else None
    run = package.get("run") if isinstance(package.get("run"), dict) else {}
    if pathway is None or summary is None:
        _gap(bundle, "malformed_package", f"Package {index}: pathway package missing a pathway or summary object")
        return
    pdata = pathway.get("data") if isinstance(pathway.get("data"), dict) else {}
    reactome_id = _text(pdata.get("reactome_id")) or _text(run.get("reactome_id"))
    if not reactome_id:
        _gap(bundle, "malformed_package", f"Package {index}: pathway package missing a reactome_id")
        return
    # Propagate the pathway resolution failure as a structured gap instead of masking it
    # as background. Technical errors stay retryable; do not emit a membership record.
    status = pathway.get("status")
    if status != "ok":
        meanings = {"not_found": "no pathway record", "error": "technical retrieval failure",
                    "skipped": "pathway not resolved"}
        code = f"pathway_{status}" if status in ("not_found", "error", "skipped") else "malformed_source"
        _gap(bundle, code, f"{reactome_id}: pathway resolution {meanings.get(status, status)}",
             "reactome_pathway", reactome_id, retryable=status == "error")
        return
    # Propagate mouse-inference and member-source failures so they are not lost.
    mouse = package.get("mouse_inference") if isinstance(package.get("mouse_inference"), dict) else {}
    if mouse.get("status") not in (None, "ok"):
        _gap(bundle, f"pathway_mouse_inference_{mouse.get('status')}",
             f"{reactome_id}: mouse pathway inference {mouse.get('status')}",
             "reactome_orthology", reactome_id, retryable=mouse.get("status") == "error")
    for miss in (package.get("missing") or []):
        if isinstance(miss, dict) and miss.get("status") in ("error", "not_found", "skipped", "partial"):
            _gap(bundle, f"pathway_member_{miss.get('status')}",
                 f"{reactome_id}/{miss.get('source')}: {miss.get('status')} ({miss.get('reason')})",
                 str(miss.get("source")), reactome_id, retryable=miss.get("status") == "error")
    # Identity: versioned membership + source version distinguish distinct evidence with
    # equal coverage counts; timestamps are excluded so identical evidence deduplicates.
    members = sorted(
        [(g.get("symbol"), g.get("shared_participant")) for g in (pdata.get("genes") or [])
         if isinstance(g, dict)], key=lambda x: str(x[0]))
    identity = {"pathway": reactome_id, "source_version": pathway.get("source_version"),
                "members": members, "summary": summary}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True,
                                       allow_nan=False, default=str).encode()).hexdigest()[:24]
    record = EvidenceRecord(
        id=f"pathway-{digest}", source="reactome_pathway", entity=reactome_id, level="background",
        context="reference", endpoint="pathway_membership_and_coverage",
        source_version=_text(pathway.get("source_version")),
        retrieved_at=_text(pathway.get("retrieved_at")),
        payload={"pathway_package": deepcopy(package),
                 "limitation": "Pathway membership and per-gene coverage counts; "
                               "not measured pathway activity or a completed comparison."})
    if record.id not in seen:
        seen.add(record.id)
        bundle.records.append(record)
    _gap(bundle, "pathway_background_only",
         f"{reactome_id}: pathway membership/coverage is background, not measured pathway "
         f"activity; a pathway-vs-pathway comparison still needs its own observations",
         "reactome_pathway", reactome_id)


def adapt_packages(packages: list[dict]) -> EvidenceBundle:
    """Adapt schema 0.1 packages without inventing studies, subjects, or observations.

    Invalid packages/sources become non-retryable contract gaps. Only a source's
    explicit ``error`` status is retryable. Identical background records deduplicate.
    """
    bundle = EvidenceBundle(package_count=len(packages))
    seen: set[str] = set()
    for index, package in enumerate(packages):
        if isinstance(package, dict):
            try:
                # Preserve source failures and malformed envelopes for audit too.
                # Reject NaN/Infinity rather than writing non-standard JSON artifacts.
                json.dumps(package, allow_nan=False)
            except (TypeError, ValueError, OverflowError, RecursionError):
                _gap(bundle, "malformed_package", f"Package {index}: content is not valid finite JSON")
                continue
            bundle.raw_packages.append(deepcopy(package))
        if isinstance(package, dict) and package.get("schema_version") == "0.1-pathway":
            _adapt_pathway_package(package, bundle, seen, index)
            continue
        if not isinstance(package, dict) or not all(isinstance(package.get(k), dict) for k in ("gene", "run", "sources")):
            _gap(bundle, "malformed_package", f"Package {index}: expected gene, run and sources objects; receipts are not packages")
            continue
        gene, run, sources = package["gene"], package["run"], package["sources"]
        data = gene.get("data") if isinstance(gene.get("data"), dict) else {}
        query = gene.get("query") if isinstance(gene.get("query"), dict) else {}
        entity = _text(data.get("symbol")) or _text(query.get("symbol"))
        if not entity or package.get("schema_version") != "0.1":
            _gap(bundle, "malformed_package", f"Package {index}: missing gene identity or unsupported schema_version", gene=entity)
            continue
        gene_ok = _source_ok(bundle, gene, "mygene", entity)
        if gene_ok and data.get("ambiguous") is not False:
            _gap(bundle, "ambiguous_gene", "Gene normalization is ambiguous or its ambiguity flag is missing; identity needs review", "mygene", entity)
        if gene_ok and not _text(data.get("ensembl_primary")):
            _gap(bundle, "gene_unresolved", "Gene normalization has no primary Ensembl identifier", "mygene", entity)

        entries: list[tuple[str, str | None, Any]] = [("mygene", None, gene)] if gene_ok else []
        for source in _SOURCES:
            if source not in sources:
                _gap(bundle, "source_missing", f"{source}: no SourceResult supplied", source, entity)
                continue
            if source == "ensembl_orthology":
                orthology = sources[source]
                if not isinstance(orthology, dict):
                    _gap(bundle, "malformed_source", "Orthology must be keyed by target species", source, entity)
                    continue
                for species in _SPECIES:
                    if species not in orthology:
                        _gap(bundle, "source_missing", f"ensembl_orthology/{species}: no SourceResult supplied", source, entity)
                entries.extend((source, species, result) for species, result in orthology.items())
            else:
                entries.append((source, None, sources[source]))
        for source in sources.keys() - set(_SOURCES):
            if source not in _OPTIONAL_SOURCES:
                _gap(bundle, "unsupported_source", f"{source}: no scientific interpretation is defined", str(source), entity)
            entries.append((source, None, sources[source]))
        for source, subkey, value in entries:
            if not _source_ok(bundle, value, source, entity, subkey):
                continue
            try:
                record = _record(entity, source, value, run, subkey)
            except (TypeError, ValueError):
                _gap(bundle, "malformed_source", f"{source}: payload is not valid JSON or record metadata", str(source), entity)
                continue
            if record.id not in seen:
                seen.add(record.id)
                bundle.records.append(record)
            _note_truncation(bundle, source, value, entity)
    return bundle
