#!/usr/bin/env python3
"""Experiment-side relaxed tool-call equivalence checks.

This script does not replace the official EgoBench evaluator. It adds a local
diagnostic pass for cases where final DB state is correct but strict tool-call
matching misses equivalent aggregate parameters, for example split versus merged
product quantities in compute_total_* calls.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from typing import Any


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from analysis_scripts.evaluate_interaction import (  # noqa: E402
    compare_parameters_with_fuzzy_match,
    get_init_db,
    simplify_tool_calls,
)


NAME_KEYS = ("product_name", "dish_name", "ingredient_name", "recipe_name", "set_meal_name")
QUANTITY_KEYS = ("quantity", "qty")


def extract_interaction_calls(interaction_tool_logs: list[dict[str, Any]], db_instance: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for entry in interaction_tool_logs:
        batch = entry.get("calls")
        if not isinstance(batch, list):
            call = entry.get("call")
            batch = [call] if isinstance(call, dict) else []
        for call in batch:
            if not isinstance(call, dict):
                continue
            tool_name = call.get("tool_name") or call.get("name")
            params = dict(call.get("parameters", {}))
            if db_instance is not None and hasattr(db_instance, str(tool_name)):
                try:
                    sig = inspect.signature(getattr(db_instance, str(tool_name)))
                    params = {key: value for key, value in params.items() if key in sig.parameters}
                except (TypeError, ValueError):
                    pass
            calls.append({"tool_name": tool_name, "parameters": params})
    return calls


def norm_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.lower().strip().split())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def aggregate_item_list(items: list[Any]) -> dict[tuple[Any, ...], float]:
    aggregated: dict[tuple[Any, ...], float] = {}
    for item in items:
        if not isinstance(item, dict):
            key = (norm_scalar(item),)
            quantity = 1.0
        else:
            name_key = next((key for key in NAME_KEYS if key in item), None)
            if name_key:
                key = (name_key, norm_scalar(item[name_key]))
            else:
                non_quantity = {
                    key: norm_scalar(value)
                    for key, value in item.items()
                    if key not in QUANTITY_KEYS
                }
                key = tuple(sorted(non_quantity.items()))
            quantity_key = next((key for key in QUANTITY_KEYS if key in item), None)
            quantity = float(item.get(quantity_key, 1)) if quantity_key else 1.0
        aggregated[key] = aggregated.get(key, 0.0) + quantity
    return aggregated


def aggregate_equal(left: dict[tuple[Any, ...], float], right: dict[tuple[Any, ...], float]) -> bool:
    if set(left) != set(right):
        return False
    for key in left:
        if abs(float(left[key]) - float(right[key])) > 1e-9:
            return False
    return True


def relaxed_compute_params_match(
    gt_params: dict[str, Any],
    actual_params: dict[str, Any],
    *,
    db_instance: Any,
    scenario: str,
) -> bool:
    gt_base: dict[str, Any] = {}
    actual_base: dict[str, Any] = {}
    list_fields: set[str] = set()
    for key, value in gt_params.items():
        if isinstance(value, list):
            list_fields.add(key)
        else:
            gt_base[key] = value
    for key, value in actual_params.items():
        if isinstance(value, list):
            list_fields.add(key)
        else:
            actual_base[key] = value

    if not compare_parameters_with_fuzzy_match(gt_base, actual_base, db_instance, scenario):
        return False

    for field in list_fields:
        gt_value = gt_params.get(field)
        actual_value = actual_params.get(field)
        if not isinstance(gt_value, list) or not isinstance(actual_value, list):
            return False
        if not aggregate_equal(aggregate_item_list(gt_value), aggregate_item_list(actual_value)):
            return False
    return True


def calls_match(
    gt_call: dict[str, Any],
    actual_call: dict[str, Any],
    *,
    db_instance: Any,
    scenario: str,
) -> tuple[bool, str]:
    if gt_call.get("tool_name") != actual_call.get("tool_name"):
        return False, "tool_name"
    gt_params = gt_call.get("parameters", {})
    actual_params = actual_call.get("parameters", {})
    tool_name = str(gt_call.get("tool_name") or "")
    if tool_name.startswith("compute_total_") and relaxed_compute_params_match(
        gt_params,
        actual_params,
        db_instance=db_instance,
        scenario=scenario,
    ):
        return True, "relaxed_aggregate"
    if compare_parameters_with_fuzzy_match(gt_params, actual_params, db_instance, scenario):
        return True, "strict"
    return False, "parameters"


def evaluate_task(
    gt_calls: list[dict[str, Any]],
    interaction_calls: list[dict[str, Any]],
    *,
    db_instance: Any,
    scenario: str,
) -> dict[str, Any]:
    matched_indices: set[int] = set()
    match_details: list[dict[str, Any]] = []
    for gt_index, gt_call in enumerate(gt_calls):
        for actual_index, actual_call in enumerate(interaction_calls):
            if actual_index in matched_indices:
                continue
            matched, mode = calls_match(gt_call, actual_call, db_instance=db_instance, scenario=scenario)
            if matched:
                matched_indices.add(actual_index)
                match_details.append(
                    {
                        "gt_index": gt_index,
                        "actual_index": actual_index,
                        "tool_name": gt_call.get("tool_name"),
                        "mode": mode,
                    }
                )
                break
    return {
        "matches": len(match_details),
        "total_gt_calls": len(gt_calls),
        "total_interaction_calls": len(interaction_calls),
        "success": len(match_details) == len(gt_calls),
        "match_details": match_details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run relaxed experiment-side tool equivalence diagnostics.")
    parser.add_argument("--model_name", required=True)
    parser.add_argument("--scenario", required=True, choices=["retail", "kitchen", "restaurant", "order"])
    parser.add_argument("--scenario_number", required=True, type=int)
    parser.add_argument("--task_ids", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    scenario_key = f"{args.scenario}{args.scenario_number}"
    gt_path = PROJECT_ROOT / "scenarios" / "final" / f"{scenario_key}.json"
    interaction_path = PROJECT_ROOT / "results" / args.model_name / f"{scenario_key}_easy.json"
    if not gt_path.exists():
        raise FileNotFoundError(gt_path)
    if not interaction_path.exists():
        raise FileNotFoundError(interaction_path)

    task_filter = {
        int(part.strip())
        for part in args.task_ids.split(",")
        if part.strip()
    }

    gt_data = json.loads(gt_path.read_text(encoding="utf-8"))
    interaction_data = json.loads(interaction_path.read_text(encoding="utf-8"))
    interaction_by_task_id = {int(item.get("task_id")): item for item in interaction_data if item.get("task_id") is not None}
    db_instance = get_init_db(args.scenario, args.scenario_number)

    task_results: list[dict[str, Any]] = []
    for idx, gt_item in enumerate(gt_data, start=1):
        task_id = int(gt_item.get("task_id", idx))
        if task_filter and task_id not in task_filter:
            continue
        interaction_item = interaction_by_task_id.get(task_id)
        if not interaction_item:
            continue
        gt_calls = simplify_tool_calls(db_instance, gt_item.get("ground_truth", []))
        actual_calls = extract_interaction_calls(interaction_item.get("tool_calls", []), db_instance)
        relaxed = evaluate_task(gt_calls, actual_calls, db_instance=db_instance, scenario=args.scenario)
        task_results.append({"task_id": task_id, "relaxed_tool_based": relaxed})

    output = {
        "model_name": args.model_name,
        "scenario": scenario_key,
        "tasks": task_results,
        "success_count": sum(1 for item in task_results if item["relaxed_tool_based"]["success"]),
        "task_count": len(task_results),
    }

    output_path = Path(args.output) if args.output else (
        PROJECT_ROOT
        / "experiments"
        / "gpt55_frame_service_runner"
        / "cache"
        / "eval_equivalence"
        / f"{args.model_name}_{scenario_key}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"Saved relaxed equivalence report to: {output_path}")


if __name__ == "__main__":
    main()
