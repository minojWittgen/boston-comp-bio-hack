"""Conversational intake; only the server constructs executable contracts."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import time
import uuid

from coordinator.engine import execute, initial_state, now
from coordinator.models import ChatSubmission, IntakeDecision, InvestigationRequest, CONTEXTS, TERMINAL


def prepare_chat(submission: ChatSubmission, previous: dict | None = None) -> dict:
    if previous and previous["status"] not in TERMINAL:
        raise ValueError("Wait for the current investigation to finish before replying.")
    if submission.demo and previous:
        raise ValueError("Start a new conversation for the synthetic example.")
    messages = copy.deepcopy((previous or {}).get("chat", {}).get("messages", []))
    messages.append({"role": "user", "content": submission.prompt})
    if len(messages) > 20 or sum(len(m["content"]) for m in messages) > 24000:
        raise ValueError("This conversation has reached its limit. Start a new investigation.")
    state = initial_state(str(uuid.uuid4()), InvestigationRequest(intent=submission.prompt))
    state["contract_hash"] = None  # An execution contract does not exist during intake.
    state["chat"] = {"messages": messages, "demo": submission.demo,
                     "parent_id": previous["id"] if previous else None,
                     "previous_request": previous["request"] if previous else None,
                     "awaiting_confirmation": False,
                     "can_confirm": bool(previous and previous.get("chat", {}).get("awaiting_confirmation"))}
    return state


def criteria_preview(request: InvestigationRequest) -> str:
    lines = ["Here are the proposed comparison rules:"]
    for c in request.criteria:
        lines.append(
            f"• {c.description} — {c.context.replace('_', ' ')}, study {c.study_id}, {c.species}, {c.tissue}; "
            f"{c.feature} {', '.join(c.modalities)} {c.quantity}; {c.treatment} ({c.treatment_timepoint}) versus "
            f"{c.control} ({c.control_timepoint}); expected {c.expected_direction}; minimum absolute log₂ change "
            f"{c.min_abs_log2_fold_change:g}, at least {c.min_pairs} biological pairs, {c.confidence_level:.1%} "
            f"Student t interval. Modalities {'must be matched' if c.matched_modalities else 'may use different cohorts'}; "
            f"{'required' if c.required else 'optional'}. Rationale: {c.rationale}")
    lines.append('Reply “Use these criteria” to freeze these rules, or describe a change. Measurements and reviewed species mappings are still required for validation.')
    return "\n\n".join(lines)


async def execute_chat(state, save, provider, reasoner=None):
    started = time.monotonic()
    chat = state["chat"]

    async def message(text):
        chat["messages"].append({"role": "assistant", "content": text})
        chat["reply"] = text
        state["updated_at"] = now()
        await save(copy.deepcopy(state))

    try:
        state.update(status="running", stage="understanding_intent", updated_at=now())
        await save(copy.deepcopy(state))
        async with asyncio.timeout(state["request"]["budget"]["max_seconds"]):
            prompt = chat["messages"][-1]["content"]
            confirm = prompt.strip().rstrip(".! ").casefold() == "use these criteria"
            if chat["demo"]:
                payload = json.loads((Path(__file__).resolve().parents[1] / "examples/development-investigation.json").read_text())
                request = InvestigationRequest.model_validate(payload)
                await message("I’m running the synthetic example across in vitro, in vivo and patient contexts. The measurements and comparison rules are preset demonstration data, not biological evidence.")
            elif confirm and chat["can_confirm"]:
                request = InvestigationRequest.model_validate({**chat["previous_request"], "criteria_confirmed": True})
                await message("The displayed comparison rules are fixed. I’ll check which measurements and comparisons are available.")
            else:
                if reasoner is None:
                    raise RuntimeError("Chat needs the backend’s Claude API connection. It is disabled in this local session. You can still try the clearly labeled synthetic example.")
                # Never send thousands of measurements back through the intake model.
                previous = chat["previous_request"]
                context = ({k: previous[k] for k in ("intent", "genes", "disease", "criteria")} if previous else None)
                decision = IntakeDecision.model_validate(await reasoner.intake(chat["messages"], context))
                if decision.next_step != "propose_criteria" and decision.criteria:
                    raise ValueError("Intake returned numerical rules for a non-validation step.")
                request = InvestigationRequest(intent=decision.intent, genes=decision.genes, disease=decision.disease,
                                               phase="exploration" if decision.next_step == "explore" else "validation",
                                               criteria=decision.criteria, reference_required=decision.next_step == "explore")
                state["request"] = request.model_dump(mode="json")
                if decision.next_step == "explore" and not request.genes:
                    raise ValueError("Background exploration needs an identified gene; ask for clarification first.")
                if decision.next_step == "propose_criteria" and not request.criteria:
                    raise ValueError("Intake proposed an empty set of comparison rules.")
                if decision.next_step != "explore":
                    chat["awaiting_confirmation"] = decision.next_step == "propose_criteria"
                    response = criteria_preview(request) if chat["awaiting_confirmation"] else decision.message
                    state.update(status="needs_input", stage="conversation")
                    state["report"] = {"execution_status": "needs_input", "required_input": response,
                                       "contexts": {c: {"finding": "not_assessable"} for c in CONTEXTS}}
                    await message(response)
                    return state
                await message(decision.message)
            # This is the only transition from an intake draft to frozen execution inputs.
            state["request"] = request.model_dump(mode="json")
            state["contract_hash"] = request.digest()
            await save(copy.deepcopy(state))
            await execute(state, save, provider, reasoner)
            report = state.get("report") or {}
            interpretation = report.get("interpretation") or {}
            response = interpretation.get("summary")
            if not response:
                if chat["demo"] and state["status"] == "complete":
                    response = "The synthetic workflow completed. All three example comparisons passed the fixed numerical checks. These are fabricated measurements for demonstrating the software."
                else:
                    response = f"The investigation finished with {state['status']} execution. The evidence and unresolved checks are shown below."
            if request.phase == "exploration":
                response += "\n\nThis is background exploration; no numerical biological claim has been validated. What study measurements and comparison would you like to assess next?"
            if report.get("interpretation_status", "").startswith("disabled"):
                response += "\n\nModel interpretation is disabled in this local session."
            await message(response)
    except Exception as exc:
        state.update(status="partial" if isinstance(exc, TimeoutError) else "failed", stage="finished", updated_at=now())
        reason = "The conversation exceeded its time budget; unfinished work is not a biological negative." if isinstance(exc, TimeoutError) else str(exc)[:600]
        state["errors"].append({"stage": "chat", "reason": reason})
        if state.get("report"):
            state["report"]["execution_status"] = state["status"]
        await message(f"I couldn’t finish this request. {reason}")
    finally:
        if reasoner:
            state["usage"].update(model_calls=reasoner.calls, **reasoner.usage)
        state["elapsed_seconds"] = round(time.monotonic() - started, 3)
        # Previous request may contain data supplied through the structured API; no need to duplicate it forever.
        chat.pop("previous_request", None)
        chat.pop("can_confirm", None)
        await save(copy.deepcopy(state))
    return state
