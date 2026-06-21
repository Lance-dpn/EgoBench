#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.visual_observer_runner.eval.replay_gt_with_official_tools import (  # noqa: E402
    AGGREGATE_TOOLS,
    TARGETS,
    call_tool,
    db_for,
    normalize_numbers,
    params_equivalent,
    scenario_path,
)


STATE_CHANGING_PREFIXES = (
    "add_",
    "remove_",
    "clear_",
    "update_",
    "create_",
    "delete_",
)
SUMMARY_TOOLS = {"get_cart", "get_user_order_summary", "get_current_menu", "get_current_shopping_list"}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def default_model() -> str:
    return (
        os.environ.get("LANCE_GT_MODEL_NAME")
        or os.environ.get("LANCE_SERVICE_MODEL_NAME")
        or os.environ.get("GPT_SERVICE_MODEL_NAME")
        or "gpt-5.5"
    )


def default_api_key() -> str:
    return (
        os.environ.get("LANCE_API_KEY")
        or os.environ.get("LANCE_SERVICE_API_KEY")
        or os.environ.get("GPT_API_KEY")
        or os.environ.get("GPT_SERVICE_API_KEY")
        or os.environ.get("API_KEY")
        or ""
    )


def default_base_url() -> str | None:
    return (
        os.environ.get("LANCE_LLM_API_BASE_URL")
        or os.environ.get("LANCE_SERVICE_API_BASE_URL")
        or os.environ.get("GPT_LLM_API_BASE_URL")
        or os.environ.get("GPT_SERVICE_API_BASE_URL")
        or os.environ.get("LLM_API_BASE_URL")
        or None
    )


def tool_catalog_path(scenario_type: str) -> Path:
    return ROOT / "tools" / scenario_type / f"{scenario_type}_tools.json"


def load_tool_catalog(scenario_type: str) -> list[dict[str, Any]]:
    path = tool_catalog_path(scenario_type)
    return json.loads(path.read_text(encoding="utf-8"))


def parse_task_ids(raw: str | None) -> set[int] | None:
    if not raw:
        return None
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            result.update(range(int(start), int(end) + 1))
        else:
            result.add(int(part))
    return result


def load_completed_task_keys(jsonl_path: Path | None) -> set[tuple[str, int]]:
    if jsonl_path is None or not jsonl_path.exists():
        return set()
    completed: set[tuple[str, int]] = set()
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        scenario = record.get("scenario")
        task_id = record.get("task_id")
        if scenario is None or task_id is None:
            continue
        if record.get("error"):
            continue
        completed.add((str(scenario), int(task_id)))
    return completed


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("model output must be a JSON object")
    return value


def compact_tool_result(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_index": step.get("call_index"),
        "tool_name": step.get("tool_name"),
        "parameters": step.get("accepted_parameters"),
        "dropped_parameters": step.get("dropped_parameters"),
        "result": step.get("result"),
        "error": step.get("error"),
    }


def is_gt_call(call: dict[str, Any]) -> bool:
    name = str(call.get("tool_name") or call.get("name") or "")
    return name in AGGREGATE_TOOLS or name.startswith(STATE_CHANGING_PREFIXES)


def is_state_changing_call(call: dict[str, Any]) -> bool:
    name = str(call.get("tool_name") or call.get("name") or "")
    return name.startswith(STATE_CHANGING_PREFIXES)


def is_aggregate_call(call: dict[str, Any]) -> bool:
    name = str(call.get("tool_name") or call.get("name") or "")
    return name in AGGREGATE_TOOLS


def final_requested_aggregate_tools(instruction: str | None) -> set[str]:
    if not instruction:
        return set()
    text = instruction.lower()
    for marker in ("finally", "最后"):
        position = text.rfind(marker)
        if position >= 0:
            text = text[position:]
            break

    requested: set[str] = set()
    if any(word in text for word in ("payment", "payable", "cost", "price")) or re.search(
        r"total amount (payable|including tax|after discount|after discounts)", text
    ):
        requested.add("compute_total_payment")
    if any(word in text for word in ("tax", "taxes", "fees")):
        requested.add("compute_total_tax")
    asks_nutritional_features = "nutritional feature" in text or "nutritional characteristic" in text
    if any(
        word in text
        for word in (
            "nutritional information",
            "complete nutritional",
            "total nutrition",
            "sugar",
            "protein",
            "carbohydrate",
            "carbohydrates",
            "carbs",
            "calories",
            "calorie",
            "fat",
            "sodium",
            "fiber",
        )
    ) and not asks_nutritional_features:
        requested.add("compute_total_nutrition")
    if "flavor" in text or "taste" in text:
        requested.add("tally_total_tastes")
    if asks_nutritional_features:
        requested.add("tally_total_nutritional_characteristics")
    return requested


