#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.retail.retail_init import retail_init_data6

SCENARIO = ROOT / "scenarios/final/retail6.json"
AUDIT = ROOT / "experiments/visual_observer_runner/eval/retail6_gt_v1_audit.md"

DISPLAY = {p["name"].lower(): p["name"] for p in retail_init_data6["products"]}
PRODUCTS = {p["name"].lower(): p for p in retail_init_data6["products"]}
PRODUCT_ORDER = [p["name"].lower() for p in retail_init_data6["products"]]
LISTS = {
    row["user_id"]: [
        {"product_name": item["product_name"].lower(), "quantity": float(item["quantity"])}
        for item in row.get("items", [])
    ]
    for row in retail_init_data6["user_shopping_lists"]
}

VISUAL = {
    "first heart-shaped cookie": "st michel le palmier crispy caramel",
    "second chocolate cookie": "bahlsen",
    "third white-packaged cookie box": "desobry speculoos",
    "red-lid cylindrical cookie above third box": "nutella biscuits",
    "yellow-packaged cookie below third box": "leibniz keks",
}


def n(name: str, field: str) -> float:
    return float(PRODUCTS[name]["nutrition"][field])


def norm_origin(origin: str) -> str:
    aliases = {
        "denmark": "danmark",
        "danish": "danmark",
        "uk": "united kingdom",
        "britain": "united kingdom",
        "british": "united kingdom",
    }
    key = origin.lower()
    return aliases.get(key, key)


def is_origin(p: dict, *origins: str) -> bool:
    want = {norm_origin(o) for o in origins}
    return norm_origin(p["country_of_origin"]) in want


def has_taste(p: dict, taste: str) -> bool:
    return taste.lower() in [t.lower() for t in p["taste"]]


def has_tag(p: dict, tag: str) -> bool:
    aliases = {
        "high calorie": "high_calories",
        "high_calorie": "high_calories",
        "high calories": "high_calories",
        "high sugar": "high_sugar",
        "high fat": "high_fat",
        "high oil": "high_fat",
        "high protein": "high_protein",
        "low sodium": "low_sodium",
        "high sodium": "high_sodium",
    }
    key = aliases.get(tag.lower().replace("-", " "), tag.lower().replace("-", "_").replace(" ", "_"))
    return key in [x.lower() for x in p["nutritional_characteristics"]]


def has_allergen(p: dict, allergen: str) -> bool:
    values = {a.lower() for a in p.get("allergens", [])}
    key = allergen.lower()
    if key in {"nut", "nuts"}:
        return "nut" in values or "nuts" in values
    return key in values


def no_allergen(p: dict, allergen: str) -> bool:
    return not has_allergen(p, allergen)


def discounted(p: dict) -> bool:
    return p["discount"] < 1.0


def all_products(pred: Callable[[dict], bool]) -> list[str]:
    return [name for name in PRODUCT_ORDER if pred(PRODUCTS[name])]


def ties(names: list[str], key: Callable[[dict], float], reverse: bool = False) -> list[str]:
    if not names:
        return []
    values = [(key(PRODUCTS[name]), name) for name in names]
    best = max(v for v, _ in values) if reverse else min(v for v, _ in values)
    return [name for v, name in values if v == best]


def lowest_price(pred: Callable[[dict], bool]) -> list[str]:
    return ties(all_products(pred), lambda p: p["price"])


def highest_price(pred: Callable[[dict], bool]) -> list[str]:
    return ties(all_products(pred), lambda p: p["price"], True)


def best_discount(pred: Callable[[dict], bool]) -> list[str]:
    return ties(all_products(pred), lambda p: p["discount"])


def by_nutrition(pred: Callable[[dict], bool], field: str, reverse: bool = False) -> list[str]:
    return ties(all_products(pred), lambda p: float(p["nutrition"][field]), reverse)


def add_call(user_id: str, name: str, qty: float = 1) -> dict:
    p = PRODUCTS[name]
    return {
        "tool_name": "add_to_cart",
        "parameters": {
            "user_id": user_id,
            "product_name": DISPLAY[name],
            "qty": int(qty) if qty == int(qty) else qty,
            "category": p["category"],
            "price": p["price"],
            "tax_rate": p["tax_rate"],
            "discount": p["discount"],
        },
    }


