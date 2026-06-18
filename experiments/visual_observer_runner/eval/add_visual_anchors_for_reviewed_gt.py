#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCENARIO_DIR = ROOT / "scenarios/final"


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def with_anchor(
    task: dict[str, Any],
    key: str,
    values: list[str],
    *,
    secondary_key: str | None = None,
    secondary_values: list[str] | None = None,
) -> dict[str, Any]:
    updated: OrderedDict[str, Any] = OrderedDict()
    inserted = False
    for k, v in task.items():
        if k in {"key", "value", "secondary_key", "secondary_value"}:
            continue
        updated[k] = v
        if k == "image_path":
            updated["key"] = key
            updated["value"] = values
            if secondary_key is not None and secondary_values is not None:
                updated["secondary_key"] = secondary_key
                updated["secondary_value"] = secondary_values
            inserted = True
    if not inserted:
        updated["key"] = key
        updated["value"] = values
        if secondary_key is not None and secondary_values is not None:
            updated["secondary_key"] = secondary_key
            updated["secondary_value"] = secondary_values
    return dict(updated)


def first_match(text: str, patterns: list[tuple[str, list[str]]], scenario: str, task_id: int) -> list[str]:
    matches = [(text.find(pattern), values) for pattern, values in patterns if pattern in text]
    matches = [(idx, values) for idx, values in matches if idx >= 0]
    if not matches:
        raise ValueError(f"{scenario} task {task_id}: no visual anchor pattern matched")
    return min(matches, key=lambda item: item[0])[1]


def visual_sequence(
    instruction: str,
    patterns: dict[str, list[str]],
    value_map: dict[str, str] | None = None,
) -> list[str]:
    text = clean(instruction)
    candidates: list[tuple[int, int, str]] = []
    for label, phrases in patterns.items():
        value = value_map[label] if value_map else label
        for phrase in phrases:
            for match in re.finditer(re.escape(clean(phrase)), text):
                candidates.append((match.start(), match.end(), value))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    chosen: list[tuple[int, int, str]] = []
    for start, end, value in candidates:
        overlaps = any(not (end <= old_start or start >= old_end) for old_start, old_end, _ in chosen)
        if not overlaps:
            chosen.append((start, end, value))
    chosen.sort(key=lambda item: item[0])

    values: list[str] = []
    for _, _, value in chosen:
        if not values or values[-1] != value:
            values.append(value)
    return values


def secondary_values_from_sequence(sequence: list[str], primary_values: list[str]) -> list[str]:
    idx = 0
    for primary in primary_values:
        if idx < len(sequence) and sequence[idx] == primary:
            idx += 1
            continue
        try:
            idx = sequence.index(primary, idx) + 1
        except ValueError:
            continue
    return sequence[idx : idx + 1]


def secondary_anchor_from_typed_sequence(
    sequence: list[tuple[str, list[str]]],
    primary_key: str,
    primary_values: list[str],
) -> tuple[str, list[str]] | tuple[None, list[str]]:
    primary_remaining = [value.lower() for value in primary_values]
    idx = 0
    for key, values in sequence:
        lowered_values = [value.lower() for value in values]
        if key != primary_key:
            idx += 1
            continue

        if lowered_values == [v.lower() for v in primary_values]:
            idx += 1
            break

        if all(value.lower() in set(lowered_values) for value in primary_values):
            idx += 1
            break

        if primary_remaining and primary_remaining[0] in set(lowered_values):
            primary_remaining.pop(0)
            idx += 1
            if not primary_remaining:
                break
            continue

        idx += 1
    else:
        idx = 0

    if idx < len(sequence):
        return sequence[idx]
    return None, []


def typed_visual_sequence(
    instruction: str,
    patterns: dict[str, tuple[str, list[str], list[str]]],
) -> list[tuple[str, list[str]]]:
    text = clean(instruction)
    candidates: list[tuple[int, int, str, list[str]]] = []
    for _, (key, values, phrases) in patterns.items():
        for phrase in phrases:
            for match in re.finditer(re.escape(clean(phrase)), text):
                candidates.append((match.start(), match.end(), key, values))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    chosen: list[tuple[int, int, str, list[str]]] = []
    for start, end, key, values in candidates:
        overlaps = any(not (end <= old_start or start >= old_end) for old_start, old_end, _, _ in chosen)
        if not overlaps:
            chosen.append((start, end, key, values))
    chosen.sort(key=lambda item: item[0])

    sequence: list[tuple[str, list[str]]] = []
    for _, _, key, values in chosen:
        if not sequence or sequence[-1] != (key, values):
            sequence.append((key, values))
    return sequence


