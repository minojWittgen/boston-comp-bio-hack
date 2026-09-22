"""Readable source summaries and navigation links derived only from supplied evidence."""
from dataclasses import dataclass, field
import re
from urllib.parse import quote, urlencode, urlsplit

from research_app.presentation import CONTEXT_LABELS, readable

SOURCE_NAMES = {
    "mygene": "MyGene · gene identity", "ensembl_orthology": "Ensembl · related genes across species",
    "gtex": "GTEx · tissue RNA expression", "impc": "IMPC · mouse phenotypes",
    "opentargets": "Open Targets · disease associations", "pubmed": "PubMed · article search",
    "hpa_cell_lines": "Human Protein Atlas · cell cultures", "hpa_pathology": "Human Protein Atlas · cancer summaries",
    "opentargets_depmap": "DepMap via Open Targets · cell-line screens", "reactome_pathway": "Reactome · pathway membership",
    "synthetic-demonstration": "Synthetic teaching data",
}
MISSING = "Not supplied by this source"


def obj(value):
    return value if isinstance(value, dict) else {}


def rows(value):
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def display(value):
    if value is None or value == [] or value == "":
        return MISSING
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if isinstance(v, (str, int, float))) or MISSING
    return str(value)


def safe_url(value):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password:
            return value
    except ValueError:
        pass
    return None


@dataclass
class SourceView:
    title: str
    summary: str
    limitation: str
    facts: dict = field(default_factory=dict)
    table: list = field(default_factory=list)
    links: list = field(default_factory=list)
    identities: dict = field(default_factory=dict)


