#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.kitchen.kitchen_init import kitchen_init_data


SCENARIO = ROOT / "scenarios/final/kitchen4.json"
AUDIT = ROOT / "experiments/visual_observer_runner/eval/kitchen4_gt_v1_audit.md"

CURRENT_RECIPE = "pork & chive dumplings"
CURRENT_STEP = 3
VISUAL = {
    "dish currently being cooked": "pork & chive dumplings",
    "white wrapper in hand": "flour",
    "green vegetable in basin/bowl": "garlic chives",
    "meat in basin/bowl": "pork",
}

ING: dict[str, dict] = {i["name"].lower(): i for i in kitchen_init_data["ingredients"]}
REC: dict[str, dict] = {r["name"].lower(): r for r in kitchen_init_data["recipes"]}
RECIPE_ORDER = [r["name"].lower() for r in kitchen_init_data["recipes"]]
ING_ORDER = [i["name"].lower() for i in kitchen_init_data["ingredients"]]
DISPLAY_ING = {k: v["name"] for k, v in ING.items()}
DISPLAY_REC = {k: v["name"] for k, v in REC.items()}


def ing(name: str) -> dict:
    return ING[name.lower()]


def rec(name: str) -> dict:
    return REC[name.lower()]


def category(name: str) -> str:
    # Custom Seasoned Noodles references Chili Flakes, which is not in the ingredient catalog.
    return ING.get(name.lower(), {"category": "seasoning"})["category"].lower()


def location(name: str) -> str | None:
    return ING.get(name.lower(), {"storage_location": "spice_rack"})["storage_location"]


def nutrition_ing(name: str, field: str) -> float:
    return float(ing(name)["nutrition"].get(field) or 0)


def nutrition_rec(name: str, field: str) -> float:
    return float(rec(name)["nutrition"].get(field) or 0)


def expiry(name: str) -> date | None:
    value = ING.get(name.lower(), {}).get("expiry_date")
    return date.fromisoformat(value) if value else None


def stock(name: str) -> float:
    return float(ING.get(name.lower(), {}).get("quantity") or 0)


def recipe_ingredients(name: str) -> list[dict]:
    return rec(name)["ingredients"]


def recipe_contains_ingredient(recipe: str, ingredient: str) -> bool:
    return any(i["ingredient_name"].lower() == ingredient.lower() for i in recipe_ingredients(recipe))


def has_allergen(recipe: str, allergen: str) -> bool:
    return allergen.lower() in [a.lower() for a in rec(recipe)["allergens"]]


def has_taste(recipe: str, taste: str) -> bool:
    return taste.lower() in [t.lower() for t in rec(recipe)["taste"]]


def has_tag(recipe: str, tag: str) -> bool:
    return tag.lower() in [t.lower() for t in rec(recipe)["nutritional_characteristics"]]


def recipes(pred: Callable[[str], bool]) -> list[str]:
    return [r for r in RECIPE_ORDER if pred(r)]


def ingredients(pred: Callable[[str], bool]) -> list[str]:
    return [i for i in ING_ORDER if pred(i)]


def ties(cands: list[str], key: Callable[[str], float], reverse: bool = False) -> list[str]:
    if not cands:
        return []
    vals = [(key(x), x) for x in cands]
    best = max(v for v, _ in vals) if reverse else min(v for v, _ in vals)
    return [x for v, x in vals if v == best]


def count_recipe_cat(recipe: str, cat: str) -> int:
    return sum(1 for i in recipe_ingredients(recipe) if category(i["ingredient_name"]) == cat)


def sum_recipe_cat(recipe: str, cat: str) -> float:
    return sum(float(i["quantity"]) for i in recipe_ingredients(recipe) if category(i["ingredient_name"]) == cat)


def count_recipe_loc(recipe: str, loc: str) -> int:
    return sum(1 for i in recipe_ingredients(recipe) if location(i["ingredient_name"]) == loc)


def sum_recipe_loc(recipe: str, loc: str) -> float:
    return sum(float(i["quantity"]) for i in recipe_ingredients(recipe) if location(i["ingredient_name"]) == loc)


def step_count(recipe: str) -> int:
    return len(rec(recipe)["steps"])


def same_taste_as_current(recipe: str) -> bool:
    return bool(set(rec(recipe)["taste"]) & set(rec(CURRENT_RECIPE)["taste"]))


def same_tag_count(recipe: str, other: str = CURRENT_RECIPE) -> int:
    return len(set(rec(recipe)["nutritional_characteristics"]) & set(rec(other)["nutritional_characteristics"]))