RETAIL6 = {
    "heart": "St Michel Le Palmier Crispy Caramel",
    "second": "Bahlsen",
    "third": "Desobry Speculoos",
    "red": "Nutella Biscuits",
    "yellow": "Leibniz Keks",
}

RETAIL6_SEQUENCE_PATTERNS = {
    "red": [
        "cylindrical cookie box with a red lid located directly above the third box",
        "cylindrical cookie box with a red lid directly above the third box",
        "cylindrical cookie with a red lid located directly above the third box",
        "cylindrical cookie with a red lid directly above the third box",
        "cylindrical cookies with a red lid directly above the third box",
        "red lid situated directly above the third box",
        "red lid located directly above the third box",
        "red lid directly above the third box",
        "cylindrical cookie box with a red lid",
        "cylindrical cookie with a red lid",
        "cylindrical cookies with a red lid",
        "cylindrical cookie box",
        "cylindrical cookie",
    ],
    "yellow": [
        "box of yellow-packaged cookies directly beneath the third box",
        "box of yellow-packaged cookies directly below the third box",
        "yellow-packaged cookie box located directly below the third box",
        "yellow-packaged cookie box directly below the third box",
        "yellow-packaged cookie box directly beneath the third box",
        "yellow packaged cookie box located directly below the third box",
        "yellow packaged cookie box directly below the third box",
        "yellow packaged cookie box directly beneath the third box",
        "yellow-packaged box of cookies directly beneath the third box",
        "yellow-packaged box of cookies directly below the third box",
        "yellow-packaged cookie box",
        "yellow packaged cookie box",
        "yellow-packaged box",
        "yellow packaged box",
        "yellow-packaged",
        "yellow packaged",
    ],
    "third": [
        "third box of white-packaged cookies",
        "third box of white packaged cookies",
        "third white-packaged cookie box",
        "third white packaged cookie box",
        "third item you picked (a box of white-packaged cookies)",
        "third item you picked (a box of white packaged cookies)",
        "third picked item (a box of white-packaged cookies)",
        "third picked item (a box of white packaged cookies)",
        "third box of cookies being picked up",
        "third box of cookies picked up",
        "third picked-up box of white-packaged cookies",
        "third picked-up box",
        "third picked box",
        "third picked-up white-packaged cookie",
        "third picked white-packaged cookie",
        "third box of white",
        "third box",
    ],
    "second": [
        "second picked-up chocolate biscuit",
        "second picked-up chocolate cookie",
        "second picked chocolate biscuit",
        "second picked chocolate cookie",
        "second chocolate biscuit picked up",
        "second chocolate cookie picked up",
        "second item you picked (a chocolate cookie)",
        "second item picked (a chocolate cookie)",
        "second chocolate biscuit",
        "second chocolate cookie",
        "second cookie you pick up",
        "second cookie you picked up",
        "second picked-up item",
        "second picked item",
        "second item you picked",
        "second item picked",
        "second picked",
    ],
    "heart": [
        "first picked-up item, which is a heart-shaped cookie",
        "first picked item, which is a heart-shaped cookie",
        "first item picked up, which is a heart-shaped cookie",
        "first item picked, which is a heart-shaped cookie",
        "first picked single item that is heart-shaped",
        "first item you picked up, a heart-shaped cookie",
        "first picked item, a heart-shaped cookie",
        "first item picked (a heart-shaped cookie)",
        "first item picked up (a heart-shaped cookie)",
        "first picked item",
        "first picked-up item",
        "first item picked up",
        "first item picked",
        "first heart-shaped cookie",
        "heart-shaped cookie",
        "heart-shaped biscuit",
        "heart-shaped",
    ],
}

