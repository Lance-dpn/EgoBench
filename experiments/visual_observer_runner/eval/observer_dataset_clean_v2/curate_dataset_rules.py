#!/usr/bin/env python3
"""Curate clean v2 observer eval cases after video GT review.

This script applies reviewer policy decisions to the generated clean-v2
datasets. It does not create GT and does not read old bootstrap/final/eval
artifacts.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = ROOT / "experiments/visual_observer_runner/eval/observer_dataset_clean_v2"
SCENARIOS = ("order", "retail", "restaurant", "kitchen")


TRUNCATED_SUFFIXES = (
    " of the",
    " for the",
    " with the",
    " to the",
    " from the",
    " above the",
    " below the",
    " left of the",
    " right of the",
    " and the",
    " and",
    " or",
    " the",
)

UNDER_SPECIFIED_HINTS = {
    "among wines you pointed to",
    "among wines you pointed to, please",
    "bottle to right of the",
    "category and of bottle to right of the",
    "bottle above the",
    "bottle to left of the",
    "wine above the",
    "ingredient",
    "ingredient's calories",
    "wines that",
    "box's",
}

USER_OR_ROLE_RE = re.compile(
    r"\b(user id|wine enthusiast|wine critic|wine purchaser|wine novice|wine lover|shopper|customer|collector|expert)\b",
    re.I,
)

BUSINESS_AS_VISUAL_RE = re.compile(
    r"\b(product database|current inventory|current menu|other products|products produced|"
    r"search the current|find the recipe with|select the recipe|ingredients at home|"
    r"stored in home|stored on countertop|stored in the home|drink-category ingredients|"
    r"wine suitable|specific taste characteristics|same country of origin|"
    r"greatest variety of vegetables from all recipes)\b",
    re.I,
)

COMPARISON_OR_MULTI_RE = re.compile(
    r"\b(compare|difference between|respective|either|same as|two bottles|two wines|"
    r"one bottle .* one bottle|whether .* and whether|price difference)\b",
    re.I,
)

BOTH_ATTRIBUTE_RE = re.compile(
    r"\bboth (have|has|are|is|contain|contains|share|meet|satisfy)\b",
    re.I,
)

PAIR_REFERENT_RE = re.compile(
    r"\b(wine|bottle|dish|box|ingredient|category|section)s?\b.*\band\b.*\b"
    r"(wine|bottle|dish|box|ingredient|category|section)s?\b",
    re.I,
)


REPAIRS: dict[str, dict[str, Any]] = {
    "order_clean_v2_problem_0207": {
        "content_hint": "top category on the left panel",
        "notes": "Repaired truncated visual query from existing video GT: category is COLD CUTS.",
    },
    "kitchen_clean_v2_problem_0045": {
        "content_hint": "recipe being prepared from cutting fried pork chops",
        "action": "cutting",
        "notes": "Repaired truncated visual query from existing video GT: Deep-fried Meat Platter.",
    },
    "kitchen_clean_v2_problem_0035": {
        "target_kind": "recipe_name",
        "selection_unit": "recipe_scene",
        "content_hint": "dish being prepared from cutting fried pork chops",
        "notes": "Repaired extracted target from ingredient_name to recipe_name; the visual query asks for the dish being prepared.",
    },
    "retail_clean_v2_problem_0235": {
        "content_hint": "pointed orange St Michel cookie box on the shelf",
        "action": "pointing",
        "notes": "Repaired visual referent from downstream allergen fact to the visible orange product box.",
    },
    "restaurant_clean_v2_problem_0103": {
        "target_kind": "category",
        "selection_unit": "menu_section",
        "content_hint": "dark background category area on the right foldout",
        "notes": "Repaired extracted target from dish_name to category; the visual query asks for a menu area, not a single dish.",
    },
    "order_clean_v2_problem_0227": {
        "target_kind": "dish_name",
        "selection_unit": "menu_item",
        "content_hint": "second-to-last dish in the Italian Pasta category on the middle fold",
        "notes": "Repaired extracted target from category to dish_name; the visual query asks for a specific dish in the category.",
    },
    "order_clean_v2_problem_0243": {
        "target_kind": "dish_name",
        "selection_unit": "menu_item",
        "content_hint": "third dish in the top Antipasti & Snacks section on the middle fold",
        "notes": "Repaired extracted target from category to dish_name; the visual query asks for a specific dish in the top middle-fold section.",
    },
    "kitchen_clean_v2_problem_0016": {
        "target_kind": "ingredient_name",
        "selection_unit": "ingredient",
        "content_hint": "green vegetable located on the right side of the blue cutting board",
        "notes": "Repaired visual target from recipe_name to ingredient_name; the observer should resolve the visible ingredient, while recipe lookup is downstream service/tool logic.",
    },
    "kitchen_clean_v2_problem_0036": {
        "target_kind": "recipe_name",
        "selection_unit": "recipe_scene",
        "content_hint": "dish being prepared from slicing fried pork cutlets into strips",
        "notes": "Repaired extracted target from ingredient_name to recipe_name; the visual query asks for the dish being prepared.",
    },
    "kitchen_clean_v2_problem_0040": {
        "target_kind": "recipe_name",
        "selection_unit": "recipe_scene",
        "content_hint": "dish currently being prepared from cutting pork chops",
        "notes": "Repaired extracted target from ingredient_name to recipe_name; the visual query asks for the dish being prepared.",
    },
    "kitchen_clean_v2_problem_0041": {
        "target_kind": "recipe_name",
        "selection_unit": "recipe_scene",
        "content_hint": "dish currently being prepared from cutting pork chops",
        "notes": "Repaired extracted visual referent to the dish currently being prepared; downstream countertop checks are business/tool logic.",
    },
    "kitchen_clean_v2_problem_0042": {
        "target_kind": "recipe_name",
        "selection_unit": "recipe_scene",
        "content_hint": "dish currently being prepared from cutting pork chops",
        "notes": "Repaired extracted visual referent to the dish currently being prepared; downstream ingredient-category checks are business/tool logic.",
    },
}

for _case_id in (
    "retail_clean_v2_problem_0237",
    "retail_clean_v2_problem_0238",
    "retail_clean_v2_problem_0239",
    "retail_clean_v2_problem_0240",
    "retail_clean_v2_problem_0243",
    "retail_clean_v2_problem_0244",
    "retail_clean_v2_problem_0245",
    "retail_clean_v2_problem_0246",
    "retail_clean_v2_problem_0247",
):
    REPAIRS[_case_id] = {
        "target_kind": "product_name",
        "selection_unit": "product",
        "notes": "Repaired extracted target from visible_text to product_name; the instruction asks for the pointed cheese product, not an isolated shelf label OCR task.",
    }


MANUAL_EXCLUSIONS: dict[str, str] = {
    # Retail cases where the extracted visual query asks the observer to resolve
    # two separate products and compare or jointly query their business facts.
    "retail_clean_v2_problem_0077": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0078": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0079": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0081": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0089": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0101": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0102": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0104": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0108": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0109": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0110": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0111": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0115": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0129": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0139": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0142": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0170": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0183": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0196": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0199": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0046": "excluded_truncated_or_under_specified_visual_query",
    "retail_clean_v2_problem_0047": "excluded_truncated_or_under_specified_visual_query",
    "retail_clean_v2_problem_0070": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "retail_clean_v2_problem_0012": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0013": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0023": "excluded_truncated_or_under_specified_visual_query",
    "retail_clean_v2_problem_0025": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "retail_clean_v2_problem_0026": "excluded_truncated_or_under_specified_visual_query",
    "retail_clean_v2_problem_0027": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0028": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0172": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0174": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0175": "excluded_multi_object_comparison_or_business_comparison",
    "retail_clean_v2_problem_0211": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "retail_clean_v2_problem_0212": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0026": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0027": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0029": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0031": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0043": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0044": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0069": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0070": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0087": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0088": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0089": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0090": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0091": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0117": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0118": "excluded_user_identity_or_role_extracted_as_visual_referent",
    "order_clean_v2_problem_0119": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0122": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0123": "excluded_truncated_or_under_specified_visual_query",
    "order_clean_v2_problem_0124": "excluded_truncated_or_under_specified_visual_query",
    "order_clean_v2_problem_0132": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0156": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0157": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0160": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0162": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0163": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0164": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0176": "excluded_multi_object_comparison_or_business_comparison",
    "order_clean_v2_problem_0220": "excluded_truncated_or_under_specified_visual_query",
    "order_clean_v2_problem_0222": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "order_clean_v2_problem_0248": "excluded_multi_object_comparison_or_business_comparison",

    # Restaurant clean-up: exclude business facts, true multi-object sequences,
    # textual service/tool categories, and under-specified references.
    "restaurant_clean_v2_problem_0013": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0043": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0048": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0049": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0050": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0051": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0053": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0065": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0112": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0130": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0141": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0142": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0143": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0144": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0145": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0146": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0148": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0151": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0157": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0158": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0159": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0160": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0182": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0184": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0087": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0092": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0099": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0101": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0190": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0208": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0209": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0210": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0211": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0212": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0213": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0214": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0216": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0217": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0224": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0238": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0240": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0265": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0266": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0267": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0268": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0269": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0272": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0274": "excluded_multi_object_comparison_or_business_comparison",
    "restaurant_clean_v2_problem_0277": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0278": "excluded_truncated_or_under_specified_visual_query",
    "restaurant_clean_v2_problem_0279": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0314": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0315": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0319": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0320": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0321": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0322": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0323": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0324": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0325": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0326": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0327": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0328": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0329": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0330": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0331": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0332": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0334": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0335": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0336": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0337": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0338": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0339": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
    "restaurant_clean_v2_problem_0348": "excluded_business_goal_or_database_query_extracted_as_visual_referent",
}


ORDER_MENU_SEGMENTS: dict[str, list[dict[str, Any]]] = {
    "afrikana_annie_1.mp4": [
        {"menu_instance": "menu1", "menu_label": "Afrikana", "menu_time_range": [0.0, 0.9]},
        {"menu_instance": "menu2", "menu_label": "Annie", "menu_time_range": [0.9, 8.5]},
    ],
    "annie_butcher_1.mp4": [
        {"menu_instance": "menu1", "menu_label": "Annie", "menu_time_range": [0.0, 7.9]},
        {"menu_instance": "menu2", "menu_label": "Butcher", "menu_time_range": [7.9, 8.8]},
    ],
    "annie_meraki_1.mp4": [
        {"menu_instance": "menu1", "menu_label": "Annie", "menu_time_range": [0.0, 7.9]},
        {"menu_instance": "menu2", "menu_label": "Meraki", "menu_time_range": [7.9, 8.8]},
    ],
    "annie_pauhana_1.mp4": [
        {"menu_instance": "menu1", "menu_label": "Annie", "menu_time_range": [0.0, 7.9]},
        {"menu_instance": "menu2", "menu_label": "Pauhana", "menu_time_range": [7.9, 8.8]},
    ],
    "greek_annie_1.mp4": [
        {"menu_instance": "menu1", "menu_label": "Greek", "menu_time_range": [0.0, 8.9]},
        {"menu_instance": "menu2", "menu_label": "Annie", "menu_time_range": [8.9, 16.5]},
    ],
    "sunny_annie_1.mp4": [
        {"menu_instance": "menu1", "menu_label": "Sunny", "menu_time_range": [0.0, 0.9]},
        {"menu_instance": "menu2", "menu_label": "Annie", "menu_time_range": [0.9, 8.8]},
    ],
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def case_text(case: dict[str, Any]) -> tuple[str, str, str]:
    ref = case.get("visual_query_v1", {}).get("referent", {})
    hint = (ref.get("appearance", {}) or {}).get("content_hint") or ""
    snippets = " || ".join(case.get("source_instruction_snippets") or [])
    return hint, snippets, f"{hint} || {snippets}"


def is_truncated_hint(hint: str) -> bool:
    low = hint.strip().lower()
    return low in UNDER_SPECIFIED_HINTS or any(low.endswith(suffix) for suffix in TRUNCATED_SUFFIXES)


def exclusion_reason(case: dict[str, Any]) -> str | None:
    if case["case_id"] in MANUAL_EXCLUSIONS:
        return MANUAL_EXCLUSIONS[case["case_id"]]
    if case.get("gt_status") == "gt_video_annotated":
        return None
    hint, snippets, text = case_text(case)
    low_hint = hint.lower()
    low_text = text.lower()

    if USER_OR_ROLE_RE.search(low_hint):
        return "excluded_user_identity_or_role_extracted_as_visual_referent"
    if BUSINESS_AS_VISUAL_RE.search(low_hint):
        return "excluded_business_goal_or_database_query_extracted_as_visual_referent"
    if is_truncated_hint(hint):
        return "excluded_truncated_or_under_specified_visual_query"
    if COMPARISON_OR_MULTI_RE.search(low_text) or BOTH_ATTRIBUTE_RE.search(low_text):
        return "excluded_multi_object_comparison_or_business_comparison"
    if PAIR_REFERENT_RE.search(low_hint) and ("both" in low_text or "either" in low_text or "compare" in low_text):
        return "excluded_multi_object_comparison_or_business_comparison"
    return None


def apply_repairs(case: dict[str, Any]) -> bool:
    repair = REPAIRS.get(case["case_id"])
    if not repair:
        return False
    ref = case["visual_query_v1"]["referent"]
    target = case["visual_query_v1"]["target"]
    if "content_hint" in repair:
        ref.setdefault("appearance", {})["content_hint"] = repair["content_hint"]
    if "action" in repair:
        ref["action"] = repair["action"]
    if "target_kind" in repair:
        target["kind"] = repair["target_kind"]
    if "selection_unit" in repair:
        target["selection_unit"] = repair["selection_unit"]
    case.setdefault("review_notes", []).append(repair["notes"])
    return True


def menu_segment_for_time(video_id: str, time_value: Any) -> dict[str, Any] | None:
    segments = ORDER_MENU_SEGMENTS.get(video_id)
    if not segments:
        return None
    try:
        key_time = float(time_value)
    except (TypeError, ValueError):
        return None
    for index, segment in enumerate(segments):
        start, end = segment["menu_time_range"]
        is_last = index == len(segments) - 1
        if start <= key_time < end or (is_last and start <= key_time <= end):
            return segment
    return min(
        segments,
        key=lambda segment: min(abs(key_time - segment["menu_time_range"][0]), abs(key_time - segment["menu_time_range"][1])),
    )


def apply_order_menu_scope(case: dict[str, Any]) -> bool:
    if case.get("scenario") != "order":
        return False
    segment = menu_segment_for_time(case.get("video_id") or "", (case.get("event_gt") or {}).get("key_frame_time"))
    if not segment:
        return False
    scope = case.setdefault("visual_query_v1", {}).setdefault("scope", {})
    changed = False
    for key in ("menu_instance", "menu_label"):
        if scope.get(key) != segment[key]:
            scope[key] = segment[key]
            changed = True
    if "menu_time_range" in scope:
        scope.pop("menu_time_range", None)
        changed = True
    return changed


def excluded_record(case: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "scenario": case["scenario"],
        "video_id": case.get("video_id"),
        "reason": reason,
        "problem_type": case.get("problem_type"),
        "visual_query_v1": case.get("visual_query_v1"),
        "source_task_ids": case.get("source_task_ids", []),
        "source_problem_ids": case.get("source_problem_ids", []),
        "source_instruction_snippets": case.get("source_instruction_snippets", []),
    }


def refresh_dataset(data: dict[str, Any], excluded_total: int) -> None:
    cases = data["cases"]
    data["case_count"] = len(cases)
    data["gt_ready_case_count"] = sum(c.get("gt_status") == "gt_video_annotated" for c in cases)
    data["review_required_count"] = len(cases) - data["gt_ready_case_count"]
    data["excluded_count"] = excluded_total
    data["coverage"]["cluster_count"] = len(cases)
    data["coverage"]["video_case_counts"] = dict(Counter(c["video_id"] for c in cases))
    data["coverage"]["target_kind_counts"] = dict(
        Counter(c["visual_query_v1"]["target"]["kind"] for c in cases)
    )
    data["coverage"]["referent_type_counts"] = dict(
        Counter(c["visual_query_v1"]["referent"]["type"] for c in cases)
    )
    data["coverage"]["menu_label_counts"] = dict(
        Counter((c["visual_query_v1"].get("scope") or {}).get("menu_label") or "unknown" for c in cases)
    )
    data["coverage"]["menu_instance_counts"] = dict(
        Counter((c["visual_query_v1"].get("scope") or {}).get("menu_instance") or "unknown" for c in cases)
    )


def write_sidecars(scenario: str, data: dict[str, Any], excluded: list[dict[str, Any]]) -> None:
    out_dir = DATA_ROOT / scenario
    metadata = {
        key: data[key]
        for key in ("schema_version", "scenario", "status", "generated_at_utc", "source_policy", "process_doc")
        if key in data
    }
    write_json(out_dir / "excluded_cases.json", {**metadata, "excluded_cases": excluded})
    review_required = [
        {
            "case_id": c["case_id"],
            "reason": "gt_pending_video_annotation",
            "video_id": c.get("video_id"),
            "visual_query_v1": c.get("visual_query_v1"),
            "source_task_ids": c.get("source_task_ids", []),
        }
        for c in data["cases"]
        if c.get("gt_status") != "gt_video_annotated"
    ]
    write_json(out_dir / "review_required_cases.json", {**metadata, "review_required_cases": review_required})

    lines = [
        f"# {scenario.title()} Clean v2",
        "",
        "- Input source: `scenarios/final/*.json` instructions only.",
        "- Old bootstrap/problem_set/eval/final values are not read for extraction.",
        "- DB/tool data may be used only to confirm canonical names after visual identification.",
        "",
        f"- Eval cases: {data['case_count']}",
        f"- GT-ready cases: {data['gt_ready_case_count']}",
        f"- Review-required cases: {data['review_required_count']}",
        f"- Excluded cases: {data['excluded_count']}",
        "",
        "## Video Coverage",
    ]
    for video_id, count in sorted(data["coverage"]["video_case_counts"].items()):
        lines.append(f"- `{video_id}`: {count}")
    lines.extend(["", "## Target Kinds"])
    for key, count in sorted(data["coverage"]["target_kind_counts"].items()):
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Referent Types"])
    for key, count in sorted(data["coverage"]["referent_type_counts"].items()):
        lines.append(f"- `{key}`: {count}")
    menu_label_counts = data["coverage"].get("menu_label_counts") or {}
    if any(key != "unknown" for key in menu_label_counts):
        lines.extend(["", "## Menu Labels"])
        for key, count in sorted(menu_label_counts.items()):
            if key != "unknown":
                lines.append(f"- `{key}`: {count}")
        lines.extend(["", "## Menu Instances"])
        for key, count in sorted((data["coverage"].get("menu_instance_counts") or {}).items()):
            if key != "unknown":
                lines.append(f"- `{key}`: {count}")
    lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write curated datasets. Default is dry-run.")
    args = parser.parse_args()

    report: dict[str, Any] = {}
    for scenario in SCENARIOS:
        dataset_path = DATA_ROOT / scenario / "05_observer_dataset_with_gt.json"
        data = load_json(dataset_path)
        excluded_path = DATA_ROOT / scenario / "excluded_cases.json"
        existing_excluded = load_json(excluded_path).get("excluded_cases", []) if excluded_path.exists() else []
        existing_ids = {item["case_id"] for item in existing_excluded}

        kept: list[dict[str, Any]] = []
        newly_excluded: list[dict[str, Any]] = []
        repaired: list[str] = []
        menu_scoped: list[str] = []
        for case in data["cases"]:
            if apply_repairs(case):
                repaired.append(case["case_id"])
            if apply_order_menu_scope(case):
                menu_scoped.append(case["case_id"])
            reason = exclusion_reason(case)
            if reason:
                if case["case_id"] not in existing_ids:
                    newly_excluded.append(excluded_record(case, reason))
                continue
            kept.append(case)

        excluded = existing_excluded + newly_excluded
        data["cases"] = kept
        refresh_dataset(data, len(excluded))
        report[scenario] = {
            "kept_cases": len(kept),
            "newly_excluded": len(newly_excluded),
            "excluded_by_reason": dict(Counter(item["reason"] for item in newly_excluded)),
            "repaired": repaired,
            "menu_scoped": menu_scoped,
            "gt_ready": data["gt_ready_case_count"],
            "review_required": data["review_required_count"],
            "excluded_total": len(excluded),
        }
        if args.apply:
            write_json(dataset_path, data)
            write_sidecars(scenario, data, excluded)

    print(json.dumps({"mode": "apply" if args.apply else "dry_run", "report": report}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
