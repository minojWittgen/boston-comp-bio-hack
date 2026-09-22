"""Research report rendering, separate from chat and provider credentials."""
import streamlit as st

from research_app.presentation import (CONCLUSIONS, assistant_summary, collection_notes,
    comparison_views, context_coverage, is_synthetic, requirement_rows, search_status,
    CONTEXT_LABELS, readable)
from research_app.sources import source_view
from research_app.report_outline import (COVERAGE_LABELS, comparison_outline,
    context_outline, named_references, preview_records)
from research_app.explanations import (comparison_explanations, criteria_origin,
    overview_explanation, requirement_explanations, source_contributions)


def criteria_table(state):
    return [{"Measurement / context": r["title"], "Minimum studies in this plan": r["minimum"],
             "Qualifying studies supplied": r["qualifying_studies"] if r["qualifying_studies"] is not None else "Not checked yet",
             "Needed for this question": "Required" if r["required"] else "Optional"}
            for r in requirement_explanations(state)]


def show_reasoning(state):
    st.subheader("How we reached this result")
    st.write(overview_explanation(state))
    st.markdown("**How much evidence does this plan ask for?**")
    st.write(criteria_origin(state))
    criteria = criteria_table(state)
    if criteria:
        st.table(criteria)
    st.caption("This is a minimum for the software's descriptive comparison, not a scientific sample-size calculation or proof that one study is sufficient. Study IDs are counted once per requirement; one study may contribute to more than one context. More database rows do not increase this count.")
    with st.expander("What makes a study qualify?"):
        st.write("It must be supplied as a study observation with a study ID and source reference, and match the requested gene, species, context, measurement type and outcome name. Any specified disease, tissue or host species must also match. The comparison then needs compatible measurements and a shared comparison group with a reported direction of change.")
        st.caption("The current checker compares supplied labels exactly. It does not independently validate study quality, sample size, effect magnitude, units, statistical significance or scientific equivalence.")
    contributions = source_contributions(state)
    if contributions:
        with st.expander("What we found and how it relates to the question"):
            st.table([{"Source": row["title"], "Finding in the returned data": row["finding"],
                       "What this can—and cannot—answer": row["role"]} for row in contributions])
            st.caption("These statements describe the retrieved records. Open Sources for the linked database entries, papers and full returned measurements.")
    else:
        st.write("No source records are available yet.")
    st.markdown("**What needs to happen next?**")
    records = state.evidence.records if state.evidence else []
    if records and not any(r.level == "observation" for r in records):
        st.write("The sources found so far provide reference material. The next step is to extract the study measurements, keep their source and sample information, and prepare compatible comparisons. Another search of the same sources alone will not supply those missing measurements.")
    st.write("This prototype compares reported directions of change. It does not yet calculate a harmonized comparison of absolute measurement values across datasets. Review the proposed outcome, comparison groups and alignment method before treating the result as an answer to that broader question.")
    issues = list(dict.fromkeys(issue for explanation in comparison_explanations(state).values() for issue in explanation["plan_issues"]))
    for issue in issues:
        st.warning("Plan needs review: " + issue)