RETAIL10_PATTERNS = [
    ("rectangular cheese located at the innermost", ["Emmi Gruyere Cheese"]),
    ("rectangular cheese located at the very back", ["Emmi Gruyere Cheese"]),
    ("rectangular cheese located furthest inside", ["Emmi Gruyere Cheese"]),
    ("rectangular cheese farthest inside", ["Emmi Gruyere Cheese"]),
    ("rectangular cheese piece at the very back", ["Emmi Gruyere Cheese"]),
    ("rectangular cheese piece located at the very back", ["Emmi Gruyere Cheese"]),
    ("rectangular cheese piece located furthest inside", ["Emmi Gruyere Cheese"]),
    ("rectangular cheese block at the innermost", ["Emmi Gruyere Cheese"]),
    ("innermost rectangular cheese", ["Emmi Gruyere Cheese"]),
    ("innermost rectangular piece of cheese", ["Emmi Gruyere Cheese"]),
    ("cheese with the lowest label price", ["Basiron Gouda Cheese"]),
    ("cheese with the lowest labeled price", ["Basiron Gouda Cheese"]),
    ("cheese with the lowest tag price", ["Basiron Gouda Cheese"]),
    ("cheese with the lowest price on its tag", ["Basiron Gouda Cheese"]),
    ("cheese with the lowest labelled price", ["Basiron Gouda Cheese"]),
    ("cheese with the lowest label", ["Basiron Gouda Cheese"]),
    ("cheese with the rightmost label", ["Gruyere AOP Cheese"]),
    ("cheese with the label furthest to the right", ["Gruyere AOP Cheese"]),
    ("cheese block with the rightmost label", ["Gruyere AOP Cheese"]),
    ("square cheese that is closest to you", ["Switzerland Swiss Cheese"]),
    ("square cheese piece that is closest to you", ["Switzerland Swiss Cheese"]),
    ("square cheese closest to you", ["Switzerland Swiss Cheese"]),
    ("wedge-shaped cheese closest to you", ["Appenzeller Cheese"]),
    ("wedge-shaped cheese that is closest to you", ["Appenzeller Cheese"]),
    ("wedge of cheese closest to you", ["Appenzeller Cheese"]),
]

RETAIL10_SEQUENCE_PATTERNS = {
    "Mystic Valley Cheese": [
        "cheese directly below the cheese with the lowest tag price",
        "cheese directly below the cheese with the lowest label price",
        "directly below the cheese with the lowest tag price",
        "directly below the cheese with the lowest label price",
        "directly below the lowest-tag cheese",
        "directly below the lowest label cheese",
    ],
    "Basiron Gouda Cheese": [
        "item directly below the rectangular cheese at the very back",
        "item directly below the rectangular cheese located at the very back",
        "directly below the rectangular cheese at the very back",
        "directly below the rectangular cheese located at the very back",
        "directly below back rectangular cheese",
        "cheese with the lowest label price",
        "cheese with the lowest labeled price",
        "cheese with the lowest tag price",
        "cheese with the lowest price on its tag",
        "cheese with the lowest labelled price",
        "cheese with the lowest label",
        "lowest labeled price",
    ],
    "Gruyere AOP Cheese": [
        "cheese whose label is furthest to the right",
        "cheese with the label furthest to the right",
        "cheese with the rightmost label",
        "cheese block with the rightmost label",
        "cheese furthest to the right",
        "cheese with the rightmost labelled price",
        "rightmost label",
    ],
    "Emmi Gruyere Cheese": [
        "rectangular cheese located at the innermost",
        "rectangular cheese located at the very back",
        "rectangular cheese located furthest inside",
        "rectangular cheese farthest inside",
        "rectangular cheese piece at the very back",
        "rectangular cheese piece located at the very back",
        "rectangular cheese piece located furthest inside",
        "rectangular cheese block at the innermost",
        "rectangular cheese furthest inside",
        "innermost rectangular cheese",
        "innermost rectangular piece of cheese",
        "rectangular cheese at the very back",
        "rectangular cheese located at the back",
    ],
    "Switzerland Swiss Cheese": [
        "square cheese that is closest to you",
        "square cheese piece that is closest to you",
        "square cheese closest to you",
        "front square cheese",
    ],
    "Appenzeller Cheese": [
        "wedge-shaped cheese closest to you",
        "wedge-shaped cheese that is closest to you",
        "wedge of cheese closest to you",
        "wedge-shaped cheese piece that is closest to you",
        "front wedge-shaped cheese",
        "front wedge cheese",
    ],
}

