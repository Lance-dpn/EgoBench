"""Normalize EgoBench visual requests into reviewable structured records.

This module intentionally avoids reading videos or using scenario key/value as
detail GT. It extracts likely visual referents from task instructions so the
next stage can bootstrap event/detail GT by video inspection.
"""

from __future__ import annotations

import re
from typing import Any


ORDINAL_PATTERN = re.compile(
    r"\b(first|second|third|fourth|fifth|sixth|last|final)\b",
    re.IGNORECASE,
)

VISUAL_CUE_PATTERN = re.compile(
    r"\b(point(?:ed|ing)?|look(?:ed|ing)?|visible|shown|labeled|label|mark(?:ed)?|"
    r"hold(?:ing)?|held|pick(?:ed|ing)?|put down|place(?:d)?|sprinkl(?:e|ing)|"
    r"pour(?:ed|ing)?|cut(?:ting)?|slic(?:e|ing)|boil(?:ing)?|simmer(?:ing)?|"
    r"stir[- ]?fry(?:ing)?|cook(?:ing)?|serve(?:d)?|menu|section|category|"
    r"fold(?:out)?|page|shelf|row|column|left|right|top|bottom|middle|corner|"
    r"border|card|box|package|bottle|wine|cheese|cookie|dish|ingredient|recipe|"
    r"tray|pot|pan|wok|cutting board|table|plate|region|area)\b",
    re.IGNORECASE,
)

NON_VISUAL_ACTION_PATTERN = re.compile(
    r"\b(price|tax|discount|nutrition|calorie|protein|sodium|sugar|fat|fiber|"
    r"carbohydrate|allergen|country|origin|cart|order|shopping list|calculate|"
    r"compute|total|add|remove|highest|lowest|cheapest|expensive)\b",
    re.IGNORECASE,
)

POINTING_PATTERN = re.compile(r"\bpoint(?:ed|ing)?\b|\bpoint at\b", re.IGNORECASE)
ACTION_PATTERN = re.compile(
    r"\b(hold(?:ing)?|held|pick(?:ed|ing)?|put down|place(?:d)?|sprinkl(?:e|ing)|"
    r"pour(?:ed|ing)?|cut(?:ting)?|slic(?:e|ing)|boil(?:ing)?|simmer(?:ing)?|"
    r"stir[- ]?fry(?:ing)?|cook(?:ing)?|serve(?:d)?)\b",
    re.IGNORECASE,
)
TEXT_PATTERN = re.compile(r"\b(label|labeled|mark(?:ed)?|text|title|sign|shown|visible)\b", re.IGNORECASE)
REGION_PATTERN = re.compile(
    r"\b(left|right|top|bottom|middle|corner|border|fold(?:out)?|page|panel|"
    r"section|category|shelf|row|column|area|region|side)\b",
    re.IGNORECASE,
)
GEOMETRY_PATTERN = re.compile(
    r"\b(left|right(?!\s+now)|top|bottom|middle|corner|border|fold(?:out)?|page|panel|"
    r"shelf|row|column|area|region|side|tray|pot|pan|wok|cutting board|table|plate)\b",
    re.IGNORECASE,
)
RELATIVE_PATTERN = re.compile(r"\b(to the left of|to the right of|next to|under|below|above|beside)\b", re.IGNORECASE)
APPEARANCE_PATTERN = re.compile(
    r"\b(red|green|blue|yellow|brown|dark|white|black|orange|light|small|large|"
    r"rectangular|round|diamond|plaid|pattern|background|illustration|sticker|wrapper)\b",
    re.IGNORECASE,
)

TARGET_KEY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("product_name", re.compile(r"\b(product|item|box|package|bottle|wine|cheese|cookie)\b", re.I)),
    ("dish_name", re.compile(r"\b(dish|menu item|food)\b", re.I)),
    ("recipe_name", re.compile(r"\b(recipe|dish you are cooking|currently cooking|dish corresponds)\b", re.I)),
    ("ingredient_name", re.compile(r"\b(ingredient|powder|vegetable|meat|seasoning)\b", re.I)),
    ("set_meal_name", re.compile(r"\b(set meal|set)\b", re.I)),
    ("category", re.compile(r"\b(category|section)\b", re.I)),
]

