"""Current architecture, distilled from the integration and coordinator guides."""

STYLES = """<style>
.xctx-figure .architecture-node {text-align:left;padding:18px 16px;}
.xctx-figure .architecture-node strong {font-size:17px;margin:0;}
.xctx-figure .architecture-node small {letter-spacing:.04em;margin-bottom:10px;}
.xctx-figure .architecture-entry + .architecture-entry {border-top:1px solid #d6dfd3;margin-top:15px;padding-top:15px;}
.xctx-figure .architecture-core {background:#e9f0e5;border-color:#b5c9b9;}
.xctx-figure .architecture-output {margin-top:20px;}
.xctx-figure .architecture-output p {font-size:12px;font-weight:400;color:#edf3ed;}
.xctx-figure .workflow-step strong {display:block;margin-bottom:6px;}
.xctx-figure .workflow-step span {font-size:12px;}
.xctx-figure .workflow-note {margin-top:16px;padding:12px 15px;border:1px dashed #d9c9aa;
  border-radius:8px;background:#f5efe4;color:#735c38;font-size:12px;line-height:1.5;}
@media(max-width:700px) {
  .xctx-figure .research-workflow {flex-direction:column;gap:20px;}
  .xctx-figure .research-workflow .flow-step:not(:last-child)::after {content:'↓';right:calc(50% - 5px);top:auto;bottom:-20px;font-size:17px;}
}
</style>"""


def architecture_diagram():
    return """<figure class="xctx-figure" aria-label="Website chat and Claude MCP share a coordinator connected to the evidence pipeline">
<div class="fig-kicker">01 / ONE RESEARCH SYSTEM, TWO WAYS IN</div>
<div class="context-bridge">
  <div class="context-node architecture-node">
    <small>CHOOSE YOUR INTERFACE</small>
    <div class="architecture-entry"><strong>Website chat</strong><p>Streamlit + API<br>Your question → model-assisted research plan, using your key.</p></div>
    <div class="architecture-entry"><strong>Claude via MCP</strong><p>Claude app or Code<br>Your assistant supplies the research scope through MCP tools.</p></div>
  </div>
  <div class="bridge-arrow" aria-hidden="true">↔</div>
  <div class="context-node architecture-node architecture-core">
    <small>SHARED SERVICE · MODAL</small><strong>Investigation coordinator</strong>
    <p>Keep the research scope.<br>Request source evidence.<br>Explain findings and differences.<br>Record gaps and next steps.</p>
    <div class="context-tags"><span>API + MCP adapter</span><span>Background jobs</span></div>
  </div>
  <div class="bridge-arrow" aria-hidden="true">↔</div>
  <div class="context-node architecture-node">
    <small>EVIDENCE PIPELINE · MODAL</small><strong>Public data → evidence packages</strong>
    <p>Retrieve gene information from GTEx, HPA, DepMap, IMPC, Ensembl, Open Targets and PubMed.</p>
    <p>Preserve source links, biological context and collection limits.</p>
  </div>
</div>
<div class="report-root architecture-output">The coordinator returns a traceable report<p>Findings · Comparisons · Sources · Open questions<br>Saved results can be read through the website or MCP.</p></div>
<figcaption>Current live-question architecture. Models frame the question; the coordinator uses source-specific rules for findings and comparisons, with no additional model call after retrieval. Guided examples use cached synthetic evidence.</figcaption>
</figure>"""


def investigation_diagram():
    return """<figure class="xctx-figure" aria-label="Research scope, collection, comparison, review and report, with bounded collection retries">
<div class="fig-kicker">02 / FROM A QUESTION TO AN EXPLAINABLE REPORT</div>
<ol class="fig-flow research-workflow">
  <li class="flow-step workflow-step"><strong>Define scope</strong><span>Question, species, settings and measurements</span></li>
  <li class="flow-step workflow-step"><strong>Collect sources</strong><span>Reported values, source records and metadata</span></li>
  <li class="flow-step workflow-step"><strong>Compare findings</strong><span>Keep differences in what was measured visible</span></li>
  <li class="flow-step workflow-step"><strong>Review gaps</strong><span>Account for missing information and search limits</span></li>
  <li class="flow-step workflow-step"><strong>Report &amp; next steps</strong><span>Explain what we found and what still needs evidence</span></li>
</ol>
<div class="workflow-note">↶ A recoverable collection error can trigger one retry within the run budget. Unavailable evidence and technical failures remain visible.</div>
<figcaption>A finished investigation can leave the biological question open. Species, experimental setting, measurement type and available study or sample identifiers stay attached to the evidence.</figcaption>
</figure>"""
