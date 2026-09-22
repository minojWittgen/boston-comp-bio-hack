"""Source registry (v3 §4.5 tool descriptions + §6 evidence dimensions).

One entry per evidence source. Each carries:
  §4.5 tool description : purpose, eligible_inputs, output_meaning, limitations,
                          failure_behavior, version
  §6 evidence record    : evidence_role, result_origin, measured_vs_inferred,
                          species, context, modality, source_dependencies
  eval policy           : leaks_answers (benchmark-answer leakage in eval mode)

`source_dependencies` lists the canonical UPSTREAM data providers. Two sources that
share a provider are not independent replications (§1, §3). `independent_sources()`
deduplicates on these so, e.g., a direct IMPC query and Open Targets' IMPC-derived
evidence count IMPC once, not twice.

`render_tools_md()` emits `tools.md` so the coordinator can read tool contracts.
"""
from __future__ import annotations

# evidence_role is "background" for every source here: these are target-knowledge
# lookups, not measured in-vitro→in-vivo→patient comparisons (that is a teammate's
# analysis layer and the agent's job to assemble).
SOURCES: dict[str, dict] = {
    "mygene": {
        "purpose": "Normalize a human gene symbol to stable identifiers (Ensembl, Entrez).",
        "eligible_inputs": "human gene symbol",
        "output_meaning": "canonical symbol, name, Ensembl gene id(s), Entrez id; ambiguity flag",
        "limitations": "symbol synonyms can be ambiguous; not an evidence source itself",
        "failure_behavior": "not_found if no exact symbol match; error on technical failure",
        "version": "MyGene.info v3",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "n/a", "species": "human",
        "context": "identifier_normalization", "modality": "identifier",
        "source_dependencies": ["MyGene.info"], "leaks_answers": False,
    },
    "reactome_pathway": {
        "purpose": "List human genes participating in a versioned Reactome pathway.",
        "eligible_inputs": "Reactome stable id (R-HSA-...)",
        "output_meaning": "participating human genes (UniProt-backed), shared_participant flag",
        "limitations": "pathway membership only; not experimental evidence of activity",
        "failure_behavior": "not_found if no participants; error on technical failure",
        "version": "Reactome ContentService (graph DB version recorded per call)",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "n/a", "species": "human",
        "context": "pathway_definition", "modality": "pathway_membership",
        "source_dependencies": ["Reactome"], "leaks_answers": False,
    },
    "reactome_gene_pathways": {
        "purpose": "Which human Reactome pathways a gene is in, and what each does.",
        "eligible_inputs": "human gene symbol",
        "output_meaning": "pathways (stId + name + description) the gene participates in",
        "limitations": "membership + description only; not a pathway-level evidence rollup",
        "failure_behavior": "not_found if the gene maps to no human pathway; error on failure",
        "version": "Reactome ContentService (graph DB version recorded per call)",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "n/a", "species": "human",
        "context": "pathway_definition", "modality": "pathway_membership",
        "source_dependencies": ["Reactome"], "leaks_answers": False,
    },
    "reactome_orthology": {
        "purpose": "Reactome's computationally inferred mouse pathway for a human pathway.",
        "eligible_inputs": "human Reactome stable id (R-HSA-...)",
        "output_meaning": "inferred mouse pathway stId and release; labeled inferred",
        "limitations": "COMPUTATIONALLY INFERRED, not an independent cross-species experiment",
        "failure_behavior": "not_found if no inferred pathway; error on technical failure",
        "version": "Reactome ContentService (graph DB version recorded per call)",
        "evidence_role": "background", "result_origin": "computationally_inferred",
        "measured_vs_inferred": "inferred", "species": "mouse",
        "context": "pathway_definition", "modality": "pathway_membership",
        "source_dependencies": ["Reactome"], "leaks_answers": False,
    },
    "ensembl_orthology": {
        "purpose": "Species-specific orthologs for a human gene with relationship type.",
        "eligible_inputs": "human Ensembl gene id + target species",
        "output_meaning": "orthologs with one2one/one2many/many2many type and %identity",
        "limitations": "homology is not an observed cross-species replication (§4.4)",
        "failure_behavior": "not_found if no ortholog record; error on technical failure",
        "version": "Ensembl REST (Compara)",
        "evidence_role": "background", "result_origin": "computationally_inferred",
        "measured_vs_inferred": "inferred", "species": "cross_species",
        "context": "orthology", "modality": "orthology",
        "source_dependencies": ["Ensembl Compara"], "leaks_answers": False,
    },
    "impc": {
        "purpose": "Mouse knockout phenotypes; distinguishes never-phenotyped from no-hit.",
        "eligible_inputs": "mouse gene symbol (from a unique one2one ortholog)",
        "output_meaning": "phenotyped flag, tested count, phenotype hits (MP terms)",
        "limitations": "single-gene knockout phenotype; not a pathway-level expression readout",
        "failure_behavior": "not_found if never phenotyped; skipped if no unique ortholog; error on failure",
        "version": "IMPC Solr (statistical-result + genotype-phenotype cores)",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "measured", "species": "mouse",
        "context": "in_vivo", "modality": "phenotype",
        "source_dependencies": ["IMPC"], "leaks_answers": False,
    },
    "gtex": {
        "purpose": "Human bulk-RNA baseline expression across tissues.",
        "eligible_inputs": "human Ensembl gene id",
        "output_meaning": "median TPM per tissue (healthy reference, GTEx v8)",
        "limitations": "healthy reference baseline; not a disease/patient contrast",
        "failure_behavior": "not_found if gene absent; error on technical failure",
        "version": "GTEx API v2 (gtex_v8)",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "measured", "species": "human",
        "context": "human_reference", "modality": "rna",
        "source_dependencies": ["GTEx"], "leaks_answers": False,
    },
    "opentargets_association": {
        "purpose": "Target–disease association evidence aggregated by Open Targets.",
        "eligible_inputs": "human Ensembl gene id",
        "output_meaning": "top associated diseases with aggregated association scores",
        "limitations": "aggregated score, NOT a calibrated translation probability (§9)",
        "failure_behavior": "not_found if target absent; error on GraphQL/technical failure",
        "version": "Open Targets Platform GraphQL (dataVersion recorded per call)",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "aggregated", "species": "human",
        "context": "target_disease_association", "modality": "aggregated_association",
        # aggregates many upstreams; overlaps direct IMPC / GTEx (§9) -> dedup handles it
        "source_dependencies": ["Open Targets", "IMPC", "Expression Atlas", "GTEx",
                                "GWAS/genetics"],
        "leaks_answers": True,  # disease association leaks benchmark answers in eval
    },
    "hpa_rna": {
        "purpose": "Human Protein Atlas cell-line RNA expression (in vitro).",
        "eligible_inputs": "human Ensembl gene id",
        "output_meaning": "cell-line RNA distribution and cell-line-specific nTPM",
        "limitations": "search API returns summary; per-cell-line nTPM vectors need the bulk TSV",
        "failure_behavior": "not_found if gene absent; error on technical failure",
        "version": "HPA search-api",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "measured", "species": "human",
        "context": "in_vitro", "modality": "rna",
        "source_dependencies": ["Human Protein Atlas"], "leaks_answers": False,
    },
    "hpa_protein": {
        "purpose": "Human Protein Atlas cell-line protein evidence (in vitro).",
        "eligible_inputs": "human Ensembl gene id",
        "output_meaning": "subcellular location and protein class (immunofluorescence)",
        "limitations": "localization/class, not a quantitative protein abundance matrix",
        "failure_behavior": "not_found if gene absent; error on technical failure",
        "version": "HPA search-api",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "measured", "species": "human",
        "context": "in_vitro", "modality": "protein",
        "source_dependencies": ["Human Protein Atlas"], "leaks_answers": False,
    },
    "opentargets_depmap": {
        "purpose": "DepMap CRISPR fitness essentiality across cancer cell lines (in vitro).",
        "eligible_inputs": "human Ensembl gene id",
        "output_meaning": "isEssential flag and per-tissue DepMap screen gene-effect scores",
        "limitations": "fitness dependency, not pathway expression",
        "failure_behavior": "not_found if no essentiality record; error on technical failure",
        "version": "Open Targets Platform GraphQL (DepMap)",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "measured", "species": "human",
        "context": "in_vitro", "modality": "crispr_fitness",
        "source_dependencies": ["DepMap", "Open Targets"],
        "leaks_answers": False,  # fitness, not disease association -> allowed in eval
    },
    "pubmed": {
        "purpose": "Literature hit count for a gene (optionally AND a disease term).",
        "eligible_inputs": "gene symbol + optional disease term",
        "output_meaning": "publication count and PMIDs",
        "limitations": "citation volume, not evidence of a specific measurement",
        "failure_behavior": "not_found if zero hits; error on technical failure",
        "version": "NCBI E-utilities (esearch)",
        "evidence_role": "background", "result_origin": "published_retrieved",
        "measured_vs_inferred": "n/a", "species": "human",
        "context": "literature", "modality": "literature",
        "source_dependencies": ["literature"], "leaks_answers": True,
    },
}


