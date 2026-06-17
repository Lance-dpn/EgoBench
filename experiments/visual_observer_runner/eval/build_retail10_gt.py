#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.retail.retail_init import retail_init_data10

SCENARIO = ROOT / "scenarios/final/retail10.json"
AUDIT = ROOT / "experiments/visual_observer_runner/eval/retail10_gt_v1_audit.md"

DISPLAY = {p["name"].lower(): p["name"] for p in retail_init_data10["products"]}
PRODUCTS = {p["name"].lower(): p for p in retail_init_data10["products"]}
PRODUCT_ORDER = [p["name"].lower() for p in retail_init_data10["products"]]
LISTS = {
    row["user_id"]: [
        {"product_name": item["product_name"].lower(), "quantity": int(item["quantity"])}
        for item in row.get("items", [])
    ]
    for row in retail_init_data10["user_shopping_lists"]
}

VISUAL = {
    "innermost rectangular / rectangular at very back": "emmi gruyere cheese",
    "lowest label/tag price": "basiron gouda cheese",
    "rightmost / furthest-right label": "gruyere aop cheese",
    "front wedge-shaped cheese": "beaujolais cheese",
    "front square cheese": "switzerland swiss cheese",
    "directly below back rectangular cheese": "basiron gouda cheese",
    "directly below lowest-tag cheese": "mystic valley cheese",
}


def n(name: str, field: str) -> float:
    return PRODUCTS[name]["nutrition"][field]


def is_origin(p: dict, *origins: str) -> bool:
    aliases = {
        "usa": "united states",
        "us": "united states",
        "american": "united states",
        "uk": "united kingdom",
        "british": "united kingdom",
        "dutch": "netherlands",
        "swiss": "switzerland",
        "french": "france",
        "italian": "italy",
    }
    want = {aliases.get(o.lower(), o.lower()) for o in origins}
    return p["country_of_origin"].lower() in want


def has_taste(p: dict, taste: str) -> bool:
    return taste.lower() in [t.lower() for t in p["taste"]]


def all_products(pred: Callable[[dict], bool]) -> list[str]:
    return [name for name in PRODUCT_ORDER if pred(PRODUCTS[name])]


def ties(names: list[str], key: Callable[[dict], float], reverse: bool = False) -> list[str]:
    if not names:
        return []
    values = [(key(PRODUCTS[name]), name) for name in names]
    best = max(v for v, _ in values) if reverse else min(v for v, _ in values)
    return [name for v, name in values if v == best]


def add_call(user_id: str, name: str, qty: int | float) -> dict:
    p = PRODUCTS[name]
    return {
        "tool_name": "add_to_cart",
        "parameters": {
            "user_id": user_id,
            "product_name": DISPLAY[name],
            "qty": qty,
            "category": p["category"],
            "price": p["price"],
            "tax_rate": p["tax_rate"],
            "discount": p["discount"],
        },
    }


def remove_call(user_id: str, name: str, qty: int | float) -> dict:
    return {
        "tool_name": "remove_from_cart",
        "parameters": {
            "user_id": user_id,
            "product_name": DISPLAY.get(name, name),
            "qty": qty,
        },
    }


