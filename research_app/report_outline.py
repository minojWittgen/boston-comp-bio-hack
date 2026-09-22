"""Small, read-only previews of the coordinator's full research result."""
import re

from research_app.presentation import CONTEXT_LABELS, context_coverage, readable
from research_app.sources import source_view

COVERAGE_LABELS = {
    "addressed": "Sources match the requested scope",
    "limited": "Related evidence; some scope details differ",
    "unavailable": "No matching source returned",
    "pending": "Still being reviewed",
}


def context_outline(state):
    rows = context_coverage(state)
    for row in rows:
        if not row["total"]:
            row["detail"] = "Outside this question's scope."
            continue
        counts = ((row["addressed"], "with matching sources"),
                  (row["limited"], "with related evidence only"),
                  (row["unavailable"], "with no source returned"))
        pending = row["total"] - sum(count for count, _ in counts)
        if pending:
            counts += ((pending, "still being reviewed"),)
        row["detail"] = " · ".join(f"{n} {'topic' if n == 1 else 'topics'} {label}" for n, label in counts if n)
    return rows


def preview_records(state, limit=3):
    """Prefer covered scope and varied entities/contexts; never rank biological strength."""
    records = list(state.evidence.records if state.evidence else [])
    matching = {eid for c in state.investigation.coverage if c.status == "addressed" for eid in c.evidence_ids}
    records.sort(key=lambda r: (r.id not in matching, r.source in {"mygene", "ensembl_orthology"}))
    chosen, seen = [], set()
    for record in records:
        group = (record.entity, record.context)
        if group not in seen:
            chosen.append(record)
            seen.add(group)
        if len(chosen) == limit:
            break
    for record in records:
        if len(chosen) == limit:
            break
        if record not in chosen:
            chosen.append(record)
    return chosen


def named_references(state, text):
    """Replace internal record references, preserving the complete explanation."""
    if state.plan:
        for req in state.plan.requirements:
            text = text.replace(f"For {req.id},", f"For {req.title},")
            for status, label in COVERAGE_LABELS.items():
                if text.startswith(f"{req.id}: {status};"):
                    text = f"{req.title}: {label};" + text[len(f"{req.id}: {status};"):]
            for field in ("species", "context", "modality", "endpoint", "condition", "tissue", "host_species"):
                value = getattr(req, field)
                if value:
                    label = CONTEXT_LABELS.get(value, readable(value)) if field == "context" else readable(value)
                    pattern = rf"(?<![\w]){field}={re.escape(value)}(?=,|\)|;|$)"
                    text = re.sub(pattern, lambda _: f"{readable(field)}: {label}", text)
    names = {r.id: source_view(r).title for r in (state.evidence.records if state.evidence else [])}
    if not names:
        return text
    # Only identifier slots emitted by the coordinator, not words, numbers or URLs.
    pattern = r"\[(" + "|".join(re.escape(key) for key in sorted(names, key=len, reverse=True)) + r")\]"
    text = re.sub(pattern, lambda m: names[m[1]], text)
    pattern = r"(?<![\w/])(" + "|".join(re.escape(key) for key in sorted(names, key=len, reverse=True)) + r")(?==)"
    return re.sub(pattern, lambda m: names[m[1]] + " · direction", text)


def comparison_outline(state, comparison):
    requirements = {r.id: r for r in state.plan.requirements} if state.plan else {}
    spec = next((s for s in state.plan.comparisons if s.id == comparison.id), None) if state.plan else None
    coverage = {c.requirement_id: c for c in state.investigation.coverage}
    sides = []
    for side, req_id, ids in (("First context", spec.left if spec else None, comparison.left_evidence_ids),
                              ("Second context", spec.right if spec else None, comparison.right_evidence_ids)):
        req = requirements.get(req_id)
        entry = coverage.get(req_id)
        scope = f"{req.entity} · {CONTEXT_LABELS[req.context]} · {readable(req.species)} · {req.modality}" if req else side
        sides.append({"Requested context": scope,
                      "Source coverage": COVERAGE_LABELS.get(entry.status if entry else "pending", COVERAGE_LABELS["pending"]),
                      "Source records": len(set(ids))})
    return sides