# ------------------------------------------------------------------ evidence dimensions
_DIMENSION_KEYS = ("evidence_role", "result_origin", "measured_vs_inferred",
                   "species", "context", "modality", "source_dependencies")


def evidence_dimensions(source: str) -> dict:
    """The v3 §6 evidence-record fields for a source (empty dict if unknown)."""
    e = SOURCES.get(source, {})
    return {k: e[k] for k in _DIMENSION_KEYS if k in e}


def annotate(source: str, result: dict) -> dict:
    """Attach §6 evidence-record fields to a SourceResult (non-mutating copy)."""
    return {**result, "evidence": evidence_dimensions(source)}


# ------------------------------------------------------------------ independence (§1/§3)
def independent_sources(source_ids: list[str]) -> dict:
    """Deduplicate on upstream providers so shared data is not counted twice.

    Returns the unique provider set and which sources map to each — e.g. a direct
    IMPC query and Open Targets both list 'IMPC', so IMPC is one independent provider.
    """
    providers: dict[str, list[str]] = {}
    for sid in source_ids:
        for dep in SOURCES.get(sid, {}).get("source_dependencies", []):
            providers.setdefault(dep, []).append(sid)
    return {"n_independent": len(providers), "providers": providers}


# ------------------------------------------------------------------ eval policy (§5, §9)
def eval_allows(source: str) -> bool:
    """True if a source may run in eval mode (does not leak benchmark answers).

    Open Targets *association* leaks (disease link); baseline expression and DepMap
    fitness do not — they are registered as separate sources with leaks_answers=False.
    """
    return not SOURCES.get(source, {}).get("leaks_answers", False)


