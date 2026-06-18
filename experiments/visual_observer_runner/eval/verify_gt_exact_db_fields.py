#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kitchen.kitchen_init import kitchen_init_data
from tools.order.order_init import order_init_data
from tools.restaurant.restaurant_init import restaurant_init_data5
from tools.retail.retail_init import retail_init_data6, retail_init_data10


TARGETS = ["retail6", "retail10", "kitchen4", "restaurant5", "order2"]


def scenario_rows(name: str) -> list[dict[str, Any]]:
    return json.loads((ROOT / "scenarios/final" / f"{name}.json").read_text(encoding="utf-8"))


def require_exact(value: Any, valid: set[str], where: str, errors: list[str]) -> None:
    if value not in valid:
        errors.append(f"{where}: {value!r} is not an exact DB value")


def require_equal(actual: Any, expected: Any, where: str, errors: list[str]) -> None:
    if actual != expected:
        errors.append(f"{where}: expected {expected!r}, got {actual!r}")


def retail_exact(name: str, seed: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    products = {p["name"]: p for p in seed["products"]}
    users = {u["user_id"] for u in seed["user_carts"]} | {u["user_id"] for u in seed["user_shopping_lists"]}
    for tidx, task in enumerate(scenario_rows(name), 1):
        require_equal(task.get("key"), "product_name", f"{name} task {tidx} key", errors)
        for value in task.get("value", []):
            require_exact(value, set(products), f"{name} task {tidx} value[]", errors)
        for cidx, call in enumerate(task.get("ground_truth") or [], 1):
            p = call.get("parameters", {})
            prefix = f"{name} task {tidx} call {cidx} {call.get('tool_name')}"
            if "user_id" in p:
                require_exact(p["user_id"], users, f"{prefix}.user_id", errors)
            if "product_name" in p:
                require_exact(p["product_name"], set(products), f"{prefix}.product_name", errors)
                prod = products.get(p["product_name"])
                if prod and call.get("tool_name") == "add_to_cart":
                    for field in ["category", "price", "tax_rate", "discount"]:
                        require_equal(p.get(field), prod[field], f"{prefix}.{field}", errors)
            for item_index, item in enumerate(p.get("products") or [], 1):
                require_exact(item.get("product_name"), set(products), f"{prefix}.products[{item_index}].product_name", errors)
                if not isinstance(item.get("quantity"), (int, float)) or item.get("quantity") <= 0:
                    errors.append(f"{prefix}.products[{item_index}].quantity must be positive numeric")
    return errors


def kitchen_exact() -> list[str]:
    errors: list[str] = []
    ingredients = {i["name"] for i in kitchen_init_data["ingredients"]}
    recipes = {r["name"] for r in kitchen_init_data["recipes"]}
    users = {u["user_id"] for u in kitchen_init_data["user_menus"]} | {u["user_id"] for u in kitchen_init_data["user_shopping_lists"]}
    for tidx, task in enumerate(scenario_rows("kitchen4"), 1):
        key = task.get("key")
        if key not in {"recipe_name", "ingredient_name"}:
            errors.append(f"kitchen4 task {tidx} key invalid: {key!r}")
        for value in task.get("value", []):
            require_exact(value, recipes if key == "recipe_name" else ingredients, f"kitchen4 task {tidx} value[]", errors)
        for cidx, call in enumerate(task.get("ground_truth") or [], 1):
            p = call.get("parameters", {})
            prefix = f"kitchen4 task {tidx} call {cidx} {call.get('tool_name')}"
            if "user_id" in p:
                require_exact(p["user_id"], users, f"{prefix}.user_id", errors)
            if "recipe_name" in p:
                require_exact(p["recipe_name"], recipes, f"{prefix}.recipe_name", errors)
            if "ingredient_name" in p:
                require_exact(p["ingredient_name"], ingredients, f"{prefix}.ingredient_name", errors)
            for item_index, item in enumerate(p.get("ingredients") or [], 1):
                require_exact(item.get("ingredient_name"), ingredients, f"{prefix}.ingredients[{item_index}].ingredient_name", errors)
                if not isinstance(item.get("quantity"), (int, float)) or item.get("quantity") <= 0:
                    errors.append(f"{prefix}.ingredients[{item_index}].quantity must be positive numeric")
            for item_index, recipe in enumerate(p.get("recipes") or [], 1):
                require_exact(recipe, recipes, f"{prefix}.recipes[{item_index}]", errors)
    return errors


def restaurant_exact() -> list[str]:
    errors: list[str] = []
    dishes = {d["name"] for d in restaurant_init_data5["dishes"]}
    sets = {s["name"] for s in restaurant_init_data5.get("set_meals", [])}
    users = {u["user_id"] for u in restaurant_init_data5["user_orders"]}
    for tidx, task in enumerate(scenario_rows("restaurant5"), 1):
        require_equal(task.get("key"), "dish_name", f"restaurant5 task {tidx} key", errors)
        for value in task.get("value", []):
            require_exact(value, dishes, f"restaurant5 task {tidx} value[]", errors)
        for cidx, call in enumerate(task.get("ground_truth") or [], 1):
            p = call.get("parameters", {})
            prefix = f"restaurant5 task {tidx} call {cidx} {call.get('tool_name')}"
            if "user_id" in p:
                require_exact(p["user_id"], users, f"{prefix}.user_id", errors)
            if "dish_name" in p:
                require_exact(p["dish_name"], dishes, f"{prefix}.dish_name", errors)
            if "set_meal_name" in p:
                require_exact(p["set_meal_name"], sets, f"{prefix}.set_meal_name", errors)
            for item_index, item in enumerate(p.get("dishes") or [], 1):
                dish_name = item.get("dish_name")
                set_name = item.get("set_meal_name")
                if dish_name is not None:
                    require_exact(dish_name, dishes | sets, f"{prefix}.dishes[{item_index}].dish_name", errors)
                if set_name is not None:
                    require_exact(set_name, sets, f"{prefix}.dishes[{item_index}].set_meal_name", errors)
                if not isinstance(item.get("quantity"), (int, float)) or item.get("quantity") <= 0:
                    errors.append(f"{prefix}.dishes[{item_index}].quantity must be positive numeric")
    return errors


def order_exact() -> list[str]:
    errors: list[str] = []
    restaurants = {d["restaurant_name"] for d in order_init_data["dishes"]} | {
        s["restaurant_name"] for s in order_init_data.get("set_meals", [])
    } | {u["restaurant_name"] for u in order_init_data["user_orders"]}
    dishes_by_rest: dict[str, dict[str, dict[str, Any]]] = {}
    sets_by_rest: dict[str, set[str]] = {}
    users = {u["user_id"] for u in order_init_data["user_orders"]}
    for d in order_init_data["dishes"]:
        dishes_by_rest.setdefault(d["restaurant_name"], {})[d["name"]] = d
    for s in order_init_data.get("set_meals", []):
        sets_by_rest.setdefault(s["restaurant_name"], set()).add(s["name"])
    all_dishes = {d["name"] for d in order_init_data["dishes"]}

    for tidx, task in enumerate(scenario_rows("order2"), 1):
        require_equal(task.get("key"), "dish_name", f"order2 task {tidx} key", errors)
        for value in task.get("value", []):
            require_exact(value, all_dishes, f"order2 task {tidx} value[]", errors)
        for cidx, call in enumerate(task.get("ground_truth") or [], 1):
            p = call.get("parameters", {})
            prefix = f"order2 task {tidx} call {cidx} {call.get('tool_name')}"
            rest = p.get("restaurant_name")
            if rest is not None:
                require_exact(rest, restaurants, f"{prefix}.restaurant_name", errors)
            if "user_id" in p:
                require_exact(p["user_id"], users, f"{prefix}.user_id", errors)
            valid_dishes = dishes_by_rest.get(rest, {}) if rest else {}
            valid_sets = sets_by_rest.get(rest, set()) if rest else set()
            if "dish_name" in p:
                require_exact(p["dish_name"], set(valid_dishes), f"{prefix}.dish_name", errors)
                dish = valid_dishes.get(p["dish_name"])
                if dish and call.get("tool_name") == "add_dish_to_order":
                    for field in ["category", "price", "tax_rate", "discount"]:
                        require_equal(p.get(field), dish[field], f"{prefix}.{field}", errors)
            if "set_meal_name" in p:
                require_exact(p["set_meal_name"], valid_sets, f"{prefix}.set_meal_name", errors)
            for item_index, item in enumerate(p.get("dishes") or [], 1):
                dish_name = item.get("dish_name")
                set_name = item.get("set_meal_name")
                if dish_name is not None:
                    require_exact(dish_name, set(valid_dishes) | valid_sets, f"{prefix}.dishes[{item_index}].dish_name", errors)
                if set_name is not None:
                    require_exact(set_name, valid_sets, f"{prefix}.dishes[{item_index}].set_meal_name", errors)
                if not isinstance(item.get("quantity"), (int, float)) or item.get("quantity") <= 0:
                    errors.append(f"{prefix}.dishes[{item_index}].quantity must be positive numeric")
    return errors


def main() -> None:
    checks = {
        "retail6": retail_exact("retail6", retail_init_data6),
        "retail10": retail_exact("retail10", retail_init_data10),
        "kitchen4": kitchen_exact(),
        "restaurant5": restaurant_exact(),
        "order2": order_exact(),
    }
    total_errors = 0
    for name in TARGETS:
        errors = checks[name]
        total_errors += len(errors)
        print(f"{name}: exact_field_errors={len(errors)}")
        for err in errors[:30]:
            print("  ", err)
    if total_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
