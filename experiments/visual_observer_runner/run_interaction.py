#!/usr/bin/env python3
"""
EgoBench runner for a visual observer plus a text-only LLM service agent.

This script intentionally lives outside the official run/ tree. It reuses the
official prompts, tools, DB objects, API config, and result schema, but replaces
direct video-to-service-model calls with a cached visual observation block.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env_file(PROJECT_ROOT / ".env")

from config.service_agent_config import SERVICE_MODEL_NAME, VIDEO_LOCAL_PATH, get_video_path  # noqa: E402
from run.prompts import SERVICE_AGENT_PROMPT_BASE, USER_TEXT_ONLY_PROMPT_EASY, USER_TURN_SUMMARY_PROMPT  # noqa: E402
from run.utils import call_llm, check_tool_call, check_user_contradiction, execute_tool  # noqa: E402
from tools.kitchen.kitchen_db import KitchenDB  # noqa: E402
from tools.kitchen.kitchen_init import kitchen_init_data  # noqa: E402
from tools.order.order_db import OrderDB  # noqa: E402
from tools.order.order_init import order_init_data  # noqa: E402
from tools.restaurant.restaurant_db import RestaurantDB  # noqa: E402
from tools.restaurant.restaurant_init import restaurant_init_data, restaurant_init_data5  # noqa: E402
from tools.retail.retail_db import RetailDB  # noqa: E402
from tools.retail.retail_init import (  # noqa: E402
    retail_init_data1,
    retail_init_data2,
    retail_init_data3,
    retail_init_data4,
    retail_init_data5,
    retail_init_data6,
    retail_init_data7,
    retail_init_data8,
    retail_init_data9,
    retail_init_data10,
)


VISUAL_CONTEXT_TEMPLATE = """

## Visual Anchor
The following block provides visual anchor evidence for the current user
request. Depending on the experiment mode, it may come from the two-stage visual
observer or from scenario key/value labels used as an oracle control. Treat this
block as visual evidence only.

{visual_observation}

Use these key/value facts to map the user's visual reference to a likely
catalog/menu/ingredient anchor. They do not establish any database attribute or
state. Prices, tax, discounts, nutrition, allergens, taste, country/origin,
category, set membership, inventory, cart/order/menu state, and totals must come
from tool results.

If the block includes pointed_sequence, shelf_order, or neighbor_map, use those
only as visual grounding for ordinal or adjacent references such as first,
second, third, last, immediately left, or immediately right. The primary
visual_key_values still identify the current user referent.
"""


SERVICE_PROMPT_VERSION = "database_grounded_visual_normalization_v2"


SERVICE_DATABASE_GROUNDING_INSTRUCTION = """

## Database Grounding
- Give customer-facing factual answers only when they are supported by tool
  results in this conversation. This includes prices, tax, discounts, nutrition,
  allergens, taste, country/origin, category, set membership, inventory,
  cart/order/menu state, totals, and whether an item satisfies a condition.
- Visual observations may identify the item or region being discussed, but they
  are not evidence for database attributes or mutable state.
- Do not use real-world knowledge, product names, label style, or common sense
  to fill missing database facts. If a fact is needed and not present in prior
  tool results, call a suitable tool before answering or acting.
- If a tool is a reverse lookup for an attribute, use the returned candidate
  list as evidence only for items that actually appear in that list. Do not
  apply the attribute to an item that the tool did not return.
- For filtering, ranking, cheapest/highest/lowest, tie-sensitive choices, or
  conditional branches, build a candidate set with tools and verify the needed
  properties for each candidate before choosing.
- Treat empty, partial, fuzzy, or ambiguous tool results as inconclusive. Use
  another relevant tool or ask a minimal clarification when needed.
- Before adding, removing, or calculating, ensure the item list and parameters
  are grounded in visual evidence, dialogue history, and tool results rather
  than guesses.

## Visual Anchor Normalization
- Visual observer product/menu names may contain OCR errors. Treat them as
  noisy anchors, not final catalog keys.
- Before using a visual product/menu name for price, country/origin, category,
  tax, discount, nutrition, cart actions, or comparisons, reconcile it with
  actual tool-returned catalog/menu entries.
- Required workflow when a visual anchor contains a product/menu name:
  1. Start with the full visual anchor exactly as observed.
  2. If the tool result is empty, generic, or drops distinctive visual tokens,
     do not answer, ask the user to accept the generic item, or act on it.
  3. Immediately run additional lookup(s) using stable category words and
     distinctive visible tokens from the observation, then compare the returned
     candidate names.
  4. Normalize to the most specific returned candidate that preserves the
     distinctive visual evidence and the item type.
  5. Only after normalization should you request price, tax, discount,
     category, country/origin candidates, nutrition, or perform cart/order
     actions for that item.
