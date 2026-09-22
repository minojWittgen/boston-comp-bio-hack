"""Accessible, local diagrams for the public research story. No external assets."""
from html import escape
from base64 import b64encode

import streamlit as st

MEASUREMENTS = {
    "DNA": ("Perturbation / variant", "Orthology / genotype", "Patient variants",
            "DNA can connect a variant or perturbation to a finding. It does not establish RNA abundance or protein activity."),
    "RNA": ("Expression response", "Tissue expression", "Cohort expression",
            "RNA describes expression. A change in RNA does not automatically imply the same change in protein or function."),
    "Protein": ("Abundance / location", "Tissue protein", "Patient protein",
                "Protein abundance and location add evidence, but neither alone establishes activity."),
    "Function": ("Perturbation effect", "Organism phenotype", "Clinical outcome",
                 "Functional measurements test an effect in a particular setting. Cell fitness, animal phenotypes and clinical outcomes need different interpretations."),
}

STYLES = """<style>
.xctx-figure {--ink:#28473c;--muted:#627267;--line:#d6dfd3;--sage:#e9f0e5;
  margin:0 0 .6rem;padding:24px;border:1px solid var(--line);border-radius:16px;
  background:#fcfcf8;color:var(--ink);font-family:inherit;box-sizing:border-box;}
.xctx-figure * {box-sizing:border-box;}
.xctx-figure .fig-kicker {font-size:11px;font-weight:650;letter-spacing:.13em;color:var(--muted);margin-bottom:20px;}
.xctx-figure p {margin:6px 0 0;font-size:14px;line-height:1.55;}
.xctx-figure figcaption {font-size:12px;color:var(--muted);line-height:1.5;margin-top:18px;}
.xctx-figure .fig-lane {display:grid;grid-template-columns:138px minmax(0,1fr);align-items:center;gap:20px;margin:16px 0;}
.xctx-figure .lane-label {font-size:13px;font-weight:650;line-height:1.5;}
.xctx-figure .lane-label span {display:block;font-size:11px;font-weight:400;color:var(--muted);margin-top:4px;}
.xctx-figure .fig-flow {display:flex;gap:22px;list-style:none;margin:0;padding:0;}
.xctx-figure .flow-step {position:relative;flex:1;min-width:0;border:1px solid var(--line);border-radius:9px;
  padding:16px 10px;background:#f3f4ef;font-size:13px;text-align:center;line-height:1.5;}
.xctx-figure .flow-step:not(:last-child)::after {content:'→';position:absolute;right:-19px;top:calc(50% - 14px);font-size:20px;color:#83958a;}
.xctx-figure .research-lane .flow-step {background:var(--sage);border-color:#b5c9b9;}
.xctx-figure .research-lane .flow-step:last-child {background:#315d4e;color:white;}
.xctx-figure .fig-blindspots {display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:14px 16px;margin:18px 0;
  background:#f5efe4;border:1px dashed #d9c9aa;border-radius:9px;font-size:12px;color:#735c38;}
.xctx-figure .fig-blindspots strong {margin-right:5px;}
.xctx-figure .fig-chip {padding:3px 9px;border:1px solid #decfb4;border-radius:20px;background:#fffaf1;}
.xctx-figure .context-bridge {display:grid;grid-template-columns:1fr 38px 1fr 38px 1fr;align-items:center;}
.xctx-figure .context-node {text-align:center;border:1px solid var(--line);border-radius:12px;padding:22px 15px;background:white;min-width:0;}
.xctx-figure .context-node strong {display:block;font-size:18px;margin-top:10px;}
.xctx-figure .context-node small {display:block;color:var(--muted);font-size:11px;letter-spacing:.08em;margin-top:4px;}
.xctx-figure .context-node p {font-size:13px;}
.xctx-figure .bridge-arrow {text-align:center;color:#849b8b;font-size:26px;}
.xctx-figure .fig-icon {width:64px;height:64px;stroke:currentColor;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;}
.xctx-figure .context-tags {display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin-top:18px;}
.xctx-figure .context-tags span {font-size:11px;background:var(--sage);padding:5px 9px;border-radius:5px;}
.xctx-figure .matrix-scroll {overflow-x:auto;}
.xctx-figure .evidence-map {width:100%;border-collapse:separate;border-spacing:5px;table-layout:fixed;}
.xctx-figure .evidence-map th {font-size:12px;font-weight:600;padding:9px 7px;text-align:center;}
.xctx-figure .evidence-map th:first-child {width:19%;text-align:left;}
.xctx-figure .evidence-map td {padding:13px 9px;border:1px solid #e1e7dc;border-radius:7px;
  background:#f3f5f0;text-align:center;font-size:12px;line-height:1.4;color:#647365;}
.xctx-figure .evidence-map tr[data-active='true'] th {color:#234d3c;}
.xctx-figure .evidence-map tr[data-active='true'] td {background:#dfeadb;border-color:#96b291;color:#244331;font-weight:600;}
.xctx-figure .row-dot {display:inline-block;width:7px;height:7px;margin-right:7px;border:1px solid #a5b6a7;border-radius:50%;}
.xctx-figure tr[data-active='true'] .row-dot {background:#315d4e;border-color:#315d4e;}
.xctx-figure .report-root {margin:0 auto;width:fit-content;max-width:100%;padding:12px 28px;
  background:#315d4e;color:white;font-size:14px;font-weight:600;text-align:center;border-radius:8px;}
.xctx-figure .report-branches {display:block;width:100%;height:42px;color:#a1b4a3;}
.xctx-figure .report-outcomes {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;}
.xctx-figure .report-outcome {border:1px solid var(--line);border-top:3px solid #719174;border-radius:8px;padding:17px 15px;background:#f0f5ed;}
.xctx-figure .report-outcome:nth-child(2) {border-top-color:#b78651;background:#faf3e8;}
.xctx-figure .report-outcome:nth-child(3) {border-top-color:#839197;background:#eff2f2;}
.xctx-figure .report-outcome strong {font-size:16px;}
.xctx-figure .report-outcome p {font-size:13px;}
@media(max-width:700px) {
  .xctx-figure {padding:18px 12px;}
  .xctx-figure .fig-lane {grid-template-columns:1fr;gap:10px;}
  .xctx-figure .lane-label span {display:inline;margin-left:8px;}
  .xctx-figure .flow-step {padding:12px 5px;font-size:12px;}
  .xctx-figure .context-bridge {grid-template-columns:1fr;gap:8px;}
  .xctx-figure .bridge-arrow {transform:rotate(90deg);height:28px;}
  .xctx-figure .context-node {padding:16px;}
  .xctx-figure .context-node .fig-icon {width:48px;height:48px;}
  .xctx-figure .report-outcomes {gap:8px;}
  .xctx-figure .report-outcome {padding:12px 8px;}
  .xctx-figure .evidence-map {min-width:430px;}
}
@media(max-width:420px) {
  .xctx-figure .fig-flow {flex-direction:column;gap:20px;}
  .xctx-figure .flow-step:not(:last-child)::after {content:'↓';right:calc(50% - 5px);top:auto;bottom:-20px;font-size:17px;}
  .xctx-figure .report-outcomes {grid-template-columns:1fr;}
  .xctx-figure .report-branches {display:none;}
  .xctx-figure .report-root {margin-bottom:12px;}
}
</style>"""


