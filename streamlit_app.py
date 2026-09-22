"""Research chat for the team's canonical investigation coordinator."""
import os

import requests
import streamlit as st
from pydantic import ValidationError

from coordinator.jobs import TERMINAL
from research_app.client import InvestigationClient
from research_app.presentation import assistant_summary, context_coverage, is_synthetic
from research_app.tutorials import tutorial

st.set_page_config(page_title="Cross-context · Research chat", page_icon="◈", layout="wide")
st.markdown("""<style>
.block-container {max-width: 1150px; padding-top: 4rem;}
h1 {font-family: Georgia, serif; font-weight: 500 !important; letter-spacing: -1px;}
[data-testid="stSidebar"] {border-right: 1px solid #e1e5dc;}
.eyebrow {color: #527064; text-transform: uppercase; font-size: .72rem; letter-spacing: .18em;}
</style>""", unsafe_allow_html=True)


def setting(name, default=""):
    if os.environ.get(name):
        return os.environ[name]
    try:
        return str(st.secrets.get(name, default))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return default


access_token = setting("COORDINATOR_API_TOKEN") or setting("INVESTIGATION_API_TOKEN")


def clear_conversation():
    for key in ("run_id", "run_snapshot", "messages", "demo_run"):
        st.session_state.pop(key, None)


def clear_model_key():
    st.session_state.visitor_api_key = ""


# Detach these session values from Streamlit's cleanup of hidden widgets.
# They survive view switches and remain per-session, never cached or persisted.
for name in ("visitor_api_key", "visitor_model"):
    if name in st.session_state:
        st.session_state[name] = st.session_state[name]


if st.session_state.get("coordinator_ui_version") != 3:
    clear_conversation()
    st.session_state.coordinator_ui_version = 3

api_url = setting("INVESTIGATION_API_URL", "http://127.0.0.1:8000")
client = InvestigationClient(api_url, access_token)


def submit(prompt):
    try:
        parent = st.session_state.get("run_id")
        with st.spinner("Framing your question with your model account…"):
            result = client.chat(prompt, parent,
                                 api_key=st.session_state.get("visitor_api_key", ""),
                                 model=st.session_state.get("visitor_model", ""))
        st.session_state.setdefault("messages", []).append({"role": "user", "content": prompt})
        st.session_state.run_id = result["run_id"]
        st.session_state.pop("run_snapshot", None)
        st.rerun()
    except (ValueError, requests.RequestException) as exc:
        detail = "Check the research-service connection and try again."
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            try:
                body = exc.response.json().get("detail")
                if isinstance(body, str):
                    detail = body
            except ValueError:
                pass
        st.error(f"Could not start the investigation. {detail}")


st.markdown('<div class="eyebrow">Boston computational biology hackathon</div>', unsafe_allow_html=True)
st.title("Follow the evidence across contexts.")
st.write("Explore a complete example, ask your own question, or bring this research workflow into Claude through MCP.")
experience = st.radio("Choose how to explore", ["Try the tutorial", "Investigate with your key", "Connect through MCP"],
                      horizontal=True, key="experience")

with st.sidebar:
    st.markdown("### ◈ Cross-context")
    st.caption("BIOLOGICAL INVESTIGATIONS")
    st.divider()
    st.write("One question. Every context.")
    st.caption("In vitro · In vivo · Patients")
    if experience == "Investigate with your key":
        st.session_state.setdefault("visitor_model", "claude-opus-5-5")
        st.markdown("**Model settings · website chat only**")
        st.text_input("Your Anthropic API key", type="password", key="visitor_api_key",
                      placeholder="sk-ant-…", help="Used only for your chat planning calls. Not saved in investigation downloads.")
        st.text_input("Anthropic model ID", key="visitor_model", placeholder="e.g. claude-opus-5-5")
        st.caption("Website chat uses your Anthropic API account and credits. Settings stay in this session when you switch views. Reloading or closing the app can clear them. Your key is not saved in investigations.")
        st.button("Clear API key", on_click=clear_model_key, width="stretch",
                  disabled=not st.session_state.get("visitor_api_key"))
        if st.button("New conversation", width="stretch"):
            clear_conversation()
            st.rerun()
    elif experience == "Try the tutorial":
        st.markdown("**Start here. No setup needed.**")
        st.write("Inspect the research plan, context comparisons, evidence and final report using two guided cases.")
        st.caption("Tutorials use labeled synthetic data. No API key, access code or live collection is needed.")
    else:
        st.markdown("**Your assistant, our research tools.**")
        st.write("Use Claude Code, Claude Desktop or Claude on the web. Claude supplies the model; our MCP supplies the investigation workflow.")
        st.caption("No separate Anthropic API key or team access code is needed for the hosted MCP.")
    st.divider()
    st.caption("Public research prototype. Use public data; anyone with an investigation ID can retrieve its results. Live investigations have a limited demo allowance. Tutorials remain available.")
    st.caption("Evidence checks evaluate declared scope and comparability; they do not independently validate source data or establish clinical efficacy.")

model_ready = bool(st.session_state.get("visitor_api_key", "").strip() and st.session_state.get("visitor_model", "").strip())


