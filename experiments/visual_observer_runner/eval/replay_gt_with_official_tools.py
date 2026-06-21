#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import inspect
import io
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kitchen.kitchen_db import KitchenDB
from tools.kitchen.kitchen_init import kitchen_init_data
from tools.order.order_db import OrderDB
from tools.order.order_init import order_init_data
from tools.restaurant.restaurant_db import RestaurantDB
from tools.restaurant.restaurant_init import restaurant_init_data5
from tools.retail.retail_db import RetailDB
from tools.retail.retail_init import retail_init_data6, retail_init_data10


TARGETS: dict[str, tuple[str, int, type, dict[str, Any]]] = {
    "retail6": ("retail", 6, RetailDB, retail_init_data6),
    "retail10": ("retail", 10, RetailDB, retail_init_data10),
    "restaurant5": ("restaurant", 5, RestaurantDB, restaurant_init_data5),
    "kitchen4": ("kitchen", 4, KitchenDB, kitchen_init_data),
    "order2": ("order", 2, OrderDB, order_init_data),
}

AGGREGATE_TOOLS = {
    "compute_total_payment",
    "compute_total_tax",
    "compute_total_nutrition",
    "compute_total_nutritions",
    "tally_total_tastes",
    "tally_total_nutritional_characteristics",
}


def scenario_path(name: str) -> Path:
    return ROOT / "scenarios" / "final" / f"{name}.json"


def normalize_numbers(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: normalize_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_numbers(v) for v in value]
    if isinstance(value, tuple):
        return [normalize_numbers(v) for v in value]
    if isinstance(value, float):
        rounded = round(value, 10)
        if rounded.is_integer():
            return int(rounded)
        return rounded
    return value