# ------------------------------------------------------------------ tools.md generator
def render_tools_md() -> str:
    """Render the registry as a coordinator-readable tool manifest (§4.5)."""
    lines = ["# Tool manifest",
             "",
             "Auto-generated from `registry.py` (v3 §4.5). One row per evidence source: "
             "its contract and the evidence dimensions (§6) its output carries.",
             ""]
    for sid, e in SOURCES.items():
        lines += [
            f"## {sid}",
            "",
            f"- **Purpose**: {e['purpose']}",
            f"- **Eligible inputs**: {e['eligible_inputs']}",
            f"- **Output meaning**: {e['output_meaning']}",
            f"- **Limitations**: {e['limitations']}",
            f"- **Failure behavior**: {e['failure_behavior']}",
            f"- **Version**: {e['version']}",
            f"- **Evidence** — role: {e['evidence_role']}; origin: {e['result_origin']}; "
            f"measured/inferred: {e['measured_vs_inferred']}; species: {e['species']}; "
            f"context: {e['context']}; modality: {e['modality']}",
            f"- **Source dependencies**: {', '.join(e['source_dependencies'])}",
            f"- **Eval**: {'skipped (leaks answers)' if e['leaks_answers'] else 'allowed'}",
            "",
        ]
    return "\n".join(lines)
