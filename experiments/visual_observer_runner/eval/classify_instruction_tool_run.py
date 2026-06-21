#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.visual_observer_runner.eval.replay_gt_with_official_tools import (
    AGGREGATE_TOOLS,
    params_equivalent,
)
from experiments.visual_observer_runner.eval.summarize_instruction_tool_run import load_latest


STATE_PREFIXES = ("add_", "remove_", "clear_", "update_", "create_", "delete_")


def tool_name(call: dict[str, Any]) -> str:
    return str(call.get("tool_name") or call.get("name") or "")


def is_state_call(call: dict[str, Any]) -> bool:
    return tool_name(call).startswith(STATE_PREFIXES)


def is_aggregate_call(call: dict[str, Any]) -> bool:
    return tool_name(call) in AGGREGATE_TOOLS


def calls_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return tool_name(left).lower() == tool_name(right).lower() and params_equivalent(
        left.get("parameters") or {},
        right.get("parameters") or {},
    )


def strip_extra_aggregate_evidence(
    generated: list[dict[str, Any]], existing: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[int]]:
    """Remove aggregate calls from generated that are not needed to align existing.

    This identifies the common case where the execution agent correctly called a
    compute tool to prove a branch condition, then included that evidence call in
    generated GT even though benchmark GT only contains final requested outputs.
    """
    kept: list[dict[str, Any]] = []
    removed_indices: list[int] = []
    existing_index = 0
    for index, call in enumerate(generated):
        if existing_index < len(existing) and calls_match(call, existing[existing_index]):
            kept.append(call)
            existing_index += 1
            continue
        if is_aggregate_call(call):
            removed_indices.append(index + 1)
            continue
        kept.append(call)
    return kept, removed_indices


def state_sequence(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call for call in calls if is_state_call(call)]


def aggregate_sequence(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call for call in calls if is_aggregate_call(call)]


def sequence_matches(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    return len(left) == len(right) and all(calls_match(a, b) for a, b in zip(left, right))


def classify_record(record: dict[str, Any]) -> dict[str, Any]:
    generated = record.get("generated_ground_truth") or []
    existing = record.get("existing_ground_truth") or []
    comparison = record.get("gt_comparison") or {}
    if record.get("error"):
        label = "execution_error"
    elif comparison.get("all_pairs_match"):
        label = "exact_match"
    else:
        filtered, removed = strip_extra_aggregate_evidence(generated, existing)
        if removed and sequence_matches(filtered, existing):
            label = "extra_branch_evidence_aggregate"
        elif sequence_matches(state_sequence(generated), state_sequence(existing)):
            if sequence_matches(aggregate_sequence(generated), aggregate_sequence(existing)):
                label = "ordering_or_case_normalization_gap"
            else:
                label = "same_state_changes_aggregate_diff"
        else:
            label = "state_change_or_branch_diff"

    first_diff = None
    for index, (left, right) in enumerate(zip(generated, existing), start=1):
        if not calls_match(left, right):
            first_diff = {
                "index": index,
                "generated": left,
                "existing": right,
            }
            break
    if first_diff is None and len(generated) != len(existing):
        first_diff = {
            "index": min(len(generated), len(existing)) + 1,
            "generated_len": len(generated),
            "existing_len": len(existing),
        }

    return {
        "scenario": record.get("scenario"),
        "task_id": record.get("task_id"),
        "label": label,
        "error": record.get("error"),
        "generated_len": len(generated),
        "existing_len": len(existing),
        "executed_steps": len(record.get("executed_steps") or []),
        "value": record.get("value") or [],
        "secondary_value": record.get("secondary_value") or [],
        "first_diff": first_diff,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify instruction-driven GT run mismatches.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    by_scenario: dict[str, list[dict[str, Any]]] = {}
    flat: list[dict[str, Any]] = []
    for path in sorted(args.run_dir.glob("*.jsonl")):
        scenario = path.stem
        records = list(load_latest(path).values())
        classifications = [classify_record(record) for record in records]
        by_scenario[scenario] = classifications
        flat.extend(classifications)

    counts: dict[str, dict[str, int]] = {}
    for scenario, items in by_scenario.items():
        counts[scenario] = dict(Counter(item["label"] for item in items))

    task_ids_by_label: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for item in flat:
        task_ids_by_label[str(item["scenario"])][item["label"]].append(int(item["task_id"]))

    payload = {
        "run_dir": str(args.run_dir),
        "counts": counts,
        "task_ids_by_label": {
            scenario: dict(labels) for scenario, labels in task_ids_by_label.items()
        },
        "records": by_scenario,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for scenario in sorted(by_scenario):
        print(f"{scenario}: {counts.get(scenario, {})}")
        for label, task_ids in sorted(task_ids_by_label.get(scenario, {}).items()):
            if label == "exact_match":
                continue
            print(f"  {label}: {task_ids[:30]}")


if __name__ == "__main__":
    main()
