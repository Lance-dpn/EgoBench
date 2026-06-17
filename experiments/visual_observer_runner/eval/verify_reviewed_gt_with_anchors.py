#!/usr/bin/env python3
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis_scripts.evaluate_interaction import evaluate_interaction_success
from tools.kitchen.kitchen_db import KitchenDB
from tools.kitchen.kitchen_init import kitchen_init_data
from tools.order.order_db import OrderDB
from tools.order.order_init import order_init_data
from tools.restaurant.restaurant_db import RestaurantDB
from tools.restaurant.restaurant_init import restaurant_init_data5
from tools.retail.retail_db import RetailDB
from tools.retail.retail_init import retail_init_data6, retail_init_data10


TARGETS = {
    "retail6": ("retail", 6, RetailDB, retail_init_data6),
    "retail10": ("retail", 10, RetailDB, retail_init_data10),
    "kitchen4": ("kitchen", 4, KitchenDB, kitchen_init_data),
    "restaurant5": ("restaurant", 5, RestaurantDB, restaurant_init_data5),
    "order2": ("order", 2, OrderDB, order_init_data),
}


def load_scenario(name: str) -> list[dict[str, Any]]:
    return json.loads((ROOT / "scenarios/final" / f"{name}.json").read_text(encoding="utf-8"))


def validate_anchor_values(name: str, scenario: str, number: int, rows: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if scenario == "retail":
        seed = retail_init_data6 if number == 6 else retail_init_data10
        valid = {p["name"].lower() for p in seed["products"]}
        expected_keys = {"product_name"}
    elif scenario == "kitchen":
        valid_recipe = {r["name"].lower() for r in kitchen_init_data["recipes"]}
        valid_ing = {i["name"].lower() for i in kitchen_init_data["ingredients"]}
        expected_keys = {"recipe_name", "ingredient_name"}
    elif scenario == "restaurant":
        valid_dish = {d["name"].lower() for d in restaurant_init_data5["dishes"]}
        valid_set = {s["name"].lower() for s in restaurant_init_data5.get("set_meals", [])}
        expected_keys = {"dish_name", "set_meal_name", "category"}
    elif scenario == "order":
        valid_dish = {d["name"].lower() for d in order_init_data["dishes"]}
        valid_set = {s["name"].lower() for s in order_init_data.get("set_meals", [])}
        expected_keys = {"dish_name", "set_meal_name", "category"}
    else:
        raise ValueError(scenario)

    for idx, row in enumerate(rows, 1):
        key = row.get("key")
        values = row.get("value")
        if key not in expected_keys:
            errors.append(f"{name} task {idx}: unexpected or missing key={key!r}")
            continue
        if not isinstance(values, list) or not values:
            errors.append(f"{name} task {idx}: value must be a non-empty list")
            continue
        for value in values:
            lower = str(value).lower()
            if scenario == "kitchen" and key == "recipe_name" and lower not in valid_recipe:
                errors.append(f"{name} task {idx}: recipe anchor not found: {value}")
            elif scenario == "kitchen" and key == "ingredient_name" and lower not in valid_ing:
                errors.append(f"{name} task {idx}: ingredient anchor not found: {value}")
            elif scenario == "retail" and lower not in valid:
                errors.append(f"{name} task {idx}: product anchor not found: {value}")
            elif scenario in {"restaurant", "order"} and key == "dish_name" and lower not in valid_dish:
                errors.append(f"{name} task {idx}: dish anchor not found: {value}")
            elif scenario in {"restaurant", "order"} and key == "set_meal_name" and lower not in valid_set:
                errors.append(f"{name} task {idx}: set-meal anchor not found: {value}")
    return errors


def execute_gt(name: str, db_cls: type, seed: dict[str, Any], rows: list[dict[str, Any]]) -> list[tuple[Any, int, str, dict[str, Any], dict[str, Any]]]:
    errors = []
    for row in rows:
        db = db_cls()
        db.init_from_json(seed)
        for index, call in enumerate(row.get("ground_truth") or [], 1):
            tool_name = call["tool_name"]
            params = call.get("parameters", {})
            method = getattr(db, tool_name)
            sig = inspect.signature(method)
            valid_params = {k: v for k, v in params.items() if k in sig.parameters}
            result = method(**valid_params)
            if isinstance(result, dict) and result.get("status") == "error":
                errors.append((row.get("task_id"), index, tool_name, valid_params, result))
                break
    return errors


def official_eval(name: str, scenario: str, number: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenario_path = ROOT / "scenarios/final" / f"{name}.json"
    interaction = []
    for row in rows:
        gt = row.get("ground_truth") or []
        interaction.append(
            {
                "task_id": row.get("task_id"),
                "tool_calls": [{"turn": 0, "calls": gt, "results": []}],
                "tokens_consumed": 0,
                "rounds_count": 1,
                "tool_calls_count": len(gt),
            }
        )
    out = Path("/tmp") / f"{name}_gt_as_interaction.json"
    out.write_text(json.dumps(interaction, ensure_ascii=False, indent=2), encoding="utf-8")
    return evaluate_interaction_success(
        str(scenario_path),
        str(out),
        scenario=scenario,
        args=SimpleNamespace(scenario_number=number),
        silent=True,
    )


def main() -> None:
    overall_errors: list[str] = []
    for name, (scenario, number, db_cls, seed) in TARGETS.items():
        rows = load_scenario(name)
        anchor_errors = validate_anchor_values(name, scenario, number, rows)
        exec_errors = execute_gt(name, db_cls, seed, rows)
        result = official_eval(name, scenario, number, rows)
        joint = result["joint_success"]
        micro = result["micro_tool_stats"]
        print(
            f"{name}: tasks={len(rows)} anchors={'ok' if not anchor_errors else len(anchor_errors)} "
            f"db_errors={len(exec_errors)} joint={joint['success_count']}/{result['total_scenarios']} "
            f"micro={micro['micro_accuracy']}"
        )
        for error in anchor_errors[:10]:
            print("  anchor_error:", error)
        for error in exec_errors[:10]:
            print("  exec_error:", error)
        if anchor_errors:
            overall_errors.extend(anchor_errors)
        if exec_errors:
            overall_errors.extend(f"{name} execution error: {err}" for err in exec_errors)
        if joint["success_count"] != result["total_scenarios"] or micro["micro_accuracy"] != 1.0:
            overall_errors.append(f"{name} official eval failed: joint={joint}, micro={micro}")
    if overall_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
