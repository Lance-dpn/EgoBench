#!/usr/bin/env python3
"""Sample normalized observer GT cases, call the observer, and score outputs."""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
DEFAULT_GT_PATH = (
    CURRENT_FILE.parent
    / "eval"
    / "observer_problem_set_order1"
    / "observer_grounding_order1_bootstrap.json"
)
DEFAULT_GT_DIR = DEFAULT_GT_PATH.parent
DEFAULT_OUTPUT_DIR = (
    CURRENT_FILE.parent
    / "cache"
    / "visual_stage_eval"
    / "observer_problem_set_order1"
    / "eval_runs"
)

SAMPLE_PLAN = {
    "menu_category_by_visual_style": 2,
    "menu_category_by_absolute_region": 2,
    "menu_category_by_relative_anchor": 2,
    "pointed_dish_by_ordinal": 2,
    "category_containing_pointed_dish": 1,
    "dish_by_position_in_menu_region": 1,
}

PROBLEM_TYPE_ORDER = list(SAMPLE_PLAN)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def scenario_from_key(scenario_key: str) -> str:
    return re.sub(r"\d+$", "", scenario_key)


def gt_path_for_scenario(scenario_key: str) -> Path:
    return (
        CURRENT_FILE.parent
        / "eval"
        / f"observer_problem_set_{scenario_key}"
        / f"observer_grounding_{scenario_key}_bootstrap.json"
    )


def output_dir_for_scenario(scenario_key: str) -> Path:
    return (
        CURRENT_FILE.parent
        / "cache"
        / "visual_stage_eval"
        / f"observer_problem_set_{scenario_key}"
        / "eval_runs"
    )


def visual_problem_payload(case: dict[str, Any]) -> dict[str, Any]:
    observer_input = dict(case.get("observer_input") or {})
    for key in ("schema_version", "problem_id"):
        observer_input.pop(key, None)
    return observer_input


