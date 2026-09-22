#!/usr/bin/env python3
"""PRIMARY suite generator: same research request + same SOURCE corpus for every system.

  python bench/gen_primary.py [--limits dev|final]

Each case is a small frozen corpus of source-native material (methods excerpts, DE result tables,
specimen metadata, native API responses). NO extraction, normalization or interpretation is
supplied: each system does its own. Everything is synthetic and labelled as such in
corpus/PROVENANCE.json; it is an engineering probe, not biological evidence.

Cases (updated review):
  xctx-p00  development example (never graded)
  xctx-p01  scoped agreement            — in vitro, mouse IMQ and patient evidence all support TYK2 up
  xctx-p02  animal-context disagreement — mouse IMQ skin shows Tyk2 DOWN under a valid comparison; patient support retained
  xctx-p03  invalid within-person match — protein specimens come from different participants (same cohort summary)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, dump, load  # noqa: E402

SPEC = load(Path(__file__).with_name("spec.json"))
PRIMARY = ROOT / "primary"
GENES_H = ["TYK2", "JAK1", "STAT3", "IL17A", "IL23R", "KRT16", "S100A8", "GAPDH", "ACTB", "IFNG"]
GENES_M = ["Tyk2", "Jak1", "Stat3", "Il17a", "Il23r", "Krt16", "S100a8", "Gapdh", "Actb", "Ifng"]

TASK = """# Research request

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
"""


def csv_text(rows, header):
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=header, lineterminator="\n"); w.writeheader(); w.writerows(rows); return buf.getvalue()


def de_table(rng, genes, target, target_l2fc, target_padj):
    rows = []
    for g in genes:
        if g == target:
            l2, p = target_l2fc, target_padj
        else:
            l2 = round(rng.gauss(0, 0.5), 3); p = round(min(1.0, abs(rng.gauss(0.3, 0.3))), 4)
        rows.append({"gene": g, "baseMean": round(rng.uniform(50, 3000), 1), "log2FoldChange": l2, "lfcSE": round(rng.uniform(0.1, 0.3), 3),
                     "pvalue": p / 10 if p < 1 else p, "padj": p})
    return rows


def write_case(cid, *, mouse_l2fc, protein_participants, prot_prefix, limits, note=None):
    rng = random.Random(cid); c = PRIMARY / "cases" / cid; corpus = c / "corpus"
    files = []
    def put(rel, text):
        p = corpus / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); files.append(rel)

    iv = SPEC["invitro"]
    put("study_A_invitro/methods.md", f"""# Study A — methods excerpt (synthetic)

Primary human epidermal keratinocytes ({iv['model']}) were stimulated with {iv['perturbation']} or {iv['reference']}.
Total RNA was profiled by bulk RNA-seq ({iv['n_case']} stimulated, {iv['n_reference']} vehicle wells). Differential
expression was computed with DESeq2 for the contrast **IL-23 vs vehicle**; results are in `de_results.csv`
(log2FoldChange > 0 means higher in IL-23). Endpoint: mRNA abundance.
""")
    put("study_A_invitro/de_results.csv", csv_text(de_table(rng, GENES_H, "TYK2", iv["log2fc"], iv["padj"]), ["gene", "baseMean", "log2FoldChange", "lfcSE", "pvalue", "padj"]))

    v = SPEC["invivo"]
    put("study_B_mouse_imq/methods.md", f"""# Study B — methods excerpt (synthetic)

Species: *Mus musculus*, C57BL/6J, female, 8–10 weeks. Psoriasiform inflammation was induced with topical
imiquimod (5% cream, 62.5 mg/day, 6 days) on shaved dorsal skin; controls received vehicle cream. On day 6,
full-thickness dorsal skin was collected ({v['n_case']} IMQ, {v['n_reference']} vehicle; see `animals.csv`) and
profiled by bulk RNA-seq. DESeq2 contrast: **IMQ vs vehicle** (log2FoldChange > 0 = higher in IMQ).
Endpoint: mRNA abundance. Gene symbols are mouse (MGI) symbols.
""")
    put("study_B_mouse_imq/de_results.csv", csv_text(de_table(rng, GENES_M, "Tyk2", mouse_l2fc, v["padj"]), ["gene", "baseMean", "log2FoldChange", "lfcSE", "pvalue", "padj"]))
    put("study_B_mouse_imq/animals.csv", csv_text([{"animal_id": f"M{i:02d}", "group": "IMQ" if i <= 6 else "vehicle", "sex": "F", "tissue": "dorsal skin, full thickness", "day": 6} for i in range(1, 13)],
                                                  ["animal_id", "group", "sex", "tissue", "day"]))

    P = [f"P{i:02d}" for i in range(1, 13)]
    cs = SPEC["cohort_summary"]
    put("study_C_patient_cohort/methods.md", f"""# Study C — methods excerpt (synthetic)

