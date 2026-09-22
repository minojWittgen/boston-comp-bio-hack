# Research request

**Question.** An in-vitro experiment (study A) reports that TYK2 mRNA is higher in IL-23-stimulated primary
human keratinocytes than in vehicle-treated controls. Using only the material in `corpus/`, assess whether
this directional finding is supported in the supplied animal evidence (study B) and patient evidence (study C).

Specifically:
1. **in_vitro_vs_animal** — does the corresponding measurement in the animal study agree in direction under a
   scientifically valid comparison? State the basis for comparability (species, tissue, contrast, endpoint) or
   explain why it cannot be established.
2. **in_vitro_vs_patient_rna** — does patient lesional vs non-lesional skin RNA agree in direction?
3. **patient_rna_vs_patient_protein_within_person** — is the patient RNA change accompanied by a protein change
   *within the same participants*? Distinguish within-person corroboration from population-level agreement between
   independent groups. Preserve any missingness in specimen/participant/visit metadata rather than assuming it.

For each comparison give `supported`, `opposed`, or `insufficient_evidence`, a short justification, and citations
to the exact source locations (file + line / row / JSON path). Reference resources in `corpus/api/` (gene
identity, orthology, tissue reference abundance, knockout phenotypes) are background: use them for identity and
species mapping, not as disease-contrast evidence. List limitations and anything that remains unresolved.

Deliver a short report in the envelope described by `schema/report.schema.json` via `submit_report`.