def visual_problem_key(case: dict[str, Any]) -> str:
    return json.dumps(visual_problem_payload(case), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def visual_problem_label(case: dict[str, Any]) -> str:
    observer_input = case.get("observer_input") or {}
    slots = observer_input.get("slots") or {}
    video_path = observer_input.get("video_path") or case.get("video_path")
    menu_label = observer_input.get("menu_label") or case.get("menu_label")
    if observer_input.get("task_type") == "pointed_dish_by_ordinal":
        referent = f"{slots.get('ordinal')} pointed dish"
    else:
        referent = str(slots.get("anchor_text") or slots.get("anchor_id") or observer_input.get("task_type") or "")
    scope = " / ".join(str(item) for item in (video_path, menu_label) if item)
    return f"{scope}: {referent}" if scope else referent


def canonical_match(predicted_values: list[str], detail_gt: dict[str, Any]) -> bool:
    expected = [detail_gt["canonical_value"], *(detail_gt.get("acceptable_aliases") or [])]
    expected_norm = [normalize_text(v) for v in expected if v]
    for predicted in predicted_values:
        pred_norm = normalize_text(predicted)
        if not pred_norm:
            continue
        if any(exp == pred_norm or exp in pred_norm or pred_norm in exp for exp in expected_norm):
            return True
    return False


EVENT_COVERAGE_PASS_THRESHOLD = 0.8


def normalized_range(range_value: Any) -> list[float] | None:
    if isinstance(range_value, dict) and {"start", "end"} <= set(range_value):
        start = range_value.get("start")
        end = range_value.get("end")
        if start is None and end is None:
            return None
        if start is None:
            start = 0.0
        if end is None:
            end = start
        return [float(start), float(end)]
    if not isinstance(range_value, list) or len(range_value) != 2:
        return None
    return [float(range_value[0]), float(range_value[1])]


def midpoint(range_value: list[float]) -> float:
    return (min(range_value) + max(range_value)) / 2.0


def in_range(value: float | None, range_value: Any) -> bool | None:
    normalized = normalized_range(range_value)
    if value is None or normalized is None:
        return None
    start, end = min(normalized), max(normalized)
    return start <= float(value) <= end


def event_gt_coverage_ratio(range_value: Any, event_gt: dict[str, Any]) -> float | None:
    pred = normalized_range(range_value)
    gt = normalized_range(event_gt.get("primary_content_range"))
    if pred is None or gt is None:
        return None
    pred_start, pred_end = min(pred), max(pred)
    gt_start, gt_end = min(gt), max(gt)
    gt_length = max(gt_end - gt_start, 0.0)
    if gt_length <= 0:
        return None
    overlap = max(0.0, min(pred_end, gt_end) - max(pred_start, gt_start))
    return round(overlap / gt_length, 4)


def useful_observation(observation: dict[str, Any]) -> dict[str, Any]:
    useful = observation.get("observation", observation)
    return useful if isinstance(useful, dict) else {}


def event_coverage_score(observation: dict[str, Any], event_gt: dict[str, Any]) -> dict[str, Any] | None:
    if normalized_range(event_gt.get("primary_content_range")) is None:
        return None
    useful = useful_observation(observation)
    selected = useful.get("selected_event") or {}
    candidates = useful.get("candidates") or []
    ranges = []
    if isinstance(selected, dict):
        ranges.append(
            selected.get("event_time_range") or selected.get("time_range") or selected.get("start_end_seconds")
        )
    for candidate in candidates:
        if isinstance(candidate, dict):
            ranges.append(
                candidate.get("event_time_range") or candidate.get("time_range") or candidate.get("start_end_seconds")
            )
    best: dict[str, Any] | None = None
    for range_value in ranges:
        ratio = event_gt_coverage_ratio(range_value, event_gt)
        if ratio is None:
            continue
        normalized_pred = normalized_range(range_value)
        score = {
            "coverage_ratio": ratio,
            "predicted_range": normalized_pred,
            "gt_primary_range": normalized_range(event_gt.get("primary_content_range")),
            "pass_threshold": EVENT_COVERAGE_PASS_THRESHOLD,
            "pass": ratio >= EVENT_COVERAGE_PASS_THRESHOLD,
        }
        if best is None or score["coverage_ratio"] > best["coverage_ratio"]:
            best = score
    return best or {
        "coverage_ratio": 0.0,
        "predicted_range": None,
        "gt_primary_range": normalized_range(event_gt.get("primary_content_range")),
        "pass_threshold": EVENT_COVERAGE_PASS_THRESHOLD,
        "pass": False,
    }


def trace_event_observation(observation: dict[str, Any]) -> dict[str, Any] | None:
    trace_path = observation.get("trace_path")
    if not trace_path:
        return None
    path = Path(trace_path)
    if not path.exists():
        return None
    trace = load_json(path)
    for task in (trace.get("tasks") or {}).values():
        observations = task.get("observations") or []
        if not observations:
            continue
        clean_plan = (
            observations[-1]
            .get("stages", {})
            .get("event_localizer", {})
            .get("clean_plan")
        )
        if isinstance(clean_plan, dict):
            return {
                "selected_event": clean_plan.get("selected_event"),
                "candidates": clean_plan.get("candidates") or [],
            }
    return None


def event_observation_for_scoring(observation: dict[str, Any]) -> dict[str, Any] | None:
    useful = useful_observation(observation)
    if isinstance(useful.get("selected_event"), dict):
        return {
            "selected_event": useful.get("selected_event"),
            "candidates": useful.get("candidates") or [],
        }
    return trace_event_observation(observation)


def scored_event_coverage(observation: dict[str, Any], event_gt: dict[str, Any]) -> dict[str, Any] | None:
    direct = event_coverage_score(observation, event_gt)
    if direct is not None and direct.get("coverage_ratio", 0.0) > 0:
        return direct
    trace_observation = trace_event_observation(observation)
    if trace_observation is None:
        return direct
    trace_score = event_coverage_score(trace_observation, event_gt)
    if trace_score is None:
        return direct
    if direct is None or trace_score.get("coverage_ratio", 0.0) >= direct.get("coverage_ratio", 0.0):
        return trace_score
    return direct


def first_keyframe_time(selected_event: dict[str, Any] | None) -> float | None:
    if not isinstance(selected_event, dict):
        return None
    keyframes = selected_event.get("keyframes") or []
    if not isinstance(keyframes, list) or not keyframes:
        return None
    first = keyframes[0]
    if not isinstance(first, dict):
        return None
    timestamp = first.get("timestamp") if "timestamp" in first else first.get("time")
    if timestamp is None:
        return None
    try:
        return float(timestamp)
    except (TypeError, ValueError):
        return None


def event_keyframe_score(observation: dict[str, Any], event_gt: dict[str, Any]) -> dict[str, Any] | None:
    primary_range = normalized_range(event_gt.get("primary_content_range"))
    if primary_range is None:
        return None
    event_observation = event_observation_for_scoring(observation)
    selected_event = (event_observation or {}).get("selected_event")
    keyframe_time = first_keyframe_time(selected_event)
    expected_range = normalized_range(event_gt.get("expected_time_range"))
    transition_range = normalized_range(event_gt.get("allowed_transition_range"))
    center = event_gt.get("center_time")
    try:
        center_time = float(center) if center is not None else midpoint(primary_range)
    except (TypeError, ValueError):
        center_time = midpoint(primary_range)
    primary_length = max(max(primary_range) - min(primary_range), 0.0)
    distance = None if keyframe_time is None else round(abs(keyframe_time - center_time), 4)
    normalized_distance = (
        None
        if distance is None or primary_length <= 0
        else round(distance / primary_length, 4)
    )
    in_primary = in_range(keyframe_time, primary_range)
    return {
        "first_keyframe_time": keyframe_time,
        "gt_primary_range": primary_range,
        "gt_expected_range": expected_range,
        "gt_allowed_transition_range": transition_range,
        "in_primary": in_primary,
        "in_expected": in_range(keyframe_time, expected_range),
        "in_allowed_transition": in_range(keyframe_time, transition_range),
        "distance_to_gt_center": distance,
        "normalized_distance_to_gt_center": normalized_distance,
        "pass": bool(in_primary),
    }


def detail_sample_coverage_score(observation: dict[str, Any], event_gt: dict[str, Any]) -> dict[str, Any] | None:
    primary_range = normalized_range(event_gt.get("primary_content_range"))
    if primary_range is None:
        return None
    useful = useful_observation(observation)
    detail_items = useful.get("detail_evidence") or []
    if not isinstance(detail_items, list) or not detail_items:
        return None
    timestamps = detail_items[0].get("timestamps") if isinstance(detail_items[0], dict) else None
    if not isinstance(timestamps, list) or not timestamps:
        return None
    try:
        numeric_timestamps = [float(item) for item in timestamps]
    except (TypeError, ValueError):
        return None
    sample_range = [min(numeric_timestamps), max(numeric_timestamps)]
    return {
        "sample_time_range": sample_range,
        "gt_primary_range": primary_range,
        "coverage_ratio": event_gt_coverage_ratio(sample_range, event_gt),
    }


def scored_event_match(observation: dict[str, Any], event_gt: dict[str, Any]) -> bool | None:
    score = scored_event_coverage(observation, event_gt)
    if score is None:
        return None
    return bool(score.get("pass"))


def extract_predicted_values(observation: dict[str, Any]) -> list[str]:
    useful = useful_observation(observation)
    values: list[str] = []
    for item in useful.get("visual_key_values") or []:
        if isinstance(item, dict):
            value = item.get("value") or item.get("name") or item.get("text")
            if value:
                values.append(str(value))
    for item in useful.get("resolved_referents") or useful.get("referents") or []:
        if isinstance(item, dict):
            value = item.get("value") or item.get("name") or item.get("text")
            if value:
                values.append(str(value))
    for key in ("answer", "target_value", "value", "name", "text", "raw"):
        value = useful.get(key)
        if isinstance(value, str):
            values.append(value)
    return list(dict.fromkeys(values))


def build_business_message(case: dict[str, Any], scenario_key: str | None = None) -> tuple[str, str]:
    observer_input = case["observer_input"]
    slots = observer_input.get("slots") or {}
    menu_label = observer_input.get("menu_label")
    task_type = observer_input.get("task_type") or case.get("problem_type") or ""
    target_kind = observer_input.get("target_kind") or ""
    video_path = observer_input.get("video_path") or case.get("video_path")
    anchor_text = (
        slots.get("anchor_text")
        or slots.get("anchor_id")
        or slots.get("visual_problem_label")
        or case.get("visual_problem_label")
        or ""
    )
    ordinal = slots.get("ordinal")

    scenario_label = scenario_from_key(scenario_key or case.get("scenario_key") or "order")
    if menu_label:
        scope_text = f"{menu_label.replace('_', ' ').title()} in the saved {scenario_label} video"
    else:
        scope_text = f"the saved {scenario_label} video"
    prefix = f"I am using {scope_text}. Please resolve only the visual reference from the video."
    if task_type == "pointed_dish_by_ordinal":
        message = f"{prefix} Which dish is the {ordinal} pointed dish?"
        referent_hint = f"{ordinal} pointed dish"
    elif task_type == "category_containing_pointed_dish":
        pointed_target = anchor_text.replace("menu category containing ", "")
        pointed_target = re.sub(r"^the\s+", "", pointed_target, flags=re.IGNORECASE)
        message = f"{prefix} Which menu category contains the {pointed_target}?"
        referent_hint = anchor_text
    elif task_type == "dish_by_position_in_menu_region":
        position = slots.get("position", "last")
        message = f"{prefix} What is the {position} dish inside the {anchor_text}?"
        referent_hint = f"{position} dish in {anchor_text}"
    elif target_kind == "menu_catalog_or_category":
        message = f"{prefix} Identify the menu category title for: {anchor_text}."
        referent_hint = anchor_text
    elif ordinal and slots.get("action"):
        message = f"{prefix} Identify the visible {target_kind or 'target'} for: {ordinal} {slots.get('action')} event."
        referent_hint = f"{ordinal} {slots.get('action')} {target_kind or 'target'}"
    else:
        message = f"{prefix} Identify the visible {target_kind or 'target'} for: {anchor_text}."
        referent_hint = anchor_text

    return (
        f"{message}\nVisual referent to resolve: {referent_hint}\nReturn the visible name/title only.",
        referent_hint,
    )


def build_sample_plan(
    by_type: dict[str, list[dict[str, Any]]],
    sample_size: int | None | str,
) -> dict[str, int]:
    if sample_size == "all":
        return {problem_type: len(cases) for problem_type, cases in sorted(by_type.items())}
    if sample_size is None:
        default_plan = {key: min(count, len(by_type[key])) for key, count in SAMPLE_PLAN.items() if key in by_type}
        if default_plan:
            return default_plan
        return {problem_type: min(2, len(cases)) for problem_type, cases in sorted(by_type.items())}

    available = {problem_type: len(cases) for problem_type, cases in by_type.items() if cases}
    if sample_size < len(available):
        raise ValueError(
            f"sample_size={sample_size} is smaller than available problem types={len(available)}"
        )
    total_available = sum(available.values())
    if sample_size > total_available:
        raise ValueError(f"sample_size={sample_size} exceeds available cases={total_available}")

    plan = {problem_type: 1 for problem_type in available}
    remaining = sample_size - len(plan)
    if remaining <= 0:
        return {key: plan[key] for key in PROBLEM_TYPE_ORDER if key in plan}

    capacities = {key: available[key] - plan[key] for key in plan}
    capacity_total = sum(capacities.values())
    raw_allocations: list[tuple[float, str, int]] = []
    allocated = 0
    for problem_type, capacity in capacities.items():
        exact = remaining * capacity / capacity_total if capacity_total else 0
        base = min(capacity, int(exact))
        plan[problem_type] += base
        allocated += base
        raw_allocations.append((exact - base, problem_type, capacity - base))

    for _, problem_type, capacity_left in sorted(raw_allocations, reverse=True):
        if allocated >= remaining:
            break
        if capacity_left <= 0:
            continue
        plan[problem_type] += 1
        allocated += 1

    ordered_keys = [key for key in PROBLEM_TYPE_ORDER if key in plan]
    ordered_keys.extend(sorted(key for key in plan if key not in set(ordered_keys)))
    return {key: plan[key] for key in ordered_keys}


def sample_cases(
    eval_cases: list[dict[str, Any]],
    seed: int,
    sample_size: int | None | str = None,
    include_high_review: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rng = random.Random(seed)
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in eval_cases:
        if not include_high_review and case.get("human_review_priority") == "high":
            continue
        by_type[case["problem_type"]].append(case)
    sample_plan = build_sample_plan(by_type, sample_size)
    sampled: list[dict[str, Any]] = []
    for problem_type, count in sample_plan.items():
        pool = by_type[problem_type]
        if len(pool) < count:
            raise ValueError(f"Not enough cases for {problem_type}: need {count}, have {len(pool)}")
        sampled.extend(rng.sample(pool, count))
    return sampled, sample_plan


def call_observer(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    current_user_message, referent_hint = build_business_message(case, args.scenario_key)
    video_path = PROJECT_ROOT / "videos" / case["video_path"]
    scenario = scenario_from_key(args.scenario_key)
    payload = {
        "task_id": f"observer_gt_sample_{case['case_id']}",
        "request_key": f"{case['case_id']}_{int(time.time())}",
        "experiment_id": args.experiment_id,
        "scenario": scenario,
        "video_path": str(video_path),
        "image_description": case.get("image_description") or f"You are viewing a saved {scenario} video.",
        "current_user_message": current_user_message,
        "referent_hint": referent_hint,
        "observer_input": case["observer_input"],
    }
    start = time.time()
    response = requests.post(args.observer_url, json=payload, timeout=args.timeout)
    response.raise_for_status()
    data = response.json()
    data["_request_payload"] = payload
    data["_elapsed_seconds_client"] = round(time.time() - start, 3)
    return data


def aggregate_rows(rows: list[dict[str, Any]], group_key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(group_key) or "")].append(row)

    summary_rows = []
    for key, items in groups.items():
        event_items = [row for row in items if row.get("event_coverage_ratio") is not None]
        keyframe_items = [row for row in items if row.get("event_keyframe_match") is not None]
        sample_items = [row for row in items if row.get("detail_sample_gt_coverage_ratio") is not None]
        summary_rows.append(
            {
                group_key: key,
                "visual_problem_label": items[0].get("visual_problem_label"),
                "problem_type": items[0].get("problem_type"),
                "case_count": len(items),
                "case_ids": [row["case_id"] for row in items],
                "detail_correct": sum(1 for row in items if row.get("detail_match")),
                "event_pass": sum(1 for row in event_items if row.get("event_match") is True),
                "event_evaluable": len(event_items),
                "event_mean_coverage": (
                    round(sum(float(row["event_coverage_ratio"]) for row in event_items) / len(event_items), 4)
                    if event_items
                    else None
                ),
                "event_keyframe_pass": sum(1 for row in keyframe_items if row.get("event_keyframe_match") is True),
                "event_keyframe_evaluable": len(keyframe_items),
                "detail_sample_mean_gt_coverage": (
                    round(
                        sum(float(row["detail_sample_gt_coverage_ratio"]) for row in sample_items) / len(sample_items),
                        4,
                    )
                    if sample_items
                    else None
                ),
            }
        )
    return sorted(summary_rows, key=lambda row: (str(row.get("problem_type")), str(row.get("visual_problem_label"))))


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Observer Grounding Sample Evaluation",
        "",
        f"- Experiment: `{result['experiment_id']}`",
        f"- Observer URL: `{result['observer_url']}`",
        f"- Seed: `{result['seed']}`",
        f"- Cases: {len(result['cases'])}",
        f"- Detail exact/alias match: {result['summary']['detail_correct']}/{result['summary']['total']}",
        f"- Event mean GT coverage: {result['summary']['event_mean_coverage']}",
        f"- Event coverage pass@{EVENT_COVERAGE_PASS_THRESHOLD}: {result['summary']['event_pass']}/{result['summary']['event_evaluable']}",
        f"- Event keyframe in GT primary range: {result['summary']['event_keyframe_pass']}/{result['summary']['event_keyframe_evaluable']}",
        f"- Event keyframe mean normalized center distance: {result['summary']['event_keyframe_mean_normalized_distance']}",
        f"- Detail sample mean GT coverage: {result['summary']['detail_sample_mean_gt_coverage']}",
        "",
        "## Visual Problem Summary",
        "",
    ]
    for row in result.get("summary_by_visual_problem") or []:
        lines.extend(
            [
                f"- `{row['problem_type']}` {row['visual_problem_label']}: "
                f"detail {row['detail_correct']}/{row['case_count']}, "
                f"event {row['event_pass']}/{row['event_evaluable']}, "
                f"keyframe {row['event_keyframe_pass']}/{row['event_keyframe_evaluable']}, "
                f"sample coverage {row['detail_sample_mean_gt_coverage']}; "
                f"cases={row['case_ids']}",
            ]
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
        ]
    )
    for row in result["cases"]:
        lines.extend(
            [
                f"### {row['case_id']} `{row['problem_type']}`",
                f"- Video/Menu: `{row['video_path']}` / `{row['menu_label']}`",
                f"- Visual problem: {row['visual_problem_label']}",
                f"- Request: {row['request_message']}",
                f"- Expected: **{row['expected_value']}**",
                f"- Predicted values: {row['predicted_values']}",
                f"- Detail match: `{row['detail_match']}`",
                f"- Event coverage: `{row.get('event_coverage_ratio')}`",
                f"- Event pass@{EVENT_COVERAGE_PASS_THRESHOLD}: `{row['event_match']}`",
                f"- Event keyframe pass: `{row.get('event_keyframe_match')}`",
                f"- Event keyframe score: `{row.get('event_keyframe_score')}`",
                f"- Detail sample GT coverage: `{row.get('detail_sample_gt_coverage_ratio')}`",
                f"- Trace: `{row.get('trace_path')}`",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario_key", default="order1")
    parser.add_argument("--gt_path", type=Path)
    parser.add_argument("--observer_url", default="http://127.0.0.1:18082/observe")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--sample_size", default=None, help="Number of cases to sample, or `all`.")
    parser.add_argument("--all", action="store_true", help="Evaluate all eligible cases.")
    parser.add_argument("--include_high_review", action="store_true")
    parser.add_argument("--experiment_id", default="observer-grounding-order1-sample")
    parser.add_argument("--output_dir", type=Path)
    args = parser.parse_args()
    if args.gt_path is None:
        args.gt_path = gt_path_for_scenario(args.scenario_key)
    if args.output_dir is None:
        args.output_dir = output_dir_for_scenario(args.scenario_key)
    if args.all:
        sample_size: int | str | None = "all"
    elif args.sample_size is None:
        sample_size = None
    elif str(args.sample_size).lower() == "all":
        sample_size = "all"
    else:
        sample_size = int(args.sample_size)

    gt = load_json(args.gt_path)
    detail_by_id = {item["detail_gt_id"]: item for item in gt["detail_ground_truths"]}
    event_by_id = {item["event_gt_id"]: item for item in gt["event_ground_truths"]}
    sampled, sample_plan = sample_cases(gt["eval_cases"], args.seed, sample_size, args.include_high_review)

    rows = []
    for index, case in enumerate(sampled, start=1):
        print(f"[{index}/{len(sampled)}] {case['case_id']} {case['problem_type']}", flush=True)
        request_message, _ = build_business_message(case, args.scenario_key)
        observation = call_observer(case, args)
        detail_gt = detail_by_id[case["detail_gt_id"]]
        event_gt = event_by_id[case["event_gt_id"]]
        predicted_values = extract_predicted_values(observation)
        event_score = scored_event_coverage(observation, event_gt)
        keyframe_score = event_keyframe_score(observation, event_gt)
        sample_score = detail_sample_coverage_score(observation, event_gt)
        rows.append(
            {
                "case_id": case["case_id"],
                "problem_type": case["problem_type"],
                "visual_problem_key": case.get("visual_problem_key") or visual_problem_key(case),
                "visual_problem_label": case.get("visual_problem_label") or visual_problem_label(case),
                "video_path": case["video_path"],
                "menu_label": case["menu_label"],
                "request_message": request_message,
                "event_gt_id": case["event_gt_id"],
                "detail_gt_id": case["detail_gt_id"],
                "expected_value": detail_gt["canonical_value"],
                "acceptable_aliases": detail_gt.get("acceptable_aliases", []),
                "predicted_values": predicted_values,
                "detail_match": canonical_match(predicted_values, detail_gt),
                "event_score": event_score,
                "event_coverage_ratio": None if event_score is None else event_score.get("coverage_ratio"),
                "event_match": None if event_score is None else bool(event_score.get("pass")),
                "event_keyframe_score": keyframe_score,
                "event_keyframe_match": None if keyframe_score is None else bool(keyframe_score.get("pass")),
                "detail_sample_gt_coverage": sample_score,
                "detail_sample_gt_coverage_ratio": None if sample_score is None else sample_score.get("coverage_ratio"),
                "trace_path": observation.get("trace_path"),
                "elapsed_seconds": observation.get("_elapsed_seconds_client"),
                "raw_observation": observation,
            }
        )

    event_rows = [row for row in rows if row["event_coverage_ratio"] is not None]
    event_mean_coverage = (
        round(sum(float(row["event_coverage_ratio"]) for row in event_rows) / len(event_rows), 4)
        if event_rows
        else None
    )
    keyframe_rows = [row for row in rows if row["event_keyframe_score"] is not None]
    keyframe_distances = [
        row["event_keyframe_score"].get("normalized_distance_to_gt_center")
        for row in keyframe_rows
        if row["event_keyframe_score"].get("normalized_distance_to_gt_center") is not None
    ]
    sample_rows = [row for row in rows if row["detail_sample_gt_coverage_ratio"] is not None]
    summary = {
        "total": len(rows),
        "detail_correct": sum(1 for row in rows if row["detail_match"]),
        "event_evaluable": len(event_rows),
        "event_mean_coverage": event_mean_coverage,
        "event_pass_threshold": EVENT_COVERAGE_PASS_THRESHOLD,
        "event_pass": sum(1 for row in event_rows if row["event_match"] is True),
        "event_keyframe_evaluable": len(keyframe_rows),
        "event_keyframe_pass": sum(1 for row in keyframe_rows if row["event_keyframe_match"] is True),
        "event_keyframe_pass_rate": (
            round(sum(1 for row in keyframe_rows if row["event_keyframe_match"] is True) / len(keyframe_rows), 4)
            if keyframe_rows
            else None
        ),
        "event_keyframe_mean_normalized_distance": (
            round(sum(float(item) for item in keyframe_distances) / len(keyframe_distances), 4)
            if keyframe_distances
            else None
        ),
        "detail_sample_mean_gt_coverage": (
            round(sum(float(row["detail_sample_gt_coverage_ratio"]) for row in sample_rows) / len(sample_rows), 4)
            if sample_rows
            else None
        ),
    }
    result = {
        "schema_version": "observer_grounding_sample_eval_v4",
        "experiment_id": args.experiment_id,
        "observer_url": args.observer_url,
        "seed": args.seed,
        "sample_plan": sample_plan,
        "summary": summary,
        "summary_by_problem_type": aggregate_rows(rows, "problem_type"),
        "summary_by_visual_problem": aggregate_rows(rows, "visual_problem_key"),
        "cases": rows,
    }
    output_json = args.output_dir / f"{args.experiment_id}.json"
    output_md = args.output_dir / f"{args.experiment_id}.md"
    write_json(output_json, result)
    output_md.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote {output_json}")
    print(f"Wrote {output_md}")


if __name__ == "__main__":
    main()
