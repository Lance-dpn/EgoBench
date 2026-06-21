#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import inspect
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


def output_report_path() -> Path:
    return ROOT / "experiments" / "visual_observer_runner" / "eval" / "compute_gt_result_audit_20260618.json"


def display_maps(seed: dict[str, Any]) -> dict[str, dict[str, str]]:
    maps: dict[str, dict[str, str]] = {
        "product": {},
        "dish": {},
        "set_meal": {},
        "recipe": {},
        "ingredient": {},
        "restaurant": {},
    }
    for product in seed.get("products", []):
        name = str(product.get("name", ""))
        maps["product"][name.lower()] = name
    for dish in seed.get("dishes", []):
        name = str(dish.get("name", ""))
        maps["dish"][name.lower()] = name
        restaurant = dish.get("restaurant_name")
        if restaurant:
            maps["restaurant"][str(restaurant).lower()] = str(restaurant)
    for set_meal in seed.get("set_meals", []):
        name = str(set_meal.get("name", ""))
        maps["set_meal"][name.lower()] = name
        restaurant = set_meal.get("restaurant_name")
        if restaurant:
            maps["restaurant"][str(restaurant).lower()] = str(restaurant)
    for recipe in seed.get("recipes", []):
        name = str(recipe.get("name", ""))
        maps["recipe"][name.lower()] = name
    for ingredient in seed.get("ingredients", []):
        name = str(ingredient.get("name", ""))
        maps["ingredient"][name.lower()] = name
    return maps


