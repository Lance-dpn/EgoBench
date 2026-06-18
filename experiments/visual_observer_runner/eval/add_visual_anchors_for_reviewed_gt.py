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

ORDER2_PATTERNS = [
    ("top right of the first expanded page", ["Greek Village Roast Chicken Leg"]),
    ("top-right of the first expanded page", ["Greek Village Roast Chicken Leg"]),
    ("top right first expanded page", ["Greek Village Roast Chicken Leg"]),
    ("chicken and potatoes casserole", ["Greek Village Roast Chicken Leg"]),
    ("dish with dairy products", ["Greek Yogurt with Honey & Nuts"]),
    ("dairy product", ["Greek Yogurt with Honey & Nuts"]),
    ("wooden bowl", ["Greek Yogurt with Honey & Nuts"]),
    ("white plate dessert", ["Vanilla pudding"]),
    ("bottom right of the sixth page", ["Vanilla pudding"]),
    ("bottom-right sixth-page white plate", ["Vanilla pudding"]),
    ("first dish in the right text list", ["Feta & Tomato Spaghetti"]),
    ("first item in the right text list", ["Feta & Tomato Spaghetti"]),
    ("first item in the right list", ["Feta & Tomato Spaghetti"]),
    ("second item in the right text list", ["Octopus Spaghetti"]),
    ("second item in the right list", ["Octopus Spaghetti"]),
    ("third item in the right text list", ["Spaghetti Bolognese"]),
    ("third item in the right list", ["Spaghetti Bolognese"]),
    ("bright blue plate", ["Fried calamari"]),
    ("fried calamari", ["Fried calamari"]),
    ("dark blue casserole", ["Santarini Seafood Rice"]),
    ("seafood paella", ["Santarini Seafood Rice"]),
    ("seafood risotto", ["Santarini Seafood Rice"]),
    ("red seafood in a copper", ["Grilled Octopus"]),
    ("red seafood in copper", ["Grilled Octopus"]),
    ("copper-colored double-handled pot", ["Grilled Octopus"]),
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

ORDER2_NO_VISUAL_SPECIALS = {
    12: ["Baklava"],
    89: ["Grilled Fish"],
    93: ["Santarini Seafood Rice", "Feta & Tomato Spaghetti", "Moussaka"],
}


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


def restaurant5_values(instruction: str, task_id: int) -> list[str]:
    return first_match(clean(instruction), RESTAURANT5_PATTERNS, "restaurant5", task_id)


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
        elif name == "restaurant5":
            key, values = "dish_name", restaurant5_values(task["Instruction"], idx)
        elif name == "order2":
            key, values = "dish_name", order2_values(task["Instruction"], idx)
        else:
            raise ValueError(name)
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