def remove_call(user_id: str, name: str, qty: float) -> dict:
    return {
        "tool_name": "remove_from_cart",
        "parameters": {
            "user_id": user_id,
            "product_name": DISPLAY.get(name, name),
            "qty": int(qty) if qty == int(qty) else qty,
        },
    }


class TaskBuilder:
    def __init__(self, user_id: str, task_id: int):
        self.user_id = user_id
        self.task_id = task_id
        self.calls: list[dict] = []
        self.notes: list[str] = []
        self.cart: OrderedDict[str, float] = OrderedDict()
        for row in retail_init_data6["user_carts"]:
            if row["user_id"] == user_id:
                for item in row.get("items", []):
                    name = item["product_name"].lower()
                    if name in PRODUCTS:
                        self.cart[name] = float(item["quantity"])
                    else:
                        self.notes.append(f"skip uncatalogued initial cart item: {item['product_name']}")

    def note(self, text: str) -> None:
        self.notes.append(text)

    def add(self, names: list[str], qty: float = 1, reason: str = "") -> None:
        if not names:
            if reason:
                self.notes.append(f"no add: {reason} yielded no matching products")
            return
        for name in names:
            self.calls.append(add_call(self.user_id, name, qty))
            self.cart[name] = self.cart.get(name, 0) + float(qty)
            self.notes.append(f"add {DISPLAY[name]} x{qty:g}" + (f": {reason}" if reason else ""))

    def remove_names(self, names: list[str], reason: str) -> None:
        for name in names:
            if name in self.cart:
                qty = self.cart[name]
                self.calls.append(remove_call(self.user_id, name, qty))
                del self.cart[name]
                self.notes.append(f"remove {DISPLAY.get(name, name)} x{qty:g}: {reason}")

    def remove_if(self, pred: Callable[[dict], bool], reason: str) -> None:
        names = [name for name in self.cart if name in PRODUCTS and pred(PRODUCTS[name])]
        self.remove_names(names, reason)

    def clear(self, reason: str) -> None:
        self.calls.append({"tool_name": "clear_cart", "parameters": {"user_id": self.user_id}})
        self.cart.clear()
        self.notes.append(f"clear cart: {reason}")

    def add_list_missing(self, reason: str, pred: Callable[[dict], bool] | None = None, *, top_up: bool = False) -> None:
        pred = pred or (lambda p: True)
        for item in LISTS.get(self.user_id, []):
            name = item["product_name"]
            if name not in PRODUCTS or not pred(PRODUCTS[name]):
                continue
            target_qty = item["quantity"]
            current = self.cart.get(name, 0)
            qty = target_qty - current if top_up else target_qty
            if top_up:
                should_add = qty > 0
            else:
                should_add = current == 0
            if should_add and qty > 0:
                self.add([name], qty, reason)

    def cart_products(self) -> list[dict]:
        return [
            {"product_name": DISPLAY.get(name, name), "quantity": int(qty) if qty == int(qty) else qty}
            for name, qty in self.cart.items()
            if qty > 0
        ]

    def compute(self, kind: str) -> None:
        tool = {
            "payment": "compute_total_payment",
            "tax": "compute_total_tax",
            "nutrition": "compute_total_nutrition",
        }[kind]
        self.calls.append(
            {
                "tool_name": tool,
                "parameters": {"user_id": self.user_id, "products": self.cart_products()},
            }
        )
        self.notes.append(f"compute {kind} over {len(self.cart_products())} cart lines")

    def known_cart_names(self) -> list[str]:
        return [name for name in self.cart if name in PRODUCTS]

    def total_payment_unit_price(self) -> float:
        return sum(PRODUCTS[name]["price"] * qty for name, qty in self.cart.items() if name in PRODUCTS)

    def total_nutrition(self, field: str) -> float:
        return sum(n(name, field) * qty for name, qty in self.cart.items() if name in PRODUCTS)

    def avg_nutrition(self, field: str) -> float:
        qty = sum(qty for name, qty in self.cart.items() if name in PRODUCTS)
        return self.total_nutrition(field) / qty if qty else 0.0

    def avg_price(self) -> float:
        qty = sum(qty for name, qty in self.cart.items() if name in PRODUCTS)
        return self.total_payment_unit_price() / qty if qty else 0.0

    def remove_extreme_price(self, reverse: bool, reason: str) -> None:
        names = self.known_cart_names()
        chosen = ties(names, lambda p: p["price"], reverse)
        self.remove_names(chosen, reason)

    def remove_extreme_nutrition(self, field: str, reverse: bool, reason: str) -> None:
        names = self.known_cart_names()
        chosen = ties(names, lambda p: float(p["nutrition"][field]), reverse)
        self.remove_names(chosen, reason)