def clean_number(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def norm_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.lower().strip().split())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def norm_item_list(items: list[dict[str, Any]], name_key: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in items:
        name = str(item.get(name_key, "")).lower().strip()
        quantity = item.get("quantity", item.get("qty", 1))
        try:
            qty = float(quantity)
        except (TypeError, ValueError):
            qty = 0.0
        if not name:
            continue
        result[name] = result.get(name, 0.0) + qty
    return result


def norm_name_list(items: list[Any]) -> list[str]:
    return sorted(str(item).lower().strip() for item in items)


def canon_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): canon_json(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return [canon_json(v) for v in value]
    if isinstance(value, float):
        return round(value, 10)
    return value


def results_equal(left: Any, right: Any) -> bool:
    return canon_json(left) == canon_json(right)


def execute_call(db: Any, call: dict[str, Any]) -> Any:
    tool_name = call["tool_name"]
    params = call.get("parameters", {})
    method = getattr(db, tool_name)
    sig = inspect.signature(method)
    valid_params = {key: value for key, value in params.items() if key in sig.parameters}
    return method(**valid_params)


def find_order_store(db: OrderDB, restaurant_name: str) -> tuple[str, dict[str, Any] | None]:
    if restaurant_name in db.restaurants:
        return restaurant_name, db.restaurants[restaurant_name]
    target = restaurant_name.lower()
    for name, store in db.restaurants.items():
        if name.lower() == target:
            return name, store
    return restaurant_name, None


def derive_retail_params(db: RetailDB, call: dict[str, Any], maps: dict[str, dict[str, str]]) -> dict[str, Any]:
    params = dict(call.get("parameters", {}))
    user_id = params.get("user_id")
    items = []
    for item in db.user_carts.get(user_id, {}).values():
        if item.product_name.lower() not in db.catalog:
            continue
        product_name = maps["product"].get(item.product_name.lower(), item.product_name)
        items.append({"product_name": product_name, "quantity": clean_number(item.quantity)})
    return {"user_id": user_id, "products": items}


def derive_restaurant_params(db: RestaurantDB, call: dict[str, Any], maps: dict[str, dict[str, str]]) -> dict[str, Any]:
    params = dict(call.get("parameters", {}))
    user_id = params.get("user_id")
    dishes = []
    for item in db.user_orders.get(user_id, {}).values():
        name_key = item.dish_name.lower()
        display = maps["dish"].get(name_key) or maps["set_meal"].get(name_key) or item.dish_name
        dishes.append({"dish_name": display, "quantity": clean_number(item.quantity)})
    return {"user_id": user_id, "dishes": dishes}


def is_mutation_call(call: dict[str, Any]) -> bool:
    name = str(call.get("tool_name") or "")
    return name.startswith(("add_", "remove_", "clear_", "update_", "set_", "replace_"))


def derive_order_params(
    db: OrderDB,
    call: dict[str, Any],
    maps: dict[str, dict[str, str]],
    *,
    include_set_meals_for_payment: bool,
) -> dict[str, Any]:
    params = dict(call.get("parameters", {}))
    restaurant_name = str(params.get("restaurant_name", ""))
    user_id = params.get("user_id")
    canonical_restaurant, store = find_order_store(db, restaurant_name)
    display_restaurant = maps["restaurant"].get(canonical_restaurant.lower(), restaurant_name)
    dishes = []
    if store:
        for item in store["user_orders"].get(user_id, {}).values():
            name_key = item.dish_name.lower()
            if (
                call["tool_name"] == "compute_total_payment"
                and not include_set_meals_for_payment
                and name_key in store["set_meals"]
            ):
                continue
            display = maps["dish"].get(name_key) or maps["set_meal"].get(name_key) or item.dish_name
            dishes.append({"dish_name": display, "quantity": clean_number(item.quantity)})
    return {"restaurant_name": display_restaurant, "user_id": user_id, "dishes": dishes}


def derive_kitchen_params(db: KitchenDB, call: dict[str, Any], maps: dict[str, dict[str, str]]) -> dict[str, Any]:
    params = dict(call.get("parameters", {}))
    user_id = params.get("user_id")
    if call["tool_name"] in {"tally_total_tastes", "tally_total_nutritional_characteristics"}:
        recipes = [
            maps["recipe"].get(recipe.lower(), recipe)
            for recipe in db.user_menus.get(user_id, [])
        ]
        return {"user_id": user_id, "recipes": recipes}

    ingredients = []
    for item in db.user_shopping_lists.get(user_id, {}).values():
        ingredient_name = maps["ingredient"].get(item.ingredient_name.lower(), item.ingredient_name)
        ingredients.append({"ingredient_name": ingredient_name, "quantity": clean_number(item.quantity)})
    return {"user_id": user_id, "ingredients": ingredients}


def derive_expected_params(
    scenario: str,
    db: Any,
    call: dict[str, Any],
    maps: dict[str, dict[str, str]],
    *,
    include_set_meals_for_payment: bool = True,
) -> dict[str, Any]:
    if scenario == "retail":
        return derive_retail_params(db, call, maps)
    if scenario == "restaurant":
        return derive_restaurant_params(db, call, maps)
    if scenario == "order":
        return derive_order_params(
            db,
            call,
            maps,
            include_set_meals_for_payment=include_set_meals_for_payment,
        )
    if scenario == "kitchen":
        return derive_kitchen_params(db, call, maps)
    raise ValueError(scenario)


def list_params_match(tool_name: str, scenario: str, actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    scalar_keys = set(actual) | set(expected)
    list_key = None
    if "products" in scalar_keys:
        list_key = "products"
    elif "dishes" in scalar_keys:
        list_key = "dishes"
    elif "ingredients" in scalar_keys:
        list_key = "ingredients"
    elif "recipes" in scalar_keys:
        list_key = "recipes"
    if list_key:
        scalar_keys.remove(list_key)
    for key in scalar_keys:
        if norm_scalar(actual.get(key)) != norm_scalar(expected.get(key)):
            return False
    if list_key == "products":
        return norm_item_list(actual.get("products", []), "product_name") == norm_item_list(expected.get("products", []), "product_name")
    if list_key == "dishes":
        return norm_item_list(actual.get("dishes", []), "dish_name") == norm_item_list(expected.get("dishes", []), "dish_name")
    if list_key == "ingredients":
        return norm_item_list(actual.get("ingredients", []), "ingredient_name") == norm_item_list(expected.get("ingredients", []), "ingredient_name")
    if list_key == "recipes":
        return norm_name_list(actual.get("recipes", [])) == norm_name_list(expected.get("recipes", []))
    return True


def audit_scenario(name: str, *, apply: bool) -> dict[str, Any]:
    scenario, number, db_cls, seed = TARGETS[name]
    rows = json.loads(scenario_path(name).read_text(encoding="utf-8"))
    maps = display_maps(seed)
    changes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    checked = 0

    for task_index, row in enumerate(rows):
        db = db_cls()
        with contextlib.redirect_stdout(io.StringIO()):
            db.init_from_json(seed)
        gt_calls = row.get("ground_truth") or []
        for call_index, call in enumerate(gt_calls):
            tool_name = call.get("tool_name")
            if tool_name in AGGREGATE_TOOLS:
                checked += 1
                original_params = deepcopy(call.get("parameters", {}))
                later_calls = gt_calls[call_index + 1 :]
                include_set_meals_for_payment = not any(is_mutation_call(later) for later in later_calls)
                expected_params = derive_expected_params(
                    scenario,
                    db,
                    call,
                    maps,
                    include_set_meals_for_payment=include_set_meals_for_payment,
                )
                original_result = execute_call(db, call)
                expected_call = {"tool_name": tool_name, "parameters": expected_params}
                expected_result = execute_call(db, expected_call)
                params_match = list_params_match(tool_name, scenario, original_params, expected_params)
                result_match = results_equal(original_result, expected_result)
                if not params_match or not result_match:
                    record = {
                        "scenario": name,
                        "task_id": row.get("task_id", task_index + 1),
                        "call_index": call_index + 1,
                        "tool_name": tool_name,
                        "params_match": params_match,
                        "result_match": result_match,
                        "original_parameters": original_params,
                        "expected_parameters": expected_params,
                        "original_result": original_result,
                        "expected_result": expected_result,
                    }
                    changes.append(record)
                    if apply:
                        call["parameters"] = expected_params

            result = execute_call(db, call)
            if isinstance(result, dict) and result.get("status") == "error":
                errors.append(
                    {
                        "scenario": name,
                        "task_id": row.get("task_id", task_index + 1),
                        "call_index": call_index + 1,
                        "tool_name": tool_name,
                        "parameters": call.get("parameters", {}),
                        "result": result,
                    }
                )

    if apply and changes:
        scenario_path(name).write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "scenario": name,
        "scenario_type": scenario,
        "scenario_number": number,
        "tasks": len(rows),
        "aggregate_calls_checked": checked,
        "changes": changes,
        "execution_errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify and optionally fix GT compute/tally calls against DB tool results.")
    parser.add_argument("--scenarios", nargs="*", default=list(TARGETS), choices=list(TARGETS))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default=str(output_report_path()))
    args = parser.parse_args()

    reports = [audit_scenario(name, apply=args.apply) for name in args.scenarios]
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for report in reports:
        print(
            f"{report['scenario']}: tasks={report['tasks']} "
            f"aggregate_checked={report['aggregate_calls_checked']} "
            f"changes={len(report['changes'])} errors={len(report['execution_errors'])}"
        )
        for change in report["changes"][:8]:
            print(
                f"  task {change['task_id']} call {change['call_index']} {change['tool_name']}: "
                f"params_match={change['params_match']} result_match={change['result_match']}"
            )
        if len(report["changes"]) > 8:
            print(f"  ... {len(report['changes']) - 8} more changes")
        for error in report["execution_errors"][:5]:
            print(f"  ERROR task {error['task_id']} call {error['call_index']} {error['tool_name']}: {error['result']}")
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
