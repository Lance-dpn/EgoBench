#!/usr/bin/env python3
"""Build observer evaluation problem-set drafts from normalized visual requests.

This script converts instruction-level visual candidates into reusable observer
questions. The output is still pre-GT: event/detail grounding fields are empty
and intended for later video inspection plus human correction.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.visual_observer_runner.visual_request_normalizer import (  # noqa: E402
    normalize_space,
    normalize_visual_requests,
)


SCENARIOS_DIR = PROJECT_ROOT / "scenarios" / "final"
DEFAULT_OUTPUT_ROOT = CURRENT_FILE.parent / "eval"

ACTIVE_RESTAURANT_TO_MENU_BY_VIDEO = {
    "greek_annie_1.mp4": {
        "Mediterranean Greek Restaurant": "menu_1",
        "Annie Italian Restaurant": "menu_2",
    },
    "annie_butcher_1.mp4": {
        "Annie Italian Restaurant": "menu_1",
        "Butcher Restaurant": "menu_2",
    },
    "sunny_annie_1.mp4": {
        "Sunny Side Diner": "menu_1",
        "Sunny Side Restaurant": "menu_1",
        "Sunshine Restaurant": "menu_1",
        "Annie Italian Restaurant": "menu_2",
    },
    "afrikana_annie_1.mp4": {
        "Afrikana Kitchen": "menu_1",
        "Annie Italian Restaurant": "menu_2",
    },
    "annie_meraki_1.mp4": {
        "Annie Italian Restaurant": "menu_1",
        "Meraki Kitchen": "menu_2",
        "Meraki Restaurant": "menu_2",
        "Mediterranean Greek Restaurant": "menu_2",
    },
    "annie_pauhana_1.mp4": {
        "Annie Italian Restaurant": "menu_1",
        "Pau Hana Bar": "menu_2",
    },
}

ORDINAL_ZH = {
    "first": "第一次",
    "second": "第二次",
    "third": "第三次",
    "fourth": "第四次",
    "fifth": "第五次",
    "sixth": "第六次",
    "last": "最后一次",
    "final": "最后一次",
}

ORDINAL_EN = {
    "first": "first",
    "second": "second",
    "third": "third",
    "fourth": "fourth",
    "fifth": "fifth",
    "sixth": "sixth",
    "last": "last",
    "final": "last",
}

ANCHOR_EN_BY_ID = {
    "above_bottom_right_small_section": "menu category directly above the bottom-right small supplementary section",
    "above_dark_background_section": "menu category directly above the dark-background section",
    "above_small_hand_illustration_section": "menu category directly above the small-hand-illustration section",
    "above_visible_anchor": "menu category directly above the specified visible anchor",
    "below_appetizers_and_snacks": "menu category directly below the Appetizers and Snacks category",
    "below_dark_background_section": "menu category below the dark-background section",
    "below_small_hand_illustration_section": "menu category directly below the small-hand-illustration section",
    "below_visible_anchor": "menu category below the specified visible anchor",
    "bottom_left_category": "bottom-left menu category",
    "bottom_left_white_rounded_box": "bottom-left white rounded-box menu category",
    "bottom_middle_fold_category": "bottom category on the middle fold",
    "bottom_right_category": "bottom-right menu category",
    "bottom_right_dark_background_white_text": "bottom-right dark-background menu category",
    "bottom_right_small_supplementary_section": "bottom-right small supplementary menu section",
    "dark_background_white_text_section": "dark-background menu section",
    "dark_green_background_small_card": "small-card category inside the dark-green background section",
    "first_left_white_rounded_box": "first white rounded-box category on the left side",
    "first_top_left_white_rounded_box": "first top-left white rounded-box category",
    "left_border_small_hand": "menu category with a small hand illustration on the left border",
    "left_dark_green_background_white_box": "left-side dark-green-background section",
    "left_of_salad_small_hand_section": "menu category to the left of the salad section with a small hand icon",
    "left_of_small_hand_illustration_section": "menu category to the left of the small-hand-illustration section",
    "left_of_visible_anchor": "menu category to the left of the specified visible anchor",
    "middle_left_fold_category": "middle category on the left fold/page",
    "middle_left_small_card": "small-card category in the middle-left area",
    "middle_middle_fold_category": "center category on the middle fold",
    "middle_right_fold_category": "center category on the right fold",
    "middle_fold_right_border_small_hand": "category on the right border of the middle fold with a small hand illustration",
    "middle_fold_title_left_small_hand": "category with a small hand illustration to the left of the middle-fold title",
    "right_border_small_hand": "menu category with a small hand illustration on the right border",
    "right_fold_dark_background_white_text": "dark-background section on the right fold",
    "right_fold_left_border_small_hand": "category on the left border of the right fold with a small hand illustration",
    "right_of_top_middle_section": "menu category to the right of the top-middle section",
    "right_of_visible_anchor": "menu category to the right of the specified visible anchor",
    "second_bottom_left_white_rounded_box": "second bottom-left white rounded-box category",
    "second_left_white_rounded_box": "second white rounded-box category on the left side",
    "second_top_left_white_rounded_box": "second top-left white rounded-box category",
    "small_card_section": "small-card menu category",
    "small_hand_illustration_section": "menu category with a small hand illustration",
    "third_left_white_rounded_box": "third white rounded-box category on the left side",
    "top_left_category": "top-left menu category",
    "top_left_independent_small_card": "top-left independent small-card category",
    "top_left_white_rounded_box": "top-left white rounded-box category",
    "top_middle_fold_category": "top category on the middle fold",
    "top_right_category": "top-right menu category",
    "white_rounded_box": "white rounded-box menu category",
}

ANCHOR_REGION_BY_ID: dict[str, dict[str, Any]] = {
    "top_right_category": {"fold": "right", "vertical_position": "top", "region_role": "menu_category"},
    "top_middle_fold_category": {"fold": "middle", "vertical_position": "top", "region_role": "menu_category"},
    "middle_middle_fold_category": {"fold": "middle", "vertical_position": "center", "region_role": "menu_category"},
    "middle_right_fold_category": {"fold": "right", "vertical_position": "center", "region_role": "menu_category"},
    "bottom_right_category": {"fold": "right", "vertical_position": "bottom", "region_role": "menu_category"},
    "bottom_right_small_supplementary_section": {
        "fold": "right",
        "vertical_position": "bottom",
        "region_role": "small_supplementary_title",
        "region_size": "small_supplementary",
    },
    "dark_background_white_text_section": {
        "fold": "right",
        "vertical_position": "bottom",
        "region_role": "dark_background_category",
        "visual_style": "dark_background",
    },
    "right_fold_dark_background_white_text": {
        "fold": "right",
        "vertical_position": "bottom",
        "region_role": "dark_background_category",
        "visual_style": "dark_background",
    },
    "below_appetizers_and_snacks": {
        "fold": "middle",
        "vertical_position": "top",
        "region_role": "menu_category",
    },
    "above_dark_background_section": {
        "fold": "right",
        "vertical_position": "bottom",
        "region_role": "dark_background_category",
        "visual_style": "dark_background",
    },
    "above_bottom_right_small_section": {
        "fold": "right",
        "vertical_position": "bottom",
        "region_role": "small_supplementary_title",
        "region_size": "small_supplementary",
    },
}

NUMERIC_COMPARISON_PATTERN = re.compile(
    r"\b(price|cost|amount|calor(?:y|ies)|protein|sodium|sugar|fat|fiber|"
    r"carbohydrate|tax|discount|content|rate)\b.{0,80}\b("
    r"below|above|less than|greater than|exceed|exceeds|higher than|lower than)\b"
    r"|\b(below|above|less than|greater than|exceed|exceeds|higher than|lower than)\b"
    r".{0,80}\b(yuan|kcal|calories|grams?|mg|%)\b",
    re.IGNORECASE,
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def load_scenario_tasks(scenario_key: str) -> list[dict[str, Any]]:
    path = SCENARIOS_DIR / f"{scenario_key}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return load_json(path)


def restaurant_from_ground_truth(task: dict[str, Any]) -> str | None:
    counts: Counter[str] = Counter()
    for call in task.get("ground_truth") or []:
        parameters = call.get("parameters") or {}
        restaurant_name = parameters.get("restaurant_name")
        if restaurant_name:
            counts[normalize_space(restaurant_name)] += 1
    if counts:
        return counts.most_common(1)[0][0]
    return None


def restaurant_from_analysis(task: dict[str, Any]) -> str | None:
    analysis = task.get("analysis") or ""
    patterns = [
        r"limited exclusively to ([^.\\n]+)",
        r"limited to ([^.\\n]+)",
        r"restricted exclusively to ([^.\\n]+)",
        r"restricted solely to ([^.\\n]+)",
        r"restricted to ([^.\\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, analysis, re.IGNORECASE)
        if match:
            value = normalize_space(match.group(1))
            value = re.sub(r"^(the\s+)?", "", value, flags=re.IGNORECASE)
            value = re.sub(r"\s+(menu|restaurant)$", "", value, flags=re.IGNORECASE)
            return value
    return None


def infer_active_restaurant(task: dict[str, Any]) -> str | None:
    return restaurant_from_ground_truth(task) or restaurant_from_analysis(task)


def infer_menu_label(video_path: str | None, active_restaurant: str | None) -> str | None:
    if not video_path or not active_restaurant:
        return None
    mapping = ACTIVE_RESTAURANT_TO_MENU_BY_VIDEO.get(video_path, {})
    if active_restaurant in mapping:
        return mapping[active_restaurant]
    active_lower = active_restaurant.lower()
    for restaurant, label in mapping.items():
        if restaurant.lower() in active_lower or active_lower in restaurant.lower():
            return label
    return None


def is_false_visual_request(request: dict[str, Any]) -> bool:
    snippet = request["review_source_instruction_snippet"].lower()
    if re.search(r"\b(first|second)\s+menu\b", snippet) and "currently only" in snippet:
        return True
    if re.search(r"\b(menu|menus)\b.{0,80}\b(two restaurants|restaurant)\b", snippet) and "currently only" in snippet:
        return True
    if request["event_mode"] == "relative_spatial_region":
        has_spatial_relative = bool(
            re.search(
                r"\b(directly|immediately|located|category|section|area|region|"
                r"fold|page|border|corner)\b.{0,40}\b(above|below|left|right)\b"
                r"|\b(above|below|left|right)\b.{0,40}\b(category|section|area|region|fold|page|border|corner)\b",
                snippet,
            )
        )
        if request["target_key"] != "category" and NUMERIC_COMPARISON_PATTERN.search(snippet) and not has_spatial_relative:
            return True
        if request["target_key"] != "category" and not has_spatial_relative:
            return True
    if request["event_mode"] == "object_action_state" and "cooking student" in snippet:
        return True
    return False


def is_pointed_dish_problem(request: dict[str, Any]) -> bool:
    return (
        request["event_mode"] == "temporal_sequence_event"
        and request["detail_mode"] == "entity_identity"
        and request["target_key"] == "dish_name"
        and request.get("action") == "pointing"
        and bool(request.get("ordinal"))
    )


def is_category_request(request: dict[str, Any]) -> bool:
    return request["target_key"] == "category" and request["detail_mode"] == "section_or_category_identity"


def extract_region_dish_position(snippet: str) -> tuple[str, str] | None:
    text = snippet.lower()
    if re.search(r"\b(cheapest|lowest|highest|most expensive|highest-calorie|lowest-calorie)\b", text):
        return None
    patterns = [
        ("second_to_last", "倒数第二个", r"\bsecond-to-last\s+dish\b"),
        ("last", "最后一个", r"\blast\s+dish\b"),
        ("first", "第一个", r"\bfirst\s+dish\b"),
        ("top", "最上方", r"\btop\s+dish\b|\bdish\s+at\s+the\s+very\s+top\b"),
        ("bottom", "最下方", r"\bbottom\s+dish\b|\bdish\s+at\s+the\s+very\s+bottom\b"),
    ]
    if not re.search(r"\b(category|section|block|box|card|fold|panel|flap|page)\b", text):
        return None
    for position_id, position_zh, pattern in patterns:
        if re.search(pattern, text):
            return position_id, position_zh
    return None


def is_region_dish_problem(request: dict[str, Any]) -> bool:
    return (
        request["event_mode"] in {"static_spatial_region", "relative_spatial_region"}
        and request["target_key"] == "dish_name"
        and extract_region_dish_position(request["review_source_instruction_snippet"]) is not None
    )


def should_rescue_as_category_request(request: dict[str, Any]) -> bool:
    if request["target_key"] == "category":
        return False
    if is_region_dish_problem(request):
        return False
    if request["event_mode"] not in {"static_spatial_region", "relative_spatial_region"}:
        return False
    text = request["review_source_instruction_snippet"].lower()
    return bool(re.search(r"\b(category|section|block|card|box)\b", text))


def clause_mentions_pointed_category(snippet: str) -> str | None:
    text = snippet.lower()
    match = re.search(
        r"\bsame\s+category\s+as\s+(?:the\s+)?(first|second|third|last|final)\s+dish\s+you\s+pointed",
        text,
    )
    if match:
        return match.group(1)
    match = re.search(
        r"\b(category|section)\s+(?:where|containing|that contains|of)\s+"
        r"(?:the\s+)?(first|second|third|last|final)\s+(?:pointed|pointed-at|pointed out)",
        text,
    )
    if match:
        return match.group(2)
    match = re.search(
        r"\b(first|second|third|last|final)\s+(?:pointed|pointed-at|pointed out)"
        r".{0,40}\b(category|section)\b",
        text,
    )
    if match and "category" in text:
        return match.group(1)
    return None


def canonical_anchor_from_clause(snippet: str) -> dict[str, Any]:
    text = snippet.lower().replace("dark-background", "dark background").replace("white-background", "white background")
    anchor_id = "unclassified_menu_anchor"
    anchor_zh = "未归类的菜单视觉锚点"
    problem_type = "menu_category_by_absolute_region"
    relation = None
    confidence = "medium"

    pointed_ordinal = clause_mentions_pointed_category(snippet)
    if pointed_ordinal:
        return {
            "problem_type": "category_containing_pointed_dish",
            "anchor_id": f"category_containing_{pointed_ordinal}_pointed_dish",
            "anchor_zh": f"包含{ORDINAL_ZH.get(pointed_ordinal, pointed_ordinal)}指向菜品的菜单分类",
            "relation": "contains_pointed_dish",
            "confidence": "medium",
        }

    if "under the category" in text or "under the section" in text:
        problem_type = "menu_category_by_relative_anchor"
        relation = "below"
        if "dark background" in text:
            anchor_id = "below_dark_background_section"
            anchor_zh = "深色背景区域下方的菜单分类"
        else:
            anchor_id = "below_visible_anchor"
            anchor_zh = "指定可见锚点下方的菜单分类"
    elif "directly above" in text or "immediately above" in text:
        problem_type = "menu_category_by_relative_anchor"
        relation = "above"
        if "dark background" in text:
            anchor_id = "above_dark_background_section"
            anchor_zh = "深色背景白字区域正上方的菜单分类"
        elif "small supplementary" in text or "bottom-right" in text or "bottom right" in text or "homemade bread" in text:
            anchor_id = "above_bottom_right_small_section"
            anchor_zh = "右下角小型/补充区域正上方的菜单分类"
        elif "small hand" in text or "hand illustration" in text:
            anchor_id = "above_small_hand_illustration_section"
            anchor_zh = "小手图标区域正上方的菜单分类"
        else:
            anchor_id = "above_visible_anchor"
            anchor_zh = "指定可见锚点正上方的菜单分类"
    elif "directly below" in text or "immediately below" in text:
        problem_type = "menu_category_by_relative_anchor"
        relation = "below"
        if "appetizers and snacks" in text:
            anchor_id = "below_appetizers_and_snacks"
            anchor_zh = "Appetizers and Snacks 分类正下方的菜单分类"
        elif "small hand" in text or "hand illustration" in text:
            anchor_id = "below_small_hand_illustration_section"
            anchor_zh = "小手图标区域正下方的菜单分类"
        else:
            anchor_id = "below_visible_anchor"
            anchor_zh = "指定可见锚点正下方的菜单分类"
    elif "to the left of" in text:
        problem_type = "menu_category_by_relative_anchor"
        relation = "left_of"
        if "salad" in text and ("small hand" in text or "hand icon" in text or "hand illustration" in text):
            anchor_id = "left_of_salad_small_hand_section"
            anchor_zh = "带小手图标的 salad 区域左侧菜单分类"
        elif "small hand" in text or "hand illustration" in text:
            anchor_id = "left_of_small_hand_illustration_section"
            anchor_zh = "小手图标区域左侧菜单分类"
        else:
            anchor_id = "left_of_visible_anchor"
            anchor_zh = "指定可见锚点左侧菜单分类"
    elif "to the right of" in text:
        problem_type = "menu_category_by_relative_anchor"
        relation = "right_of"
        if "top" in text and ("middle panel" in text or "middle fold" in text):
            anchor_id = "right_of_top_middle_section"
            anchor_zh = "中间折页顶部区域右侧菜单分类"
        else:
            anchor_id = "right_of_visible_anchor"
            anchor_zh = "指定可见锚点右侧菜单分类"
    elif "middle of the far-right fold" in text or "middle of the rightmost fold" in text or "very middle of the rightmost fold" in text:
        anchor_id = "middle_right_fold_category"
        anchor_zh = "右侧折页正中菜单分类"
    elif ("middle category of the left" in text or "middle section of the left" in text or "middle of the left" in text or "middle position of the left" in text) and (
        "fold" in text or "page" in text or "panel" in text or "flap" in text
    ):
        anchor_id = "middle_left_fold_category"
        anchor_zh = "左侧折页/页面中部菜单分类"
    elif "white card" in text or "small card" in text:
        problem_type = "menu_category_by_visual_style"
        if "middle" in text and "left" in text:
            anchor_id = "middle_left_small_card"
            anchor_zh = "左侧中部小卡片区域的菜单分类"
        elif "top" in text and "left" in text:
            anchor_id = "top_left_independent_small_card"
            anchor_zh = "左上方独立小卡片区域的菜单分类"
        elif "dark green background" in text or "deep green background" in text:
            anchor_id = "dark_green_background_small_card"
            anchor_zh = "深绿色背景中的小卡片区域菜单分类"
        else:
            anchor_id = "small_card_section"
            anchor_zh = "小卡片区域的菜单分类"
    elif "dark background" in text or "dark green background" in text or "deep green background" in text:
        problem_type = "menu_category_by_visual_style"
        if "bottom right" in text or "bottom-right" in text:
            anchor_id = "bottom_right_dark_background_white_text"
            anchor_zh = "右下角深色背景区域的菜单分类"
        elif "right fold" in text or "right flap" in text or "right side" in text or "on the right" in text:
            anchor_id = "right_fold_dark_background_white_text"
            anchor_zh = "右侧折页深色背景区域的菜单分类"
        elif "left" in text:
            anchor_id = "left_dark_green_background_white_box"
            anchor_zh = "左侧深绿色背景区域的菜单分类"
        else:
            anchor_id = "dark_background_white_text_section"
            anchor_zh = "深色背景区域的菜单分类"
    elif "white rounded box" in text or "white rounded-box" in text or "white box" in text or "white-box" in text:
        problem_type = "menu_category_by_visual_style"
        ordinal_prefix = ""
        if "second" in text:
            ordinal_prefix = "second_"
            ordinal_zh = "第二个"
        elif "third" in text:
            ordinal_prefix = "third_"
            ordinal_zh = "第三个"
        elif "first" in text:
            ordinal_prefix = "first_"
            ordinal_zh = "第一个"
        else:
            ordinal_zh = ""
        if "top" in text and "left" in text:
            anchor_id = f"{ordinal_prefix}top_left_white_rounded_box"
            anchor_zh = f"左上方{ordinal_zh}白色圆角框区域的菜单分类"
        elif "bottom" in text and "left" in text:
            anchor_id = f"{ordinal_prefix}bottom_left_white_rounded_box"
            anchor_zh = f"左下方{ordinal_zh}白色圆角框区域的菜单分类"
        elif "left" in text:
            anchor_id = f"{ordinal_prefix}left_white_rounded_box"
            anchor_zh = f"左侧{ordinal_zh}白色圆角框区域的菜单分类"
        else:
            anchor_id = f"{ordinal_prefix}white_rounded_box"
            anchor_zh = f"{ordinal_zh}白色圆角框区域的菜单分类"
    elif "small hand" in text or "hand illustration" in text or "hand icon" in text:
        problem_type = "menu_category_by_visual_style"
        if ("right border" in text or "right side" in text) and ("middle fold" in text or "middle menu fold" in text):
            anchor_id = "middle_fold_right_border_small_hand"
            anchor_zh = "中间折页右边框带小手图标区域的菜单分类"
        elif ("left border" in text or "left side" in text) and ("right fold" in text or "right flap" in text or "right fold-out" in text):
            anchor_id = "right_fold_left_border_small_hand"
            anchor_zh = "右侧折页左边框带小手图标区域的菜单分类"
        elif "left" in text and ("middle fold" in text or "title" in text):
            anchor_id = "middle_fold_title_left_small_hand"
            anchor_zh = "中间折页标题左侧带小手图标区域的菜单分类"
        elif "right border" in text:
            anchor_id = "right_border_small_hand"
            anchor_zh = "右边框带小手图标区域的菜单分类"
        elif "left border" in text:
            anchor_id = "left_border_small_hand"
            anchor_zh = "左边框带小手图标区域的菜单分类"
        else:
            anchor_id = "small_hand_illustration_section"
            anchor_zh = "带小手图标区域的菜单分类"
    elif ("bottom right" in text or "bottom-right" in text) and (
        "small" in text or "smaller" in text or "supplementary" in text or "homemade bread" in text
    ):
        anchor_id = "bottom_right_small_supplementary_section"
        anchor_zh = "右下角小型/补充区域的菜单分类"
    elif "top" in text and "middle" in text and ("fold" in text or "page" in text or "panel" in text or "flap" in text):
        anchor_id = "top_middle_fold_category"
        anchor_zh = "中间折页顶部菜单分类"
    elif "bottom" in text and "middle" in text and ("fold" in text or "page" in text or "panel" in text or "flap" in text):
        anchor_id = "bottom_middle_fold_category"
        anchor_zh = "中间折页底部菜单分类"
    elif "middle" in text and ("middle fold" in text or "middle panel" in text or "middle page" in text or "middle flap" in text):
        anchor_id = "middle_middle_fold_category"
        anchor_zh = "中间折页正中菜单分类"
    elif "top" in text and "right" in text:
        anchor_id = "top_right_category"
        anchor_zh = "右上方菜单分类"
    elif "top" in text and "left" in text:
        if "small card" in text or "independent" in text:
            anchor_id = "top_left_independent_small_card"
            anchor_zh = "左上方独立小卡片区域的菜单分类"
        else:
            anchor_id = "top_left_category"
            anchor_zh = "左上方菜单分类"
    elif "bottom" in text and "right" in text:
        anchor_id = "bottom_right_category"
        anchor_zh = "右下方菜单分类"
    elif "bottom" in text and "left" in text:
        anchor_id = "bottom_left_category"
        anchor_zh = "左下方菜单分类"
    else:
        confidence = "low"

    return {
        "problem_type": problem_type,
        "anchor_id": anchor_id,
        "anchor_zh": anchor_zh,
        "relation": relation,
        "confidence": confidence,
    }


def category_target_kind(problem_type: str) -> str:
    if problem_type == "category_containing_pointed_dish":
        return "menu_catalog_or_category"
    return "menu_catalog_or_category"


def anchor_text_en(anchor: dict[str, Any]) -> str:
    anchor_id = anchor["anchor_id"]
    if anchor_id.startswith("category_containing_") and anchor_id.endswith("_pointed_dish"):
        ordinal = anchor_id.removeprefix("category_containing_").removesuffix("_pointed_dish")
        return f"menu category containing the {ORDINAL_EN.get(ordinal, ordinal)} pointed dish"
    if anchor_id.endswith("_pointed_dish"):
        ordinal = anchor_id.removesuffix("_pointed_dish")
        return f"{ORDINAL_EN.get(ordinal, ordinal)} pointed dish"
    return ANCHOR_EN_BY_ID.get(anchor_id, anchor_id.replace("_", " "))


def problem_question(problem: dict[str, Any]) -> str:
    video = problem["video_path"]
    menu = problem["menu_label"] or "active menu"
    if problem["problem_type"] == "pointed_dish_by_ordinal":
        ordinal_zh = ORDINAL_ZH.get(problem["ordinal"], problem["ordinal"])
        return f"识别视频 {video} 中 {menu} 上{ordinal_zh}指向的菜品名称。"
    if problem["problem_type"] == "dish_by_position_in_menu_region":
        anchor_zh = problem["visual_anchor"]["anchor_zh"]
        position_zh = problem["visual_anchor"]["position_zh"]
        return f"识别视频 {video} 中 {menu} 上“{anchor_zh}”里的{position_zh}菜品名称。"
    anchor_zh = problem["visual_anchor"]["anchor_zh"]
    return f"识别视频 {video} 中 {menu} 上“{anchor_zh}”对应的菜单 catalog/category。"


def problem_question_en(problem: dict[str, Any]) -> str:
    video = problem["video_path"]
    menu = problem["menu_label"] or "active_menu"
    if problem["problem_type"] == "pointed_dish_by_ordinal":
        ordinal = ORDINAL_EN.get(problem["ordinal"], problem["ordinal"])
        return f"Identify the dish name of the {ordinal} pointed item on {menu} in {video}."
    anchor = problem["visual_anchor"]["anchor_en"]
    if problem["problem_type"] == "dish_by_position_in_menu_region":
        position = problem["visual_anchor"]["position_id"]
        return f"Identify the dish name at position `{position}` inside `{anchor}` on {menu} in {video}."
    return f"Identify the menu catalog/category for `{anchor}` on {menu} in {video}."


def snippet_text(problem: dict[str, Any]) -> str:
    return " ".join(
        normalize_space(example.get("review_source_instruction_snippet") or "").lower()
        for example in problem.get("review_examples", [])
    )


def infer_anchor_region_from_text(anchor_id: str, text: str) -> dict[str, Any] | None:
    if "topmost category on the right flap" in text or "topmost category on the right fold" in text:
        return {"fold": "right", "vertical_position": "top", "region_role": "menu_category"}
    if "very top of the middle fold" in text or "top of the middle fold" in text:
        return {"fold": "middle", "vertical_position": "top", "region_role": "menu_category"}
    if "dark background section on the right fold" in text:
        return {
            "fold": "right",
            "vertical_position": "bottom",
            "region_role": "dark_background_category",
            "visual_style": "dark_background",
        }
    return ANCHOR_REGION_BY_ID.get(anchor_id)


def target_region_constraints_for_problem(problem: dict[str, Any]) -> dict[str, Any]:
    anchor_id = problem["visual_anchor"]["anchor_id"]
    problem_type = problem["problem_type"]
    text = snippet_text(problem)
    constraints: dict[str, Any] = {
        "target_role": "menu_category" if problem["target_kind"] == "menu_catalog_or_category" else problem["target_kind"],
    }

    if problem_type == "menu_category_by_relative_anchor":
        relation = problem["visual_anchor"].get("relation")
        constraints.update(
            {
                "relation": relation,
                "relation_axis": "vertical" if relation in {"above", "below"} else "horizontal",
                "adjacency": "direct",
                "same_fold": True,
                "same_column": relation in {"above", "below"},
                "do_not_return_anchor": True,
            }
        )

    if anchor_id in {"bottom_right_category", "bottom_right_small_supplementary_section"} and (
        "small section" in text or "smaller section" in text or "homemade bread" in text or "supplementary" in text
    ):
        constraints.update(
            {
                "fold": "right",
                "vertical_position": "bottom",
                "region_size": "small_supplementary",
                "region_role": "small_supplementary_title",
                "avoid_region_role": "main_category",
            }
        )

    if anchor_id == "dark_green_background_small_card":
        constraints.update(
            {
                "region_size": "small_card",
                "region_role": "small_card_category",
                "visual_style": "dark_green_background",
                "avoid_region_role": "large_section_header",
            }
        )
        if "second small card" in text or "middle of the deep green" in text or "middle of the dark green" in text:
            constraints["ordinal_within_region"] = "second"
            constraints["vertical_position"] = "middle"

    return constraints


def normalized_slots_for_problem(problem: dict[str, Any]) -> dict[str, Any]:
    if problem["problem_type"] == "pointed_dish_by_ordinal":
        return {
            "action": "pointing",
            "ordinal": problem["ordinal"],
            "sequence_scope": "stable pointing events on the specified menu, ordered by time",
            "pointing_resolution": {
                "primary_cue": "fingertip_or_contact_point",
                "selection_unit": "nearest_menu_text_row",
                "do_not_use": ["hand_body_overlap", "most_salient_text", "row_count_guess"],
            },
        }

    anchor_id = problem["visual_anchor"]["anchor_id"]
    slots: dict[str, Any] = {
        "anchor_id": anchor_id,
        "anchor_text": problem["visual_anchor"]["anchor_en"],
        "anchor_region": infer_anchor_region_from_text(anchor_id, snippet_text(problem)),
        "target_region_constraints": target_region_constraints_for_problem(problem),
    }
    relation = problem["visual_anchor"].get("relation")
    if relation is not None:
        slots["relation"] = relation
    if problem["problem_type"] == "dish_by_position_in_menu_region":
        slots["position"] = problem["visual_anchor"]["position_id"]
        slots["region_scope"] = "items inside the specified menu region"
    return {key: value for key, value in slots.items() if value is not None}


def observer_input_for_problem(problem: dict[str, Any]) -> dict[str, Any]:
    """Minimal fill-in style payload intended for the observer runtime."""

    base = {
        "schema_version": "observer_input_v1",
        "problem_id": problem["problem_id"],
        "video_path": problem["video_path"],
        "menu_label": problem["menu_label"],
        "task_type": problem["problem_type"],
        "target_kind": problem["target_kind"],
        "output_contract": {
            "event": {
                "time_range": "start/end seconds or null for static menu-region tasks",
                "region": "coarse visual region on the specified menu",
            },
            "detail": {
                "target_value": "single dish name or menu catalog/category label",
                "evidence": "visible text/region evidence only",
            },
        },
        "forbidden": [
            "raw user instruction",
            "database lookup",
            "tool call",
            "business condition evaluation",
            "final scenario value hint",
        ],
    }
    base["slots"] = normalized_slots_for_problem(problem)
    return base


def observer_task_for_problem(problem: dict[str, Any]) -> dict[str, Any]:
    if problem["problem_type"] == "pointed_dish_by_ordinal":
        return {
            "problem_id": problem["problem_id"],
            "event_mode": "temporal_sequence_event",
            "detail_mode": "entity_identity",
            "target_key": "dish_name",
            "target_kind": "menu_item",
            "action": "pointing",
            "ordinal": problem["ordinal"],
            "sequence_scope": "all distinct stable pointing events on the specified visible menu in time order",
            "spatial_scope": {
                "surface": "menu",
                "menu_label": problem["menu_label"],
                "region_terms": [],
                "relative_terms": [],
            },
            "forbidden": ["database facts", "tool calls", "business condition decisions"],
        }
    if problem["problem_type"] == "dish_by_position_in_menu_region":
        return {
            "problem_id": problem["problem_id"],
            "event_mode": problem["event_mode"],
            "detail_mode": "entity_identity",
            "target_key": "dish_name",
            "target_kind": "menu_item",
            "action": None,
            "ordinal": problem["visual_anchor"]["position_id"],
            "sequence_scope": "visible item order within the specified menu region",
            "spatial_scope": {
                "surface": "menu",
                "menu_label": problem["menu_label"],
                "anchor_id": problem["visual_anchor"]["anchor_id"],
                "anchor_zh": problem["visual_anchor"]["anchor_zh"],
                "position": problem["visual_anchor"]["position_id"],
            },
            "forbidden": ["database facts", "tool calls", "business condition decisions", "dish ranking/filtering"],
        }
    return {
        "problem_id": problem["problem_id"],
        "event_mode": problem["event_mode"],
        "detail_mode": "section_or_category_identity",
        "target_key": "menu_catalog_or_category",
        "target_kind": "menu_catalog_or_category",
        "action": None,
        "ordinal": None,
        "sequence_scope": None,
        "spatial_scope": {
            "surface": "menu",
            "menu_label": problem["menu_label"],
            "anchor_id": problem["visual_anchor"]["anchor_id"],
            "anchor_zh": problem["visual_anchor"]["anchor_zh"],
            "relation": problem["visual_anchor"].get("relation"),
        },
        "forbidden": ["database facts", "tool calls", "business condition decisions", "dish ranking/filtering"],
    }


def build_problem_record(
    *,
    group_key: tuple[Any, ...],
    requests: list[dict[str, Any]],
    task_context_by_id: dict[int, dict[str, Any]],
    problem_index: int,
) -> dict[str, Any]:
    first = requests[0]
    task_context = task_context_by_id[first["task_id"]]
    problem_type = group_key[0]
    problem: dict[str, Any] = {
        "problem_id": f"order1_problem_{problem_index:04d}",
        "scenario_key": first["scenario_key"],
        "video_path": first["image_path"],
        "menu_label": task_context["menu_label"],
        "active_restaurant": task_context["active_restaurant"],
        "problem_type": problem_type,
        "target_kind": "dish_name" if problem_type in {"pointed_dish_by_ordinal", "dish_by_position_in_menu_region"} else "menu_catalog_or_category",
        "event_mode": first["event_mode"],
        "detail_mode": "entity_identity" if problem_type in {"pointed_dish_by_ordinal", "dish_by_position_in_menu_region"} else "section_or_category_identity",
        "source_request_ids": [request["request_id"] for request in requests],
        "source_task_ids": sorted({request["task_id"] for request in requests}),
        "review_examples": [
            {
                "request_id": request["request_id"],
                "task_id": request["task_id"],
                "review_source_instruction_snippet": request["review_source_instruction_snippet"],
            }
            for request in requests[:5]
        ],
        "event_gt": {
            "gt_status": "pending_video_inspection",
            "expected_time_range": None,
            "primary_content_range": None,
            "allowed_transition_range": None,
            "expected_region": None,
        },
        "detail_gt": {
            "gt_status": "pending_video_inspection",
            "target_value": None,
            "acceptable_aliases": [],
            "negative_neighbors": [],
        },
        "needs_human_review": True,
    }

    if problem_type == "pointed_dish_by_ordinal":
        problem["ordinal"] = first["ordinal"]
        problem["visual_anchor"] = {
            "anchor_id": f"{first['ordinal']}_pointed_dish",
            "anchor_zh": f"{ORDINAL_ZH.get(first['ordinal'], first['ordinal'])}指向的菜品",
            "relation": "pointing_sequence",
        }
    elif problem_type == "dish_by_position_in_menu_region":
        anchor = dict(group_key[3])
        problem["ordinal"] = anchor["position_id"]
        problem["visual_anchor"] = anchor
    else:
        problem["visual_anchor"] = group_key[3]
        problem["ordinal"] = None

    problem["visual_anchor"]["anchor_en"] = anchor_text_en(problem["visual_anchor"])
    problem["question_en"] = problem_question_en(problem)
    problem["question_zh"] = problem_question(problem)
    problem["observer_input"] = observer_input_for_problem(problem)
    problem["observer_task"] = observer_task_for_problem(problem)
    return problem


def collect_task_context(tasks: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    contexts: dict[int, dict[str, Any]] = {}
    for idx, task in enumerate(tasks, start=1):
        active_restaurant = infer_active_restaurant(task)
        video_path = task.get("image_path")
        contexts[idx] = {
            "task_id": idx,
            "active_restaurant": active_restaurant,
            "menu_label": infer_menu_label(video_path, active_restaurant),
            "video_path": video_path,
        }
    return contexts


def collect_candidate_requests(scenario_key: str, tasks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, dict[str, Any]]]:
    contexts = collect_task_context(tasks)
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for idx, task in enumerate(tasks, start=1):
        for request in normalize_visual_requests(scenario_key=scenario_key, task_id=idx, task=task):
            context = contexts[idx]
            request["active_restaurant"] = context["active_restaurant"]
            request["resolved_menu_label"] = context["menu_label"]
            skip_reason = None
            if not context["menu_label"]:
                skip_reason = "unresolved_active_menu_label"
            elif is_false_visual_request(request):
                skip_reason = "false_visual_or_business_comparison"
            elif should_rescue_as_category_request(request):
                request["target_key"] = "category"
                request["target_kind"] = category_target_kind("menu_category_by_absolute_region")
                request["detail_mode"] = "section_or_category_identity"
            elif not (is_pointed_dish_problem(request) or is_category_request(request) or is_region_dish_problem(request)):
                skip_reason = "unsupported_or_non_observer_problem"
            if skip_reason:
                skipped.append(
                    {
                        "request_id": request["request_id"],
                        "task_id": idx,
                        "skip_reason": skip_reason,
                        "event_mode": request["event_mode"],
                        "target_key": request["target_key"],
                        "review_source_instruction_snippet": request["review_source_instruction_snippet"],
                    }
                )
            else:
                kept.append(request)
    return kept, skipped, contexts


def build_problem_groups(requests: list[dict[str, Any]], contexts: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for request in requests:
        context = contexts[request["task_id"]]
        if is_pointed_dish_problem(request):
            key = (
                "pointed_dish_by_ordinal",
                request["image_path"],
                context["menu_label"],
                request["ordinal"],
            )
        elif is_region_dish_problem(request):
            anchor = canonical_anchor_from_clause(request["review_source_instruction_snippet"])
            position_id, position_zh = extract_region_dish_position(request["review_source_instruction_snippet"]) or ("unknown", "指定位置")
            anchor = {
                **anchor,
                "position_id": position_id,
                "position_zh": position_zh,
            }
            key = (
                "dish_by_position_in_menu_region",
                request["image_path"],
                context["menu_label"],
                tuple(sorted(anchor.items())),
            )
        else:
            anchor = canonical_anchor_from_clause(request["review_source_instruction_snippet"])
            key = (
                anchor["problem_type"],
                request["image_path"],
                context["menu_label"],
                tuple(sorted(anchor.items())),
            )
        grouped[key].append(request)

    problems: list[dict[str, Any]] = []
    for idx, (key, group_requests) in enumerate(
        sorted(grouped.items(), key=lambda item: (str(item[0][0]), str(item[0][1]), str(item[0][2]), str(item[0][3]))),
        start=1,
    ):
        if key[0] != "pointed_dish_by_ordinal":
            anchor = dict(key[3])
            problem_key = (key[0], key[1], key[2], anchor)
        else:
            problem_key = key
        problems.append(
            build_problem_record(
                group_key=problem_key,
                requests=group_requests,
                task_context_by_id=contexts,
                problem_index=idx,
            )
        )
    return problems


def summarize(problems: list[dict[str, Any]], skipped: list[dict[str, Any]], output_dir: Path, scenario_key: str) -> str:
    by_type = Counter(problem["problem_type"] for problem in problems)
    by_video_menu = Counter((problem["video_path"], problem["menu_label"]) for problem in problems)
    by_target = Counter(problem["target_kind"] for problem in problems)
    skipped_by_reason = Counter(item["skip_reason"] for item in skipped)
    lines = [
        "# Observer Problem Set Draft Summary",
        "",
        f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Scenario: `{scenario_key}`",
        "",
        "This is a pre-GT observer evaluation problem set. It is derived from",
        "scenario instructions but grouped by reusable visual recognition tasks.",
        "Event/detail grounding fields are empty until video inspection.",
        "",
        "## Outputs",
        "",
        f"- `observer_problem_set_draft.json`: {len(problems)} problem instances",
        f"- `observer_inputs.jsonl`: {len(problems)} observer-facing normalized inputs",
        f"- `observer_problem_type_summary.json`: {len(by_type)} problem types",
        f"- `skipped_visual_request_candidates.json`: {len(skipped)} skipped candidates",
        "",
        "## Counts By Problem Type",
        "",
    ]
    for key, count in by_type.most_common():
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Counts By Target Kind", ""])
    for key, count in by_target.most_common():
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Counts By Video/Menu", ""])
    for (video, menu), count in sorted(by_video_menu.items()):
        lines.append(f"- `{video}` / `{menu}`: {count}")
    lines.extend(["", "## Skipped Candidate Reasons", ""])
    for key, count in skipped_by_reason.most_common():
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Example Problems", ""])
    for problem in problems[:20]:
        lines.append(f"- `{problem['problem_id']}` `{problem['problem_type']}`: {problem['question_zh']}")
    lines.extend(
        [
            "",
            "## Review Notes",
            "",
            "- This draft resolves active order menus to concrete `menu_1`/`menu_2` labels.",
            "- `review_examples` keep traceability to original tasks but are not observer prompts.",
            "- `menu_catalog_or_category` is used for menu section/catalog targets rather than final dish values.",
            "- Known limitation: canonical visual anchors are rule-based and should be reviewed before GT filling.",
            "",
        ]
    )
    return "\n".join(lines)


def problem_type_summary(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for problem in problems:
        group = grouped.setdefault(
            problem["problem_type"],
            {
                "problem_type": problem["problem_type"],
                "count": 0,
                "target_kinds": [],
                "problem_ids": [],
                "examples": [],
            },
        )
        group["count"] += 1
        if problem["target_kind"] not in group["target_kinds"]:
            group["target_kinds"].append(problem["target_kind"])
        group["problem_ids"].append(problem["problem_id"])
        if len(group["examples"]) < 5:
            group["examples"].append(
                {
                    "problem_id": problem["problem_id"],
                    "question_en": problem["question_en"],
                    "question_zh": problem["question_zh"],
                    "video_path": problem["video_path"],
                    "menu_label": problem["menu_label"],
                    "visual_anchor": problem["visual_anchor"],
                }
            )
    return sorted(grouped.values(), key=lambda item: (-item["count"], item["problem_type"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario_key", default="order1")
    parser.add_argument("--output_dir", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tasks = load_scenario_tasks(args.scenario_key)
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / f"observer_problem_set_{args.scenario_key}")
    requests, skipped, contexts = collect_candidate_requests(args.scenario_key, tasks)
    problems = build_problem_groups(requests, contexts)
    summary = summarize(problems, skipped, output_dir, args.scenario_key)

    write_json(output_dir / "observer_problem_set_draft.json", problems)
    write_jsonl(output_dir / "observer_inputs.jsonl", [problem["observer_input"] for problem in problems])
    write_json(output_dir / "observer_problem_type_summary.json", problem_type_summary(problems))
    write_json(output_dir / "skipped_visual_request_candidates.json", skipped)
    (output_dir / "summary.md").write_text(summary, encoding="utf-8")

    print(f"output_dir={output_dir}")
    print(f"scenario_key={args.scenario_key}")
    print(f"problem_instances={len(problems)}")
    print(f"problem_types={len(problem_type_summary(problems))}")
    print(f"skipped_candidates={len(skipped)}")


if __name__ == "__main__":
    main()
