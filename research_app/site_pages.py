"""Public introduction and attribution, grounded in the repository's design documents."""
import streamlit as st

from research_app.intro_diagrams import (MEASUREMENTS, STYLES, contexts_diagram,
    measurement_diagram, report_diagram, search_diagram, show_diagram)

REPOSITORY = "https://github.com/minojWittgen/boston-comp-bio-hack"
PAGES = {"intro": "Introduction", "research": "Research workspace", "references": "References"}
EXPERIENCES = {
    "Try the tutorial": "Guided examples",
    "Investigate with your key": "Ask your own question",
    "Connect through MCP": "Use in Claude (MCP)",
}


def open_workspace(experience="Try the tutorial"):
    # Navigation keeps the current conversation and credentials in this session.
    st.session_state.page = "research"
    st.session_state.experience = experience


def introduction():
    st.html(STYLES)
    st.title("Follow the evidence across contexts.")
    st.markdown("### A promising finding is a beginning. Where else does it hold?")
    st.write(
        "A result in cells raises a bigger question: does it hold in an organism, in patients, "
        "and across different measurements? That takes evidence with its context intact."
    )
    st.subheader("A paper summary is only the starting point")
    st.write("When an LLM workflow stops at finding and summarizing papers, the underlying measurements and experimental differences can stay out of view.")
    show_diagram(search_diagram())
    st.button("Explore a guided example", type="primary", on_click=open_workspace, width="content")
    st.caption("No sign-up or API key needed. The examples use clearly labeled synthetic data.")

    st.subheader("The same question, in different settings")
    show_diagram(contexts_diagram())

    st.subheader("More kinds of evidence. Different meanings.")
    selected = st.radio("Explore a measurement type", list(MEASUREMENTS), index=1,
                        horizontal=True, key="intro_measurement")
    show_diagram(measurement_diagram(selected))
    st.write(MEASUREMENTS[selected][3])

    st.subheader("A clearer answer—or a clearer next experiment")
    show_diagram(report_diagram())

    with st.container(border=True):
        st.markdown("**What you can try today**")
        st.write(
            "Explore two guided reports, search public gene sources with your own question, "
            "or use the same research tools inside Claude through MCP."
        )
        st.caption(
            "Available now: source findings, descriptive comparisons, traceable reports, and checks of "
            "separately supplied study observations. Further work: extracting study measurements, harmonizing "
            "datasets and running new numerical analyses."
        )
    st.button("Ask your own research question", on_click=open_workspace,
              args=("Investigate with your key",), width="content")
    st.caption("Website chat uses your Anthropic API key. You can also connect from Claude through MCP.")


