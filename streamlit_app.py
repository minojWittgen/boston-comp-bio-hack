"""Research chat for the team's canonical investigation coordinator."""
import os
import re

import requests
import streamlit as st
from pydantic import ValidationError

from coordinator.jobs import TERMINAL
from research_app.client import InvestigationClient
from research_app.presentation import assistant_summary, STAGES
from research_app.report_ui import show_report
from research_app.tutorials import tutorial

st.set_page_config(page_title="Cross-context · Research chat", page_icon="◈", layout="wide")
st.markdown("""<style>
.block-container {max-width: 1150px; padding-top: 4rem;}
h1 {font-family: Georgia, serif; font-weight: 500 !important; letter-spacing: -1px;}
[data-testid="stSidebar"] {border-right: 1px solid #e1e5dc;}
.eyebrow {color: #527064; text-transform: uppercase; font-size: .72rem; letter-spacing: .18em;}
[data-testid="stMetricValue"] {font-size: 1.4rem; white-space: normal;}
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

# Reopen a stored report without repeating collection or paid model calls.
requested_report = st.query_params.get("report", "")
if re.fullmatch(r"[a-f0-9]{32}", requested_report) and st.session_state.get("opened_report") != requested_report:
    clear_conversation()
    st.session_state.opened_report = requested_report
    st.session_state.run_id = requested_report
    st.session_state.experience = "Investigate with your key"


def submit(prompt):
    try:
        parent = st.session_state.get("run_id")
        with st.spinner("Framing your question with your model account…"):
            result = client.chat(prompt, parent,
                                 api_key=st.session_state.get("visitor_api_key", ""),
                                 model=st.session_state.get("visitor_model", ""))
        st.session_state.setdefault("messages", []).append({"role": "user", "content": prompt})
        st.session_state.run_id = result["run_id"]
        st.session_state.opened_report = result["run_id"]
        st.query_params["report"] = result["run_id"]
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
            st.query_params.pop("report", None)
            st.session_state.pop("opened_report", None)
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



if experience == "Try the tutorial":
    st.subheader("See an investigation from question to report")
    st.write("These are synthetic teaching cases. They show how the coordinator preserves a research question, checks evidence across contexts, and reports disagreement or missing evidence.")
    case = st.radio("Tutorial case", ["Disagreement across contexts", "Missing patient evidence"], horizontal=True)
    name = "cross-context-conflict" if case == "Disagreement across contexts" else "missing-evidence"
    state = tutorial(name)
    with st.expander("Walk through this case", expanded=True):
        st.markdown("**1 · Research question**")
        st.write(state.request.question)
        st.markdown("**2 · Review the question** — open What we needed to answer to see the species, contexts and measurements being requested.")
        st.markdown("**3 · Inspect sources** — open Sources to see study observations, database summaries, source links and sample identifiers.")
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
        st.info("You can read saved reports without an API key. To ask a new question here, enter your Anthropic API key and model ID in the sidebar. The tutorial and MCP are also available without a separate API key.")
    st.caption("Live investigations retrieve and explain published database findings for the genes in your question, compare their species and research contexts, and report uncertainties and next steps. Individual patient comparisons are only possible when the sources provide matched patient data.")
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
                    if not st.session_state.get("messages"):
                        st.session_state.messages = [{"role": "user", "content": state.request.question}]
                    if state.status in TERMINAL:
                        st.session_state.setdefault("messages", []).append({"role": "assistant", "content": assistant_summary(state)})
                        st.rerun()
            except (requests.RequestException, ValidationError):
                st.error("Could not read this investigation. Check the service connection or start a new conversation.")
                return
            messages = st.session_state.get("messages", [])
            if state.status in TERMINAL and messages and messages[-1]["role"] == "assistant":
                messages[-1]["content"] = assistant_summary(state)
            for message in messages:
                with st.chat_message(message["role"]):
                    st.write(message["content"])
            if state.status not in TERMINAL:
                st.info(STAGES.get(state.stage, "Searching and reviewing evidence") + "…")
            show_report(state)
            if state.status in TERMINAL:
                st.link_button("Reopen this saved report", f"?report={state.run_id}")
        show_conversation()

    snapshot = st.session_state.get("run_snapshot")
    pending = "run_id" in st.session_state and (not snapshot or snapshot.status not in TERMINAL)
    if prompt := st.chat_input("Ask a research question or clarify the scope…" if model_ready else "Add your key and model in the sidebar to chat…",
                               disabled=pending or not model_ready, max_chars=4000):
        if len(prompt.strip()) < 5:
            st.info("Please add a little more detail to your message.")
        else:
            submit(prompt.strip())