def source_view(record):
    source = obj(record.payload.get("source_result"))
    data, query = obj(source.get("data")), obj(source.get("query"))
    name = SOURCE_NAMES.get(record.source, readable(record.source))
    view = SourceView(f"{record.entity} · {name}", "A source result was retrieved. Open the source to review its content.",
                      "Interpret this result in its reported source context. Study design, measurement definitions and comparability may need further review.")
    view.identities = {"Study ID": record.study_id or MISSING, "Participant / subject ID": record.subject_id or MISSING,
                       "Sample / specimen ID": record.specimen_id or MISSING, "Time point": record.timepoint or MISSING}
    for i, value in enumerate(record.provenance, 1):
        if url := safe_url(value):
            view.links.append((f"Supplied source link {i}", url, "supplied"))
        elif isinstance(value, str) and re.fullmatch(r"PMID:\d+", value):
            pmid = value.removeprefix("PMID:")
            view.links.append((f"Source reference · PMID {pmid}", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "identifier"))
        elif isinstance(value, str) and ":" not in value:
            view.facts[f"Source reference {i}"] = value
    # These links navigate by returned identifiers. They are not paper citations or
    # claims that a database landing page contains the experiment needed by the plan.
    ensg = query.get("ensg") or data.get("ensembl_primary") or data.get("id")
    if not isinstance(ensg, str) or not re.fullmatch(r"ENSG\d+(?:\.\d+)?", ensg):
        ensg = None
    if ensg:
        view.facts["Ensembl gene ID"] = ensg
    if record.source == "mygene":
        view.summary = f"Gene identity: {display(data.get('symbol'))} — {display(data.get('name'))}."
        view.limitation = "Gene identity provides a lookup reference, not experimental evidence."
        if data.get("ambiguous") is not False:
            view.limitation += " The returned gene identity needs review."
        entrez = str(data.get("entrez", ""))
        if entrez.isdigit():
            view.facts["NCBI Gene ID"] = entrez
            view.links.append(("NCBI gene record", f"https://www.ncbi.nlm.nih.gov/gene/{entrez}", "identifier"))
        if ensg:
            view.links.append(("Ensembl gene record", f"https://www.ensembl.org/id/{ensg}", "identifier"))
    elif record.source == "ensembl_orthology":
        species = query.get("target_species") or record.species
        view.title += f" · {readable(species)}"
        orthologs = rows(data.get("orthologs"))
        view.summary = f"Returned {len(orthologs)} related {'gene' if len(orthologs) == 1 else 'genes'} for {readable(species)}."
        examples = []
        for row in orthologs[:3]:
            target, query_identity = row.get("perc_id_target"), row.get("perc_id_source")
            if isinstance(target, (int, float)) and isinstance(query_identity, (int, float)):
                examples.append(f"{display(row.get('target_symbol'))}: {target:.2f}% identity in the other-species sequence and {query_identity:.2f}% in the queried-gene sequence")
        if examples:
            view.summary += " " + "; ".join(examples) + "."
        view.limitation = "Sequence similarity does not establish conserved expression, pathway activity or disease effects."
        view.facts["How to read sequence identity"] = "Target means the other-species sequence; source means the queried-gene sequence. Each percentage describes identical sequence positions relative to that side. Neither is a probability, an evidence score, nor an RNA-abundance measurement."
        view.links.append(("Ensembl guide to identity percentages", "https://grch37.ensembl.org/Help/View?id=578", "definition"))
        for row in orthologs:
            view.table.append({"Gene": display(row.get("target_symbol")), "Species": readable(row.get("species")),
                               "Ensembl gene ID": display(row.get("target_id")), "Relationship": readable(row.get("type")),
                               "Other-species sequence identity (%)": row.get("perc_id_target"), "Queried-gene sequence identity (%)": row.get("perc_id_source")})
            target = row.get("target_id", "")
            if isinstance(target, str) and re.fullmatch(r"ENS[A-Z]*G\d+", target):
                view.links.append((f"Ensembl {target}", f"https://www.ensembl.org/id/{target}", "identifier"))
    elif record.source == "gtex":
        view.table = [{"Tissue / cell type": readable(r.get("tissue")), "Median RNA (TPM)": r.get("median_tpm")} for r in rows(data.get("tissues"))]
        view.summary = f"Median RNA expression was returned for {len(view.table)} tissue or cell-type groups."
        examples = [f"{r['Tissue / cell type']}: {r['Median RNA (TPM)']:.2f} TPM" for r in view.table[:3] if isinstance(r['Median RNA (TPM)'], (int, float))]
        if examples:
            view.summary += " Examples from the returned reference dataset: " + "; ".join(examples) + "."
        view.limitation = "Group medians are reference expression levels, not patient-level measurements or disease-versus-control effects. TPM means transcripts per million."
        if ensg:
            view.links.append(("GTEx gene page", f"https://gtexportal.org/home/gene/{ensg}", "identifier"))
    elif record.source == "impc":
        hits = rows(data.get("hits"))
        view.summary = f"Mouse phenotype associations returned: {len(hits)}. The source reports {display(data.get('n_tests'))} tests."
        view.limitation = "These are mouse phenotype annotations. They do not directly measure the requested human or patient response."
        view.table = [{"Phenotype": display(r.get("mp_term_name")), "Phenotype ID": display(r.get("mp_term_id")),
                       "Sex": display(r.get("sex")), "Genotype": display(r.get("zygosity")), "Allele": display(r.get("allele_symbol")),
                       "Reported p-value": r.get("p_value")} for r in hits]
        if symbol := query.get("mouse_symbol"):
            params = urlencode({"q": f'marker_symbol:"{symbol}"', "rows": 500, "wt": "json"})
            view.links.append(("IMPC source query (JSON)", f"https://www.ebi.ac.uk/mi/impc/solr/genotype-phenotype/select?{params}", "query"))
    elif record.source == "opentargets":
        assoc = obj(data.get("associatedDiseases"))
        view.table = [{"Disease": display(obj(r.get("disease")).get("name")), "Disease ID": display(obj(r.get("disease")).get("id")),
                       "Association score": r.get("score")} for r in rows(assoc.get("rows"))]
        view.summary = f"Returned {len(view.table)} disease associations out of {display(assoc.get('count'))} reported by the database."
        view.limitation = "Association scores are database rankings, not probabilities or treatment effects. The returned list may include diseases outside your question."
    elif record.source == "pubmed":
        pmids = [str(p) for p in data.get("pmids", []) if str(p).isdigit()] if isinstance(data.get("pmids"), list) else []
        view.summary = f"Returned {len(pmids)} article identifiers from {display(data.get('count'))} search matches."
        view.limitation = "These are search results, not screened studies. Article titles, full text and study measurements were not supplied by this search."
        if term := query.get("term"):
            view.facts["Search query"] = str(term)
            view.links.append(("Open PubMed search", "https://pubmed.ncbi.nlm.nih.gov/?" + urlencode({"term": str(term)}), "query"))
        view.links.extend((f"PubMed article · PMID {p}", f"https://pubmed.ncbi.nlm.nih.gov/{p}/", "identifier") for p in pmids)
    elif record.source == "hpa_cell_lines":
        rna, protein = obj(data.get("rna")), obj(data.get("protein"))
        view.summary = f"Cell-line RNA distribution: {display(rna.get('cell_line_distribution'))}. Protein location: {display(protein.get('subcellular_location'))}."
        view.facts.update({"Cell-line RNA distribution": display(rna.get("cell_line_distribution")),
                           "Cell-line-specific RNA (nTPM)": display(rna.get("cell_line_specific_ntpm")),
                           "Protein location": display(protein.get("subcellular_location"))})
        view.limitation = "Distribution and protein location are summaries; they do not supply matched RNA/protein measurements or a disease contrast."
    elif record.source == "hpa_pathology":
        view.summary = f"Cancer RNA distribution: {display(data.get('cancer_rna_distribution'))}. Cancer RNA specificity: {display(data.get('cancer_rna_specificity'))}."
        view.facts.update({"Disease annotations": display(data.get("disease_involvement")),
                           "Cancer RNA distribution": display(data.get("cancer_rna_distribution")),
                           "Cancer RNA specificity": display(data.get("cancer_rna_specificity"))})
        view.limitation = "These are cohort summaries and disease annotations. Individual patient variation and matched patient samples are not resolved."
    elif record.source == "opentargets_depmap":
        for tissue in rows(data.get("tissues")):
            for screen in rows(tissue.get("screens")):
                view.table.append({"Cell line": display(screen.get("cellLineName")), "Tissue": display(tissue.get("tissueName")),
                                   "Disease annotation": display(screen.get("diseaseFromSource")), "CRISPR gene-effect score": screen.get("geneEffect"),
                                   "RNA expression (units not supplied)": screen.get("expression")})
        view.summary = f"Cell-line screen results returned: {len(view.table)} across {display(data.get('n_tissues'))} tissue groups."
        if view.table:
            first = view.table[0]
            values = []
            if first['RNA expression (units not supplied)'] is not None:
                values.append(f"RNA expression {first['RNA expression (units not supplied)']} (units not supplied)")
            if first['CRISPR gene-effect score'] is not None:
                values.append(f"CRISPR gene-effect score {first['CRISPR gene-effect score']}")
            if values:
                view.summary += f" Example returned screen, {first['Cell line']}: " + "; ".join(values) + "."
        view.limitation = "Cell-line names and returned screen values are shown below. Repeated names can represent multiple screens, not independent studies. The response does not specify study IDs, expression units or treatment-versus-control contrasts; gene-effect scores describe CRISPR fitness dependency."
    elif record.source == "reactome_pathway":
        view.summary = "Pathway membership was retrieved."
        view.limitation = "Membership defines the genes in scope; it does not measure pathway activity."
        if re.fullmatch(r"R-[A-Z]{3}-\d+", record.entity):
            view.links.append(("Reactome pathway", f"https://reactome.org/content/detail/{record.entity}", "identifier"))
    if record.source in {"opentargets", "opentargets_depmap"} and ensg:
        view.links.append(("Open Targets gene page", f"https://platform.opentargets.org/target/{ensg}", "identifier"))
    if record.source in {"hpa_cell_lines", "hpa_pathology"} and ensg:
        view.links.append(("Human Protein Atlas gene page", f"https://www.proteinatlas.org/{ensg}-{quote(record.entity, safe='')}", "identifier"))
    if not data and record.source != "reactome_pathway":
        view.summary = "The source did not supply a readable data summary."
    if record.level == "observation":
        view.summary = f"{readable(record.endpoint)}: {readable(record.direction)}. Comparison: {record.contrast or MISSING}."
        view.limitation = "This is a supplied study observation. Its source, measurements and participant matching still need scientific review."
        view.facts.update({"Measured outcome": readable(record.endpoint), "Reported direction": readable(record.direction),
                           "Comparison group / condition": record.contrast or MISSING, "Units": record.unit or MISSING,
                           "Species": readable(record.species), "Context": CONTEXT_LABELS.get(record.context, MISSING),
                           "Tissue": record.tissue or MISSING, "Disease / condition": record.condition or MISSING,
                           "Host species": readable(record.host_species)})
    return view