TARGET_KIND_BY_KEY = {
    "product_name": "product",
    "dish_name": "menu_item",
    "recipe_name": "recipe",
    "ingredient_name": "ingredient",
    "category": "category_or_section",
    "set_meal_name": "set_meal",
}


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def split_instruction(instruction: str) -> list[str]:
    """Split an instruction into review-sized clauses."""

    text = normalize_space(instruction)
    if not text:
        return []
    rough_parts = re.split(
        r"(?<=[.!?])\s+|;\s+|\b(?:Then|Next|Finally|Subsequently|Otherwise|If so|If not),?\s+",
        text,
        flags=re.IGNORECASE,
    )
    clauses: list[str] = []
    for part in rough_parts:
        part = normalize_space(part)
        if not part:
            continue
        subparts = re.split(r",\s+(?=(?:ask|check|find|select|determine|identify|confirm|look|focus)\b)", part, flags=re.I)
        for sub in subparts:
            sub = normalize_space(sub)
            if len(sub) >= 12:
                clauses.append(sub)
    return clauses


def keep_visual_clause(text: str) -> bool:
    if not VISUAL_CUE_PATTERN.search(text):
        return False
    lowered = text.lower()
    if re.search(r"\bplace (?:an? |the )?order\b", lowered) or "cutting phase" in lowered:
        return False
    if re.search(r"\b(select|choose|recommend).{0,80}\brestaurant\b", lowered):
        return False
    if re.search(
        r"\b(opened|look(?:ed)? at|check(?:ed)?|review(?:ed)?|viewed|compared|taken out|show)\b.{0,120}\bmenus?\b",
        lowered,
    ) and not lowered.startswith(("ask", "have the ai", "please ask")):
        return False
    if "cooking student" in lowered:
        return False
    if re.search(r"\b(menu \d+\s+is|menus? from two restaurants|menus? are labeled|show .*menus? from)\b", lowered):
        return False
    if POINTING_PATTERN.search(text) and not ORDINAL_PATTERN.search(text) and re.search(
        r"\b(three|two|several|\d+) .{0,80}\b(dishes|items|products|sequence|sequentially)\b",
        lowered,
    ):
        return False
    if "instead of cooking" in lowered:
        return False
    physical_visual = bool(
        POINTING_PATTERN.search(text)
        or ACTION_PATTERN.search(text)
        or GEOMETRY_PATTERN.search(text)
        or RELATIVE_PATTERN.search(text)
        or APPEARANCE_PATTERN.search(text)
    )
    strong_visual = bool(
        physical_visual
        or TEXT_PATTERN.search(text)
    )
    if re.search(
        r"\b(find|search|filter|select|list|add|remove|calculate|compute)\b",
        text,
        re.IGNORECASE,
    ) and re.search(
        r"\b(all|database|catalog|shopping list|cart|order|current menu|currently in the menu)\b",
        text,
        re.IGNORECASE,
    ) and not physical_visual:
        return False
    if (
        not physical_visual
        and re.search(r"\b(label(?:ed)?|feature|allergen|nutrition|gluten|low[-_ ]?sugar|low[-_ ]?sodium|low[-_ ]?calorie)\b", text, re.I)
    ):
        return False
    if not strong_visual:
        return False
    return True


