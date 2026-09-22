"""Plan research intent before retrieval; never decide whether evidence passes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Protocol

from pydantic import ValidationError

from .models import InvestigationRequest, ResearchPlan


class PlanningError(ValueError):
    """The request or model response cannot safely define an investigation."""


class Planner(Protocol):
    def plan(self, request: InvestigationRequest) -> ResearchPlan: ...


_GENE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_PATHWAY_REQUEST = re.compile(r"\bpathways?\b|\bsignall?ing\b|패스웨이|신호\s*경로", re.I)
_TOOL_NAME = "submit_research_plan"
_PROMPT_PATH = Path(__file__).parent / "prompts" / "intent.md"
_LIMITATIONS = [
    "Source retrieval is not biological validation.",
    "Orthology is not conserved pathway activity.",
    "Unpaired cohorts cannot establish within-patient agreement.",
    "Descriptive agreement does not establish causality or clinical efficacy.",
    "RNA abundance, protein abundance, and protein activity are distinct endpoints.",
    "Missing biological evidence remains an unmet criterion or gap, not a positive finding.",
]


def _validate_genes(genes: list[str]) -> None:
    if any(not _GENE.fullmatch(gene) for gene in genes):
        raise PlanningError("Gene symbols must contain only letters, digits, underscores, or hyphens (maximum 64 characters).")
    if len(set(genes)) != len(genes):
        raise PlanningError("Gene symbols must be unique.")


def _input_genes(request: InvestigationRequest) -> list[str]:
    _validate_genes(request.genes)
    if request.pathway is not None:
        _validate_genes(request.pathway.genes)
        if request.genes and not set(request.pathway.genes).issubset(request.genes):
            raise PlanningError("Explicit genes must include every member of the supplied versioned pathway; clarify the requested scope.")
        return list(request.genes or request.pathway.genes)
    if _PATHWAY_REQUEST.search(request.question):
        raise PlanningError("A pathway request requires supplied pathway membership with an ID, source, version, and genes; membership cannot be invented.")
    return list(request.genes)


def _validated_plan(payload: Any) -> ResearchPlan:
    try:
        plan = ResearchPlan.model_validate(payload)
    except ValidationError as exc:
        if any(error['msg'] == "Value error, Requirement entities must be declared genes or the supplied pathway ID"
               for error in exc.errors(include_input=False, include_context=False)):
            raise PlanningError("The research plan does not satisfy the required schema: a requirement refers to an undeclared gene or pathway. No investigation was started.") from exc
        raise PlanningError("The research plan does not satisfy the required schema.") from exc
    except (TypeError, ValueError) as exc:
        raise PlanningError("The research plan does not satisfy the required schema.") from exc
    _validate_genes(plan.genes)
    return plan


def _check_preservation(request: InvestigationRequest, plan: ResearchPlan, genes: list[str]) -> None:
    if plan.question != request.question:
        raise PlanningError("The planner changed the user's question.")
    if genes and plan.genes != genes:
        raise PlanningError("The planner changed the explicit gene scope.")
    if not genes:
        # A model may extract symbols written in the question, but cannot infer
        # pathway members or add related genes from its own biological knowledge.
        for gene in plan.genes:
            if not re.search(r"(?<![A-Za-z0-9_-])" + re.escape(gene) + r"(?![A-Za-z0-9_-])", request.question, re.I):
                raise PlanningError("Inferred gene symbols must occur in the question; supply genes or versioned pathway membership explicitly.")
    if request.disease and plan.disease != request.disease:
        raise PlanningError("The planner changed the explicit disease scope.")
    if request.requirements and plan.requirements != request.requirements:
        raise PlanningError("The planner changed explicit requirements, including their biological axes or mandatory status.")
    if request.comparisons and plan.comparisons != request.comparisons:
        raise PlanningError("The planner changed explicit comparisons.")
    if plan.pathway != request.pathway:
        raise PlanningError("The planner changed or invented pathway membership.")


def _annotate_inferences(request: InvestigationRequest, plan: ResearchPlan, genes: list[str]) -> ResearchPlan:
    payload = plan.model_dump()
    assumptions = list(plan.assumptions)
    if not genes:
        assumptions.append("Gene symbols were extracted from the question and have not been independently resolved to biological identifiers.")
    if not request.disease and plan.disease:
        assumptions.append(f"Disease scope inferred from the question: {plan.disease}; this interpretation requires review.")
    if not request.requirements:
        assumptions.extend(
            f"Proposed criterion {item.id}: entity={item.entity}; species={item.species}; context={item.context}; modality={item.modality}; endpoint={item.endpoint}; condition={item.condition}; tissue={item.tissue}; host_species={item.host_species}; min_studies={item.min_studies}; required={item.required}. These choices are unverified interpretations of intent, not evidence."
            for item in plan.requirements
        )
    if not request.comparisons:
        for item in payload["comparisons"]:
            assumptions.append(
                f"Proposed comparison {item['id']} ({item['left']} versus {item['right']}); require_matched_subjects={item['require_matched_subjects']}. This interpretation requires review; missing cross-species, context-alignment, or normalization evidence remains a gap."
            )
            # A proposed mapping must never satisfy a machine-consumed basis
            # check. Keep the proposal visible, but only in unverified metadata.
            for field in ("cross_species_basis", "context_alignment_basis"):
                if item[field] is not None:
                    assumptions.append(
                        f"Unverified model proposal for comparison {item['id']} {field}: {item[field]}. This is a suggestion to investigate, not an established validation basis."
                    )
                item[field] = None
    payload["assumptions"] = list(dict.fromkeys(assumptions))
    payload["claims_to_avoid"] = list(dict.fromkeys([*_LIMITATIONS, *plan.claims_to_avoid]))
    return _validated_plan(payload)


class ExplicitPlanner:
    """Construct a plan from supplied criteria without a model or network call."""

    def plan(self, request: InvestigationRequest) -> ResearchPlan:
        genes = _input_genes(request)
        if not genes or not request.requirements:
            raise PlanningError("Explicit planning requires genes (or versioned pathway genes) and at least one evidence requirement.")
        return _validated_plan({
            "question": request.question,
            "genes": genes,
            "disease": request.disease,
            "requirements": [item.model_dump() for item in request.requirements],
            "comparisons": [item.model_dump() for item in request.comparisons],
            "pathway": request.pathway.model_dump() if request.pathway else None,
            "claims_to_avoid": list(_LIMITATIONS),
        })


class ClaudePlanner:
    """One bounded provider call; injected clients support offline tests.

    The coordinator, not the model, evaluates criteria after evidence arrives.
    The configured model is required; no fallback model or model retry is used.
    """

    def __init__(self, model: str | None = None, client: Any | None = None) -> None:
        self.model = (model or os.getenv("ANTHROPIC_MODEL", "")).strip()
        if not self.model:
            raise PlanningError("Set ANTHROPIC_MODEL to the provider model to use for planning.")
        if client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
            if not api_key:
                raise PlanningError("Set ANTHROPIC_API_KEY to enable Claude planning.")
            from anthropic import Anthropic
            client = Anthropic(api_key=api_key, max_retries=0, timeout=60.0)
        self.client = client

    def plan(self, request: InvestigationRequest) -> ResearchPlan:
        from anthropic import transform_schema

        genes = _input_genes(request)
        # This payload contains intent only. Retrieved text and evidence bundles
        # deliberately have no argument or route into this planning call.
        intent = {"request": request.model_dump(), "effective_explicit_genes": genes}
        response = self.client.messages.create(
            model=self.model,
            max_tokens=6000,
            system=_PROMPT_PATH.read_text(encoding="utf-8"),
            messages=[{"role": "user", "content": json.dumps(intent, ensure_ascii=False)}],
            tools=[{
                "name": _TOOL_NAME,
                "description": "Return an unassessed research plan preserving the supplied research intent.",
                "input_schema": transform_schema(ResearchPlan),
                "strict": True,
            }],
            # Some current models reject forced tool choice. Auto keeps this a
            # single bounded call; below, we still require exactly one valid plan.
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        )
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise PlanningError("Anthropic declined to create a research plan for this request. No investigation or data collection was started.")
        if stop_reason == "max_tokens":
            raise PlanningError("The model reached the planning token limit before completing its plan. No investigation was started.")
        if stop_reason != "tool_use":
            raise PlanningError("The planning response ended without a complete structured plan.")
        blocks = [item for item in getattr(response, "content", []) if getattr(item, "type", None) == "tool_use"]
        if len(blocks) != 1 or getattr(blocks[0], "name", None) != _TOOL_NAME:
            raise PlanningError("The planner must return exactly one research-plan tool result.")
        plan = _validated_plan(getattr(blocks[0], "input", None))
        _check_preservation(request, plan, genes)
        return _annotate_inferences(request, plan, genes)
