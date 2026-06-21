"""LangGraph service-agent turn runner.

This module keeps the current GPT frame-agent behavior but expresses the
service-side inner loop as a LangGraph state machine. It is intentionally
standalone so it can be compared against the legacy runner without changing it.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, TypedDict

try:  # Imported lazily at module import so py_compile works without runtime deps.
    from langgraph.graph import END, START, StateGraph
except ModuleNotFoundError:  # pragma: no cover - depends on optional dependency.
    END = START = StateGraph = None  # type: ignore[assignment]

from experiments.gpt55_frame_service_runner.run_frame_agent import (
    call_service_model,
    canonical_tool_call_text,
    concise_text,
    detect_tool_call,
    is_strict_tool_call_response,
    is_visual_context_request,
    message_likely_needs_visual,
    normalize_calls,
    should_attach_frames_for_call,
    split_repeated_state_changes,
)

VISUAL_RESOLVE_INSTRUCTIONS = """
You are an internal GPT-5.5 visual resolver for an EgoBench service agent.

Use only the attached sampled video frames and the task/dialogue text in the
current input. Do not call tools. Do not invent database facts. Do not solve the
whole task. Your job is to preserve visual evidence as a compact hypothesis that
the service agent can later canonicalize with official database tools.

Return concise JSON only, with these keys:
- frame_status: "inspected" or "insufficient"
- visual_referents: array of objects for visible objects, ingredients, dishes,
  product packages, menu sections, locations, actions, pointing targets, OCR
  fragments, spatial relations, or ordinal references relevant to the request
- confidence: "high", "medium", or "low"
- ambiguity: short text describing unresolved visual alternatives
- tool_grounding_suggestions: array of generic read-only tool lookup ideas,
  such as checking official names, categories, prices, nutrition, recipes,
  ingredient lists, menu categories, or inventory before any mutation
- caution: short reminder of what must not be treated as a DB fact yet

For each visual_referent, include the referent type, best visual hypothesis,
supporting visual cues, likely stable/adjacent frame evidence if available, and
uncertainty. If the frames are ambiguous, still summarize what can be seen and
what should be verified with read-only tools. Never say frames are unavailable
when frames are attached to this call.