def show_report(state):
    if is_synthetic(state):
        st.warning("Synthetic demonstration · these observations are fabricated, not biological findings.")
    if state.plan:
        st.markdown("**Investigated genes:** " + ", ".join(state.plan.genes))
    if state.evidence:
        background = sum(r.level == "background" for r in state.evidence.records)
        observations = sum(r.level == "observation" for r in state.evidence.records)
        st.caption(f"Evidence retrieved · {background} background references · {observations} declared observations · {state.evidence.package_count} source packages")
        if background and not observations and state.status in TERMINAL and not is_synthetic(state):
            st.info("Live sources returned background references. The current pipeline does not yet supply the experimental observations needed for these comparisons. Open Evidence to inspect the retrieved sources; missing observations remain explicit gaps.")
    a, b = st.columns(2)
    a.metric("Execution", state.status.replace("_", " ").title())
    b.metric("Evidence conclusion", state.assessment.conclusion.replace("_", " ").title() if state.assessment else "Not assessed")
    st.caption("Execution describes whether the investigation finished. The evidence conclusion describes the comparisons.")
    for col, row in zip(st.columns(3), context_coverage(state)):
        with col.container(border=True):
            st.markdown(f"**{row['label']}**")
            st.write(row["detail"])
    findings, evidence, plan, activity = st.tabs(["Comparisons & gaps", "Evidence", "Research plan", "Activity"])
    with findings:
        if state.assessment:
            for comparison in state.assessment.comparisons:
                with st.expander(f"{comparison.id.replace('_', ' ')} · {comparison.conclusion.replace('_', ' ')}"):
                    st.write(comparison.detail)
                    if comparison.evidence_ids:
                        st.caption("Evidence: " + ", ".join(comparison.evidence_ids))
            if not state.assessment.comparisons:
                st.info("No biological comparison was specified. Evidence coverage alone is not validation.")
            for check in state.assessment.checks:
                with st.expander(f"{'✓' if check.passed else '○'} {check.id.replace('_', ' ')} · {'met' if check.passed else 'unmet'}"):
                    st.write(check.detail)
                    st.caption("Required" if check.required else "Optional")
            gaps = (state.evidence.gaps if state.evidence else []) + state.assessment.gaps
            with st.expander(f"Gaps and interpretation limits ({len(gaps)})", expanded=state.status == "partial"):
                for gap in gaps:
                    st.markdown(f"**{gap.code.replace('_', ' ')}**")
                    st.write(gap.detail)
        elif state.status != "failed":
            st.caption("Comparisons appear after evidence checks finish.")
    with evidence:
        records = state.evidence.records if state.evidence else []
        for level, label in [("observation", "Declared observations"), ("background", "Background references")]:
            scoped = [r for r in records if r.level == level]
            st.markdown(f"**{label} · {len(scoped)}**")
            if scoped:
                columns = ("id", "source", "entity", "species", "host_species", "context", "modality", "endpoint", "direction", "study_id", "subject_id", "specimen_id", "timepoint")
                st.dataframe([{k: getattr(r, k) for k in columns} for r in scoped], hide_index=True, width="stretch")
                with st.expander(f"Inspect {label.lower()} and provenance"):
                    record = st.selectbox("Evidence record", scoped, format_func=lambda r: f"{r.id} · {r.source}", key=f"evidence-{state.run_id}-{level}")
                    st.write({k: v for k, v in record.model_dump().items() if k != "payload" and v is not None})
                    st.json(record.payload, expanded=False)
            else:
                st.caption("None supplied or retrieved.")
        st.caption("Background references do not fulfill observation requirements. Original packages remain in the downloadable investigation.")
    with plan:
        if state.plan:
            st.write(state.plan.question)
            if state.plan.assumptions:
                st.warning("The plan contains assumptions or proposed scope that need researcher review.")
                for assumption in state.plan.assumptions:
                    st.write(assumption)
            st.dataframe([r.model_dump() for r in state.plan.requirements], hide_index=True, width="stretch")
            if state.plan.pathway:
                st.write(f"Pathway: {state.plan.pathway.id} · {state.plan.pathway.source} · {state.plan.pathway.version}")
                st.caption("Versioned membership defines scope; it does not measure pathway activity.")
            for limitation in state.plan.claims_to_avoid:
                st.caption(limitation)
            st.caption("Clarify the question in chat to start a new investigation. This run's plan stays fixed.")
        else:
            st.caption("The research plan has not been produced yet.")
    with activity:
        st.caption(f"Investigation {state.run_id} · {state.attempts} collection attempts")
        for event in state.events:
            st.markdown(f"**{event['stage'].replace('_', ' ')}**")
            detail = {k: v for k, v in event.items() if k not in ("stage", "at")}
            if detail:
                st.write(detail)
            st.caption(event.get("at", ""))
        if state.plan_sha256:
            st.caption(f"Frozen plan: {state.plan_sha256}")
    if state.error:
        st.error(state.error)
    if state.report:
        st.download_button("Download Markdown report", state.report,
                           file_name=f"investigation-{state.run_id}.md", mime="text/markdown")
    st.download_button("Download evidence and full investigation", state.model_dump_json(indent=2),
                       file_name=f"investigation-{state.run_id}.json", mime="application/json")