class TaskBuilder:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.calls: list[dict] = []
        self.notes: list[str] = []
        self.cart: OrderedDict[str, float] = OrderedDict()
        for row in retail_init_data10["user_carts"]:
            if row["user_id"] == user_id:
                for item in row.get("items", []):
                    self.cart[item["product_name"].lower()] = float(item["quantity"])

    def add(self, names: list[str], qty: int | float = 1, reason: str = "") -> None:
        for name in names:
            self.calls.append(add_call(self.user_id, name, qty))
            self.cart[name] = self.cart.get(name, 0) + float(qty)
            if reason:
                self.notes.append(f"add {DISPLAY[name]} x{qty}: {reason}")

    def remove_if(self, pred: Callable[[dict], bool], reason: str) -> None:
        for name in list(self.cart.keys()):
            p = PRODUCTS.get(name)
            if p and pred(p):
                qty = self.cart[name]
                self.calls.append(remove_call(self.user_id, name, qty))
                del self.cart[name]
                self.notes.append(f"remove {DISPLAY[name]} x{qty:g}: {reason}")

    def remove_name_if_present(self, name: str, reason: str) -> None:
        if name in self.cart:
            qty = self.cart[name]
            self.calls.append(remove_call(self.user_id, name, qty))
            del self.cart[name]
            self.notes.append(f"remove {DISPLAY[name]} x{qty:g}: {reason}")

    def add_list_missing(self, pred: Callable[[dict], bool], reason: str, *, full: bool = False) -> None:
        for item in LISTS.get(self.user_id, []):
            name = item["product_name"]
            p = PRODUCTS[name]
            current = self.cart.get(name, 0)
            qty = item["quantity"] - current if full else item["quantity"]
            if qty > 0 and (full or current == 0) and pred(p):
                self.add([name], qty, reason)

    def compute(self, kind: str) -> None:
        tool = {
            "payment": "compute_total_payment",
            "tax": "compute_total_tax",
            "nutrition": "compute_total_nutrition",
        }[kind]
        self.calls.append(
            {
                "tool_name": tool,
                "parameters": {
                    "user_id": self.user_id,
                    "products": [
                        {"product_name": DISPLAY.get(name, name), "quantity": int(qty) if qty == int(qty) else qty}
                        for name, qty in self.cart.items()
                    ],
                },
            }
        )


def sel(pred: Callable[[dict], bool], metric: str, reverse: bool = False) -> list[str]:
    return ties(all_products(pred), lambda p: p["nutrition"][metric] if metric in p["nutrition"] else p[metric], reverse)


def price_min(pred): return ties(all_products(pred), lambda p: p["price"])
def price_max(pred): return ties(all_products(pred), lambda p: p["price"], True)
def disc_best(pred): return ties(all_products(pred), lambda p: p["discount"])
def tax_min(pred): return ties(all_products(pred), lambda p: p["tax_rate"])