def references():
    st.title("References and acknowledgments")
    st.write(
        "The ideas, data sources and project notes behind Cross-context. These references explain "
        "what shaped the workflow and where its evidence comes from."
    )
    st.subheader("Ideas that shaped the workflow")
    st.markdown(
        "**[AutoSciRub: Learning to Evaluate Before Improving](https://arxiv.org/abs/2608.31076)** · Research preprint, August 2026  \n"
        "We adapted its pattern of defining criteria before execution, checking results against them, and "
        "keeping follow-up bounded. Our coordinator implements its own checks for biological context and "
        "comparison metadata. It does not run the full AutoSciRub system. "
        f"[Implementation and attribution]({REPOSITORY}/blob/main/docs/plans/2026-09-22-coordinator-build.md) "
        "records the pinned source and the adaptation in our own words; no AutoSciRub implementation code "
        "was copied into that coordinator change."
    )
    st.markdown(
        "**[Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)** · December 2024  \n"
        "An architectural reference for simple, composable workflows, tool use and feedback. It informs "
        "how we organize the research steps."
    )
    st.markdown(
        "**[Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)** · January 2026  \n"
        "An evaluation reference for checking outcomes and execution traces. Our reports distinguish "
        "a finished search from having enough evidence to answer a biological question."
    )
    st.caption("These are methodological influences. They are not evidence that this prototype has been scientifically validated.")

    st.subheader("Public sources used by the evidence pipeline")
    st.write("Which sources appear in a report depends on the question and what the services return. Open a report’s Sources tab to inspect the actual records and links.")
    st.markdown("""
| Source | What it contributes | How to read it |
| --- | --- | --- |
| [MyGene.info](https://mygene.info/) | Gene names and identifiers | Helps locate the intended gene. |
| [Ensembl](https://www.ensembl.org/) | Related genes across species | Sequence similarity helps with mapping; it is not an experimental replication. |
| [GTEx](https://gtexportal.org/home/) | Gene-expression summaries across human tissues | Reference expression is not a disease-specific patient comparison. |
| [Human Protein Atlas](https://www.proteinatlas.org/) | Cell-line, protein-location and cancer-cohort annotations | Summaries do not supply individual patient measurements or sample identities. |
| [DepMap](https://depmap.org/portal/), accessed through Open Targets | Cell-line expression and CRISPR gene-effect summaries | Perturbation effects in cell lines do not establish effects in patients. |
| [IMPC](https://www.mousephenotype.org/) | Mouse phenotypes associated with gene disruption | Phenotypes add context; they do not substitute for a requested RNA or protein measurement. |
| [Open Targets](https://platform.opentargets.org/) | Gene–disease associations and source annotations | An association is a research lead, not proof of a treatment effect. |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov/) | Publication searches and article identifiers | Search matches still need study-level review and extraction. |
| [Reactome](https://reactome.org/) | Pathway definitions and participants in the pathway pipeline | Membership does not measure pathway activity; inferred events remain labeled. |
""")
    st.caption(
        "Several services can expose the same underlying study. More portals or returned rows do not "
        "automatically mean more independent evidence. Each report preserves available source information; "
        "researcher review is still needed to establish study quality and independence."
    )
    st.markdown(f"[How the data pipeline works]({REPOSITORY}/blob/main/data_pipeline/PIPELINE.md) · "
                f"[Source descriptions and limitations]({REPOSITORY}/blob/main/data_pipeline/tools.md)")

    with st.expander("Related systems and tools we reviewed"):
        st.write("The design document also surveys possible building blocks. Listing them here does not mean they are integrated into this demo.")
        st.markdown(
            "[Biomni](https://github.com/snap-stanford/Biomni) and "
            "[ToolUniverse](https://github.com/mims-harvard/ToolUniverse) are related biomedical tool and agent systems. "
            "[Open Targets MCP](https://github.com/opentargets/platform-mcp) was reviewed as a way for agents to query biological resources. "
            "Our current pipeline queries source APIs through its own adapters."
        )
        st.markdown(f"The [full design and candidate inventory]({REPOSITORY}/blob/main/cross-context-biology-agent.md) "
                    "also discusses dataset access, single-cell analysis and reusable scientific skills as future options.")

    st.subheader("Follow the project from idea to implementation")
    st.markdown(f"""
- [Scientific rationale and broader design]({REPOSITORY}/blob/main/cross-context-biology-agent.md) — the research goal, evidence dimensions and proposed extensions.
- [Current research workflow]({REPOSITORY}/blob/main/coordinator/README.md) — what the coordinator implements and what its checks mean.
- [Frontend and backend integration]({REPOSITORY}/blob/main/docs/frontend-integration.md) — how chat, reports and the shared service connect.
- [Use the tools through MCP]({REPOSITORY}/blob/main/docs/mcp.md) — connection instructions for Claude and other MCP clients.
- [Demo story and walkthrough]({REPOSITORY}/blob/main/docs/demo-story.md) — a short presentation guide and the scope of this demo.
- [Run the project yourself]({REPOSITORY}#run-the-integrated-app-locally) — setup, tests and deployment instructions.
""")
    st.caption("The design document describes the broader ambition. The implementation guides describe what is available in this prototype.")
    st.button("Explore a guided example", type="primary", on_click=open_workspace, width="content")