def _icon(kind):
    shapes = {
        "cells": '<ellipse cx="32" cy="25" rx="25" ry="15"/><path d="M7 25v11c0 8 11 15 25 15s25-7 25-15V25"/><circle cx="22" cy="22" r="5"/><circle cx="41" cy="27" r="6"/><circle cx="30" cy="33" r="3"/><path d="M17 28l-2 2m32-12 2-2"/>',
        "mouse": '<path d="M9 39c-9 0-9-13 0-13"/><ellipse cx="30" cy="37" rx="20" ry="13"/><path d="M44 28l10 5 5 8-13 4"/><circle cx="46" cy="25" r="7"/><circle cx="52" cy="35" r="1"/><path d="M20 47l-4 6m19-4 3 4m19-13 6-2m-7 5 6 2"/>',
        "patients": '<circle cx="32" cy="17" r="8"/><path d="M18 54V41c0-9 6-14 14-14s14 5 14 14v13M25 41v13m14-13v13"/><circle cx="11" cy="23" r="5"/><path d="M3 48V37c0-5 3-8 8-8m42-11a5 5 0 1 1 0 10m-3 2c7-2 11 2 11 8v10"/>',
    }
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" stroke="#315d4e" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{shapes[kind]}</svg>'
    return _svg_image(svg, "fig-icon")


def _svg_image(svg, css_class):
    # st.html permits HTML but strips inline SVG. A local data image keeps vector
    # sharpness without relaxing sanitization or loading any external resource.
    data = b64encode(svg.encode()).decode()
    return f'<img class="{css_class}" src="data:image/svg+xml;base64,{data}" alt="">'


