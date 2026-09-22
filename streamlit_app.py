"""Chat frontend. Intent extraction, contracts, model calls and tools live on the server."""
import hmac
import json
import os

import requests
import streamlit as st

from coordinator.models import TERMINAL
from research_app.client import InvestigationClient
from research_app.evidence import source_rows

st.set_page_config(page_title="Cross-context · Research chat", page_icon="◈", layout="wide")
st.markdown("""<style>
.block-container {max-width: 1100px; padding-top: 4rem;}
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


access_token = setting("INVESTIGATION_API_TOKEN")
if access_token and not st.session_state.get("authorized"):
    st.title("Cross-context research workspace")
    with st.form("access"):
        supplied = st.text_input("Team access code", type="password")
        submitted = st.form_submit_button("Open workspace")
    if submitted:
        if hmac.compare_digest(supplied, access_token):
            st.session_state.authorized = True
            st.rerun()
        st.error("The access code was not accepted.")
    st.stop()

api_url = setting("INVESTIGATION_API_URL", "http://127.0.0.1:8000")
client = InvestigationClient(api_url, access_token)


def submit(prompt, demo=False):
    try:
        started = client.chat(prompt, st.session_state.get("run_id"), demo=demo)
        st.session_state.run_id = started["id"]
        st.session_state.pop("run_snapshot", None)
        st.rerun()
    except requests.RequestException:
        st.error("The research service could not accept this message. Check the connection and try again.")


with st.sidebar:
    st.markdown("### ◈ Cross-context")
    st.caption("BIOLOGICAL INVESTIGATIONS")
    st.divider()
    st.write("One question. Every context.")
    st.caption("In vitro · In vivo · Patients")
    if st.button("New conversation", width="stretch"):
        st.session_state.pop("run_id", None)
        st.session_state.pop("run_snapshot", None)
        st.rerun()
    if st.button("Try synthetic investigation", width="stretch", disabled="run_id" in st.session_state):
        submit("Show me the synthetic investigation across all three contexts.", demo=True)
    st.caption("The example uses fabricated measurements to demonstrate the workflow.")
    with st.expander("Connection"):
        st.caption(f"Investigation API: {api_url}")
        st.caption("Chat and MCP use the same research service.")
    st.divider()
    st.caption("Research prototype. Conclusions remain conditional on the available evidence, methods and sample identities.")

st.markdown('<div class="eyebrow">Boston computational biology hackathon</div>', unsafe_allow_html=True)
st.title("Follow the evidence across contexts.")
st.write("Ask a research question. We’ll frame the investigation, collect evidence and show what remains unresolved.")


def show_report(state):
    report = state.get("report") or {}
    for error in state["errors"]:
        st.error(f"{error['stage']}: {error['reason']}")
    if not report or state["status"] == "needs_input":
        return
    if "synthetic_fixture" in report.get("origins", []):
        st.warning("Synthetic demonstration · these measurements are fabricated, not real biological evidence.")
    if report.get("contexts"):
        for column, (name, context) in zip(st.columns(3), report["contexts"].items()):
            with column.container(border=True):
                st.markdown(f"**{name.replace('_', ' ').title()}**")
                st.write(context["finding"].replace("_", " "))
    findings, evidence = st.tabs(["Findings", "Evidence"])
    with findings:
        for finding in report.get("criteria", []):
            with st.expander(f"{finding['criterion_id']} · {finding['finding']}"):
                st.write(finding["scope"])
                for check in finding["checks"]:
                    st.write(f"{'✓' if check['passed'] else '○'} {check['detail']}")
                for calc in finding["calculations"]:
                    st.markdown(f"**{calc['modality']}** · {calc['n_pairs']} biological pairs")
                    st.write(f"Mean log₂ fold change: {calc['mean_log2_fold_change']:.3f}; {calc['confidence_level']:.0%} interval: {calc['interval'][0]:.3f} to {calc['interval'][1]:.3f}")
                    st.dataframe(calc["individuals"], hide_index=True, width="stretch")
        for note in (report.get("interpretation") or {}).get("reference_notes", []):
            st.write(note["note"])
            st.caption(f"Source: {note['source']} · package {note['package_run_id']}")
        if report.get("phase") == "exploration":
            st.info("Background evidence collected for framing. Numerical validation still needs study measurements and agreed comparison rules.")
        for step in report.get("next_steps", []):
            st.write(step)
        with st.expander("Scope and limitations"):
            for limitation in report.get("limitations", []):
                st.write(limitation)
            st.caption(report.get("interpretation_status", ""))
    with evidence:
        if report.get("observations"):
            st.dataframe(report["observations"], hide_index=True, width="stretch")
        for package in state["reference_packages"]:
            st.markdown("**Retrieved background evidence**")
            st.dataframe(source_rows(package), hide_index=True, width="stretch")
        if not report.get("observations") and not state["reference_packages"]:
            st.caption("No evidence collected yet.")
    with st.expander("Investigation activity"):
        for event in state["events"]:
            st.write(event["detail"])
        st.caption(f"{state['usage']['tool_calls']} tool calls · {state['usage']['model_calls']} model calls")
    st.download_button("Download investigation and evidence", json.dumps(state, indent=2),
                       file_name=f"investigation-{state['id']}.json", mime="application/json")


if "run_id" not in st.session_state:
    with st.chat_message("assistant"):
        st.write("What biological question are you investigating? Include the gene or target, the disease or tissue, and what you want to compare if you know it.")
        st.caption('For example: “What evidence connects TYK2 to psoriasis across cell experiments, animal models and patients?”')
else:
    run_id = st.session_state.run_id

    @st.fragment(run_every="3s")
    def show_conversation():
        cached = st.session_state.get("run_snapshot")
        try:
            if cached and cached["id"] == run_id and cached["status"] in TERMINAL:
                state = cached
            else:
                state = client.get(run_id)
                st.session_state.run_snapshot = state
                if state["status"] in TERMINAL:
                    st.rerun()  # Re-enable chat input after the background job stops.
        except requests.RequestException:
            st.error("Could not refresh this investigation. The background job may still be running.")
            if st.button("Retry connection"):
                st.rerun()
            return
        for message in state.get("chat", {}).get("messages", []):
            with st.chat_message(message["role"]):
                st.write(message["content"])
        if state["status"] not in TERMINAL:
            stages = {"understanding_intent": "Framing your question", "collecting": "Collecting evidence",
                      "checking": "Checking comparisons", "comparison": "Comparing contexts",
                      "planning": "Choosing the next research step"}
            st.info(stages.get(state["stage"], "Working on your investigation") + "…")
        else:
            st.caption(f"Investigation {run_id[:8]} · {state['status'].replace('_', ' ')}")
        show_report(state)
    show_conversation()

snapshot = st.session_state.get("run_snapshot")
pending = "run_id" in st.session_state and (not snapshot or snapshot["status"] not in TERMINAL)
if prompt := st.chat_input("Ask a research question or reply…", disabled=pending, max_chars=4000):
    if len(prompt.strip()) < 3:
        st.info("Please add a little more detail to your message.")
    else:
        submit(prompt.strip())
