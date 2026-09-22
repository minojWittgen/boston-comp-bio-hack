"""Per-source fetchers.

Every public function returns a SourceResult dict and never raises:
  status = "ok"         data found
           "not_found"  query succeeded, source has no record (a database fact, not a biological negative)
           "error"      technical failure (network, schema change, rate limit exhausted)
           "skipped"    disabled by mode, or an upstream step failed
"""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any

import requests

HEADERS = {"User-Agent": "xctx-hackathon/0.1", "Accept": "application/json"}
TIMEOUT = 30

OT_URL = "https://api.platform.opentargets.org/api/v4/graphql"
ENSEMBL = "https://rest.ensembl.org"
MYGENE = "https://mygene.info/v3"
GTEX = "https://gtexportal.org/api/v2"
IMPC = "https://www.ebi.ac.uk/mi/impc/solr"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
HPA = "https://www.proteinatlas.org/api/search_download.php"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def result(source: str, status: str, query: dict, data: Any = None,
           error: str | None = None, version: str | None = None) -> dict:
    return {"source": source, "status": status, "query": query, "data": data,
            "error": error, "source_version": version, "retrieved_at": now()}


def http(method: str, url: str, *, params=None, json=None, max_tries: int = 4) -> Any:
    """HTTP call with backoff on 429/5xx. Raises after the last attempt."""
    resp = None
    for attempt in range(max_tries):
        resp = requests.request(method, url, params=params, json=json,
                                headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code in (429, 500, 502, 503, 504):
            wait = float(resp.headers.get("Retry-After", 2 ** attempt))
            time.sleep(min(wait, 30))
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    raise RuntimeError(f"exhausted retries: {url}")


# ---------------------------------------------------------------- gene normalization
def normalize_gene(symbol: str) -> dict:
    q = {"symbol": symbol}
    try:
        d = http("GET", f"{MYGENE}/query", params={
            "q": f"symbol:{symbol}", "species": "human", "size": 3,
            "fields": "symbol,name,entrezgene,ensembl.gene"})
        hits = [h for h in d.get("hits", []) if h.get("symbol", "").upper() == symbol.upper()]
        if not hits:
            return result("mygene", "not_found", q)
        h = hits[0]
        ens = h.get("ensembl") or []
        ens_ids = [e["gene"] for e in (ens if isinstance(ens, list) else [ens])]
        return result("mygene", "ok", q, data={
            "symbol": h["symbol"], "name": h.get("name"), "entrez": h.get("entrezgene"),
            "ensembl_ids": ens_ids,
            "ensembl_primary": ens_ids[0] if ens_ids else None,
            "ambiguous": len(ens_ids) != 1 or len(hits) > 1})
    except Exception as e:  # noqa: BLE001
        return result("mygene", "error", q, error=repr(e))


# ---------------------------------------------------------------- Ensembl orthology
def ensembl_orthologs(ensg: str, target_species: str) -> dict:
    """Keep every ortholog with its type (one2one / one2many / many2many)."""
    q = {"ensg": ensg, "target_species": target_species}
    try:
        d = http("GET", f"{ENSEMBL}/homology/id/human/{ensg}", params={
            "type": "orthologues", "target_species": target_species,
            "sequence": "none", "content-type": "application/json"})
        homs = (d.get("data") or [{}])[0].get("homologies", [])
        if not homs:
            return result("ensembl_orthology", "not_found", q, data={"orthologs": []})
        orthologs = []
        for h in homs:
            tgt = h.get("target", {})
            orthologs.append({
                "target_id": tgt.get("id"), "species": tgt.get("species"),
                "type": h.get("type"),
                "perc_id_target": tgt.get("perc_id"),
                "perc_id_source": h.get("source", {}).get("perc_id")})
        for o in orthologs:  # add symbols for downstream (IMPC needs mouse symbol)
            try:
                o["target_symbol"] = http("GET", f"{ENSEMBL}/lookup/id/{o['target_id']}",
                                          params={"content-type": "application/json"}
                                          ).get("display_name")
            except Exception:  # noqa: BLE001
                o["target_symbol"] = None
        return result("ensembl_orthology", "ok", q, data={
            "orthologs": orthologs,
            "one2one": [o for o in orthologs if o["type"] == "ortholog_one2one"]})
    except Exception as e:  # noqa: BLE001
        return result("ensembl_orthology", "error", q, error=repr(e))


# ---------------------------------------------------------------- GTEx
def gtex_expression(ensg: str, dataset: str = "gtex_v8") -> dict:
    q = {"ensg": ensg, "dataset": dataset}
    try:
        ref = http("GET", f"{GTEX}/reference/gene", params={"geneId": ensg})
        genes = ref.get("data", [])
        if not genes:
            return result("gtex", "not_found", q, version=dataset)
        gencode = genes[0]["gencodeId"]
        try:
            d = http("GET", f"{GTEX}/expression/clusteredMedianGeneExpression",
                     params={"gencodeId": gencode, "datasetId": dataset})
            rows = d.get("medianGeneExpression", [])
        except Exception:  # noqa: BLE001  fallback to older endpoint
            d = http("GET", f"{GTEX}/expression/medianGeneExpression",
                     params={"gencodeId": gencode, "datasetId": dataset})
            rows = d.get("data", [])
        if not rows:
            return result("gtex", "not_found", q, data={"gencodeId": gencode}, version=dataset)
        tissues = sorted(({"tissue": r.get("tissueSiteDetailId"), "median_tpm": r.get("median")}
                          for r in rows), key=lambda r: r["median_tpm"] or 0, reverse=True)
        return result("gtex", "ok", q, data={"gencodeId": gencode, "tissues": tissues},
                      version=dataset)
    except Exception as e:  # noqa: BLE001
        return result("gtex", "error", q, error=repr(e), version=dataset)


# ---------------------------------------------------------------- IMPC
def impc_phenotypes(mouse_symbol: str) -> dict:
    """Distinguish 'phenotyped, no hits' from 'never phenotyped'."""
    q = {"mouse_symbol": mouse_symbol}
    try:
        tested = http("GET", f"{IMPC}/statistical-result/select", params={
            "q": f'marker_symbol:"{mouse_symbol}"', "rows": 0, "wt": "json"}
        )["response"]["numFound"]
        if tested == 0:
            return result("impc", "not_found", q, data={"phenotyped": False})
        d = http("GET", f"{IMPC}/genotype-phenotype/select", params={
            "q": f'marker_symbol:"{mouse_symbol}"', "rows": 500, "wt": "json",
            "fl": "mp_term_id,mp_term_name,top_level_mp_term_name,zygosity,sex,p_value,allele_symbol"})
        docs = d["response"]["docs"]
        return result("impc", "ok", q, data={"phenotyped": True, "n_tests": tested,
                                              "hits": docs})
    except Exception as e:  # noqa: BLE001
        return result("impc", "error", q, error=repr(e))


# ---------------------------------------------------------------- Open Targets
OT_QUERY = """
query T($id: String!) {
  target(ensemblId: $id) {
    id approvedSymbol approvedName biotype
    associatedDiseases(page: {index: 0, size: 25}) {
      count
      rows {
        score
        disease { id name }
        datasourceScores { id score }
      }
    }
  }
}"""
OT_META = "query { meta { dataVersion { year month } } }"


def opentargets_target(ensg: str) -> dict:
    q = {"ensg": ensg}
    try:
        version = None
        try:
            m = http("POST", OT_URL, json={"query": OT_META})["data"]["meta"]["dataVersion"]
            version = f"{m['year']}.{m['month']}"
        except Exception:  # noqa: BLE001
            pass
        d = http("POST", OT_URL, json={"query": OT_QUERY, "variables": {"id": ensg}})
        if d.get("errors"):
            return result("opentargets", "error", q, error=str(d["errors"]), version=version)
        tgt = d["data"]["target"]
        if not tgt:
            return result("opentargets", "not_found", q, version=version)
        return result("opentargets", "ok", q, data=tgt, version=version)
    except Exception as e:  # noqa: BLE001
        return result("opentargets", "error", q, error=repr(e))


# ---------------------------------------------------------------- PubMed
def pubmed_search(symbol: str, disease: str = "", retmax: int = 20) -> dict:
    term = f'"{symbol}"[tiab]' + (f" AND ({disease})" if disease else "")
    q = {"term": term}
    params = {"db": "pubmed", "term": term, "retmode": "json", "retmax": retmax}
    if os.environ.get("NCBI_API_KEY"):
        params["api_key"] = os.environ["NCBI_API_KEY"]
    try:
        d = http("GET", f"{EUTILS}/esearch.fcgi", params=params)["esearchresult"]
        count, ids = int(d.get("count", 0)), d.get("idlist", [])
        if count == 0:
            return result("pubmed", "not_found", q, data={"count": 0})
        return result("pubmed", "ok", q, data={"count": count, "pmids": ids})
    except Exception as e:  # noqa: BLE001
        return result("pubmed", "error", q, error=repr(e))


# ---------------------------------------------------------------- HPA cell lines (in vitro)
def hpa_cell_lines(ensg: str) -> dict:
    """Human Protein Atlas in-vitro evidence: cell-line RNA + protein (separate modalities).

    RNA (modality=rna): HPA cell-line distribution and cell-line-specific nTPM (summary;
    per-cell-line nTPM vectors need the bulk TSV, see registry limitations).
    Protein (modality=protein): subcellular location and protein class (HPA
    immunofluorescence in cell lines).
    """
    q = {"ensg": ensg}
    cols = "g,eg,rnacld,rnaclsm,scl,scml,pc"
    try:
        rows = http("GET", HPA, params={"search": ensg, "format": "json",
                                        "compress": "no", "columns": cols})
        row = next((r for r in rows if r.get("Ensembl") == ensg), None)
        if not row:
            return result("hpa_cell_lines", "not_found", q, version="HPA")
        rna = {"cell_line_distribution": row.get("RNA cell line distribution"),
               "cell_line_specific_ntpm": row.get("RNA cell line specific nTPM")}
        protein = {"subcellular_location": row.get("Subcellular location"),
                   "subcellular_main": row.get("Subcellular main location"),
                   "protein_class": row.get("Protein class")}
        has_rna = any(v for v in rna.values())
        has_protein = any(v for v in protein.values())
        if not has_rna and not has_protein:  # identifier-only row, no substantive evidence
            return result("hpa_cell_lines", "not_found", q, version="HPA",
                          data={"reason": "gene row exists but no cell-line RNA/protein fields"})
        return result("hpa_cell_lines", "ok", q, version="HPA", data={
            "gene": row.get("Gene"), "rna": rna, "protein": protein,
            "has_rna": has_rna, "has_protein": has_protein})
    except Exception as e:  # noqa: BLE001
        return result("hpa_cell_lines", "error", q, error=repr(e))


# ---------------------------------------------------------------- HPA pathology (patient / disease)
def hpa_pathology(ensg: str) -> dict:
    """HPA cancer/disease evidence (TCGA-derived). COHORT-level, not individual variation.

    Fills the patient/disease context at the same background/summary level as the other
    sources: disease involvement and cancer RNA specificity/distribution. Per-patient
    variation and matched measurements are NOT provided (kept as an explicit gap).
    """
    q = {"ensg": ensg}
    cols = "g,eg,di,rnacas,rnacad"
    try:
        rows = http("GET", HPA, params={"search": ensg, "format": "json",
                                        "compress": "no", "columns": cols})
        row = next((r for r in rows if r.get("Ensembl") == ensg), None)
        if not row:
            return result("hpa_pathology", "not_found", q, version="HPA")
        disease = row.get("Disease involvement") or []
        cancer_spec = row.get("RNA cancer specificity")
        cancer_dist = row.get("RNA cancer distribution")
        has_cancer_rna = bool(cancer_spec or cancer_dist)
        has_disease_annotation = bool(disease)
        if not has_cancer_rna and not has_disease_annotation:  # identifier-only row
            return result("hpa_pathology", "not_found", q, version="HPA",
                          data={"reason": "gene row exists but no disease annotation or cancer RNA"})
        return result("hpa_pathology", "ok", q, version="HPA", data={
            "disease_involvement": disease,
            "cancer_rna_specificity": cancer_spec,
            "cancer_rna_distribution": cancer_dist,
            "has_cancer_rna": has_cancer_rna,
            "has_disease_annotation": has_disease_annotation,
            "granularity": "cohort",
            "individual_variation": "not resolved"})
    except Exception as e:  # noqa: BLE001
        return result("hpa_pathology", "error", q, error=repr(e))


# ---------------------------------------------------------------- Open Targets DepMap (in vitro)
OT_DEPMAP_QUERY = """
query D($id: String!) {
  target(ensemblId: $id) {
    id approvedSymbol
    isEssential
    depMapEssentiality {
      tissueName
      screens { cellLineName diseaseFromSource geneEffect expression mutation }
    }
  }
}"""


def opentargets_depmap(ensg: str) -> dict:
    """DepMap CRISPR fitness essentiality (in vitro cell lines) via Open Targets.

    This is fitness dependency, NOT disease association and NOT pathway expression, so
    it does not leak benchmark answers and runs in eval mode too.
    """
    q = {"ensg": ensg}
    try:
        d = http("POST", OT_URL, json={"query": OT_DEPMAP_QUERY, "variables": {"id": ensg}})
        if d.get("errors"):
            return result("opentargets_depmap", "error", q, error=str(d["errors"]))
        tgt = d["data"]["target"]
        if not tgt:
            return result("opentargets_depmap", "not_found", q)
        ess = tgt.get("depMapEssentiality") or []
        if tgt.get("isEssential") is None and not ess:
            return result("opentargets_depmap", "not_found", q,
                          data={"isEssential": None, "n_tissues": 0})
        return result("opentargets_depmap", "ok", q, data={
            "isEssential": tgt.get("isEssential"),
            "n_tissues": len(ess), "tissues": ess})
    except Exception as e:  # noqa: BLE001
        return result("opentargets_depmap", "error", q, error=repr(e))