def call(tool_name: str, **parameters) -> dict:
    return {"tool_name": tool_name, "parameters": parameters}


class Builder:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.calls: list[dict] = []
        self.notes: list[str] = []
        self.menu: list[str] = []
        self.shopping: OrderedDict[str, float] = OrderedDict()

        for m in kitchen_init_data["user_menus"]:
            if m["user_id"] == user_id:
                self.menu = [r.lower() for r in m["recipes"]]
        for s in kitchen_init_data["user_shopping_lists"]:
            if s["user_id"] == user_id:
                self.shopping = OrderedDict((i["ingredient_name"].lower(), float(i["quantity"])) for i in s["items"])

    def add_recipe(self, items: list[str] | str, reason: str = "") -> None:
        if isinstance(items, str):
            items = [items]
        for item in items:
            self.calls.append(call("add_recipe_to_menu", user_id=self.user_id, recipe_name=DISPLAY_REC[item]))
            if item not in self.menu:
                self.menu.append(item)
            if reason:
                self.notes.append(f"add recipe {DISPLAY_REC[item]}: {reason}")

    def remove_recipe(self, item: str, reason: str = "") -> None:
        if item in self.menu:
            self.calls.append(call("remove_recipe_from_menu", user_id=self.user_id, recipe_name=DISPLAY_REC[item]))
            self.menu.remove(item)
            if reason:
                self.notes.append(f"remove recipe {DISPLAY_REC[item]}: {reason}")

    def add_item(self, item: str, qty: float, reason: str = "") -> None:
        self.calls.append(call("add_to_shopping_list", user_id=self.user_id, ingredient_name=DISPLAY_ING.get(item, item.title()), quantity=qty))
        self.shopping[item] = self.shopping.get(item, 0) + qty
        if reason:
            self.notes.append(f"add item {DISPLAY_ING.get(item, item)} x{qty:g}: {reason}")

    def remove_item(self, item: str, reason: str = "") -> None:
        if item in self.shopping:
            self.calls.append(call("remove_from_shopping_list", user_id=self.user_id, ingredient_name=DISPLAY_ING.get(item, item.title())))
            del self.shopping[item]
            if reason:
                self.notes.append(f"remove item {DISPLAY_ING.get(item, item)}: {reason}")

    def set_item_qty(self, item: str, qty: float, reason: str = "") -> None:
        self.remove_item(item, reason + " reset")
        self.add_item(item, qty, reason)

    def compute(self) -> None:
        self.calls.append(
            call(
                "compute_total_nutritions",
                user_id=self.user_id,
                ingredients=[
                    {"ingredient_name": DISPLAY_ING.get(i, i.title()), "quantity": int(q) if q == int(q) else q}
                    for i, q in self.shopping.items()
                ],
            )
        )

    def tally_tastes(self) -> None:
        self.calls.append(call("tally_total_tastes", user_id=self.user_id, recipes=[DISPLAY_REC[r] for r in self.menu]))

    def tally_tags(self) -> None:
        self.calls.append(call("tally_total_nutritional_characteristics", user_id=self.user_id, recipes=[DISPLAY_REC[r] for r in self.menu]))

    def add_recipe_ingredients_by(self, pred: Callable[[str], bool], mult: float = 1, reason: str = "") -> None:
        for r in list(self.menu):
            for item in recipe_ingredients(r):
                name = item["ingredient_name"].lower()
                if name in ING and pred(name):
                    self.add_item(name, float(item["quantity"]) * mult, reason or f"from {DISPLAY_REC[r]}")

    def final_order(self) -> str:
        return (
            "menu=[" + ", ".join(DISPLAY_REC[r] for r in self.menu) + "]; shopping=["
            + ", ".join(f"{DISPLAY_ING.get(i, i)} x{q:g}" for i, q in self.shopping.items())
            + "]"
        )


def expired_before(name: str, d: date) -> bool:
    e = expiry(name)
    return e is not None and e < d


def pantry_soonest() -> list[str]:
    cands = ingredients(lambda i: location(i) == "pantry" and expiry(i) is not None)
    return ties(cands, lambda i: expiry(i).toordinal())