RESTAURANT5_PATTERNS = [
    ("red strip horizontally across the rim", ["H"]),
    ("tuft of slender grass leaves", ["H"]),
    ("slender grass leaves", ["H"]),
    ("sprig of long thin grass leaves", ["H"]),
    ("middle of the top row", ["H"]),
    ("rectangular slice of bread", ["F"]),
    ("rectangular bread slice", ["F"]),
    ("bottom-left corner", ["F"]),
    ("bottom left of the left menu", ["F"]),
    ("bottom-left of the left menu", ["F"]),
    ("dark, long, thin stick", ["U"]),
    ("dark, long, thin stirrer", ["U"]),
    ("dark, long, thin pressure rod", ["U"]),
    ("middle of the bottom row", ["U"]),
    ("top-left corner", ["T"]),
    ("top left corner", ["T"]),
    ("distinct dark brown horizontal band", ["T"]),
    ("dark brown horizontal band", ["T"]),
    ("dark horizontal middle band", ["T"]),
    ("top right corner", ["E"]),
    ("top-right corner", ["E"]),
    ("cocktail in a stemmed glass", ["E"]),
    ("orange on the bottom and white on the top", ["E"]),
    ("stemmed cocktail", ["E"]),
    ("only beverage served in a stemmed cocktail glass", ["E"]),
    ("only drink served in a cocktail glass", ["E"]),
    ("only beverage served in a cocktail glass", ["E"]),
    ("bottom right corner", ["R"]),
    ("bottom-right corner", ["R"]),
    ("whole slice of dark citrus", ["R"]),
    ("whole dark citrus slice", ["R"]),
]

RESTAURANT5_SECONDARY_BY_TASK = {
    1: ["T"],
    2: ["E"],
    3: ["F"],
    4: ["H"],
    5: ["R"],
    6: ["H"],
    7: ["F"],
    8: ["R"],
    9: ["U"],
    10: ["H"],
    11: ["R"],
    12: ["E"],
    13: ["F"],
    14: ["H"],
    15: ["T"],
    16: ["R"],
    17: ["R"],
    18: ["H"],
    19: ["U"],
    20: ["T"],
    21: ["E"],
    22: ["E"],
    23: ["H"],
    24: ["U"],
    25: ["F"],
    26: ["F"],
    27: ["H"],
    28: ["U"],
    29: ["H"],
    30: ["H"],
    31: ["F"],
    32: ["E"],
    33: ["R"],
    34: ["E"],
    35: ["E"],
    36: ["U"],
    37: ["R"],
    38: ["T"],
    39: ["H"],
    40: ["T"],
    41: ["R"],
    42: ["E"],
    43: ["H"],
    44: ["F"],
    45: ["U"],
    46: ["T"],
    47: ["T"],
    48: ["T"],
    49: ["H"],
    50: ["R"],
}

KITCHEN4_SEQUENCE_PATTERNS = {
    "recipe": (
        "recipe_name",
        ["Pork & Chive Dumplings"],
        [
            "which recipe corresponds to the dish",
            "dish you are currently cooking",
            "dish you are currently preparing",
            "current recipe",
            "current dish",
            "dumpling recipe",
            "dumplings",
        ],
    ),
    "flour": (
        "ingredient_name",
        ["Flour"],
        [
            "white wrapper in your hand",
            "white wrapper",
            "white item",
            "item you are holding",
            "item in your hand",
            "flour wrapper",
            "wrapper",
        ],
    ),
    "garlic_chives": (
        "ingredient_name",
        ["Garlic Chives"],
        [
            "green vegetable in the basin",
            "green vegetable in the bowl",
            "green vegetables",
            "green vegetable",
            "green ingredient",
            "garlic chives",
        ],
    ),
    "pork": (
        "ingredient_name",
        ["Pork"],
        [
            "meat in the basin",
            "meat in the bowl",
            "meat ingredient",
            "meat",
            "pork",
        ],
    ),
    "garlic_and_pork": (
        "ingredient_name",
        ["Garlic Chives", "Pork"],
        [
            "green vegetable in the basin and the meat in the basin",
            "green vegetable and meat in the basin",
            "green vegetables and meat in the bowl",
        ],
    ),
    "garlic_and_flour": (
        "ingredient_name",
        ["Garlic Chives", "Flour"],
        [
            "green vegetable and the white item",
            "green vegetable in the basin and the white item",
        ],
    ),
    "pork_and_flour": (
        "ingredient_name",
        ["Pork", "Flour"],
        [
            "meat and the white wrapper",
            "meat in the basin and the white wrapper",
        ],
    ),
}

