#!/usr/bin/env python3
"""PRIMARY suite generator (v4): same research request + same SOURCE corpus for every system.

  python bench/gen_primary.py [--limits dev|final]

Each case is a frozen corpus of source-native material. Nothing is pre-extracted, normalized or
interpreted. Everything is synthetic and labelled in corpus/PROVENANCE.json.

Corpus layout
  study_A_invitro/ study_B_mouse_imq/ study_C_patient_cohort/   methods excerpts + result tables + specimen metadata
  api/                     recorded native responses for EVERY request the production data pipeline makes
                           in eval mode (index.json maps method+url+params → file). The integrated system's
                           collectors replay these; the baseline may read them like any other file.

Cases
  xctx-p00  development/calibration example (never graded)
  xctx-p01  scoped agreement
  xctx-p02  animal-context disagreement (mouse IMQ Tyk2 DOWN under a valid comparison)
  xctx-p03  invalid within-person match (proteomics on a second cohort; methods say so)
  xctx-p04  mixed input: two genes (TYK2, IL17A) and two pathway definitions — integration check only
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, dump, load  # noqa: E402

SPEC = load(Path(__file__).with_name("spec.json"))
PRIMARY = ROOT / "primary"
GENES = {"TYK2": {"mouse": "Tyk2", "ensg": "ENSG00000105397", "entrez": "7297", "ensmusg": "ENSMUSG00000032175", "name": "tyrosine kinase 2"},
         "IL17A": {"mouse": "Il17a", "ensg": "ENSG00000112115", "entrez": "3605", "ensmusg": "ENSMUSG00000025929", "name": "interleukin 17A"}}
GENES_H = ["TYK2", "JAK1", "STAT3", "IL17A", "IL23R", "KRT16", "S100A8", "GAPDH", "ACTB", "IFNG"]
GENES_M = ["Tyk2", "Jak1", "Stat3", "Il17a", "Il23r", "Krt16", "S100a8", "Gapdh", "Actb", "Ifng"]
MYGENE = "https://mygene.info/v3"; ENSEMBL = "https://rest.ensembl.org"; GTEX = "https://gtexportal.org/api/v2"
IMPC = "https://www.ebi.ac.uk/mi/impc/solr"; OT_URL = "https://api.platform.opentargets.org/api/v4/graphql"
HPA = "https://www.proteinatlas.org/api/search_download.php"

TASK = """# Research request

**Question.** An in-vitro experiment (study A) reports that {gene} mRNA is higher in IL-23-stimulated primary
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
identity, orthology, tissue reference abundance, knockout phenotypes, recorded as native API responses) are
background: use them for identity and species mapping, not as disease-contrast evidence. List limitations and
anything that remains unresolved.

