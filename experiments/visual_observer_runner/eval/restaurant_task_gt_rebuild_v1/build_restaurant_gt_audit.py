"""Build restaurant task-level GT audit artifacts.

This script intentionally does not infer corrected GT for tasks that have not
been manually reviewed. Unreviewed tasks remain pending so we do not accidentally
convert official GT into "corrected" GT.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.restaurant.restaurant_db import RestaurantDB
from tools.restaurant.restaurant_init import restaurant_init_data


OUT_DIR = Path(__file__).resolve().parent
SCENARIO_DIR = ROOT / "scenarios" / "final"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": call.get("tool_name"),
        "parameters": call.get("parameters", {}),
    }


def calls_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    return [canonical_tool_call(item) for item in left] == [canonical_tool_call(item) for item in right]


def init_db() -> RestaurantDB:
    db = RestaurantDB()
    db.init_from_json(restaurant_init_data)
    return db


def call_tool(db: RestaurantDB, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    method = getattr(db, tool_name, None)
    if method is None:
        return {"status": "error", "message": f"Unknown tool: {tool_name}"}
    try:
        return method(**params)
    except TypeError as exc:
        # Scenario ground_truth sometimes uses richer metadata than the DB method
        # accepts, e.g. category/price/tax_rate on add_dish_to_order.
        trimmed = dict(params)
        if tool_name == "add_dish_to_order":
            trimmed = {
                "user_id": params.get("user_id"),
                "dish_name": params.get("dish_name"),
                "quantity": params.get("quantity", 1),
            }
        elif tool_name == "add_set_meal_to_order":
            trimmed = {
                "user_id": params.get("user_id"),
                "set_meal_name": params.get("set_meal_name"),
                "quantity": params.get("quantity", 1),
            }
        elif tool_name == "remove_dish_from_order":
            trimmed = {
                "user_id": params.get("user_id"),
                "dish_name": params.get("dish_name"),
                "quantity": params.get("quantity", 1),
            }
        elif tool_name == "remove_set_meal_from_order":
            trimmed = {
                "user_id": params.get("user_id"),
                "set_meal_name": params.get("set_meal_name"),
                "quantity": params.get("quantity", 1),
            }
        try:
            result = method(**trimmed)
        except Exception as inner_exc:  # pragma: no cover - diagnostic artifact
            return {
                "status": "error",
                "message": str(inner_exc),
                "original_type_error": str(exc),
                "trimmed_parameters": trimmed,
            }
        return {"status": "success_after_parameter_trim", "trimmed_parameters": trimmed, "result": result}
    except Exception as exc:  # pragma: no cover - diagnostic artifact
        return {"status": "error", "message": str(exc)}


def replay_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    db = init_db()
    trace = []
    for call in calls:
        tool_name = call.get("tool_name")
        params = call.get("parameters", {})
        result = call_tool(db, tool_name, params)
        trace.append({"tool_name": tool_name, "parameters": params, "result": result})
    return trace


def main() -> None:
    manual = load_json(OUT_DIR / "manual_corrected_cases.json")
    manual_by_key = {
        (int(item["scenario_number"]), int(item["task_id"])): item
        for item in manual.get("cases", [])
    }

    all_audit = []
    review_required = []
    summary = {
        "schema_version": "restaurant_gt_rebuild_summary_v1",
        "total_tasks": 0,
        "manual_reviewed": 0,
        "same_as_official_after_review": 0,
        "review_required": 0,
        "pending_manual_rebuild": 0,
        "by_scenario": {},
    }

    for scenario_number in range(1, 5):
        scenario_path = SCENARIO_DIR / f"restaurant{scenario_number}.json"
        tasks = load_json(scenario_path)
        corrected_records = []
        scenario_summary = {
            "tasks": len(tasks),
            "manual_reviewed": 0,
            "same_as_official_after_review": 0,
            "review_required": 0,
            "pending_manual_rebuild": 0,
        }

        for task in tasks:
            task_id = int(task["task_id"])
            official_gt = task.get("ground_truth", [])
            manual_case = manual_by_key.get((scenario_number, task_id))
            if manual_case is None:
                status = "pending_manual_rebuild"
                corrected_gt = None
                visual_slots = []
                diff = {
                    "has_difference": None,
                    "difference_type": [],
                    "notes": "Task has not yet been rebuilt from instruction, visual evidence, and tool replay.",
                }
                confidence = None
            else:
                status = manual_case["status"]
                corrected_gt = manual_case.get("corrected_ground_truth")
                if corrected_gt is None:
                    corrected_gt = official_gt
                visual_slots = manual_case.get("visual_slots", [])
                same = calls_equal(corrected_gt, official_gt)
                diff = {
                    "has_difference": not same,
                    "difference_type": [] if same else ["manual_corrected_gt_differs_from_official"],
                    "notes": manual_case.get("difference_summary", ""),
                }
                confidence = manual_case.get("confidence")
                scenario_summary["manual_reviewed"] += 1
                summary["manual_reviewed"] += 1

            replay_target = corrected_gt if corrected_gt is not None else official_gt
            replay_trace = replay_calls(replay_target)
            audit = {
                "schema_version": "restaurant_task_gt_audit_v1",
                "scenario": "restaurant",
                "scenario_number": scenario_number,
                "task_id": task_id,
                "instruction_source": "Instruction",
                "instruction": task.get("Instruction", ""),
                "visual_slots": visual_slots,
                "tool_trace": replay_trace,
                "corrected_ground_truth": corrected_gt,
                "official_ground_truth": official_gt,
                "diff": diff,
                "status": status,
                "confidence": confidence,
            }
            all_audit.append(audit)
            corrected_records.append(
                {
                    "scenario": "restaurant",
                    "scenario_number": scenario_number,
                    "task_id": task_id,
                    "instruction": task.get("Instruction", ""),
                    "status": status,
                    "confidence": confidence,
                    "corrected_ground_truth": corrected_gt,
                    "official_ground_truth": official_gt,
                    "diff": diff,
                }
            )

            summary["total_tasks"] += 1
            scenario_summary[status] = scenario_summary.get(status, 0) + 1
            if status == "same_as_official_after_review":
                summary["same_as_official_after_review"] += 1
            elif status == "review_required":
                summary["review_required"] += 1
                review_required.append(audit)
            elif status == "pending_manual_rebuild":
                summary["pending_manual_rebuild"] += 1

        summary["by_scenario"][f"restaurant{scenario_number}"] = scenario_summary
        write_json(OUT_DIR / f"corrected_ground_truth_restaurant{scenario_number}.json", corrected_records)

    with (OUT_DIR / "restaurant_gt_audit.jsonl").open("w", encoding="utf-8") as f:
        for row in all_audit:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_json(OUT_DIR / "review_required_cases.json", review_required)
    write_json(OUT_DIR / "summary.json", summary)

    report_lines = [
        "# Restaurant GT Rebuild Diff Report",
        "",
        f"- Total tasks: {summary['total_tasks']}",
        f"- Manual reviewed: {summary['manual_reviewed']}",
        f"- Same as official after review: {summary['same_as_official_after_review']}",
        f"- Review required: {summary['review_required']}",
        f"- Pending manual rebuild: {summary['pending_manual_rebuild']}",
        "",
        "## Review Required",
        "",
    ]
    for row in review_required:
        report_lines.append(
            f"- restaurant{row['scenario_number']} task {row['task_id']}: {row['diff']['notes']}"
        )
    report_lines.append("")
    report_lines.append("## Pending")
    report_lines.append("")
    report_lines.append("Tasks marked `pending_manual_rebuild` have not yet been treated as corrected GT.")
    (OUT_DIR / "restaurant_gt_diff_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