def build_task(task_id: int, user_id: str) -> TaskBuilder:
    b = TaskBuilder(user_id)
    # Visual branch facts used below:
    rect = PRODUCTS[VISUAL["innermost rectangular / rectangular at very back"]]
    lowest = PRODUCTS[VISUAL["lowest label/tag price"]]
    right = PRODUCTS[VISUAL["rightmost / furthest-right label"]]
    wedge = PRODUCTS[VISUAL["front wedge-shaped cheese"]]
    square = PRODUCTS[VISUAL["front square cheese"]]

    if task_id == 1:
        b.add(sel(lambda p: is_origin(p, "France") and has_taste(p, "creamy"), "calories_kcal"), reason="rectangular back cheese protein > 25")
        b.add_list_missing(lambda p: p["price"] < 30, "shopping-list item missing and price < 30")
        b.compute("nutrition")
    elif task_id == 2:
        b.add(sel(lambda p: 10 <= p["price"] <= 40 and has_taste(p, "savory"), "carbs_g", True), reason="lowest label is Netherlands")
        b.add_list_missing(lambda p: n(p["name"].lower(), "sodium_mg") < 600, "shopping-list item unpurchased and sodium < 600")
        b.compute("tax")
    elif task_id == 3:
        b.add(price_min(lambda p: 500 <= n(p["name"].lower(), "sodium_mg") <= 800 and has_taste(p, "tangy")), reason="front square cheese is not salty")
        b.remove_if(lambda p: n(p["name"].lower(), "calories_kcal") > 450, "calories > 450")
        b.add_list_missing(lambda p: p["tax_rate"] == 0, "shopping-list tax-free item")
        b.compute("payment")
    elif task_id == 4:
        b.add(sel(lambda p: has_taste(p, "mild") and n(p["name"].lower(), "carbs_g") < 1, "calories_kcal"), reason="front wedge fat is not > 30")
        b.add_list_missing(lambda p: p["tax_rate"] > 0.06, "shopping-list item missing and tax > 0.06")
        b.compute("nutrition")
    elif task_id == 5:
        b.add(price_min(lambda p: is_origin(p, "UK", "Germany") and has_taste(p, "nutty")), reason="rightmost label sugar < 0.5")
        b.add_list_missing(lambda p: is_origin(p, "USA", "Spain"), "shopping-list item from USA or Spain")
        b.compute("payment")
    elif task_id == 6:
        b.add(disc_best(lambda p: has_taste(p, "creamy") and p["price"] < 35), reason="back rectangular cheese is not mild")
        b.add_list_missing(lambda p: n(p["name"].lower(), "protein_g") > 20, "shopping-list item protein > 20")
        b.compute("nutrition")
    elif task_id == 7:
        b.add(price_min(lambda p: has_taste(p, "savory") and n(p["name"].lower(), "fat_g") < 25), reason="front square price is not > 50")
        b.add_list_missing(lambda p: p["tax_rate"] == 0 or p["tax_rate"] < 0.05, "shopping-list tax exempt or tax < 0.05")
        b.compute("tax")
    elif task_id == 8:
        b.add(sel(lambda p: is_origin(p, "Italy") and p["tax_rate"] > 0.08, "sodium_mg", True), reason="lowest label is not Switzerland")
        b.remove_if(lambda p: p["price"] > 60, "unit price > 60")
        b.add_list_missing(lambda p: p["price"] < 45, "shopping-list item missing and price < 45")
        b.compute("nutrition")
    elif task_id == 9:
        b.add(sel(lambda p: is_origin(p, "Netherlands") and has_taste(p, "nutty") and p["price"] < 30, "carbs_g"), reason="front wedge tax is not < 0.06")
        b.add_list_missing(lambda p: n(p["name"].lower(), "protein_g") > 25, "shopping-list item protein > 25")
        b.compute("nutrition")
    elif task_id == 10:
        b.add(sel(lambda p: has_taste(p, "tangy") and p["price"] < 40, "sodium_mg"), reason="rightmost label fat > 30")
        b.remove_if(lambda p: n(p["name"].lower(), "sugar_g") > 2, "sugar > 2")
        b.add_list_missing(lambda p: n(p["name"].lower(), "fat_g") < 25, "shopping-list item fat < 25")
        b.compute("nutrition")
    elif task_id == 11:
        b.add(sel(lambda p: is_origin(p, "France") and 15 <= p["price"] <= 45, "carbs_g"), reason="back rectangular protein > 20")
        b.add_list_missing(lambda p: p["discount"] < 0.95, "shopping-list item discount < 0.95")
        b.compute("payment")
    elif task_id == 12:
        b.add(sel(lambda p: p["price"] < 50 and has_taste(p, "creamy"), "calories_kcal", True), reason="front square is Switzerland")
        b.add_list_missing(lambda p: not is_origin(p, "France"), "shopping-list item not from France")
        b.compute("nutrition")
    elif task_id == 13:
        b.add(sel(lambda p: 30 <= p["price"] <= 60 and has_taste(p, "savory"), "protein_g", True), reason="front wedge is not nutty")
        b.remove_if(lambda p: has_taste(p, "salty"), "salty flavor")
        b.add_list_missing(lambda p: n(p["name"].lower(), "calories_kcal") < 350, "shopping-list item not fully purchased and calories < 350", full=True)
        b.compute("nutrition")
    elif task_id == 14:
        b.add(sel(lambda p: p["price"] > 25 and p["tax_rate"] < 0.10, "calories_kcal"), reason="lowest label carbs are not < 1")
        b.add_list_missing(lambda p: has_taste(p, "mild"), "shopping-list item mild")
        b.compute("nutrition")
    elif task_id == 15:
        b.add(sel(lambda p: is_origin(p, "UK", "Germany") and p["discount"] < 0.95, "protein_g", True), reason="rightmost label is not France")
        b.add_list_missing(lambda p: p["tax_rate"] > 0.06, "shopping-list item tax > 0.06")
        b.compute("tax")
    elif task_id == 16:
        b.add(sel(lambda p: is_origin(p, "Netherlands") and 20 <= p["price"] <= 60, "sodium_mg"), reason="back rectangular discount is not < 0.85")
        b.remove_if(lambda p: is_origin(p, "USA", "Spain"), "origin USA or Spain")
        b.add_list_missing(lambda p: p["price"] > 25, "shopping-list item price > 25")
        b.compute("payment")
    elif task_id == 17:
        b.add(sel(lambda p: p["price"] > 35 and p["tax_rate"] < 0.08, "calories_kcal", True), reason="front square fat is not < 25")
        b.add_list_missing(lambda p: p["discount"] < 0.95, "shopping-list item discount < 0.95")
        b.compute("nutrition")
    elif task_id == 18:
        b.add(sel(lambda p: 15 <= p["price"] <= 45 and p["discount"] < 0.95, "sodium_mg", True), reason="front wedge sugar is not < 0.5")
        b.remove_name_if_present(VISUAL["lowest label/tag price"], "remove lowest-label cheese if present")
        b.add_list_missing(lambda p: not is_origin(p, "Italy"), "shopping-list item origin not Italy")
        b.compute("nutrition")
    elif task_id == 19:
        b.add(tax_min(lambda p: is_origin(p, "USA", "Spain") and has_taste(p, "creamy")), reason="rightmost label protein > 25")
        b.add_list_missing(lambda p: p["price"] < 30, "shopping-list item price < 30")
        b.compute("tax")
    elif task_id == 20:
        b.add(sel(lambda p: has_taste(p, "tangy") and 20 <= p["price"] <= 50, "fat_g"), reason="lowest label is Netherlands")
        b.remove_if(lambda p: n(p["name"].lower(), "calories_kcal") > 450, "calories > 450")
        b.add_list_missing(lambda p: n(p["name"].lower(), "sodium_mg") < 500, "shopping-list item sodium < 500")
        b.compute("payment")
    elif task_id == 21:
        b.add(sel(lambda p: 20 <= n(p["name"].lower(), "fat_g") <= 30 and p["discount"] < 0.85, "protein_g", True), reason="back rectangular price is not < 40")
        b.add_list_missing(lambda p: n(p["name"].lower(), "sugar_g") == 0, "shopping-list item sugar = 0")
        b.compute("nutrition")
    elif task_id == 22:
        b.add(sel(lambda p: p["price"] > 45 and has_taste(p, "mild"), "sodium_mg"), reason="front wedge is discounted")
        b.remove_if(lambda p: n(p["name"].lower(), "fat_g") > 35, "fat > 35")
        b.add_list_missing(lambda p: p["price"] < 50, "shopping-list item price < 50")
        b.compute("nutrition")
    elif task_id == 23:
        b.add(sel(lambda p: has_taste(p, "savory") and p["tax_rate"] < 0.08, "protein_g", True), reason="rightmost label calories are not below 350")
        b.add_list_missing(lambda p: is_origin(p, "Switzerland"), "shopping-list item from Switzerland")
        b.compute("nutrition")
    elif task_id == 24:
        b.add(price_max(lambda p: is_origin(p, "France") and 0.05 <= p["tax_rate"] <= 0.10), reason="front square flavor contains savory")
        b.remove_if(lambda p: is_origin(p, "USA", "Spain"), "origin USA or Spain")
        b.add_list_missing(lambda p: n(p["name"].lower(), "protein_g") > 17, "shopping-list item protein > 17")
        b.compute("nutrition")
    elif task_id == 25:
        b.add(disc_best(lambda p: is_origin(p, "Netherlands") and n(p["name"].lower(), "fat_g") > 30), reason="back rectangular tax is not < 0.08")
        b.add_list_missing(lambda p: n(p["name"].lower(), "sodium_mg") < 450, "shopping-list item sodium < 450")
        b.compute("payment")
    elif task_id == 26:
        b.add(sel(lambda p: is_origin(p, "UK", "Germany") and p["price"] < 40, "fat_g"), reason="lowest label is not Swiss with sugar < 0.5")
        b.remove_if(lambda p: n(p["name"].lower(), "fat_g") > 35, "fat > 35")
        b.add_list_missing(lambda p: is_origin(p, "France"), "shopping-list item from France")
        b.compute("nutrition")
    elif task_id == 27:
        b.add(sel(lambda p: is_origin(p, "Italy") and 0.05 <= p["tax_rate"] <= 0.12, "carbs_g", True), reason="rightmost label is not France with discount < 0.95")
        b.add_list_missing(lambda p: n(p["name"].lower(), "calories_kcal") < 350, "shopping-list item calories < 350")
        b.compute("nutrition")
    elif task_id == 28:
        b.add(sel(lambda p: has_taste(p, "tangy") and p["tax_rate"] < 0.08, "fat_g"), reason="front wedge sodium is not below 500")
        b.remove_if(lambda p: n(p["name"].lower(), "sugar_g") > 1, "sugar > 1")
        b.add_list_missing(lambda p: n(p["name"].lower(), "protein_g") > 20, "shopping-list item not fully purchased and protein > 20", full=True)
        b.compute("payment")
    elif task_id == 29:
        b.add(sel(lambda p: 20 <= p["price"] <= 60 and p["discount"] < 0.85, "calories_kcal"), reason="back rectangular protein is not > 30")
        b.add_list_missing(lambda p: is_origin(p, "UK", "Germany"), "shopping-list item from UK or Germany")
        b.compute("tax")
    elif task_id == 30:
        b.add(sel(lambda p: is_origin(p, "Switzerland") and has_taste(p, "mild"), "protein_g", True), reason="front square calories < 400")
        b.remove_if(lambda p: is_origin(p, "Netherlands"), "origin Netherlands")
        b.add_list_missing(lambda p: n(p["name"].lower(), "fat_g") < 25, "shopping-list item fat < 25")
        b.compute("nutrition")
    elif task_id == 31:
        b.add(sel(lambda p: has_taste(p, "savory") and p["price"] < 50, "calories_kcal"), reason="rightmost label protein > 25")
        b.add_list_missing(lambda p: p["tax_rate"] == 0, "shopping-list tax-exempt item")
        b.compute("nutrition")
    elif task_id == 32:
        b.add(sel(lambda p: p["tax_rate"] > 0.10 and 30 <= p["price"] <= 60, "protein_g", True), reason="front wedge sugar is not 0")
        b.remove_if(lambda p: n(p["name"].lower(), "calories_kcal") > 450, "calories > 450")
        b.add_list_missing(lambda p: p["price"] < 25, "shopping-list item price < 25")
        b.compute("nutrition")
    elif task_id == 33:
        b.add(sel(lambda p: has_taste(p, "nutty") and 0.7 <= p["discount"] <= 0.95, "calories_kcal", True), reason="lowest label carbs are not < 1")
        b.add_list_missing(lambda p: n(p["name"].lower(), "protein_g") > 30, "shopping-list item protein > 30")
        b.compute("payment")
    elif task_id == 34:
        b.add(sel(lambda p: is_origin(p, "Netherlands") and p["price"] < 20, "protein_g", True), reason="back rectangular discount is not < 0.85")
        b.remove_if(lambda p: has_taste(p, "tangy"), "tangy flavor")
        b.add_list_missing(lambda p: is_origin(p, "USA", "Spain"), "shopping-list item from USA or Spain")
        b.compute("tax")
    elif task_id == 35:
        b.add(sel(lambda p: p["discount"] < 0.95 and has_taste(p, "mild"), "fat_g"), reason="back rectangular sodium is not below 500")
        b.remove_if(lambda p: p["tax_rate"] > 0.15, "tax rate > 0.15")
        b.add_list_missing(lambda p: p["price"] < 30, "shopping-list item price < 30")
        b.compute("nutrition")
    elif task_id == 36:
        b.add(price_max(lambda p: p["tax_rate"] < 0.08 and has_taste(p, "nutty")), reason="front square origin is Switzerland")
        b.add_list_missing(lambda p: has_taste(p, "salty"), "shopping-list item salty")
        b.compute("tax")
    elif task_id == 37:
        b.add(sel(lambda p: is_origin(p, "France") and 20 <= n(p["name"].lower(), "fat_g") <= 30, "carbs_g"), reason="lowest label has discount")
        b.remove_if(lambda p: n(p["name"].lower(), "calories_kcal") > 400, "calories > 400")
        b.add_list_missing(lambda p: is_origin(p, "Netherlands"), "shopping-list item from Netherlands")
        b.compute("payment")
    elif task_id == 38:
        b.add(disc_best(lambda p: is_origin(p, "Italy") and 0.05 <= p["tax_rate"] <= 0.10), reason="front wedge fat is not below 25")
        b.add_list_missing(lambda p: n(p["name"].lower(), "calories_kcal") < 350, "shopping-list item calories < 350")
        b.compute("nutrition")
    elif task_id == 39:
        b.add(sel(lambda p: is_origin(p, "UK", "Germany") and 20 <= p["price"] <= 50, "protein_g", True), reason="rightmost flavor includes savory")
        b.remove_if(lambda p: is_origin(p, "USA", "Spain"), "origin USA or Spain")
        b.add_list_missing(lambda p: n(p["name"].lower(), "sodium_mg") < 600, "shopping-list item sodium < 600")
        b.compute("payment")
    elif task_id == 40:
        b.add(disc_best(lambda p: is_origin(p, "Netherlands") and 20 <= n(p["name"].lower(), "fat_g") <= 35), reason="back rectangular price is not below 30")
        b.add_list_missing(lambda p: n(p["name"].lower(), "protein_g") > 25, "shopping-list item protein > 25")
        b.compute("tax")
    elif task_id == 41:
        b.add(sel(lambda p: p["tax_rate"] > 0.10 and 30 <= p["price"] <= 60, "sodium_mg", True), reason="front wedge protein is not > 28")
        b.remove_if(lambda p: n(p["name"].lower(), "sugar_g") > 1, "sugar > 1")
        min_tax = min(PRODUCTS[item["product_name"]]["tax_rate"] for item in LISTS[b.user_id])
        b.add_list_missing(lambda p: p["tax_rate"] == min_tax, "shopping-list item tied for lowest list tax")
        b.compute("nutrition")
    elif task_id == 42:
        b.add(sel(lambda p: p["discount"] < 0.85 and p["price"] < 50, "protein_g", True), reason="lowest label calories are not > 400")
        b.add_list_missing(lambda p: n(p["name"].lower(), "fat_g") <= 30, "shopping-list item fat <= 30")
        b.compute("nutrition")
    elif task_id == 43:
        b.add(disc_best(lambda p: 15 <= p["price"] <= 45 and n(p["name"].lower(), "fat_g") < 30), reason="front square tax is not < 0.08")
        b.remove_if(lambda p: p["price"] > 60, "unit price > 60")
        b.add_list_missing(lambda p: p["discount"] < 0.95, "shopping-list item not fully purchased and discount < 0.95", full=True)
        b.compute("payment")
    elif task_id == 44:
        b.add(sel(lambda p: p["discount"] < 0.85 and n(p["name"].lower(), "calories_kcal") >= 400, "carbs_g", True), reason="front square origin is not France")
        b.add_list_missing(lambda p: n(p["name"].lower(), "sodium_mg") < 600, "shopping-list item sodium < 600")
        b.compute("nutrition")
    elif task_id == 45:
        b.add(disc_best(lambda p: is_origin(p, "UK") and p["price"] < 50), reason="front wedge is not salty")
        b.add_list_missing(lambda p: not is_origin(p, "USA"), "shopping-list item not from USA")
        b.compute("payment")
    elif task_id == 46:
        b.add(sel(lambda p: has_taste(p, "savory") and n(p["name"].lower(), "carbs_g") < 1, "sodium_mg", True), reason="lowest-label tax < 0.08")
        b.add_list_missing(lambda p: p["tax_rate"] == 0, "shopping-list tax-exempt item")
        b.compute("nutrition")
    elif task_id == 47:
        b.add(price_max(lambda p: is_origin(p, "France") and has_taste(p, "tangy")), reason="back rectangular fat > 30")
        b.add_list_missing(lambda p: p["price"] < 35, "shopping-list item price < 35")
        b.compute("tax")
    elif task_id == 48:
        b.add(sel(lambda p: is_origin(p, "Switzerland") and p["tax_rate"] < 0.1, "sodium_mg"), reason="rightmost label price is not < 30")
        b.add_list_missing(lambda p: n(p["name"].lower(), "sugar_g") == 0, "shopping-list item sugar = 0")
        b.compute("nutrition")
    elif task_id == 49:
        b.add(sel(lambda p: is_origin(p, "France") and p["price"] > 40, "carbs_g"), reason="front wedge discount is not lower than 0.9")
        b.add_list_missing(lambda p: n(p["name"].lower(), "calories_kcal") < 350, "shopping-list item calories < 350")
        b.compute("nutrition")
    elif task_id == 50:
        b.add(disc_best(lambda p: is_origin(p, "Italy") and n(p["name"].lower(), "protein_g") > 20), reason="front square calories are not below 350")
        b.add_list_missing(lambda p: p["tax_rate"] < 0.05, "shopping-list item tax < 0.05")
        b.compute("nutrition")
    elif task_id == 51:
        b.add(price_min(lambda p: is_origin(p, "Switzerland") and n(p["name"].lower(), "fat_g") < 31), reason="lowest-label protein is not > 28")
        b.add_list_missing(lambda p: p["price"] > 20, "shopping-list item price > 20")
        b.compute("tax")
    elif task_id == 52:
        b.add(sel(lambda p: is_origin(p, "UK") and has_taste(p, "creamy"), "calories_kcal"), reason="back rectangular sodium > 600")
        b.add_list_missing(lambda p: has_taste(p, "nutty"), "shopping-list item nutty")
        b.compute("nutrition")
    elif task_id == 53:
        b.add(sel(lambda p: is_origin(p, "Netherlands") and p["price"] < 45, "fat_g"), reason="rightmost-label sugar is safe")
        b.add_list_missing(lambda p: n(p["name"].lower(), "calories_kcal") < 400, "shopping-list item calories < 400")
        b.compute("payment")
    elif task_id == 54:
        b.add(price_max(lambda p: is_origin(p, "Switzerland") and has_taste(p, "mild")), reason="front square carbs < 1")
        b.add_list_missing(lambda p: n(p["name"].lower(), "protein_g") > 20, "shopping-list item protein > 20")
        b.compute("nutrition")
    elif task_id == 55:
        b.add(sel(lambda p: is_origin(p, "France") and n(p["name"].lower(), "fat_g") > 25, "sodium_mg", True), reason="back rectangular is not Italy")
        b.add_list_missing(lambda p: not is_origin(p, "UK"), "shopping-list item not from UK")
        b.compute("tax")
    elif task_id == 56:
        b.add(price_min(lambda p: is_origin(p, "Netherlands") and has_taste(p, "nutty")), reason="front wedge tax > 0.1")
        b.add_list_missing(lambda p: n(p["name"].lower(), "sugar_g") < 0.5, "shopping-list item sugar < 0.5")
        b.compute("nutrition")
    elif task_id == 57:
        b.add(sel(lambda p: is_origin(p, "USA") and n(p["name"].lower(), "calories_kcal") < 400, "fat_g"), reason="lowest-label flavor is creamy")
        b.add_list_missing(lambda p: p["tax_rate"] > 0.05, "shopping-list item tax > 0.05")
        b.compute("payment")
    elif task_id == 58:
        b.add(disc_best(lambda p: is_origin(p, "UK") and n(p["name"].lower(), "protein_g") > 22), reason="rightmost-label fat is not below 25")
        b.add_list_missing(lambda p: True, "shopping-list necessity not purchased")
        b.compute("nutrition")
    elif task_id == 59:
        b.add(price_max(lambda p: is_origin(p, "Netherlands") and p["tax_rate"] < 0.08), reason="front square price is not > 45")
        b.add_list_missing(lambda p: has_taste(p, "savory"), "shopping-list item savory")
        b.compute("nutrition")
    elif task_id == 60:
        b.add(sel(lambda p: is_origin(p, "USA") and p["tax_rate"] > 0.1, "fat_g"), reason="front wedge protein meets threshold")
        b.add_list_missing(lambda p: p["price"] < 40, "shopping-list item price < 40")
        b.compute("nutrition")
    elif task_id == 61:
        b.add(price_min(lambda p: True), reason="rightmost-label calories are not > 420; no UK cheese under 500mg sodium")
        b.add_list_missing(lambda p: n(p["name"].lower(), "protein_g") > 18, "shopping-list item protein > 18")
        b.compute("tax")
    elif task_id == 62:
        b.add(sel(lambda p: is_origin(p, "Netherlands") and p["price"] < 35, "sodium_mg"), reason="back rectangular discount is not significantly better than 0.8")
        b.add_list_missing(lambda p: p["tax_rate"] != 0, "shopping-list item not tax-exempt")
        b.compute("nutrition")
    elif task_id == 63:
        b.add(disc_best(lambda p: is_origin(p, "USA") and n(p["name"].lower(), "calories_kcal") > 350), reason="lowest-label sodium is not below 450")
        b.add_list_missing(lambda p: is_origin(p, "France"), "shopping-list item French-produced")
        b.compute("payment")
    else:
        raise KeyError(task_id)

    return b