if experience == "Try the tutorial":
    st.subheader("See an investigation from question to report")
    st.write("These are synthetic teaching cases. They show how the coordinator preserves a research question, checks evidence across contexts, and reports disagreement or missing evidence.")
    case = st.radio("Tutorial case", ["Disagreement across contexts", "Missing patient evidence"], horizontal=True)
    name = "cross-context-conflict" if case == "Disagreement across contexts" else "missing-evidence"
    state = tutorial(name)
    with st.expander("Walk through this case", expanded=True):
        st.markdown("**1 · Research question**")
        st.write(state.request.question)
        st.markdown("**2 · Fix the criteria** — open Research plan to see the required species, contexts and endpoints.")
        st.markdown("**3 · Inspect evidence** — open Evidence to distinguish declared observations from background references.")
        st.markdown("**4 · Read the conclusion** — completing the workflow can reveal conflicting evidence; missing evidence stays a gap.")
    show_report(state)

elif experience == "Connect through MCP":
    st.subheader("Use Cross-context inside Claude")
    st.write("Claude turns your question into explicit research criteria and calls our MCP tools. The same coordinator collects evidence, checks comparisons and returns a traceable report. You do not need an Anthropic API key for this path.")
    endpoint = setting("XCTX_MCP_URL", "https://minoj--xctx-research-api.modal.run/mcp/")
    st.markdown("**Claude Code · terminal**")
    st.code(f"claude mcp add --transport http cross-context-biology {endpoint}\nclaude mcp get cross-context-biology", language="bash")
    st.caption("Then open Claude Code and use /mcp to inspect the connection. This repository also includes .mcp.json; approve its connector when Claude Code asks.")
    st.markdown("**Claude app · Desktop or web**")
    st.write("Open Customize → Connectors → Add custom connector. Name it Cross-context biology, paste the URL below, then enable it in your conversation. No authentication or API key is required by this server. Organization accounts may need an owner to add it.")
    st.code(endpoint, language=None)
    st.markdown("**Try this first**")
    st.code("Use Cross-context biology to run the synthetic cross-context-conflict tutorial. Call start_investigation, then get_investigation, and explain why a complete investigation can have conflicting evidence.", language=None)
    st.markdown("**Then investigate your question**")
    st.write("Ask Claude to propose criteria from your research intent and review them with you before starting. It must not invent observations or validated comparison bases. The tools are start_investigation and get_investigation.")
    st.caption("Your Claude plan or client model charges still apply. Public live investigations have a limited hosting allowance; the tutorial works without live collection. The website chat is an optional alternative.")
    st.markdown("[Full setup guide](https://github.com/minojWittgen/boston-comp-bio-hack/blob/main/docs/mcp.md) · [Claude Code documentation](https://code.claude.com/docs/en/mcp) · [Claude connector documentation](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)")

else:
    if model_ready:
        st.caption("Your model settings are entered. They will be checked when you send a question.")
    else:
        st.info("Website chat is optional. Enter your Anthropic API key and model ID in the sidebar, or choose the tutorial or MCP to continue without a separate API key.")
    st.caption("Live investigations retrieve source references for the genes in your question. Unlike the synthetic tutorial, they do not come with prefilled experiment or patient observations, so an honest result may be partial / not assessable.")
    if "run_id" not in st.session_state:
        with st.chat_message("assistant"):
            st.write("What biological question are you investigating? Include the gene or target, the disease or tissue, and what you want to compare.")
            st.caption('For example: “Compare TYK2 RNA abundance in human cell cultures, mouse models and psoriasis patients.”')
    else:
        run_id = st.session_state.run_id

        @st.fragment(run_every="3s")
        def show_conversation():
            cached = st.session_state.get("run_snapshot")
            try:
                if cached and cached.run_id == run_id and cached.status in TERMINAL:
                    state = cached
                else:
                    state = client.get(run_id)
                    st.session_state.run_snapshot = state
                    if state.status in TERMINAL:
                        st.session_state.messages.append({"role": "assistant", "content": assistant_summary(state)})
                        st.rerun()
            except (requests.RequestException, ValidationError):
                st.error("Could not read this investigation. Check the service connection or start a new conversation.")
                return
            for message in st.session_state.get("messages", []):
                with st.chat_message(message["role"]):
                    st.write(message["content"])
            if state.status not in TERMINAL:
                st.info(state.stage.replace("_", " ").capitalize() + "…")
            show_report(state)
        show_conversation()

    snapshot = st.session_state.get("run_snapshot")
    pending = "run_id" in st.session_state and (not snapshot or snapshot.status not in TERMINAL)
    if prompt := st.chat_input("Ask a research question or clarify the scope…" if model_ready else "Add your key and model in the sidebar to chat…",
                               disabled=pending or not model_ready, max_chars=4000):
        if len(prompt.strip()) < 5:
            st.info("Please add a little more detail to your message.")
        else:
            submit(prompt.strip())