Adults with plaque psoriasis (n = {cs['n_participants']}; mean age {cs['age_mean']}; {int(cs['sex_ratio_f']*100)}% female; site {cs['site']}).
At the baseline visit, paired 4 mm punch biopsies were taken from a lesional plaque and from non-lesional skin.
RNA: bulk RNA-seq, values reported as log2 CPM per specimen in `rna_log2cpm.csv`.
Protein: Olink Explore panel, NPX (log2 scale) per specimen in `protein_npx.csv`.
Specimen-to-participant mapping, visit and biopsy site are in `specimens.csv`. **Participant identity must be
taken from `specimens.csv`; specimen ids are not participant ids.**
""")
    spec_rows, rna_rows, prot_rows = [], [], []
    for pid in P:
        base = rng.uniform(4, 6); d = SPEC["patient_rna"]["log2fc"] + rng.gauss(0, 0.15)
        for arm, val in (("nonlesional", base), ("lesional", base + d)):
            sid = f"S-{pid}-{'L' if arm == 'lesional' else 'NL'}-rna"
            spec_rows.append({"specimen_id": sid, "participant_id": pid, "visit": "baseline", "site_type": arm, "assay": "rna"})
            for g in GENES_H:
                rna_rows.append({"specimen_id": sid, "gene": g, "log2cpm": round(val if g == "TYK2" else rng.uniform(2, 9), 3)})
    for pid in protein_participants:
        base = rng.uniform(3, 5); d = SPEC["patient_prot"]["log2fc"] + rng.gauss(0, 0.15)
        for arm, val in (("nonlesional", base), ("lesional", base + d)):
            sid = f"{prot_prefix}-{pid}-{'L' if arm == 'lesional' else 'NL'}-prot"
            spec_rows.append({"specimen_id": sid, "participant_id": pid, "visit": "baseline", "site_type": arm, "assay": "protein"})
            for g in ("TYK2", "IL17A", "S100A8", "IFNG"):
                prot_rows.append({"specimen_id": sid, "assay_target": g, "npx": round(val if g == "TYK2" else rng.uniform(1, 6), 3)})
    put("study_C_patient_cohort/specimens.csv", csv_text(spec_rows, ["specimen_id", "participant_id", "visit", "site_type", "assay"]))
    put("study_C_patient_cohort/rna_log2cpm.csv", csv_text(rna_rows, ["specimen_id", "gene", "log2cpm"]))
    put("study_C_patient_cohort/protein_npx.csv", csv_text(prot_rows, ["specimen_id", "assay_target", "npx"]))

    # native-shaped API responses (background)
    ensg = SPEC["ensg"]
    put("api/mygene_query_TYK2.json", json.dumps({"took": 3, "total": 1, "max_score": 90.1, "hits": [{"_id": "7297", "_score": 90.1, "symbol": "TYK2", "name": "tyrosine kinase 2", "entrezgene": "7297", "ensembl": {"gene": ensg}}]}, indent=1))
    put("api/ensembl_homology_mus_musculus.json", json.dumps({"data": [{"id": ensg, "homologies": [{"type": "ortholog_one2one", "method_link_type": "ENSEMBL_ORTHOLOGUES", "source": {"id": ensg, "species": "homo_sapiens", "perc_id": 78.1},
                                                                                             "target": {"id": "ENSMUSG00000032175", "species": "mus_musculus", "perc_id": 79.4, "display_name": "Tyk2"}}]}]}, indent=1))
    put("api/gtex_medianGeneExpression_TYK2.json", json.dumps({"data": [{"gencodeId": f"{ensg}.12", "geneSymbol": "TYK2", "tissueSiteDetailId": t["tissue"], "median": t["median_tpm"], "unit": "TPM", "datasetId": "gtex_v8"} for t in SPEC["gtex_reference"]["tissues"]]}, indent=1))
    put("api/impc_genotype_phenotype_Tyk2.json", json.dumps({"response": {"numFound": len(SPEC["impc_hits"]), "docs": [{"marker_symbol": "Tyk2", **h} for h in SPEC["impc_hits"]]}}, indent=1))

    put("PROVENANCE.json", json.dumps({"synthetic": True, "origin": "bench/gen_primary.py from bench/spec.json", "note": "Engineering probe. Values are generated; API files imitate native response shapes with synthetic content. No file here is real study data.", "files": sorted(files)}, indent=1))
    put("README_CORPUS.md", "# Corpus\n\nAll files under this directory are the permitted source material for this task. See PROVENANCE.json. Nothing here has been pre-extracted or interpreted.\n\n" + "\n".join(f"- `{f}`" for f in sorted(files)))
    (c / "task.md").write_text(TASK)
    manifest = {"case_id": cid, "suite": "primary", "task_file": "task.md", "corpus_root": "corpus", "permitted_files": sorted(files),
                "deliverable_schema": "../../../schema/report.schema.json",
                "tools": ["list_files", "read_file", "search", "python_eval", "submit_report"],
                "limits": limits}
    if note: manifest["_note"] = note
    dump(c / "manifest.json", manifest)
    print(f"  wrote {cid} ({len(files)} corpus files)")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limits", choices=["dev", "final"], default="final"); a = ap.parse_args()
    lim = SPEC["limits_final"] if a.limits == "final" else SPEC["limits_dev"]
    P = [f"P{i:02d}" for i in range(1, 13)]; Q = [f"Q{i:02d}" for i in range(1, 13)]
    write_case("xctx-p00", mouse_l2fc=SPEC["invivo"]["log2fc_agree"], protein_participants=P, prot_prefix="S", limits=SPEC["limits_dev"], note="DEVELOPMENT EXAMPLE — feasibility only, never graded")
    write_case("xctx-p01", mouse_l2fc=SPEC["invivo"]["log2fc_agree"], protein_participants=P, prot_prefix="S", limits=lim)
    write_case("xctx-p02", mouse_l2fc=SPEC["invivo"]["log2fc_oppose"], protein_participants=P, prot_prefix="S", limits=lim)
    write_case("xctx-p03", mouse_l2fc=SPEC["invivo"]["log2fc_agree"], protein_participants=Q, prot_prefix="T", limits=lim)
    print("done. Rubric lives in held_out/primary_rubric.json — never inside primary/.")


if __name__ == "__main__":
    main()