def markdown_report(state):
    """A readable export; the canonical audit and every original payload stay in JSON."""
    if getattr(state, "investigation", None) is not None:
        from coordinator.engine import render_report
        return render_report(state).rstrip() + "\n\n" + _source_markdown(state)
    def escape(value):
        text = str(value)
        for char in ("\\", "[", "]", "*", "_", "<", ">", "`", "|"):
            text = text.replace(char, "\\" + char)
        return text.replace("\n", " ")
    lines = ["# CoMEA research report", "", escape(state.request.question), "", assistant_summary(state), "", "## Why this result?", "", overview_explanation(state), "", criteria_origin(state), "",
             "The study minimum is a software threshold, not a statistical sample-size calculation. More database rows do not count as more studies.", ""]
    for row in requirement_explanations(state):
        lines.append(f"- {escape(row['title'])}: minimum study count: {row['minimum']}; qualifying studies supplied: {row['qualifying_studies'] if row['qualifying_studies'] is not None else 'not checked'}.")
    lines.extend(["", "## What we found and what it means", ""])
    for contribution in source_contributions(state):
        lines.extend([f"### {escape(contribution['title'])}", "", escape(contribution['finding']), "", escape(contribution['role']), ""])
    explanations = comparison_explanations(state)
    lines.extend(["## Comparisons", ""])
    for view in comparison_views(state):
        lines.extend([f"### {escape(view['title'])}", "", f"**{view['conclusion']}**", "", escape(view['detail']), ""])
        explanation = explanations[view['id']]
        lines.extend(f"- {escape(note)}" for note in explanation['needs'] + explanation['reasons'] + explanation['plan_issues'])
        lines.extend(["", explanation['identity'], ""])
        for count in explanation['counts']:
            lines.append(f"- {escape(count['Context / measurement'])}: minimum {count['Minimum studies in this plan']} studies; {count['Studies meeting scope and traceability']} meet scope; {count['Studies usable in this comparison']} usable in this comparison.")
        lines.append("")
    lines.extend(["## Evidence needed", "", "These measurements come from the research plan; they are not claims about what a source measured.", ""])
    for row in requirement_rows(state):
        lines.extend([f"### {escape(row['Question to answer'])}", ""])
        lines.extend(f"- **{key}:** {escape(value)}" for key, value in row.items() if key != "Question to answer")
        lines.append("")
    lines.extend(["## Sources", "", "Database links are built from returned identifiers or queries. Article search hits have not been screened as study evidence.", ""])
    for record in (state.evidence.records if state.evidence else []):
        view = source_view(record)
        lines.extend([f"### {escape(view.title)}", "", escape(view.summary), "", escape(view.limitation), ""])
        lines.extend(f"- [{escape(label)}]({url.replace('(', '%28').replace(')', '%29')})" for label, url, _ in view.links)
        lines.extend(f"- **{key}:** {escape(value)}" for key, value in {**view.facts, **view.identities}.items())
        if view.table:
            lines.extend(["", f"Source data preview: {min(25, len(view.table))} of {len(view.table)} returned rows. Full data are in the JSON download.", ""])
            columns = list(view.table[0])
            lines.extend(["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
            lines.extend("| " + " | ".join(escape(row.get(col)) if row.get(col) is not None else "Not supplied" for col in columns) + " |" for row in view.table[:25])
        lines.append("")
    lines.extend(["## Search limitations", ""] + [f"- {escape(note)}" for note in collection_notes(state)])
    lines.extend(["", "Comparisons check supplied measurements and metadata; source accuracy, cohort independence and scientific comparability require researcher review.", ""])
    return "\n".join(lines)


def _source_markdown(state):
    """Preserve source links and numeric previews alongside the canonical report."""
    def escape(value):
        text = str(value)
        for char in ("\\", "[", "]", "*", "_", "<", ">", "`", "|"):
            text = text.replace(char, "\\" + char)
        return text.replace("\n", " ")
    lines = ["## Source records and measurements", "", "Links use identifiers, queries or provenance supplied with the retrieved records.", ""]
    for record in (state.evidence.records if state.evidence else []):
        view = source_view(record)
        lines.extend([f"### {escape(view.title)}", "", escape(view.summary), "", escape(view.limitation), ""])
        lines.extend(f"- [{escape(label)}]({url.replace('(', '%28').replace(')', '%29')})" for label, url, _ in view.links)
        lines.extend(f"- **{key}:** {escape(value)}" for key, value in {**view.facts, **view.identities}.items())
        if view.table:
            columns = list(view.table[0])
            lines.extend(["", f"Source data preview: {min(25, len(view.table))} of {len(view.table)} returned rows. Full data are in the JSON download.", "",
                          "| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
            lines.extend("| " + " | ".join(escape(row.get(col)) if row.get(col) is not None else "Not supplied" for col in columns) + " |" for row in view.table[:25])
        lines.append("")
    return "\n".join(lines)


def render_source(record, finding=None):
    view = source_view(record)
    with st.expander(view.title):
        st.write(view.summary)
        st.caption(view.limitation)
        if finding is not None and finding.summary != view.summary:
            st.markdown("**Full research finding**")
            st.write(finding.summary)
            for limitation in finding.limitations:
                if limitation != view.limitation:
                    st.caption(limitation)
        primary = [link for link in view.links if not link[0].startswith("PubMed article")]
        for label, url, _ in primary[:3]:
            st.link_button(label, url)
        with st.container():
            st.markdown("**Study and sample traceability**")
            for label, value in view.identities.items():
                st.text(f"{label}: {value}")
            for label, value in view.facts.items():
                st.text(f"{label}: {value}")
            extra_links = [link for link in view.links if link not in primary[:3]]
            if extra_links:
                columns = st.columns(2)
                for i, (label, url, _) in enumerate(extra_links):
                    with columns[i % 2]:
                        st.link_button(label, url)
            if view.table:
                st.dataframe(view.table, hide_index=True, width="stretch")
            if not view.links:
                st.caption("No source link was included in this result.")
            elif any(kind in {"identifier", "query"} for _, _, kind in view.links):
                st.caption("Database and article links are built from identifiers or queries in the retrieved result. A link is a way to inspect the source, not proof that it supports this comparison.")
            st.caption(f"Retrieved: {record.retrieved_at or 'Not supplied'} · Source release: {record.source_version or 'Not supplied'}")


def show_report(state):
    if getattr(state, "investigation", None) is not None:
        _show_investigation_report(state)
        return
    if is_synthetic(state):
        st.warning("Synthetic teaching example · all observations are fabricated, not biological findings.")
    a, b = st.columns([1, 2])
    a.metric("Source search", search_status(state))
    b.metric("Answer to your question", CONCLUSIONS[state.assessment.conclusion] if state.assessment else "Not assessed yet")
    records = state.evidence.records if state.evidence else []
    observations = [r for r in records if r.level == "observation"]
    references = [r for r in records if r.level == "background"]
    if references and not observations:
        st.info("We found database summaries and reference material, but no study observations with the measurements and source information needed for this comparison. Read Sources for what was retrieved and Comparisons for what is still needed.")
    for col, row in zip(st.columns(3), context_coverage(state)):
        with col.container(border=True):
            st.markdown(f"**{row['label']}**")
            st.write(row["detail"])
    reasoning, findings, sources, question = st.tabs(["Why this result?", "Comparisons", "Sources", "What we needed to answer"])
    with reasoning:
        show_reasoning(state)
    with findings:
        st.subheader("What can we conclude?")
        views = comparison_views(state)
        if not views:
            st.write("No comparison has been assessed yet.")
        explanations = comparison_explanations(state)
        for view in views:
            with st.container(border=True):
                st.markdown(f"**{view['title']}**")
                st.write(view["conclusion"])
                st.write(view["detail"])
                explanation = explanations[view["id"]]
                st.table(explanation["counts"])
                for reason in explanation["reasons"]:
                    st.write(reason)
                for issue in explanation["plan_issues"]:
                    st.warning("Plan needs review: " + issue)
                with st.expander("What would make these measurements comparable?"):
                    for item in explanation["needs"]:
                        st.write(item)
                    st.write(explanation["identity"])
                if view["records"]:
                    with st.expander("Measurements used in this comparison"):
                        st.dataframe([{"Gene": r.entity, "Study ID": r.study_id or "Not supplied", "Measured outcome": r.endpoint,
                                       "Direction": r.direction, "Participant / subject ID": r.subject_id or "Not supplied",
                                       "Sample / specimen ID": r.specimen_id or "Not supplied"} for r in view["records"]], hide_index=True, width="stretch")
        notes = collection_notes(state)
        if notes:
            st.markdown("**Search limitations**")
            for note in notes:
                st.write(note)
        st.caption("These comparisons check supplied measurements and metadata. Source accuracy, independent study populations and scientific comparability still require researcher review.")
    with sources:
        st.subheader("Where the information comes from")
        st.write("Open a source to see its measurements, article links and available study or sample identifiers. “Not supplied” means the retrieved result does not include that information.")
        if not records:
            st.info("No source results have been returned.")
        if observations:
            st.markdown("**Study observations**")
            for record in observations:
                render_source(record)
        if references:
            st.markdown("**Database summaries and article searches**")
            st.caption("These can guide further research. They are not counted as study observations for the comparisons above.")
            for record in references:
                render_source(record)
    with question:
        st.subheader("Your research question")
        st.write(state.request.question)
        st.markdown("**Measurements needed to answer it**")
        if state.plan:
            origin = "These criteria were supplied with the request." if state.request.requirements else "The model proposed these criteria from your question. Review them before interpreting the results."
            st.write(origin + " A measurement listed here is a research requirement, not a result retrieved from a source.")
            for row in requirement_rows(state):
                with st.expander(f"{row['Question to answer']} · {row['Evidence available']}"):
                    for label, value in row.items():
                        if label != "Question to answer":
                            st.text(f"{label}: {value}")
            st.caption("Distinct study identifiers are counted once; different identifiers alone do not prove independent study populations.")
            if state.plan.assumptions:
                with st.expander("Proposed assumptions to review"):
                    for assumption in state.plan.assumptions:
                        st.write(assumption)
            if state.plan.pathway:
                st.write(f"Pathway: {state.plan.pathway.id} · {state.plan.pathway.source} · {state.plan.pathway.version}")
                st.caption("Pathway membership defines scope; it does not measure activity.")
            st.caption("Clarify your question in chat to start a new search with revised criteria.")
        else:
            st.write("The research question is still being prepared.")
    if state.error:
        st.error(state.error)
    if state.status in {"complete", "partial", "failed"}:
        st.download_button("Download readable report", markdown_report(state), file_name=f"research-report-{state.run_id}.md", mime="text/markdown")
    with st.expander("Technical details and original data"):
        st.caption("For reproducibility and debugging. Internal record IDs identify stored results, not publications, participants or samples.")
        st.json({"investigation_id": state.run_id, "status": state.status, "events": state.events,
                 "assessment": state.assessment.model_dump() if state.assessment else None,
                 "collection_limits": [g.model_dump() for g in state.evidence.gaps] if state.evidence else [],
                 "plan_sha256": state.plan_sha256}, expanded=False)
        st.download_button("Download all original data (JSON)", state.model_dump_json(indent=2), file_name=f"investigation-{state.run_id}.json", mime="application/json")


def _show_investigation_report(state):
    investigation = state.investigation
    records = state.evidence.records if state.evidence else []
    if is_synthetic(state):
        st.warning("Synthetic teaching example · not biological findings.")
    a, b = st.columns([1, 2])
    a.metric("Source search", search_status(state))
    b.metric("Investigation", "Complete" if investigation.criteria_met else "Collection incomplete")
    with st.expander("What does this status mean?"):
        st.write(investigation.completion_reason)
        st.caption("A finished investigation means the source review is done. It does not establish a biological claim.")
    for col, row in zip(st.columns(3), context_outline(state)):
        with col.container(border=True):
            st.markdown(f"**{row['label']}**")
            st.write(row["detail"])

    findings, comparisons, sources, question = st.tabs(["Findings", "Comparisons", "Sources", "What we needed to answer"])
    with findings:
        st.subheader("What we found")
        preview = preview_records(state)
        st.caption(f"Showing {len(preview)} of {len(records)} returned records, selected to cover the question and different contexts. This is a preview, not a ranking of study quality. All records are in Sources.")
        for record in preview:
            view = source_view(record)
            with st.container(border=True):
                st.markdown(f"**{view.title}**")
                st.caption(f"{CONTEXT_LABELS.get(record.context, readable(record.context))} · {readable(record.species)} · {record.modality or 'Measurement not specified'}")
                st.write(view.summary)
                st.caption(view.limitation)
                for label, url, _ in view.links[:1]:
                    st.markdown(f"[{label}]({url.replace('(', '%28').replace(')', '%29')})")
        if not preview:
            st.info("No source records have been returned. The coverage and next steps explain the remaining search work.")
        _show_notes("What remains uncertain", [named_references(state, note) for note in investigation.limitations])
        notes = collection_notes(state)
        if notes:
            with st.expander("Source availability and search limits"):
                for note in notes:
                    st.write(note)
        _show_notes("What to do next", [named_references(state, note) for note in investigation.next_steps])
        if not investigation.next_steps:
            st.write("Review the linked sources and refine the research question if you want to investigate further.")

    with comparisons:
        st.subheader("Similarities, differences and open questions")
        comparisons_to_show = investigation.comparisons
        labels = {c.id: " ↔ ".join(row["Requested context"] for row in comparison_outline(state, c)) for c in comparisons_to_show}
        if len(comparisons_to_show) > 1:
            selected = st.selectbox("Choose a comparison", list(labels), format_func=labels.get)
            comparisons_to_show = [c for c in comparisons_to_show if c.id == selected]
        for comparison in comparisons_to_show:
            with st.container(border=True):
                st.table(comparison_outline(state, comparison))
                st.caption("Source coverage describes what was retrieved. It does not establish agreement or count independent studies.")
                for col, side, ids in zip(st.columns(2), ("First context", "Second context"),
                                         (comparison.left_evidence_ids, comparison.right_evidence_ids)):
                    with col:
                        st.markdown(f"**{side} · example source**")
                        available = [r for r in records if r.id in ids]
                        available.sort(key=lambda r: r.source in {"mygene", "ensembl_orthology"})
                        if available:
                            record = available[0]
                            source = source_view(record)
                            st.markdown(f"**{source.title}**")
                            st.write(source.summary)
                            st.caption(f"Returned context: {readable(record.species)} · {CONTEXT_LABELS.get(record.context, readable(record.context))} · {record.modality or 'Measurement not specified'}")
                            st.caption(source.limitation)
                        else:
                            st.write("No source record was returned for this side.")
                _show_notes("Limits of this comparison", comparison.limitations)
                with st.expander("Full comparison explanation and source references"):
                    st.write(named_references(state, comparison.summary))
        if not comparisons_to_show:
            st.write("No cross-context comparison was requested or returned. The retrieved findings are available in Findings and Sources.")
        if state.assessment and any(r.level == "observation" for r in records):
            with st.expander("Optional comparison of supplied study observations"):
                st.write(CONCLUSIONS[state.assessment.conclusion])
                st.caption("This separate check compares declared study measurements. It does not determine whether the research investigation is complete.")
                details = comparison_explanations(state)
                for view in comparison_views(state, observation_only=True):
                    st.markdown(f"**{view['title']}**")
                    st.write(view["conclusion"])
                    st.write(view["detail"])
                    if view["id"] in details:
                        st.table(details[view["id"]]["counts"])
                        for reason in details[view["id"]]["reasons"]:
                            st.write(reason)

    with sources:
        st.subheader("Where the information comes from")
        st.write("Open a source for the full finding, measurements, article links and available study or sample identifiers.")
        full_findings = {f.evidence_id: f for f in investigation.findings}
        for record in records:
            render_source(record, full_findings.get(record.id))
        if not records:
            st.info("No source results have been returned.")

    with question:
        st.subheader("Your research question")
        st.write(state.request.question)
        st.write(criteria_origin(state))
        rows = requirement_rows(state)
        if rows:
            st.table([{"Question to answer": row["Question to answer"], "Context": row["Context"],
                       "Source coverage": COVERAGE_LABELS.get(row["Evidence available"].lower(), row["Evidence available"])} for row in rows])
            for row in rows:
                with st.expander(f"{row['Question to answer']} · {row['Evidence available']}"):
                    for key, value in row.items():
                        st.text(f"{key}: {value}")
        if state.plan and state.plan.assumptions:
            with st.expander("Scope assumptions to review"):
                for assumption in state.plan.assumptions:
                    st.write(assumption)
        if state.plan and state.plan.pathway:
            st.caption(f"Pathway scope: {state.plan.pathway.id} · {state.plan.pathway.source} · {state.plan.pathway.version}")

    if state.error:
        st.error(state.error)
    if state.status in {"complete", "partial", "failed"}:
        st.download_button("Download readable report", markdown_report(state), file_name=f"research-report-{state.run_id}.md", mime="text/markdown")
    with st.expander("Technical details and original data"):
        st.json({"investigation_id": state.run_id, "status": state.status,
                 "investigation": investigation.model_dump(),
                 "optional_observation_assessment": state.assessment.model_dump() if state.assessment else None,
                 "collection_limits": [g.model_dump() for g in state.evidence.gaps] if state.evidence else [],
                 "events": state.events, "plan_sha256": state.plan_sha256}, expanded=False)
        st.download_button("Download all original data (JSON)", state.model_dump_json(indent=2), file_name=f"investigation-{state.run_id}.json", mime="application/json")


def _show_notes(title, notes, limit=2):
    notes = list(dict.fromkeys(note.strip() for note in notes if note.strip()))
    wording = {
        "Research completion means source material and research gaps were accounted for, not that a molecular effect was confirmed.":
            "Completing the source review does not confirm a biological effect.",
        "Database measurements and summaries are usable research findings at their reported scope. The background label distinguishes them from separately supplied normalized observations; it does not mean non-empirical or unusable.":
            "Database findings are interpreted at the level reported by each source. A summary is not automatically a comparable study measurement.",
    }
    if not notes:
        return
    st.markdown(f"**{title}**")
    for note in notes[:limit]:
        st.write("• " + wording.get(note, note))
    if len(notes) > limit:
        with st.expander(f"{title} · {len(notes) - limit} more"):
            for note in notes[limit:]:
                st.write("• " + note)