ORDER2_PATTERNS = [
    ("dish located at the top right of the first expanded page", ["Greek Village Roast Chicken Leg"]),
    ("dish in the top right corner of the first expanded page", ["Greek Village Roast Chicken Leg"]),
    ("top right of the first expanded page", ["Greek Village Roast Chicken Leg"]),
    ("top-right of the first expanded page", ["Greek Village Roast Chicken Leg"]),
    ("top right first expanded page", ["Greek Village Roast Chicken Leg"]),
    ("chicken and potatoes casserole", ["Greek Village Roast Chicken Leg"]),
    ("dish with dairy products and some nuts and fruits placed on a white plate", ["Vanilla pudding"]),
    ("dish that has dairy products and some nuts and fruit on a white plate", ["Vanilla pudding"]),
    ("dish with dairy products and some nuts and fruits on a white plate", ["Vanilla pudding"]),
    ("dish featuring dairy products and some nuts and fruits served on a white plate", ["Vanilla pudding"]),
    ("image of dairy products and some nuts and fruits on a white plate", ["Vanilla pudding"]),
    ("dish with dairy products", ["Greek Yogurt with Honey & Nuts"]),
    ("dairy product", ["Greek Yogurt with Honey & Nuts"]),
    ("wooden bowl", ["Greek Yogurt with Honey & Nuts"]),
    ("white plate dessert", ["Vanilla pudding"]),
    ("bottom right of the sixth page", ["Vanilla pudding"]),
    ("bottom-right sixth-page white plate", ["Vanilla pudding"]),
    ("first dish in the right text list", ["Feta & Tomato Spaghetti"]),
    ("first item in the right text list", ["Feta & Tomato Spaghetti"]),
    ("first item in the text list on the right side of the 5th expanded page", ["Feta & Tomato Spaghetti"]),
    ("first item in the text list on the right page of the 5th expanded page", ["Feta & Tomato Spaghetti"]),
    ("first item in the right list", ["Feta & Tomato Spaghetti"]),
    ("second dish in the right text list", ["Octopus Spaghetti"]),
    ("second item in the right text list", ["Octopus Spaghetti"]),
    ("second item in the text list on the right side of the 5th expanded page", ["Octopus Spaghetti"]),
    ("second item in the text list on the right page of the 5th expanded page", ["Octopus Spaghetti"]),
    ("second item in the right list", ["Octopus Spaghetti"]),
    ("third dish in the right text list", ["Spaghetti Bolognese"]),
    ("third item in the right text list", ["Spaghetti Bolognese"]),
    ("third item in the text list on the right side of the 5th expanded page", ["Spaghetti Bolognese"]),
    ("third item in the text list on the right page of the 5th expanded page", ["Spaghetti Bolognese"]),
    ("last item in the text list on the right side of the 5th expanded page", ["Spaghetti Bolognese"]),
    ("third item in the right list", ["Spaghetti Bolognese"]),
    ("bright blue plate", ["Fried calamari"]),
    ("fried calamari", ["Fried calamari"]),
    ("dark blue casserole", ["Santarini Seafood Rice"]),
    ("seafood paella", ["Santarini Seafood Rice"]),
    ("seafood risotto", ["Santarini Seafood Rice"]),
    ("red seafood in a copper", ["Grilled Octopus"]),
    ("red seafood in copper", ["Grilled Octopus"]),
    ("copper-colored double-handled pot", ["Grilled Octopus"]),
    ("dish with a roasted vegetable skewer on that wooden cutting board", ["Grilled Fish"]),
    ("roasted vegetable skewer on that wooden cutting board", ["Grilled Fish"]),
    ("dish featuring a grilled vegetable skewer on that wooden cutting board", ["Grilled Fish"]),
    ("grilled vegetable skewer", ["Grilled Fish"]),
    ("wooden cutting board", ["Grilled Fish"]),
    ("dark grey plate", ["Greek Lamb Chops"]),
    ("dark gray plate", ["Greek Lamb Chops"]),
    ("greek lamb chops", ["Greek Lamb Chops"]),
    ("dish located above the dark blue casserole", ["Greek Lamb Chops"]),
]