F = VISUAL["first heart-shaped cookie"]
S = VISUAL["second chocolate cookie"]
T = VISUAL["third white-packaged cookie box"]
R = VISUAL["red-lid cylindrical cookie above third box"]
Y = VISUAL["yellow-packaged cookie below third box"]


def build_task(task_id: int, user_id: str) -> TaskBuilder:
    b = TaskBuilder(user_id, task_id)
    first, second, third, red, yellow = PRODUCTS[F], PRODUCTS[S], PRODUCTS[T], PRODUCTS[R], PRODUCTS[Y]

    if task_id == 1:
        b.note("first heart cookie lacks nuts, so use red-lid fallback")
        b.add(lowest_price(lambda p: p["tax_rate"] < 0.10 and has_taste(p, "sweet")), reason="red-lid Nutella is high sugar")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("tax")
    elif task_id == 2:
        b.add(lowest_price(lambda p: p["category"] == "cookie" and has_tag(p, "high calorie")), reason="second Bahlsen is discounted and from Germany")
        b.compute("payment")
    elif task_id == 3:
        b.note("third Desobry protein is < 7 but price is not > 40, so inspect first cookie milk allergen")
        b.add(by_nutrition(lambda p: 0.7 <= p["discount"] <= 0.9 and has_taste(p, "sweet"), "calories_kcal", True), reason="first Palmier contains milk")
        b.compute("nutrition")
    elif task_id == 4:
        b.add(best_discount(lambda p: is_origin(p, "Italy") and 60 <= p["price"] <= 80), reason="red-lid Nutella is sweet and carbs exceed 60g")
        b.compute("nutrition")
    elif task_id == 5:
        b.note("yellow Leibniz is not from France and fat is not > 25, so use second-cookie sweet fallback")
        b.add(by_nutrition(lambda p: p["category"] == "cookie" and has_allergen(p, "nuts") and p["discount"] < 0.85, "calories_kcal"), reason="second Bahlsen is sweet")
        b.compute("payment")
    elif task_id == 6:
        italian_gluten_free = by_nutrition(lambda p: is_origin(p, "Italy") and no_allergen(p, "gluten"), "sodium_mg")
        b.add(italian_gluten_free or lowest_price(lambda p: is_origin(p, "Italy")), reason="first Palmier is high sugar and < 40; no gluten-free Italy item exists")
        b.compute("tax")
    elif task_id == 7:
        uk_milk_free = by_nutrition(lambda p: is_origin(p, "UK") and no_allergen(p, "milk"), "sugar_g")
        b.add(uk_milk_free or lowest_price(lambda p: is_origin(p, "UK") and has_allergen(p, "soy")), reason="red-lid Nutella is high calorie with sugar > 30")
        b.compute("nutrition")
    elif task_id == 8:
        b.note("yellow Leibniz tax is not higher than 0.08; third Desobry does not contain soy")
        b.add(highest_price(lambda p: has_allergen(p, "soy") and has_taste(p, "nutty")), reason="third white box lacks soy")
        b.compute("tax")
    elif task_id == 9:
        b.note("first Palmier is not bitter; second Bahlsen is from Germany")
        b.add(by_nutrition(lambda p: p["category"] == "cookie" and has_tag(p, "high oil") and p["tax_rate"] < 0.1, "calories_kcal", True), reason="second cookie origin is Germany")
        b.compute("payment")
    elif task_id == 10:
        b.add(by_nutrition(lambda p: 15 <= p["price"] <= 40 and has_taste(p, "bitter"), "protein_g", True), reason="third Desobry price is not below 25; red-lid Nutella sugar exceeds 20g")
        b.compute("tax")
    elif task_id == 11:
        b.note("second Bahlsen is not from France; yellow price is between 10 and 60")
        b.add(best_discount(lambda p: p["category"] == "cookie" and has_taste(p, "nutty") and is_origin(p, "Japan", "Germany", "Denmark")), reason="yellow price fallback")
        b.add_list_missing("soy-free list item absent from cart", lambda p: no_allergen(p, "soy"))
        b.compute("nutrition")
    elif task_id == 12:
        b.note("red-lid Nutella price is not below 25; first Palmier is high fat")
        b.add(lowest_price(lambda p: 0.05 <= p["tax_rate"] <= 0.1 and discounted(p)), qty=2, reason="first Palmier high-fat fallback")
        b.compute("payment")
    elif task_id == 13:
        b.add(lowest_price(lambda p: has_allergen(p, "gluten") and is_origin(p, "Italy")), reason="third Desobry contains nuts and exceeds 400 kcal")
        b.compute("tax")
    elif task_id == 14:
        b.add(by_nutrition(lambda p: has_taste(p, "nutty") and p["tax_rate"] < 0.1 and is_origin(p, "Italy"), "calories_kcal", True), reason="yellow Leibniz sugar does not exceed 30 and red-lid Nutella is not discounted better than 0.8")
        b.compute("nutrition")
    elif task_id == 15:
        b.note("second Bahlsen is not France; first Palmier is not Germany/Denmark/Japan")
        b.add(all_products(lambda p: has_tag(p, "low sodium") and is_origin(p, "France") and no_allergen(p, "soy")), reason="low-sodium France fallback without soy")
        b.compute("tax")
    elif task_id == 16:
        b.note("red-lid Nutella sugar is not > 35; third Desobry is not gluten-free")
        b.add(lowest_price(lambda p: 15 <= p["price"] <= 40 and has_taste(p, "minty")), reason="third white box contains gluten")
        b.compute("payment")
    elif task_id == 17:
        b.note("first Palmier discount is not < 0.85; yellow Leibniz fat does not exceed 20")
        b.compute("nutrition")
    elif task_id == 18:
        b.note("second Bahlsen fat is not < 20; third Desobry price is not > 40")
        b.add(lowest_price(lambda p: has_taste(p, "sweet") and has_taste(p, "bitter") and has_allergen(p, "soy")), reason="third price fallback")
        b.compute("payment")
    elif task_id == 19:
        b.note("red-lid Nutella calories are exactly 500, not > 500; yellow Leibniz lacks high-fat label")
        b.add(by_nutrition(lambda p: p["price"] > 40 and has_taste(p, "bitter"), "calories_kcal"), reason="yellow lacks high-fat label")
        b.compute("tax")
    elif task_id == 20:
        b.add(best_discount(lambda p: p["category"] == "cookie" and is_origin(p, "Germany", "Denmark", "Japan") and no_allergen(p, "nuts")), qty=2, reason="first Palmier is sweet and < 30")
        b.compute("payment")
    elif task_id == 21:
        b.note("third Desobry sugar does not exceed 40; yellow Leibniz contains soy")
        b.add(lowest_price(lambda p: has_taste(p, "nutty") and discounted(p)), reason="yellow contains soy")
        if b.avg_nutrition("calories_kcal") > 500:
            b.remove_extreme_nutrition("calories_kcal", True, "weighted average calories > 500")
        b.compute("tax")
    elif task_id == 22:
        b.note("red-lid Nutella is not discounted below 0.85; first Palmier is high calorie")
        b.add(best_discount(lambda p: p["tax_rate"] < 0.08 and has_tag(p, "high calorie")), reason="first high-calorie fallback")
        if b.total_payment_unit_price() > 50:
            b.remove_extreme_price(True, "cart unit-price total > 50")
        b.compute("tax")
    elif task_id == 23:
        b.note("second Bahlsen contains gluten and is outside France; third Desobry tax does not exceed 0.06")
        if b.total_nutrition("sugar_g") > 100:
            b.remove_extreme_nutrition("sugar_g", True, "total sugar > 100g")
        b.compute("payment")
    elif task_id == 24:
        b.add(by_nutrition(lambda p: has_tag(p, "high protein") and no_allergen(p, "soy"), "calories_kcal"), reason="yellow Leibniz fat < 20 and origin is Germany")
        if b.total_nutrition("calories_kcal") > 1000:
            b.remove_extreme_nutrition("fat_g", True, "total calories > 1000")
        b.compute("tax")
    elif task_id == 25:
        b.note("first Palmier is not Italy; third Desobry contains milk")
        b.add(best_discount(lambda p: has_taste(p, "sweet") and p["tax_rate"] < 0.08), reason="third milk-allergen fallback")
        if b.total_payment_unit_price() > 40:
            b.remove_extreme_price(True, "cart unit-price total > 40")
        b.compute("tax")
    elif task_id == 26:
        b.add(by_nutrition(lambda p: p["category"] == "cookie" and is_origin(p, "Japan", "Germany", "Denmark") and has_allergen(p, "nuts"), "calories_kcal", True), reason="second Bahlsen is sweet and carbs exceed 50")
        if b.total_nutrition("sugar_g") > 60:
            b.remove_extreme_nutrition("sugar_g", True, "total sugar > 60g")
        b.compute("payment")
    elif task_id == 27:
        b.note("red-lid Nutella is not below 400 kcal; first Palmier is high fat")
        b.add(by_nutrition(lambda p: has_taste(p, "nutty") and 15 <= p["price"] <= 40, "calories_kcal"), reason="first high-fat fallback")
        if b.total_payment_unit_price() > 30:
            b.remove_extreme_price(True, "cart unit-price total > 30")
        b.compute("tax")
    elif task_id == 28:
        b.add(lowest_price(lambda p: is_origin(p, "Denmark", "Japan", "Germany") and has_tag(p, "high sugar")), reason="yellow Leibniz is Germany with discount 0.9")
        if b.total_nutrition("fat_g") > 30:
            b.remove_extreme_nutrition("fat_g", True, "total fat > 30g")
        b.compute("payment")
    elif task_id == 29:
        b.note("second Bahlsen is not nutty and red-lid Nutella has no high-sodium label")
        if b.total_payment_unit_price() > 35:
            b.remove_extreme_price(True, "cart unit-price total > 35")
        b.compute("tax")
    elif task_id == 30:
        b.note("first Palmier is not high-protein and third Desobry is not bitter")
        if b.total_nutrition("protein_g") > 10:
            b.remove_extreme_nutrition("protein_g", True, "total protein > 10g")
        b.compute("payment")
    elif task_id == 31:
        b.add([F, T], reason="first is high sugar under 30 and third Desobry contains nuts")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("tax")
    elif task_id == 32:
        b.add([F, S], qty=2, reason="first price < 28 and second price < 35")
        b.compute("payment")
    elif task_id == 33:
        b.clear("first sugar > 30 and second origin is Germany")
        b.add(by_nutrition(lambda p: no_allergen(p, "soy"), "calories_kcal"), reason="similar soy-free lowest-calorie replacement")
        b.add_list_missing("unpurchased shopping-list item")
        if b.total_payment_unit_price() > 100:
            b.remove_extreme_price(True, "cart unit-price total > 100")
        b.compute("nutrition")
    elif task_id == 34:
        b.add(best_discount(lambda p: has_tag(p, "high protein") and 15 <= p["price"] <= 40), reason="yellow Leibniz protein is not < 7")
        b.add_list_missing("shopping-list item not fully purchased", top_up=True)
        b.compute("payment")
    elif task_id == 35:
        b.add([T], reason="first contains gluten and second is from Germany")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("tax")
    elif task_id == 36:
        b.add([T, Y], reason="third is sweet and yellow is from Germany")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("payment")
    elif task_id == 37:
        b.note("second Bahlsen is discounted, so search Germany/Denmark/Japan price range")
        b.add(lowest_price(lambda p: is_origin(p, "Germany", "Denmark", "Japan") and 15 <= p["price"] <= 40), reason="fallback country and price filter")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("nutrition")
    elif task_id == 38:
        b.add([S], reason="red-lid Nutella contains nuts and first Palmier is from France")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("payment")
    elif task_id == 39:
        b.add([T], reason="yellow contains gluten and second is from Germany")
        b.add_list_missing("unpurchased shopping-list item")
        b.compute("tax")
    elif task_id == 40:
        b.add(by_nutrition(lambda p: is_origin(p, "Denmark", "Japan", "Germany") and p["price"] < 40, "calories_kcal"), reason="first Palmier calories are not below 500")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("payment")
    elif task_id == 41:
        b.note("first Palmier contains gluten; red-lid Nutella lacks high-protein label")
        b.add(by_nutrition(lambda p: has_tag(p, "high protein") and has_taste(p, "bitter"), "sodium_mg"), reason="high-protein bitter fallback")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("nutrition")
        b.compute("tax")
    elif task_id == 42:
        b.add(by_nutrition(lambda p: is_origin(p, first["country_of_origin"]) and p["discount"] < 0.9 and p["tax_rate"] < 0.1, "protein_g", True), reason="cheapest picked item is Palmier but not under 20")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("payment")
    elif task_id == 43:
        b.note("yellow Leibniz sugar does not exceed 30")
        b.remove_if(lambda p: n(p["name"].lower(), "sugar_g") > 30 and p["name"].lower() not in {x["product_name"] for x in LISTS.get(b.user_id, [])}, "high-sugar item not on shopping list")
        b.compute("nutrition")
    elif task_id == 44:
        b.note("most expensive picked item is Desobry at 33.8, not > 40")
        b.add(best_discount(lambda p: has_taste(p, "sweet") and p["tax_rate"] < 0.1), reason="picked-item max price fallback")
        if b.avg_price() > 25:
            b.remove_extreme_price(True, "weighted average unit price > 25")
        b.compute("tax")
    elif task_id == 45:
        b.note("red-lid Nutella contains nuts; second Bahlsen is nut-free but not France")
        b.add(by_nutrition(lambda p: is_origin(p, "Italy") and no_allergen(p, "nuts"), "fat_g"), reason="Italy nut-free fallback")
        b.remove_if(lambda p: has_allergen(p, "nuts"), "remove cart items containing nuts")
        b.compute("nutrition")
    elif task_id == 46:
        picked = [name for name in [F, S, T] if is_origin(PRODUCTS[name], "Germany", "Denmark", "Japan") and PRODUCTS[name]["price"] < 50]
        b.add(picked, reason="picked items from Germany/Denmark/Japan under 50")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("payment")
    elif task_id == 47:
        b.note("yellow Leibniz is not bitter; second Bahlsen contains milk")
        b.add([S], reason="second cookie contains milk")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("tax")
    elif task_id == 48:
        lowest_picked = ties([F, S, T], lambda p: float(p["nutrition"]["calories_kcal"]))
        if any(is_origin(PRODUCTS[name], "Japan", "Germany", "Denmark") for name in lowest_picked):
            b.add(lowest_picked, reason="lowest-calorie picked item is from Germany")
        else:
            b.add(by_nutrition(lambda p: has_allergen(p, "gluten") and p["discount"] < 0.85, "sugar_g"), reason="fallback gluten and discount filter")
        if b.avg_nutrition("calories_kcal") > 500:
            b.remove_extreme_nutrition("calories_kcal", True, "weighted average calories > 500")
        b.compute("payment")
    elif task_id == 49:
        more_expensive = R if PRODUCTS[R]["price"] > PRODUCTS[T]["price"] else T
        if PRODUCTS[more_expensive]["price"] > 60:
            b.add([more_expensive], reason="more expensive compared item exceeds 60")
        else:
            b.add(by_nutrition(lambda p: is_origin(p, PRODUCTS[more_expensive]["country_of_origin"]) and has_tag(p, "high sugar"), "calories_kcal", True), reason="same-origin high-sugar fallback")
        b.add_list_missing("shopping-list item absent from cart")
        b.compute("tax")
    else:
        raise ValueError(f"Unsupported task id: {task_id}")

    return b


