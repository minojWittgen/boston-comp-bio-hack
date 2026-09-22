# Demo fixes and reproduction handoff — 2026-09-22

The website, HTTP API, and MCP share the team's coordinator. The tutorial uses
labeled synthetic observations; ordinary chat and MCP submissions retrieve live
pipeline references and never substitute tutorial data.

## What was broken and what changed

| Symptom | Verified cause | Change |
| --- | --- | --- |
| Key/model disappeared after switching to MCP or the tutorial | Streamlit removed the hidden widgets' session values | Preserve those values in the same session; Clear API key still clears them and other sessions remain isolated |
| Opus rejected the planning call before collection | Provider HTTP 400: forced `tool_choice: tool` is unsupported by the tested Opus model | One bounded call with automatic tool choice and strict tool inputs; validate the original contract afterward |
| TP53 sometimes failed plan validation | The generated mouse requirement used `Trp53 (mouse counterpart...)` instead of the declared `TP53` target | Specify stable queried target identity in the schema and prompt; keep species separate; reject aliases instead of silently rewriting intent |
| A valid key still produced a generic failure | Provider refusal, unavailable model, permission error, and timeout were not distinguished | Show safe cause-specific messages; no automatic retries or model changes |
| Server lacked sources already on main | The earlier `xctx-evidence` deployment lacked HPA/DepMap and even `build_pathway` | Redeploy the pipeline and integrate the team's subsequently merged HPA pathology/source adapters from main at `b2d557d` |
| Real results looked empty compared with the tutorial | Context cards counted fulfilled observation requirements, while retrieved references stayed background | Show investigated genes and retrieved reference/observation/package counts; explain partial results |

The demo's editable model default is `claude-opus-5-5`. This ID was returned by the
supplied demo account's Models API. Other accounts can enter another supported exact
ID. This is not an automatic fallback or a shared project model account.

## Live checks actually performed

| Check | Result | Investigation ID |
| --- | --- | --- |
| Opus chat: MLH1 / colorectal cancer, before pipeline redeployment | Plan accepted; 8 live background records; partial / not_assessable; no execution error | `eeb31d6bc0894f2e80b4138723a12383` |
| MCP: TYK2, MLH1, TP53, after first pipeline update | 3 packages; 10 background records per gene (30 total), including HPA and DepMap; no collection error | `8f54b96a787a4a718270e14093fa6382` |
| Opus chat: TP53 / breast cancer, after fixing target identity | Plan accepted; 10 live background records; partial / not_assessable; no execution error | `b0bcd93371324ecaab66980a72947133` |
| Final hosted browser: MLH1 / colorectal cancer, with current main pipeline | Opus plan accepted; 11 live background records including HPA pathology; report and Evidence tab visibly rendered; no execution error | `8f0a8c066be24a92918e7f3edd6fc07c` |
| Opus chat: TYK2 / psoriasis | Provider returned `stop_reason: refusal`, including on a captured direct SDK call; no job started | None |

These IDs refer to immutable results at the versions tested. The MCP test preceded
the team's final HPA pathology merge; it records the then-unknown optional sources as
background with unsupported-source gaps. The final deployment recognizes those
sources plus HPA pathology. Do not rewrite old results to make them look newer.

The final browser check also switched from chat to MCP and back with the same session
credentials, confirmed chat remained enabled, then successfully started the MLH1 run.
The Evidence tab displayed 11 background records and zero declared observations, with
working report/download controls. Credential retention and clearing are also covered
by the offline Streamlit tests. No credential value is in these artifacts or the repo.

The TYK2 refusal is distinct from gene support: live MCP retrieval returned TYK2
references. The app surfaces a provider refusal and stops; it does not switch models,
retry automatically, alter the user's question, or claim collection succeeded.

Background references, even patient-context cohort summaries, do not establish paired
patient observations or comparable cross-species experiments. `partial / not_assessable`
is an expected honest result when those observations are missing. These checks verify
software integration, not biological validity or clinical efficacy.

## Reproduce the website checks

1. Open <https://minoj--xctx-research-web.modal.run/> and inspect both tutorial cases.
   No credentials or live jobs are needed.