- When a lookup returns candidates, compare the returned names with the visual
  anchor. Prefer the most specific complete returned item whose name preserves
  the distinctive visual tokens. Do not blindly use the first returned item.
- Reject generic substring matches that drop distinctive visual tokens. For
  example, if the visual anchor is "KIM CRAFTED Sauvignon Blanc", a tool result
  of only "sauvignon blanc" is a generic category-style match and must not be
  treated as the identified bottle, even if the user later says "yes" to a
  price confirmation. Probe with distinctive tokens and broader item-type
  terms such as "kim", "crafted", and "sauvignon blanc" before proceeding.
- If a lookup returns both a generic item and a more specific item, choose the
  specific item when it best matches the visual anchor. For example,
  "Kim Crawford Sauvignon Blanc" is a better catalog normalization than
  "sauvignon blanc" for a visual anchor containing Kim/Crawford-like brand text.
- Never continue with a generic returned item while a more specific returned
  candidate plausibly matches the visual evidence. If the first lookup for
  "KIM CRAFTED Sauvignon Blanc" returns only "sauvignon blanc", query broader
  candidate lists such as "sauvignon blanc" and choose among the returned
  catalog names before answering or taking cart actions.
- For same-country or same-origin requests, first normalize the visual item to
  an exact tool-returned catalog/menu item. Then use only reverse-lookup tool
  results or other tool-returned database evidence to establish origin-based
  candidate sets. Do not use label appearance, product name stereotypes, or
  real-world knowledge as the country/origin source.
- If the only available country/origin tool is a reverse lookup such as
  find_products_by_country_of_origin(country), treat each call as a hypothesis
  test for that country. The country is proven for the normalized target item
  only if the returned product_names list contains that exact normalized item.
  If the target item is absent from the returned list, that country is disproven
  for the target and must not be used for answering, filtering alternatives, or
  choosing cart/order actions.
- Do not say or imply that a normalized item is from a country unless a prior
  tool result returned that exact item in that country's product_names list.
  For example, if find_products_by_country_of_origin("New Zealand") does not
  return "kim crawford sauvignon blanc", then New Zealand is not supported and
  must be discarded, even if the product name seems associated with New Zealand
  in real-world knowledge.
- For same-country searches, first identify the proven country by reverse
  lookup membership for the normalized target item. Only after that membership
  check succeeds may you use the same returned country list as the candidate
  set for cheaper/higher/discounted/similar alternatives.
- If the visual anchor cannot be confidently normalized to a tool-returned
  catalog/menu item, say that the match is inconclusive or ask one concise
  clarification. Do not infer country/origin, price, or alternatives from
  label appearance or real-world knowledge.