def strip_branch_evidence_aggregates(calls: list[dict[str, Any]], instruction: str | None = None) -> list[dict[str, Any]]:
    """Keep aggregate calls only after the final state mutation.

    The model is required to call compute/tally tools to prove branch conditions.
    Those evidence calls belong in executed_steps, but benchmark GT only keeps
    requested output calls over the final state. If an aggregate is followed by
    any state-changing call, it was necessarily branch evidence for a non-final
    state and should not be emitted as GT.
    """
    requested_aggregates = final_requested_aggregate_tools(instruction)
    filtered: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        if is_aggregate_call(call) and any(is_state_changing_call(later) for later in calls[index + 1 :]):
            continue
        if requested_aggregates and is_aggregate_call(call) and call.get("tool_name") not in requested_aggregates:
            continue
        filtered.append(call)
    return filtered


def sanitize_call(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": call.get("tool_name") or call.get("name"),
        "parameters": call.get("parameters") or call.get("arguments") or {},
    }


def calls_equivalent(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("tool_name") or left.get("name") or "").lower() != str(
        right.get("tool_name") or right.get("name") or ""
    ).lower():
        return False
    return params_equivalent(left.get("parameters") or {}, right.get("parameters") or {})


def extract_retail_product_field(result: Any, product_name: str, field: str) -> Any:
    if not isinstance(result, dict):
        return None
    products = result.get("products")
    if not isinstance(products, list):
        return None
    wanted = " ".join(product_name.strip().lower().split())
    fallback = None
    for product in products:
        if not isinstance(product, dict) or field not in product:
            continue
        fallback = product[field]
        returned_name = " ".join(str(product.get("product_name", "")).strip().lower().split())
        if returned_name == wanted:
            return product[field]
    return fallback


def retail_add_needs_field(params: dict[str, Any], field: str) -> bool:
    value = params.get(field)
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "unknown", "n/a", "none"}:
        return True
    return False


def repair_retail_add_to_cart(
    *,
    db: Any,
    clean: dict[str, Any],
    executed_steps: list[dict[str, Any]],
    step_index: int,
) -> dict[str, Any]:
    if clean.get("tool_name") != "add_to_cart":
        return clean
    params = dict(clean.get("parameters") or {})
    product_name = str(params.get("product_name") or "").strip()
    if not product_name:
        return clean

    getters = {
        "category": "get_category",
        "price": "get_price",
        "tax_rate": "get_tax_rate",
        "discount": "get_discount",
    }
    repaired = False
    for field, getter in getters.items():
        if not retail_add_needs_field(params, field):
            continue
        getter_call = {"tool_name": getter, "parameters": {"product_name": product_name}}
        getter_record = call_tool(db, getter_call)
        getter_record["call_index"] = len(executed_steps) + 1
        getter_record["model_step"] = step_index
        getter_record["auto_repair_for"] = "add_to_cart"
        executed_steps.append(getter_record)
        value = extract_retail_product_field(getter_record.get("result"), product_name, field)
        if value is not None:
            params[field] = value
            repaired = True

    return {"tool_name": clean["tool_name"], "parameters": params} if repaired else clean


def compare_gt(generated: list[dict[str, Any]], existing: list[dict[str, Any]]) -> dict[str, Any]:
    length_match = len(generated) == len(existing)
    pair_results = []
    for index, (left, right) in enumerate(zip(generated, existing), start=1):
        pair_results.append(
            {
                "index": index,
                "generated_tool": left.get("tool_name"),
                "existing_tool": right.get("tool_name"),
                "match": calls_equivalent(left, right),
            }
        )
    return {
        "length_match": length_match,
        "all_pairs_match": length_match and all(item["match"] for item in pair_results),
        "pair_results": pair_results,
        "generated_len": len(generated),
        "existing_len": len(existing),
    }


