#!/usr/bin/env python3
"""
Evaluate whether observer outputs contain EgoBench visual anchor labels.

This script treats scenarios/final/* key/value fields as evaluation labels only.
They are never sent to the observer. The main metric is recall-oriented:
every expected value should be contained somewhere in the observer's predicted
values for the expected key. Extra predicted values are allowed because an
actual first user request may be broad.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
DEFAULT_OUTPUT_DIR = CURRENT_FILE.parent / "cache" / "visual_anchor_eval"


def normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fuzzy_match(expected: str, predicted: str, threshold: float) -> bool:
    expected_norm = normalize_text(expected)
    predicted_norm = normalize_text(predicted)
    if not expected_norm or not predicted_norm:
        return False
    if expected_norm == predicted_norm:
        return True
    if expected_norm in predicted_norm or predicted_norm in expected_norm:
        return True
    return difflib.SequenceMatcher(None, expected_norm, predicted_norm).ratio() >= threshold


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def resolve_video_path(video_name: str) -> str:
    path = Path(video_name)
    if path.exists():
        return str(path.resolve())
    candidate = PROJECT_ROOT / "videos" / os.path.basename(video_name)
    if candidate.exists():
        return str(candidate.resolve())
    return video_name


VISUAL_CUE_PATTERN = re.compile(
    r"point|pointed|pointing|look|looked|see|visible|video|pick|picked|hold|holding|"
    r"hand|left|right|top|bottom|middle|row|column|shelf|menu|category|section|"
    r"leaflet|fold|panel|box|card|tray|pot|cutting board|table|served|sprinkling|"
    r"ingredient|dish|bottle|wine|cheese|cookie|recipe|region",
    re.IGNORECASE,
)

NON_VISUAL_CUE_PATTERN = re.compile(
    r"price|tax|discount|nutrition|calorie|protein|sodium|sugar|fat|fiber|"
    r"carbohydrate|allergen|country|origin|cart|order|shopping list|calculate|"
    r"compute|total|add|remove|highest|lowest|cheapest|expensive|if|otherwise",
    re.IGNORECASE,
)


def visual_brief_from_instruction(instruction: str) -> str:
    instruction = re.split(
        r"\bFirst,?\s+ask\b|\bThen,?\s+ask\b|\bNext,?\s+ask\b|\bFinally,?\s+ask\b|"
        r"\bSubsequently,?\s+ask\b|\bAfter\b",
        instruction,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    parts = re.split(r"(?<=[.!?])\s+|\n+", instruction.strip())
    selected = []
    for part in parts:
        text = part.strip()
        if not text:
            continue
        if VISUAL_CUE_PATTERN.search(text):
            selected.append(text)
    if not selected:
        selected = parts[:2]

    # Keep visual language but avoid flooding AURA with business constraints.
    cleaned = []
    for text in selected[:6]:
        clauses = re.split(r";|, then |\. Then |\. Next |\. Finally ", text)
        visual_clauses = [
            clause.strip()
            for clause in clauses
            if VISUAL_CUE_PATTERN.search(clause)
            and not (
                NON_VISUAL_CUE_PATTERN.search(clause)
                and not re.search(r"point|look|see|visible|hand|left|right|top|bottom|middle|row|shelf|menu|section|tray|pot|cutting board", clause, re.I)
            )
        ]
        cleaned.extend(visual_clauses or [text])

    brief = " ".join(cleaned)
    return re.sub(r"\s+", " ", brief).strip()


def build_observer_message(task: dict[str, Any], prompt_mode: str) -> str:
    instruction = task.get("Instruction", "")
    image_description = task.get("image_description", "")
    if prompt_mode == "instruction":
        visual_brief = visual_brief_from_instruction(instruction)
        return (
            "Identify visual anchors for this request. Focus only on what the "
            "user saw, pointed at, held, selected, or visually described. Ignore "
            "business conditions, database attributes, and final actions.\n\n"
            f"Visual request:\n{visual_brief}"
        )
    if prompt_mode == "first_request":
        first_sentence = re.split(r"(?<=[.!?])\s+", instruction.strip(), maxsplit=1)[0]
        return first_sentence or instruction
    if prompt_mode == "scene_only":
        return (
            "Identify the visible anchors in this scene that a user may refer to "
            "by pointing order, hand, location, label, menu region, object state, "
            "or appearance. Do not use database facts.\n\n"
            f"Scene:\n{image_description}"
        )
    raise ValueError(f"unknown prompt_mode: {prompt_mode}")


def call_observer(task: dict[str, Any], args: argparse.Namespace, scenario_key: str, task_id: int) -> dict[str, Any]:
    payload = {
        "task_id": f"{scenario_key}_task{task_id}_anchor_eval",
        "scenario": args.scenario,
        "experiment_id": args.experiment_id,
        "experiment_timestamp": args.run_timestamp,
        "video_path": resolve_video_path(task.get("image_path", "")),
        "image_description": task.get("image_description", ""),
        "current_user_message": build_observer_message(task, args.prompt_mode),
    }
    response = requests.post(args.observer_url, json=payload, timeout=args.timeout)
    response.raise_for_status()
    return response.json()


def iter_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        if value.strip():
            strings.append(value)
    elif isinstance(value, list):
        for item in value:
            strings.extend(iter_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            strings.extend(iter_strings(item))
    return strings


def collect_predictions(observation_response: dict[str, Any], expected_key: str) -> dict[str, Any]:
    observation = observation_response.get("observation", observation_response)
    predicted_for_key: list[str] = []
    predicted_all: list[str] = []

    def add(value: Any, target: list[str]) -> None:
        if value in (None, ""):
            return
        text = str(value)
        if text not in target:
            target.append(text)

    if isinstance(observation, dict):
        for item in observation.get("visual_key_values") or []:
            if not isinstance(item, dict):
                continue
            key = normalize_text(item.get("key")).replace(" ", "_")
            value = item.get("value")
            add(value, predicted_all)
            if key == expected_key:
                add(value, predicted_for_key)

        for evidence in observation.get("detail_evidence") or []:
            if not isinstance(evidence, dict):
                continue
            details = evidence.get("details")
            if not isinstance(details, dict):
                continue
            target_identity = details.get("target_identity")
            add(target_identity, predicted_all)
            if expected_key in {"product_name", "dish_name", "ingredient_name", "recipe_name", "set_meal_name"}:
                add(target_identity, predicted_for_key)
            for item in details.get("visual_key_values") or []:
                if not isinstance(item, dict):
                    continue
                key = normalize_text(item.get("key")).replace(" ", "_")
                value = item.get("value")
                add(value, predicted_all)
                if key == expected_key:
                    add(value, predicted_for_key)
            for value in details.get("candidate_items") or []:
                add(value, predicted_all)
                add(value, predicted_for_key)

    if not predicted_for_key:
        predicted_for_key = list(predicted_all)

    return {
        "predicted_for_key": predicted_for_key,
        "predicted_all": predicted_all,
    }


def evaluate_one(
    task: dict[str, Any],
    observation_response: dict[str, Any],
    threshold: float,
) -> dict[str, Any]:
    expected_key = str(task.get("key", ""))
    expected_values = [str(v) for v in task.get("value", [])]
    predictions = collect_predictions(observation_response, expected_key)
    predicted_values = predictions["predicted_for_key"]

    matched = []
    missing = []
    match_details = []
    for expected in expected_values:
        best = None
        best_score = -1.0
        for predicted in predicted_values:
            score = difflib.SequenceMatcher(None, normalize_text(expected), normalize_text(predicted)).ratio()
            if score > best_score:
                best = predicted
                best_score = score
            if fuzzy_match(expected, predicted, threshold):
                best = predicted
                best_score = score
                break
        if best is not None and fuzzy_match(expected, best, threshold):
            matched.append(expected)
            match_details.append({"expected": expected, "predicted": best, "score": round(best_score, 3)})
        else:
            missing.append(expected)
            match_details.append({"expected": expected, "best_predicted": best, "score": round(best_score, 3)})

    contains_all = bool(expected_values) and not missing
    if contains_all:
        status = "PASS_CONTAINS_ALL"
    elif matched:
        status = "PARTIAL_MISSING_SOME"
    else:
        status = "FAIL_MISSING_ALL"

    extra = [
        value
        for value in predicted_values
        if not any(fuzzy_match(expected, value, threshold) for expected in expected_values)
    ]

    return {
        "task_id": task.get("task_id"),
        "expected_key": expected_key,
        "expected_values": expected_values,
        "predicted_values": predicted_values,
        "predicted_all": predictions["predicted_all"],
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "match_details": match_details,
        "anchor_recall": round(len(matched) / len(expected_values), 4) if expected_values else 0.0,
        "contains_all": contains_all,
        "status": status,
    }


def observation_from_result_task(result_task: dict[str, Any]) -> dict[str, Any] | None:
    observation = result_task.get("aura_observation")
    if observation:
        return observation
    observations = result_task.get("aura_observations") or []
    if observations:
        return observations[0].get("observation")
    return None


def load_result_observations(args: argparse.Namespace, scenario_key: str) -> dict[int, dict[str, Any]]:
    if not args.result_json:
        return {}
    result_path = Path(args.result_json)
    if result_path.is_dir():
        result_path = result_path / f"{scenario_key}_easy.json"
    data = load_json(result_path)
    observations = {}
    for item in data:
        task_id = int(item.get("task_id", len(observations) + 1))
        observation = observation_from_result_task(item)
        if observation:
            observations[task_id] = observation
    return observations


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    pass_count = sum(1 for item in results if item["contains_all"])
    partial_count = sum(1 for item in results if item["status"] == "PARTIAL_MISSING_SOME")
    fail_count = sum(1 for item in results if item["status"] == "FAIL_MISSING_ALL")
    total_expected = sum(len(item["expected_values"]) for item in results)
    total_matched = sum(len(item["matched"]) for item in results)
    return {
        "total_tasks": total,
        "contains_all_count": pass_count,
        "partial_count": partial_count,
        "fail_count": fail_count,
        "contains_all_rate": round(pass_count / total, 4) if total else 0.0,
        "value_recall": round(total_matched / total_expected, 4) if total_expected else 0.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate observer visual anchor containment")
    parser.add_argument("--scenario", choices=["retail", "kitchen", "restaurant", "order"], required=True)
    parser.add_argument("--scenario_number", type=int, required=True)
    parser.add_argument("--num_tasks", type=int, default=0, help="0 means all tasks")
    parser.add_argument("--start_task", type=int, default=1)
    parser.add_argument("--observer_url", default="http://127.0.0.1:18082/observe")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--prompt_mode", choices=["instruction", "first_request", "scene_only"], default="instruction")
    parser.add_argument("--result_json", default=None, help="Evaluate existing result JSON/dir instead of calling observer")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached output file when calling observer")
    parser.add_argument("--threshold", type=float, default=0.82)
    parser.add_argument("--output_dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--run_timestamp", default=time.strftime("%Y%m%d%H%M%S", time.localtime()))
    parser.add_argument("--experiment_id", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenario_key = f"{args.scenario}{args.scenario_number}"
    if not args.experiment_id:
        args.experiment_id = f"visual-anchor-eval-{scenario_key}-{args.prompt_mode}"

    scenario_path = PROJECT_ROOT / "scenarios" / "final" / f"{scenario_key}.json"
    tasks = load_json(scenario_path)
    start_index = max(args.start_task - 1, 0)
    tasks = tasks[start_index:]
    if args.num_tasks > 0:
        tasks = tasks[: args.num_tasks]

    output_dir = Path(args.output_dir)
    output_path = output_dir / f"{scenario_key}_{args.prompt_mode}_{args.run_timestamp}.json"
    if args.result_json:
        output_path = output_dir / f"{scenario_key}_from_results_{args.run_timestamp}.json"

    cached = None if args.refresh or args.result_json or not output_path.exists() else load_json(output_path)
    if cached:
        print(f"Using cached evaluation: {output_path}")
        print(json.dumps(cached.get("summary", {}), ensure_ascii=False, indent=2))
        return

    result_observations = load_result_observations(args, scenario_key)
    evaluations = []
    raw_records = []

    for task in tasks:
        task_id = int(task.get("task_id", len(evaluations) + 1))
        print(f"Evaluating {scenario_key} task {task_id}...", flush=True)
        if result_observations:
            observation = result_observations.get(task_id)
            if observation is None:
                raise RuntimeError(f"No observation found in result JSON for task {task_id}")
        else:
            observation = call_observer(task, args, scenario_key, task_id)
        evaluation = evaluate_one(task, observation, args.threshold)
        evaluations.append(evaluation)
        raw_records.append(
            {
                "task_id": task_id,
                "expected_key": evaluation["expected_key"],
                "expected_values": evaluation["expected_values"],
                "evaluation": evaluation,
                "observation": observation,
            }
        )
        print(
            f"  {evaluation['status']} recall={evaluation['anchor_recall']} "
            f"matched={evaluation['matched']} missing={evaluation['missing']}",
            flush=True,
        )

    report = {
        "scenario": scenario_key,
        "prompt_mode": args.prompt_mode,
        "source": "result_json" if args.result_json else "observer",
        "threshold": args.threshold,
        "summary": summarize(evaluations),
        "results": evaluations,
        "records": raw_records,
    }
    write_json(output_path, report)
    print("\nSummary:")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