def search_diagram():
    return """<figure class="xctx-figure" aria-label="Paper-focused LLM search and the cross-context research workflow">
<div class="fig-kicker">01 / LOOK BEYOND THE PAPER SUMMARY</div>
<div class="fig-lane"><div class="lane-label">Paper-focused<br>LLM search<span>When the workflow stops at publications</span></div>
<ol class="fig-flow"><li class="flow-step">Ask a question</li><li class="flow-step">Find papers</li><li class="flow-step">Summarize claims</li></ol></div>
<div class="fig-blindspots"><strong>What can be left out?</strong><span class="fig-chip">Measured values</span><span class="fig-chip">Experimental conditions</span><span class="fig-chip">Species differences</span><span class="fig-chip">Patient variation</span></div>
<div class="fig-lane research-lane"><div class="lane-label">Cross-context<br>research<span>Follow the claim into its evidence</span></div>
<ol class="fig-flow"><li class="flow-step">Define the<br>evidence needed</li><li class="flow-step">Inspect source<br>records + references</li><li class="flow-step">Compare settings<br>+ measurements</li><li class="flow-step">Explain findings<br>+ open questions</li></ol></div>
<figcaption>The difference is the research workflow and the evidence it inspects. Today’s demo works with retrieved database findings and source metadata; raw-data reanalysis is a further step.</figcaption>
</figure>"""


def contexts_diagram():
    nodes = []
    for kind, title, subtitle, question, tags in (
        ("cells", "Cell cultures", "IN VITRO", "What happens in a controlled experiment?", "Cell type · Conditions"),
        ("mouse", "Animal models", "IN VIVO", "Does the finding carry over to an organism?", "Species · Tissue"),
        ("patients", "Patients", "HUMAN DISEASE", "What is observed in people with disease?", "People · Samples"),
    ):
        nodes.append(f'<div class="context-node">{_icon(kind)}<strong>{title}</strong><small>{subtitle}</small><p>{question}</p><div class="context-tags"><span>{tags}</span></div></div>')
    bridge = '<div class="bridge-arrow" aria-hidden="true">↔</div>'.join(nodes)
    return f'<figure class="xctx-figure" aria-label="Compare evidence between cell cultures, animal models and patients"><div class="fig-kicker">02 / A FINDING IN ONE SETTING RAISES A QUESTION IN ANOTHER</div><div class="context-bridge">{bridge}</div><figcaption>Each connection needs evidence. A result in cells does not automatically establish the same response in animals or patients.</figcaption></figure>'


def measurement_diagram(selected):
    rows = []
    for name, values in MEASUREMENTS.items():
        cells = ''.join(f'<td>{escape(value)}</td>' for value in values[:3])
        rows.append(f'<tr data-active="{str(name == selected).lower()}"><th scope="row"><span class="row-dot" aria-hidden="true"></span>{name}</th>{cells}</tr>')
    return f'''<figure class="xctx-figure" aria-label="Conceptual evidence map across measurement types and biological settings">
<div class="fig-kicker">03 / DIFFERENT MEASUREMENTS, DIFFERENT QUESTIONS</div>
<div class="matrix-scroll"><table class="evidence-map"><thead><tr><th scope="col">Measurement</th><th scope="col">Cell cultures</th><th scope="col">Animal models</th><th scope="col">Patients</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<figcaption>Conceptual map. Each cell names evidence a researcher might seek; it does not indicate that this demo has retrieved those data.</figcaption></figure>'''


def report_diagram():
    branches = _svg_image('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 42" preserveAspectRatio="none"><path d="M450 0V21M150 42V21H750V42M450 21V42" fill="none" stroke="#a1b4a3" stroke-width="1.5"/></svg>', "report-branches")
    return """<figure class="xctx-figure" aria-label="A research report explains agreement, differences and gaps">
<div class="fig-kicker">04 / MAKE THE NEXT RESEARCH QUESTION CLEAR</div>
<div class="report-root">Evidence + biological context</div>
""" + branches + """
<div class="report-outcomes"><div class="report-outcome"><strong>What agrees?</strong><p>Which comparable observations point in the same direction?</p></div><div class="report-outcome"><strong>What differs?</strong><p>Which findings change with the species, setting or measurement?</p></div><div class="report-outcome"><strong>What is missing?</strong><p>Which question still needs a measurement, source or better comparison?</p></div></div>
<figcaption>Follow every finding back to its source. A useful report can reveal disagreement or an unanswered question.</figcaption></figure>"""


def show_diagram(html):
    st.html(html)