USER_BY_TASK = {
    1: "user_123", 2: "user_456", 3: "user_789", 4: "user_101", 5: "user_202",
    6: "user_404", 7: "user_505", 8: "user_123", 9: "user_456", 10: "user_789",
    11: "user_101", 12: "user_202", 13: "user_303", 14: "user_404", 15: "user_505",
    16: "user_606", 17: "user_707", 18: "user_202", 19: "user_456", 20: "user_101",
    21: "user_303", 22: "user_505", 23: "user_606", 24: "user_707", 25: "user_123",
    26: "user_404", 27: "user_123", 28: "user_789", 29: "user_101", 30: "user_303",
    31: "user_404", 32: "user_606", 33: "user_707", 34: "user_123", 35: "user_456",
    36: "user_789", 37: "user_101", 38: "user_202", 39: "user_303", 40: "user_404",
    41: "user_505", 42: "user_606", 43: "user_707", 44: "user_123", 45: "user_456",
    46: "user_789", 47: "user_101", 48: "user_202", 49: "user_303", 50: "user_404",
    51: "user_505", 52: "user_606", 53: "user_707", 54: "user_123", 55: "user_456",
    56: "user_789", 57: "user_101", 58: "user_202", 59: "user_303", 60: "user_404",
    61: "user_505", 62: "user_606", 63: "user_707",
}