ORDER2_LABEL_TO_VALUE = {
    "top right first expanded page / chicken and potatoes casserole": ["Greek Village Roast Chicken Leg"],
    "bright blue plate with fried items and lemon": ["Fried calamari"],
    "dark grey plate with white sauce dish": ["Greek Lamb Chops"],
    "dark blue casserole containing seafood / seafood paella": ["Santarini Seafood Rice"],
    "red seafood in copper double-handled pot": ["Grilled Octopus"],
    "grilled vegetable skewer on wooden cutting board": ["Grilled Fish"],
    "dairy product in wooden bowl": ["Greek Yogurt with Honey & Nuts"],
    "white plate dessert at bottom right of sixth page": ["Vanilla pudding"],
    "right list first item on fifth page": ["Feta & Tomato Spaghetti"],
    "right list second item on fifth page": ["Octopus Spaghetti"],
    "right list third item on fifth page": ["Spaghetti Bolognese"],
}

ORDER2_SEQUENCE_PATTERNS = {
    "top_right": (
        "dish_name",
        ["Greek Village Roast Chicken Leg"],
        [
            "dish located at the top right of the first expanded page",
            "dish in the top right corner of the first expanded page",
            "top right of the first expanded page",
            "top-right of the first expanded page",
            "top right first expanded page",
            "top-right first expanded page",
            "chicken and potatoes casserole",
            "top-right dish",
            "top right dish",
        ],
    ),
    "fried_calamari": (
        "dish_name",
        ["Fried calamari"],
        [
            "bright blue plate with fried items and lemon",
            "bright blue plate",
            "fried calamari",
        ],
    ),
    "lamb_chops": (
        "dish_name",
        ["Greek Lamb Chops"],
        [
            "dark grey plate with white sauce dish",
            "dark gray plate with white sauce dish",
            "dish served on a dark grey plate with a white sauce dish",
            "dish served on a dark gray plate with a white sauce dish",
            "dark grey plate",
            "dark gray plate",
            "greek lamb chops",
        ],
    ),
    "seafood_rice": (
        "dish_name",
        ["Santarini Seafood Rice"],
        [
            "dark blue casserole containing seafood",
            "deep blue casserole containing seafood",
            "deep blue casserole",
            "dark blue casserole",
            "seafood paella",
            "seafood rice",
            "seafood risotto",
        ],
    ),
    "octopus": (
        "dish_name",
        ["Grilled Octopus"],
        [
            "red seafood in a copper",
            "red seafood in copper",
            "copper-colored double-handled pot",
            "copper double-handled pot",
            "grilled octopus",
        ],
    ),
    "fish": (
        "dish_name",
        ["Grilled Fish"],
        [
            "dish with a roasted vegetable skewer on that wooden cutting board",
            "roasted vegetable skewer on that wooden cutting board",
            "grilled vegetable skewer on wooden cutting board",
            "dish featuring a grilled vegetable skewer on that wooden cutting board",
            "grilled vegetable skewer",
            "wooden cutting board",
            "grilled fish",
        ],
    ),
    "yogurt": (
        "dish_name",
        ["Greek Yogurt with Honey & Nuts"],
        [
            "dairy product served in a wooden bowl",
            "dish with dairy products served in a wooden bowl",
            "dairy product in a wooden bowl",
            "dairy product in wooden bowl",
            "wooden bowl",
            "greek yogurt",
            "circled dessert",
        ],
    ),
    "pudding": (
        "dish_name",
        ["Vanilla pudding"],
        [
            "dish with dairy products and some nuts and fruits placed on a white plate",
            "dish that has dairy products and some nuts and fruit on a white plate",
            "dish with dairy products and some nuts and fruits on a white plate",
            "dish featuring dairy products and some nuts and fruits served on a white plate",
            "image of dairy products and some nuts and fruits on a white plate",
            "white plate dessert at bottom right of sixth page",
            "dish served on a white plate located at the bottom right of the 6th expanded page",
            "dish in the white plate located at the bottom right of the 6th expanded page",
            "white plate located at the bottom right of the 6th expanded page",
            "bottom-right sixth-page white plate",
            "white plate dessert",
            "bottom right of the sixth page",
            "bottom-right of the sixth page",
            "vanilla pudding",
        ],
    ),
    "right_first": (
        "dish_name",
        ["Feta & Tomato Spaghetti"],
        [
            "first dish in the right text list",
            "first item in the right text list",
            "first item in right text list",
            "first item in the text list on the right side of the 5th expanded page",
            "first item in the text list on the right page of the 5th expanded page",
            "first item in the right list",
            "first item in right list",
            "previous item in the text list",
            "right text list first item",
            "feta & tomato spaghetti",
        ],
    ),
    "right_second": (
        "dish_name",
        ["Octopus Spaghetti"],
        [
            "second dish in the right text list",
            "second item in the right text list",
            "second item in right text list",
            "second item in the text list on the right side of the 5th expanded page",
            "second item in the text list on the right page of the 5th expanded page",
            "second item in the right list",
            "second item in right list",
            "right text list second item",
            "octopus spaghetti",
        ],
    ),
    "right_third": (
        "dish_name",
        ["Spaghetti Bolognese"],
        [
            "third dish in the right text list",
            "third item in the right text list",
            "third item in right text list",
            "third item in the text list on the right side of the 5th expanded page",
            "third item in the text list on the right page of the 5th expanded page",
            "last item in the text list on the right side of the 5th expanded page",
            "third item in the right list",
            "third item in right list",
            "right text list third item",
            "spaghetti bolognese",
        ],
    ),
}