When the request uses page/spread/expanded-page ordinals on a physical menu,
build a chronological ordinal map of distinct visible menu views before naming
the target. Count every distinct opened page/spread state that is visible in the
sampled frames, including section-divider pages and item pages; do not merge a
divider page with the following item page just because they share a category.
Prefer stable fully visible frames over page-turn transition frames, but mention
reasonable alternate ordinal interpretations when the sampled frames are sparse.
For spatial phrases such as top-right, bottom-right, wooden bowl, casserole pot,
plate, or card, match the visible food image/container and its page position,
not only the nearest text block. If the ordinal cue and object/container cue
point to different dishes, return both candidates with the conflict explicit
instead of collapsing to one uncertain answer.
""".strip()


STATE_CHANGING_TOOL_PREFIXES = ("add_", "remove_", "update_", "set_", "clear_", "replace_", "delete_")
STATE_CHANGING_TOOLS = {
    "add_to_cart",
    "remove_from_cart",
    "clear_cart",
    "add_dish_to_order",
    "remove_dish_from_order",
    "clear_user_order",
    "add_set_meal_to_order",
    "remove_set_meal_from_order",
    "add_to_shopping_list",
    "remove_from_shopping_list",
    "delete_recipe_from_menu",
}
RETAIL_READ_ONLY_TOOLS = {
    "get_category",
    "get_price",
    "get_tax_rate",
    "get_discount",
    "get_nutrition",
    "get_allergens",
    "find_products_by_price_range",
    "find_products_by_country_of_origin",
    "find_products_by_taste",
    "find_products_by_nutritional_characteristic",
    "list_discounted_products",
}
RESTAURANT_READ_ONLY_TOOLS = {
    "get_dish_nutrition",
    "get_dish_allergens",
    "get_tax_rate",
    "get_dish_taste_profile",
    "get_dish_price",
    "get_dish_discount",
    "find_dishes_by_category",
    "find_dishes_by_nutritional_tag",
    "find_dishes_by_taste",
    "filter_dishes_by_price_range",
    "list_all_discounted_dishes",
    "get_set_meal_details",
    "find_set_meals_containing_dish",
}
KITCHEN_READ_ONLY_TOOLS = {
    "get_all_ingredient_names",
    "get_ingredients_by_category",
    "get_all_recipe_names",
    "get_recipe_ingredients",
    "get_cooking_steps",
    "get_current_menu",
}


class ServiceTurnState(TypedDict, total=False):
    service_history: list[dict[str, str]]
    local_tool_logs: list[dict[str, Any]]
    local_dialogue_logs: list[dict[str, Any]]
    trace: list[dict[str, Any]]
    latest_reply: str
    proposed_tool_calls: list[dict[str, Any]]
    approved_tool_calls: list[dict[str, Any]]
    latest_tool_results: list[dict[str, Any]]
    task_requirements: dict[str, Any]
    completion_errors: list[str]
    task_context_note: str
    visual_memory: str
    visual_resolve_attempted: bool
    agent_final_reply: str
    frames_sent_this_turn: bool
    force_attach_frames: bool
    last_attach_frames: bool
    context_prepared: bool
    frame_attached_calls: int
    visual_context_requests: int
    visual_context_recovery_attempts: int
    inner_input_tokens: int
    inner_output_tokens: int
    inner_calls: int
    inner_rounds: int
    tool_rounds: int
    repair_rounds: int
    stopped_reason: str


@dataclass
class LangGraphTurnConfig:
    turn: int
    latest_user_message: str
    max_inner_tool_rounds: int
    max_tool_calls: int
    image_detail: str
    frame_attach_policy: str
    max_visual_context_requests: int
    max_repair_rounds: int = 2
    task_instruction: str = ""
    image_description: str = ""
    enable_visual_resolve: bool = True
    scenario: str = ""
    scenario_number: int = 0


@dataclass
class LangGraphTurnResult:
    reply: str
    input_tokens: int
    output_tokens: int
    calls: int
    rounds: int
    tool_logs: list[dict[str, Any]]
    dialogue_logs: list[dict[str, Any]]
    frame_attached_calls: int
    visual_context_requests: int
    time: float
    updated_history: list[dict[str, str]]
    trace: list[dict[str, Any]]


class LangGraphFrameServiceAgent:
    def __init__(
        self,
        *,
        service_client: Any,
        instructions: str,
        frames: list[Any],
        db: Any,
        execute_tool: Any,
        check_tool_call: Any,
        prior_tool_logs: list[dict[str, Any]],
        config: LangGraphTurnConfig,
    ) -> None:
        if StateGraph is None:
            raise RuntimeError(
                "langgraph is not installed. Install it with `pip install -U langgraph` "
                "in the environment used for this experiment."
            )
        self.service_client = service_client
        self.instructions = instructions
        self.frames = frames
        self.db = db
        self.execute_tool = execute_tool
        self.check_tool_call = check_tool_call
        self.prior_tool_logs = prior_tool_logs
        self.config = config
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        graph = StateGraph(ServiceTurnState)
        graph.add_node("prepare_context", self._prepare_context)
        graph.add_node("think_and_plan", self._think_and_plan)
        graph.add_node("validate_action", self._validate_action)
        graph.add_node("execute_tools", self._execute_tools)
        graph.add_node("final_check", self._final_check)
        graph.add_node("final_reply", self._final_reply)
        graph.add_node("finalize_budget", self._finalize_budget)
        graph.add_node("stop_without_reply", self._stop_without_reply)

        graph.add_edge(START, "prepare_context")
        graph.add_edge("prepare_context", "think_and_plan")
        graph.add_conditional_edges(
            "think_and_plan",
            self._route_after_think_and_plan,
            {
                "validate_action": "validate_action",
                "final_check": "final_check",
                "stop_without_reply": "stop_without_reply",
            },
        )
        graph.add_conditional_edges(
            "validate_action",
            self._route_after_validate_action,
            {
                "think_and_plan": "think_and_plan",
                "execute_tools": "execute_tools",
                "stop_without_reply": "stop_without_reply",
            },
        )
        graph.add_conditional_edges(
            "execute_tools",
            self._route_after_execute,
            {
                "prepare_context": "prepare_context",
                "finalize_budget": "finalize_budget",
                "stop_without_reply": "stop_without_reply",
            },
        )
        graph.add_conditional_edges(
            "final_check",
            self._route_after_final_check,
            {
                "think_and_plan": "think_and_plan",
                "final_reply": "final_reply",
                "stop_without_reply": "stop_without_reply",
            },
        )
        graph.add_edge("final_reply", END)
        graph.add_edge("finalize_budget", END)
        graph.add_edge("stop_without_reply", END)
        return graph.compile()

    def run(self, service_history: list[dict[str, str]]) -> LangGraphTurnResult:
        start = time.time()
        initial_state: ServiceTurnState = {
            "service_history": [dict(msg) for msg in service_history],
            "local_tool_logs": [],
            "local_dialogue_logs": [],
            "trace": [],
            "latest_reply": "",
            "proposed_tool_calls": [],
            "approved_tool_calls": [],
            "latest_tool_results": [],
            "task_requirements": {},
            "completion_errors": [],
            "task_context_note": "",
            "visual_memory": "",
            "visual_resolve_attempted": False,
            "agent_final_reply": "",
            "frames_sent_this_turn": False,
            "force_attach_frames": False,
            "last_attach_frames": False,
            "context_prepared": False,
            "frame_attached_calls": 0,
            "visual_context_requests": 0,
            "visual_context_recovery_attempts": 0,
            "inner_input_tokens": 0,
            "inner_output_tokens": 0,
            "inner_calls": 0,
            "inner_rounds": 0,
            "tool_rounds": 0,
            "repair_rounds": 0,
            "stopped_reason": "",
        }
        final_state = self.graph.invoke(initial_state)
        return LangGraphTurnResult(
            reply=str(final_state.get("agent_final_reply") or final_state.get("latest_reply") or ""),
            input_tokens=int(final_state.get("inner_input_tokens", 0) or 0),
            output_tokens=int(final_state.get("inner_output_tokens", 0) or 0),
            calls=int(final_state.get("inner_calls", 0) or 0),
            rounds=int(final_state.get("inner_rounds", 0) or 0),
            tool_logs=list(final_state.get("local_tool_logs", [])),
            dialogue_logs=list(final_state.get("local_dialogue_logs", [])),
            frame_attached_calls=int(final_state.get("frame_attached_calls", 0) or 0),
            visual_context_requests=int(final_state.get("visual_context_requests", 0) or 0),
            time=time.time() - start,
            updated_history=list(final_state.get("service_history", [])),
            trace=list(final_state.get("trace", [])),
        )

    def _prepare_context(self, state: ServiceTurnState) -> dict[str, Any]:
        if bool(state.get("context_prepared", False)):
            return {
                "trace": self._append_trace(state, "prepare_context", already_prepared=True),
            }

        merged: ServiceTurnState = dict(state)
        for step in (self._init_task_state, self._prepare_db_context, self._visual_resolve):
            update = step(merged)
            merged.update(update)
        merged["context_prepared"] = True
        merged["trace"] = self._append_trace(merged, "prepare_context", already_prepared=False)
        return merged

    def _think_and_plan(self, state: ServiceTurnState) -> dict[str, Any]:
        return self._call_model(state)

    def _route_after_think_and_plan(self, state: ServiceTurnState) -> str:
        reply = str(state.get("latest_reply", ""))
        if is_visual_context_request(reply) or state.get("proposed_tool_calls"):
            return "validate_action"
        return "final_check"

    def _validate_action(self, state: ServiceTurnState) -> dict[str, Any]:
        if is_visual_context_request(str(state.get("latest_reply", ""))):
            return self._validate_visual_request_action(state)
        return self._validate_tool_calls(state)

    def _validate_visual_request_action(self, state: ServiceTurnState) -> dict[str, Any]:
        if self._can_retry_visual(state):
            return self._retry_with_visual(state)
        return self._deny_visual_request(state)

    def _route_after_validate_action(self, state: ServiceTurnState) -> str:
        if state.get("approved_tool_calls"):
            return "execute_tools"
        if int(state.get("repair_rounds", 0) or 0) <= self.config.max_repair_rounds:
            return "think_and_plan"
        return "stop_without_reply"

    def _final_check(self, state: ServiceTurnState) -> dict[str, Any]:
        return self._completion_verifier(state)

    def _route_after_final_check(self, state: ServiceTurnState) -> str:
        if not state.get("completion_errors"):
            return "final_reply"
        if int(state.get("repair_rounds", 0) or 0) <= self.config.max_repair_rounds:
            return "think_and_plan"
        return "stop_without_reply"

    def _init_task_state(self, state: ServiceTurnState) -> dict[str, Any]:
        task_text = self.config.latest_user_message
        requirements = self._infer_task_requirements(task_text)
        if not requirements:
            return {
                "task_requirements": {},
                "trace": self._append_trace(state, "init_task_state", requirements={}),
            }
        history = list(state.get("service_history", []))
        history.append(
            {
                "role": "user",
                "content": self._task_requirements_note(requirements),
            }
        )
        return {
            "service_history": history,
            "task_requirements": requirements,
            "trace": self._append_trace(state, "init_task_state", requirements=requirements),
        }

    def _prepare_db_context(self, state: ServiceTurnState) -> dict[str, Any]:
        return {
            "task_context_note": "",
            "trace": self._append_trace(state, "prepare_db_context", added=False, reason="db_content_access_disabled"),
        }

    def _visual_resolve(self, state: ServiceTurnState) -> dict[str, Any]:
        if not self._should_visual_resolve(state):
            return {
                "visual_resolve_attempted": False,
                "trace": self._append_trace(state, "visual_resolve", added=False),
            }

        prompt_parts = [
            "Internal visual resolver input.",
            f"Latest user message: {self._compact_text(self.config.latest_user_message, 1200)}",
        ]
        if self.config.image_description:
            prompt_parts.append(f"Scenario/video text summary: {self._compact_text(self.config.image_description, 1000)}")
        prompt_parts.append(
            "Inspect the attached frames and emit the requested compact JSON visual memory. "
            "This is a hypothesis for later DB grounding, not final proof."
        )
        visual_history = [{"role": "user", "content": "\n\n".join(prompt_parts)}]
        frame_header = (
            "VISUAL RESOLVER FRAMES ATTACHED. Inspect these sampled video frames and write "
            "a compact JSON visual memory. Do not request more visual context."
        )
        reply, input_tokens, output_tokens = call_service_model(
            self.service_client,
            instructions=VISUAL_RESOLVE_INSTRUCTIONS,
            service_history=visual_history,
            frames=self.frames,
            attach_frames=True,
            image_detail=self.config.image_detail,
            frame_header=frame_header,
        )
        visual_memory = str(reply or "{}")
        history = list(state.get("service_history", []))
        history.append(
            {
                "role": "user",
                "content": (
                    "Internal GPT-5.5 visual memory for this user turn:\n"
                    f"{visual_memory}\n\n"
                    "Use this as visual hypothesis only. Canonicalize names, fields, facts, "
                    "branch decisions, calculations, and state changes with official DB tools. "
                    "If this memory describes a visual boundary such as a menu section, shelf area, "
                    "box, foldout, region, or available subset, retrieve or verify that boundary's "
                    "candidate set with official read-only tools before applying global attribute "
                    "filters, rankings, mutations, or final claims. "
                    "Do not say frames are unavailable in this turn; these frames were already "
                    "processed into visual memory."
                ),
            }
        )
        print(f"👁️ [LangGraph Visual Resolve] {concise_text(visual_memory)}")
        return {
            "service_history": history,
            "visual_memory": visual_memory,
            "visual_resolve_attempted": True,
            "frame_attached_calls": int(state.get("frame_attached_calls", 0) or 0) + 1,
            "inner_input_tokens": int(state.get("inner_input_tokens", 0) or 0) + input_tokens,
            "inner_output_tokens": int(state.get("inner_output_tokens", 0) or 0) + output_tokens,
            "trace": self._append_trace(
                state,
                "visual_resolve",
                added=True,
                reply_chars=len(visual_memory),
            ),
        }

    def _should_visual_resolve(self, state: ServiceTurnState) -> bool:
        if not self.config.enable_visual_resolve:
            return False
        if bool(state.get("frames_sent_this_turn", False)):
            return False
        if not self.frames:
            return False
        if self.config.frame_attach_policy == "never":
            return False
        if self.config.frame_attach_policy == "each_turn":
            return True
        if self.config.frame_attach_policy == "first_turn":
            return self.config.turn == 0
        if self.config.frame_attach_policy == "auto":
            return message_likely_needs_visual(self._combined_task_text())
        return False

    def _append_trace(self, state: ServiceTurnState, event: str, **payload: Any) -> list[dict[str, Any]]:
        trace = list(state.get("trace", []))
        trace.append(
            {
                "event": event,
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                **payload,
            }
        )
        return trace

    def _call_model(self, state: ServiceTurnState) -> dict[str, Any]:
        attach_frames = should_attach_frames_for_call(
            self.config,
            turn=self.config.turn,
            latest_user_message=self.config.latest_user_message,
            frames_sent_this_turn=bool(state.get("frames_sent_this_turn", False)),
            force_attach=bool(state.get("force_attach_frames", False)),
        )
        frame_header = None
        if attach_frames:
            frame_header = (
                "VISUAL CONTEXT IS ATTACHED TO THIS MESSAGE. Inspect the chronological frames, "
                "identify the visual referent as best as possible, then call official read-only "
                "tools if database evidence is needed. Do not ask for more visual context in this "
                "assistant response."
            )
        instructions = self.instructions
        if str(state.get("visual_memory") or "").strip():
            instructions = (
                self.instructions
                + "\n\n## Internal Visual Memory Availability\n"
                "This LangGraph turn already ran an internal GPT-5.5 visual resolver on attached "
                "sampled frames. The resulting visual memory appears in the conversation as an "
                "internal note. Treat visual grounding for that referent as available from that "
                "memory even when frames are not attached to this specific service-call input. "
                "Do not ask for visual context again unless the user asks about a new visual "
                "referent that is not covered by the memory. Continue by using official read-only "
                "tools to canonicalize the visual hypothesis before any state change, "
                "calculation, or final DB-backed claim. If the visual memory defines a bounded "
                "candidate set such as an available menu section, shelf area, box, foldout, or "
                "region, retrieve or verify that boundary first and intersect later tag/ranking "
                "tools with that boundary. Do not replace a bounded visual subset with a global "
                "restaurant/catalog search."
            )
        reply, input_tokens, output_tokens = call_service_model(
            self.service_client,
            instructions=instructions,
            service_history=list(state.get("service_history", [])),
            frames=self.frames,
            attach_frames=attach_frames,
            image_detail=self.config.image_detail,
            frame_header=frame_header,
        )
        reply = str(reply or "[Empty model response]")
        print(f"🤖 LangGraph Agent: {reply}")
        is_tool, tool_call_obj = detect_tool_call(reply, self.check_tool_call)
        proposed_calls = normalize_calls(tool_call_obj) if is_tool else []
        return {
            "latest_reply": reply,
            "proposed_tool_calls": proposed_calls,
            "approved_tool_calls": [],
            "last_attach_frames": attach_frames,
            "frames_sent_this_turn": bool(state.get("frames_sent_this_turn", False)) or attach_frames,
            "force_attach_frames": False,
            "frame_attached_calls": int(state.get("frame_attached_calls", 0) or 0) + (1 if attach_frames else 0),
            "inner_input_tokens": int(state.get("inner_input_tokens", 0) or 0) + input_tokens,
            "inner_output_tokens": int(state.get("inner_output_tokens", 0) or 0) + output_tokens,
            "trace": self._append_trace(
                state,
                "call_model",
                attach_frames=attach_frames,
                is_tool=is_tool,
                visual_request=is_visual_context_request(reply),
                proposed_tool_count=len(proposed_calls),
            ),
        }

    def _route_after_model(self, state: ServiceTurnState) -> str:
        reply = str(state.get("latest_reply", ""))
        if is_visual_context_request(reply):
            if self._can_retry_visual(state):
                return "retry_with_visual"
            return "deny_visual_request"
        if state.get("proposed_tool_calls"):
            return "validate_tool_calls"
        return "completion_verifier"

    def _can_retry_visual(self, state: ServiceTurnState) -> bool:
        if self.config.frame_attach_policy == "never":
            return False
        if self.config.max_visual_context_requests <= 0:
            return False
        if int(state.get("visual_context_requests", 0) or 0) >= 1:
            return False
        if bool(state.get("last_attach_frames", False)):
            return int(state.get("visual_context_recovery_attempts", 0) or 0) < 1
        return int(state.get("visual_context_requests", 0) or 0) < self.config.max_visual_context_requests

    def _retry_with_visual(self, state: ServiceTurnState) -> dict[str, Any]:
        history = list(state.get("service_history", []))
        reply = str(state.get("latest_reply", ""))
        history.append({"role": "assistant", "content": reply})
        if bool(state.get("last_attach_frames", False)):
            note = (
                "Internal routing note: frames were already attached. Retry once with the same "
                "visual context. Inspect the frames and proceed without asking for more visual context."
            )
            recovery_attempts = int(state.get("visual_context_recovery_attempts", 0) or 0) + 1
        else:
            note = (
                "Internal routing note: visual context will be attached on the next retry. "
                "Inspect the frames and proceed with official tool calls when needed."
            )
            recovery_attempts = int(state.get("visual_context_recovery_attempts", 0) or 0)
        history.append({"role": "user", "content": note})
        print("🖼️ [LangGraph] Service requested visual context; retrying with frames.")
        return {
            "service_history": history,
            "force_attach_frames": True,
            "visual_context_requests": int(state.get("visual_context_requests", 0) or 0) + 1,
            "visual_context_recovery_attempts": recovery_attempts,
            "trace": self._append_trace(state, "retry_with_visual", note=note),
        }

    def _deny_visual_request(self, state: ServiceTurnState) -> dict[str, Any]:
        history = list(state.get("service_history", []))
        history.append({"role": "assistant", "content": str(state.get("latest_reply", ""))})
        note = (
            "Internal routing note: no additional visual context will be attached in this user turn. "
            "Use the already attached frames, internal GPT-5.5 visual memory if present, current "
            "visual hypothesis, and official tool results. Do not ask for visual context again and "
            "do not say frames/images are unavailable in this turn. If the visual evidence is "
            "insufficient, proceed with the best supported tool-based path. If the completion verifier "
            "named a missing official tool, emit strict JSON for that tool next. Provide a concise "
            "limitation only after the completion verifier allows a final reply."
        )
        history.append({"role": "user", "content": note})
        print("🖼️ [LangGraph] Denied repeated visual context request; asking model to continue from existing evidence.")
        return {
            "service_history": history,
            "repair_rounds": int(state.get("repair_rounds", 0) or 0) + 1,
            "trace": self._append_trace(state, "deny_visual_request", note=note),
        }

    def _route_after_visual_denial(self, state: ServiceTurnState) -> str:
        if int(state.get("repair_rounds", 0) or 0) <= self.config.max_repair_rounds:
            return "call_model"
        return "stop_without_reply"

    def _validate_tool_calls(self, state: ServiceTurnState) -> dict[str, Any]:
        proposed_calls = list(state.get("proposed_tool_calls", []))
        errors: list[str] = []
        if not is_strict_tool_call_response(str(state.get("latest_reply", ""))):
            errors.append("Tool-call output must be exactly one JSON value with no extra text.")
        for index, call in enumerate(proposed_calls, start=1):
            if not isinstance(call, dict):
                errors.append(f"call {index}: not a JSON object")
                continue
            tool_name = str(call.get("tool_name") or call.get("name") or "").strip()
            if not tool_name:
                errors.append(f"call {index}: missing tool_name")
            elif not hasattr(self.db, tool_name):
                errors.append(f"call {index}: unknown tool {tool_name!r}")
            params = call.get("parameters", call.get("arguments", {}))
            if not isinstance(params, dict):
                errors.append(f"call {index}: parameters must be an object")
        errors.extend(self._semantic_tool_errors(proposed_calls, state))
        if errors:
            history = list(state.get("service_history", []))
            history.append({"role": "assistant", "content": str(state.get("latest_reply", ""))})
            history.append(
                {
                    "role": "user",
                    "content": (
                        "Internal schema validator rejected your previous output:\n"
                        + "\n".join(f"- {err}" for err in errors)
                        + "\nRe-emit only valid official tool-call JSON, or answer if no tool is needed."
                    ),
                }
            )
            print(f"🧪 [LangGraph Validator] rejected tool calls: {errors}")
            return {
                "service_history": history,
                "approved_tool_calls": [],
                "repair_rounds": int(state.get("repair_rounds", 0) or 0) + 1,
                "trace": self._append_trace(state, "validate_tool_calls", approved=False, errors=errors),
            }

        safe_calls, repeated_calls = split_repeated_state_changes(
            proposed_calls,
            prior_tool_logs=self.prior_tool_logs,
            current_tool_logs=list(state.get("local_tool_logs", [])),
            latest_user_message=self.config.latest_user_message,
        )
        if repeated_calls:
            history = list(state.get("service_history", []))
            history.append({"role": "assistant", "content": canonical_tool_call_text(proposed_calls)})
            history.append(
                {
                    "role": "user",
                    "content": (
                        "Internal repeat guard blocked duplicate state-changing tool call(s):\n"
                        f"{canonical_tool_call_text(repeated_calls)}\n"
                        "Do not repeat completed mutations unless the user explicitly asks for more."
                    ),
                }
            )
            print(f"🛡️ [LangGraph Repeat Guard] blocked: {canonical_tool_call_text(repeated_calls)}")
            return {
                "service_history": history,
                "approved_tool_calls": safe_calls,
                "repair_rounds": int(state.get("repair_rounds", 0) or 0) + 1,
                "trace": self._append_trace(
                    state,
                    "validate_tool_calls",
                    approved=not repeated_calls,
                    repeated_calls=repeated_calls,
                    safe_call_count=len(safe_calls),
                ),
            }
        return {
            "approved_tool_calls": proposed_calls,
            "trace": self._append_trace(state, "validate_tool_calls", approved=True, call_count=len(proposed_calls)),
        }

    def _route_after_validation(self, state: ServiceTurnState) -> str:
        if state.get("approved_tool_calls"):
            return "execute_tools"
        if int(state.get("repair_rounds", 0) or 0) <= self.config.max_repair_rounds:
            return "call_model"
        return "stop_without_reply"

    def _execute_tools(self, state: ServiceTurnState) -> dict[str, Any]:
        calls = list(state.get("approved_tool_calls", []))
        current_calls = int(state.get("inner_calls", 0) or 0)
        if current_calls + len(calls) > self.config.max_tool_calls:
            return {
                "stopped_reason": "tool calls exceeded limit",
                "agent_final_reply": "[Interaction stopped: tool calls exceeded limit]",
                "trace": self._append_trace(state, "execute_tools", skipped=True, reason="tool_limit"),
            }
        print(f"🛠️ LangGraph Tool Call: {canonical_tool_call_text(calls)}")
        tool_results = self.execute_tool(self.db, calls)
        tool_logs = list(state.get("local_tool_logs", []))
        tool_logs.append({"turn": self.config.turn, "calls": calls, "results": tool_results})
        combined_result = "; ".join(res.get("content", str(res)) for res in tool_results)
        history = list(state.get("service_history", []))
        history.append({"role": "assistant", "content": canonical_tool_call_text(calls)})
        history.append({"role": "user", "content": f"Tool execution result: {combined_result}"})
        return {
            "service_history": history,
            "local_tool_logs": tool_logs,
            "latest_tool_results": tool_results,
            "inner_calls": current_calls + len(calls),
            "tool_rounds": int(state.get("tool_rounds", 0) or 0) + 1,
            "proposed_tool_calls": [],
            "approved_tool_calls": [],
            "trace": self._append_trace(
                state,
                "execute_tools",
                call_count=len(calls),
                result_count=len(tool_results),
            ),
        }

    def _route_after_execute(self, state: ServiceTurnState) -> str:
        if state.get("agent_final_reply"):
            return "stop_without_reply"
        if int(state.get("tool_rounds", 0) or 0) >= self.config.max_inner_tool_rounds:
            return "finalize_budget"
        return "prepare_context"

    def _completion_verifier(self, state: ServiceTurnState) -> dict[str, Any]:
        errors = self._completion_errors(state)
        if not errors:
            return {
                "completion_errors": [],
                "trace": self._append_trace(state, "completion_verifier", approved=True),
            }
        history = list(state.get("service_history", []))
        latest_reply = str(state.get("latest_reply", ""))
        history.append({"role": "assistant", "content": latest_reply})
        history.append(
            {
                "role": "user",
                "content": (
                    "Internal completion verifier rejected the previous final reply because required "
                    "task steps are still incomplete:\n"
                    + "\n".join(f"- {err}" for err in errors)
                    + "\nContinue from the current tool evidence. Do not repeat completed state changes. "
                    "If a missing official tool or tool family is named above, the next assistant message "
                    "MUST be strict JSON for the smallest needed tool call. Do not answer or explain before "
                    "trying an available official tool. Do not request visual context again when internal "
                    "visual memory or attached-frame evidence already exists. Explain only after the named "
                    "official tools have been tried and failed to support the requested missing evidence."
                ),
            }
        )
        print(f"🧭 [LangGraph Completion] rejected final reply: {errors}")
        return {
            "service_history": history,
            "completion_errors": errors,
            "repair_rounds": int(state.get("repair_rounds", 0) or 0) + 1,
            "trace": self._append_trace(state, "completion_verifier", approved=False, errors=errors),
        }

    def _route_after_completion_verifier(self, state: ServiceTurnState) -> str:
        if not state.get("completion_errors"):
            return "final_reply"
        if int(state.get("repair_rounds", 0) or 0) <= self.config.max_repair_rounds:
            return "call_model"
        return "stop_without_reply"

    def _final_reply(self, state: ServiceTurnState) -> dict[str, Any]:
        reply = str(state.get("latest_reply") or "")
        print(f"💬 LangGraph Agent Reply: {concise_text(reply)}")
        history = list(state.get("service_history", []))
        history.append({"role": "assistant", "content": reply})
        dialogue_logs = list(state.get("local_dialogue_logs", []))
        dialogue_logs.append({"role": "agent", "turn": self.config.turn, "content": reply})
        return {
            "service_history": history,
            "local_dialogue_logs": dialogue_logs,
            "agent_final_reply": reply,
            "inner_rounds": int(state.get("inner_rounds", 0) or 0) + 1,
            "trace": self._append_trace(state, "final_reply"),
        }

    def _finalize_budget(self, state: ServiceTurnState) -> dict[str, Any]:
        history = list(state.get("service_history", []))
        history.append(
            {
                "role": "user",
                "content": (
                    "Internal budget note: the tool-round budget for this user turn is exhausted. "
                    "Do not call more tools. Produce one concise final reply using only available evidence."
                ),
            }
        )
        reply, input_tokens, output_tokens = call_service_model(
            self.service_client,
            instructions=self.instructions,
            service_history=history,
            frames=self.frames,
            attach_frames=False,
            image_detail=self.config.image_detail,
            frame_header=None,
        )
        reply = str(reply or "[Empty model response]")
        is_tool, _ = detect_tool_call(reply, self.check_tool_call)
        if is_tool or is_visual_context_request(reply):
            reply = (
                "I could not complete the request within the internal tool-round budget. "
                "The available evidence is incomplete, so I cannot give a reliable final answer."
            )
        print(f"💬 LangGraph Agent Budget Reply: {concise_text(reply)}")
        history.append({"role": "assistant", "content": reply})
        dialogue_logs = list(state.get("local_dialogue_logs", []))
        dialogue_logs.append({"role": "agent", "turn": self.config.turn, "content": reply})
        return {
            "service_history": history,
            "local_dialogue_logs": dialogue_logs,
            "agent_final_reply": reply,
            "inner_rounds": int(state.get("inner_rounds", 0) or 0) + 1,
            "inner_input_tokens": int(state.get("inner_input_tokens", 0) or 0) + input_tokens,
            "inner_output_tokens": int(state.get("inner_output_tokens", 0) or 0) + output_tokens,
            "trace": self._append_trace(state, "finalize_budget"),
        }

    def _stop_without_reply(self, state: ServiceTurnState) -> dict[str, Any]:
        reason = str(state.get("stopped_reason") or "no user-visible reply")
        reply = str(state.get("agent_final_reply") or f"[Interaction stopped: {reason}]")
        print(f"🛑 [LangGraph] {reply}")
        return {
            "agent_final_reply": reply,
            "stopped_reason": reason,
            "trace": self._append_trace(state, "stop_without_reply", reason=reason),
        }

    def _infer_task_requirements(self, text: str) -> dict[str, Any]:
        value = str(text or "").lower()
        requirements: dict[str, Any] = {}
        if "shopping list" in value and "cart" in value and re.search(r"\bmissing\b|缺失|没.*加", value):
            requirements["shopping_cart_reconcile"] = True
        final_compute = self._infer_final_compute_tool(value)
        if final_compute:
            requirements["final_compute"] = final_compute
        if "sugar" in value and ("allergen" in value or "nuts" in value or "nut" in value):
            requirements["compound_branch_requires_allergen_evidence"] = True
        if self._current_request_explicitly_requests_state_change(value):
            if self._current_request_has_conditional_state_change(value):
                requirements["conditional_state_change"] = True
            else:
                requirements["expects_state_change"] = True
        return requirements

    def _current_request_has_conditional_state_change(self, value: str) -> bool:
        text = str(value or "").lower()
        if not re.search(r"\b(if|when|unless)\b|如果|若|除非", text):
            return False
        if not self._current_request_explicitly_requests_state_change(text):
            return False
        mutation_word = r"\b(add|remove|clear|update|replace|delete|buy|purchase)\b|加入|添加|移除|删除|更新|下单"
        fallback_branch_with_mutation = re.search(
            r"\b(otherwise|else)\b.{0,160}(?:" + mutation_word + r")|(?:如果不|否则).{0,160}(?:"
            + mutation_word
            + r")",
            text,
        )
        return not bool(fallback_branch_with_mutation)

    def _current_request_explicitly_requests_state_change(self, value: str) -> bool:
        text = str(value or "").lower()
        read_only_selection_intent = any(
            phrase in text
            for phrase in (
                "select a restaurant",
                "choose a restaurant",
                "recommend a restaurant",
                "which restaurant",
                "more suitable restaurant",
                "suitable restaurant",
                "better fit",
                "help me select",
                "help me choose",
                "help me figure out which",
                "could you help me select",
                "could you help me choose",
                "can you help me select",
                "can you help me choose",
                "able to order",
                "must be able to order",
                "whether i can order",
            )
        )
        explicit_mutation_verb = bool(
            re.search(r"\badd\b|\bremove\b|\bclear\b|\bupdate\b|\breplace\b|\bdelete\b|\bbuy\b|\bpurchase\b|\bplace an order for\b", text)
        )
        if read_only_selection_intent and not explicit_mutation_verb:
            return False
        mutation_patterns = [
            r"\badd\b.{0,120}\b(?:cart|order|shopping list)\b",
            r"\b(?:put|place)\b.{0,80}\b(?:in|into|to)\b.{0,40}\b(?:cart|order|shopping list)\b",
            r"\bplace an order for\b.{0,80}\b(?:item|product|dish|meal|portion|serving|pizza|pasta|rice|dessert|drink|coffee|tea)\b",
            r"\b(?:remove|delete|clear|update|replace|cancel)\b.{0,120}\b(?:cart|order|shopping list|menu)\b",
            r"\b(?:buy|purchase)\b.{0,80}\b(?:it|this|one|item|product|dish|meal|cookie|cheese|drink)\b",
            r"\b(?:add|remove|delete|clear|update|replace)\b.{0,80}\b(?:item|product|dish|meal|recipe)\b",
        ]
        if any(re.search(pattern, text) for pattern in mutation_patterns):
            return True
        chinese_markers = ("加入购物车", "加到购物车", "加购", "加入订单", "加到订单", "下单", "移除", "删除", "清空", "更新订单")
        if any(marker in text for marker in chinese_markers):
            return True
        return False

    def _infer_final_compute_tool(self, value: str) -> str | None:
        if "total tax" in value or "calculate the tax" in value or "compute total tax" in value:
            return self._first_available_tool(["compute_total_tax"])
        payment_patterns = (
            "total payment",
            "total payable",
            "amount payable",
            "final amount",
            "total amount",
            "total cost",
            "total price",
            "after discount",
            "after applying discounts",
        )
        if any(pattern in value for pattern in payment_patterns):
            return self._first_available_tool(["compute_total_payment"])
        nutrition_pattern = re.search(
            r"total\s+(?:grams?\s+of\s+)?(?:dietary\s+)?"
            r"(?:fiber|fibre|protein|fat|carbohydrate|carbohydrates|carbs|sugar|sodium|calcium|calorie|calories|nutrition)",
            value,
        )
        if nutrition_pattern or "calculate the nutrition" in value:
            return self._first_available_tool(["compute_total_nutrition", "compute_total_nutritions"])
        return None

    def _first_available_tool(self, names: list[str]) -> str | None:
        for name in names:
            if hasattr(self.db, name):
                return name
        return None

    def _combined_task_text(self) -> str:
        return "\n".join(
            part
            for part in (
                self.config.latest_user_message,
                self.config.image_description,
            )
            if str(part or "").strip()
        )

    def _db_context_note(self) -> str:
        return ""

    def _order_db_context_note(self, restaurants: dict[str, Any]) -> str:
        return ""

    def _compact_text(self, text: str, limit: int) -> str:
        compact = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(compact) <= limit:
            return compact
        return compact[: max(0, limit - 3)].rstrip() + "..."

    def _task_requirements_note(self, requirements: dict[str, Any]) -> str:
        lines = [
            "Internal LangGraph task checklist. Track these requirements explicitly and do not give a final reply until they are satisfied or proven impossible by official tools:"
        ]
        if requirements.get("compound_branch_requires_allergen_evidence"):
            lines.append("- Compound branch: if a condition requires both sugar and nuts/allergen evidence, do not execute that branch after checking only sugar.")
        if requirements.get("expects_state_change"):
            lines.append("- State change: perform the requested add/remove/update action for the active branch before final reply.")
        if requirements.get("conditional_state_change"):
            lines.append(
                "- Conditional state change: first prove the branch condition with official tools. "
                "Execute add/remove/update only if the condition is true; if the condition is false, "
                "do not mutate state and explain that the condition was not triggered."
            )
        if requirements.get("shopping_cart_reconcile"):
            lines.append("- Shopping-list/cart reconciliation: call the relevant shopping-list and cart tools, add missing or insufficient items, then continue.")
        final_compute = requirements.get("final_compute")
        if final_compute:
            lines.append(f"- Final calculation: call `{final_compute}` after all required cart/order mutations are complete.")
        return "\n".join(lines)

    def _tool_names(self, logs: list[dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for entry in logs:
            for call in entry.get("calls", []):
                if isinstance(call, dict):
                    names.append(str(call.get("tool_name") or call.get("name") or ""))
        return names

    def _semantic_tool_errors(self, calls: list[dict[str, Any]], state: ServiceTurnState) -> list[str]:
        errors: list[str] = []
        requirements = dict(state.get("task_requirements", {}))
        tool_names = self._tool_names(list(state.get("local_tool_logs", [])))
        proposed_names = [str(call.get("tool_name") or call.get("name") or "") for call in calls if isinstance(call, dict)]
        if requirements.get("compound_branch_requires_allergen_evidence"):
            entering_then_branch = any(
                name in {
                    "find_products_by_country_of_origin",
                    "find_products_by_price_range",
                    "add_to_cart",
                    "add_dish_to_order",
                    "add_set_meal_to_order",
                }
                for name in proposed_names
            )
            has_allergen_evidence = any("allergen" in name.lower() for name in tool_names)
            has_allergen_tool = any("allergen" in name.lower() for name in dir(self.db))
            if has_allergen_tool and entering_then_branch and not has_allergen_evidence:
                errors.append(
                    "compound branch requires nuts/allergen evidence, but no allergen-related official tool result exists yet; do not enter the branch based only on sugar or nutrition evidence."
                )
        if len(calls) > 12:
            names = [str(call.get("tool_name") or call.get("name") or "") for call in calls if isinstance(call, dict)]
            unique_names = set(names)
            broad_read_only = unique_names <= {
                "get_price",
                "get_tax_rate",
                "get_discount",
                "get_category",
                "get_nutrition",
                "get_product_price",
                "get_dish_price",
                "get_dish_nutrition",
                "get_tax_rate",
            }
            if broad_read_only:
                errors.append(
                    f"tool batch has {len(calls)} read-only fact calls, which is too broad for one decision point; shrink the candidate set first using category/country/price/list constraints, then batch only the remaining small set."
                )
        errors.extend(self._speculative_order_restaurant_probe_errors(calls, state))
        errors.extend(self._visual_boundary_tool_errors(proposed_names, state))
        errors.extend(self._state_change_permission_errors(calls, state))
        for index, call in enumerate(calls, start=1):
            if not isinstance(call, dict):
                continue
            errors.extend(self._canonical_action_errors(call, index))
        return errors

    def _speculative_order_restaurant_probe_errors(
        self, calls: list[dict[str, Any]], state: ServiceTurnState
    ) -> list[str]:
        if self._scenario_kind() != "order":
            return []
        restaurant_names = {
            str((call.get("parameters") or call.get("arguments") or {}).get("restaurant_name") or "").strip()
            for call in calls
            if isinstance(call, dict) and isinstance(call.get("parameters") or call.get("arguments") or {}, dict)
        }
        restaurant_names.discard("")
        if len(restaurant_names) <= 1:
            return []
        supported = self._successful_restaurant_names_from_tool_history(state)
        unsupported = sorted(name for name in restaurant_names if name not in supported)
        if not unsupported:
            return []
        return [
            "do not batch-probe multiple order restaurant_name values when some names are not already "
            "supported by successful official tool results in this dialogue. Query only the restaurant "
            "you can ground next, or ask the user to confirm the exact restaurant_name before querying "
            "the unsupported restaurant namespace. Unsupported in this batch: "
            + ", ".join(repr(name) for name in unsupported)
        ]

    def _successful_restaurant_names_from_tool_history(self, state: ServiceTurnState) -> set[str]:
        supported: set[str] = set()
        for entry in state.get("local_tool_logs", []):
            calls = entry.get("calls", [])
            results = entry.get("results", [])
            if not isinstance(calls, list) or not isinstance(results, list):
                continue
            for call, result in zip(calls, results):
                if not isinstance(call, dict):
                    continue
                params = call.get("parameters") or call.get("arguments") or {}
                if not isinstance(params, dict):
                    continue
                restaurant_name = str(params.get("restaurant_name") or "").strip()
                if not restaurant_name:
                    continue
                parsed = self._parse_tool_result_content(result)
                if self._tool_result_has_positive_evidence(parsed):
                    supported.add(restaurant_name)
        return supported

    def _tool_result_has_positive_evidence(self, parsed: Any) -> bool:
        if not isinstance(parsed, dict):
            return False
        if parsed.get("status") == "success":
            matching = parsed.get("matching_dishes") or parsed.get("matching_set_meals")
            if isinstance(matching, dict) and matching:
                return True
        for key in ("dishes", "set_meals", "items"):
            value = parsed.get(key)
            if isinstance(value, list) and len(value) > 0:
                return True
        if "total_tax" in parsed or "total" in parsed or "total_nutrition" in parsed:
            return True
        return False

    def _state_change_permission_errors(self, calls: list[dict[str, Any]], state: ServiceTurnState) -> list[str]:
        requirements = dict(state.get("task_requirements", {}))
        if requirements.get("expects_state_change"):
            return []
        blocked = [
            str(call.get("tool_name") or call.get("name") or "")
            for call in calls
            if isinstance(call, dict) and self._is_state_changing_tool(str(call.get("tool_name") or call.get("name") or ""))
        ]
        if not blocked:
            return []
        if requirements.get("conditional_state_change"):
            status = self._conditional_state_change_status(state)
            if status == "true":
                return []
            if status == "false":
                return [
                    "conditional branch is false according to official tool evidence; the state-changing "
                    "action must not be executed. Answer that the condition was not triggered. Blocked "
                    "tool(s): "
                    + ", ".join(blocked)
                ]
            if status == "unknown":
                return [
                    "conditional state-changing action is not allowed until the branch condition has been "
                    "decided with official read-only or compute tool evidence. Blocked tool(s): "
                    + ", ".join(blocked)
                ]
            if status == "unsupported":
                return []
        return [
            "state-changing tool call is not allowed for the current user request because the user asked for "
            "identification, checking, comparison, recommendation, or restaurant selection only. Do not add, "
            "remove, clear, update, or replace cart/order/list/menu contents unless the current user message "
            "explicitly asks for that action. Answer from read-only evidence instead. Blocked tool(s): "
            + ", ".join(blocked)
        ]

    def _conditional_state_change_status(self, state: ServiceTurnState) -> str:
        condition = self._extract_total_nutrition_threshold_condition(self.config.latest_user_message)
        if condition is None:
            return "unsupported"
        metric_field, operator, threshold = condition
        value = self._latest_total_nutrition_value(state, metric_field)
        if value is None:
            return "unknown"
        if self._compare_threshold(value, operator, threshold):
            return "true"
        return "false"

    def _extract_total_nutrition_threshold_condition(self, text: str) -> tuple[str, str, float] | None:
        value = str(text or "").lower()
        metric_pattern = (
            r"(?P<metric>dietary\s+fiber|fibre|fiber|protein|fat|carbohydrates|carbohydrate|"
            r"carbs|sugar|sodium|calories|calorie|nutrition)"
        )
        operator_pattern = (
            r"(?P<operator>less\s+than|below|under|greater\s+than|more\s+than|above|over|"
            r"at\s+least|no\s+less\s+than|<=|>=|<|>)"
        )
        match = re.search(
            r"(?:total\s+)?(?:grams?\s+of\s+)?"
            + metric_pattern
            + r".{0,140}?"
            + operator_pattern
            + r"\s*(?P<threshold>\d+(?:\.\d+)?)",
            value,
        )
        if not match:
            return None
        metric = re.sub(r"\s+", " ", match.group("metric")).strip()
        metric_fields = {
            "dietary fiber": "fiber_g",
            "fiber": "fiber_g",
            "fibre": "fiber_g",
            "protein": "protein_g",
            "fat": "fat_g",
            "carbohydrate": "carbs_g",
            "carbohydrates": "carbs_g",
            "carbs": "carbs_g",
            "sugar": "sugar_g",
            "sodium": "sodium_mg",
            "calorie": "calories_kcal",
            "calories": "calories_kcal",
            "nutrition": "",
        }
        metric_field = metric_fields.get(metric)
        if not metric_field:
            return None
        return metric_field, match.group("operator"), float(match.group("threshold"))

    def _latest_total_nutrition_value(self, state: ServiceTurnState, metric_field: str) -> float | None:
        for entry in reversed(list(state.get("local_tool_logs", []))):
            calls = entry.get("calls", [])
            results = entry.get("results", [])
            if not isinstance(calls, list) or not isinstance(results, list):
                continue
            for call, result in reversed(list(zip(calls, results))):
                if not isinstance(call, dict):
                    continue
                tool_name = str(call.get("tool_name") or call.get("name") or "")
                if tool_name not in {"compute_total_nutrition", "compute_total_nutritions"}:
                    continue
                parsed = self._parse_tool_result_content(result)
                if not isinstance(parsed, dict):
                    continue
                total_nutrition = parsed.get("total_nutrition")
                if not isinstance(total_nutrition, dict) or metric_field not in total_nutrition:
                    continue
                try:
                    return float(total_nutrition[metric_field])
                except (TypeError, ValueError):
                    continue
        return None

    def _compare_threshold(self, value: float, operator: str, threshold: float) -> bool:
        normalized = re.sub(r"\s+", " ", str(operator or "").lower()).strip()
        if normalized in {"less than", "below", "under", "<"}:
            return value < threshold
        if normalized in {"greater than", "more than", "above", "over", ">"}:
            return value > threshold
        if normalized in {"at least", "no less than", ">="}:
            return value >= threshold
        if normalized == "<=":
            return value <= threshold
        return False

    def _is_state_changing_tool(self, tool_name: str) -> bool:
        name = str(tool_name or "")
        return name in STATE_CHANGING_TOOLS or name.startswith(STATE_CHANGING_TOOL_PREFIXES)

    def _visual_boundary_tool_errors(self, proposed_names: list[str], state: ServiceTurnState) -> list[str]:
        if not self._has_visual_menu_boundary(state):
            return []
        if self._has_boundary_tool_evidence(state):
            return []
        proposed = set(proposed_names)
        boundary_tools = {"find_dishes_by_category", "get_set_meal_details", "find_set_meals_containing_dish"}
        if proposed & boundary_tools:
            return []
        global_dish_filters = {
            "find_dishes_by_nutritional_tag",
            "find_dishes_by_taste",
            "filter_dishes_by_price_range",
            "list_all_discounted_dishes",
        }
        per_dish_fact_tools = {
            "get_dish_nutrition",
            "get_dish_allergens",
            "get_tax_rate",
            "get_dish_taste_profile",
            "get_dish_price",
            "get_dish_discount",
        }
        if proposed & (global_dish_filters | per_dish_fact_tools):
            return [
                "visual menu/section boundary is active, but no official boundary candidate set has been retrieved yet; call a category/menu/set-meal list tool for the visually bounded section before global tag, taste, price, ranking, mutation, or final-answer tools."
            ]
        return []

    def _has_boundary_tool_evidence(self, state: ServiceTurnState) -> bool:
        tool_names = set(self._tool_names(list(state.get("local_tool_logs", []))))
        return bool(tool_names & {"find_dishes_by_category", "get_set_meal_details", "find_set_meals_containing_dish"})

    def _has_visual_menu_boundary(self, state: ServiceTurnState) -> bool:
        visual_memory = str(state.get("visual_memory") or "").lower()
        request = str(self.config.latest_user_message or "").lower()
        if not visual_memory:
            return False
        visual_boundary = any(
            term in visual_memory
            for term in (
                "menu_section",
                "section",
                "category",
                "box",
                "foldout",
                "region",
                "available subset",
                "boundary",
            )
        )
        request_boundary = any(
            term in request
            for term in (
                "section",
                "category",
                "box",
                "foldout",
                "region",
                "area",
                "only",
                "available",
                "among",
                "within",
            )
        )
        dish_context = any(term in request for term in ("dish", "menu", "restaurant", "meal", "item"))
        return visual_boundary and request_boundary and dish_context and self._has_any_db_tool(["find_dishes_by_category"])

    def _canonical_action_errors(self, call: dict[str, Any], index: int) -> list[str]:
        params = call.get("parameters", call.get("arguments", {}))
        if not isinstance(params, dict):
            return []
        return []

    def _completion_errors(self, state: ServiceTurnState) -> list[str]:
        requirements = dict(state.get("task_requirements", {}))
        logs = list(state.get("local_tool_logs", []))
        tool_names = self._tool_names(logs)
        errors: list[str] = []
        if not requirements:
            errors.extend(self._visual_identity_completion_errors(state, tool_names))
            errors.extend(self._visual_boundary_completion_errors(state))
            return errors
        if requirements.get("expects_state_change") and not any(self._is_state_changing_tool(name) for name in tool_names):
            errors.append("requested state-changing action has not been executed.")
        if requirements.get("conditional_state_change") and not any(self._is_state_changing_tool(name) for name in tool_names):
            status = self._conditional_state_change_status(state)
            if status == "unknown":
                errors.append(
                    "conditional state-changing branch has not been decided with official tool evidence."
                )
        if requirements.get("shopping_cart_reconcile"):
            if "get_shopping_list" not in tool_names:
                errors.append("shopping list has not been checked with get_shopping_list.")
            if "get_cart" not in tool_names:
                errors.append("cart has not been checked with get_cart before reconciliation.")
        final_compute = requirements.get("final_compute")
        if final_compute and final_compute not in tool_names:
            errors.append(f"final requested calculation `{final_compute}` has not been called.")
        errors.extend(self._visual_identity_completion_errors(state, tool_names))
        errors.extend(self._visual_boundary_completion_errors(state))
        return errors

    def _visual_identity_completion_errors(self, state: ServiceTurnState, tool_names: list[str]) -> list[str]:
        if not str(state.get("visual_memory") or "").strip():
            return []
        latest_reply = str(state.get("latest_reply") or "")
        if is_visual_context_request(latest_reply) or detect_tool_call(latest_reply, self.check_tool_call)[0]:
            return []
        current_request = str(self.config.latest_user_message or "").lower()
        if not self._is_visual_identity_request(current_request):
            return []
        errors: list[str] = []
        scenario = self._scenario_kind()
        if (
            scenario == "kitchen"
            and "ingredient" in current_request
            and hasattr(self.db, "get_all_ingredient_names")
            and "get_all_ingredient_names" not in tool_names
        ):
            errors.append(
                "visual ingredient identity has not been canonicalized with `get_all_ingredient_names`; "
                "call the official read-only name-list tool before giving a final ingredient identity."
            )
        if (
            scenario == "retail"
            and any(term in current_request for term in ("product", "item", "package", "box"))
            and self._has_any_db_tool(sorted(RETAIL_READ_ONLY_TOOLS))
            and not any(name in RETAIL_READ_ONLY_TOOLS for name in tool_names)
        ):
            errors.append(
                "visual product/item identity has not been grounded with an official retail read-only tool; "
                "next emit strict JSON for one of `get_category`, `get_price`, `get_nutrition`, "
                "`find_products_by_price_range`, `find_products_by_taste`, or another available retail "
                "read-only lookup before giving a final product identity."
            )
        if (
            scenario in {"restaurant", "order"}
            and any(term in current_request for term in ("dish", "menu", "meal", "category", "section", "restaurant", "drink", "item"))
            and self._has_any_db_tool(sorted(RESTAURANT_READ_ONLY_TOOLS))
            and not any(name in RESTAURANT_READ_ONLY_TOOLS for name in tool_names)
        ):
            if scenario == "order":
                tool_hint = (
                    "next emit strict JSON for `find_dishes_by_category` with exact `restaurant_name` and "
                    "`category`, or for `get_dish_price`/`get_dish_nutrition` with exact `restaurant_name` "
                    "and `dish_name`, before giving a final restaurant/menu identity."
                )
            else:
                tool_hint = (
                    "next emit strict JSON for `find_dishes_by_category`, `get_dish_price`, "
                    "`get_dish_nutrition`, or another available read-only dish/menu lookup before giving "
                    "a final dish/menu identity."
                )
            errors.append(
                "visual dish/menu identity has not been grounded with an official read-only dish/menu tool; "
                + tool_hint
            )
        return errors

    def _scenario_kind(self) -> str:
        scenario = str(getattr(self.config, "scenario", "") or "").strip().lower()
        if scenario:
            return scenario
        if hasattr(self.db, "add_to_cart"):
            return "retail"
        if hasattr(self.db, "get_all_ingredient_names") or hasattr(self.db, "get_all_recipe_names"):
            return "kitchen"
        if hasattr(self.db, "find_dishes_by_category") or hasattr(self.db, "add_dish_to_order"):
            return "restaurant"
        return ""

    def _has_any_db_tool(self, names: list[str]) -> bool:
        return any(hasattr(self.db, name) for name in names)

    def _is_visual_identity_request(self, text: str) -> bool:
        value = str(text or "").lower()
        if message_likely_needs_visual(value):
            return True
        has_identity_intent = bool(
            re.search(r"\b(identify|name|recognize|recognise|what|which|find|tell|determine)\b", value)
        )
        has_db_entity = any(
            term in value
            for term in (
                "ingredient",
                "product",
                "dish",
                "item",
                "recipe",
                "menu",
                "food",
            )
        )
        has_visual_anchor = any(
            term in value
            for term in (
                "visible",
                "shown",
                "left",
                "right",
                "top",
                "bottom",
                "above",
                "below",
                "tray",
                "board",
                "shelf",
                "menu",
                "pointed",
                "selected",
                "placed",
            )
        )
        return has_identity_intent and has_db_entity and has_visual_anchor

    def _visual_boundary_completion_errors(self, state: ServiceTurnState) -> list[str]:
        if not self._has_visual_menu_boundary(state):
            return []
        latest_reply = str(state.get("latest_reply") or "")
        if is_visual_context_request(latest_reply) or detect_tool_call(latest_reply, self.check_tool_call)[0]:
            return []
        request = str(self.config.latest_user_message or "").lower()
        if not ("only" in request and "available" in request):
            return []
        empty_boundary_restaurants = self._empty_only_boundary_restaurants(state)
        if not empty_boundary_restaurants:
            return []
        if self._reply_discloses_boundary_ambiguity(latest_reply):
            return []
        restaurants = ", ".join(sorted(empty_boundary_restaurants))
        return [
            "visual available-section boundary is unresolved for "
            f"{restaurants}: only empty official category results exist for that bounded section. "
            "Do not treat one empty category lookup as proof that the visually available section has no valid items. "
            "Try another plausible official category/list boundary from the visual memory, or state the boundary ambiguity "
            "instead of choosing another restaurant based on a global search."
        ]

    def _reply_discloses_boundary_ambiguity(self, reply: str) -> bool:
        value = str(reply or "").lower()
        has_boundary = any(term in value for term in ("section", "boundary", "available", "category", "subset"))
        has_uncertainty = any(
            term in value
            for term in (
                "ambiguous",
                "ambiguity",
                "unresolved",
                "uncertain",
                "cannot reliably",
                "can't reliably",
                "could not reliably",
                "couldn't reliably",
                "not reliably",
                "could not be officially mapped",
                "couldn't be officially mapped",
                "could not verify",
                "can't verify",
                "not verified",
            )
        )
        return has_boundary and has_uncertainty

    def _empty_only_boundary_restaurants(self, state: ServiceTurnState) -> set[str]:
        category_counts: dict[str, list[int]] = {}
        for entry in state.get("local_tool_logs", []):
            calls = entry.get("calls", [])
            results = entry.get("results", [])
            if not isinstance(calls, list) or not isinstance(results, list):
                continue
            for call, result in zip(calls, results):
                if not isinstance(call, dict):
                    continue
                name = str(call.get("tool_name") or call.get("name") or "")
                if name != "find_dishes_by_category":
                    continue
                params = call.get("parameters", call.get("arguments", {}))
                if not isinstance(params, dict):
                    continue
                restaurant = str(params.get("restaurant_name") or "").strip()
                if not restaurant:
                    continue
                parsed = self._parse_tool_result_content(result)
                dishes = parsed.get("dishes") if isinstance(parsed, dict) else None
                if isinstance(dishes, list):
                    category_counts.setdefault(restaurant, []).append(len(dishes))
        return {restaurant for restaurant, counts in category_counts.items() if counts and all(count == 0 for count in counts)}

    def _parse_tool_result_content(self, result: Any) -> Any:
        if isinstance(result, dict) and "content" in result:
            content = result.get("content")
        else:
            content = result
        if isinstance(content, (dict, list)):
            return content
        text = str(content or "").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                import ast

                return ast.literal_eval(text)
            except (SyntaxError, ValueError):
                return {}
