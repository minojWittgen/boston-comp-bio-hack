"""Research chat for the team's canonical investigation coordinator."""
import hmac
import os

import requests
import streamlit as st
from pydantic import ValidationError

from coordinator.jobs import TERMINAL
from research_app.client import InvestigationClient
from research_app.presentation import assistant_summary, context_coverage, is_synthetic

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


def clear_conversation():
    for key in ("run_id", "run_snapshot", "messages", "demo_run"):
        st.session_state.pop(key, None)


def clear_model_key():
    st.session_state.visitor_api_key = ""


if st.session_state.get("coordinator_ui_version") != 2:
    clear_conversation()
    st.session_state.coordinator_ui_version = 2

api_url = setting("INVESTIGATION_API_URL", "http://127.0.0.1:8000")
client = InvestigationClient(api_url, access_token)


def submit(prompt=None, demo=None):
    try:
        if demo:
            result = client.demo(demo)
            prompt = "Show the synthetic missing-evidence example." if demo == "missing-evidence" else "Show the synthetic cross-context disagreement example."
        else:
            parent = None if st.session_state.get("demo_run") else st.session_state.get("run_id")
            with st.spinner("Framing your question with your model account…"):
                result = client.chat(prompt, parent,
                                     api_key=st.session_state.get("visitor_api_key", ""),
                                     model=st.session_state.get("visitor_model", ""))
        st.session_state.setdefault("messages", []).append({"role": "user", "content": prompt})
        st.session_state.run_id = result["run_id"]
        st.session_state.demo_run = bool(demo)
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


with st.sidebar:
    st.markdown("### ◈ Cross-context")
    st.caption("BIOLOGICAL INVESTIGATIONS")
    st.divider()
    st.write("One question. Every context.")
    st.caption("In vitro · In vivo · Patients")
    st.markdown("**Model settings**")
    st.text_input("Your Anthropic API key", type="password", key="visitor_api_key",
                  placeholder="sk-ant-…", help="Used only for your chat planning calls. Never included in investigation downloads.")
    st.text_input("Anthropic model ID", key="visitor_model", placeholder="e.g. claude-sonnet-4-6",
                  help="Enter a model available to your Anthropic API account.")
    st.caption("Chat uses your Anthropic account and credits. Your key stays in this browser session's server memory and is sent to Anthropic for planning. It is not saved in investigations.")
    st.button("Clear API key", on_click=clear_model_key, width="stretch",
              disabled=not st.session_state.get("visitor_api_key"))
    st.divider()
    if st.button("New conversation", width="stretch"):
        clear_conversation()
        st.rerun()
    st.markdown("**Explore the workflow**")
    for name, label in [("cross-context-conflict", "Try a disagreement example"), ("missing-evidence", "Try a missing-evidence example")]:
        if st.button(label, width="stretch", disabled="run_id" in st.session_state):
            submit(demo=name)
    st.caption("Both examples use clearly labeled synthetic fixtures. No model key is needed.")
    with st.expander("Connection"):
        st.caption(f"Research service: {api_url}")
        st.caption("Frontend and MCP use the team's investigation coordinator.")
    st.divider()
    st.caption("Research prototype. Evidence checks evaluate declared scope and comparability; they do not independently validate source data or establish clinical efficacy.")

st.markdown('<div class="eyebrow">Boston computational biology hackathon</div>', unsafe_allow_html=True)
st.title("Follow the evidence across contexts.")
st.write("Ask a research question. Inspect the plan, the evidence, and the comparisons that remain unresolved.")

model_ready = bool(st.session_state.get("visitor_api_key", "").strip() and st.session_state.get("visitor_model", "").strip())
if model_ready:
    st.caption("Your model settings are entered. They will be checked when you send a question.")
else:
    st.info("To chat, add your Anthropic API key and model ID in the sidebar. You can try the synthetic examples or use MCP without a separate model key.")

with st.expander("Use this through MCP · no separate model API key"):
    st.write("Connect your MCP-compatible assistant to the investigation service. Your assistant turns the research question into explicit criteria; our coordinator collects evidence, checks comparisons, and returns a traceable report.")
    st.code(api_url.rstrip("/") + "/mcp/", language=None)
    st.markdown("1. Add this Streamable HTTP endpoint in a client that supports custom servers and bearer authentication.\n2. Supply the team access code as the bearer token when required.\n3. Ask your assistant to define the criteria, call `start_investigation`, and poll `get_investigation`.")
    st.caption("Our MCP tools make no model API calls. Your assistant's subscription or usage charges still apply, and server hosting and evidence collection have costs. Keep API keys out of tool arguments and chat messages.")
    st.markdown("[MCP setup and example](https://github.com/minojWittgen/boston-comp-bio-hack/blob/main/docs/mcp.md)")


def show_report(state):
    if is_synthetic(state):
        st.warning("Synthetic demonstration · these observations are fabricated, not biological findings.")
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