ORDER2_NO_VISUAL_SPECIALS: dict[int, list[str]] = {}


def retail6_values(instruction: str, task_id: int) -> list[str]:
    text = clean(instruction)
    multi = {
        32: ["heart", "second"],
        33: ["heart", "second"],
        42: ["heart", "second", "third"],
        44: ["heart", "second", "third"],
        46: ["heart", "second", "third"],
        48: ["heart", "second", "third"],
        49: ["red", "third"],
    }
    if task_id in multi:
        return [RETAIL6[k] for k in multi[task_id]]
    patterns = [
        ("yellow-packaged", [RETAIL6["yellow"]]),
        ("yellow packaged", [RETAIL6["yellow"]]),
        ("red lid", [RETAIL6["red"]]),
        ("cylindrical", [RETAIL6["red"]]),
        ("second chocolate", [RETAIL6["second"]]),
        ("second cookie", [RETAIL6["second"]]),
        ("second picked-up chocolate", [RETAIL6["second"]]),
        ("second picked item", [RETAIL6["second"]]),
        ("third box of white-packaged", [RETAIL6["third"]]),
        ("third box of white", [RETAIL6["third"]]),
        ("third white-packaged", [RETAIL6["third"]]),
        ("third picked box", [RETAIL6["third"]]),
        ("heart-shaped", [RETAIL6["heart"]]),
        ("first item picked", [RETAIL6["heart"]]),
        ("first picked item", [RETAIL6["heart"]]),
        ("first picked-up item", [RETAIL6["heart"]]),
    ]
    return first_match(text, patterns, "retail6", task_id)


def retail6_secondary_values(instruction: str, primary_values: list[str]) -> list[str]:
    sequence = visual_sequence(instruction, RETAIL6_SEQUENCE_PATTERNS, RETAIL6)
    return secondary_values_from_sequence(sequence, primary_values)


def retail10_values(instruction: str, task_id: int) -> list[str]:
    return first_match(clean(instruction), RETAIL10_PATTERNS, "retail10", task_id)


def retail10_secondary_values(instruction: str, primary_values: list[str]) -> list[str]:
    sequence = visual_sequence(instruction, RETAIL10_SEQUENCE_PATTERNS)
    return secondary_values_from_sequence(sequence, primary_values)


def kitchen4_anchor(instruction: str, task_id: int) -> tuple[str, list[str]]:
    text = clean(instruction)
    if ("green" in text and "meat" in text) and (
        "identify" in text or "specific ingredient" in text or "specific ingredients" in text
    ):
        return "ingredient_name", ["Garlic Chives", "Pork"]
    if ("green" in text and ("white item" in text or "white wrapper" in text)) and "identify" in text:
        return "ingredient_name", ["Garlic Chives", "Flour"]
    if ("meat" in text and ("white item" in text or "white wrapper" in text)) and "identify" in text:
        return "ingredient_name", ["Pork", "Flour"]
    if "white wrapper" in text or "white item" in text or "item you are holding" in text or "item in your hand" in text:
        return "ingredient_name", ["Flour"]
    if "green vegetable" in text or "green vegetables" in text or "green ingredient" in text or "vegetable category" in text:
        return "ingredient_name", ["Garlic Chives"]
    if "meat in the bowl" in text or "meat in the basin" in text or "ingredient of the meat" in text or "ingredient in the mixture" in text:
        return "ingredient_name", ["Pork"]
    if "which recipe" in text or "which dish" in text or "dish you are currently" in text or "dish you are preparing" in text:
        return "recipe_name", ["Pork & Chive Dumplings"]
    raise ValueError(f"kitchen4 task {task_id}: no visual anchor pattern matched")


