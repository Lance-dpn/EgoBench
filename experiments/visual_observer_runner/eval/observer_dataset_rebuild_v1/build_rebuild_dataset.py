#!/usr/bin/env python3
"""Build the independent visual observer eval dataset rebuild.

The new dataset is intentionally stored apart from the older
observer_problem_set_* folders. Existing video-inspected bootstrap files are
used as the GT source, then normalized into visual_query_v1 with inline GT.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
EVAL_DIR = ROOT / "experiments/visual_observer_runner/eval"
OUT_ROOT = EVAL_DIR / "observer_dataset_rebuild_v1"
FINAL_DIR = ROOT / "scenarios/final"

SOURCE_BOOTSTRAPS = {
    "order": EVAL_DIR / "observer_problem_set_order1/observer_grounding_order1_bootstrap.json",
    "retail": EVAL_DIR / "observer_problem_set_retail/observer_grounding_retail_bootstrap.json",
    "restaurant": EVAL_DIR
    / "observer_problem_set_restaurant/_work/observer_grounding_restaurant_bootstrap_before_instruction_level_rebuild.json",
    "kitchen": EVAL_DIR
    / "observer_problem_set_kitchen/_work/observer_grounding_kitchen_bootstrap_before_instruction_level_rebuild.json",
}

SCENARIO_GLOBS = {
    "order": ["order*.json"],
    "retail": ["retail*.json"],
    "restaurant": ["restaurant*.json"],
    "kitchen": ["kitchen*.json"],
}

ORDINAL_WORDS = ("first", "second", "third", "fourth", "fifth", "sixth", "last")
ACTION_WORDS = (
    ("pointing", ("pointing", "pointed", "indicated", "finger")),
    ("holding", ("holding", "held")),
    ("picking", ("picking", "picked", "take", "taking", "grab", "grabbing")),
    ("placing", ("placing", "placed", "put", "putting")),
    ("sprinkling", ("sprinkling", "sprinkle")),
    ("pouring", ("pouring", "pour")),
    ("cutting", ("cutting", "cut")),
    ("cooking", ("cooking", "cook", "stir", "stirring", "frying")),
    ("served", ("served", "serving", "brought", "delivered")),
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def scenario_key_from_case(case: dict[str, Any], scenario: str) -> str:
    for key in ("scenario_key", "video_path", "case_id"):
        value = str(case.get(key) or "")
        match = re.search(rf"({scenario}\d+)", value)
        if match:
            return match.group(1)
    if scenario == "order":
        return "order1"
    return scenario


def video_id_from_case(case: dict[str, Any], scenario_key: str) -> str:
    return str(case.get("video_path") or f"{scenario_key}.mp4")


def load_scenario_tasks(scenario: str) -> tuple[list[dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    files: list[Path] = []
    for pattern in SCENARIO_GLOBS[scenario]:
        files.extend(sorted(FINAL_DIR.glob(pattern)))
    rows: list[dict[str, Any]] = []
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for path in sorted(files):
        scenario_key = path.stem
        for item in load_json(path):
            task_id = int(item["task_id"])
            row = {
                "scenario": scenario,
                "scenario_key": scenario_key,
                "task_id": task_id,
                "image_name": item.get("image_name"),
                "image_path": item.get("image_path"),
                "instruction": item.get("Instruction"),
                "key": item.get("key"),
                "value": item.get("value"),
            }
            rows.append(row)
            index[(scenario_key, task_id)] = row
    return rows, index


def event_map(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["event_gt_id"]: item for item in source.get("event_ground_truths", [])}


def detail_map(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["detail_gt_id"]: item for item in source.get("detail_ground_truths", [])}


def get_slots(case: dict[str, Any]) -> dict[str, Any]:
    observer_input = case.get("observer_input") or {}
    return observer_input.get("slots") or {}


def flatten_text(*values: Any) -> str:
    parts: list[str] = []

    def visit(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for sub in value.values():
                visit(sub)
        elif isinstance(value, list):
            for sub in value:
                visit(sub)
        else:
            parts.append(str(value))

    for value in values:
        visit(value)
    return " ".join(parts)


def parse_ordinal(text: str, slots: dict[str, Any]) -> str | None:
    anchor = slots.get("anchor") if isinstance(slots.get("anchor"), dict) else {}
    for value in (
        slots.get("ordinal"),
        anchor.get("ordinal"),
        slots.get("anchor_id"),
        slots.get("anchor_text"),
        slots.get("visual_referent"),
        text,
    ):
        lowered = str(value or "").lower()
        for word in ORDINAL_WORDS:
            if re.search(rf"\b{word}\b", lowered):
                return word
    return None


def parse_action(text: str, slots: dict[str, Any], referent_type: str) -> str | None:
    anchor = slots.get("anchor") if isinstance(slots.get("anchor"), dict) else {}
    explicit = str(anchor.get("action") or slots.get("action") or "").lower()
    if explicit and explicit != "resolve_visual_referent":
        if explicit == "pointed":
            return "pointing"
        return explicit
    lowered = text.lower()
    for action, words in ACTION_WORDS:
        if any(word in lowered for word in words):
            return action
    if referent_type in {"static_region", "relative_region", "composite_scene"}:
        return None
    return None


def parse_region(text: str, slots: dict[str, Any]) -> dict[str, Any]:
    lowered = text.lower()
    side = None
    vertical = None
    container = None

    if any(word in lowered for word in ("leftmost", "far left", "left side", "left/")):
        side = "left"
    elif any(word in lowered for word in ("rightmost", "far right", "right side", "right/")):
        side = "right"
    elif any(word in lowered for word in ("center", "middle")):
        side = "center"

    if any(word in lowered for word in ("topmost", "top ", "upper", "highest")):
        vertical = "top"
    elif any(word in lowered for word in ("bottom", "lower")):
        vertical = "bottom"
    elif any(word in lowered for word in ("middle", "center")):
        vertical = vertical or "middle"

    container_words = (
        "fold",
        "page",
        "panel",
        "shelf",
        "tray",
        "pot",
        "wok",
        "cutting_board",
        "cutting board",
        "table",
        "menu",
    )
    for word in container_words:
        if word in lowered:
            container = word.replace(" ", "_")
            if container == "menu":
                container = "page"
            break

    constraints = slots.get("visual_constraints") if isinstance(slots.get("visual_constraints"), dict) else {}
    shelf_region = constraints.get("shelf_region")
    shelf_level = constraints.get("shelf_level")
    if shelf_region and not side:
        side = str(shelf_region)
    if shelf_level and not vertical:
        vertical = str(shelf_level)
    return {"side": side, "vertical": vertical, "container": container}


def parse_relation(text: str, slots: dict[str, Any]) -> dict[str, Any]:
    relation = slots.get("relation")
    if isinstance(relation, dict):
        relation_type = relation.get("type")
        anchor = relation.get("anchor") or {}
    elif relation:
        relation_type = str(relation)
        anchor = {}
    else:
        relation_type = None
        anchor = {}

    lowered = text.lower()
    for word in ("above", "below", "left_of", "right_of", "inside", "containing", "next_to"):
        if relation_type:
            break
        probe = word.replace("_", " ")
        if word in lowered or probe in lowered:
            relation_type = word
    if relation_type == "contains_pointed_dish":
        relation_type = "containing"
    return {"type": relation_type, "anchor": anchor}


def parse_appearance(text: str, slots: dict[str, Any]) -> dict[str, Any]:
    lowered = text.lower()
    colors = (
        "red",
        "blue",
        "green",
        "yellow",
        "white",
        "black",
        "brown",
        "dark",
        "purple",
        "orange",
        "pink",
        "gold",
        "silver",
    )
    color = next((word for word in colors if re.search(rf"\b{word}\b", lowered)), None)
    style = None
    if "dark background" in lowered or "dark backgroud" in lowered:
        style = "dark_background"
    elif "white" in lowered and ("box" in lowered or "rounded" in lowered):
        style = "white_rounded_box"
    elif "label" in lowered:
        style = "label"
    elif "hand illustration" in lowered or "small hand" in lowered:
        style = "hand_illustration"

    size = None
    if re.search(r"\bsmall\b", lowered):
        size = "small"
    elif re.search(r"\blarge\b|\bbig\b", lowered):
        size = "large"

    shape = None
    for word in ("bottle", "box", "card", "bag", "jar", "packet", "package"):
        if word in lowered:
            shape = word
            break

    constraints = slots.get("visual_constraints") if isinstance(slots.get("visual_constraints"), dict) else {}
    if constraints.get("label_color") and not color:
        color = constraints["label_color"]
    if constraints.get("label_mark") and not style:
        style = f"label:{constraints['label_mark']}"

    content_hint = None
    for key in ("visual_referent", "anchor_text"):
        value = slots.get(key)
        if isinstance(value, str) and value:
            content_hint = value
            break
    if not content_hint:
        label = text.strip()
        content_hint = label[:180] if label else None

    return {
        "color": color,
        "style": style,
        "size": size,
        "shape": shape,
        "content_hint": content_hint,
    }


def infer_target_kind(case: dict[str, Any], scenario: str, slots: dict[str, Any]) -> str:
    target = slots.get("target") if isinstance(slots.get("target"), dict) else {}
    raw = str(
        target.get("field")
        or target.get("kind")
        or case.get("target_key")
        or case.get("target_kind")
        or (case.get("observer_input") or {}).get("target_kind")
        or ""
    ).lower()
    if "ingredient" in raw:
        return "ingredient_name"
    if "recipe" in raw:
        return "recipe_name"
    if "product" in raw or scenario == "retail":
        return "product_name"
    if "category" in raw or "catalog" in raw or "section" in raw:
        return "category"
    if "text" in raw:
        return "visible_text"
    if "dish" in raw or "menu" in raw or scenario in {"order", "restaurant"}:
        return "dish_name"
    return "visible_region"


def infer_surface(case: dict[str, Any], scenario: str, slots: dict[str, Any], text: str) -> str:
    scene = slots.get("scene_context") if isinstance(slots.get("scene_context"), dict) else {}
    raw_surface = str(scene.get("surface") or "").lower()
    lowered = text.lower()
    if scenario == "retail":
        return "shelf"
    if scenario == "kitchen":
        return "kitchen_workspace"
    if scenario == "order":
        return "menu"
    if "table" in raw_surface or "served" in lowered or "serving" in lowered:
        return "table"
    return "menu"


def infer_selection_unit(scenario: str, surface: str, target_kind: str) -> str:
    if target_kind == "category":
        if surface == "shelf":
            return "shelf_label"
        return "menu_category"
    if target_kind == "product_name":
        return "product_package"
    if target_kind == "ingredient_name":
        return "ingredient"
    if target_kind == "recipe_name":
        return "recipe_scene"
    if surface == "table":
        return "served_dish"
    if surface == "menu":
        return "menu_item"
    return "visible_region"


def infer_referent_type(problem_type: str, text: str, target_kind: str, scenario: str) -> str:
    lowered = f"{problem_type} {text}".lower()
    if "pointing_sequence" in lowered or "pointed_dish_by_ordinal" in lowered:
        return "pointing_sequence"
    if "selected_pointing" in lowered:
        return "selected_pointing_event"
    if "relative" in lowered or any(word in lowered for word in ("above", "below", "next to", "left of", "right of")):
        return "relative_region"
    if scenario == "kitchen" and target_kind == "recipe_name":
        return "composite_scene"
    if any(word in lowered for word in ("sprink", "pour", "cut", "cook", "pick", "hold", "place", "served")):
        return "object_action_state"
    return "static_region"


def menu_label(case: dict[str, Any], slots: dict[str, Any], text: str) -> str | None:
    value = case.get("menu_label") or slots.get("menu_label")
    if value:
        return str(value)
    lowered = text.lower()
    if "menu_1" in lowered or "menu 1" in lowered or "first menu" in lowered:
        return "menu_1"
    if "menu_2" in lowered or "menu 2" in lowered or "second menu" in lowered:
        return "menu_2"
    return None


def build_visual_query(case: dict[str, Any], scenario: str) -> dict[str, Any]:
    slots = get_slots(case)
    observer_input = case.get("observer_input") or {}
    text = flatten_text(
        case.get("problem_type"),
        case.get("visual_problem_label"),
        case.get("dedupe_rationale"),
        observer_input.get("task_type"),
        slots,
    )
    target_kind = infer_target_kind(case, scenario, slots)
    surface = infer_surface(case, scenario, slots, text)
    referent_type = infer_referent_type(str(case.get("problem_type") or observer_input.get("task_type") or ""), text, target_kind, scenario)
    return {
        "schema_version": "visual_query_v1",
        "scenario": scenario,
        "surface": surface,
        "target": {
            "kind": target_kind,
            "selection_unit": infer_selection_unit(scenario, surface, target_kind),
            "cardinality": "single",
        },
        "referent": {
            "type": referent_type,
            "action": parse_action(text, slots, referent_type),
            "ordinal": parse_ordinal(text, slots),
            "region": parse_region(text, slots),
            "relation": parse_relation(text, slots),
            "appearance": parse_appearance(text, slots),
        },
        "scope": {
            "video_id": video_id_from_case(case, scenario_key_from_case(case, scenario)),
            "menu_label": menu_label(case, slots, text) if surface == "menu" else None,
            "time_hint": None,
        },
    }


def inline_event_gt(event: dict[str, Any] | None) -> dict[str, Any] | None:
    if not event:
        return None
    expected = event.get("expected_time_range") or event.get("primary_content_range")
    primary = event.get("primary_content_range") or event.get("expected_time_range")
    key_frame = event.get("key_frame_time") or event.get("center_time")
    if key_frame is None and isinstance(primary, list) and len(primary) == 2:
        key_frame = round((float(primary[0]) + float(primary[1])) / 2, 3)
    region = event.get("expected_region") or event.get("region_hint")
    if isinstance(region, dict):
        region = region.get("description") or canonical_json(region)
    return {
        "event_gt_id": event.get("event_gt_id"),
        "event_type": event.get("event_type"),
        "expected_time_range": expected,
        "primary_content_range": primary,
        "allowed_transition_range": event.get("allowed_transition_range"),
        "evidence_time_range": event.get("evidence_time_range") or primary,
        "key_frame_time": key_frame,
        "key_frame_path": event.get("key_frame_path"),
        "expected_region": {"description": region},
        "confidence": event.get("confidence"),
        "evidence": event.get("evidence"),
    }


def inline_detail_gt(detail: dict[str, Any] | None, visual_query: dict[str, Any]) -> dict[str, Any] | None:
    if not detail:
        return None
    value = detail.get("canonical_value")
    if value is None:
        value = detail.get("expected_answer")
    return {
        "detail_gt_id": detail.get("detail_gt_id"),
        "target_kind": visual_query["target"]["kind"],
        "canonical_value": value,
        "acceptable_aliases": detail.get("acceptable_aliases") or [],
        "negative_neighbors": detail.get("negative_neighbors") or [],
        "confidence": detail.get("confidence"),
        "evidence": detail.get("evidence") or detail.get("notes"),
    }


def source_instruction_snippets(case: dict[str, Any], scenario_key: str, task_index: dict[tuple[str, int], dict[str, Any]]) -> list[str]:
    snippets = case.get("source_instruction_snippets")
    if snippets:
        return list(dict.fromkeys(str(item) for item in snippets))
    out: list[str] = []
    for task_id in case.get("source_task_ids") or []:
        task = task_index.get((scenario_key, int(task_id)))
        if task and task.get("instruction"):
            out.append(str(task["instruction"])[:500])
    return out


def raw_problem_text(case: dict[str, Any]) -> str:
    slots = get_slots(case)
    return (
        str(case.get("visual_problem_label") or "")
        or str(slots.get("visual_referent") or "")
        or str(slots.get("anchor_text") or "")
        or str((case.get("observer_input") or {}).get("task_type") or "")
    )


def make_raw_rows(
    case: dict[str, Any],
    scenario: str,
    scenario_key: str,
    task_index: dict[tuple[str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    task_ids = case.get("source_task_ids") or []
    request_ids = case.get("source_request_ids") or []
    rows: list[dict[str, Any]] = []
    for i, task_id in enumerate(task_ids):
        task = task_index.get((scenario_key, int(task_id)), {})
        request_id = request_ids[i] if i < len(request_ids) else f"{scenario_key}_task{task_id}_{case.get('case_id')}"
        rows.append(
            {
                "raw_problem_id": request_id,
                "scenario": scenario,
                "scenario_key": scenario_key,
                "task_id": int(task_id),
                "video_id": video_id_from_case(case, scenario_key),
                "image_path": task.get("image_path"),
                "instruction": task.get("instruction"),
                "visual_problem_raw_text": raw_problem_text(case),
                "source_clause": case.get("visual_problem_label") or raw_problem_text(case),
                "branch": case.get("branch") or "unknown",
                "extraction_notes": case.get("review_notes") or [],
                "cluster_case_id": case.get("case_id"),
            }
        )
    if not rows:
        rows.append(
            {
                "raw_problem_id": f"{case.get('case_id')}_raw",
                "scenario": scenario,
                "scenario_key": scenario_key,
                "task_id": None,
                "video_id": video_id_from_case(case, scenario_key),
                "image_path": None,
                "instruction": None,
                "visual_problem_raw_text": raw_problem_text(case),
                "source_clause": case.get("visual_problem_label") or raw_problem_text(case),
                "branch": case.get("branch") or "unknown",
                "extraction_notes": case.get("review_notes") or [],
                "cluster_case_id": case.get("case_id"),
            }
        )
    return rows


def cluster_record(case: dict[str, Any], scenario: str, visual_query: dict[str, Any], raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenario_key = scenario_key_from_case(case, scenario)
    return {
        "problem_id": case.get("case_id"),
        "scenario": scenario,
        "scenario_key": scenario_key,
        "video_id": video_id_from_case(case, scenario_key),
        "visual_query_v1": visual_query,
        "cluster_key": canonical_json(visual_query),
        "problem_type": case.get("problem_type") or (case.get("observer_input") or {}).get("task_type"),
        "source_task_ids": case.get("source_task_ids") or [],
        "source_problem_ids": [row["raw_problem_id"] for row in raw_rows],
        "source_instruction_snippets": case.get("source_instruction_snippets") or [],
        "dedupe_rationale": case.get("dedupe_rationale"),
        "review_notes": case.get("review_notes") or [],
    }


def eval_case_record(
    case: dict[str, Any],
    scenario: str,
    visual_query: dict[str, Any],
    event_gt: dict[str, Any] | None,
    detail_gt: dict[str, Any] | None,
    cluster: dict[str, Any],
) -> dict[str, Any]:
    missing = []
    if not event_gt or not event_gt.get("primary_content_range") or event_gt.get("key_frame_time") is None:
        missing.append("event_gt")
    if not detail_gt or detail_gt.get("canonical_value") in (None, ""):
        missing.append("detail_gt")
    status = case.get("gt_status") or "gt_bootstrap_pending_human_review"
    if missing:
        status = "review_required_missing_" + "_and_".join(missing)
    return {
        "case_id": case.get("case_id"),
        "scenario": scenario,
        "scenario_key": cluster["scenario_key"],
        "video_id": cluster["video_id"],
        "problem_type": cluster["problem_type"],
        "branch": case.get("branch") or "unknown",
        "visual_query_v1": visual_query,
        "event_gt": event_gt,
        "detail_gt": detail_gt,
        "evaluation_modes": case.get("evaluation_modes")
        or ["event_only", "detail_with_gt_event", "detail_with_predicted_event", "end_to_end"],
        "source_task_ids": cluster["source_task_ids"],
        "source_request_ids": case.get("source_request_ids") or [],
        "source_problem_ids": cluster["source_problem_ids"],
        "source_instruction_snippets": case.get("source_instruction_snippets") or [],
        "dedupe_rationale": case.get("dedupe_rationale"),
        "review_notes": case.get("review_notes") or [],
        "gt_status": status,
        "gt_confidence": case.get("gt_confidence") or case.get("case_gt_confidence"),
        "source_bootstrap_case": deepcopy(case),
    }


def unique_preserve_order(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = canonical_json(value)
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def merge_eval_cases_by_visual_query(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[canonical_json(case["visual_query_v1"])].append(case)

    merged_cases: list[dict[str, Any]] = []
    old_to_new: dict[str, str] = {}
    for group in grouped.values():
        base = deepcopy(group[0])
        source_cases = [item.pop("source_bootstrap_case", None) for item in group]
        source_cases = [item for item in source_cases if item is not None]
        if len(group) > 1:
            base["merged_source_case_ids"] = [item["case_id"] for item in group]
            base["source_task_ids"] = sorted({task_id for item in group for task_id in item.get("source_task_ids", [])})
            base["source_request_ids"] = unique_preserve_order(
                [request_id for item in group for request_id in item.get("source_request_ids", [])]
            )
            base["source_problem_ids"] = unique_preserve_order(
                [problem_id for item in group for problem_id in item.get("source_problem_ids", [])]
            )
            base["source_instruction_snippets"] = unique_preserve_order(
                [snippet for item in group for snippet in item.get("source_instruction_snippets", [])]
            )
            base["review_notes"] = unique_preserve_order(
                [note for item in group for note in item.get("review_notes", [])]
            )
            base["dedupe_rationale"] = "Merged cases with identical visual_query_v1. " + str(base.get("dedupe_rationale") or "")

            detail_values = {canonical_json(item.get("detail_gt")) for item in group}
            event_values = {canonical_json(item.get("event_gt")) for item in group}
            if len(detail_values) > 1 or len(event_values) > 1:
                base["gt_status"] = "review_required_conflicting_gt_after_visual_query_merge"
                base["review_notes"].append("Identical visual_query_v1 had conflicting source GT; manual review required.")
        else:
            base["merged_source_case_ids"] = [base["case_id"]]

        base["source_bootstrap_cases"] = source_cases
        base.pop("source_bootstrap_case", None)
        for item in group:
            old_to_new[item["case_id"]] = base["case_id"]
        merged_cases.append(base)

    return merged_cases, old_to_new


def cluster_from_eval_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "problem_id": case["case_id"],
        "scenario": case["scenario"],
        "scenario_key": case["scenario_key"],
        "video_id": case["video_id"],
        "visual_query_v1": case["visual_query_v1"],
        "cluster_key": canonical_json(case["visual_query_v1"]),
        "problem_type": case["problem_type"],
        "source_task_ids": case.get("source_task_ids") or [],
        "source_problem_ids": case.get("source_problem_ids") or [],
        "source_instruction_snippets": case.get("source_instruction_snippets") or [],
        "dedupe_rationale": case.get("dedupe_rationale"),
        "review_notes": case.get("review_notes") or [],
        "merged_source_case_ids": case.get("merged_source_case_ids") or [case["case_id"]],
    }


def convert_excluded(
    excluded: list[dict[str, Any]],
    scenario: str,
    task_index: dict[tuple[str, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in excluded:
        scenario_key = scenario_key_from_case(case, scenario)
        visual_query = build_visual_query(case, scenario)
        rows.append(
            {
                "case_id": case.get("case_id"),
                "scenario": scenario,
                "scenario_key": scenario_key,
                "video_id": video_id_from_case(case, scenario_key),
                "visual_query_v1": visual_query,
                "source_task_ids": case.get("source_task_ids") or [],
                "source_instruction_snippets": source_instruction_snippets(case, scenario_key, task_index),
                "exclude_reason": case.get("exclude_reason")
                or case.get("excluded_reason")
                or case.get("review_notes")
                or case.get("notes")
                or "under_specified_or_not_strict_eval_ready",
                "source_bootstrap_case": case,
            }
        )
    return rows


def validate_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for case in cases:
        case_id = case["case_id"]
        if case_id in seen_case_ids:
            issues.append({"case_id": case_id, "issue": "duplicate_case_id"})
        seen_case_ids.add(case_id)
        vq = case.get("visual_query_v1") or {}
        required = ["schema_version", "scenario", "surface", "target", "referent", "scope"]
        missing = [key for key in required if key not in vq]
        if missing:
            issues.append({"case_id": case_id, "issue": "visual_query_missing_keys", "missing": missing})
        if not case.get("event_gt") or not case["event_gt"].get("primary_content_range"):
            issues.append({"case_id": case_id, "issue": "missing_event_primary_content_range"})
        if not case.get("event_gt") or case["event_gt"].get("key_frame_time") is None:
            issues.append({"case_id": case_id, "issue": "missing_event_key_frame_time"})
        if not case.get("detail_gt") or case["detail_gt"].get("canonical_value") in (None, ""):
            issues.append({"case_id": case_id, "issue": "missing_detail_canonical_value"})
    return issues


def build_scenario(scenario: str) -> dict[str, Any]:
    source_path = SOURCE_BOOTSTRAPS[scenario]
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    out_dir = OUT_ROOT / scenario
    source = load_json(source_path)
    tasks, task_index = load_scenario_tasks(scenario)
    events = event_map(source)
    details = detail_map(source)

    raw_rows: list[dict[str, Any]] = []
    query_rows: list[dict[str, Any]] = []
    provisional_eval_cases: list[dict[str, Any]] = []

    for case in source.get("eval_cases", []):
        scenario_key = scenario_key_from_case(case, scenario)
        raw_for_case = make_raw_rows(case, scenario, scenario_key, task_index)
        visual_query = build_visual_query(case, scenario)
        for raw in raw_for_case:
            raw_rows.append(raw)
            query_rows.append(
                {
                    "raw_problem_id": raw["raw_problem_id"],
                    "scenario": scenario,
                    "scenario_key": scenario_key,
                    "task_id": raw["task_id"],
                    "video_id": raw["video_id"],
                    "visual_query_v1": visual_query,
                    "cluster_case_id": case.get("case_id"),
                }
            )
        cluster = cluster_record(case, scenario, visual_query, raw_for_case)
        event_gt = inline_event_gt(events.get(case.get("event_gt_id")))
        detail_gt = inline_detail_gt(details.get(case.get("detail_gt_id")), visual_query)
        eval_case = eval_case_record(case, scenario, visual_query, event_gt, detail_gt, cluster)
        provisional_eval_cases.append(eval_case)

    eval_cases, old_to_new_case_id = merge_eval_cases_by_visual_query(provisional_eval_cases)
    for row in raw_rows:
        row["cluster_case_id"] = old_to_new_case_id.get(row["cluster_case_id"], row["cluster_case_id"])
    for row in query_rows:
        row["cluster_case_id"] = old_to_new_case_id.get(row["cluster_case_id"], row["cluster_case_id"])
    clusters = [cluster_from_eval_case(case) for case in eval_cases]
    review_required = [case for case in eval_cases if str(case["gt_status"]).startswith("review_required")]

    excluded = convert_excluded(source.get("excluded_cases", []), scenario, task_index)
    validation_issues = validate_cases(eval_cases)
    status_counts = Counter(case["gt_status"] for case in eval_cases)
    scenario_counts = Counter(case["scenario_key"] for case in eval_cases)
    target_counts = Counter(case["visual_query_v1"]["target"]["kind"] for case in eval_cases)
    referent_counts = Counter(case["visual_query_v1"]["referent"]["type"] for case in eval_cases)

    metadata = {
        "schema_version": "observer_dataset_rebuild_v1",
        "scenario": scenario,
        "status": "gt_bootstrap_pending_human_review",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_bootstrap": str(source_path.relative_to(ROOT)),
        "process_doc": "experiments/visual_observer_runner/eval/eval-process.md",
        "notes": [
            "Stored in an independent rebuild directory; older observer_problem_set_* folders are not modified.",
            "visual_query_v1 is the clustering and observer-call source of truth.",
            "GT is inline per case. Indexed eval exports should be generated from this file.",
        ],
    }

    write_jsonl(out_dir / "01_scenario_tasks.jsonl", tasks)
    write_jsonl(out_dir / "02_visual_questions_raw.jsonl", raw_rows)
    write_jsonl(out_dir / "03_visual_queries_raw.jsonl", query_rows)
    write_json(
        out_dir / "04_visual_query_clusters.json",
        {
            **metadata,
            "cluster_count": len(clusters),
            "clusters": clusters,
        },
    )
    write_json(
        out_dir / "05_observer_dataset_with_gt.json",
        {
            **metadata,
            "case_count": len(eval_cases),
            "excluded_count": len(excluded),
            "review_required_count": len(review_required),
            "coverage": {
                "scenario_case_counts": dict(sorted(scenario_counts.items())),
                "target_kind_counts": dict(sorted(target_counts.items())),
                "referent_type_counts": dict(sorted(referent_counts.items())),
                "status_counts": dict(sorted(status_counts.items())),
                "source_task_count": len(tasks),
                "raw_visual_problem_count": len(raw_rows),
                "visual_query_count": len(query_rows),
                "cluster_count": len(clusters),
            },
            "cases": eval_cases,
        },
    )
    write_json(out_dir / "excluded_cases.json", {"schema_version": "observer_dataset_rebuild_v1", "scenario": scenario, "excluded_cases": excluded})
    write_json(
        out_dir / "review_required_cases.json",
        {
            "schema_version": "observer_dataset_rebuild_v1",
            "scenario": scenario,
            "validation_issues": validation_issues,
            "review_required_cases": review_required,
        },
    )
    summary = [
        f"# {scenario.title()} Observer Dataset Rebuild v1",
        "",
        f"- Source bootstrap: `{source_path.relative_to(ROOT)}`",
        f"- Scenario tasks: {len(tasks)}",
        f"- Raw visual problems: {len(raw_rows)}",
        f"- Visual query clusters / eval cases: {len(eval_cases)}",
        f"- Excluded cases: {len(excluded)}",
        f"- Review-required cases: {len(review_required)}",
        f"- Validation issues: {len(validation_issues)}",
        "",
        "## Scenario Coverage",
    ]
    for key, value in sorted(scenario_counts.items()):
        summary.append(f"- `{key}`: {value}")
    summary.extend(["", "## Target Kinds"])
    for key, value in sorted(target_counts.items()):
        summary.append(f"- `{key}`: {value}")
    summary.extend(["", "## Referent Types"])
    for key, value in sorted(referent_counts.items()):
        summary.append(f"- `{key}`: {value}")
    summary.extend(["", "## Files"])
    for filename in (
        "01_scenario_tasks.jsonl",
        "02_visual_questions_raw.jsonl",
        "03_visual_queries_raw.jsonl",
        "04_visual_query_clusters.json",
        "05_observer_dataset_with_gt.json",
        "excluded_cases.json",
        "review_required_cases.json",
    ):
        summary.append(f"- `{filename}`")
    write_text(out_dir / "summary.md", "\n".join(summary) + "\n")

    return {
        "scenario": scenario,
        "tasks": len(tasks),
        "raw": len(raw_rows),
        "cases": len(eval_cases),
        "excluded": len(excluded),
        "review_required": len(review_required),
        "validation_issues": len(validation_issues),
    }


def write_root_readme(results: list[dict[str, Any]]) -> None:
    lines = [
        "# Observer Dataset Rebuild v1",
        "",
        "This directory is independent from the older `observer_problem_set_*` folders.",
        "It follows `../eval-process.md` and stores GT inline in each eval case.",
        "",
        "## Layout",
        "",
        "Each scenario subdirectory contains:",
        "",
        "- `01_scenario_tasks.jsonl`: final scenario tasks used as extraction source.",
        "- `02_visual_questions_raw.jsonl`: un-deduped extracted visual problems.",
        "- `03_visual_queries_raw.jsonl`: visual_query_v1 per raw problem.",
        "- `04_visual_query_clusters.json`: deduped observer problems.",
        "- `05_observer_dataset_with_gt.json`: source-of-truth eval cases with inline event/detail GT.",
        "- `excluded_cases.json`: cases kept out of strict eval.",
        "- `review_required_cases.json`: validation or GT gaps that need manual review.",
        "- `summary.md`: readable counts and coverage.",
        "",
        "## Current Build",
        "",
    ]
    for row in results:
        lines.append(
            f"- `{row['scenario']}`: {row['cases']} cases, {row['raw']} raw visual problems, "
            f"{row['excluded']} excluded, {row['review_required']} review-required, "
            f"{row['validation_issues']} validation issues"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `visual_query_v1` is the normalized observer-call interface and cluster key.",
            "- GT is bootstrapped from existing video-inspected files and marked for human review where needed.",
            "- Do not edit indexed exports by hand; generate them from `05_observer_dataset_with_gt.json`.",
        ]
    )
    write_text(OUT_ROOT / "README.md", "\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=["order", "retail", "restaurant", "kitchen", "all"],
        default="all",
    )
    args = parser.parse_args()
    scenarios = ["order", "retail", "restaurant", "kitchen"] if args.scenario == "all" else [args.scenario]
    results = [build_scenario(scenario) for scenario in scenarios]

    existing_results: list[dict[str, Any]] = []
    if (OUT_ROOT / "README.md").exists() and args.scenario != "all":
        # Keep the root README complete after incremental per-scenario builds.
        for scenario in ["order", "retail", "restaurant", "kitchen"]:
            dataset = OUT_ROOT / scenario / "05_observer_dataset_with_gt.json"
            if dataset.exists() and scenario not in {row["scenario"] for row in results}:
                data = load_json(dataset)
                existing_results.append(
                    {
                        "scenario": scenario,
                        "tasks": data["coverage"]["source_task_count"],
                        "raw": data["coverage"]["raw_visual_problem_count"],
                        "cases": data["case_count"],
                        "excluded": data["excluded_count"],
                        "review_required": data["review_required_count"],
                        "validation_issues": len(load_json(OUT_ROOT / scenario / "review_required_cases.json").get("validation_issues", [])),
                    }
                )
    merged = {row["scenario"]: row for row in existing_results + results}
    write_root_readme([merged[key] for key in ["order", "retail", "restaurant", "kitchen"] if key in merged])
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
