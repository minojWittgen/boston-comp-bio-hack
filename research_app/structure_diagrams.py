"""Render the repository's canonical Mermaid figures without rewriting their graphs."""
from pathlib import Path
import re

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/minojWittgen/boston-comp-bio-hack"
FIGURES = (
    {
        "tab": "Coordinator workflow",
        "title": "Figure 1. Investigation execution and diagnostic separation",
        "document": "coordinator/README.md",
        "anchor": "execution-and-scientific-meaning",
        "block": 0,
        "status": "IMPLEMENTED COORDINATOR",
        "caption": "Research scope is fixed before collection. Source-grounded findings are compared across species, modalities and experimental contexts. Recoverable collection errors permit at most one retry within budget. Supplied-observation checks form a separate diagnostic path and do not determine investigation completion.",
    },
    {
        "tab": "Research framework",
        "title": "Figure 2. Proposed framework for cross-context evidence assessment",
        "document": "cross-context-biology-agent.md",
        "anchor": "2-architecture",
        "block": 0,
        "status": "CONCEPTUAL DESIGN · BROADER THAN THE CURRENT PROTOTYPE",
        "caption": "The design separates experimental context, species, modality and individual identity. In-vitro, in-vivo and patient evidence converge on a comparison with explicit criteria and bounded follow-up. This figure describes the broader research framework; Figure 1 documents the current execution protocol.",
    },
    {
        "tab": "Data pipeline",
        "title": "Figure 3. Gene and pathway evidence retrieval",
        "document": "data_pipeline/PIPELINE.md",
        "anchor": "flow",
        "block": 0,
        "status": "IMPLEMENTED PIPELINE · GENE COLLECTION CONNECTED TO THE COORDINATOR",
        "caption": "Gene queries yield source packages with in-vitro and cohort annotations. Pathway queries retrieve Reactome membership, definitions and labeled mouse inference; per-member gene collection is optional. The pathway branch is available in the pipeline and is not yet an automatic pathway-wide coordinator workflow.",
    },
    {
        "tab": "Evidence contexts",
        "title": "Figure 4. Evidence organization and unresolved patient-level information",
        "document": "data_pipeline/PIPELINE.md",
        "anchor": "evidence-organized-by-context--mirrors-the-v3-12-boxes",
        "block": 1,
        "status": "PIPELINE EVIDENCE MODEL · SOURCE COVERAGE VARIES BY QUERY",
        "caption": "Source records retain their biological setting and measurement meaning. Human reference data and disease cohorts remain distinct. Cohort-level summaries do not resolve individual or matched-patient variation; unavailable measurements and identifiers remain explicit gaps.",
    },
)


def diagram_source(figure):
    document = (ROOT / figure["document"]).read_text(encoding="utf-8")
    blocks = re.findall(r"^```mermaid\s*\n(.*?)^```\s*$", document, flags=re.MULTILINE | re.DOTALL)
    return blocks[figure["block"]].strip()


def show_structure():
    # Preserve the wide source graph at its natural text size rather than
    # shrinking all three context subgraphs into unreadable labels.
    st.html("""<style>
    .st-key-source-figure-4 [data-testid="stMermaidChart"] {display:block;overflow:auto;}
    .st-key-source-figure-4 [data-testid="stMermaidChart"] img {
      width:auto;max-width:none;max-height:none;
    }
    </style>""")
    tabs = st.tabs([figure["tab"] for figure in FIGURES])
    for number, (tab, figure) in enumerate(zip(tabs, FIGURES), start=1):
        with tab:
            source = diagram_source(figure)
            st.caption(figure["status"])
            if number == 4:
                st.caption("Scroll horizontally to inspect this wide figure at its original text size.")
            with st.container(border=True, key=f"source-figure-{number}"):
                st.mermaid_chart(source)
            st.markdown(f"**{figure['title']}.** {figure['caption']}")
            st.markdown(f"Source: [{figure['document']}]({REPOSITORY}/blob/main/{figure['document']}#{figure['anchor']}). "
                        "Node labels, connections and branches are rendered directly from the Markdown source.")
            with st.expander("View original Mermaid source"):
                st.code(source, language="mermaid")
