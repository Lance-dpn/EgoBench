#!/usr/bin/env python3
"""Clean visual observer dataset rebuild from scenario instructions only.

This builder deliberately does not read older observer_problem_set_* folders,
older bootstrap files, eval outputs, DB files, or official final values. It
implements the instruction -> raw visual problem -> visual_query_v1 -> cluster
part of eval-process.md and leaves GT as pending video annotation.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = ROOT / "scenarios/final"
OUT_ROOT = ROOT / "experiments/visual_observer_runner/eval/observer_dataset_clean_v2"

SCENARIOS = ("order", "retail", "restaurant", "kitchen")
ORDINALS = ("second-to-last", "first", "second", "third", "fourth", "fifth", "sixth", "last")

VISUAL_TERMS = (
    "point",
    "pointing",
    "pointed",
    "finger",
    "menu",
    "dish",
    "category",
    "section",
    "fold",
    "page",
    "panel",
    "card",
    "box",
    "area",
    "bottle",
    "wine",
    "shelf",
    "label",
    "capsule",
    "cap",
    "picked",
    "pick",
    "put back",
    "holding",
    "held",
    "ingredient",
    "recipe",
    "tray",
    "pot",
    "wok",
    "cutting board",
    "sprinkling",
    "pouring",
    "cutting",
    "cooking",
    "served",
    "plate",
    "left",
    "right",
    "top",
    "bottom",
    "middle",
    "above",
    "below",
)

BUSINESS_TERMS = (
    "price",
    "discount",
    "tax",
    "protein",
    "calorie",
    "nutrition",
    "nutritional",
    "allergen",
    "allergy",
    "sodium",
    "sugar",
    "fat",
    "fiber",
    "stock",
    "inventory",
    "cart",
    "order",
    "shopping list",
    "menu.",
    "add",
    "lowest",
    "highest",
    "cheapest",
    "recommend",
    "search",
    "find all",
    "query",
    "confirm whether",
    "check whether",
    "determine whether",
)

CLAUSE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|;\s+|\|\s+")


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


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def scenario_files(scenario: str) -> list[Path]:
    return sorted(FINAL_DIR.glob(f"{scenario}*.json"))


def scenario_from_key(scenario_key: str) -> str:
    for scenario in SCENARIOS:
        if scenario_key.startswith(scenario):
            return scenario
    raise ValueError(f"Unknown scenario key: {scenario_key}")


def video_id_for_task(scenario: str, scenario_key: str, item: dict[str, Any]) -> str:
    image_name = str(item.get("image_name") or "")
    image_path = str(item.get("image_path") or "")
    for value in (image_name, image_path):
        if value.endswith(".mp4"):
            return Path(value).name
    if scenario == "kitchen" and scenario_key == "kitchen2":
        return "deep_fried.mp4"
    if scenario == "kitchen" and scenario_key == "kitchen3":
        return "Green Pepper Chicken.mp4"
    return f"{scenario_key}.mp4"


def load_tasks(scenario: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in scenario_files(scenario):
        scenario_key = path.stem
        for item in load_json(path):
            rows.append(
                {
                    "scenario": scenario,
                    "scenario_key": scenario_key,
                    "task_id": int(item["task_id"]),
                    "video_id": video_id_for_task(scenario, scenario_key, item),
                    "image_name": item.get("image_name"),
                    "image_path": item.get("image_path"),
                    "instruction": item.get("Instruction"),
                }
            )
    return rows


def split_clauses(instruction: str) -> list[str]:
    parts = [part.strip() for part in CLAUSE_SPLIT_RE.split(instruction) if part.strip()]
    clauses: list[str] = []
    for part in parts:
        subparts = re.split(r"\b(?:if|otherwise|then|next|finally|subsequently|first,|first)\b", part, flags=re.I)
        for sub in subparts:
            sub = sub.strip(" ,.")
            if sub:
                clauses.append(sub)
    return clauses


def is_visual_clause(text: str, scenario: str) -> bool:
    lowered = text.lower()
    if is_business_only_clause(text):
        return False
    if not any(term in lowered for term in VISUAL_TERMS):
        return False
    if scenario == "retail" and any(word in lowered for word in ("bottle", "wine", "shelf", "box", "cookies", "cheese", "point", "picked", "holding", "label")):
        return True
    if scenario == "kitchen" and any(word in lowered for word in ("ingredient", "recipe", "tray", "pot", "wok", "cutting board", "sprink", "pour", "dish composed")):
        return True
    if scenario in {"order", "restaurant"} and any(word in lowered for word in ("dish", "category", "section", "menu", "fold", "page", "point", "served", "plate", "set meal")):
        return True
    return False


def is_business_only_clause(text: str) -> bool:
    lowered = text.lower().strip()
    business_starts = (
        "there are multiple",
        "no such",
        "such wines exist",
        "such wine exists",
        "it does",
        "it is",
        "if it",
        "the total",
        "calculate",
        "list the",
        "remove the",
        "add the",
        "add all",
        "change the quantity",
    )
    if lowered.startswith(business_starts):
        return True
    if any(term in lowered for term in ("cart", "shopping list", "current order")):
        return True
    if "ask the ai service agent to find" in lowered and not any(
        word in lowered for word in ("category located", "section", "area", "fold", "page", "shelf", "right of", "left of", "above", "below")
    ):
        return True
    return False


def branch_for_clause(text: str) -> str:
    lowered = text.lower()
    if lowered.startswith("if ") or " if " in lowered[:20]:
        return "if_branch"
    if lowered.startswith("otherwise"):
        return "else_branch"
    if lowered.startswith("finally"):
        return "final"
    if lowered.startswith("then") or lowered.startswith("next") or lowered.startswith("subsequently"):
        return "follow_up"
    return "initial_or_contextual"


def compact_phrase(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" ,.;:")
    text = re.sub(r"^(?:ask|have|please ask) the ai (?:service )?agent to\s+", "", text, flags=re.I)
    text = re.sub(r"^(?:check|query|confirm|determine|identify|select|find)\s+", "", text, flags=re.I)
    return text.strip(" ,.;:")


def sanitize_visual_phrase(text: str) -> str | None:
    text = compact_phrase(text)
    lowered = text.lower()
    if not text:
        return None
    if re.fullmatch(r"(?:among )?(?:these|those|such|other)?\s*(?:wines|dishes|items|ingredients|recipes)", lowered):
        return None
    if re.match(r"^(?:among|from|regarding)?\s*(?:these|those|such|other)\s+(?:wines|dishes|items|ingredients|recipes)\b", lowered):
        return None
    if " in the order" in lowered or " current order" in lowered:
        return None
    if re.search(r"\b(?:wines|dishes|recipes|ingredients)\s+(?:from|with|to pair|that share|that require|not containing)\b", lowered):
        return None
    text = re.sub(r"\s+(?:is|are|has|have)\s+(?:on\s+)?(?:discount|sale).*$", "", text, flags=re.I)
    text = re.sub(r"\s+(?:is|are|has|have)\s+(?:not\s+)?(?:in\s+)?stock.*$", "", text, flags=re.I)
    text = re.sub(r"\s+(?:has|have|with)\s+(?:a\s+)?(?:tax|price|protein|calorie|fat|sodium|sugar|fiber|allergen|discount).*$", "", text, flags=re.I)
    text = re.sub(r"\s+(?:is|are)\s+(?:below|above|greater than|higher than|less than).*$", "", text, flags=re.I)
    text = re.sub(r"\s+(?:has|have)\s+expired.*$", "", text, flags=re.I)
    lowered = text.lower()
    if re.search(r"\b(?:has|have|is|are|contains?|include|including)\b[^.;,]*(?:discount|on sale|stock|expired|calorie|kcal|below|greater than|higher than|less than|price|tax|protein|fat|sodium|sugar|fiber|allergen|low[- ]fat|low[- ]sugar|high protein|nutrition)", lowered):
        region_match = re.search(
            r"\b((?:category|section|area|card|box|panel|fold|page)[^.;,]*)",
            text,
            flags=re.I,
        )
        if region_match:
            text = region_match.group(1)
        else:
            return None
    if re.search(r"\b(?:has|have|contains?|include|including)\s+(?:discount|tax|price|protein|calorie|allergen|sodium|sugar|fat|fiber|stock|inventory)\b", lowered):
        return None
    if re.search(r"\b(?:highest|lowest|smallest|cheapest|largest|fewest|most expensive|priced above|priced below|tax rate|protein content|calorie|allergen|sodium|sugar|fat content|fiber content)\b", lowered):
        # Keep the visual region only when a business-filtered item is selected
        # inside a visible category/section/area.
        region_match = re.search(
            r"\b((?:category|section|area|card|box|panel|fold|page)[^.;,]*)",
            text,
            flags=re.I,
        )
        if region_match:
            text = region_match.group(1)
        else:
            return None
    text = re.sub(r"\s+(?:and\s+)?add\s+.*$", "", text, flags=re.I)
    text = re.sub(r"\s+that\s+meets?\s+.*$", "", text, flags=re.I)
    text = re.sub(r"\s+that\s+is\s+(?:gluten|allergen|nut|dairy|egg|fish|protein|calorie|price|tax|sodium|sugar|fat|fiber).*$", "", text, flags=re.I)
    text = re.sub(r"\s+that\s+are\s+\[.*$", "", text, flags=re.I)
    text = re.sub(r"\s+which\s+(?:does|do|is|are|has|have)\s+.*$", "", text, flags=re.I)
    text = re.sub(r"\s+to\s+the\s+order.*$", "", text, flags=re.I)
    text = re.sub(r"\s+to\s+your\s+(?:cart|menu|shopping list).*$", "", text, flags=re.I)
    text = re.sub(r"\s+for\s+a\s+(?:dish|item|product|recipe|ingredient).*$", "", text, flags=re.I)
    text = re.sub(r"\s+that\s+is\s+\[.*$", "", text, flags=re.I)
    text = re.sub(r"\s+with\s+(?:the\s+)?(?:highest|lowest|cheapest|largest|fewest).*$", "", text, flags=re.I)
    text = re.sub(r"\s+and\s+determine\s+.*$", "", text, flags=re.I)
    text = re.sub(r"\s+ask\s+the\s+ai\s+.*$", "", text, flags=re.I)
    text = re.sub(r"^(?:in|within|inside)\s+the\s+", "", text, flags=re.I)
    text = compact_phrase(text)
    if len(text) < 8:
        return None
    if is_business_only_clause(text):
        return None
    return text


def is_generic_short_reference(text: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:second-to-last|first|second|third|fourth|fifth|sixth|last)?\s*(?:pointed|indicated|selected)?\s*(?:dish|bottle|wine|box|item|product)",
            text.strip(),
            flags=re.I,
        )
    )


def prune_subsumed_phrases(phrases: list[str]) -> list[str]:
    # Prefer a single specific visual referent per clause instead of keeping
    # generic fragments such as "second bottle" next to the full focused phrase.
    kept: list[str] = []
    lowered = [phrase.lower() for phrase in phrases]
    for i, phrase in enumerate(phrases):
        low = lowered[i]
        if any(i != j and len(low) < len(other) and low in other for j, other in enumerate(lowered)):
            continue
        kept.append(phrase)
    if len(kept) > 1:
        kept = [phrase for phrase in kept if not is_generic_short_reference(phrase)]
    if any("recipe" in phrase.lower() for phrase in kept):
        kept = [
            phrase
            for phrase in kept
            if not re.match(r"^(?:ingredients?|dish) (?:placed|composed|on|in)\b", phrase, flags=re.I)
        ]
    return kept


def extract_pattern_phrases(clause: str, scenario: str) -> list[str]:
    text = compact_phrase(clause)
    lowered = text.lower()
    phrases: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        value = sanitize_visual_phrase(value)
        if not value:
            return
        if len(value) < 8:
            return
        if is_business_only_clause(value):
            return
        if value.lower() not in {item.lower() for item in phrases}:
            phrases.append(value[:260])

    # Generic pointing references.
    for match in re.finditer(
        r"\b((?:second-to-last|first|second|third|fourth|fifth|sixth|last)\s+(?:pointed|indicated|selected)?\s*(?:dish|bottle|wine|box|item|product)[^.;,]*(?:in|inside|within|located|on|with|of|above|below|left|right|middle|top|bottom|picked|put back|put down|returned|placed back)[^.;,]*)",
        text,
        flags=re.I,
    ):
        add(match.group(1))
    for match in re.finditer(
        r"\b((?:second-to-last|first|second|third|fourth|fifth|sixth|last)\s+(?:pointed|indicated|selected)?\s*(?:dish|bottle|wine|box|item|product))\b",
        text,
        flags=re.I,
    ):
        add(match.group(1))
    for match in re.finditer(
        r"\b((?:second-to-last|first|second|third|fourth|fifth|sixth|last)\s+(?:dish|bottle|wine|box|item|product)\s+(?:you|your finger)\s+(?:are\s+)?(?:pointing|pointed|indicated)\s*(?:at|to)?)",
        text,
        flags=re.I,
    ):
        add(match.group(1))

    # Menu/category/section regions.
    for match in re.finditer(
        r"\b((?:category|section|area|card|box|panel|fold|page)[^.;,]*(?:located|featuring|with|at|on|above|below|left|right|middle|top|bottom)[^.;,]*)",
        text,
        flags=re.I,
    ):
        add(match.group(1))
    for match in re.finditer(
        r"\b((?:within|in|inside)\s+the\s+(?:category|section|area)[^.;,]*)",
        text,
        flags=re.I,
    ):
        add(match.group(1))

    # Spatially described dish/product/ingredient references.
    for match in re.finditer(
        r"\b((?:dish|item|bottle|wine|box|product|ingredient)[^.;,]*(?:located|placed|position|leftmost|rightmost|topmost|far right|far left|highest|lowest|top left|right side|left side|middle shelf|same row|above|below|to the right|to the left)[^.;,]*)",
        text,
        flags=re.I,
    ):
        add(match.group(1))
    for match in re.finditer(
        r"\b((?:leftmost|rightmost|topmost|bottom|top|far right|far left)[^.;,]*(?:dish|item|bottle|wine|box|ingredient)[^.;,]*)",
        text,
        flags=re.I,
    ):
        add(match.group(1))

    # Appearance-selected retail/menu objects.
    for match in re.finditer(
        r"\b((?:bottle|wine|box|cookies|cheese|product|dish|item)[^.;,]*(?:with|containing|has|label|capsule|cap|foil|liquid|dark|white|red|blue|green|yellow|pink|brown|gold|copper)[^.;,]*)",
        text,
        flags=re.I,
    ):
        add(match.group(1))

    # Kitchen action / recipe scene references.
    if scenario == "kitchen":
        for match in re.finditer(
            r"\b((?:ingredient|powder|vegetable|dish|recipe)[^.;,]*(?:sprinkling|pouring|cutting|cooking|boiling|placed|on the baking tray|on the blue cutting board|in the wok|in the pot|composed of)[^.;,]*)",
            text,
            flags=re.I,
        ):
            add(match.group(1))
        for match in re.finditer(
            r"\b((?:which\s+)?recipe[^.;,]*(?:corresponds to|composed of|placed on|boiling|cutting board|baking tray|wok|pot)[^.;,]*)",
            text,
            flags=re.I,
        ):
            add(match.group(1))

    # Clauses whose entire text is already a focused visual request.
    focused_starts = (
        "focus on ",
        "regarding ",
        "among ",
        "the dish ",
        "the bottle ",
        "the wine ",
        "the box ",
        "the ingredient ",
        "the recipe ",
        "what ingredient ",
        "which recipe ",
        "what kind of ingredient ",
    )
    if lowered.startswith(focused_starts) and not is_business_only_clause(text):
        add(text)

    # Avoid generic context-only phrases such as "you pointed at three dishes".
    return prune_subsumed_phrases([
        phrase
        for phrase in phrases
        if not re.fullmatch(r"(?:you\s+)?(?:have\s+)?(?:just\s+)?point(?:ed|ing)?(?:\s+out)?\s+(?:at\s+)?three\s+(?:dishes|bottles|items)(?:\s+in\s+sequence)?", phrase, flags=re.I)
    ])


def extract_visual_problem_texts(task: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = task["scenario"]
    clauses = split_clauses(task["instruction"] or "")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, clause in enumerate(clauses):
        if not is_visual_clause(clause, scenario):
            continue
        if len(clause) < 12:
            continue
        for j, phrase in enumerate(extract_pattern_phrases(clause, scenario)):
            key = phrase.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "raw_problem_id": f"{task['scenario_key']}_task{task['task_id']:03d}_visual_{i:02d}_{j:02d}",
                    "scenario": scenario,
                    "scenario_key": task["scenario_key"],
                    "task_id": task["task_id"],
                    "video_id": task["video_id"],
                    "image_path": task.get("image_path"),
                    "instruction": task["instruction"],
                    "visual_problem_raw_text": phrase,
                    "source_clause": clause,
                    "branch": branch_for_clause(clause),
                    "extraction_notes": ["clean_v2_pattern_visual_referent_extraction"],
                }
            )
    return out


def clean_content_hint(text: str) -> str | None:
    lowered = canonical_hint_text(text)
    fragments = re.split(r"\b(?:ask the ai|check|query|search|find|add|determine if|determine whether|confirm whether)\b", lowered, flags=re.I)
    hint = fragments[0].strip(" ,.")
    for term in BUSINESS_TERMS:
        hint = re.sub(rf"\b{re.escape(term)}\b", "", hint, flags=re.I)
    hint = re.sub(r"\s+", " ", hint).strip(" ,.")
    if not hint:
        return None
    return hint[:220]


def canonical_hint_text(text: str) -> str:
    text = text.lower()
    replacements = {
        "bottom-left": "bottom left",
        "top-left": "top left",
        "bottom-right": "bottom right",
        "top-right": "top right",
        "left-hand": "left",
        "right-hand": "right",
        "currently cooking": "cooking",
        "currently boiling": "boiling",
        "placed on": "on",
        "placed in": "in",
        "located at": "at",
        "located in": "in",
        "specific type of ": "",
        "what kind of ": "",
        "what ingredient ": "ingredient ",
        "which recipe ": "recipe ",
        "the recipe that ": "recipe that ",
        "corresponds to": "corresponds to",
        "chunked": "chunky",
        "simmering": "boiling",
        "inside": "in",
        "currently on": "on",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"\b(?:the|a|an)\s+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:")
    return text


def extract_ordinal(text: str) -> str | None:
    lowered = text.lower()
    for ordinal in ORDINALS:
        if re.search(rf"\b{ordinal}\b", lowered):
            return ordinal
    return None


def extract_action(text: str, referent_type: str) -> str | None:
    lowered = text.lower()
    if any(word in lowered for word in ("point", "finger", "indicat")):
        return "pointing"
    if any(word in lowered for word in ("holding", "held", "in your hand")):
        return "holding"
    if any(word in lowered for word in ("picked", "pick up", "picking")):
        return "picking"
    if any(word in lowered for word in ("put back", "put down", "placed back", "returned")):
        return "placing"
    if "sprink" in lowered:
        return "sprinkling"
    if "pour" in lowered:
        return "pouring"
    if re.search(r"\bcut(?:ting)?\b", lowered.replace("cutting board", "")) or "slicing" in lowered:
        return "cutting"
    if any(word in lowered for word in ("cook", "stir", "fry", "boiling")):
        return "cooking"
    if any(word in lowered for word in ("served", "plate", "brought")) and referent_type == "object_action_state":
        return "served"
    return None


def infer_target_kind(text: str, scenario: str) -> str:
    lowered = text.lower()
    if "set meal" in lowered:
        return "set_meal_name"
    if scenario == "retail":
        if "label" in lowered and "product" not in lowered and "bottle" not in lowered and "box" not in lowered:
            return "visible_text"
        return "product_name"
    if scenario == "kitchen":
        if "recipe" in lowered or "dish composed" in lowered or "which dish" in lowered:
            return "recipe_name"
        return "ingredient_name"
    if "category" in lowered or "section" in lowered or "catalog" in lowered:
        return "category"
    if any(word in lowered for word in ("area", "card", "box", "fold", "panel")) and not any(word in lowered for word in ("dish", "item", "set meal")):
        return "category"
    return "dish_name"


def infer_surface(text: str, scenario: str) -> str:
    lowered = text.lower()
    if scenario == "retail":
        return "shelf"
    if scenario == "kitchen":
        return "kitchen_workspace"
    if scenario == "restaurant" and any(word in lowered for word in ("served", "plate", "table", "brought")):
        return "table"
    return "menu"


def selection_unit(surface: str, target_kind: str) -> str:
    if target_kind == "category":
        return "shelf_label" if surface == "shelf" else "menu_category"
    if target_kind == "product_name":
        return "product_package"
    if target_kind == "ingredient_name":
        return "ingredient"
    if target_kind == "recipe_name":
        return "recipe_scene"
    if target_kind == "set_meal_name":
        return "menu_item"
    if target_kind == "visible_text":
        return "shelf_label" if surface == "shelf" else "menu_category"
    if surface == "table":
        return "served_dish"
    return "menu_item"


def infer_referent_type(text: str, scenario: str, target_kind: str) -> str:
    lowered = text.lower()
    if target_kind == "recipe_name" and scenario == "kitchen":
        return "composite_scene"
    action_probe = lowered.replace("cutting board", "")
    if any(word in action_probe for word in ("sprink", "pour", "cut", "cook", "boiling", "picked", "pick up", "holding", "held", "served", "plate")):
        return "object_action_state"
    if any(word in lowered for word in ("point", "finger", "indicat")):
        return "pointing_sequence" if extract_ordinal(text) else "selected_pointing_event"
    relation_probe = re.sub(r"\b(?:top|bottom)\s+(?:left|right)\s+of\b", "", lowered)
    if any(word in relation_probe for word in ("above", "below", "to the right", "to the left", "left of", "right of", "next to", "under", "over")):
        return "relative_region"
    return "static_region"


def region(text: str, surface: str) -> dict[str, str | None]:
    lowered = text.lower()
    side = None
    vertical = None
    container = None
    if any(word in lowered for word in ("leftmost", "far left", "left side", "left of", "on the left", "top-left", "bottom-left", "top left", "bottom left")):
        side = "left"
    elif any(word in lowered for word in ("rightmost", "far right", "right side", "right of", "on the right", "top-right", "bottom-right", "top right", "bottom right")):
        side = "right"
    elif any(word in lowered for word in ("middle", "center", "central")):
        side = "center"
    if any(word in lowered for word in ("topmost", "top ", "upper", "highest", "above", "top-left", "top-right", "top left", "top right")):
        vertical = "top"
    elif any(word in lowered for word in ("bottom", "lower", "below", "bottom-left", "bottom-right", "bottom left", "bottom right")):
        vertical = "bottom"
    elif any(word in lowered for word in ("middle", "center")):
        vertical = vertical or "middle"
    if "fold" in lowered:
        container = "fold"
    elif "page" in lowered or surface == "menu":
        container = "page" if any(word in lowered for word in ("page", "menu")) else None
    elif "panel" in lowered:
        container = "panel"
    elif "shelf" in lowered or surface == "shelf":
        container = "shelf"
    elif "tray" in lowered:
        container = "tray"
    elif "pot" in lowered:
        container = "pot"
    elif "wok" in lowered:
        container = "wok"
    elif "cutting board" in lowered:
        container = "cutting_board"
    elif "table" in lowered or surface == "table":
        container = "table"
    return {"side": side, "vertical": vertical, "container": container}


def relation(text: str) -> dict[str, Any]:
    lowered = text.lower()
    relation_probe = re.sub(r"\b(?:top|bottom)\s+(?:left|right)\s+of\b", "", lowered)
    relation_type = None
    for key, probes in {
        "above": ("above", "over", "directly above"),
        "below": ("below", "under", "directly below"),
        "left_of": ("left of", "to the left"),
        "right_of": ("right of", "to the right"),
        "inside": ("inside", "within", "in the category", "within the category"),
        "containing": ("containing", "contains", "that contains"),
        "next_to": ("next to", "adjacent"),
    }.items():
        if any(probe in relation_probe for probe in probes):
            relation_type = key
            break
    return {"type": relation_type, "anchor": {}}


def appearance(text: str) -> dict[str, str | None]:
    lowered = canonical_hint_text(text)
    color_text = lowered.replace("blue cutting board", "").replace("white text", "").replace("white font", "")
    color = None
    for candidate in ("red", "blue", "green", "yellow", "white", "black", "brown", "dark", "gold", "pink", "purple", "orange", "silver", "copper"):
        if re.search(rf"\b{candidate}\b", color_text):
            color = candidate
            break
    style = None
    if "dark background" in lowered or "dark-background" in lowered:
        style = "dark_background"
    elif "hand illustration" in lowered or "small hand" in lowered:
        style = "hand_illustration"
    elif "white card" in lowered or "white box" in lowered:
        style = "white_card"
    elif "label" in lowered:
        style = "label"
    size = None
    if "small" in lowered:
        size = "small"
    elif "large" in lowered or "big" in lowered or "thickest" in lowered:
        size = "large"
    shape = None
    for candidate in ("bottle", "box", "card", "bag", "package", "plate"):
        if candidate in lowered:
            shape = candidate
            break
    return {"color": color, "style": style, "size": size, "shape": shape, "content_hint": clean_content_hint(text)}


def menu_label(text: str, scenario: str) -> str | None:
    lowered = text.lower()
    if scenario != "order":
        return None
    if "menu 1" in lowered or "menu_1" in lowered or "first menu" in lowered:
        return "menu_1"
    if "menu 2" in lowered or "menu_2" in lowered or "second menu" in lowered:
        return "menu_2"
    return None


def visual_query(raw: dict[str, Any]) -> dict[str, Any]:
    text = raw["visual_problem_raw_text"]
    scenario = raw["scenario"]
    target_kind = infer_target_kind(text, scenario)
    surface = infer_surface(text, scenario)
    referent_type = infer_referent_type(text, scenario, target_kind)
    vq = {
        "schema_version": "visual_query_v1",
        "scenario": scenario,
        "surface": surface,
        "target": {
            "kind": target_kind,
            "selection_unit": selection_unit(surface, target_kind),
            "cardinality": "single",
        },
        "referent": {
            "type": referent_type,
            "action": extract_action(text, referent_type),
            "ordinal": extract_ordinal(text),
            "region": region(text, surface),
            "relation": relation(text),
            "appearance": appearance(text),
        },
        "scope": {
            "video_id": raw["video_id"],
            "menu_label": menu_label(text, scenario),
            "time_hint": None,
        },
    }
    normalize_visual_query(vq, text, raw["video_id"])
    return vq


def normalize_visual_query(vq: dict[str, Any], text: str, video_id: str) -> None:
    lowered = canonical_hint_text(text)
    referent = vq["referent"]
    target_kind = vq["target"]["kind"]
    if vq["scenario"] == "kitchen":
        if target_kind == "recipe_name":
            if "baking tray" in lowered:
                referent["appearance"]["content_hint"] = "recipe scene: ingredients on baking tray"
            elif "pot" in lowered and "blue cutting board" in lowered:
                referent["appearance"]["content_hint"] = "recipe scene: pot ingredients and vegetables on blue cutting board"
            elif any(term in lowered for term in ("fried pork", "pork chop", "cutlet")):
                referent["appearance"]["content_hint"] = "recipe scene: slicing fried pork cutlet"
            elif video_id == "Green Pepper Chicken.mp4" and any(term in lowered for term in ("current action", "current operation", "this dish", "this is", "recipe this")):
                referent["appearance"]["content_hint"] = "recipe scene: current green pepper chicken cooking"
        elif target_kind == "ingredient_name":
            if "bottom left" in lowered and "cutting board" in lowered:
                referent["appearance"]["content_hint"] = "ingredient at bottom left of cutting board"
            elif "top left" in lowered and "cutting board" in lowered:
                referent["appearance"]["content_hint"] = "ingredient at top left of cutting board"
            elif "right side" in lowered and "cutting board" in lowered:
                referent["appearance"]["content_hint"] = "ingredient on right side of cutting board"
            elif "left side" in lowered and "baking tray" in lowered:
                referent["appearance"]["content_hint"] = "ingredient on left side of baking tray"
            elif any(term in lowered for term in ("yellow powder", "staple powder", "powder")) and "baking tray" in lowered:
                referent["appearance"]["content_hint"] = "powder on right side of baking tray"

    if vq["scenario"] == "retail":
        if "put back" in lowered or "put down" in lowered or "returned" in lowered or "placed back" in lowered:
            referent["action"] = "placing"
            referent["type"] = "object_action_state"
        elif "picked up" in lowered or "picked" in lowered:
            referent["action"] = "picking"
            referent["type"] = "object_action_state"


def problem_type(vq: dict[str, Any]) -> str:
    return f"{vq['surface']}__{vq['target']['kind']}__{vq['referent']['type']}"


def build_scenario(scenario: str) -> dict[str, Any]:
    out_dir = OUT_ROOT / scenario
    tasks = load_tasks(scenario)
    raw_rows: list[dict[str, Any]] = []
    for task in tasks:
        raw_rows.extend(extract_visual_problem_texts(task))

    query_rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in raw_rows:
        vq = visual_query(raw)
        key = stable_json(vq)
        query_rows.append(
            {
                "raw_problem_id": raw["raw_problem_id"],
                "scenario": raw["scenario"],
                "scenario_key": raw["scenario_key"],
                "task_id": raw["task_id"],
                "video_id": raw["video_id"],
                "visual_query_v1": vq,
                "cluster_key": key,
            }
        )
        grouped[key].append(raw)

    clusters: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    cluster_id_counter = 1
    for key, group in sorted(grouped.items(), key=lambda item: (item[1][0]["scenario_key"], item[1][0]["video_id"], item[0])):
        vq = json.loads(key)
        problem_id = f"{scenario}_clean_v2_problem_{cluster_id_counter:04d}"
        cluster_id_counter += 1
        source_task_ids = sorted({row["task_id"] for row in group})
        source_problem_ids = [row["raw_problem_id"] for row in group]
        snippets = []
        seen_snippets = set()
        for row in group:
            snippet = row["source_clause"]
            if snippet not in seen_snippets:
                snippets.append(snippet)
                seen_snippets.add(snippet)
        cluster = {
            "problem_id": problem_id,
            "scenario": scenario,
            "video_id": vq["scope"]["video_id"],
            "visual_query_v1": vq,
            "problem_type": problem_type(vq),
            "source_task_ids": source_task_ids,
            "source_problem_ids": source_problem_ids,
            "source_instruction_snippets": snippets[:12],
            "dedupe_rationale": "Same scenario, video_id, surface, target, referent, and scope under visual_query_v1.",
            "review_notes": [],
        }
        clusters.append(cluster)
        cases.append(
            {
                "case_id": problem_id,
                "scenario": scenario,
                "video_id": vq["scope"]["video_id"],
                "problem_type": problem_type(vq),
                "visual_query_v1": vq,
                "event_gt": {
                    "primary_content_range": None,
                    "expected_time_range": None,
                    "allowed_transition_range": None,
                    "key_frame_time": None,
                    "expected_region": {"description": None, "coarse_region": None, "notes": None},
                    "confidence": "pending",
                    "evidence": "Pending actual video annotation. Clean v2 does not use old bootstrap or final value as GT.",
                },
                "detail_gt": {
                    "target_kind": vq["target"]["kind"],
                    "canonical_value": None,
                    "acceptable_aliases": [],
                    "negative_neighbors": [],
                    "confidence": "pending",
                    "evidence": "Pending actual video annotation. Clean v2 does not use old bootstrap or final value as GT.",
                },
                "gt_status": "gt_pending_video_annotation",
                "evaluation_modes": [],
                "source_task_ids": source_task_ids,
                "source_problem_ids": source_problem_ids,
                "source_instruction_snippets": snippets[:12],
                "review_notes": ["GT must be filled by inspecting the source video before strict observer evaluation."],
            }
        )

    target_counts = Counter(case["visual_query_v1"]["target"]["kind"] for case in cases)
    referent_counts = Counter(case["visual_query_v1"]["referent"]["type"] for case in cases)
    video_counts = Counter(case["video_id"] for case in cases)
    metadata = {
        "schema_version": "observer_dataset_clean_v2",
        "scenario": scenario,
        "status": "visual_problem_clusters_ready_gt_pending",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_policy": {
            "allowed_inputs": ["scenarios/final/*.json instruction fields"],
            "disallowed_inputs": [
                "observer_problem_set_*",
                "observer_dataset_rebuild_v1",
                "old bootstrap files",
                "eval_result",
                "DB/tool data",
                "scenario final key/value for extraction, clustering, or GT",
            ],
        },
        "process_doc": "experiments/visual_observer_runner/eval/eval-process.md",
    }
    write_jsonl(out_dir / "01_scenario_tasks.jsonl", tasks)
    write_jsonl(out_dir / "02_visual_questions_raw.jsonl", raw_rows)
    write_jsonl(out_dir / "03_visual_queries_raw.jsonl", query_rows)
    write_json(out_dir / "04_visual_query_clusters.json", {**metadata, "cluster_count": len(clusters), "clusters": clusters})
    write_json(
        out_dir / "05_observer_dataset_with_gt.json",
        {
            **metadata,
            "case_count": len(cases),
            "gt_ready_case_count": 0,
            "excluded_count": len(excluded),
            "review_required_count": len(cases),
            "coverage": {
                "source_task_count": len(tasks),
                "raw_visual_problem_count": len(raw_rows),
                "visual_query_count": len(query_rows),
                "cluster_count": len(clusters),
                "video_case_counts": dict(sorted(video_counts.items())),
                "target_kind_counts": dict(sorted(target_counts.items())),
                "referent_type_counts": dict(sorted(referent_counts.items())),
            },
            "cases": cases,
        },
    )
    write_json(out_dir / "excluded_cases.json", {**metadata, "excluded_cases": excluded})
    write_json(
        out_dir / "review_required_cases.json",
        {
            **metadata,
            "review_required_cases": [
                {
                    "case_id": case["case_id"],
                    "reason": "gt_pending_video_annotation",
                    "video_id": case["video_id"],
                    "visual_query_v1": case["visual_query_v1"],
                    "source_task_ids": case["source_task_ids"],
                }
                for case in cases
            ],
        },
    )
    summary = [
        f"# {scenario.title()} Clean v2",
        "",
        "- Input source: `scenarios/final/*.json` instructions only.",
        "- Old bootstrap/problem_set/eval/DB/final values are not read.",
        "- GT is intentionally pending until actual video annotation is performed.",
        "",
        f"- Scenario tasks: {len(tasks)}",
        f"- Raw visual problems: {len(raw_rows)}",
        f"- Visual query clusters / eval cases: {len(cases)}",
        f"- GT-ready cases: 0",
        "",
        "## Video Coverage",
    ]
    for key, value in sorted(video_counts.items()):
        summary.append(f"- `{key}`: {value}")
    summary.extend(["", "## Target Kinds"])
    for key, value in sorted(target_counts.items()):
        summary.append(f"- `{key}`: {value}")
    summary.extend(["", "## Referent Types"])
    for key, value in sorted(referent_counts.items()):
        summary.append(f"- `{key}`: {value}")
    write_text(out_dir / "summary.md", "\n".join(summary) + "\n")

    return {
        "scenario": scenario,
        "tasks": len(tasks),
        "raw": len(raw_rows),
        "cases": len(cases),
        "gt_ready": 0,
    }


def write_root_readme(results: list[dict[str, Any]]) -> None:
    lines = [
        "# Observer Dataset Clean v2",
        "",
        "This is a clean rebuild from `scenarios/final/*.json` instructions only.",
        "It deliberately does not use older bootstrap/problem-set files or final values.",
        "",
        "GT is pending and must be filled by actual video inspection before strict observer evaluation.",
        "",
        "## Build Results",
        "",
    ]
    for row in results:
        lines.append(f"- `{row['scenario']}`: {row['cases']} cases from {row['raw']} raw visual problems over {row['tasks']} tasks")
    lines.extend(
        [
            "",
            "## Files Per Scenario",
            "",
            "- `01_scenario_tasks.jsonl`",
            "- `02_visual_questions_raw.jsonl`",
            "- `03_visual_queries_raw.jsonl`",
            "- `04_visual_query_clusters.json`",
            "- `05_observer_dataset_with_gt.json`",
            "- `excluded_cases.json`",
            "- `review_required_cases.json`",
            "- `summary.md`",
        ]
    )
    write_text(OUT_ROOT / "README.md", "\n".join(lines) + "\n")


def validate_no_forbidden_fields() -> list[str]:
    issues: list[str] = []
    forbidden = ("source_bootstrap", "source_bootstrap_case", "source_bootstrap_cases", "scenario_final_values_seen")
    for path in OUT_ROOT.glob("*/05_observer_dataset_with_gt.json"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                issues.append(f"{path}: forbidden token {token}")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    args = parser.parse_args()
    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    results = [build_scenario(scenario) for scenario in scenarios]
    if args.scenario == "all":
        write_root_readme(results)
    else:
        existing = []
        for scenario in SCENARIOS:
            p = OUT_ROOT / scenario / "05_observer_dataset_with_gt.json"
            if p.exists():
                data = load_json(p)
                existing.append(
                    {
                        "scenario": scenario,
                        "tasks": data["coverage"]["source_task_count"],
                        "raw": data["coverage"]["raw_visual_problem_count"],
                        "cases": data["case_count"],
                        "gt_ready": data["gt_ready_case_count"],
                    }
                )
        write_root_readme(existing)
    issues = validate_no_forbidden_fields()
    if issues:
        raise SystemExit("\n".join(issues))
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