Deliver a short report in the envelope described by `schema/report.schema.json` via `submit_report`.
"""
TASK_P04 = TASK.replace("that {gene} mRNA is higher", "that TYK2 and IL17A mRNA are each higher") + """
**Mixed-input scope.** Answer each comparison **per gene** (`in_vitro_vs_animal:TYK2`, `in_vitro_vs_animal:IL17A`, …)
and additionally for each supplied pathway definition in `corpus/pathways/` (`in_vitro_vs_animal:R-HSA-SYN-1`, …).
A finding about one member gene is not a finding about the whole pathway; say what the pathway-level evidence
actually covers and mark unsupported pathway conclusions as insufficient_evidence. Do not count one measurement
as independent corroboration for more than one entity.
"""


def csv_text(rows, header):
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=header, lineterminator="\n"); w.writeheader(); w.writerows(rows); return buf.getvalue()


def de_table(rng, genes, targets: dict, ):
    rows = []
    for g in genes:
        if g in targets:
            l2, p = targets[g]
        else:
            l2 = round(rng.gauss(0, 0.5), 3); p = round(min(1.0, abs(rng.gauss(0.3, 0.3))), 4)
        rows.append({"gene": g, "baseMean": round(rng.uniform(50, 3000), 1), "log2FoldChange": l2, "lfcSE": round(rng.uniform(0.1, 0.3), 3),
                     "pvalue": p / 10 if p < 1 else p, "padj": p})
    return rows


# ------------------------------------------------------------------ recorded native API responses
def api_recordings(genes: list[str]) -> list[tuple[dict, str, dict]]:
    """(request, filename, response) for every call the production pipeline makes in eval mode."""
    rec = []
    for g in genes:
        G = GENES[g]; ensg, mm = G["ensg"], G["mouse"]
        rec.append(({"method": "GET", "url": f"{MYGENE}/query", "params": {"q": f"symbol:{g}", "species": "human", "size": 3, "fields": "symbol,name,entrezgene,ensembl.gene"}},
                    f"mygene_query_{g}.json", {"took": 3, "total": 1, "max_score": 90.1, "hits": [{"_id": G["entrez"], "_score": 90.1, "symbol": g, "name": G["name"], "entrezgene": G["entrez"], "ensembl": {"gene": ensg}}]}))
        for sp, hom in (("mus_musculus", [{"type": "ortholog_one2one", "method_link_type": "ENSEMBL_ORTHOLOGUES", "source": {"id": ensg, "species": "homo_sapiens", "perc_id": 78.1}, "target": {"id": G["ensmusg"], "species": "mus_musculus", "perc_id": 79.4}}]),
                        ("rattus_norvegicus", []),
                        ("macaca_mulatta", [{"type": "ortholog_one2one", "method_link_type": "ENSEMBL_ORTHOLOGUES", "source": {"id": ensg, "species": "homo_sapiens", "perc_id": 96.0}, "target": {"id": f"ENSMMUG_{g}", "species": "macaca_mulatta", "perc_id": 96.2}}])):
            rec.append(({"method": "GET", "url": f"{ENSEMBL}/homology/id/human/{ensg}", "params": {"type": "orthologues", "target_species": sp, "sequence": "none", "content-type": "application/json"}},
                        f"ensembl_homology_{g}_{sp}.json", {"data": [{"id": ensg, "homologies": hom}]}))
            for h in hom:
                tid = h["target"]["id"]; name = mm if sp == "mus_musculus" else g
                rec.append(({"method": "GET", "url": f"{ENSEMBL}/lookup/id/{tid}", "params": {"content-type": "application/json"}},
                            f"ensembl_lookup_{tid}.json", {"id": tid, "display_name": name, "species": sp, "biotype": "protein_coding", "object_type": "Gene"}))
        rec.append(({"method": "GET", "url": f"{GTEX}/reference/gene", "params": {"geneId": ensg}}, f"gtex_reference_gene_{g}.json",
                    {"data": [{"gencodeId": f"{ensg}.12", "geneSymbol": g, "geneType": "protein coding", "chromosome": "chr19", "start": 10350528, "end": 10380676, "strand": "-"}], "paging_info": {"numberOfPages": 1, "page": 0, "maxItemsPerPage": 250, "totalNumberOfItems": 1}}))
        tissues = SPEC["gtex_reference"]["tissues"]
        rec.append(({"method": "GET", "url": f"{GTEX}/expression/clusteredMedianGeneExpression", "params": {"gencodeId": f"{ensg}.12", "datasetId": "gtex_v8"}}, f"gtex_clusteredMedianGeneExpression_{g}.json",
                    {"medianGeneExpression": [{"gencodeId": f"{ensg}.12", "geneSymbol": g, "tissueSiteDetailId": t["tissue"], "median": t["median_tpm"], "unit": "TPM", "datasetId": "gtex_v8"} for t in tissues], "clusters": {}}))
        rec.append(({"method": "GET", "url": f"{IMPC}/statistical-result/select", "params": {"q": f'marker_symbol:"{mm}"', "rows": 0, "wt": "json"}}, f"impc_statistical_result_{mm}.json",
                    {"responseHeader": {"status": 0}, "response": {"numFound": 412, "start": 0, "docs": []}}))
        rec.append(({"method": "GET", "url": f"{IMPC}/genotype-phenotype/select", "params": {"q": f'marker_symbol:"{mm}"', "rows": 500, "wt": "json", "fl": "mp_term_id,mp_term_name,top_level_mp_term_name,zygosity,sex,p_value,allele_symbol"}}, f"impc_genotype_phenotype_{mm}.json",
                    {"responseHeader": {"status": 0}, "response": {"numFound": len(SPEC["impc_hits"]), "start": 0, "docs": [dict(h) for h in SPEC["impc_hits"]]}}))
        rec.append(({"method": "GET", "url": HPA, "params": {"search": ensg, "format": "json", "compress": "no", "columns": "g,eg,rnacld,rnaclsm,scl,scml,pc"}}, f"hpa_search_{g}.json",
                    [{"Gene": g, "Ensembl": ensg, "RNA cell line distribution": "Detected in many", "RNA cell line specific nTPM": None, "Subcellular location": "Cytosol", "Subcellular main location": "Cytosol", "Protein class": "Enzymes, Kinases"}]))
        rec.append(({"method": "POST", "url": OT_URL, "json_variables": {"id": ensg}, "json_query_contains": "depMapEssentiality"}, f"opentargets_depmap_{g}.json",
                    {"data": {"target": {"id": ensg, "approvedSymbol": g, "isEssential": False, "depMapEssentiality": [{"tissueName": "Skin", "screens": [{"cellLineName": "A375", "diseaseFromSource": "melanoma", "geneEffect": -0.12, "expression": 4.1, "mutation": None}]}]}}}))
    return rec


def write_case(cid, *, genes, mouse_l2fc: dict, protein_participants, prot_prefix, second_cohort: bool, limits, note=None, pathways=None):
    rng = random.Random(cid); c = PRIMARY / "cases" / cid; corpus = c / "corpus"
    files = []
    def put(rel, text):
        p = corpus / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text); files.append(rel)

    iv = SPEC["invitro"]
    put("study_A_invitro/methods.md", f"""# Study A — methods excerpt (synthetic)