def build_task(task_id: int) -> Builder | None:
    users = {
        1: "cook_001", 2: "cook_004", 3: "cook_006", 4: "cook_003", 5: "cook_005",
        6: "cook_001", 7: "cook_002", 8: "cook_010", 9: "cook_008", 10: "cook_009",
        11: "cook_007", 12: "cook_002", 13: "cook_004", 14: "cook_005", 15: "cook_003",
        16: "cook_006", 17: "cook_010", 18: "cook_009", 19: "cook_008", 20: "cook_007",
        21: "cook_003", 22: "cook_001", 23: "cook_007", 24: "cook_008", 25: "cook_005",
        26: "cook_002", 27: "cook_002", 28: "cook_007", 29: "cook_008", 30: "cook_001",
        31: "cook_004", 32: "cook_005", 33: "cook_009", 34: "cook_006", 35: "cook_010",
        36: "cook_003", 37: "cook_007", 38: "cook_001", 39: "cook_002", 40: "cook_008",
        41: "cook_005", 42: "cook_004", 43: "cook_006", 44: "cook_010", 45: "cook_009",
        46: "cook_010", 47: "cook_006", 48: "cook_004", 49: "cook_009", 50: "cook_003",
    }
    b = Builder(users[task_id])

    if task_id == 1:
        b.add_recipe(ties(recipes(lambda r: has_allergen(r, "eggs")), lambda r: nutrition_rec(r, "calories_kcal"), True), "current dumpling recipe contains soy")
        b.add_recipe_ingredients_by(lambda i: category(i) == "carbs/grains" and stock(i) == 0, reason="out-of-stock dry good in menu")
        b.tally_tastes()
    elif task_id == 2:
        b.add_recipe(ties(recipes(lambda r: not recipe_contains_ingredient(r, "flour")), step_count), "flour wrapper is not expired")
        for r in list(b.menu):
            if has_allergen(r, "fish"):
                b.remove_recipe(r, "remove fish allergen")
        b.compute()
    elif task_id == 3:
        b.add_item(ties(ingredients(lambda i: category(i) == "seasoning"), lambda i: nutrition_ing(i, "sodium_mg"))[0], 2, "garlic chives sugar <= 5")
        for i in list(b.shopping):
            if category(i) == "drinks":
                b.remove_item(i, "remove drink item")
        b.compute()
    elif task_id == 4:
        b.add_recipe(ties(recipes(same_taste_as_current), lambda r: len(recipe_ingredients(r))), "current recipe is high_protein")
        b.add_recipe_ingredients_by(lambda i: expired_before(i, date(2026, 5, 8)), reason="expired ingredient in menu")
        b.tally_tags()
    elif task_id == 5:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "vegan")), lambda r: nutrition_rec(r, "calories_kcal")), "dumpling step count is not greater than 5")
        b.add_recipe_ingredients_by(lambda i: category(i) == "carbs/grains" and location(i) == "pantry" and stock(i) < 0, reason="insufficient pantry dry good")
        b.tally_tags()
    elif task_id == 6:
        b.add_recipe([]) if False else None
        for i in ties(ingredients(lambda x: category(x) == "meat"), stock):
            b.add_item(i, 10, "pork calories > 200; lowest stock meat")
        for i in list(b.shopping):
            if expired_before(i, date(2026, 5, 8)):
                b.remove_item(i, "expired shopping item")
        b.compute()
    elif task_id == 7:
        b.add_item(ties(ingredients(lambda i: category(i) == "fruits"), lambda i: nutrition_ing(i, "fiber_g"), True)[0], 10, "pork is not in freezer")
        cutoff = date(2026, 5, 7) + timedelta(days=7)
        for i in list(b.shopping):
            e = expiry(i)
            if e and e > cutoff:
                b.remove_item(i, "more than one week away from expiration")
        b.compute()
    elif task_id == 8:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "high_sodium")), lambda r: count_recipe_cat(r, "carbs/grains")), "dumplings include umami")
        b.add_recipe_ingredients_by(lambda i: stock(i) < next((float(x["quantity"]) for r in b.menu for x in recipe_ingredients(r) if x["ingredient_name"].lower() == i), 0), reason="stock lower than recipe requirement")
        b.compute()
    elif task_id == 9:
        cands = recipes(lambda r: not (set(rec(r)["taste"]) & set(rec(CURRENT_RECIPE)["taste"])))
        b.add_recipe(ties(cands, lambda r: sum_recipe_cat(r, "meat")), "previous step used seasoning")
        b.add_recipe_ingredients_by(lambda i: expiry(i) is not None and expiry(i) < date(2026, 5, 16), reason="expires within three days from today")
        b.compute()
    elif task_id == 10:
        b.add_recipe(ties(recipes(lambda r: recipe_contains_ingredient(r, "garlic chives") or recipe_contains_ingredient(r, "flour")), lambda r: nutrition_rec(r, "sugar_g")), "garlic chives and flour stored differently")
        for i in list(b.shopping):
            if category(i) == "fruits":
                b.add_item(i, 5, "increase fruit item by 500g")
        b.tally_tags()
    elif task_id == 11:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "high_fiber")), lambda r: nutrition_rec(r, "carbs_g")), "pork inventory is not below 500g")
        b.add_recipe_ingredients_by(lambda i: location(i) == "fridge", reason="fridge ingredient used by menu")
        b.tally_tastes()
    elif task_id == 12:
        b.add_recipe(ties(recipes(lambda r: has_taste(r, "sweet")), lambda r: count_recipe_loc(r, "freezer"), True), "current recipe contains gluten")
        vegs = [i["ingredient_name"].lower() for r in b.menu for i in recipe_ingredients(r) if category(i["ingredient_name"]) == "vegetable"]
        low = ties(list(dict.fromkeys(vegs)), stock)
        for i in low:
            req = sum(float(x["quantity"]) for r in b.menu for x in recipe_ingredients(r) if x["ingredient_name"].lower() == i)
            b.add_item(i, req * 2, "lowest-stock vegetable in menu, double required")
        b.tally_tastes()
    elif task_id == 13:
        b.add_recipe(ties(recipes(lambda r: not rec(r)["allergens"]), lambda r: nutrition_rec(r, "protein_g"), True), "no_additives tag absent")
        b.add_recipe_ingredients_by(lambda i: expired_before(i, date(2026, 5, 10)), reason="ingredient expires before May 10")
        b.compute()
    elif task_id == 14:
        b.add_recipe(ties(recipes(lambda r: sum_recipe_cat(r, "dairy/egg/soy") > 0), lambda r: nutrition_rec(r, "sodium_mg"), True), "combined pork and flour stock is not below 1000g")
        for i in sorted({x["ingredient_name"].lower() for r in b.menu for x in recipe_ingredients(r) if category(x["ingredient_name"]) == "carbs/grains" and location(x["ingredient_name"]) == "pantry"}):
            b.add_item(i, 5, "dry ingredient in storage cabinet")
        b.tally_tastes()
    elif task_id == 15:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "high_calcium")), lambda r: sum_recipe_cat(r, "fruits"), True), "garlic chives are not on countertop")
        for i in list(b.shopping):
            if location(i) == "fridge":
                b.remove_item(i, "clear refrigerated shopping item")
        b.tally_tags()
    elif task_id == 16:
        b.add_item(ties(ingredients(lambda i: category(i) == "vegetable"), lambda i: nutrition_ing(i, "carbs_g"), True)[0], 4, "current step is not final")
        for i in list(b.shopping):
            if i in {"soy sauce", "tofu"}:
                b.remove_item(i, "soy source ingredient")
        b.compute()
    elif task_id == 17:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "low_fat")), lambda r: count_recipe_cat(r, "vegetable"), True), "dumplings taste savory")
        b.add_item("orange juice", 20, "menu has no drink ingredient")
        b.compute()
    elif task_id == 18:
        b.add_recipe(ties(recipes(lambda r: has_allergen(r, "dairy")), step_count), "garlic chives do not expire after May 10")
        b.add_recipe_ingredients_by(lambda i: stock(i) < 1, reason="menu ingredient stock below 100g")
        b.tally_tastes()
    elif task_id == 19:
        b.add_item(ties(ingredients(lambda i: location(i) != "countertop" and category(i) == "seasoning"), lambda i: nutrition_ing(i, "sodium_mg"))[0], 3, "flour is a dry good")
        for r in list(b.menu):
            if has_taste(r, "sweet"):
                b.remove_recipe(r, "remove sweet recipe")
        b.compute()
    elif task_id == 20:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "high_fat")), lambda r: sum_recipe_cat(r, "meat")), "dumplings are not low_fat")
        for i in sorted({x["ingredient_name"].lower() for r in b.menu[-1:] for x in recipe_ingredients(r) if location(x["ingredient_name"]) == "fridge" and stock(x["ingredient_name"]) == 14}):
            req = sum(float(x["quantity"]) for r in b.menu[-1:] for x in recipe_ingredients(r) if x["ingredient_name"].lower() == i)
            b.add_item(i, req, "fridge ingredient with stock 14 in newly added recipe")
        b.tally_tags()
    elif task_id == 21:
        b.add_item(ties(ingredients(lambda i: category(i) == "carbs/grains"), lambda i: nutrition_ing(i, "fiber_g"))[0], 5, "dumplings have no fish allergen")
        for r in list(b.menu):
            if has_taste(r, "sour"):
                b.remove_recipe(r, "remove sour recipe")
        b.add_item(pantry_soonest()[0], 10, "no expired pantry ingredient; add soonest-expiring pantry item")
        b.compute()
    elif task_id == 22:
        b.add_item(ties(ingredients(lambda i: category(i) == "meat"), lambda i: nutrition_ing(i, "calories_kcal"))[0], 10, "pork fat <= 20")
        for r in list(b.menu):
            if has_allergen(r, "dairy"):
                b.remove_recipe(r, "remove dairy recipe")
        for i in ingredients(lambda x: location(x) == "countertop" and expiry(x) and date(2026, 5, 9) <= expiry(x) <= date(2026, 5, 11)):
            b.add_item(i, 2, "countertop ingredient within two days of expiration")
        b.compute()
    elif task_id == 23:
        b.add_recipe(ties(recipes(lambda r: has_taste(r, "sweet") and same_tag_count(r) >= 2), lambda r: nutrition_rec(r, "protein_g"), True), "flour is a dry good")
        for i in list(b.shopping):
            if location(i) == "spice_rack":
                b.remove_item(i, "remove spice-rack shopping item")
        b.add_recipe_ingredients_by(lambda i: category(i) == "vegetable" and stock(i) == 0, reason="out-of-stock vegetable required by menu")
        b.tally_tastes()
    elif task_id == 24:
        b.add_recipe(ties(recipes(lambda r: has_allergen(r, "soy")), lambda r: nutrition_rec(r, "calories_kcal")), "previous step used seasonings")
        for i in list(b.shopping):
            if category(i) == "drinks":
                b.add_item(i, b.shopping[i], "double beverage quantity")
        for i in ingredients(lambda x: location(x) == "freezer" and stock(x) < 10):
            b.add_item(i, 8, "freezer stock below 10")
        b.tally_tags()
    elif task_id == 25:
        b.add_recipe(ties(recipes(lambda r: has_taste(r, "sour")), lambda r: sum_recipe_cat(r, "dairy/egg/soy"), True), "garlic chives are refrigerated")
        for i in list(b.shopping):
            if b.shopping[i] < 1:
                b.remove_item(i, "remove item below 100g")
        for i in sorted({x["ingredient_name"].lower() for r in b.menu for x in recipe_ingredients(r) if category(x["ingredient_name"]) == "meat"}):
            b.add_item(i, 5, "meat ingredient required by menu")
        b.tally_tastes()
    elif task_id == 26:
        b.add_recipe(ties(recipes(lambda r: has_allergen(r, "eggs")), lambda r: count_recipe_loc(r, "pantry"), True), "dumplings are not sweet")
        for i in list(b.shopping):
            if category(i) == "meat":
                b.add_item(i, 5, "increase meat shopping item by 500g")
        b.tally_tags() if False else b.compute()
    elif task_id == 27:
        b.add_recipe(ties(recipes(lambda r: has_allergen(r, "fish")), lambda r: count_recipe_cat(r, "carbs/grains"), True), "previous step used vegetable ingredients")
        for i in list(b.shopping):
            if location(i) == "fridge":
                b.remove_item(i, "delete refrigerated shopping item")
        b.add_recipe_ingredients_by(lambda i: category(i) == "fruits" and stock(i) < sum(float(x["quantity"]) for r in b.menu for x in recipe_ingredients(r) if x["ingredient_name"].lower() == i), reason="insufficient fruit for menu")
        b.tally_tastes()
    elif task_id == 28:
        b.add_item(ties(ingredients(lambda i: category(i) == "dairy/egg/soy"), lambda i: nutrition_ing(i, "protein_g"), True)[0], 10, "dumplings have no eggs allergen")
        for r in list(b.menu):
            if has_tag(r, "high_calories"):
                b.remove_recipe(r, "remove high_calories recipe")
        b.compute()
    elif task_id == 29:
        cands = recipes(lambda r: has_tag(r, "vegan") and not rec(r)["allergens"] and rec(r)["nutritional_characteristics"] == ["high_fiber"])
        b.add_recipe(ties(cands, step_count), "dumplings are not salty")
        for i in list(b.shopping):
            if location(i) == "pantry":
                b.add_item(i, 3, "increase storage-cabinet item by 300g")
        for r in list(b.menu):
            if has_allergen(r, "gluten"):
                b.remove_recipe(r, "remove gluten recipe")
        b.compute()
    elif task_id == 30:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "high_protein") and has_tag(r, "low_sugar")), step_count), "garlic chives sugar <= 10")
        for r in list(b.menu):
            if any(category(x["ingredient_name"]) == "fruits" for x in recipe_ingredients(r)):
                b.remove_recipe(r, "remove recipe requiring fruit")
        for i in ingredients(lambda x: location(x) == "countertop" and stock(x) < 10):
            b.add_item(i, 5, "countertop stock below 1000g")
        b.tally_tastes()
    elif task_id == 31:
        b.add_recipe(ties(recipes(lambda r: has_allergen(r, "gluten")), lambda r: count_recipe_loc(r, "fridge"), True), "dumplings are not low_sodium")
        for r in list(b.menu):
            if step_count(r) < 5:
                b.remove_recipe(r, "remove recipe with fewer than 5 steps")
        for i in list(b.shopping):
            if category(i) == "meat":
                b.remove_item(i, "delete meat item")
        b.compute()
    elif task_id == 32:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "low_fat")), step_count), "pork expiration is not later than May 12")
        for i in list(b.shopping):
            if category(i) == "dairy/egg/soy":
                b.remove_item(i, "delete egg/dairy/soy item")
        b.add_recipe_ingredients_by(lambda i: stock(i) == 0, reason="zero-stock menu ingredient")
        b.tally_tags()
    elif task_id == 33:
        cands = recipes(lambda r: not recipe_contains_ingredient(r, "pork") and not recipe_contains_ingredient(r, "garlic chives"))
        b.add_recipe(ties(cands, lambda r: nutrition_rec(r, "sodium_mg")), "pork + garlic chives stock > 1000g")
        for i in ingredients(lambda x: category(x) == "fruits" and expired_before(x, date(2026, 5, 9))):
            b.add_item(i, 10, "expired fruit at home")
        for i in list(b.shopping):
            if category(i) == "drinks" and location(i) == "fridge":
                b.remove_item(i, "remove refrigerated drink")
        b.tally_tastes()
    elif task_id == 34:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "high_fiber")), lambda r: nutrition_rec(r, "fat_g")), "flour is not expired before May 8")
        for i in list(b.shopping):
            if b.shopping[i] > 5:
                b.set_item_qty(i, b.shopping[i] / 2, "halve item over 500g")
        for i in ingredients(lambda x: category(x) == "seasoning" and location(x) == "spice_rack" and stock(x) < 5):
            b.add_item(i, 2, "spice-rack seasoning stock below 5")
        b.tally_tags()
    elif task_id == 35:
        b.add_item(ties(ingredients(lambda i: category(i) == "meat"), lambda i: nutrition_ing(i, "protein_g"), True)[0], 15, "pork is refrigerated")
        for r in list(b.menu):
            if has_allergen(r, "soy"):
                b.remove_recipe(r, "remove soy-allergen recipe")
        for i in sorted({x["ingredient_name"].lower() for r in b.menu for x in recipe_ingredients(r) if category(x["ingredient_name"]) == "carbs/grains" and not expired_before(x["ingredient_name"], date(2026, 5, 6))}):
            b.add_item(i, 5, "not-expired dry good in menu")
        b.compute()
    elif task_id == 36:
        b.add_recipe(ties(recipes(lambda r: has_taste(r, "sweet")), lambda r: count_recipe_cat(r, "seasoning")), "dumplings contain soy")
        for r in list(b.menu):
            if not rec(r)["allergens"]:
                b.remove_recipe(r, "clear empty-allergen recipe")
        for i in list(b.shopping):
            if category(i) == "dairy/egg/soy":
                b.set_item_qty(i, 8, "set egg/dairy/soy item to 800g")
        b.compute()
    elif task_id == 37:
        b.add_recipe(ties(recipes(lambda r: has_taste(r, "savory")), lambda r: count_recipe_cat(r, "vegetable"), True), "pork expires before May 9")
        for r in list(b.menu):
            if any(category(x["ingredient_name"]) == "carbs/grains" for x in recipe_ingredients(r)):
                b.remove_recipe(r, "remove recipe requiring dry goods")
        for i in ingredients(lambda x: category(x) == "seasoning" and location(x) == "spice_rack" and stock(x) == 0):
            b.add_item(i, 2, "zero-stock spice-rack seasoning")
        b.tally_tastes()
    elif task_id == 38:
        b.add_item(ties(ingredients(lambda i: location(i) == "pantry"), lambda i: nutrition_ing(i, "fiber_g"), True)[0], 8, "flour is not egg/dairy/soy")
        for i in list(b.shopping):
            if category(i) == "vegetable":
                b.remove_item(i, "delete vegetable shopping record")
        for r in list(b.menu):
            if has_allergen(r, "dairy"):
                b.remove_recipe(r, "remove dairy recipe")
        b.compute()
    elif task_id == 39:
        b.add_recipe(ties(recipes(lambda r: not rec(r)["allergens"]), lambda r: count_recipe_loc(r, "countertop")), "dumplings are not high_calories")
        for i in list(b.shopping):
            if location(i) == "spice_rack":
                b.remove_item(i, "remove spice-rack item")
        for i in ingredients(lambda x: category(x) == "fruits" and location(x) == "countertop" and expired_before(x, date(2026, 5, 6))):
            b.add_item(i, 10, "expired countertop fruit")
        b.compute()
    elif task_id == 40:
        b.add_recipe(ties(recipes(lambda r: has_tag(r, "high_calcium")), lambda r: count_recipe_cat(r, "dairy/egg/soy"), True), "dumplings are not mild")
        removed = False
        for r in list(b.menu):
            if has_allergen(r, "fish"):
                b.remove_recipe(r, "remove fish allergen")
                removed = True
        if not removed:
            for r in list(b.menu):
                if has_allergen(r, "gluten"):
                    b.remove_recipe(r, "fallback remove gluten allergen")
        for i in ingredients(lambda x: category(x) == "meat" and expired_before(x, date(2026, 5, 11))):
            b.add_item(i, 10, "expired meat before today")
        b.tally_tags()
    elif task_id == 41:
        b.add_item(ties(ingredients(lambda i: category(i) == "drinks"), lambda i: nutrition_ing(i, "calories_kcal"), True)[0], 5, "garlic chives are not on countertop")
        for i in list(b.shopping):
            if location(i) == "fridge":
                b.remove_item(i, "remove refrigerated shopping item")
        b.add_recipe_ingredients_by(lambda i: category(i) == "vegetable" and stock(i) == 0, reason="out-of-stock menu vegetable")
        b.compute()
    elif task_id == 42:
        b.add_recipe(ties(recipes(lambda r: has_taste(r, "sour")), lambda r: count_recipe_cat(r, "dairy/egg/soy")), "next step does not require freezer ingredients")
        for r in list(b.menu):
            if has_tag(r, "high_protein"):
                b.remove_recipe(r, "delete high_protein recipe")
        for i in list(b.shopping):
            if category(i) == "meat":
                b.set_item_qty(i, 10, "set meat shopping item to 1000g")
        b.tally_tags()
    elif task_id == 43:
        b.add_item(ties(ingredients(lambda i: category(i) == "fruits"), lambda i: nutrition_ing(i, "sugar_g"))[0], 20, "dumplings contain gluten")
        for i in list(b.shopping):
            if b.shopping[i] < 3:
                b.remove_item(i, "delete item below 300g")
        for r in list(b.menu):
            if recipe_contains_ingredient(r, "pork"):
                b.remove_recipe(r, "remove pork recipe")
        b.compute()
    elif task_id == 44:
        b.add_recipe(ties(recipes(lambda r: has_taste(r, "umami")), lambda r: nutrition_rec(r, "calories_kcal")), "garlic chives sodium < 50")
        for r in list(b.menu):
            if not rec(r)["allergens"]:
                b.remove_recipe(r, "remove recipe with no allergens")
        for i in ingredients(lambda x: category(x) == "drinks" and location(x) == "fridge" and expired_before(x, date(2026, 5, 12))):
            b.add_item(i, 5, "expired refrigerated drink")
        b.tally_tags()
    elif task_id == 45:
        b.add_recipe(ties(recipes(lambda r: has_taste(r, "sweet")), lambda r: nutrition_rec(r, "sodium_mg"), True), "pork is not in freezer")
        for i in list(b.shopping):
            if category(i) == "vegetable":
                b.remove_item(i, "remove vegetable item")
        for i in ingredients(lambda x: location(x) == "pantry" and expiry(x) and expiry(x) < date(2026, 7, 8)):
            b.add_item(i, 2, "pantry item expiring in less than two months")
        b.compute()
    elif task_id == 46:
        b.add_recipe(ties(recipes(lambda r: recipe_contains_ingredient(r, "pork") and recipe_contains_ingredient(r, "garlic chives")), lambda r: nutrition_rec(r, "fat_g")), "pork and garlic chives both expired before today")
        for i in list(b.shopping):
            if stock(i) > 13:
                b.remove_item(i, "home stock greater than 1300g")
        b.add_recipe_ingredients_by(lambda i: category(i) == "carbs/grains", reason="dry good used by menu")
        b.tally_tags()
    elif task_id == 47:
        b.add_recipe(ties(recipes(lambda r: not rec(r)["allergens"]), lambda r: nutrition_rec(r, "calories_kcal")), "dumplings are not vegan")
        for i in list(b.shopping):
            if category(i) == "carbs/grains":
                b.remove_item(i, "clear dry good from shopping list")
        b.add_recipe_ingredients_by(lambda i: expiry(i) is not None and expiry(i) < date(2026, 5, 10), mult=2, reason="expired menu ingredient, double recipe amount")
        b.compute()
    elif task_id == 48:
        b.add_item(ties(ingredients(lambda i: category(i) == "vegetable"), lambda i: nutrition_ing(i, "fiber_g"), True)[0], 8, "garlic chives calories < 50")
        for r in list(b.menu):
            if has_taste(r, "bitter"):
                b.remove_recipe(r, "remove bitter recipe")
        for i in ingredients(lambda x: category(x) == "seasoning" and location(x) == "spice_rack" and stock(x) < 2.5):
            b.add_item(i, 1, "spice-rack seasoning stock below 250g")
        b.compute()
    elif task_id == 49:
        b.add_recipe(ties(recipes(lambda r: has_allergen(r, "soy")), lambda r: count_recipe_cat(r, "seasoning")), "dumplings have no dairy allergen")
        for i in list(b.shopping):
            if location(i) == "freezer":
                b.set_item_qty(i, b.shopping[i] / 2, "halve freezer shopping item")
        for i in sorted({x["ingredient_name"].lower() for r in b.menu for x in recipe_ingredients(r) if category(x["ingredient_name"]) == "meat"}):
            b.add_item(i, 5, "meat ingredient required by menu")
        b.tally_tastes()
    elif task_id == 50:
        b.add_item(ties(ingredients(lambda i: location(i) == "countertop"), lambda i: nutrition_ing(i, "sodium_mg"))[0], 2, "flour stock is not below 100g")
        for r in list(b.menu):
            if has_tag(r, "high_fiber"):
                b.remove_recipe(r, "delete high_fiber recipe")
        for i in ingredients(lambda x: category(x) == "vegetable" and location(x) == "fridge" and expired_before(x, date(2026, 5, 12))):
            b.add_item(i, 5, "expired refrigerated vegetable")
        b.compute()
    else:
        return None

    return b