def kitchen4_secondary_anchor(
    instruction: str,
    primary_key: str,
    primary_values: list[str],
) -> tuple[str | None, list[str]]:
    sequence = typed_visual_sequence(instruction, KITCHEN4_SEQUENCE_PATTERNS)
    key, values = secondary_anchor_from_typed_sequence(sequence, primary_key, primary_values)
    return key, values


def restaurant5_values(instruction: str, task_id: int) -> list[str]:
    return first_match(clean(instruction), RESTAURANT5_PATTERNS, "restaurant5", task_id)


def restaurant5_secondary_values(task_id: int) -> list[str]:
    return RESTAURANT5_SECONDARY_BY_TASK.get(task_id, [])


def order2_values(instruction: str, task_id: int) -> list[str]:
    # The reviewed order2 GT builder already records the menu visual anchor in
    # each task branch. Reuse that as the authoritative source, with a small
    # fallback for tasks that begin from textual restaurant/menu preferences.
    src = (Path(__file__).parent / "build_order2_gt.py").read_text(encoding="utf-8")
    starts = list(re.finditer(r"\n\s+(?:if|elif) task_id == (\d+):", src))
    for i, match in enumerate(starts):
        if int(match.group(1)) != task_id:
            continue
        end = starts[i + 1].start() if i + 1 < len(starts) else src.find("\n    else:", match.end())
        block = src[match.end():end]
        labels = re.findall(r'anchor = VISUAL\["([^"]+)"\]', block)
        if not labels:
            labels = re.findall(r'VISUAL\["([^"]+)"\]', block)
        if labels:
            return ORDER2_LABEL_TO_VALUE[labels[0]]
        if task_id in ORDER2_NO_VISUAL_SPECIALS:
            return ORDER2_NO_VISUAL_SPECIALS[task_id]
        break
    return first_match(clean(instruction), ORDER2_PATTERNS, "order2", task_id)


def order2_secondary_anchor(
    instruction: str,
    primary_values: list[str],
) -> tuple[str | None, list[str]]:
    sequence = typed_visual_sequence(instruction, ORDER2_SEQUENCE_PATTERNS)
    key, values = secondary_anchor_from_typed_sequence(sequence, "dish_name", primary_values)
    return key, values


def patch_file(name: str) -> tuple[int, dict[str, int]]:
    path = SCENARIO_DIR / f"{name}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    patched = []
    for idx, task in enumerate(data, 1):
        secondary_key = None
        secondary_values = None
        if name == "retail6":
            key, values = "product_name", retail6_values(task["Instruction"], idx)
            secondary_key = "product_name"
            secondary_values = retail6_secondary_values(task["Instruction"], values)
        elif name == "retail10":
            key, values = "product_name", retail10_values(task["Instruction"], idx)
            secondary_key = "product_name"
            secondary_values = retail10_secondary_values(task["Instruction"], values)
        elif name == "kitchen4":
            key, values = kitchen4_anchor(task["Instruction"], idx)
            secondary_key, secondary_values = kitchen4_secondary_anchor(task["Instruction"], key, values)
        elif name == "restaurant5":
            key, values = "dish_name", restaurant5_values(task["Instruction"], idx)
            secondary_key = "dish_name"
            secondary_values = restaurant5_secondary_values(idx)
        elif name == "order2":
            key, values = "dish_name", order2_values(task["Instruction"], idx)
            secondary_key, secondary_values = order2_secondary_anchor(task["Instruction"], values)
        else:
            raise ValueError(name)
        if secondary_key is None:
            secondary_key = key
            secondary_values = []
        counts[key] = counts.get(key, 0) + 1
        patched.append(
            with_anchor(
                task,
                key,
                values,
                secondary_key=secondary_key,
                secondary_values=secondary_values,
            )
        )
    path.write_text(json.dumps(patched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(patched), counts


def main() -> None:
    for name in ["retail6", "retail10", "kitchen4", "restaurant5", "order2"]:
        total, counts = patch_file(name)
        print(f"{name}: patched {total} tasks; keys={counts}")


if __name__ == "__main__":
    main()