Primary human epidermal keratinocytes ({iv['model']}) were stimulated with {iv['perturbation']} or {iv['reference']}.
Total RNA was profiled by bulk RNA-seq ({iv['n_case']} stimulated, {iv['n_reference']} vehicle wells). Differential
expression was computed with DESeq2 for the contrast **IL-23 vs vehicle**; results are in `de_results.csv`
(log2FoldChange > 0 means higher in IL-23). Endpoint: mRNA abundance. Gene symbols are human (HGNC).
""")
    put("study_A_invitro/de_results.csv", csv_text(de_table(rng, GENES_H, {g: (iv["log2fc"] if g == "TYK2" else 1.9, iv["padj"]) for g in genes}), ["gene", "baseMean", "log2FoldChange", "lfcSE", "pvalue", "padj"]))

    v = SPEC["invivo"]
    put("study_B_mouse_imq/methods.md", f"""# Study B — methods excerpt (synthetic)

Species: *Mus musculus*, C57BL/6J, female, 8–10 weeks. Psoriasiform inflammation was induced with topical
imiquimod (5% cream, 62.5 mg/day, 6 days) on shaved dorsal skin; controls received vehicle cream. On day 6,
full-thickness dorsal skin was collected ({v['n_case']} IMQ, {v['n_reference']} vehicle; see `animals.csv`) and
profiled by bulk RNA-seq. DESeq2 contrast: **IMQ vs vehicle** (log2FoldChange > 0 = higher in IMQ).
Endpoint: mRNA abundance. Gene symbols are mouse (MGI) symbols.
""")
    put("study_B_mouse_imq/de_results.csv", csv_text(de_table(rng, GENES_M, {GENES[g]["mouse"]: (mouse_l2fc[g], v["padj"]) for g in genes}), ["gene", "baseMean", "log2FoldChange", "lfcSE", "pvalue", "padj"]))
    put("study_B_mouse_imq/animals.csv", csv_text([{"animal_id": f"M{i:02d}", "group": "IMQ" if i <= 6 else "vehicle", "sex": "F", "tissue": "dorsal skin, full thickness", "day": 6} for i in range(1, 13)], ["animal_id", "group", "sex", "tissue", "day"]))

    P = [f"P{i:02d}" for i in range(1, 13)]; cs = SPEC["cohort_summary"]
    prot_text = ("Proteomics (Olink Explore panel, NPX, log2 scale) was performed on **a second cohort of 12 participants recruited under the same protocol** with matched demographics (see `specimens.csv` for the participant mapping); each of those biopsies was assayed for protein only."
                 if second_cohort else
                 "Each biopsy was split: one half for RNA (bulk RNA-seq, log2 CPM per specimen in `rna_log2cpm.csv`) and one half for protein (Olink Explore panel, NPX, log2 scale, per specimen in `protein_npx.csv`). RNA and protein rows therefore share the biopsy `specimen_id`.")
    put("study_C_patient_cohort/methods.md", f"""# Study C — methods excerpt (synthetic)