def main() -> None:
    data = json.loads(SCENARIO.read_text())
    rows = []
    generated = 0
    calls = 0
    for task in data:
        b = build_task(int(task["task_id"]))
        if not b:
            task.pop("ground_truth", None)
            continue
        task["ground_truth"] = b.calls
        generated += 1
        calls += len(b.calls)
        rows.append((task["task_id"], b.user_id, len(b.calls), "; ".join(b.notes), b.final_order()))

    SCENARIO.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    lines = [
        "# kitchen4 GT v1 audit",
        "",
        "## Visual mapping",
        "- The video `dumplings.mp4` shows a dumpling wrapping workflow.",
        "- Current recipe: `Pork & Chive Dumplings`.",
        "- Current action/step: step 3, `wrap dumplings`.",
        "- White wrapper: `Flour` dough wrapper.",
        "- Green vegetable in bowl/basin: `Garlic Chives`.",
        "- Meat in bowl/basin: `Pork`.",
        "",
        f"Generated {generated} / {len(data)} tasks with {calls} GT calls.",
        "",
        "| Task | User | Calls | Notes | Final state |",
        "|---:|---|---:|---|---|",
    ]
    for task_id, user, n_calls, notes, final in rows:
        lines.append(f"| {task_id} | {user} | {n_calls} | {notes} | {final} |")
    AUDIT.write_text("\n".join(lines) + "\n")
    print(f"Wrote {SCENARIO}")
    print(f"Wrote {AUDIT}")
    print(f"Generated {generated}/{len(data)} tasks, calls={calls}")


if __name__ == "__main__":
    main()
