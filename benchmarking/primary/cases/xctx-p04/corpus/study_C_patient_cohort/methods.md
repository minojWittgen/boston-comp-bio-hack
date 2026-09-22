# Study C — methods excerpt (synthetic)

Adults with plaque psoriasis (n = 12; mean age 44.1; 50% female; site Site A).
At the baseline visit, paired 4 mm punch biopsies were taken from a lesional plaque and from non-lesional skin.
RNA: bulk RNA-seq, values reported as log2 CPM per specimen in `rna_log2cpm.csv`.
Each biopsy was split: one half for RNA (bulk RNA-seq, log2 CPM per specimen in `rna_log2cpm.csv`) and one half for protein (Olink Explore panel, NPX, log2 scale, per specimen in `protein_npx.csv`). RNA and protein rows therefore share the biopsy `specimen_id`.
Specimen-to-participant mapping, visit and biopsy site are in `specimens.csv`. **Participant identity must be
taken from `specimens.csv`; specimen ids are not participant ids.**