Adults with plaque psoriasis (n = {cs['n_participants']}; mean age {cs['age_mean']}; {int(cs['sex_ratio_f']*100)}% female; site {cs['site']}).
At the baseline visit, paired 4 mm punch biopsies were taken from a lesional plaque and from non-lesional skin.
RNA: bulk RNA-seq, values reported as log2 CPM per specimen in `rna_log2cpm.csv`.
{prot_text}
Specimen-to-participant mapping, visit and biopsy site are in `specimens.csv`. **Participant identity must be
taken from `specimens.csv`; specimen ids are not participant ids.**
""")
    spec_rows, rna_rows, prot_rows = [], [], []
    for pid in P:
        for arm in ("nonlesional", "lesional"):
            sid = f"S-{pid}-{'L' if arm == 'lesional' else 'NL'}"
            spec_rows.append({"specimen_id": sid, "participant_id": pid, "visit": "baseline", "site_type": arm, "assays": "rna" if second_cohort else "rna;protein"})
    for pid in P:
        base = rng.uniform(4, 6); d = SPEC["patient_rna"]["log2fc"] + rng.gauss(0, 0.15)
        for arm, val in (("nonlesional", base), ("lesional", base + d)):
            sid = f"S-{pid}-{'L' if arm == 'lesional' else 'NL'}"
            for g in GENES_H:
                rna_rows.append({"specimen_id": sid, "gene": g, "log2cpm": round(val if g in genes else rng.uniform(2, 9), 3)})
    for pid in protein_participants:
        base = rng.uniform(3, 5); d = SPEC["patient_prot"]["log2fc"] + rng.gauss(0, 0.15)
        for arm, val in (("nonlesional", base), ("lesional", base + d)):
            sid = f"{prot_prefix}-{pid}-{'L' if arm == 'lesional' else 'NL'}"
            if second_cohort:
                spec_rows.append({"specimen_id": sid, "participant_id": pid, "visit": "baseline", "site_type": arm, "assays": "protein"})
            for g in ("TYK2", "IL17A", "S100A8", "IFNG"):
                prot_rows.append({"specimen_id": sid, "assay_target": g, "npx": round(val if g in genes else rng.uniform(1, 6), 3)})
    put("study_C_patient_cohort/specimens.csv", csv_text(spec_rows, ["specimen_id", "participant_id", "visit", "site_type", "assays"]))
    put("study_C_patient_cohort/rna_log2cpm.csv", csv_text(rna_rows, ["specimen_id", "gene", "log2cpm"]))
    put("study_C_patient_cohort/protein_npx.csv", csv_text(prot_rows, ["specimen_id", "assay_target", "npx"]))

    index = []
    for req, fn, resp in api_recordings(genes):
        put(f"api/{fn}", json.dumps(resp, indent=1)); index.append({**req, "file": f"api/{fn}"})
    put("api/index.json", json.dumps({"_note": "Recorded native responses. The integrated system's collectors replay these instead of calling the live services; the baseline may read them as files.", "requests": index}, indent=1))

    if pathways:
        for pw in pathways:
            put(f"pathways/{pw['id']}.json", json.dumps(pw, indent=1))

    put("PROVENANCE.json", json.dumps({"synthetic": True, "origin": "bench/gen_primary.py from bench/spec.json",
                                       "note": "Engineering probe. Values are generated; api/ files imitate native response shapes with synthetic content; pathways/ are synthetic definitions. No file here is real study data.",
                                       "input_boundary": "processed study results, specimen metadata and recorded API snapshots — not raw sequencing reads, not live services",
                                       "files": sorted(files)}, indent=1))
    put("README_CORPUS.md", "# Corpus\n\nAll files under this directory are the permitted source material. See PROVENANCE.json. Nothing here has been pre-extracted or interpreted.\n\n" + "\n".join(f"- `{f}`" for f in sorted(files)))
    (c / "task.md").write_text((TASK_P04 if pathways else TASK).format(gene=genes[0]))
    manifest = {"case_id": cid, "suite": "primary", "task_file": "task.md", "corpus_root": "corpus", "permitted_files": sorted(files),
                "entities": {"genes": genes, "pathways": [p["id"] for p in (pathways or [])]},
                "deliverable_schema": "../../../schema/report.schema.json",
                "tools": ["list_files", "read_file", "search", "python_eval", "submit_report"], "limits": limits}
    if note: manifest["_note"] = note
    dump(c / "manifest.json", manifest)
    print(f"  wrote {cid} ({len(files)} corpus files)")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--limits", choices=["dev", "final"], default="final"); a = ap.parse_args()
    lim = SPEC["limits_final"] if a.limits == "final" else SPEC["limits_dev"]
    P = [f"P{i:02d}" for i in range(1, 13)]; Q = [f"Q{i:02d}" for i in range(1, 13)]
    agree, oppose = SPEC["invivo"]["log2fc_agree"], SPEC["invivo"]["log2fc_oppose"]
    write_case("xctx-p00", genes=["TYK2"], mouse_l2fc={"TYK2": agree}, protein_participants=P, prot_prefix="S", second_cohort=False, limits=SPEC["limits_dev"], note="DEVELOPMENT / CALIBRATION EXAMPLE — never graded")
    write_case("xctx-p01", genes=["TYK2"], mouse_l2fc={"TYK2": agree}, protein_participants=P, prot_prefix="S", second_cohort=False, limits=lim)
    write_case("xctx-p02", genes=["TYK2"], mouse_l2fc={"TYK2": oppose}, protein_participants=P, prot_prefix="S", second_cohort=False, limits=lim)
    write_case("xctx-p03", genes=["TYK2"], mouse_l2fc={"TYK2": agree}, protein_participants=Q, prot_prefix="T", second_cohort=True, limits=lim)
    pathways = [{"id": "R-HSA-SYN-1", "source": "synthetic-reactome-like", "version": "2026-09", "name": "IL-23/TYK2 receptor signalling (synthetic)", "genes": ["TYK2", "JAK1", "STAT3", "IL23R"]},
                {"id": "R-HSA-SYN-2", "source": "synthetic-reactome-like", "version": "2026-09", "name": "IL-17 effector program (synthetic)", "genes": ["IL17A", "S100A8", "KRT16"]}]
    write_case("xctx-p04", genes=["TYK2", "IL17A"], mouse_l2fc={"TYK2": agree, "IL17A": agree}, protein_participants=P, prot_prefix="S", second_cohort=False,
               limits={**lim, "max_data_tool_calls": lim["max_data_tool_calls"] + 4, "wall_clock_seconds": lim["wall_clock_seconds"] + 60}, pathways=pathways)
    print("done. Rubric lives in held_out/primary_rubric.json — never inside primary/.")


if __name__ == "__main__":
    main()