def write_audit(builders: list[TaskBuilder]) -> None:
    lines = [
        "# retail6 GT v1 audit",
        "",
        "## Visual mapping",
    ]
    for label, name in VISUAL.items():
        p = PRODUCTS[name]
        lines.append(
            f"- {label}: {DISPLAY[name]} | origin={p['country_of_origin']} | price={p['price']} | "
            f"tax={p['tax_rate']} | discount={p['discount']} | taste={p['taste']} | "
            f"tags={p['nutritional_characteristics']} | allergens={p['allergens']}"
        )
    lines += ["", "## Task decisions"]
    for b in builders:
        lines.append(f"- Task {b.task_id}: {len(b.calls)} calls")
        for note in b.notes:
            lines.append(f"  - {note}")
    AUDIT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    data = json.loads(SCENARIO.read_text(encoding="utf-8"))
    builders: list[TaskBuilder] = []
    for idx, task in enumerate(data, 1):
        user_id = task["Instruction"].split("User ID: ")[1].split(")")[0]
        builder = build_task(idx, user_id)
        task["ground_truth"] = builder.calls
        builders.append(builder)
    SCENARIO.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_audit(builders)
    print(f"wrote {SCENARIO} with {len(builders)} tasks and {sum(len(b.calls) for b in builders)} calls")
    print(f"wrote {AUDIT}")


if __name__ == "__main__":
    main()