def infer_pattern(text: str) -> str:
    has_ordinal = bool(ORDINAL_PATTERN.search(text))
    has_pointing = bool(POINTING_PATTERN.search(text))
    has_action = bool(ACTION_PATTERN.search(text))
    if has_ordinal and has_pointing:
        return "temporal_ordinal_pointing"
    if has_ordinal and has_action:
        return "temporal_ordinal_action"
    if has_pointing:
        return "single_pointing"
    if RELATIVE_PATTERN.search(text):
        return "relative_anchor"
    if TEXT_PATTERN.search(text):
        return "visible_text_or_label"
    if has_action:
        return "object_action_state"
    if re.search(r"\b(recipe|corresponds to|belongs to|based on)\b", text, re.I):
        return "composite_scene_identity"
    if re.search(r"\b(menu|section|category|fold|page)\b", text, re.I):
        return "menu_section_or_category"
    if REGION_PATTERN.search(text):
        return "spatial_region"
    return "spatial_region"


def infer_target_key(text: str, scenario: str, fallback_key: str | None) -> str:
    # Prefer explicit section/category requests over a task-level dish/product key.
    if re.search(r"\b(section|category)\b", text, re.I):
        return "category"
    for key, pattern in TARGET_KEY_PATTERNS:
        if pattern.search(text):
            if scenario == "order" and key == "product_name":
                return "dish_name"
            if scenario.startswith("retail") and key == "dish_name":
                return "product_name"
            return key
    if fallback_key:
        return str(fallback_key)
    return "visible_region"


def extract_ordinal(text: str) -> str | None:
    match = ORDINAL_PATTERN.search(text)
    return match.group(1).lower() if match else None


def extract_action(text: str) -> str | None:
    if POINTING_PATTERN.search(text):
        return "pointing"
    match = ACTION_PATTERN.search(text)
    return normalize_space(match.group(1).lower()) if match else None


def extract_scope_terms(text: str, pattern: re.Pattern[str]) -> list[str]:
    values: list[str] = []
    for match in pattern.finditer(text):
        value = normalize_space(match.group(0).lower())
        if value not in values:
            values.append(value)
    return values


def confidence_for_clause(text: str, pattern: str) -> str:
    if pattern in {"temporal_ordinal_pointing", "single_pointing"}:
        return "high"
    if REGION_PATTERN.search(text) or ACTION_PATTERN.search(text):
        return "medium"
    return "low"


def infer_menu_scope(text: str, instruction: str, scenario: str) -> dict[str, Any] | None:
    if scenario != "order":
        return None
    lowered = text.lower()
    instruction_lower = instruction.lower()
    explicit_label = None
    if re.search(r"\b(menu\s*1|first menu)\b", lowered):
        explicit_label = "menu_1"
    elif re.search(r"\b(menu\s*2|second menu)\b", lowered):
        explicit_label = "menu_2"

    if explicit_label:
        scope_type = "explicit_menu_label"
        requires_service_menu_resolution = False
    elif "once the restaurant is selected" in instruction_lower or "chosen restaurant" in instruction_lower:
        scope_type = "active_selected_menu"
        requires_service_menu_resolution = True
    else:
        scope_type = "visible_two_menu_context"
        requires_service_menu_resolution = True

    return {
        "scope_type": scope_type,
        "menu_label": explicit_label,
        "candidate_visible_menus": ["menu_1", "menu_2"],
        "requires_service_menu_resolution": requires_service_menu_resolution,
        "observer_instruction": (
            "Use menu labels or the active menu resolved by service state; do not pass restaurant names to observer."
        ),
    }


def infer_event_mode(pattern: str) -> str:
    if pattern in {"temporal_ordinal_pointing", "temporal_ordinal_action"}:
        return "temporal_sequence_event"
    if pattern == "single_pointing":
        return "single_pointing_event"
    if pattern == "relative_anchor":
        return "relative_spatial_region"
    if pattern in {"spatial_region", "menu_section_or_category", "visible_text_or_label"}:
        return "static_spatial_region"
    if pattern == "object_action_state":
        return "object_action_state"
    if pattern == "composite_scene_identity":
        return "composite_scene_context"
    return "static_spatial_region"


def infer_detail_mode(target_key: str, pattern: str) -> str:
    if target_key in {"dish_name", "product_name", "ingredient_name", "set_meal_name"}:
        return "entity_identity"
    if target_key == "recipe_name":
        return "composite_identity"
    if target_key == "category":
        return "section_or_category_identity"
    if pattern == "visible_text_or_label":
        return "visible_text"
    return "visible_region_description"