def canon(value: Any) -> Any:
    value = normalize_numbers(value)
    if isinstance(value, dict):
        return {str(k): canon(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return [canon(v) for v in value]
    if isinstance(value, str):
        return " ".join(value.strip().lower().split())
    return value


def item_multiset(items: list[dict[str, Any]], name_key: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in items:
        name = str(item.get(name_key, "")).strip().lower()
        if not name:
            continue
        quantity = item.get("quantity", item.get("qty", 1))
        try:
            qty = float(quantity)
        except (TypeError, ValueError):
            qty = 0
        qty = round(qty, 10)
        result[name] = result.get(name, 0) + qty
    return result


def params_equivalent(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    keys = set(actual) | set(expected)
    list_key = next((k for k in ("products", "dishes", "ingredients", "recipes") if k in keys), None)
    if list_key:
        keys.remove(list_key)
    for key in keys:
        if canon(actual.get(key)) != canon(expected.get(key)):
            return False
    if list_key == "products":
        return item_multiset(actual.get("products", []), "product_name") == item_multiset(expected.get("products", []), "product_name")
    if list_key == "dishes":
        return item_multiset(actual.get("dishes", []), "dish_name") == item_multiset(expected.get("dishes", []), "dish_name")
    if list_key == "ingredients":
        return item_multiset(actual.get("ingredients", []), "ingredient_name") == item_multiset(expected.get("ingredients", []), "ingredient_name")
    if list_key == "recipes":
        return sorted(canon(x) for x in actual.get("recipes", [])) == sorted(canon(x) for x in expected.get("recipes", []))
    return True


def db_for(name: str) -> tuple[str, int, Any, dict[str, Any]]:
    scenario, number, db_cls, seed = TARGETS[name]
    db = db_cls()
    with contextlib.redirect_stdout(io.StringIO()):
        db.init_from_json(seed)
    return scenario, number, db, seed


def accepted_parameters(method: Any, params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    signature = inspect.signature(method)
    accepted = {key: value for key, value in params.items() if key in signature.parameters}
    dropped = {key: value for key, value in params.items() if key not in signature.parameters}
    missing = [
        key
        for key, param in signature.parameters.items()
        if key != "self" and param.default is inspect.Signature.empty and key not in accepted
    ]
    return accepted, dropped, missing


def call_tool(db: Any, call: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(call.get("tool_name") or call.get("name") or "")
    params = deepcopy(call.get("parameters") or call.get("arguments") or {})
    record = {
        "tool_name": tool_name,
        "original_parameters": params,
        "accepted_parameters": {},
        "dropped_parameters": {},
        "missing_required_parameters": [],
        "result": None,
        "error": None,
    }
    if not tool_name or not hasattr(db, tool_name):
        record["error"] = f"tool_not_found: {tool_name}"
        return record
    method = getattr(db, tool_name)
    accepted, dropped, missing = accepted_parameters(method, params)
    record["accepted_parameters"] = accepted
    record["dropped_parameters"] = dropped
    record["missing_required_parameters"] = missing
    if missing:
        record["error"] = f"missing_required_parameters: {missing}"
        return record
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            result = method(**accepted)
        record["result"] = normalize_numbers(result)
    except Exception as exc:  # noqa: BLE001 - report tool failure without hiding it.
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def first_param(calls: list[dict[str, Any]], key: str, default: Any = None) -> Any:
    for call in calls:
        params = call.get("parameters") or {}
        if key in params:
            return params[key]
    return default


def state_call_for(scenario: str, gt_calls: list[dict[str, Any]], aggregate_call: dict[str, Any]) -> dict[str, Any] | None:
    params = aggregate_call.get("parameters") or {}
    user_id = params.get("user_id") or first_param(gt_calls, "user_id")
    if scenario == "retail":
        return {"tool_name": "get_cart", "parameters": {"user_id": user_id}}
    if scenario == "restaurant":
        return {"tool_name": "get_user_order_summary", "parameters": {"user_id": user_id}}
    if scenario == "kitchen":
        if aggregate_call.get("tool_name") in {"tally_total_tastes", "tally_total_nutritional_characteristics"}:
            return {"tool_name": "get_current_menu", "parameters": {"user_id": user_id}}
        return {"tool_name": "get_current_shopping_list", "parameters": {"user_id": user_id}}
    if scenario == "order":
        restaurant_name = params.get("restaurant_name") or first_param(gt_calls, "restaurant_name")
        return {"tool_name": "get_user_order_summary", "parameters": {"restaurant_name": restaurant_name, "user_id": user_id}}
    return None


def expected_aggregate_params_from_state(
    scenario: str,
    aggregate_call: dict[str, Any],
    state_result: dict[str, Any],
    db: Any,
) -> dict[str, Any]:
    params = deepcopy(aggregate_call.get("parameters") or {})
    tool_name = str(aggregate_call.get("tool_name") or "")
    if scenario == "retail":
        catalog = getattr(db, "catalog", {})
        products = [
            {"product_name": item.get("product_name"), "quantity": item.get("quantity")}
            for item in state_result.get("cart_items", [])
            if str(item.get("product_name") or "").lower() in catalog
        ]
        return {"user_id": params.get("user_id"), "products": products}
    if scenario in {"restaurant", "order"}:
        dishes = [
            {"dish_name": item.get("dish_name"), "quantity": item.get("quantity")}
            for item in state_result.get("items", [])
        ]
        expected = {"user_id": params.get("user_id"), "dishes": dishes}
        if scenario == "order":
            expected["restaurant_name"] = params.get("restaurant_name")
        return expected
    if scenario == "kitchen":
        if tool_name in {"tally_total_tastes", "tally_total_nutritional_characteristics"}:
            return {"user_id": params.get("user_id"), "recipes": state_result.get("recipes", [])}
        ingredients = [
            {"ingredient_name": item.get("ingredient_name"), "quantity": item.get("quantity")}
            for item in state_result.get("items", [])
        ]
        return {"user_id": params.get("user_id"), "ingredients": ingredients}
    return params


def anchor_lookup_calls(scenario: str, row: dict[str, Any], gt_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: list[tuple[str, str]] = []
    for field in ("value", "secondary_value"):
        raw = row.get(field) or []
        if isinstance(raw, str):
            raw = [raw]
        for value in raw:
            if str(value).strip():
                values.append((field, str(value)))
    calls: list[dict[str, Any]] = []
    if not values:
        return calls
    restaurant_name = first_param(gt_calls, "restaurant_name", "Mediterranean Greek Restaurant")
    for field, value in values:
        if scenario == "retail":
            calls.append({"anchor_field": field, "anchor_value": value, "tool_name": "get_price", "parameters": {"product_name": value}})
        elif scenario == "restaurant":
            calls.append({"anchor_field": field, "anchor_value": value, "tool_name": "get_dish_price", "parameters": {"dish_name": value}})
        elif scenario == "order":
            calls.append(
                {
                    "anchor_field": field,
                    "anchor_value": value,
                    "tool_name": "get_dish_price",
                    "parameters": {"restaurant_name": restaurant_name, "dish_name": value},
                }
            )
        elif scenario == "kitchen":
            calls.append(
                {
                    "anchor_field": field,
                    "anchor_value": value,
                    "tool_name": "get_recipe_ingredients",
                    "parameters": {"recipe_name": value},
                }
            )
            calls.append(
                {
                    "anchor_field": field,
                    "anchor_value": value,
                    "tool_name": "find_ingredient_category",
                    "parameters": {"ingredient_name": value},
                }
            )
    return calls


def audit_task(scenario_name: str, row: dict[str, Any]) -> dict[str, Any]:
    scenario, _, db, _ = db_for(scenario_name)
    gt_calls = row.get("ground_truth") or []
    task_report: dict[str, Any] = {
        "task_id": row.get("task_id"),
        "value": row.get("value"),
        "secondary_value": row.get("secondary_value"),
        "anchor_checks": [],
        "tool_steps": [],
        "aggregate_checks": [],
        "errors": [],
    }

    anchor_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for lookup in anchor_lookup_calls(scenario, row, gt_calls):
        anchor_field = lookup.pop("anchor_field")
        anchor_value = lookup.pop("anchor_value")
        result = call_tool(db, lookup)
        result["anchor_field"] = anchor_field
        result["anchor_value"] = anchor_value
        task_report["anchor_checks"].append(result)
        anchor_groups.setdefault((anchor_field, anchor_value), []).append(result)

    for (anchor_field, anchor_value), results in anchor_groups.items():
        if all(
            result.get("error")
            or (isinstance(result.get("result"), dict) and result["result"].get("status") == "error")
            for result in results
        ):
            task_report["errors"].append(
                {"kind": "anchor_lookup", "field": anchor_field, "value": anchor_value, "lookups": results}
            )

    for index, call in enumerate(gt_calls, start=1):
        tool_name = str(call.get("tool_name") or call.get("name") or "")
        if tool_name in AGGREGATE_TOOLS:
            state_call = state_call_for(scenario, gt_calls, call)
            if state_call:
                state_record = call_tool(db, state_call)
                state_result = state_record.get("result") if isinstance(state_record.get("result"), dict) else {}
                expected_params = expected_aggregate_params_from_state(scenario, call, state_result or {}, db)
                expected_call = {"tool_name": tool_name, "parameters": expected_params}
                expected_record = call_tool(db, expected_call)
                aggregate_record = {
                    "call_index": index,
                    "tool_name": tool_name,
                    "state_tool": state_record,
                    "expected_parameters_from_state_tool": expected_params,
                    "expected_tool_result": expected_record,
                    "params_match_state": params_equivalent(call.get("parameters") or {}, expected_params),
                }
                task_report["aggregate_checks"].append(aggregate_record)
                if not aggregate_record["params_match_state"]:
                    task_report["errors"].append({"kind": "aggregate_params_mismatch", "call_index": index, "tool_name": tool_name})

        step_record = call_tool(db, call)
        step_record["call_index"] = index
        task_report["tool_steps"].append(step_record)
        if step_record.get("error") or (isinstance(step_record.get("result"), dict) and step_record["result"].get("status") == "error"):
            task_report["errors"].append({"kind": "tool_execution", "call_index": index, "tool_name": tool_name, "step": step_record})

        if tool_name in AGGREGATE_TOOLS and task_report["aggregate_checks"]:
            check = task_report["aggregate_checks"][-1]
            check["actual_tool_result"] = step_record
            check["result_match_state"] = canon(step_record.get("result")) == canon(check["expected_tool_result"].get("result"))
            if not check["result_match_state"]:
                task_report["errors"].append({"kind": "aggregate_result_mismatch", "call_index": index, "tool_name": tool_name})

    return task_report


def audit_scenario(scenario_name: str, task_ids: set[int] | None = None) -> dict[str, Any]:
    scenario, number, _, _ = TARGETS[scenario_name]
    rows = json.loads(scenario_path(scenario_name).read_text(encoding="utf-8"))
    reports = []
    for index, row in enumerate(rows, start=1):
        task_id = int(row.get("task_id") or index)
        if task_ids and task_id not in task_ids:
            continue
        reports.append(audit_task(scenario_name, row))
    return {
        "scenario": scenario_name,
        "scenario_type": scenario,
        "scenario_number": number,
        "tasks_checked": len(reports),
        "tasks_with_errors": sum(1 for report in reports if report["errors"]),
        "task_reports": reports,
    }


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay current GT calls with official scenario tools and audit anchor/aggregate consistency."
    )
    parser.add_argument("--scenarios", nargs="*", default=list(TARGETS), choices=list(TARGETS))
    parser.add_argument("--task_ids", default=None, help="Optional comma/range filter, e.g. 1,4,8-10.")
    parser.add_argument(
        "--report",
        default=str(ROOT / "experiments" / "visual_observer_runner" / "eval" / "official_tool_replay_audit.json"),
    )
    args = parser.parse_args()

    task_ids = parse_task_ids(args.task_ids)
    reports = [audit_scenario(name, task_ids) for name in args.scenarios]
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for report in reports:
        print(
            f"{report['scenario']}: tasks_checked={report['tasks_checked']} "
            f"tasks_with_errors={report['tasks_with_errors']}"
        )
        for task in report["task_reports"]:
            if task["errors"]:
                print(f"  task {task['task_id']}: errors={len(task['errors'])}")
                for error in task["errors"][:3]:
                    print(f"    - {error['kind']}: {error.get('tool_name', '')} {error.get('field', '')}".rstrip())
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
