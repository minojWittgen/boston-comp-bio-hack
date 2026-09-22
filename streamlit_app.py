"""Thin frontend for the shared investigation API. All research runs on the backend."""
import json
import hmac
import os
from pathlib import Path

import requests
import streamlit as st

from coordinator.models import InvestigationRequest, TERMINAL
from research_app.client import InvestigationClient
from research_app.evidence import source_rows

st.set_page_config(page_title="Cross-context · Investigations", page_icon="◈", layout="wide")
st.markdown("""<style>
.block-container {max-width: 1400px; padding-top: 4rem;}
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


with st.sidebar:
    st.markdown("### ◈ Cross-context")
    st.caption("BIOLOGICAL INVESTIGATIONS")
    st.divider()
    st.write("One claim. Every context.")
    st.caption("Fixed criteria · traceable evidence · explicit uncertainty")
    with st.expander("Connection"):
        api_url = setting("INVESTIGATION_API_URL", "http://127.0.0.1:8000")
        st.caption(f"Investigation API: {api_url}")
        st.caption("The frontend and MCP call the same coordinator.")
    if st.button("New investigation", width="stretch"):
        st.session_state.pop("run_id", None)
        st.session_state.pop("run_snapshot", None)
        st.rerun()
    st.divider()
    st.caption("Research prototype. Supported findings are conditional on the stated methods and supplied samples.")

client = InvestigationClient(api_url, setting("INVESTIGATION_API_TOKEN"))
st.markdown('<div class="eyebrow">Boston computational biology hackathon</div>', unsafe_allow_html=True)
st.title("Follow the evidence across contexts.")
st.write("Define a biological claim. Run the investigation. Inspect what supports it—and what remains unresolved.")

if "run_id" not in st.session_state:
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        st.subheader("Start an investigation")
        mode = st.radio("Starting point", ["Research question", "Synthetic development example"], horizontal=True)
        fixture = json.loads((Path(__file__).parent / "examples/development-investigation.json").read_text())
        if mode == "Synthetic development example":
            st.warning("Synthetic measurements for demonstrating workflow behavior. This is not a biological finding or a held-out evaluation.")
            base = fixture
        else:
            base = {"intent": "", "genes": [], "disease": "", "criteria": [], "criteria_confirmed": False,
                    "observations": [], "retrieve_reference": True}
        intent = st.text_area("Research intent", value=base["intent"], height=110, key=f"intent-{mode}")
        uploaded = st.file_uploader("Load an investigation contract (optional)", type=["json"])
        if uploaded:
            try:
                base = json.loads(uploaded.getvalue())
            except ValueError:
                st.error("The uploaded file is not valid JSON.")
                st.stop()
        with st.expander("Scientific criteria and processed measurements", expanded=bool(uploaded)):
            st.caption("Confirm study IDs, assays, species mappings, paired samples, thresholds and limits before execution. Missing criteria produce a needs_input result.")
            raw = st.text_area("Investigation contract JSON", value=json.dumps(base, indent=2), height=260,
                               key=f"contract-{mode}-{uploaded.file_id if uploaded else 'none'}")
            confirmed = st.checkbox("I confirm the scientific criteria in this contract", key=f"confirmed-{mode}")
        if st.button("Start investigation", type="primary", width="stretch"):
            try:
                payload = json.loads(raw)
                if intent.strip() and not uploaded:
                    payload["intent"] = intent.strip()
                payload["criteria_confirmed"] = confirmed
                request = InvestigationRequest.model_validate(payload)
                started = client.start(request.model_dump(mode="json"))
                st.session_state.run_id = started["id"]
                st.rerun()
            except (ValueError, requests.RequestException) as exc:
                st.error(f"Could not start: {exc}")
    with right:
        st.subheader("One investigation, three contexts")
        for name, description in [
            ("In vitro", "Cultures and organoids, with independent biological replicates."),
            ("In vivo", "Animal measurements, measured-cell species, host species and reviewed mappings."),
            ("Patients", "Individual subjects, matched specimens, time points and measurement differences."),
        ]:
            with st.container(border=True):
                st.markdown(f"**{name}**")
                st.write(description)
        st.caption("Missing contexts stay visible. Retrieval records supply background; numerical comparisons need suitable measurements.")
else:
    run_id = st.session_state.run_id
    st.caption(f"Investigation {run_id}")

    @st.fragment(run_every="3s")
    def show_investigation():
        cached = st.session_state.get("run_snapshot")
        try:
            if cached and cached["id"] == run_id and cached["status"] in TERMINAL:
                state = cached
            else:
                state = client.get(run_id)
                st.session_state.run_snapshot = state
        except requests.RequestException as exc:
            st.error(f"Could not read this investigation: {exc}")
            return
        st.subheader(state["request"]["intent"])
        st.write(f"**Execution:** {state['status']} · **Stage:** {state['stage']}")
        if state["status"] not in TERMINAL:
            st.info("The coordinator is working. Progress refreshes automatically; the job continues independently of this page.")
        report = state.get("report") or {}
        if state["status"] == "needs_input":
            st.info(report["required_input"])
        if "synthetic_fixture" in report.get("origins", []):
            st.warning("Synthetic development data · these results demonstrate software behavior, not real biological evidence.")
        if report.get("contexts"):
            for column, (name, context) in zip(st.columns(3), report["contexts"].items()):
                with column.container(border=True):
                    st.markdown(f"**{name.replace('_', ' ').title()}**")
                    st.write(context["finding"].replace("_", " "))
        results, evidence, trace, contract = st.tabs(["Findings", "Evidence", "Execution trace", "Fixed criteria"])
        with results:
            interpretation = report.get("interpretation")
            if interpretation:
                st.write(interpretation["summary"])
                st.caption("Model-assisted interpretation; structured findings and cited IDs were checked. Scientific review remains necessary.")
                for note in interpretation.get("reference_notes", []):
                    st.write(note["note"])
                    st.caption(f"Source: {note['source']} · package {note['package_run_id']}")
            for finding in report.get("criteria", []):
                with st.expander(f"{finding['criterion_id']} · {finding['finding']}", expanded=True):
                    st.write(finding["scope"])
                    for check in finding["checks"]:
                        st.write(f"{'✓' if check['passed'] else '○'} {check['detail']}")
                    for calc in finding["calculations"]:
                        st.markdown(f"**{calc['modality']}** · {calc['n_pairs']} biological pairs")
                        st.write(f"Mean log₂ fold change: {calc['mean_log2_fold_change']:.3f}; {calc['confidence_level']:.0%} interval: {calc['interval'][0]:.3f} to {calc['interval'][1]:.3f}")
                        st.dataframe(calc["individuals"], hide_index=True, width="stretch")
            for message in report.get("limitations", []):
                st.caption(message)
            for error in state["errors"]:
                st.error(f"{error['stage']}: {error['reason']}")
        with evidence:
            if report.get("observations"):
                st.dataframe(report["observations"], hide_index=True, width="stretch")
            for package in state["reference_packages"]:
                st.markdown("**Retrieved background evidence**")
                st.dataframe(source_rows(package), hide_index=True, width="stretch")
                st.json(package, expanded=False)
            if not report.get("observations") and not state["reference_packages"]:
                st.caption("No evidence collected yet.")
        with trace:
            for event in state["events"]:
                st.write(f"**{event['stage']} / {event['action']}** — {event['detail']}")
            st.json(state["usage"])
        with contract:
            st.caption(f"Immutable contract SHA-256: {state['contract_hash']}")
            st.json(state["request"], expanded=False)
        st.download_button("Download investigation and evidence", json.dumps(state, indent=2),
                           file_name=f"investigation-{run_id}.json", mime="application/json")
    show_investigation()