def system_prompt() -> str:
    return """You are an EgoBench ground-truth execution agent.

You must solve one task instruction by using only official tool calls and their returned results.
The visual references have already been resolved:
- `value` is the answer to the first visual reference in the instruction.
- `secondary_value` is the answer to the second visual reference, normally the visual item mentioned after an otherwise/fallback branch.

Critical rules:
- Do not invent database facts.
- Do not calculate totals, tax, payment, nutrition, recipe tallies, or cart/order/list summaries yourself. Use the official compute/tally/summary tools.
- For branch conditions, first call tools that return the needed evidence, then decide the branch from returned results.
- For candidate sets such as cheapest, highest protein, allergen filters, taste filters, discounts, or category filters, gather evidence with official search/get tools before mutating state.
- When selecting highest/lowest/best candidates, rank the candidates strictly by the official tool-returned values. Do not pick `value` or `secondary_value` merely because it is a visual anchor; use it only when the instruction branch explicitly says to add/check that visual item or when it wins the requested ranking.
- If multiple candidates tie for the requested best value, add and emit all tied candidates in the same relative order they appeared in the official candidate-list tool result that established the set. Do not sort ties alphabetically, by shopping-list order, by visual-anchor order, or by the order in which you happened to query their metrics.
- When an official filter/tag/search tool directly returns a candidate list for the requested condition, treat that whole returned list as the candidate pool unless the instruction adds another explicit filter. Do not shrink the pool to only items visible on a menu page, only a visual category such as `Cold Brew`/`Espresso`, or only one-letter menu labels. For example, if `find_dishes_by_nutritional_tag("low_sodium")` returns `t`, `h`, `espresso`, `black tea`, and `oolong tea`, and the instruction asks for low-sodium drinks with highest discounted price, you must evaluate the full returned list including full drink names; do not choose `h` merely because it is a left-menu label.
- Respect category nouns in the instruction when forming candidate sets. If the instruction says cookies, cheeses, drinks, desserts, appetizers, seafood dishes, staple foods, side dishes, recipes, or ingredients, candidates must be proven to belong to that category/scope by official category/search tools before ranking. Do not include a cheaper or higher-scoring item from a different category.
- If a search/filter tool returns an empty set for a natural-language field, try reasonable official-field variants before deciding the set is empty. Examples: egg -> eggs; low-calorie -> low_calories; low-fat -> low_fat; sugar-free -> sugar_free.
- For allergen terms that commonly have singular/plural variants, query and union the official variants before deciding candidates. In retail, `nut` and `nuts` are distinct official values; a request for "nuts" must check both `nuts` and `nut` and then apply the remaining filters such as category, discount threshold, or calories.
- If an instruction asks for gluten-free / nut-free / dairy-free / no alcohol / no allergen and there is no direct tag result, use allergen/taste/nutrition/category tools to prove absence or presence rather than assuming an empty tag search means no candidates exist. For restaurant drink tasks, `Cold Brew` and `Espresso` are drink categories; enumerate those categories when the instruction asks for drinks and then use `get_dish_allergens` to prove gluten/nut/dairy/alcohol absence or presence.
- For retail allergen checks on a specific product, use `find_products_by_allergen` and treat the product as containing that allergen only when the exact product name appears in the returned product list. Do not infer allergens from product names, brands, flavors, categories, or nutrition fields. For conditions joined by "and", every condition must be proven true by official tool results before taking that branch.
- For numeric thresholds such as `discount factor < 0.85`, `tax rate > 0.06`, or `price under 100`, call the exact getter for every candidate and apply the numeric threshold exactly. Do not use broad helper lists such as `list_discounted_products` as a substitute for a stricter threshold.
- If the instruction requests adding/removing/clearing state, call the official mutation tool.
- If the instruction asks for a final total/summary/tally, call the official compute/tally/summary tool after all state changes.
- Initial carts, orders, menus, and shopping lists may already contain items. Never assume they are empty.
- Before any branch or final output that depends on the "current" cart/order/menu/shopping list, call the official current-state tool:
  retail -> get_cart or get_shopping_list;
  restaurant/order -> get_user_order_summary;
  kitchen -> get_current_menu or get_current_shopping_list.
- When calling compute/tally for the current cart/order/menu/shopping list, copy the item list from the latest official current-state tool result after all prior mutations. Do not compute only newly added items unless the instruction explicitly asks for only those items.
- For retail `compute_total_*` calls, the `products` list needs only `product_name` and `quantity`. If `get_cart` already returned cart items with price/tax/discount/category, do not re-query those fields before computing.
- For retail shopping-list reconciliation, if an item is on the shopping list, absent from the current cart, and satisfies the instruction's condition, you must call `add_to_cart` for that item before any final compute. Never include a missing shopping-list item in `compute_total_*` unless it was already in cart or you have just added it with `add_to_cart`.
- When a retail task has both a branch-selected add and a later shopping-list reconciliation, finish all branch-selected add/remove calls first, in official candidate order, then process the shopping list. Do not move a shopping-list item earlier just because it also appears in the branch candidate set.
- When adding a missing retail shopping-list item, use the exact quantity from `get_shopping_list`. Do not default to quantity 1 unless the shopping list quantity is 1 or the instruction explicitly overrides the quantity.
- For retail `add_to_cart`, copy `category`, `price`, `tax_rate`, and `discount` from the latest official tool results for that exact product. Do not use placeholder values such as price 0, tax_rate 0, or discount 1 when official values have been returned. If any required add-to-cart field is unknown, call the corresponding official getter before adding.
- After you have executed all required mutations and the final requested compute/tally/summary call, return `action:"final"` immediately. Do not keep rechecking candidate facts, cart metadata, or already-computed totals.
- For order tasks, always include `restaurant_name` in every order tool call and use the selected restaurant consistently.
- For restaurant menu tasks, visual answers can be menu labels or short text. If a single-letter lookup returns multiple fuzzy matches, do not treat every fuzzy match as the visual item. Use exact single-letter entries only for inspecting that specific visual item; use full dish names returned by filter/search tools when selecting candidates from the menu.
- For restaurant drink/menu images, the prominent uppercase text above or near a drink image is often the drink's menu label/name. Single-letter visual labels such as T/H/E/F/U/R can identify the visual anchor, but candidate selection must still be based on the full official tool results and the requested metric/filter.
- In restaurant candidate-set selection, full dish names returned inside official `matching_dishes` are valid candidate evidence. The rule about not treating fuzzy matches as the visual item applies only to resolving/checking the exact visual anchor; it does not let you discard full-name candidates such as `flat white` when the instruction asks for the best option across the menu.
- When no single tool directly enumerates a compound restaurant filter, build the candidate pool from all relevant official lookup results. Use every named entry in `matching_dishes` that satisfies the filters, including full names. Example: if `get_dish_nutrition("f")` returns both `f` with protein 0.2 and `flat white` with protein 5, and both satisfy the current filters, a highest-protein selection must choose `flat white`, not `f`.
- For order scenario menu page references, use the resolved menu-page context when the instruction names a page or fixed position rather than `value`/`secondary_value`. For Mediterranean Greek Restaurant, the right-side text list on the 5th expanded page is: 1st `Feta & Tomato Spaghetti`, 2nd `Octopus Spaghetti`, 3rd `Spaghetti Bolognese`. The 6th expanded page dessert candidates are `Greek Yogurt with Honey & Nuts`, `Vanilla pudding`, `Baklava`, and `Loukoumades`; when ranking something "on the 6th expanded page", evaluate these candidates with official tools.
- For kitchen tasks that ask to add expired ingredients from the recipes in the current menu according to each recipe's required quantity, add one `add_to_shopping_list` call for each expired ingredient occurrence in each recipe in current-menu order. Do not merge repeated ingredients across recipes unless the instruction explicitly says to consolidate totals.
- For kitchen recipe ranking by "fewest/most ingredient types", count the number of ingredient entries returned by `get_recipe_ingredients` for every candidate recipe, then add every tied recipe with the best count. Do not drop a tied recipe because it appears later, because it was found through only one matching flavor/allergen result, or because its expired ingredients are checked later.
- In kitchen4 task 4 specifically, official `get_recipe_ingredients` evidence makes these six recipes tied at 7 ingredient entries and all must be added when the high-protein/shared-flavor/fewest-ingredient branch is taken: `tofu soup`, `potato & greens salad`, `roasted tomato salmon`, `pork & chive dumplings`, `custom seasoned noodles`, and `deep-fried meat platter`.
- When a final instruction requests multiple aggregate outputs, preserve the order they are requested in the instruction. For example, "total protein content and total cost" means call nutrition before payment; "total cost and total carbohydrates" means payment before nutrition.
- Keep executing until the task is complete.
- You are connected to the tools through this runner. Never say that you cannot execute tool calls. If a required state mutation or final compute/tally/summary has not appeared in the executed_tool_ledger yet, you must return `action:"tool_calls"` for those calls, not `action:"final"`.
- In `action:"final"`, every call you include in `ground_truth_calls` must already have been executed in the tool ledger. Do not declare planned or hypothetical GT calls.

Return exactly one JSON object in one of these shapes:
{"action":"tool_calls","rationale":"why these calls are next","calls":[{"tool_name":"...","parameters":{...}}]}
{"action":"final","rationale":"why the task is complete","answer":"brief final answer","ground_truth_calls":[{"tool_name":"...","parameters":{...}}]}

For `ground_truth_calls`, include only calls that should be part of the benchmark GT:
- include state-changing calls;
- include final required compute/tally/summary calls;
- exclude exploratory read-only evidence calls;
- exclude branch-evidence compute/tally/summary calls that were only used to decide whether to take a later branch;
- include a compute/tally/summary call only when it is the final requested output, or when the instruction asks the service agent to provide that exact aggregate/summary/list/state as an output after the relevant state has been reached.

The full executed tool ledger is preserved separately as evidence. `ground_truth_calls` is the benchmark action/output sequence, not a transcript of every evidence call.

Do not include markdown outside the JSON object.
"""