"""


RETAIL_INIT_DATA = {
    1: retail_init_data1,
    2: retail_init_data2,
    3: retail_init_data3,
    4: retail_init_data4,
    5: retail_init_data5,
    6: retail_init_data6,
    7: retail_init_data7,
    8: retail_init_data8,
    9: retail_init_data9,
    10: retail_init_data10,
}


RETAIL1_WINE_SEQUENCE = [
    "Merlot Oyster Bay",
    "River Terrace Chardonnay",
    "Kim Crawford Sauvignon Blanc",
]

VISUAL_NAME_ALIASES = {
    "river terrace": "River Terrace Chardonnay",
    "river terrace chardonnay": "River Terrace Chardonnay",
    "merlot oyster bay": "Merlot Oyster Bay",
    "kim crawford sauvignon blanc": "Kim Crawford Sauvignon Blanc",
}


def init_db(scenario: str, scenario_number: int) -> Any:
    if scenario == "retail":
        db = RetailDB()
        db.init_from_json(RETAIL_INIT_DATA[scenario_number])
        return db
    if scenario == "kitchen":
        db = KitchenDB()
        db.init_from_json(kitchen_init_data)
        return db
    if scenario == "restaurant":
        db = RestaurantDB()
        db.init_from_json(restaurant_init_data5 if scenario_number == 5 else restaurant_init_data)
        return db
    if scenario == "order":
        db = OrderDB()
        db.init_from_json(order_init_data)
        return db
    raise ValueError(f"Unsupported scenario: {scenario}")


def resolve_video_path(video_filename: str) -> str:
    basename = os.path.basename(video_filename)
    local_candidate = Path(VIDEO_LOCAL_PATH) / basename
    if local_candidate.exists():
        return str(local_candidate.resolve())
    project_local = PROJECT_ROOT / "videos" / basename
    if project_local.exists():
        return str(project_local.resolve())
    return get_video_path(basename)


def slugify_name(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    slug = slug.strip("-")
    return slug or "model"


def timestamp_tag() -> str:
    return time.strftime("%Y%m%d%H%M", time.localtime())


def get_run_timestamp(args: argparse.Namespace) -> str:
    run_timestamp = getattr(args, "run_timestamp", None)
    if not run_timestamp:
        run_timestamp = timestamp_tag()
        args.run_timestamp = run_timestamp
    return run_timestamp


def build_output_model_name(args: argparse.Namespace) -> str:
    if args.output_model_name:
        return args.output_model_name
    model_name = slugify_name(args.service_model_name)
    keyword = args.output_keyword or args.scenario
    prefix = "scenario-value" if getattr(args, "visual_context_source", "observer") == "scenario_value" else "visual-observer"
    return f"{prefix}-{model_name}-{get_run_timestamp(args)}-{slugify_name(keyword)}"


def visual_observer_url(args: argparse.Namespace) -> str:
    return args.visual_observer_url or args.aura_observer_url or "http://127.0.0.1:18082/observe"


def observation_task_key(task: dict[str, Any], video_path: str, args: argparse.Namespace) -> str:
    payload = {
        "video_path": video_path,
        "scenario": args.scenario,
        "scenario_number": args.scenario_number,
        "observer_url": visual_observer_url(args),
        "version": "aura_observer_task_trace_v4_no_dialogue",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def observation_turn_key(
    task: dict[str, Any],
    video_path: str,
    args: argparse.Namespace,
    turn: int,
    current_user_message: str,
) -> str:
    payload = {
        "video_path": video_path,
        "scenario": args.scenario,
        "scenario_number": args.scenario_number,
        "turn": turn,
        "current_user_message": current_user_message,
        "observer_url": visual_observer_url(args),
        "version": "aura_observer_turn_grounded_v5_no_dialogue",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def observation_trace_file(task: dict[str, Any], video_path: str, task_id: int, args: argparse.Namespace) -> Path:
    cache_dir = Path(args.observation_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{args.scenario}{args.scenario_number}_{get_run_timestamp(args)}.json"


def load_observation_trace(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"tasks": {}}
    trace = json.loads(path.read_text(encoding="utf-8"))
    if "tasks" in trace:
        return trace
    if "turns" in trace:
        return trace

    # Backward compatibility for the older one-turn cache record shape.
    if "request" in trace and "response" in trace:
        return {"turns": [trace]}
    return {"turns": []}


def build_observation_trace_header(
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "schema_version": "aura_observer_scenario_trace_v1_no_dialogue",
        "scenario": args.scenario,
        "scenario_number": args.scenario_number,
        "scenario_key": f"{args.scenario}{args.scenario_number}",
        "run_timestamp": get_run_timestamp(args),
        "observer_mode": "aura_event_qwenvl_sequence",
        "observer_url": visual_observer_url(args),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "tasks": {},
    }


def find_cached_observation(trace: dict[str, Any], task_label: str, turn_key: str) -> dict[str, Any] | None:
    if "tasks" in trace:
        task_entry = trace.get("tasks", {}).get(task_label, {})
        for item in task_entry.get("turns", {}).values():
            if item.get("turn_key") == turn_key:
                return item.get("response")
        return None

    # Backward compatibility for older task-level cache files.
    for item in trace.get("turns", []):
        if item.get("turn_key") == turn_key:
            return item.get("response")
    return None


def upsert_observation_turn(
    trace: dict[str, Any],
    task_label: str,
    task_metadata: dict[str, Any],
    turn_label: str,
    record: dict[str, Any],
) -> None:
    if "tasks" not in trace:
        existing_turns = trace.get("turns", [])
        trace.clear()
        trace.update({"tasks": {task_label: {**task_metadata, "turns": {}}}})
        for item in existing_turns:
            trace["tasks"][task_label]["turns"][f"turn{item.get('turn', len(trace['tasks'][task_label]['turns']))}"] = item

    task_entry = trace.setdefault("tasks", {}).setdefault(
        task_label,
        {**task_metadata, "turns": {}},
    )
    task_entry.update(task_metadata)
    turns = task_entry.setdefault("turns", {})
    for key, item in list(turns.items()):
        if item.get("turn_key") == record.get("turn_key"):
            turns[key] = record
            return
    turns[turn_label] = record


def get_aura_observation(
    task: dict[str, Any],
    video_path: str,
    task_id: int,
    args: argparse.Namespace,
    turn: int,
    current_user_message: str,
) -> dict[str, Any]:
    cache_file = observation_trace_file(task, video_path, task_id, args)
    task_label = f"{args.scenario}{args.scenario_number}_task{task_id}"
    turn_label = f"turn{turn}"
    turn_key = observation_turn_key(
        task,
        video_path,
        args,
        turn,
        current_user_message,
    )
    trace = load_observation_trace(cache_file)
    if not args.refresh_observation:
        cached_response = find_cached_observation(trace, task_label, turn_key)
        if cached_response is not None:
            return cached_response

    aura_task_id = f"{args.scenario}{args.scenario_number}_{task_id}_turn{turn}"
    payload = {
        "task_id": aura_task_id,
        "experiment_id": build_output_model_name(args),
        "experiment_timestamp": get_run_timestamp(args),
        "scenario": args.scenario,
        "video_path": video_path,
        "image_description": task.get("image_description", ""),
        "current_user_message": current_user_message,
    }
    request_start = time.time()
    response = requests.post(visual_observer_url(args), json=payload, timeout=args.aura_timeout)
    response.raise_for_status()
    data = response.json()
    if not trace.get("schema_version"):
        trace.clear()
        trace.update(build_observation_trace_header(args))
    else:
        trace["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    upsert_observation_turn(
        trace,
        task_label,
        {
            "task_label": task_label,
            "task_id": task_id,
            "task_key": observation_task_key(task, video_path, args),
            "video_path": video_path,
            "image_path": task.get("image_path"),
            "image_description": task.get("image_description"),
        },
        turn_label,
        {
            "turn": turn,
            "turn_label": turn_label,
            "turn_key": turn_key,
            "aura_task_id": aura_task_id,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "elapsed_seconds": round(time.time() - request_start, 3),
            "current_user_message": current_user_message,
            "response": data,
        },
    )
    cache_file.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return data


def coerce_task_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, tuple):
        return [str(item) for item in value if item not in (None, "")]
    if value == "":
        return []
    return [str(value)]


def canonical_visual_name(value: str) -> str:
    return VISUAL_NAME_ALIASES.get(value.strip().lower(), value)


def build_neighbor_map(sequence: list[str]) -> dict[str, dict[str, str | None]]:
    neighbors = {}
    for idx, item in enumerate(sequence):
        neighbors[item] = {
            "left": sequence[idx - 1] if idx > 0 else None,
            "right": sequence[idx + 1] if idx + 1 < len(sequence) else None,
        }
    return neighbors


def build_simulated_observer_context(task: dict[str, Any]) -> dict[str, Any]:
    image_name = str(task.get("image_name") or "")
    image_path = os.path.basename(str(task.get("image_path") or ""))
    key = str(task.get("key") or "")
    if key != "product_name" or image_name != "retail1" and image_path != "retail1.mp4":
        return {}

    task_values = [canonical_visual_name(item) for item in coerce_task_values(task.get("value"))]
    sequence = task_values if len(task_values) > 1 else RETAIL1_WINE_SEQUENCE
    return {
        "pointed_sequence": sequence,
        "shelf_order": RETAIL1_WINE_SEQUENCE,
        "neighbor_map": build_neighbor_map(RETAIL1_WINE_SEQUENCE),
        "notes": (
            "Simulated observer context for retail1 wine shelf. Use this only for "
            "visual ordinal and adjacent references; verify all product attributes with tools."
        ),
    }


def build_scenario_value_observation(
    task: dict[str, Any],
    current_user_message: str,
) -> dict[str, Any]:
    visual_key = str(task.get("key") or "visual_anchor")
    visual_values = coerce_task_values(task.get("value"))
    canonical_values = [canonical_visual_name(item) for item in visual_values]
    simulated_context = build_simulated_observer_context(task)
    visual_summary = (
        f"The scenario oracle resolves the user's visual reference to "
        f"{visual_key}={', '.join(visual_values)}."
        if visual_values
        else "The scenario oracle did not provide a visual anchor value for this task."
    )
    if simulated_context.get("pointed_sequence"):
        visual_summary += (
            " Simulated observer context also provides pointed_sequence and "
            "neighbor_map for ordinal/adjacent visual references."
        )
    visual_key_values = [
        {
            "key": visual_key,
            "value": item,
            "canonical_value": canonical_visual_name(item),
            "confidence": "oracle",
            "evidence": (
                "Scenario oracle visual anchor. Use this value as the resolved identity "
                "of the item or object referenced by the user's visual description."
            ),
            "source": "scenario_key_value",
        }
        for item in visual_values
    ]
    visual_referents = [
        {
            "user_referent": "scenario oracle primary visual referent",
            "key": visual_key,
            "value": item,
            "canonical_value": canonical_values[idx],
            "source": "scenario_key_value",
        }
        for idx, item in enumerate(visual_values)
    ]
    return {
        "observation": {
            "observer": "scenario_value_oracle",
            "current_visual_request": current_user_message,
            "visual_anchor_summary": visual_summary,
            "visual_key_values": visual_key_values,
            "pointed_sequence": simulated_context.get("pointed_sequence", []),
            "shelf_order": simulated_context.get("shelf_order", []),
            "neighbor_map": simulated_context.get("neighbor_map", {}),
            "visual_referents": visual_referents,
            "detail_evidence": [],
            "uncertainties": simulated_context.get("notes"),
        }
    }


def format_visual_observation(observation: dict[str, Any]) -> str:
    useful = observation.get("observation", observation)
    return json.dumps(useful, ensure_ascii=False, indent=2)


def normalize_model_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value)


def contains_stop_signal(text: str) -> bool:
    return any(line.strip() == "STOP" for line in text.splitlines())


def build_dialogue_context(dialogue: list[dict[str, Any]], summarized_history: str, last_agent_response: str) -> str:
    if summarized_history:
        return summarized_history
    recent = dialogue[-6:]
    lines = []
    for item in recent:
        role = "User" if item.get("role") == "user" else "Service Agent"
        lines.append(f"{role}: {item.get('content', '')}")
    if last_agent_response and not lines:
        lines.append(f"Service Agent: {last_agent_response}")
    return "\n".join(lines) if lines else "No prior dialogue."


def run_simulation(input_path: str, tool_info_path: str, output_path: str, args: argparse.Namespace) -> None:
    with open(tool_info_path, "r", encoding="utf-8") as f:
        tool_descriptions = json.dumps(json.load(f), indent=2, ensure_ascii=False)
    with open(input_path, "r", encoding="utf-8") as f:
        scenarios = json.load(f)
    visual_context_source = getattr(args, "visual_context_source", "observer")

    if args.num_tasks > 0:
        scenarios = scenarios[: args.num_tasks]

    all_results = []

    for idx, sc in enumerate(scenarios):
        task_id = idx + 1
        print(f"\n{'=' * 20} Hybrid Scenario {args.scenario}{args.scenario_number}: {task_id} {'=' * 20}")

        db = init_db(args.scenario, args.scenario_number)
        user_instruction = sc.get("Instruction", "")
        image_description = sc.get("image_description", "")
        video_path = resolve_video_path(sc.get("image_path", ""))

        start_time = time.time()
        history_log = {
            "task_id": task_id,
            "mode": "text",
            "instruction": user_instruction,
            "image_description": image_description,
            "service_prompt_version": SERVICE_PROMPT_VERSION,
            "dialogue": [],
            "tool_calls": [],
            "rounds_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tool_calls_count": 0,
            "user_response_time_seconds": 0.0,
            "agent_response_time_seconds": 0.0,
            "start_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time)),
            "visual_context_source": visual_context_source,
        }
        if args.include_aura_debug_in_results:
            history_log["video_path"] = video_path
            history_log["aura_observation"] = None
            history_log["aura_observations"] = []
            history_log["aura_observation_time_seconds"] = 0.0
            history_log["visual_observer_mode"] = "first_turn_only" if args.observe_once else "per_turn"
        elif visual_context_source == "scenario_value":
            simulated_context = build_simulated_observer_context(sc)
            history_log["scenario_value_oracle"] = {
                "key": sc.get("key"),
                "value": sc.get("value"),
                "pointed_sequence": simulated_context.get("pointed_sequence", []),
                "shelf_order": simulated_context.get("shelf_order", []),
                "neighbor_map": simulated_context.get("neighbor_map", {}),
            }

        user_agent_sys_prompt = USER_TEXT_ONLY_PROMPT_EASY.format(
            user_instruction=user_instruction,
            image_description=image_description,
            original_user_response="",
            evaluation_feedback="",
            history_summary="",
            service_agent_response="Dear customer, how can I help you?",
        )
        user_messages = [
            {"role": "system", "content": user_agent_sys_prompt},
            {
                "role": "user",
                "content": (
                    "You are a customer in the environment shown in the video, and you need to complete "
                    "the instructions in **Task**. I am your AI customer service representative; please "
                    "interact with me in the first person. Let's begin the conversation.\n"
                    "Dear customer, how can I help you?"
                ),
            },
        ]

        service_agent_sys_prompt_base = SERVICE_AGENT_PROMPT_BASE.format(
            tool_descriptions=tool_descriptions
        ) + SERVICE_DATABASE_GROUNDING_INSTRUCTION
        history_log["service_prompt_contains_database_grounding"] = (
            "## Database Grounding" in service_agent_sys_prompt_base
        )
        history_log["service_prompt_contains_visual_normalization"] = (
            "## Visual Anchor Normalization" in service_agent_sys_prompt_base
        )

        service_history = []
        rounds_count = 0
        input_tokens_total = 0
        output_tokens_total = 0
        tool_calls_count = 0
        accumulated_original_scores = {}
        accumulated_final_scores = {}
        valid_evaluation_count = 0
        last_agent_response_for_check = "Dear customer, how can I help you?"
        summarized_history_str = ""
        frozen_aura_observation = None
        frozen_visual_observation_text = None
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        for turn in range(args.max_turns):
            user_start_time = time.time()
            user_reply, user_input_tok, user_output_tok = call_llm(
                user_messages,
                agent_type="user",
                service_model_name=args.service_model_name,
            )
            user_reply = normalize_model_text(user_reply, fallback="")
            user_gen_time = time.time() - user_start_time
            print(f"[Time] User response generation (Turn {turn}): {user_gen_time:.3f} seconds")
            history_log["user_response_time_seconds"] += user_gen_time
            input_tokens_total += user_input_tok
            output_tokens_total += user_output_tok

            evaluation_info = None
            if args.multi_agent_user:
                check_start_time = time.time()
                original_user_reply = user_reply
                user_reply, evaluation_info = check_user_contradiction(
                    user_response=original_user_reply,
                    user_instruction=user_instruction,
                    image_description=image_description,
                    multi_agent_user=True,
                    last_agent_response=last_agent_response_for_check,
                    history=history_log["dialogue"],
                    summarized_history=summarized_history_str if args.summary_user else None,
                    user_mode="easy",
                )
                user_reply = normalize_model_text(user_reply, fallback=original_user_reply)
                history_log["user_response_time_seconds"] += time.time() - check_start_time
                if evaluation_info and "scores" in evaluation_info:
                    valid_evaluation_count += 1
                    original_scores = evaluation_info["scores"]
                    final_scores = evaluation_info.get("corrected_scores", original_scores)
                    for key, value in original_scores.items():
                        try:
                            accumulated_original_scores[key] = accumulated_original_scores.get(key, 0.0) + float(value)
                        except ValueError:
                            pass
                    for key, value in final_scores.items():
                        try:
                            accumulated_final_scores[key] = accumulated_final_scores.get(key, 0.0) + float(value)
                        except ValueError:
                            pass

            print(f"Final User Response: {user_reply}")
            log_entry = {"role": "user", "turn": turn, "content": user_reply}
            if evaluation_info:
                log_entry["evaluation"] = evaluation_info
            history_log["dialogue"].append(log_entry)

            if contains_stop_signal(user_reply):
                print("Stop signal detected")
                break

            if args.observe_once and frozen_visual_observation_text is not None:
                aura_observation = frozen_aura_observation
                visual_observation_text = frozen_visual_observation_text
                observation_time = 0.0
                print(f"Reusing first-turn visual observation for turn {turn}.")
            elif visual_context_source == "scenario_value":
                print(f"Using scenario key/value visual oracle for turn {turn}.")
                observation_start = time.time()
                aura_observation = build_scenario_value_observation(sc, user_reply)
                observation_time = time.time() - observation_start
                visual_observation_text = format_visual_observation(aura_observation)
                if args.observe_once:
                    frozen_aura_observation = aura_observation
                    frozen_visual_observation_text = visual_observation_text
                print(f"[Time] Scenario value visual context (Turn {turn}): {observation_time:.3f} seconds")
            else:
                print(f"Observing video with visual observer for turn {turn}: {video_path}")
                observation_start = time.time()
                aura_observation = get_aura_observation(
                    sc,
                    video_path,
                    task_id,
                    args,
                    turn,
                    user_reply,
                )
                observation_time = time.time() - observation_start
                visual_observation_text = format_visual_observation(aura_observation)
                if args.observe_once:
                    frozen_aura_observation = aura_observation
                    frozen_visual_observation_text = visual_observation_text
                print(f"[Time] Visual observation (Turn {turn}): {observation_time:.3f} seconds")
            if args.include_aura_debug_in_results:
                history_log["aura_observation"] = aura_observation
                history_log["aura_observations"].append(
                    {
                        "turn": turn,
                        "user_message": user_reply,
                        "observation": aura_observation,
                        "elapsed_seconds": round(observation_time, 3),
                        "reused": args.observe_once and turn > 0,
                    }
                )
                history_log["aura_observation_time_seconds"] += observation_time
            current_turn_service_prompt = service_agent_sys_prompt_base + VISUAL_CONTEXT_TEMPLATE.format(
                visual_observation=visual_observation_text
            )

            service_history.append({"role": "user", "content": user_reply})
            user_messages.append({"role": "assistant", "content": user_reply})

            current_user_reply = user_reply
            current_agent_response = last_agent_response_for_check
            current_service_history = [msg for msg in service_history]
            current_summary = summarized_history_str
            current_service_agent_sys_prompt = current_turn_service_prompt

            def generate_summary_task() -> str | None:
                if not args.summary_user:
                    return None
                prompt = USER_TURN_SUMMARY_PROMPT.format(
                    user_instruction=user_instruction,
                    agent_response=current_agent_response,
                    user_response=current_user_reply,
                    previous_summary=current_summary if current_summary else "None",
                )
                print(f"Generating dialogue summary (Turn {turn})...")
                summary, summary_in_tok, summary_out_tok = call_llm(
                    [{"role": "user", "content": prompt}],
                    agent_type="user",
                    service_model_name=args.service_model_name,
                )
                summary = normalize_model_text(summary, fallback="")
                return json.dumps(
                    {"summary": summary, "input_tokens": summary_in_tok, "output_tokens": summary_out_tok},
                    ensure_ascii=False,
                )

            def process_agent_task() -> dict[str, Any]:
                agent_start = time.time()
                inner_input_tokens = 0
                inner_output_tokens = 0
                inner_calls = 0
                inner_rounds = 0
                agent_final_reply = ""
                local_tool_logs = []
                local_dialogue_logs = []
                local_service_history = [msg for msg in current_service_history]

                for _ in range(args.max_inner_tool_rounds):
                    current_service_msgs = [{"role": "system", "content": current_service_agent_sys_prompt}]
                    current_service_msgs.extend(local_service_history)

                    agent_reply, agent_input_tokens, agent_output_tokens = call_llm(
                        current_service_msgs,
                        agent_type="service",
                        service_model_name=args.service_model_name,
                    )
                    agent_reply = normalize_model_text(agent_reply, fallback="[Empty model response]")
                    inner_input_tokens += agent_input_tokens
                    inner_output_tokens += agent_output_tokens
                    print(f"Tested Agent: {agent_reply}")

                    is_tool, tool_call_obj = check_tool_call(agent_reply)
                    if not is_tool:
                        inner_rounds += 1
                        local_dialogue_logs.append({"role": "agent", "turn": turn, "content": agent_reply})
                        local_service_history.append({"role": "assistant", "content": agent_reply})
                        agent_final_reply = agent_reply
                        break

                    calls_this_round = len(tool_call_obj) if isinstance(tool_call_obj, list) else 1
                    if tool_calls_count + inner_calls + calls_this_round > args.max_tool_calls:
                        agent_final_reply = "[Interaction stopped: tool calls exceeded limit]"
                        break

                    inner_calls += calls_this_round
                    tool_results = execute_tool(db, tool_call_obj)
                    local_tool_logs.append(
                        {
                            "turn": turn,
                            "calls": tool_call_obj if isinstance(tool_call_obj, list) else [tool_call_obj],
                            "results": tool_results,
                        }
                    )
                    combined_result = "; ".join(res.get("content", str(res)) for res in tool_results)
                    local_service_history.append({"role": "assistant", "content": agent_reply})
                    local_service_history.append({"role": "user", "content": f"Tool execution result: {combined_result}"})
                else:
                    agent_final_reply = "[Interaction stopped: inner tool rounds exceeded limit]"

                return {
                    "reply": agent_final_reply,
                    "input_tokens": inner_input_tokens,
                    "output_tokens": inner_output_tokens,
                    "calls": inner_calls,
                    "rounds": inner_rounds,
                    "tool_logs": local_tool_logs,
                    "dialogue_logs": local_dialogue_logs,
                    "time": time.time() - agent_start,
                    "updated_history": local_service_history,
                }

            future_summary = executor.submit(generate_summary_task)
            future_agent = executor.submit(process_agent_task)
            summary_payload = future_summary.result()
            agent_res = future_agent.result()

            if summary_payload:
                summary_data = json.loads(summary_payload)
                turn_summary = summary_data["summary"]
                input_tokens_total += summary_data["input_tokens"]
                output_tokens_total += summary_data["output_tokens"]
                print(f"Turn {turn} Summary: {turn_summary}")
            else:
                turn_summary = None

            print(f"[Time] Agent response generation (Turn {turn}): {agent_res['time']:.3f} seconds")
            input_tokens_total += agent_res["input_tokens"]
            output_tokens_total += agent_res["output_tokens"]
            tool_calls_count += agent_res["calls"]
            rounds_count += agent_res["rounds"]
            history_log["agent_response_time_seconds"] += agent_res["time"]
            history_log["tool_calls"].extend(agent_res["tool_logs"])
            history_log["dialogue"].extend(agent_res["dialogue_logs"])
            service_history = agent_res["updated_history"]
            last_agent_response_for_check = agent_res["reply"]

            if args.summary_user and turn_summary:
                summarized_history_str = f"Turn {turn} Dialogue Summary of completed steps: {turn_summary}\n"

            user_agent_sys_prompt = USER_TEXT_ONLY_PROMPT_EASY.format(
                user_instruction=user_instruction,
                image_description=image_description,
                original_user_response="",
                evaluation_feedback="",
                history_summary=summarized_history_str,
                service_agent_response=last_agent_response_for_check,
            )
            if args.summary_user and turn_summary:
                user_messages = [
                    {"role": "system", "content": user_agent_sys_prompt},
                    {
                        "role": "user",
                        "content": "Please continue the conversation in the first person according to the original settings based on the summary and latest response.",
                    },
                ]
            else:
                user_messages[0]["content"] = user_agent_sys_prompt
                user_messages.append({"role": "user", "content": last_agent_response_for_check})

        executor.shutdown(wait=True)

        history_log["rounds_count"] = rounds_count
        history_log["input_tokens"] = input_tokens_total
        history_log["output_tokens"] = output_tokens_total
        history_log["tool_calls_count"] = tool_calls_count
        if valid_evaluation_count > 0:
            history_log["user_performance"] = {
                **{
                    f"original_{key}_avg": round(value / valid_evaluation_count, 2)
                    for key, value in accumulated_original_scores.items()
                },
                **{
                    f"final_{key}_avg": round(value / valid_evaluation_count, 2)
                    for key, value in accumulated_final_scores.items()
                },
            }
        else:
            history_log["user_performance"] = {}

        history_log["execution_time_seconds"] = round(time.time() - start_time, 3)
        all_results.append(history_log)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\nCompleted! Results saved to: {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run visual-observer + service-agent EgoBench simulation")
    parser.add_argument("--service_model_name", default=SERVICE_MODEL_NAME)
    parser.add_argument(
        "--output_model_name",
        default=None,
        help=(
            "Override the auto result directory name. Default prefix is visual-observer "
            "for observer mode and scenario-value for scenario_value mode."
        ),
    )
    parser.add_argument(
        "--output_keyword",
        default=None,
        help="Keyword used in the auto result directory name. Default: scenario name.",
    )
    parser.add_argument("--scenario", choices=["retail", "kitchen", "restaurant", "order"], default="retail")
    parser.add_argument("--scenario_number", type=int, default=1)
    parser.add_argument("--num_tasks", type=int, default=0)
    parser.add_argument("--max_turns", type=int, default=10)
    parser.add_argument("--max_inner_tool_rounds", type=int, default=12)
    parser.add_argument("--max_tool_calls", type=int, default=100)
    parser.add_argument("--multi_agent_user", action="store_true")
    parser.add_argument("--summary_user", action="store_true")
    parser.add_argument("--visual_observer_url", default=None)
    parser.add_argument(
        "--visual_context_source",
        choices=["observer", "scenario_value"],
        default="observer",
        help=(
            "observer calls the visual observer server; scenario_value skips video understanding "
            "and injects scenarios/final key/value labels as oracle visual anchors."
        ),
    )
    parser.add_argument(
        "--aura_observer_url",
        default=None,
        help="Deprecated alias for --visual_observer_url.",
    )
    parser.add_argument("--aura_timeout", type=int, default=600)
    parser.add_argument(
        "--observation_cache_dir",
        default=str(PROJECT_ROOT / "experiments" / "visual_observer_runner" / "cache" / "visual_observations"),
    )
    parser.add_argument("--refresh_observation", action="store_true")
    parser.add_argument(
        "--observe_once",
        action="store_true",
        help="Observe the video only for the first non-STOP user turn, then reuse that visual context for the whole task.",
    )
    parser.add_argument(
        "--include_aura_debug_in_results",
        action="store_true",
        help="Write bulky per-turn visual observations into results JSON for debugging only.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_json = PROJECT_ROOT / "scenarios" / "final" / f"{args.scenario}{args.scenario_number}.json"
    tool_info_json = PROJECT_ROOT / "tools" / args.scenario / f"{args.scenario}_tools.json"
    output_model_name = build_output_model_name(args)
    output_json = PROJECT_ROOT / "results" / output_model_name / f"{args.scenario}{args.scenario_number}_easy.json"
    run_simulation(str(input_json), str(tool_info_json), str(output_json), args)


if __name__ == "__main__":
    main()