def main() -> None:
    data = json.loads(SCENARIO.read_text())
    audit_rows = []
    total_calls = 0
    for task in data:
        task_id = int(task["task_id"])
        builder = build_task(task_id, USER_BY_TASK[task_id])
        task["ground_truth"] = builder.calls
        total_calls += len(builder.calls)
        final = builder.calls[-1]
        audit_rows.append(
            {
                "task_id": task_id,
                "user": USER_BY_TASK[task_id],
                "calls": len(builder.calls),
                "compute": final["tool_name"],
                "notes": "; ".join(builder.notes) if builder.notes else "no cart mutation before compute",
                "final_cart": ", ".join(
                    f"{DISPLAY.get(name, name)} x{qty:g}" for name, qty in builder.cart.items()
                ),
            }
        )

    SCENARIO.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    lines = [
        "# retail10 GT v1 audit",
        "",
        "## Visual mapping",
    ]
    for label, name in VISUAL.items():
        p = PRODUCTS[name]
        lines.append(
            f"- {label}: `{DISPLAY[name]}`; price={p['price']}, origin={p['country_of_origin']}, "
            f"tax={p['tax_rate']}, discount={p['discount']}, nutrition={p['nutrition']}"
        )
    lines += [
        "",
        f"Generated {len(data)} tasks with {total_calls} ground-truth calls.",
        "",
        "| Task | User | Calls | Final compute | Branch/list/removal notes | Final cart |",
        "|---:|---|---:|---|---|---|",
    ]
    for row in audit_rows:
        lines.append(
            f"| {row['task_id']} | {row['user']} | {row['calls']} | {row['compute']} | "
            f"{row['notes']} | {row['final_cart']} |"
        )
    AUDIT.write_text("\n".join(lines) + "\n")
    print(f"Wrote {SCENARIO}")
    print(f"Wrote {AUDIT}")
    print(f"Tasks: {len(data)}, calls: {total_calls}")


if __name__ == "__main__":
    main()