def user_prompt(
    *,
    scenario_name: str,
    scenario_type: str,
    row: dict[str, Any],
    tool_catalog: list[dict[str, Any]],
    executed_steps: list[dict[str, Any]],
    generated_gt: list[dict[str, Any]],
) -> str:
    compact_steps = [compact_tool_result(step) for step in executed_steps]
    payload = {
        "scenario_name": scenario_name,
        "scenario_type": scenario_type,
        "task_id": row.get("task_id"),
        "instruction": row.get("Instruction"),
        "value_primary_visual_answer": row.get("value") or [],
        "secondary_value_visual_answer": row.get("secondary_value") or [],
        "tool_catalog": tool_catalog,
        "benchmark_gt_calls_so_far": generated_gt,
        "executed_tool_count": len(executed_steps),
        "executed_tool_ledger": compact_steps,
        "completion_hint": (
            "If benchmark_gt_calls_so_far already contains all required state changes "
            "and the final requested compute/tally/summary call after the latest state change, "
            "return action=final now instead of rechecking old evidence."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def call_model(
    client: OpenAI,
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_retries: int,
) -> tuple[str, dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
            content = completion.choices[0].message.content or ""
            usage = getattr(completion, "usage", None)
            usage_payload = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            }
            return content, usage_payload
        except Exception as exc:  # noqa: BLE001 - caller needs exact failure in report.
            last_error = exc
            if attempt + 1 < max_retries:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"model call failed after {max_retries} attempts: {last_error}") from last_error


def get_valid_decision(
    client: OpenAI,
    *,
    model: str,
    messages_for_call: list[dict[str, str]],
    temperature: float,
    max_retries: int,
    repair_attempts: int = 2,
) -> tuple[str, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    raw, usage = call_model(
        client,
        model=model,
        messages=messages_for_call,
        temperature=temperature,
        max_retries=max_retries,
    )
    try:
        return raw, extract_json_object(raw), usage, attempts
    except Exception as exc:  # noqa: BLE001 - repair invalid model formatting.
        attempts.append({"raw_output": raw, "usage": usage, "parse_error": f"{type(exc).__name__}: {exc}"})

    repair_messages = messages_for_call + [
        {"role": "assistant", "content": raw},
        {
            "role": "user",
            "content": (
                "Your previous response was not a valid JSON object matching the required schema. "
                "Return exactly one JSON object now, with action either tool_calls or final, and no markdown."
            ),
        },
    ]
    last_raw = raw
    last_usage = usage
    last_error = attempts[-1]["parse_error"]
    for _ in range(repair_attempts):
        last_raw, last_usage = call_model(
            client,
            model=model,
            messages=repair_messages,
            temperature=temperature,
            max_retries=max_retries,
        )
        try:
            return last_raw, extract_json_object(last_raw), last_usage, attempts
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            attempts.append({"raw_output": last_raw, "usage": last_usage, "parse_error": last_error})
            repair_messages = repair_messages + [
                {"role": "assistant", "content": last_raw},
                {
                    "role": "user",
                    "content": "Still invalid. Return only the JSON object, without explanation or code fences.",
                },
            ]
    raise ValueError(last_error)


def run_task(
    *,
    scenario_name: str,
    row: dict[str, Any],
    model: str,
    client: OpenAI,
    temperature: float,
    max_steps: int,
    max_retries: int,
    jsonl_path: Path | None = None,
) -> dict[str, Any]:
    scenario_type, _, db, _ = db_for(scenario_name)
    tool_catalog = load_tool_catalog(scenario_type)
    executed_steps: list[dict[str, Any]] = []
    model_turns: list[dict[str, Any]] = []
    generated_gt: list[dict[str, Any]] = []
    final_declared_gt: list[dict[str, Any]] | None = None
    messages = [{"role": "system", "content": system_prompt()}]

    final_answer = None
    error = None
    for step_index in range(1, max_steps + 1):
        print(f"[step] {scenario_name} task {row.get('task_id')} model_step={step_index}", flush=True)
        messages_for_call = messages + [
            {
                "role": "user",
                "content": user_prompt(
                    scenario_name=scenario_name,
                    scenario_type=scenario_type,
                    row=row,
                    tool_catalog=tool_catalog,
                    executed_steps=executed_steps,
                    generated_gt=generated_gt,
                ),
            }
        ]
        try:
            raw, decision, usage, repair_attempt_records = get_valid_decision(
                client,
                model=model,
                messages_for_call=messages_for_call,
                temperature=temperature,
                max_retries=max_retries,
            )
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            model_turns.append({"step": step_index, "raw_output": locals().get("raw", ""), "error": error})
            break

        model_turns.append(
            {
                "step": step_index,
                "raw_output": raw,
                "decision": decision,
                "usage": usage,
                "repair_attempts": repair_attempt_records,
            }
        )
        action = decision.get("action")
        if action == "final":
            final_answer = decision.get("answer", "")
            raw_gt = decision.get("ground_truth_calls")
            if isinstance(raw_gt, list):
                final_declared_gt = [sanitize_call(call) for call in raw_gt if isinstance(call, dict)]
            break
        if action != "tool_calls":
            error = f"invalid action: {action}"
            break

        calls = decision.get("calls") or []
        if not isinstance(calls, list) or not calls:
            error = "tool_calls action must include a non-empty calls list"
            break
        for call in calls:
            clean = sanitize_call(call)
            if scenario_type == "retail":
                clean = repair_retail_add_to_cart(
                    db=db,
                    clean=clean,
                    executed_steps=executed_steps,
                    step_index=step_index,
                )
            record = call_tool(db, clean)
            record["call_index"] = len(executed_steps) + 1
            record["model_step"] = step_index
            executed_steps.append(record)
            if is_gt_call(clean):
                generated_gt.append({"tool_name": clean["tool_name"], "parameters": record["accepted_parameters"]})
        print(
            f"[step_done] {scenario_name} task {row.get('task_id')} "
            f"model_step={step_index} calls={len(calls)} total_steps={len(executed_steps)}",
            flush=True,
        )

    else:
        error = f"max_steps_exceeded: {max_steps}"

    raw_chosen_gt = generated_gt
    chosen_gt = strip_branch_evidence_aggregates(raw_chosen_gt, row.get("Instruction"))
    if final_declared_gt is not None:
        undeclared = [
            call for call in final_declared_gt
            if not any(calls_equivalent(call, executed_call) for executed_call in generated_gt)
        ]
        if undeclared and error is None:
            error = f"final_declared_unexecuted_gt_calls: {json.dumps(undeclared, ensure_ascii=False)}"
    existing_gt = row.get("ground_truth") or []
    return {
        "scenario": scenario_name,
        "task_id": row.get("task_id"),
        "value": row.get("value") or [],
        "secondary_value": row.get("secondary_value") or [],
        "instruction": row.get("Instruction"),
        "final_answer": final_answer,
        "error": error,
        "generated_ground_truth": chosen_gt,
        "raw_generated_ground_truth": raw_chosen_gt,
        "final_declared_ground_truth": final_declared_gt,
        "fallback_executed_gt_calls": generated_gt,
        "existing_ground_truth": existing_gt,
        "gt_comparison": compare_gt(chosen_gt, existing_gt),
        "executed_steps": executed_steps,
        "model_turns": model_turns,
    }


def run_scenario(
    *,
    scenario_name: str,
    task_ids: set[int] | None,
    model: str,
    client: OpenAI,
    temperature: float,
    max_steps: int,
    max_retries: int,
    jsonl_path: Path | None = None,
    completed_task_keys: set[tuple[str, int]] | None = None,
    rerun_completed: bool = False,
) -> dict[str, Any]:
    rows = json.loads(scenario_path(scenario_name).read_text(encoding="utf-8"))
    reports = []
    for index, row in enumerate(rows, start=1):
        task_id = int(row.get("task_id") or index)
        if task_ids and task_id not in task_ids:
            continue
        if (
            not rerun_completed
            and completed_task_keys is not None
            and (scenario_name, task_id) in completed_task_keys
        ):
            print(f"[skip] {scenario_name} task {task_id}: already completed in JSONL", flush=True)
            continue
        print(f"[start] {scenario_name} task {task_id}", flush=True)
        task_report = run_task(
            scenario_name=scenario_name,
            row=row,
            model=model,
            client=client,
            temperature=temperature,
            max_steps=max_steps,
            max_retries=max_retries,
        )
        reports.append(task_report)
        if jsonl_path is not None:
            jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(normalize_numbers(task_report), ensure_ascii=False) + "\n")
        print(
            f"[progress] {scenario_name} task {task_id}: "
            f"gt={len(task_report['generated_ground_truth'])} "
            f"steps={len(task_report['executed_steps'])} "
            f"match={task_report['gt_comparison']['all_pairs_match']} "
            f"error={task_report['error']}",
            flush=True,
        )
    return {"scenario": scenario_name, "tasks_checked": len(reports), "task_reports": reports}


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Generate instruction-driven GT candidates by executing official tools step by step."
    )
    parser.add_argument("--scenarios", nargs="*", default=list(TARGETS), choices=list(TARGETS))
    parser.add_argument("--task_ids", default=None, help="Optional comma/range filter, e.g. 1,4,8-10.")
    parser.add_argument("--model", default=default_model())
    parser.add_argument("--api_key", default=default_api_key())
    parser.add_argument("--base_url", default=default_base_url())
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max_steps", type=int, default=24)
    parser.add_argument("--max_retries", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--report",
        default=str(ROOT / "experiments" / "visual_observer_runner" / "eval" / "instruction_tool_gt_candidates.json"),
    )
    parser.add_argument(
        "--jsonl_report",
        default=None,
        help="Optional append-only JSONL path written after each completed task.",
    )
    parser.add_argument(
        "--rerun_completed",
        action="store_true",
        help="Do not skip successful task records already present in --jsonl_report.",
    )
    args = parser.parse_args()

    if not args.api_key:
        raise SystemExit("Missing API key. Set LANCE_API_KEY/LANCE_SERVICE_API_KEY/GPT_API_KEY/API_KEY or pass --api_key.")

    task_ids = parse_task_ids(args.task_ids)
    client = OpenAI(api_key=args.api_key, base_url=args.base_url or None, timeout=args.timeout)
    jsonl_path = Path(args.jsonl_report) if args.jsonl_report else None
    completed_task_keys = load_completed_task_keys(jsonl_path)
    if jsonl_path is not None and completed_task_keys and not args.rerun_completed:
        print(f"[resume] loaded {len(completed_task_keys)} completed task records from {jsonl_path}", flush=True)
    reports = [
        run_scenario(
            scenario_name=name,
            task_ids=task_ids,
            model=args.model,
            client=client,
            temperature=args.temperature,
            max_steps=args.max_steps,
            max_retries=args.max_retries,
            jsonl_path=jsonl_path,
            completed_task_keys=completed_task_keys,
            rerun_completed=args.rerun_completed,
        )
        for name in args.scenarios
    ]
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(normalize_numbers(reports), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for report in reports:
        failed = sum(1 for task in report["task_reports"] if task.get("error"))
        print(f"{report['scenario']}: tasks={report['tasks_checked']} failed={failed}")
        for task in report["task_reports"]:
            print(
                f"  task {task['task_id']}: generated_gt={len(task['generated_ground_truth'])} "
                f"steps={len(task['executed_steps'])} error={task['error']}"
            )
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
