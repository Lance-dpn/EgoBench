#!/usr/bin/env python3
"""Task-id aligned evaluator for partial LangGraph EgoBench result files.

The official evaluator aligns ground-truth and interaction rows by list index.
That is correct for full scenario files, but random task subsets must be
matched by task_id or the reported accuracy is meaningless.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from analysis_scripts.evaluate_interaction import (  # noqa: E402
    calculate_db_hash,
    compare_tool_calls,
    execute_tool_chain,
    get_init_db,
    simplify_tool_calls,
)


SCENARIO_FILE_RE = re.compile(r"^([a-z]+)(\d+)_(easy|hard|static)\.json$")


def flatten_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for entry in tool_calls:
        if not isinstance(entry, dict):
            continue
        calls = entry.get("calls")
        if isinstance(calls, list):
            flattened.extend(call for call in calls if isinstance(call, dict))
            continue
        call = entry.get("call")
        if isinstance(call, dict):
            flattened.append(call)
    return flattened


def has_agent_final_reply(row: dict[str, Any]) -> bool:
    return any(
        item.get("role") == "agent" and str(item.get("content") or "").strip()
        for item in row.get("dialogue", [])
        if isinstance(item, dict)
    )


def _quantity_number(value: Any) -> float | int | Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        rounded = round(float(value), 10)
        return int(rounded) if rounded.is_integer() else rounded
    try:
        rounded = round(float(value), 10)
        return int(rounded) if rounded.is_integer() else rounded
    except (TypeError, ValueError):
        return value


def _normalize_numbers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_numbers(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_numbers(item) for item in value]
    return _quantity_number(value)


def _kitchen_merge_shopping_list_adds(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Treat repeated kitchen ingredient adds as process-equivalent totals.

    Some service runs combine add_to_shopping_list calls for the same
    user/ingredient into one summed quantity. That produces the same KitchenDB
    state and should not fail process evaluation for partial rerun diagnostics.
    """
    merged: list[dict[str, Any]] = []
    index_by_key: dict[tuple[str, str, str], int] = {}

    for call in calls:
        normalized = _normalize_numbers(copy.deepcopy(call))
        tool_name = normalized.get("tool_name") or normalized.get("name")
        params = normalized.get("parameters", {})
        if tool_name != "add_to_shopping_list" or not isinstance(params, dict):
            merged.append(normalized)
            continue

        key = (
            str(params.get("user_id", "")).strip().lower(),
            str(params.get("ingredient_name", "")).strip().lower(),
            tool_name,
        )
        quantity = _quantity_number(params.get("quantity", 0))
        if key not in index_by_key or not isinstance(quantity, (int, float)):
            params["quantity"] = quantity
            index_by_key[key] = len(merged)
            merged.append(normalized)
            continue

        existing = merged[index_by_key[key]]
        existing_params = existing.setdefault("parameters", {})
        existing_qty = _quantity_number(existing_params.get("quantity", 0))
        if isinstance(existing_qty, (int, float)):
            existing_params["quantity"] = _quantity_number(existing_qty + quantity)
        else:
            merged.append(normalized)

    return _normalize_numbers(merged)


def compare_tool_calls_with_process_equivalence(
    scenario: str,
    gt_calls: list[dict[str, Any]],
    interaction_tool_calls: list[dict[str, Any]],
    db_for_matching: Any,
) -> tuple[int, int, int, bool]:
    matches, total_gt, total_actual = compare_tool_calls(
        gt_calls,
        interaction_tool_calls,
        db_for_matching,
        scenario,
    )
    if matches == total_gt and total_gt > 0:
        return matches, total_gt, total_actual, False

    if scenario != "kitchen":
        return matches, total_gt, total_actual, False

    merged_gt_calls = _kitchen_merge_shopping_list_adds(gt_calls)
    merged_actual_calls = _kitchen_merge_shopping_list_adds(flatten_calls(interaction_tool_calls))
    merged_matches, merged_total_gt, merged_total_actual = compare_tool_calls(
        merged_gt_calls,
        [{"turn": 0, "calls": merged_actual_calls}],
        db_for_matching,
        scenario,
    )
    if merged_matches == merged_total_gt and merged_total_gt > 0:
        return merged_matches, merged_total_gt, merged_total_actual, True
    return matches, total_gt, total_actual, False


