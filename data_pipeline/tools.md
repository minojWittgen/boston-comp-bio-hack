# Tool manifest

Auto-generated from `registry.py` (v3 §4.5). One row per evidence source: its contract and the evidence dimensions (§6) its output carries.

## mygene

- **Purpose**: Normalize a human gene symbol to stable identifiers (Ensembl, Entrez).
- **Eligible inputs**: human gene symbol
- **Output meaning**: canonical symbol, name, Ensembl gene id(s), Entrez id; ambiguity flag
- **Limitations**: symbol synonyms can be ambiguous; not an evidence source itself
- **Failure behavior**: not_found if no exact symbol match; error on technical failure
- **Version**: MyGene.info v3
- **Evidence** — role: background; origin: published_retrieved; measured/inferred: n/a; species: human; context: identifier_normalization; modality: identifier
- **Source dependencies**: MyGene.info
- **Eval**: allowed

## reactome_pathway

- **Purpose**: List human genes participating in a versioned Reactome pathway.
- **Eligible inputs**: Reactome stable id (R-HSA-...)
- **Output meaning**: participating human genes (UniProt-backed), shared_participant flag
- **Limitations**: pathway membership only; not experimental evidence of activity
- **Failure behavior**: not_found if no participants; error on technical failure
- **Version**: Reactome ContentService (graph DB version recorded per call)
- **Evidence** — role: background; origin: published_retrieved; measured/inferred: n/a; species: human; context: pathway_definition; modality: pathway_membership
- **Source dependencies**: Reactome
- **Eval**: allowed

## reactome_orthology

- **Purpose**: Reactome's computationally inferred mouse pathway for a human pathway.
- **Eligible inputs**: human Reactome stable id (R-HSA-...)
- **Output meaning**: inferred mouse pathway stId and release; labeled inferred
- **Limitations**: COMPUTATIONALLY INFERRED, not an independent cross-species experiment
- **Failure behavior**: not_found if no inferred pathway; error on technical failure
- **Version**: Reactome ContentService (graph DB version recorded per call)
- **Evidence** — role: background; origin: computationally_inferred; measured/inferred: inferred; species: mouse; context: pathway_definition; modality: pathway_membership
- **Source dependencies**: Reactome
- **Eval**: allowed

## ensembl_orthology

- **Purpose**: Species-specific orthologs for a human gene with relationship type.
- **Eligible inputs**: human Ensembl gene id + target species
- **Output meaning**: orthologs with one2one/one2many/many2many type and %identity
- **Limitations**: homology is not an observed cross-species replication (§4.4)
- **Failure behavior**: not_found if no ortholog record; error on technical failure
- **Version**: Ensembl REST (Compara)
- **Evidence** — role: background; origin: computationally_inferred; measured/inferred: inferred; species: cross_species; context: orthology; modality: orthology
- **Source dependencies**: Ensembl Compara
- **Eval**: allowed

## impc

- **Purpose**: Mouse knockout phenotypes; distinguishes never-phenotyped from no-hit.
- **Eligible inputs**: mouse gene symbol (from a unique one2one ortholog)
- **Output meaning**: phenotyped flag, tested count, phenotype hits (MP terms)
- **Limitations**: single-gene knockout phenotype; not a pathway-level expression readout
- **Failure behavior**: not_found if never phenotyped; skipped if no unique ortholog; error on failure
- **Version**: IMPC Solr (statistical-result + genotype-phenotype cores)
- **Evidence** — role: background; origin: published_retrieved; measured/inferred: measured; species: mouse; context: in_vivo; modality: phenotype
- **Source dependencies**: IMPC
- **Eval**: allowed

## gtex

- **Purpose**: Human bulk-RNA baseline expression across tissues.
- **Eligible inputs**: human Ensembl gene id
- **Output meaning**: median TPM per tissue (healthy reference, GTEx v8)
- **Limitations**: healthy reference baseline; not a disease/patient contrast
- **Failure behavior**: not_found if gene absent; error on technical failure
- **Version**: GTEx API v2 (gtex_v8)
- **Evidence** — role: background; origin: published_retrieved; measured/inferred: measured; species: human; context: human_reference; modality: rna
- **Source dependencies**: GTEx
- **Eval**: allowed

## opentargets_association

- **Purpose**: Target–disease association evidence aggregated by Open Targets.
- **Eligible inputs**: human Ensembl gene id
- **Output meaning**: top associated diseases with aggregated association scores
- **Limitations**: aggregated score, NOT a calibrated translation probability (§9)
- **Failure behavior**: not_found if target absent; error on GraphQL/technical failure
- **Version**: Open Targets Platform GraphQL (dataVersion recorded per call)
- **Evidence** — role: background; origin: published_retrieved; measured/inferred: aggregated; species: human; context: target_disease_association; modality: aggregated_association
- **Source dependencies**: Open Targets, IMPC, Expression Atlas, GTEx, GWAS/genetics
- **Eval**: skipped (leaks answers)

## hpa_rna

- **Purpose**: Human Protein Atlas cell-line RNA expression (in vitro).
- **Eligible inputs**: human Ensembl gene id
- **Output meaning**: cell-line RNA distribution and cell-line-specific nTPM
- **Limitations**: search API returns summary; per-cell-line nTPM vectors need the bulk TSV
- **Failure behavior**: not_found if gene absent; error on technical failure
- **Version**: HPA search-api
- **Evidence** — role: background; origin: published_retrieved; measured/inferred: measured; species: human; context: in_vitro; modality: rna
- **Source dependencies**: Human Protein Atlas
- **Eval**: allowed

## hpa_protein

- **Purpose**: Human Protein Atlas cell-line protein evidence (in vitro).
- **Eligible inputs**: human Ensembl gene id
- **Output meaning**: subcellular location and protein class (immunofluorescence)
- **Limitations**: localization/class, not a quantitative protein abundance matrix
- **Failure behavior**: not_found if gene absent; error on technical failure
- **Version**: HPA search-api
- **Evidence** — role: background; origin: published_retrieved; measured/inferred: measured; species: human; context: in_vitro; modality: protein
- **Source dependencies**: Human Protein Atlas
- **Eval**: allowed

## opentargets_depmap

- **Purpose**: DepMap CRISPR fitness essentiality across cancer cell lines (in vitro).
- **Eligible inputs**: human Ensembl gene id
- **Output meaning**: isEssential flag and per-tissue DepMap screen gene-effect scores
- **Limitations**: fitness dependency, not pathway expression
- **Failure behavior**: not_found if no essentiality record; error on technical failure
- **Version**: Open Targets Platform GraphQL (DepMap)
- **Evidence** — role: background; origin: published_retrieved; measured/inferred: measured; species: human; context: in_vitro; modality: crispr_fitness
- **Source dependencies**: DepMap, Open Targets
- **Eval**: allowed

## pubmed

- **Purpose**: Literature hit count for a gene (optionally AND a disease term).
- **Eligible inputs**: gene symbol + optional disease term
- **Output meaning**: publication count and PMIDs
- **Limitations**: citation volume, not evidence of a specific measurement
- **Failure behavior**: not_found if zero hits; error on technical failure
- **Version**: NCBI E-utilities (esearch)
- **Evidence** — role: background; origin: published_retrieved; measured/inferred: n/a; species: human; context: literature; modality: literature
- **Source dependencies**: literature
- **Eval**: skipped (leaks answers)
