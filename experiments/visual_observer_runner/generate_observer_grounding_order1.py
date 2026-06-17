#!/usr/bin/env python3
"""Generate bootstrap observer GT for the order1 normalized problem set.

The output is intentionally evaluation-oriented:
- eval_cases are the units an observer evaluator consumes.
- event_ground_truths are reusable temporal/spatial anchors.
- detail_ground_truths are reusable canonical answers.

This file does not use final task values as observer input. It only fills a
bootstrap GT file from video/menu inspection and marks ambiguous groupings for
later human review.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
DEFAULT_PROBLEM_DIR = (
    CURRENT_FILE.parent / "eval" / "observer_problem_set_order1"
)


ANNIE_CATEGORY_ALIASES = {
    "Cold Cuts": ["COLD CUTS", "cold cuts"],
    "Cheese & Olives": ["CHEESE & OLIVES", "Cheese and Olives"],
    "Annie's top dishes": ["ANNIE'S Top Dishes", "Annie's Top Dishes", "Annie's top dishes"],
    "Antipasti & Snacks": ["ANTIPASTI & SNACKS", "Antipasti / Snacks", "Antipasti and Snacks"],
    "Sandwiches & Panini": ["SANDWICHES PANINI", "SANDWICHES & PANINI", "Sandwiches / Panini"],
    "Italian Pasta": ["ITALIAN PASTA"],
    "Pizza": ["PIZZA"],
    "Salads": ["SALADS"],
    "Selected Steaks": ["SELECTED STEAKS"],
    "Handmade Bread": ["HANDMADE BREAD", "Homemade Bread"],
}

POINTING_DISH_BY_ORDINAL = {
    "first": ("Lasagne", ["lasagne"], "Annie's top dishes"),
    "second": ("Ham & melon", ["Ham and melon", "ham & melon"], "Annie's top dishes"),
    "third": ("Margherita", ["margherita"], "Pizza"),
    "last": ("Margherita", ["margherita"], "Pizza"),
    "final": ("Margherita", ["margherita"], "Pizza"),
}

VIDEO_POINTING_EVENT_RANGES = {
    "greek_annie_1.mp4": {
        "first": ([9.4, 10.2], [9.5, 10.1], [9.1, 10.35]),
        "second": ([10.35, 11.55], [10.5, 11.2], [10.2, 11.75]),
        "third": ([13.35, 14.55], [13.5, 14.25], [13.1, 14.75]),
        "last": ([13.35, 14.55], [13.5, 14.25], [13.1, 14.75]),
        "final": ([13.35, 14.55], [13.5, 14.25], [13.1, 14.75]),
    },
    "__annie_first_menu_sequence__": {
        "first": ([1.0, 2.2], [1.1, 2.0], [0.8, 2.35]),
        "second": ([2.0, 3.1], [2.1, 2.8], [1.8, 3.25]),
        "third": ([5.0, 6.1], [5.1, 5.8], [4.7, 6.3]),
        "last": ([5.0, 6.1], [5.1, 5.8], [4.7, 6.3]),
        "final": ([5.0, 6.1], [5.1, 5.8], [4.7, 6.3]),
    },
}

VIDEO_MENU_EVIDENCE_RANGES = {
    # In these videos the Annie menu is shown first, before switching to the
    # other restaurant menu near the end.
    ("afrikana_annie_1.mp4", "menu_2"): [0.0, 6.5],
    ("annie_butcher_1.mp4", "menu_1"): [0.0, 6.5],
    ("annie_meraki_1.mp4", "menu_1"): [0.0, 6.5],
    ("annie_pauhana_1.mp4", "menu_1"): [0.0, 6.5],
    ("sunny_annie_1.mp4", "menu_2"): [0.0, 6.5],
    # greek_annie_1 shows the Greek menu first, then the Annie menu.
    ("greek_annie_1.mp4", "menu_2"): [8.6, 16.1],
}

STATIC_REGION_BY_CATEGORY = {
    "Cold Cuts": "left fold, top white rounded card",
    "Cheese & Olives": "left fold, middle white rounded card",
    "Annie's top dishes": "left fold, bottom white rounded card",
    "Antipasti & Snacks": "middle fold, top white section",
    "Sandwiches & Panini": "middle fold, center boxed section",
    "Italian Pasta": "middle fold, bottom white section",
    "Pizza": "right fold, top white section",
    "Salads": "right fold, center-right boxed section with vertical SALADS title",
    "Selected Steaks": "right fold, dark-background section below Salads",
    "Handmade Bread": "right fold, bottom small supplementary section",
}

STATIC_REGION_TIME_GROUP_BY_CATEGORY = {
    "Cold Cuts": "left_fold",
    "Cheese & Olives": "left_fold",
    "Annie's top dishes": "left_fold",
    "Antipasti & Snacks": "middle_fold",
    "Sandwiches & Panini": "middle_fold",
    "Italian Pasta": "middle_fold",
    "Pizza": "right_fold",
    "Salads": "right_fold",
    "Selected Steaks": "right_fold",
    "Handmade Bread": "right_fold_bottom",
}

STATIC_REGION_TIME_RANGES = {
    "__annie_first_menu_sequence__": {
        "left_fold": ([1.0, 4.5], [1.2, 4.0], [0.8, 5.0]),
        "middle_fold": ([3.5, 7.8], [4.0, 7.4], [3.0, 8.3]),
        "right_fold": ([4.0, 8.3], [4.5, 8.0], [3.5, 8.5]),
        "right_fold_bottom": ([5.0, 8.3], [5.5, 8.0], [4.5, 8.5]),
        "full_menu": ([1.0, 8.3], [1.2, 8.0], [0.8, 8.5]),
    },
    "greek_annie_1.mp4": {
        "left_fold": ([8.5, 12.5], [9.0, 12.0], [8.2, 13.0]),
        "middle_fold": ([11.5, 16.1], [12.0, 15.8], [11.0, 16.1]),
        "right_fold": ([12.0, 15.8], [12.5, 15.5], [11.5, 16.1]),
        "right_fold_bottom": ([13.0, 16.1], [13.5, 15.8], [12.5, 16.1]),
        "full_menu": ([8.5, 16.1], [9.0, 15.8], [8.2, 16.1]),
    },
}

ANCHOR_DEFAULT_CATEGORY = {
    "bottom_left_category": "Annie's top dishes",
    "bottom_left_white_rounded_box": "Annie's top dishes",
    "bottom_middle_fold_category": "Italian Pasta",
    "bottom_right_category": "Handmade Bread",
    "bottom_right_dark_background_white_text": "Selected Steaks",
    "bottom_right_small_supplementary_section": "Handmade Bread",
    "dark_background_white_text_section": "Selected Steaks",
    "first_left_white_rounded_box": "Cold Cuts",
    "first_top_left_white_rounded_box": "Cold Cuts",
    "middle_left_fold_category": "Cheese & Olives",
    "middle_middle_fold_category": "Sandwiches & Panini",
    "middle_right_fold_category": "Selected Steaks",
    "right_fold_dark_background_white_text": "Selected Steaks",
    "second_bottom_left_white_rounded_box": "Cheese & Olives",
    "second_left_white_rounded_box": "Cheese & Olives",
    "second_top_left_white_rounded_box": "Cheese & Olives",
    "third_left_white_rounded_box": "Annie's top dishes",
    "third_top_left_white_rounded_box": "Annie's top dishes",
    "top_left_category": "Cold Cuts",
    "top_left_independent_small_card": "Cold Cuts",
    "top_left_white_rounded_box": "Cold Cuts",
    "top_middle_fold_category": "Antipasti & Snacks",
    "top_right_category": "Pizza",
    "white_rounded_box": "Annie's top dishes",
    "above_bottom_right_small_section": "Selected Steaks",
    "above_dark_background_section": "Pizza",
    "below_dark_background_section": "Handmade Bread",
    "below_visible_anchor": "Selected Steaks",
    "below_appetizers_and_snacks": "Sandwiches & Panini",
    "right_of_top_middle_section": "Pizza",
    "small_hand_illustration_section": "Italian Pasta",
    "middle_fold_title_left_small_hand": "Italian Pasta",
    "middle_fold_right_border_small_hand": "Sandwiches & Panini",
    "right_fold_left_border_small_hand": "Salads",
    "left_border_small_hand": "Salads",
}

AMBIGUOUS_ANCHORS = {
    "above_small_hand_illustration_section",
    "below_small_hand_illustration_section",
    "left_of_small_hand_illustration_section",
    "left_of_salad_small_hand_section",
    "left_of_visible_anchor",
    "right_of_visible_anchor",
    "above_visible_anchor",
    "dark_green_background_small_card",
    "left_dark_green_background_white_box",
    "right_border_small_hand",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def norm_id(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    return "_".join(part for part in cleaned.split("_") if part)


def snippet_text(problem: dict[str, Any]) -> str:
    return " ".join(
        (example.get("review_source_instruction_snippet") or "")
        for example in problem.get("review_examples", [])
    ).lower()


def infer_category(problem: dict[str, Any]) -> tuple[str | None, str, list[str], list[str]]:
    anchor_id = (problem.get("visual_anchor") or {}).get("anchor_id")
    text = snippet_text(problem)
    notes: list[str] = []
    candidates: list[str] = []

    if problem["problem_type"] == "category_containing_pointed_dish":
        for ordinal, (_, _, category) in POINTING_DISH_BY_ORDINAL.items():
            if f"_{ordinal}_pointed_dish" in (anchor_id or ""):
                return category, "high", notes, candidates
        return None, "low", ["No ordinal found in category-containing-pointed-dish anchor."], candidates

    if problem["problem_type"] == "dish_by_position_in_menu_region":
        return None, "high", notes, candidates

    if "third white" in text:
        return "Annie's top dishes", "high", notes, candidates
    if "second white" in text or "second small card" in text or "middle of the deep green" in text:
        return "Cheese & Olives", "medium", notes, candidates
    if "first white" in text or "first category with the dark green background on the left" in text:
        return "Cold Cuts", "high", notes, candidates

    if "top of the left" in text or "top category of the left" in text or "top-left" in text:
        return "Cold Cuts", "high", notes, candidates
    if "middle of the left" in text or "middle category of the left" in text:
        return "Cheese & Olives", "high", notes, candidates
    if "bottom of the left" in text or "bottom-left" in text:
        return "Annie's top dishes", "high", notes, candidates

    if "directly above the bottom-right small supplementary section" in text:
        return "Selected Steaks", "high", notes, candidates
    if "directly above the supplementary small section" in text:
        return "Selected Steaks", "high", notes, candidates
    if "immediately above the smaller homemade bread section" in text:
        return "Selected Steaks", "high", notes, candidates
    if "to the right of the section at the top of the middle" in text:
        return "Pizza", "high", notes, candidates
    if "right category of the top section of the middle" in text:
        return "Pizza", "high", notes, candidates

    if "top of the middle" in text or "top section of the middle" in text:
        return "Antipasti & Snacks", "high", notes, candidates
    if "exact middle of the middle" in text or "center of the middle" in text:
        return "Sandwiches & Panini", "high", notes, candidates
    if "bottom of the middle" in text or "left side of the middle fold title" in text:
        return "Italian Pasta", "high", notes, candidates

    if "top of the right" in text or "topmost category on the right" in text or "top right corner" in text:
        return "Pizza", "high", notes, candidates
    if "above the dark background" in text or "above the section featuring a dark background" in text:
        return "Pizza", "high", notes, candidates
    if "dark background" in text and "below" not in text and "above" not in text:
        return "Selected Steaks", "high", notes, candidates
    if "below the dark background" in text or "under the category with the dark background" in text:
        return "Handmade Bread", "high", notes, candidates
    if "bottom right" in text or "bottom-right" in text or "homemade bread" in text or "supplementary small section" in text:
        return "Handmade Bread", "high", notes, candidates

    if "salad section" in text or "left border of the right" in text or "right fold page that features a small hand" in text:
        return "Salads", "medium", notes, candidates
    if "right border of the middle" in text:
        return "Sandwiches & Panini", "medium", notes, candidates

    if "small hand illustration to the left of the middle fold title" in text:
        notes.append(
            "Source asks for the category whose title has a small hand on the left; the normalized relation label is misleading."
        )
        return "Italian Pasta", "medium", notes, candidates
    if (
        "small hand illustration to the left of the title" in text
        or "small hand located to the left of the title" in text
        or "small hand illustration located to the left of the title" in text
    ):
        notes.append(
            "Source asks for the category whose title has a small hand on the left; the normalized relation label is misleading."
        )
        return "Italian Pasta", "medium", notes, candidates
    if "small hand icon to the left of the title" in text or "small hand illustration on the left side of the title" in text:
        notes.append(
            "Source asks for the category whose title has a small hand on the left; the normalized relation label is misleading."
        )
        return "Italian Pasta", "medium", notes, candidates
    if "directly below the section with a small hand illustration in the right-hand fold" in text:
        return "Selected Steaks", "medium", notes, candidates
    if "directly above the section with the small hand illustration on the left border" in text:
        return "Pizza", "medium", notes, candidates
    if "directly above the dark green background section" in text:
        notes.append(
            "Interpreted the dark green background section as the Selected Steaks block on the right fold; the section directly above it is Salads."
        )
        return "Salads", "medium", notes, candidates
    if "directly below the category featuring lively small hand illustrations on the right border" in text:
        candidates = ["Italian Pasta", "Annie's top dishes"]
        notes.append(
            "The source can refer to the middle-fold Sandwiches & Panini right-border hand or a left-fold card border; using the middle-fold reading as primary."
        )
        return "Italian Pasta", "low", notes, candidates
    if "category with lively little hand illustrations on the right border" in text:
        candidates = ["Sandwiches & Panini", "Cheese & Olives"]
        notes.append(
            "The menu has multiple right-border hand illustrations; this normalized observer input is under-specified."
        )
        return "Sandwiches & Panini", "low", notes, candidates
    if "category marked with a small hand illustration on the right border" in text:
        candidates = ["Sandwiches & Panini", "Cheese & Olives"]
        notes.append(
            "The menu has multiple right-border hand illustrations; this normalized observer input is under-specified."
        )
        return "Sandwiches & Panini", "low", notes, candidates
    if "directly above the category with the lively small hand" in text:
        candidates = ["Pizza", "Antipasti & Snacks"]
        notes.append(
            "The normalized anchor omits which small-hand section is referenced; source snippets can map to either right-fold Salads or middle-fold Sandwiches & Panini."
        )
        return candidates[0], "low", notes, candidates
    if "directly below the section with the small hand" in text:
        candidates = ["Selected Steaks", "Italian Pasta"]
        notes.append(
            "The normalized anchor omits whether the reference is the right-fold Salads section or the middle-fold Sandwiches & Panini section."
        )
        return candidates[0], "low", notes, candidates

    category = ANCHOR_DEFAULT_CATEGORY.get(anchor_id)
    confidence = "medium"
    if anchor_id in AMBIGUOUS_ANCHORS:
        confidence = "low"
        notes.append("Anchor is under-specified after coarse grouping; verify against source task before using as a strict GT.")
    return category, confidence, notes, candidates


def pointing_ranges(video_path: str, ordinal: str) -> tuple[list[float], list[float], list[float]]:
    video_key = video_path if video_path in VIDEO_POINTING_EVENT_RANGES else "__annie_first_menu_sequence__"
    return VIDEO_POINTING_EVENT_RANGES[video_key][ordinal]


def build_pointing_event(video_path: str, menu_label: str, ordinal: str) -> dict[str, Any]:
    expected, primary, allowed = pointing_ranges(video_path, ordinal)
    event_id = f"{norm_id(video_path.removesuffix('.mp4'))}_{menu_label}_pointing_{ordinal}"
    return {
        "event_gt_id": event_id,
        "event_type": "temporal_sequence_event",
        "action": "pointing",
        "ordinal": ordinal,
        "expected_time_range": expected,
        "primary_content_range": primary,
        "allowed_transition_range": allowed,
        "evidence_time_range": allowed,
        "expected_region": "Annie Italian Restaurant menu; pointed dish row",
        "center_time": round((primary[0] + primary[1]) / 2, 3),
        "confidence": "medium" if video_path != "greek_annie_1.mp4" else "high",
        "evidence": [
            "AI bootstrap from inspected contact sheets; non-greek Annie videos share the same early Annie-menu pointing sequence."
        ],
    }


def build_static_event(video_path: str, menu_label: str, category: str | None, anchor_id: str | None) -> dict[str, Any]:
    safe_target = norm_id(category or anchor_id or "unknown_static_region")
    event_id = f"{norm_id(video_path.removesuffix('.mp4'))}_{menu_label}_static_{safe_target}"
    video_key = video_path if video_path in STATIC_REGION_TIME_RANGES else "__annie_first_menu_sequence__"
    time_group = STATIC_REGION_TIME_GROUP_BY_CATEGORY.get(category or "", "full_menu")
    expected, primary, allowed = STATIC_REGION_TIME_RANGES[video_key][time_group]
    return {
        "event_gt_id": event_id,
        "event_type": "static_spatial_region",
        "expected_time_range": expected,
        "primary_content_range": primary,
        "allowed_transition_range": allowed,
        "expected_region": STATIC_REGION_BY_CATEGORY.get(category or "", f"menu region for {anchor_id}"),
        "confidence": "medium" if category else "low",
        "evidence_time_range": allowed,
        "evidence": [
            "AI bootstrap static-region time GT from inspected contact sheets; the interval marks when the target menu region is visible enough for detail reading."
        ],
    }


def build_detail(category_or_dish: str, kind: str, confidence: str, notes: list[str], candidates: list[str]) -> dict[str, Any]:
    detail_id = f"{kind}_{norm_id(category_or_dish)}"
    aliases = ANNIE_CATEGORY_ALIASES.get(category_or_dish, []) if kind == "category" else []
    if category_or_dish == "Kalamata olives":
        aliases = ["Kalamata olive", "kalamata olives"]
    if category_or_dish == "Lasagne":
        aliases = ["lasagne"]
    if category_or_dish == "Ham & melon":
        aliases = ["Ham and melon", "ham & melon"]
    if category_or_dish == "Margherita":
        aliases = ["margherita"]
    return {
        "detail_gt_id": detail_id,
        "target_kind": "menu_catalog_or_category" if kind == "category" else "dish_name",
        "canonical_value": category_or_dish,
        "acceptable_aliases": aliases,
        "negative_neighbors": [],
        "confidence": confidence,
        "alternative_values_due_to_ambiguous_source_grouping": candidates,
        "notes": notes,
    }


def reduced_observer_input(problem: dict[str, Any]) -> dict[str, Any]:
    observer_input = problem["observer_input"]
    return {
        "schema_version": observer_input.get("schema_version"),
        "problem_id": observer_input.get("problem_id"),
        "video_path": observer_input.get("video_path"),
        "menu_label": observer_input.get("menu_label"),
        "task_type": observer_input.get("task_type"),
        "target_kind": observer_input.get("target_kind"),
        "slots": observer_input.get("slots", {}),
    }


def generate(problem_dir: Path, output_path: Path) -> dict[str, Any]:
    problems = load_json(problem_dir / "observer_problem_set_draft.json")
    eval_cases: list[dict[str, Any]] = []
    event_gt_by_id: dict[str, dict[str, Any]] = {}
    detail_gt_by_id: dict[str, dict[str, Any]] = {}

    for problem in problems:
        video_path = problem["video_path"]
        menu_label = problem["menu_label"]
        anchor_id = (problem.get("visual_anchor") or {}).get("anchor_id")
        problem_type = problem["problem_type"]
        notes: list[str] = []
        candidates: list[str] = []
        review_priority = "normal"

        if problem_type == "pointed_dish_by_ordinal":
            ordinal = problem["ordinal"]
            dish, aliases, _ = POINTING_DISH_BY_ORDINAL[ordinal]
            event = build_pointing_event(video_path, menu_label, ordinal)
            detail = build_detail(dish, "dish", event["confidence"], [], [])
            detail["acceptable_aliases"] = aliases
            modes = ["event_only", "detail_with_gt_event", "detail_with_predicted_event", "end_to_end"]
        elif problem_type == "category_containing_pointed_dish":
            ordinal = (anchor_id or "").replace("category_containing_", "").replace("_pointed_dish", "")
            if ordinal == "final":
                ordinal = "last"
            event = build_pointing_event(video_path, menu_label, ordinal)
            category, confidence, notes, candidates = infer_category(problem)
            detail = build_detail(category or "UNKNOWN", "category", confidence, notes, candidates)
            modes = ["event_only", "detail_with_gt_event", "detail_with_predicted_event", "end_to_end"]
        elif problem_type == "dish_by_position_in_menu_region":
            event = build_static_event(video_path, menu_label, "Cheese & Olives", anchor_id)
            detail = build_detail("Kalamata olives", "dish", "medium", ["Last visible dish in the middle-left Cheese & Olives card."], [])
            modes = ["detail_with_static_region"]
        else:
            category, confidence, notes, candidates = infer_category(problem)
            event = build_static_event(video_path, menu_label, category, anchor_id)
            detail = build_detail(category or "UNKNOWN", "category", confidence, notes, candidates)
            modes = ["detail_with_static_region"]

        if detail["confidence"] == "low" or detail["canonical_value"] == "UNKNOWN":
            review_priority = "high"
        elif detail["confidence"] == "medium":
            review_priority = "medium"

        event_gt_by_id[event["event_gt_id"]] = event
        detail_gt_by_id[detail["detail_gt_id"]] = detail

        eval_cases.append(
            {
                "case_id": problem["problem_id"],
                "problem_type": problem_type,
                "video_path": video_path,
                "menu_label": menu_label,
                "observer_input": reduced_observer_input(problem),
                "event_gt_id": event["event_gt_id"],
                "detail_gt_id": detail["detail_gt_id"],
                "evaluation_modes": modes,
                "gt_status": "ai_bootstrap_pending_human_review",
                "case_gt_confidence": detail["confidence"],
                "alternative_values_due_to_ambiguous_source_grouping": detail[
                    "alternative_values_due_to_ambiguous_source_grouping"
                ],
                "human_review_priority": review_priority,
                "source_task_ids": problem.get("source_task_ids", []),
                "source_request_ids": problem.get("source_request_ids", []),
                "source_consistency_notes": notes,
            }
        )

    coverage = {
        "eval_case_count": len(eval_cases),
        "event_gt_count": len(event_gt_by_id),
        "detail_gt_count": len(detail_gt_by_id),
        "human_review_priority_counts": dict(Counter(case["human_review_priority"] for case in eval_cases)),
        "detail_confidence_counts": dict(Counter(detail["confidence"] for detail in detail_gt_by_id.values())),
    }

    result = {
        "schema_version": "observer_grounding_eval_v1",
        "scenario_key": "order1",
        "status": "ai_bootstrap_pending_human_review",
        "purpose": "Bootstrap GT for evaluating observer event localization and detail recognition independently on normalized order1 visual tasks.",
        "scoring_defaults": {
            "temporal_sequence_event": {
                "event_metric": "gt_primary_range_coverage_ratio",
                "gt_range_source": "primary_content_range",
                "score_formula": "duration(overlap(predicted_time_range, primary_content_range)) / duration(primary_content_range)",
                "pass_threshold": 0.8,
                "ordinal_required": True,
            },
            "static_spatial_region": {
                "event_metric": "gt_primary_range_coverage_ratio",
                "gt_range_source": "primary_content_range",
                "score_formula": "duration(overlap(predicted_time_range, primary_content_range)) / duration(primary_content_range)",
                "pass_threshold": 0.8,
                "region_metric": "expected_region_match_pending_structured_region_output",
            },
            "detail": {
                "metric": "canonical_or_alias_exact_match",
                "case_sensitive": False,
                "normalize_whitespace": True,
                "target_value_source": "detail_ground_truths.canonical_value",
            },
        },
        "coverage": coverage,
        "eval_cases": eval_cases,
        "event_ground_truths": sorted(event_gt_by_id.values(), key=lambda x: x["event_gt_id"]),
        "detail_ground_truths": sorted(detail_gt_by_id.values(), key=lambda x: x["detail_gt_id"]),
    }
    write_json(output_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problem_dir", type=Path, default=DEFAULT_PROBLEM_DIR)
    parser.add_argument(
        "--output_path",
        type=Path,
        default=DEFAULT_PROBLEM_DIR / "observer_grounding_order1_bootstrap.json",
    )
    args = parser.parse_args()
    result = generate(args.problem_dir, args.output_path)
    print(json.dumps(result["coverage"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output_path}")


if __name__ == "__main__":
    main()