def evaluate_file(result_file: Path) -> dict[str, Any]:
    match = SCENARIO_FILE_RE.match(result_file.name)
    if not match:
        raise ValueError(f"Unrecognized result filename: {result_file.name}")
    scenario = match.group(1)
    scenario_number = int(match.group(2))
    scenario_key = f"{scenario}{scenario_number}"
    gt_file = PROJECT_ROOT / "scenarios" / "final" / f"{scenario_key}.json"
    if not gt_file.exists():
        raise FileNotFoundError(gt_file)

    gt_rows = json.loads(gt_file.read_text(encoding="utf-8"))
    gt_by_task_id = {int(row.get("task_id", index + 1)): row for index, row in enumerate(gt_rows)}
    result_rows = json.loads(result_file.read_text(encoding="utf-8"))
    db_for_matching = get_init_db(scenario, scenario_number)

    details: list[dict[str, Any]] = []
    totals = {
        "task_count": 0,
        "final_reply_count": 0,
        "tool_success_count": 0,
        "result_success_count": 0,
        "joint_success_count": 0,
        "matched_tool_calls": 0,
        "ground_truth_tool_calls": 0,
        "actual_tool_calls": 0,
    }

    for row in result_rows:
        if not isinstance(row, dict) or row.get("task_id") is None:
            continue
        task_id = int(row["task_id"])
        gt_row = gt_by_task_id.get(task_id)
        if gt_row is None:
            details.append({"task_id": task_id, "error": "missing_gt_task_id"})
            continue

        gt_calls = simplify_tool_calls(db_for_matching, gt_row.get("ground_truth", []))
        raw_matches, raw_total_gt, raw_total_actual = compare_tool_calls(
            gt_calls,
            row.get("tool_calls", []),
            db_for_matching,
            scenario,
        )
        matches, total_gt, total_actual, process_equivalent = compare_tool_calls_with_process_equivalence(
            scenario,
            gt_calls,
            row.get("tool_calls", []),
            db_for_matching,
        )
        tool_success = matches == total_gt and total_gt > 0

        result_success = False
        try:
            gt_db = get_init_db(scenario, scenario_number)
            execute_tool_chain(gt_db, gt_calls)
            gt_hash = calculate_db_hash(gt_db)

            actual_db = get_init_db(scenario, scenario_number)
            execute_tool_chain(actual_db, flatten_calls(row.get("tool_calls", [])))
            actual_hash = calculate_db_hash(actual_db)
            result_success = gt_hash == actual_hash
        except Exception as exc:  # pragma: no cover - diagnostic path
            details.append({"task_id": task_id, "error": f"result_eval_failed: {exc}"})

        final_reply = has_agent_final_reply(row)
        joint_success = tool_success and result_success
        totals["task_count"] += 1
        totals["final_reply_count"] += int(final_reply)
        totals["tool_success_count"] += int(tool_success)
        totals["result_success_count"] += int(result_success)
        totals["joint_success_count"] += int(joint_success)
        totals["matched_tool_calls"] += matches
        totals["ground_truth_tool_calls"] += total_gt
        totals["actual_tool_calls"] += total_actual
        details.append(
            {
                "task_id": task_id,
                "final_reply": final_reply,
                "tool_success": tool_success,
                "result_success": result_success,
                "joint_success": joint_success,
                "matched_tool_calls": matches,
                "ground_truth_tool_calls": total_gt,
                "actual_tool_calls": total_actual,
                "raw_matched_tool_calls": raw_matches,
                "raw_ground_truth_tool_calls": raw_total_gt,
                "raw_actual_tool_calls": raw_total_actual,
                "process_equivalent": process_equivalent,
                "user_turns": row.get("user_turns_count")
                or sum(1 for item in row.get("dialogue", []) if item.get("role") == "user"),
                "agent_turns": row.get("agent_turns_count")
                or sum(1 for item in row.get("dialogue", []) if item.get("role") == "agent"),
                "error": row.get("error"),
            }
        )

    task_count = totals["task_count"]
    gt_call_count = totals["ground_truth_tool_calls"]
    return {
        "file": str(result_file),
        "scenario": scenario_key,
        **totals,
        "final_reply_rate": totals["final_reply_count"] / task_count if task_count else 0.0,
        "tool_success_rate": totals["tool_success_count"] / task_count if task_count else 0.0,
        "result_success_rate": totals["result_success_count"] / task_count if task_count else 0.0,
        "joint_success_rate": totals["joint_success_count"] / task_count if task_count else 0.0,
        "micro_tool_accuracy": totals["matched_tool_calls"] / gt_call_count if gt_call_count else 0.0,
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate partial result files by task_id.")
    parser.add_argument("paths", nargs="+", help="Result JSON files or result directories.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    args = parser.parse_args()

    files: list[Path] = []
    for raw_path in args.paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(sorted(path.glob("*_easy.json")))
            files.extend(sorted(path.glob("*_hard.json")))
            files.extend(sorted(path.glob("*_static.json")))
        else:
            files.append(path)

    reports = [evaluate_file(path) for path in files]
    summary = {
        "files": reports,
        "task_count": sum(item["task_count"] for item in reports),
        "final_reply_count": sum(item["final_reply_count"] for item in reports),
        "tool_success_count": sum(item["tool_success_count"] for item in reports),
        "result_success_count": sum(item["result_success_count"] for item in reports),
        "joint_success_count": sum(item["joint_success_count"] for item in reports),
        "matched_tool_calls": sum(item["matched_tool_calls"] for item in reports),
        "ground_truth_tool_calls": sum(item["ground_truth_tool_calls"] for item in reports),
        "actual_tool_calls": sum(item["actual_tool_calls"] for item in reports),
    }
    task_count = summary["task_count"]
    gt_call_count = summary["ground_truth_tool_calls"]
    summary.update(
        {
            "final_reply_rate": summary["final_reply_count"] / task_count if task_count else 0.0,
            "tool_success_rate": summary["tool_success_count"] / task_count if task_count else 0.0,
            "result_success_rate": summary["result_success_count"] / task_count if task_count else 0.0,
            "joint_success_rate": summary["joint_success_count"] / task_count if task_count else 0.0,
            "micro_tool_accuracy": summary["matched_tool_calls"] / gt_call_count if gt_call_count else 0.0,
        }
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved report to: {output_path}")


if __name__ == "__main__":
    main()
