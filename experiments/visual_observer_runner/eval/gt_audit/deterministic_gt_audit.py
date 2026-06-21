#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.visual_observer_runner.eval.replay_gt_with_official_tools import (  # noqa: E402
    call_tool,
    db_for,
    normalize_numbers,
    params_equivalent,
    scenario_path,
)


def load_task(scenario: str, task_id: int) -> dict[str, Any]:
    rows = json.loads(scenario_path(scenario).read_text(encoding="utf-8"))
    for row in rows:
        if int(row.get("task_id")) == task_id:
            return row
    raise ValueError(f"task not found: {scenario} task {task_id}")


def call_with_label(db: Any, calls: list[dict[str, Any]], label: str, call: dict[str, Any]) -> dict[str, Any]:
    record = call_tool(db, call)
    record["label"] = label
    record["call_index"] = len(calls) + 1
    calls.append(record)
    return record


def matching_value(result: dict[str, Any], name: str) -> Any:
    matching = result.get("matching_dishes")
    if not isinstance(matching, dict):
        raise ValueError(f"tool result has no matching_dishes: {result}")
    wanted = name.strip().lower()
    for key, value in matching.items():
        if key.strip().lower() == wanted:
            return value
    if len(matching) == 1:
        return next(iter(matching.values()))
    raise ValueError(f"exact dish not found in matching_dishes: {name}; got {list(matching)}")


def compare_value(left: Any, op: str, right: Any) -> bool:
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == "==":
        return left == right
    raise ValueError(f"unsupported op: {op}")


def dishes_from_summary(summary_result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"dish_name": item.get("dish_name"), "quantity": item.get("quantity")}
        for item in summary_result.get("items", [])
    ]


def compare_gt(generated: list[dict[str, Any]], existing: list[dict[str, Any]]) -> dict[str, Any]:
    pair_results = []
    for index, (left, right) in enumerate(zip(generated, existing), start=1):
        pair_results.append(
            {
                "index": index,
                "generated_tool": left.get("tool_name"),
                "existing_tool": right.get("tool_name"),
                "match": (
                    str(left.get("tool_name", "")).lower() == str(right.get("tool_name", "")).lower()
                    and params_equivalent(left.get("parameters") or {}, right.get("parameters") or {})
                ),
            }
        )
    return {
        "length_match": len(generated) == len(existing),
        "all_pairs_match": len(generated) == len(existing) and all(item["match"] for item in pair_results),
        "pair_results": pair_results,
        "generated_len": len(generated),
        "existing_len": len(existing),
    }