def build_observer_task(
    *,
    request_id: str,
    event_mode: str,
    detail_mode: str,
    target_key: str,
    target_kind: str,
    action: str | None,
    ordinal: str | None,
    sequence_scope: str | None,
    spatial_scope: dict[str, Any],
    appearance_constraints: list[str],
    visible_text_constraints: list[str],
    menu_scope: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the observer-facing request without exposing business text."""

    return {
        "request_id": request_id,
        "event_mode": event_mode,
        "detail_mode": detail_mode,
        "target_key": target_key,
        "target_kind": target_kind,
        "action": action,
        "ordinal": ordinal,
        "sequence_scope": sequence_scope,
        "spatial_scope": spatial_scope,
        "appearance_constraints": appearance_constraints,
        "visible_text_constraints": visible_text_constraints,
        "menu_scope": menu_scope,
        "forbidden": [
            "database facts",
            "ranking decisions",
            "price/nutrition/tax calculations",
            "state mutation actions",
            "restaurant names unless they are visibly printed text",
        ],
    }


def build_abstract_task_key(
    *,
    event_mode: str,
    detail_mode: str,
    target_key: str,
    action: str | None,
    ordinal: str | None,
    spatial_scope: dict[str, Any],
    appearance_constraints: list[str],
    visible_text_constraints: list[str],
    menu_scope: dict[str, Any] | None,
) -> str:
    parts = [event_mode, detail_mode, f"target={target_key}"]
    if action:
        parts.append(f"action={action}")
    if ordinal:
        parts.append(f"ordinal={ordinal}")
    region_terms = spatial_scope.get("region_terms") or []
    relative_terms = spatial_scope.get("relative_terms") or []
    if region_terms:
        parts.append("region=" + "+".join(sorted(region_terms)))
    if relative_terms:
        parts.append("relative=" + "+".join(sorted(relative_terms)))
    if appearance_constraints:
        parts.append("appearance=" + "+".join(sorted(appearance_constraints)))
    if visible_text_constraints:
        parts.append("text=" + "+".join(sorted(v.lower() for v in visible_text_constraints)))
    if menu_scope and menu_scope.get("scope_type"):
        parts.append(f"menu_scope={menu_scope['scope_type']}")
        if menu_scope.get("menu_label"):
            parts.append(f"menu={menu_scope['menu_label']}")
    return "|".join(parts)


def bucket_region(spatial_scope: dict[str, Any]) -> str | None:
    terms = set(spatial_scope.get("region_terms") or [])
    if not terms:
        return None
    positional = [term for term in ("top", "bottom", "left", "right", "middle") if term in terms]
    structural = [term for term in ("corner", "border", "fold", "page") if term in terms]
    values: list[str] = []
    if positional:
        values.extend(positional)
    if structural:
        values.extend(structural)
    return "+".join(values) if values else None


def bucket_appearance(appearance_constraints: list[str]) -> str | None:
    terms = set(appearance_constraints)
    buckets: list[str] = []
    if "illustration" in terms:
        buckets.append("illustration")
    if "dark" in terms or "background" in terms:
        buckets.append("dark_background")
    if "white" in terms:
        buckets.append("white_box_or_text")
    if "small" in terms:
        buckets.append("small")
    if not buckets and terms:
        buckets.extend(sorted(terms))
    return "+".join(buckets) if buckets else None


def build_visual_task_group_key(
    *,
    event_mode: str,
    detail_mode: str,
    target_key: str,
    action: str | None,
    ordinal: str | None,
    spatial_scope: dict[str, Any],
    appearance_constraints: list[str],
    menu_scope: dict[str, Any] | None,
) -> str:
    """Coarse grouping by the visual recognition problem, not the full task text."""

    parts = [event_mode, detail_mode, f"target={target_key}"]
    if event_mode == "temporal_sequence_event":
        parts.append(f"action={action or 'event'}")
        parts.append(f"ordinal={ordinal or 'unspecified'}")
    elif event_mode == "single_pointing_event":
        parts.append(f"action={action or 'pointing'}")
    else:
        region_bucket = bucket_region(spatial_scope)
        if region_bucket:
            parts.append(f"region_bucket={region_bucket}")
        relative_terms = spatial_scope.get("relative_terms") or []
        if relative_terms:
            parts.append("relative=" + "+".join(sorted(relative_terms)))
        appearance_bucket = bucket_appearance(appearance_constraints)
        if appearance_bucket:
            parts.append(f"appearance_bucket={appearance_bucket}")
        if action:
            parts.append(f"action={action}")
    if menu_scope and menu_scope.get("scope_type"):
        parts.append(f"menu_scope={menu_scope['scope_type']}")
    return "|".join(parts)


def normalize_visual_requests(
    *,
    scenario_key: str,
    task_id: int,
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return normalized visual request candidates for one scenario task."""

    scenario = re.sub(r"\d+$", "", scenario_key)
    instruction = task.get("Instruction", "")
    clauses = [clause for clause in split_instruction(instruction) if keep_visual_clause(clause)]
    if not clauses:
        fallback = normalize_space(task.get("image_description") or instruction)
        clauses = [fallback] if fallback else []

    requests: list[dict[str, Any]] = []
    seen: set[str] = set()
    for clause in clauses:
        normalized_clause = clause.lower()
        if normalized_clause in seen:
            continue
        seen.add(normalized_clause)

        pattern = infer_pattern(clause)
        target_key = infer_target_key(clause, scenario, task.get("key"))
        ordinal = extract_ordinal(clause)
        action = extract_action(clause)
        idx = len(requests) + 1
        request_id = f"{scenario_key}_task{task_id}_v{idx}"
        event_mode = infer_event_mode(pattern)
        detail_mode = infer_detail_mode(target_key, pattern)
        sequence_scope = (
            "all distinct stable events matching the action in visible time order"
            if pattern.startswith("temporal_ordinal")
            else None
        )
        spatial_scope = {
            "surface": infer_surface(clause, scenario),
            "region_terms": extract_scope_terms(clause, REGION_PATTERN),
            "relative_terms": extract_scope_terms(clause, RELATIVE_PATTERN),
        }
        appearance_constraints = extract_scope_terms(clause, APPEARANCE_PATTERN)
        visible_text_constraints = extract_visible_text_constraints(clause)
        menu_scope = infer_menu_scope(clause, instruction, scenario)
        observer_task = build_observer_task(
            request_id=request_id,
            event_mode=event_mode,
            detail_mode=detail_mode,
            target_key=target_key,
            target_kind=TARGET_KIND_BY_KEY.get(target_key, "visible_anchor"),
            action=action,
            ordinal=ordinal,
            sequence_scope=sequence_scope,
            spatial_scope=spatial_scope,
            appearance_constraints=appearance_constraints,
            visible_text_constraints=visible_text_constraints,
            menu_scope=menu_scope,
        )
        abstract_task_key = build_abstract_task_key(
            event_mode=event_mode,
            detail_mode=detail_mode,
            target_key=target_key,
            action=action,
            ordinal=ordinal,
            spatial_scope=spatial_scope,
            appearance_constraints=appearance_constraints,
            visible_text_constraints=visible_text_constraints,
            menu_scope=menu_scope,
        )
        visual_task_group_key = build_visual_task_group_key(
            event_mode=event_mode,
            detail_mode=detail_mode,
            target_key=target_key,
            action=action,
            ordinal=ordinal,
            spatial_scope=spatial_scope,
            appearance_constraints=appearance_constraints,
            menu_scope=menu_scope,
        )
        requests.append(
            {
                "request_id": request_id,
                "scenario": scenario,
                "scenario_key": scenario_key,
                "task_id": task_id,
                "pattern": pattern,
                "event_mode": event_mode,
                "target_key": target_key,
                "target_kind": TARGET_KIND_BY_KEY.get(target_key, "visible_anchor"),
                "detail_mode": detail_mode,
                "action": action,
                "ordinal": ordinal,
                "sequence_scope": sequence_scope,
                "spatial_scope": spatial_scope,
                "appearance_constraints": appearance_constraints,
                "visible_text_constraints": visible_text_constraints,
                "menu_scope": menu_scope,
                "observer_task": observer_task,
                "abstract_task_key": abstract_task_key,
                "visual_task_group_key": visual_task_group_key,
                "detail_goal": build_detail_goal(target_key, clause),
                "review_source_instruction_snippet": clause,
                "image_path": task.get("image_path"),
                "image_description": task.get("image_description"),
                "extraction_confidence": confidence_for_clause(clause, pattern),
                "needs_review": True,
                "forbidden": [
                    "database facts",
                    "ranking decisions",
                    "price/nutrition/tax calculations",
                    "state mutation actions",
                ],
            }
        )
    return requests


def infer_surface(text: str, scenario: str) -> str | None:
    lowered = text.lower()
    if "menu" in lowered or scenario in {"order", "restaurant"}:
        return "menu"
    if "shelf" in lowered or scenario == "retail":
        return "shelf"
    if any(word in lowered for word in ["tray", "pot", "pan", "wok", "cutting board", "plate"]):
        return "kitchen_workspace"
    if scenario == "kitchen":
        return "kitchen_workspace"
    return None


def extract_visible_text_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    for match in re.finditer(r'"([^"]+)"|\'([^\']+)\'', text):
        value = normalize_space(match.group(1) or match.group(2))
        context = text[max(0, match.start() - 50) : match.end() + 50]
        if not re.search(r"\b(label(?:ed)?|mark(?:ed)?|text|printed|reads?|sign|title)\b", context, re.I):
            continue
        if re.search(
            r"\b(feature|allergen|nutrition|contains?|has|have|low[-_ ]?sugar|low[-_ ]?sodium|low[-_ ]?calorie|gluten)\b",
            context,
            re.I,
        ):
            continue
        if value and value not in constraints:
            constraints.append(value)
    return constraints


def build_detail_goal(target_key: str, text: str) -> str:
    if target_key == "category":
        return "read or identify the visible section/category anchored by the localized event or region"
    if target_key == "visible_region":
        return "describe the localized visible region without database facts"
    return f"read the single {target_key} anchored by the localized event or region"


def build_event_gt_template(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": request["request_id"],
        "gt_status": "pending_video_inspection",
        "gt_version": None,
        "scenario_key": request["scenario_key"],
        "task_id": request["task_id"],
        "video_path": request.get("image_path"),
        "pattern": request["pattern"],
        "event_mode": request["event_mode"],
        "event_type": request.get("action") or request["pattern"],
        "ordinal": request.get("ordinal"),
        "expected_time_range": None,
        "primary_content_range": None,
        "allowed_transition_range": None,
        "expected_region": {
            "coarse": None,
            "target_relation": None,
            "review_hint": request.get("review_source_instruction_snippet"),
        },
        "candidate_sequence": [],
        "confidence": None,
        "needs_human_review": True,
        "notes": "Template only. Fill after video/frame inspection.",
    }


def build_detail_gt_template(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": request["request_id"],
        "gt_status": "pending_video_inspection",
        "gt_version": None,
        "scenario_key": request["scenario_key"],
        "task_id": request["task_id"],
        "target_key": request["target_key"],
        "target_kind": request["target_kind"],
        "detail_mode": request["detail_mode"],
        "target_value": None,
        "acceptable_aliases": [],
        "visible_text_expected": [],
        "negative_neighbors": [],
        "region_dependency": "use event GT region; do not read neighboring/background anchors",
        "confidence": None,
        "needs_human_review": True,
        "notes": "Template only. Fill after video/frame inspection; final scenario value is not used as detail GT.",
    }