2. Select **Investigate with your key**, enter your own key, and check the model ID.
   Use the UI password field; do not paste credentials into research questions or MCP.
3. Switch to **Connect through MCP**, then back. Key and model should remain in that
   browser session. A new tab/session has no key; reloading or restarting the server
   can end a session. **Clear API key** disables chat and remains cleared after switching.
4. Start a new conversation and submit:

   ```text
   Compare MLH1 RNA abundance in human cell cultures, mouse models and colorectal cancer patients.
   ```

5. Repeat with **New conversation** and:

   ```text
   Compare TP53 RNA abundance in human cell cultures, mouse models and breast cancer patients.
   ```

6. Allow time for planning and source collection. Inspect **Evidence**, **Research plan**,
   **Activity**, and both downloads. Check source counts separately from criteria met.

Each live start uses the existing public allowance. Model calls use the visitor's API
credits. Hosting/source collection still uses the Modal owner's account. The default
allowance is 12 total starts through 2026-09-29 00:00 UTC; redeployment does not reset it.

## Reproduce MCP without a separate model API key

```bash
claude mcp add --transport http cross-context-biology https://minoj--xctx-research-api.modal.run/mcp/
claude mcp get cross-context-biology
```

Call `start_investigation` with explicit criteria and poll `get_investigation` every
three seconds. For the exact multi-gene source-availability check, use this tool argument:

```json
{
  "request": {
    "request": {
      "question": "Retrieve reference evidence for TYK2, MLH1 and TP53 and assess whether human in-vitro RNA abundance observations are available.",
      "genes": ["TYK2", "MLH1", "TP53"],
      "max_revisions": 0,
      "requirements": [
        {"id":"tyk2_rna","title":"TYK2 human cell RNA observations","entity":"TYK2","species":"homo_sapiens","context":"in_vitro","modality":"RNA","endpoint":"RNA abundance"},
        {"id":"mlh1_rna","title":"MLH1 human cell RNA observations","entity":"MLH1","species":"homo_sapiens","context":"in_vitro","modality":"RNA","endpoint":"RNA abundance"},
        {"id":"tp53_rna","title":"TP53 human cell RNA observations","entity":"TP53","species":"homo_sapiens","context":"in_vitro","modality":"RNA","endpoint":"RNA abundance"}
      ]
    }
  }
}
```

For a no-live-collection transport smoke check:

```bash
.venv/bin/python scripts/smoke_mcp.py https://minoj--xctx-research-api.modal.run/mcp/
```

## Reproduce setup and deployment

From the repository root (Python 3.11):

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests coordinator/tests data_pipeline/tests -q
.venv/bin/modal setup
```

The combined suite passed **165 tests and 40 subtests** after incorporating the team's
latest main changes. One existing Starlette/AnyIO deprecation warning remains. Tests
use fake model/provider responses and never consume the supplied live key.

Deploy the pipeline from its source directory so its module mounts resolve:

```bash
cd data_pipeline/evidence_pipeline
../../.venv/bin/modal deploy app.py
cd ../..
.venv/bin/modal deploy --strategy recreate modal_app.py
```

Wait for active investigations to finish before `recreate`: it restarts app containers,
and website sessions must reload. Rolling deployment can stall with an old Streamlit
WebSocket and the single-container cap. No shared Anthropic secret is attached.

Deployment names: `xctx-evidence` and `xctx-research`. Pipeline volume: `xctx-cache`.
Run state: `xctx-public-investigations`. Live allowance: `xctx-public-run-budget`.
Archived results: `xctx-investigation-artifacts`. Former private runs stay separate.

## References

- [Streamlit widget cleanup and session state](https://docs.streamlit.io/develop/concepts/architecture/widget-behavior)
- [Anthropic tool choice](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- [Anthropic strict outputs and SDK schema transformation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Chat contract](chat-and-contract.md) and [frontend integration](frontend-integration.md)

## Research report UI update

See [researcher-facing reports](researcher-report-ui.md) for the clearer labels, source links,
study/sample traceability, readable exports and saved-report links. The scientific result
and original data remain unchanged; a finished search can still have insufficient evidence.