def audit_order2_task6(spec: dict[str, Any]) -> dict[str, Any]:
    scenario = spec["scenario"]
    task_id = int(spec["task_id"])
    _, _, db, _ = db_for(scenario)
    row = load_task(scenario, task_id)
    tool_calls: list[dict[str, Any]] = []
    generated_gt: list[dict[str, Any]] = []
    notes: list[str] = []

    restaurant_name = spec["restaurant_name"]
    user_id = spec["user_id"]
    visual_values = row.get(spec["visual_anchor"]["source"]) or []
    anchor = visual_values[0] if visual_values else None
    expected_anchor = spec["visual_anchor"].get("expected")
    visual_anchor_ok = anchor == expected_anchor
    if not visual_anchor_ok:
        notes.append(f"visual anchor mismatch: expected {expected_anchor!r}, got {anchor!r}")

    branch_call = {
        "tool_name": spec["branch"]["evidence_tool"],
        "parameters": {"restaurant_name": restaurant_name, "dish_name": anchor},
    }
    branch_record = call_with_label(db, tool_calls, "branch_anchor_evidence", branch_call)
    branch_payload = matching_value(branch_record["result"], anchor)
    branch_value = branch_payload[spec["branch"]["field"]]
    branch_taken = compare_value(branch_value, spec["branch"]["op"], spec["branch"]["threshold"])

    candidate_evidence: list[dict[str, Any]] = []
    winners: list[str] = []
    if branch_taken:
        rank = spec["if_true"]["rank"]
        scored: list[dict[str, Any]] = []
        for candidate in spec["if_true"]["candidates"]:
            record = call_with_label(
                db,
                tool_calls,
                "candidate_ranking_evidence",
                {
                    "tool_name": rank["tool"],
                    "parameters": {"restaurant_name": restaurant_name, "dish_name": candidate},
                },
            )
            payload = matching_value(record["result"], candidate)
            score = payload[rank["field"]]
            scored.append({"candidate": candidate, "score": score})
            candidate_evidence.append({"candidate": candidate, "field": rank["field"], "value": score})
        best_score = min(item["score"] for item in scored) if rank["order"] == "min" else max(item["score"] for item in scored)
        winners = [item["candidate"] for item in scored if item["score"] == best_score]
        for winner in winners:
            mutation_call = {
                "tool_name": spec["if_true"]["mutation"]["tool_name"],
                "parameters": {
                    "restaurant_name": restaurant_name,
                    "user_id": user_id,
                    "dish_name": winner,
                    "quantity": spec["if_true"]["mutation"]["quantity"],
                },
            }
            mutation_record = call_with_label(db, tool_calls, "state_mutation", mutation_call)
            generated_gt.append(
                {
                    "tool_name": mutation_call["tool_name"],
                    "parameters": mutation_record["accepted_parameters"],
                }
            )
    else:
        notes.append("false branch is not implemented in this pilot spec because task6 evidence enters true branch")

    state_record = call_with_label(
        db,
        tool_calls,
        "current_state_after_mutation",
        {
            "tool_name": "get_user_order_summary",
            "parameters": {"restaurant_name": restaurant_name, "user_id": user_id},
        },
    )
    current_dishes = dishes_from_summary(state_record["result"])

    post_record = call_with_label(
        db,
        tool_calls,
        "post_check_branch_evidence_not_gt",
        {
            "tool_name": spec["post_check"]["tool_name"],
            "parameters": {"restaurant_name": restaurant_name, "user_id": user_id, "dishes": current_dishes},
        },
    )
    total_payment = post_record["result"].get("total_payment")
    post_check_blocks_extra_side = total_payment is not None and total_payment >= spec["post_check"]["threshold"]
    if post_check_blocks_extra_side:
        notes.append(
            "discounted payable amount is >= 100, so the undiscounted order total cannot be < 100; no side dish branch"
        )
    else:
        notes.append("post-check did not prove the side dish branch is false")

    for tool_name in spec["final_outputs"]:
        final_call = {
            "tool_name": tool_name,
            "parameters": {"restaurant_name": restaurant_name, "user_id": user_id, "dishes": current_dishes},
        }
        final_record = call_with_label(db, tool_calls, "final_output", final_call)
        generated_gt.append({"tool_name": tool_name, "parameters": final_record["accepted_parameters"]})

    existing_gt = row.get("ground_truth") or []
    comparison = compare_gt(generated_gt, existing_gt)
    return normalize_numbers(
        {
            "scenario": scenario,
            "task_id": task_id,
            "visual_anchor": {"source": spec["visual_anchor"]["source"], "value": anchor, "ok": visual_anchor_ok},
            "instruction": row.get("Instruction"),
            "branch_evidence": {
                "tool_call_index": branch_record["call_index"],
                "field": spec["branch"]["field"],
                "value": branch_value,
                "op": spec["branch"]["op"],
                "threshold": spec["branch"]["threshold"],
                "branch_taken": "if_true" if branch_taken else "if_false",
            },
            "candidate_scope": {
                "name": spec["if_true"]["candidate_scope_name"],
                "candidates": spec["if_true"]["candidates"],
                "ranking_evidence": candidate_evidence,
                "winners": winners,
            },
            "post_check": {
                "tool_call_index": post_record["call_index"],
                "discounted_total_payment": total_payment,
                "threshold": spec["post_check"]["threshold"],
                "extra_side_branch_blocked": post_check_blocks_extra_side,
                "description": spec["post_check"]["description"],
            },
            "current_state_after_mutation": state_record["result"],
            "generated_gt": generated_gt,
            "current_gt": existing_gt,
            "comparison": comparison,
            "notes": notes,
            "tool_calls": tool_calls,
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    if spec.get("scenario") == "order2" and int(spec.get("task_id")) == 6:
        report = audit_order2_task6(spec)
    else:
        raise ValueError("pilot deterministic audit currently supports only order2 task6")

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "match": report["comparison"]["all_pairs_match"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
