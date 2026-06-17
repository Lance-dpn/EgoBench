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

from tools.order.order_init import order_init_data


SCENARIO = ROOT / "scenarios/final/order2.json"
AUDIT = ROOT / "experiments/visual_observer_runner/eval/order2_gt_v1_audit.md"

GREEK = "Mediterranean Greek Restaurant"
ANNIE = "Annie Italian Restaurant"

DISHES_BY_REST: dict[str, dict[str, dict]] = {}
ORDER_BY_REST: dict[str, list[str]] = {}
SET_MEALS_BY_REST: dict[str, dict[str, dict]] = {}

for dish in order_init_data["dishes"]:
    rest = dish["restaurant_name"]
    key = dish["name"].lower()
    DISHES_BY_REST.setdefault(rest, {})[key] = dish
    ORDER_BY_REST.setdefault(rest, []).append(key)

for meal in order_init_data["set_meals"]:
    rest = meal["restaurant_name"]
    SET_MEALS_BY_REST.setdefault(rest, {})[meal["name"].lower()] = meal

DISPLAY = {
    rest: {key: dish["name"] for key, dish in dishes.items()}
    for rest, dishes in DISHES_BY_REST.items()
}
DISPLAY_SET = {
    rest: {key: meal["name"] for key, meal in meals.items()}
    for rest, meals in SET_MEALS_BY_REST.items()
}

VISUAL = {
    "top right first expanded page / chicken and potatoes casserole": "greek village roast chicken leg",
    "bright blue plate with fried items and lemon": "fried calamari",
    "dark grey plate with white sauce dish": "greek lamb chops",
    "dark blue casserole containing seafood / seafood paella": "santarini seafood rice",
    "red seafood in copper double-handled pot": "grilled octopus",
    "grilled vegetable skewer on wooden cutting board": "grilled fish",
    "dairy product in wooden bowl": "greek yogurt with honey & nuts",
    "white plate dessert at bottom right of sixth page": "vanilla pudding",
    "right list first item on fifth page": "feta & tomato spaghetti",
    "right list second item on fifth page": "octopus spaghetti",
    "right list third item on fifth page": "spaghetti bolognese",
}


def dish(rest: str, name: str) -> dict:
    return DISHES_BY_REST[rest][name]


def n(rest: str, name: str, field: str) -> float:
    return dish(rest, name)["nutrition"][field]


def has_tag(rest: str, name: str, tag: str) -> bool:
    return tag.lower() in [v.lower() for v in dish(rest, name).get("nutritional_characteristics", [])]


def has_taste(rest: str, name: str, taste: str) -> bool:
    return taste.lower() in [v.lower() for v in dish(rest, name).get("taste", [])]


def has_allergen(rest: str, name: str, allergen: str) -> bool:
    return allergen.lower() in [v.lower() for v in dish(rest, name).get("allergens", [])]


def names(rest: str, pred: Callable[[str], bool]) -> list[str]:
    return [name for name in ORDER_BY_REST[rest] if pred(name)]


def ties(rest: str, candidates: list[str], key: Callable[[str], float], reverse: bool = False) -> list[str]:
    if not candidates:
        return []
    values = [(key(name), name) for name in candidates]
    best = max(v for v, _ in values) if reverse else min(v for v, _ in values)
    return [name for v, name in values if v == best]


def price_min(rest: str, pred: Callable[[str], bool]) -> list[str]:
    return ties(rest, names(rest, pred), lambda x: dish(rest, x)["price"])


def price_max(rest: str, pred: Callable[[str], bool]) -> list[str]:
    return ties(rest, names(rest, pred), lambda x: dish(rest, x)["price"], True)


def metric_min(rest: str, pred: Callable[[str], bool], metric: str) -> list[str]:
    return ties(rest, names(rest, pred), lambda x: n(rest, x, metric))


def metric_max(rest: str, pred: Callable[[str], bool], metric: str) -> list[str]:
    return ties(rest, names(rest, pred), lambda x: n(rest, x, metric), True)


def discount_best(rest: str, pred: Callable[[str], bool]) -> list[str]:
    return ties(rest, names(rest, pred), lambda x: dish(rest, x)["discount"])


def discounted_price(rest: str, name: str) -> float:
    d = dish(rest, name)
    return d["price"] * d["discount"]


def greek_discounted_price(name: str) -> float:
    return discounted_price(GREEK, name)


def add_dish_call(rest: str, user_id: str, name: str, qty: float) -> dict:
    d = dish(rest, name)
    return {
        "tool_name": "add_dish_to_order",
        "parameters": {
            "restaurant_name": rest,
            "user_id": user_id,
            "dish_name": DISPLAY[rest][name],
            "quantity": qty,
            "category": d.get("category"),
            "price": d.get("price"),
            "tax_rate": d.get("tax_rate"),
            "discount": d.get("discount"),
        },
    }


def remove_dish_call(rest: str, user_id: str, name: str, qty: float) -> dict:
    return {
        "tool_name": "remove_dish_from_order",
        "parameters": {
            "restaurant_name": rest,
            "user_id": user_id,
            "dish_name": DISPLAY[rest][name],
            "quantity": qty,
        },
    }


def add_set_call(rest: str, user_id: str, name: str, qty: float) -> dict:
    return {
        "tool_name": "add_set_meal_to_order",
        "parameters": {
            "restaurant_name": rest,
            "user_id": user_id,
            "set_meal_name": DISPLAY_SET[rest][name],
            "quantity": qty,
        },
    }


def remove_set_call(rest: str, user_id: str, name: str, qty: float) -> dict:
    return {
        "tool_name": "remove_set_meal_from_order",
        "parameters": {
            "restaurant_name": rest,
            "user_id": user_id,
            "set_meal_name": DISPLAY_SET[rest][name],
            "quantity": qty,
        },
    }


def clear_call(rest: str, user_id: str) -> dict:
    return {"tool_name": "clear_user_order", "parameters": {"restaurant_name": rest, "user_id": user_id}}


class Builder:
    def __init__(self, user_id: str, rest: str = GREEK):
        self.user_id = user_id
        self.rest = rest
        self.calls: list[dict] = []
        self.notes: list[str] = [f"restaurant={rest}"]
        self.cart: OrderedDict[str, float] = OrderedDict()
        self.sets: OrderedDict[str, float] = OrderedDict()
        # The official order_init_data currently stores Greek starter orders under
        # "Greek Village Roast Chicken Leg" rather than the catalog restaurant.
        # The evaluator initializes an empty order for Mediterranean Greek Restaurant.

    def add(self, items: list[str], qty: float = 1, reason: str = "") -> None:
        for item in items:
            self.calls.append(add_dish_call(self.rest, self.user_id, item, qty))
            self.cart[item] = self.cart.get(item, 0) + qty
            if reason:
                self.notes.append(f"add {DISPLAY[self.rest][item]} x{qty:g}: {reason}")

    def add_set(self, items: list[str], qty: float = 1, reason: str = "") -> None:
        for item in items:
            self.calls.append(add_set_call(self.rest, self.user_id, item, qty))
            self.sets[item] = self.sets.get(item, 0) + qty
            if reason:
                self.notes.append(f"add set {DISPLAY_SET[self.rest][item]} x{qty:g}: {reason}")

    def remove(self, item: str, qty: float | None = None, reason: str = "") -> None:
        if item in self.cart:
            remove_qty = self.cart[item] if qty is None else min(qty, self.cart[item])
            self.calls.append(remove_dish_call(self.rest, self.user_id, item, remove_qty))
            self.cart[item] -= remove_qty
            if self.cart[item] <= 0:
                del self.cart[item]
            if reason:
                self.notes.append(f"remove {DISPLAY[self.rest][item]} x{remove_qty:g}: {reason}")

    def remove_set(self, item: str, qty: float | None = None, reason: str = "") -> None:
        if item in self.sets:
            remove_qty = self.sets[item] if qty is None else min(qty, self.sets[item])
            self.calls.append(remove_set_call(self.rest, self.user_id, item, remove_qty))
            self.sets[item] -= remove_qty
            if self.sets[item] <= 0:
                del self.sets[item]
            if reason:
                self.notes.append(f"remove set {DISPLAY_SET[self.rest][item]} x{remove_qty:g}: {reason}")

    def clear(self, reason: str = "") -> None:
        self.calls.append(clear_call(self.rest, self.user_id))
        self.cart.clear()
        self.sets.clear()
        if reason:
            self.notes.append(f"clear order: {reason}")

    def non_set_total_price(self, discounted: bool = False) -> float:
        total = 0.0
        for item, qty in self.cart.items():
            d = dish(self.rest, item)
            total += (d["price"] * d["discount"] if discounted else d["price"]) * qty
        return total

    def total_metric(self, metric: str) -> float:
        total = 0.0
        for item, qty in self.cart.items():
            total += n(self.rest, item, metric) * qty
        for meal, qty in self.sets.items():
            for inc in SET_MEALS_BY_REST[self.rest][meal]["included_dishes"]:
                total += n(self.rest, inc["dish_name"], metric) * inc.get("quantity", 1) * qty
        return total

    def contains_allergen(self, allergen: str) -> bool:
        return any(has_allergen(self.rest, item, allergen) for item in self.cart)

    def remove_non_set_by_metric(self, metric: str, reverse: bool = True, reason: str = "") -> None:
        if not self.cart:
            return
        values = [(n(self.rest, item, metric), item) for item in self.cart]
        best = max(v for v, _ in values) if reverse else min(v for v, _ in values)
        for _, item in list(values):
            if n(self.rest, item, metric) == best:
                self.remove(item, None, reason or f"{metric} {'max' if reverse else 'min'}")

    def remove_non_set_by_price(self, reverse: bool = True, reason: str = "") -> None:
        if not self.cart:
            return
        values = [(dish(self.rest, item)["price"], item) for item in self.cart]
        best = max(v for v, _ in values) if reverse else min(v for v, _ in values)
        for _, item in list(values):
            if dish(self.rest, item)["price"] == best:
                self.remove(item, None, reason or "price tie")

    def remove_non_set_by_discount(self, reason: str = "") -> None:
        if not self.cart:
            return
        best = min(dish(self.rest, item)["discount"] for item in self.cart)
        for item in list(self.cart):
            if dish(self.rest, item)["discount"] == best:
                self.remove(item, None, reason or "smallest discount factor")

    def maybe_convert_exact_set(self, reason: str = "") -> None:
        current = {k: int(v) for k, v in self.cart.items()}
        for set_name, meal in SET_MEALS_BY_REST[self.rest].items():
            included = {i["dish_name"]: int(i.get("quantity", 1)) for i in meal["included_dishes"]}
            if current == included:
                for item, qty in list(self.cart.items()):
                    self.remove(item, qty, reason or "convert exact set")
                self.add_set([set_name], 1, reason or "convert exact set")
                return

    def compute(self, kinds: list[str]) -> None:
        dishes = [
            {"dish_name": DISPLAY[self.rest][item], "quantity": int(qty) if qty == int(qty) else qty}
            for item, qty in self.cart.items()
        ] + [
            {"dish_name": DISPLAY_SET[self.rest][item], "quantity": int(qty) if qty == int(qty) else qty}
            for item, qty in self.sets.items()
        ]
        tool_map = {
            "payment": "compute_total_payment",
            "tax": "compute_total_tax",
            "nutrition": "compute_total_nutrition",
        }
        for kind in kinds:
            self.calls.append(
                {
                    "tool_name": tool_map[kind],
                    "parameters": {"restaurant_name": self.rest, "user_id": self.user_id, "dishes": dishes},
                }
            )


def high_calorie(name: str) -> bool:
    return has_tag(GREEK, name, "high_calories")


def build_task(task_id: int) -> Builder | None:
    user_id = f"customer_{((task_id - 1) % 10) + 1:03d}"
    # The official task IDs use customer_001..010 cyclically except where text says otherwise;
    # explicit entries below override by task statement.
    explicit_users = {
        1: "customer_001", 2: "customer_002", 3: "customer_003", 4: "customer_004", 5: "customer_005",
        6: "customer_006", 7: "customer_007", 8: "customer_008", 9: "customer_009", 10: "customer_010",
        11: "customer_001", 12: "customer_002", 13: "customer_003", 14: "customer_004", 15: "customer_005",
        16: "customer_006", 17: "customer_007", 18: "customer_008", 19: "customer_009", 20: "customer_010",
        21: "customer_001", 22: "customer_002", 23: "customer_003", 24: "customer_004", 25: "customer_005",
        26: "customer_006", 27: "customer_007", 28: "customer_009", 29: "customer_010", 30: "customer_001",
        31: "customer_002", 32: "customer_003", 33: "customer_004", 34: "customer_005", 35: "customer_006",
        36: "customer_007", 37: "customer_008", 38: "customer_009", 39: "customer_010", 40: "customer_001",
        41: "customer_002", 42: "customer_003", 43: "customer_004", 44: "customer_005", 45: "customer_006",
        46: "customer_007", 47: "customer_008", 48: "customer_009", 49: "customer_001", 50: "customer_002",
        51: "customer_003", 52: "customer_004", 53: "customer_005", 54: "customer_006", 55: "customer_007",
        56: "customer_008", 57: "customer_009", 58: "customer_010", 59: "customer_001", 60: "customer_002",
        61: "customer_003", 62: "customer_004", 63: "customer_005", 64: "customer_006", 65: "customer_007",
        66: "customer_008", 67: "customer_009", 68: "customer_001", 69: "customer_003", 70: "customer_004",
        71: "customer_005", 72: "customer_006", 73: "customer_007", 74: "customer_008", 75: "customer_009",
        76: "customer_010", 77: "customer_001", 78: "customer_003", 79: "customer_005", 80: "customer_006",
        81: "customer_007", 82: "customer_008", 83: "customer_009", 84: "customer_010", 85: "customer_001",
        86: "customer_002", 87: "customer_004", 88: "customer_005", 89: "customer_006", 90: "customer_007",
        91: "customer_009", 92: "customer_010", 93: "customer_001", 94: "customer_002", 95: "customer_003",
        96: "customer_004", 97: "customer_005",
    }
    b = Builder(explicit_users.get(task_id, user_id), GREEK)

    if task_id == 1:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        b.add(price_min(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "appetizers" and has_tag(GREEK, x, "vegan")), reason=f"{DISPLAY[GREEK][anchor]} protein > 20")
        if b.non_set_total_price(False) > 100:
            b.remove_non_set_by_price(True, "replace most expensive non-set item")
            b.add(discount_best(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "seafood"), reason="seafood with highest discount")
        b.compute(["nutrition", "tax"])
    elif task_id == 2:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if dish(GREEK, anchor)["price"] < 88:
            b.add(metric_min(GREEK, lambda x: False, "calories_kcal"), reason="unreachable")
        else:
            b.add([VISUAL["right list first item on fifth page"]], 2, "first item in right text list on fifth page")
        if b.total_metric("calories_kcal") > 500:
            b.remove_non_set_by_price(True, "total calories > 500")
        b.compute(["payment", "nutrition"])
    elif task_id == 3:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if has_allergen(GREEK, anchor, "seafood"):
            b.add(price_min(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "soups" and has_tag(GREEK, x, "high_fiber")), reason="fried calamari contains seafood")
        else:
            b.add([VISUAL["red seafood in copper double-handled pot"]], 1, "fallback copper pot")
        if b.contains_allergen("dairy"):
            b.clear("order contains dairy")
            b.add(metric_max(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "main courses" and has_taste(GREEK, x, "savory"), "protein_g"), reason="re-add staple with highest protein and savory")
        b.compute(["nutrition", "tax"])
    elif task_id == 4:
        anchor = VISUAL["grilled vegetable skewer on wooden cutting board"]
        if has_taste(GREEK, anchor, "sour"):
            b.add(metric_max(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "desserts" and has_tag(GREEK, x, "high_calories"), "sugar_g"), reason="sour flavor")
        else:
            b.add([VISUAL["white plate dessert at bottom right of sixth page"]], 2, "bottom-right sixth-page white plate")
        if b.non_set_total_price(False) > 150:
            b.remove_non_set_by_metric("fat_g", True, "order price > 150; remove highest fat")
        b.compute(["nutrition", "payment"])
    elif task_id == 5:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if n(GREEK, anchor, "sodium_mg") < 400:
            b.add(ties(GREEK, names(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "seafood" and has_taste(GREEK, x, "savory")), greek_discounted_price), reason="low sodium branch")
        else:
            b.add([VISUAL["right list third item on fifth page"]], 2, "third item in right text list on fifth page")
        b.maybe_convert_exact_set("exact set meal match")
        b.compute(["payment", "nutrition"])
    elif task_id == 6:
        anchor = VISUAL["dark grey plate with white sauce dish"]
        if n(GREEK, anchor, "fat_g") > 25:
            b.add([VISUAL["dairy product in wooden bowl"]], 2, "lowest carbohydrates on sixth expanded page")
        else:
            b.add(metric_max(GREEK, lambda x: dish(GREEK, x)["category"].lower() in {"main courses", "pasta", "seafood", "sides"} and has_taste(GREEK, x, "salty") and has_taste(GREEK, x, "savory"), "calories_kcal"), reason="fallback salty savory staple")
        if b.non_set_total_price(False) < 100:
            b.add(price_min(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "sides" and has_taste(GREEK, x, "sweet")), reason="low total price side sweet")
        b.compute(["nutrition", "tax"])
    elif task_id == 7:
        anchor = VISUAL["right list second item on fifth page"]
        if has_allergen(GREEK, anchor, "gluten"):
            b.add(metric_max(GREEK, lambda x: not dish(GREEK, x).get("allergens"), "protein_g"), reason="gluten allergen branch")
        else:
            b.add([VISUAL["right list first item on fifth page"]], 3, "previous item")
        if b.non_set_total_price(False) > 200:
            b.remove_non_set_by_price(True, "total price > 200; reduce most expensive by 1")
        b.compute(["nutrition", "payment"])
    elif task_id == 8:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if dish(GREEK, anchor)["price"] > 98:
            b.add(metric_min(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "appetizers" and has_tag(GREEK, x, "low_calories"), "sodium_mg"), 2, "price above 98")
        else:
            b.add([VISUAL["dairy product in wooden bowl"]], 1, "fallback wooden bowl")
        if b.total_metric("protein_g") < 30:
            b.add(price_min(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "seafood"), reason="protein < 30")
        b.compute(["tax", "nutrition"])
    elif task_id == 9:
        anchor = VISUAL["dark blue casserole containing seafood / seafood paella"]
        if n(GREEK, anchor, "calories_kcal") < 250:
            b.add(metric_min(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "soups" and has_taste(GREEK, x, "mild"), "fat_g"), reason="low calorie soup branch")
        else:
            b.add([VISUAL["bright blue plate with fried items and lemon"]], 1, "bright blue plate")
        b.maybe_convert_exact_set("exact set meal match")
        b.compute(["nutrition", "payment"])
    elif task_id == 10:
        anchor = VISUAL["grilled vegetable skewer on wooden cutting board"]
        if dish(GREEK, anchor)["discount"] <= 0.8:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "calories_kcal"), reason="discount at least 20%")
        else:
            b.add([VISUAL["dark blue casserole containing seafood / seafood paella"]], 2, "fallback seafood casserole")
        if b.non_set_total_price(False) > 180:
            b.remove_non_set_by_metric("carbs_g", True, "total amount > 180; highest carbs")
        b.compute(["nutrition", "payment"])
    elif task_id == 11:
        anchor = VISUAL["dairy product in wooden bowl"]
        if n(GREEK, anchor, "sugar_g") < 20:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "low_calories"), "protein_g"), reason="wooden bowl sugar < 20")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "savory")), 2, "fallback savory cheapest")
        if b.total_metric("calories_kcal") > 600:
            b.remove_non_set_by_metric("fat_g", True, "calories > 600")
        b.compute(["tax", "nutrition"])
    elif task_id == 12:
        b.add(metric_max(GREEK, lambda x: dish(GREEK, x)["category"].lower() == "desserts", "sugar_g"), reason="children enjoy desserts; choose sweet dessert")
        b.compute(["payment", "nutrition"])
    elif task_id == 13:
        b.add([VISUAL["right list second item on fifth page"]], 1, "family requires pasta/noodles with cephalopod")
        b.compute(["payment", "nutrition"])
    elif task_id == 14:
        b.add([VISUAL["dark blue casserole containing seafood / seafood paella"]], 1, "rainy takeout wants seafood risotto")
        b.compute(["payment", "nutrition"])
    elif task_id == 15:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if n(GREEK, anchor, "sodium_mg") > 500:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "low_fat")), 3, "sodium > 500")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sour"), "fiber_g"), reason="fallback sour high fiber")
        if b.non_set_total_price(False) < 100:
            b.add([VISUAL["red seafood in copper double-handled pot"]], 1, "non-set total < 100")
        b.compute(["nutrition", "tax"])
    elif task_id == 16:
        anchor = VISUAL["right list first item on fifth page"]
        if has_allergen(GREEK, anchor, "dairy"):
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "savory"), "carbs_g"), 2, "dairy allergen branch")
        else:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "protein_g"), reason="fallback vegan high protein")
        # Tax from one or two added low-carb savory dishes is below this threshold.
        b.compute(["nutrition"])
    elif task_id == 17:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if has_allergen(GREEK, anchor, "seafood"):
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_protein"), "fat_g"), reason="seafood allergen branch")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "sugar_g"), 2, "fallback sweet")
        if b.total_metric("sodium_mg") > 800:
            b.remove_non_set_by_metric("sodium_mg", True, "sodium > 800")
        b.compute(["payment", "nutrition"])
    elif task_id == 18:
        anchor = VISUAL["dark blue casserole containing seafood / seafood paella"]
        if has_taste(GREEK, anchor, "salty") and has_taste(GREEK, anchor, "savory"):
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "high_calories")), reason="salty and savory branch")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sour"), "protein_g"), 2, "fallback sour high protein")
        # One selected sour dish does not form a known set meal.
        b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "vegan")), reason="cannot form set; add cheapest pure vegan dish")
        b.compute(["nutrition", "payment"])
    elif task_id == 19:
        anchor = VISUAL["dark grey plate with white sauce dish"]
        if n(GREEK, anchor, "calories_kcal") > 400:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "fiber_g"), reason="calories > 400")
        else:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_protein"), "sodium_mg"), 2, "fallback high-protein low sodium")
        if b.non_set_total_price(False) > 250:
            b.remove_non_set_by_price(True, "undiscounted total > 250")
        b.compute(["nutrition", "tax"])
    elif task_id == 20:
        anchor = VISUAL["right list third item on fifth page"]
        if has_allergen(GREEK, anchor, "gluten"):
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "calories_kcal"), reason="gluten branch")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "fat_g"), 2, "fallback sweet fat")
        if b.non_set_total_price(False) > 150:
            b.remove_non_set_by_discount("budget > 150; remove smallest discount factor")
        b.compute(["nutrition", "payment"])
    elif task_id == 21:
        anchor = VISUAL["dairy product in wooden bowl"]
        if n(GREEK, anchor, "carbs_g") < 20:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "protein_g"), reason="wooden bowl carbs < 20")
        else:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "low_calories")), 2, "fallback lowest-price low-calorie")
        if b.non_set_total_price(False) > 150:
            b.remove_non_set_by_price(True, "total amount > 150")
        b.compute(["nutrition", "tax"])
    elif task_id == 22:
        anchor = VISUAL["white plate dessert at bottom right of sixth page"]
        if n(GREEK, anchor, "sugar_g") > 20:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "sugar_g"), 2, "white-plate sugar > 20")
        else:
            b.add(discount_best(GREEK, lambda x: has_taste(GREEK, x, "sweet")), reason="fallback sweet largest discount")
        if b.total_metric("protein_g") < 10:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "savory")), reason="protein < 10")
        b.compute(["nutrition", "payment"])
    elif task_id == 23:
        anchor = VISUAL["grilled vegetable skewer on wooden cutting board"]
        if not dish(GREEK, anchor).get("allergens"):
            b.add(metric_max(GREEK, lambda x: 48 <= dish(GREEK, x)["price"] <= 88, "calories_kcal"), 2, "no explicit allergen branch")
        else:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_protein"), "carbs_g"), reason="fallback high-protein low-carb")
        b.maybe_convert_exact_set("exact set meal match")
        b.compute(["tax", "nutrition"])
    elif task_id == 24:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if has_taste(GREEK, anchor, "savory"):
            b.add(ties(GREEK, names(GREEK, lambda x: has_allergen(GREEK, x, "seafood")), greek_discounted_price), reason="savory seafood; lowest discounted price")
        else:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "mild"), "calories_kcal"), 2, "fallback mild lowest calories")
        if b.non_set_total_price(True) > 200:
            b.remove_non_set_by_price(True, "discounted non-set payable > 200")
        b.compute(["payment", "nutrition"])
    elif task_id == 25:
        anchor = VISUAL["right list second item on fifth page"]
        if has_allergen(GREEK, anchor, "gluten"):
            b.add(price_max(GREEK, lambda x: has_taste(GREEK, x, "sour")), reason="gluten branch; highest-price sour")
        else:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "high_calories")), 2, "fallback high-calorie lowest price")
        if b.total_metric("calories_kcal") > 800:
            b.remove_non_set_by_metric("calories_kcal", True, "calories > 800")
        b.compute(["nutrition"])
    elif task_id == 26:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if n(GREEK, anchor, "sodium_mg") > 400:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "vegan")), reason="sodium > 400; cheapest vegan")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "protein_g"), 2, "fallback savory high protein")
        if b.contains_allergen("dairy"):
            b.clear("current order contains dairy")
            b.add(discount_best(GREEK, lambda x: True), reason="largest discount after clear")
        b.compute(["payment", "nutrition"])
    elif task_id == 27:
        anchor = VISUAL["dark blue casserole containing seafood / seafood paella"]
        if n(GREEK, anchor, "carbs_g") < 10:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "high_protein"), "fat_g"), reason="low-carb branch")
        else:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "low_calories")), 2, "fallback low-calorie cheapest")
        if b.total_metric("carbs_g") > 30:
            b.remove_non_set_by_metric("carbs_g", True, "carbs > 30")
        b.compute(["nutrition"])
    elif task_id == 28:
        anchor = VISUAL["dark grey plate with white sauce dish"]
        if n(GREEK, anchor, "calories_kcal") > 250:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "calories_kcal"), reason="calories > 250; sweet highest calories")
        else:
            b.add(discount_best(GREEK, lambda x: has_tag(GREEK, x, "high_fiber")), 2, "fallback high-fiber discount")
        if b.total_metric("sugar_g") > 40:
            b.remove_non_set_by_metric("sugar_g", True, "sugar > 40")
        b.compute(["tax", "nutrition"])
    elif task_id == 29:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if dish(GREEK, anchor)["price"] < 98:
            b.add(metric_max(GREEK, lambda x: n(GREEK, x, "sodium_mg") < 400, "protein_g"), reason="price < 98")
        else:
            b.add(price_min(GREEK, lambda x: has_allergen(GREEK, x, "nuts")), reason="fallback nut-allergen lowest price")
        if b.non_set_total_price(False) < 100 and b.cart:
            cheapest = price_min(GREEK, lambda x: x in b.cart)
            b.add(cheapest, 1, "order total < 100; increase lowest-priced dish")
        b.compute(["nutrition"])
    elif task_id == 30:
        anchor = VISUAL["white plate dessert at bottom right of sixth page"]
        if n(GREEK, anchor, "fat_g") < 10:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "carbs_g"), 2, "below wooden bowl fat < 10")
        else:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_sugar"), "protein_g"), reason="fallback high-sugar low protein")
        if b.total_metric("fat_g") > 45:
            b.remove_non_set_by_metric("fat_g", True, "fat > 45")
        b.compute(["payment", "nutrition"])
    elif task_id == 31:
        anchor = VISUAL["right list third item on fifth page"]
        if dish(GREEK, anchor)["tax_rate"] > 0.1:
            b.add(metric_min(GREEK, lambda x: has_allergen(GREEK, x, "seafood"), "sugar_g"), reason="tax > 0.1")
        else:
            b.add(ties(GREEK, names(GREEK, lambda x: has_taste(GREEK, x, "sour")), greek_discounted_price, True), 2, "fallback sour highest discounted price")
        b.maybe_convert_exact_set("set meal conversion if exact")
        b.compute(["nutrition", "payment"])
    elif task_id == 32:
        anchor = VISUAL["grilled vegetable skewer on wooden cutting board"]
        if has_tag(GREEK, anchor, "high_calories"):
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "sodium_mg"), reason="high-calorie branch")
        else:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "protein_g"), 2, "fallback sweet lowest protein")
        if b.contains_allergen("dairy"):
            dairy_items = [item for item in b.cart if has_allergen(GREEK, item, "dairy")]
            for item in price_max(GREEK, lambda x: x in dairy_items):
                b.remove(item, None, "remove most expensive dairy item")
        b.compute(["nutrition", "tax"])
    elif task_id == 33:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if has_allergen(GREEK, anchor, "seafood"):
            b.add(metric_max(GREEK, lambda x: not dish(GREEK, x).get("allergens"), "carbs_g"), reason="seafood allergen branch")
        else:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "high_fiber")), 3, "fallback high-fiber lowest price")
        if b.total_metric("sodium_mg") > 1000:
            b.remove_non_set_by_metric("sodium_mg", True, "sodium > 1000")
        b.compute(["nutrition", "payment"])
    elif task_id == 34:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if 98 <= dish(GREEK, anchor)["price"] <= 198:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "low_calories"), "fat_g"), 2, "price in range")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "sugar_g"), reason="fallback savory highest sugar")
        if b.non_set_total_price(False) > 300:
            b.remove_non_set_by_price(True, "pre-discount total > 300; halve highest-price item")
        b.compute(["nutrition", "tax"])
    elif task_id == 35:
        anchor = VISUAL["dairy product in wooden bowl"]
        if has_taste(GREEK, anchor, "mild"):
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "sodium_mg"), reason="mild branch")
        else:
            candidates = names(GREEK, lambda x: has_taste(GREEK, x, "sweet"))
            max_price = max(dish(GREEK, x)["price"] for x in candidates)
            top = [x for x in candidates if dish(GREEK, x)["price"] == max_price]
            b.add(discount_best(GREEK, lambda x: x in top), 2, "fallback sweet highest price and smallest discount")
        if b.total_metric("protein_g") > 60:
            b.add(metric_min(GREEK, lambda x: True, "protein_g"), reason="protein > 60; balance lowest protein")
        b.compute(["payment", "nutrition"])
    elif task_id == 36:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if has_tag(GREEK, anchor, "high_protein"):
            b.add(metric_min(GREEK, lambda x: dish(GREEK, x)["price"] < 60, "calories_kcal"), 2, "high-protein branch")
        else:
            b.add(price_max(GREEK, lambda x: has_allergen(GREEK, x, "gluten")), reason="fallback gluten highest price")
        if b.non_set_total_price(False) > 120:
            b.remove_non_set_by_price(True, "tax-included non-set > 120")
        b.compute(["nutrition", "payment"])
    elif task_id == 37:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if n(GREEK, anchor, "carbs_g") < 25:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "fat_g"), reason="carbs below 25")
        else:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "vegan")), 2, "fallback vegan lowest price")
        if b.total_metric("sodium_mg") > 1500:
            b.remove_non_set_by_metric("sodium_mg", True, "sodium > 1500")
        b.compute(["nutrition", "payment"])
    elif task_id == 38:
        anchor = VISUAL["right list second item on fifth page"]
        if has_allergen(GREEK, anchor, "dairy"):
            b.add(metric_max(GREEK, lambda x: discounted_price(GREEK, x) < 50, "calories_kcal"), 2, "dairy branch")
        else:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "low_fat"), "protein_g"), reason="fallback low-fat high protein")
        b.maybe_convert_exact_set("set meal conversion if exact")
        b.compute(["tax", "nutrition"])
    elif task_id == 39:
        anchor = VISUAL["dark grey plate with white sauce dish"]
        if 12 <= n(GREEK, anchor, "fat_g") <= 45:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sour"), "sugar_g"), reason="fat in range")
        else:
            b.add(price_max(GREEK, lambda x: not dish(GREEK, x).get("allergens")), 2, "fallback no-allergen highest price")
        if any(has_allergen(GREEK, item, "seafood") for item in b.cart):
            b.clear("contains seafood allergen")
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "protein_g"), reason="vegan highest protein")
        b.compute(["nutrition", "payment"])
    elif task_id == 40:
        anchor = VISUAL["dairy product in wooden bowl"]
        if n(GREEK, anchor, "sugar_g") > 20:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "savory"), "fat_g"), 2, "sugar exceeds 20")
        else:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "high_protein")), reason="fallback high-protein lowest price")
        b.maybe_convert_exact_set("set meal conversion if exact")
        b.compute(["nutrition", "payment"])
    elif task_id == 41:
        anchor = VISUAL["dark blue casserole containing seafood / seafood paella"]
        if n(GREEK, anchor, "calories_kcal") < 300:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_protein"), "carbs_g"), reason="calories < 300")
        else:
            b.add(price_max(GREEK, lambda x: has_taste(GREEK, x, "mild")), 2, "fallback mild highest unit price")
        if b.total_metric("calories_kcal") > 650:
            b.remove_non_set_by_metric("calories_kcal", True, "calories > 650")
        b.compute(["nutrition", "tax"])
    elif task_id == 42:
        anchor = VISUAL["dairy product in wooden bowl"]
        if has_allergen(GREEK, anchor, "nuts"):
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "calories_kcal"), 2, "nut allergen branch")
        else:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "low_fat"), "sodium_mg"), reason="fallback low-fat highest sodium")
        b.add_set(["dessert pairing set"], 1, "circled dessert can form Dessert Pairing Set")
        b.compute(["payment", "nutrition"])
    elif task_id == 43:
        anchor = VISUAL["grilled vegetable skewer on wooden cutting board"]
        if n(GREEK, anchor, "protein_g") < 14:
            b.add(price_max(GREEK, lambda x: has_allergen(GREEK, x, "seafood")), reason="protein < 14")
        else:
            b.add(discount_best(GREEK, lambda x: has_tag(GREEK, x, "vegan")), 2, "fallback vegan biggest discount")
        if b.non_set_total_price(False) > 180:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sour")), reason="non-set total > 180; add cheapest sour dish")
        b.compute(["nutrition", "tax"])
    elif task_id == 44:
        anchor = VISUAL["right list first item on fifth page"]
        if dish(GREEK, anchor)["tax_rate"] < 0.1:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "umami"), "calories_kcal"), reason="tax rate < 0.1")
        else:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "sugar_g"), 2, "fallback high-calorie highest sugar")
        if b.non_set_total_price(False) > 250:
            b.remove_non_set_by_price(True, "undiscounted total > 250")
        b.compute(["nutrition", "payment"])
    elif task_id == 45:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if n(GREEK, anchor, "calories_kcal") > 500:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sweet")), 2, "calories > 500")
        else:
            b.add(metric_max(GREEK, lambda x: not dish(GREEK, x).get("allergens"), "protein_g"), reason="fallback no-allergen highest protein")
        if b.contains_allergen("dairy"):
            b.clear("trace dairy allergen")
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "vegan")), reason="lowest-priced vegan replacement")
        b.compute(["nutrition", "payment"])
    elif task_id == 46:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if n(GREEK, anchor, "sodium_mg") > 800:
            b.add(metric_min(GREEK, lambda x: n(GREEK, x, "carbs_g") >= 40, "fat_g"), reason="sodium > 800")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "mild"), "calories_kcal"), 2, "fallback mild highest calories")
        b.maybe_convert_exact_set("single items match set")
        b.compute(["nutrition", "tax"])
    elif task_id == 47:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if discounted_price(GREEK, anchor) < 100:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sour"), "sugar_g"), 2, "discounted price below 100")
        else:
            b.add(price_max(GREEK, lambda x: has_tag(GREEK, x, "high_protein")), reason="fallback high-protein highest price")
        if b.total_metric("carbs_g") > 20:
            b.remove_non_set_by_metric("carbs_g", True, "carbs > 20")
        b.compute(["nutrition", "payment"])
    elif task_id == 48:
        anchor = VISUAL["dark grey plate with white sauce dish"]
        if has_tag(GREEK, anchor, "high_fiber"):
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "protein_g"), reason="high-fiber branch")
        else:
            b.add(discount_best(GREEK, lambda x: has_tag(GREEK, x, "low_fat")), 2, "fallback low-fat biggest discount")
        if b.total_metric("sugar_g") > 15:
            b.remove_non_set_by_metric("sugar_g", True, "sugar > 15")
        b.compute(["nutrition", "tax"])
    elif task_id == 49:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if has_taste(GREEK, anchor, "savory"):
            added = price_min(GREEK, lambda x: has_tag(GREEK, x, "vegan"))
            b.add(added, 2, "savory chicken branch; lowest-priced vegan")
        else:
            added = metric_max(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "protein_g")
            b.add(added, 1, "fallback high-calorie highest protein")
        b.add(added, 1, "selected dish has no exact bundle conversion; add one more portion")
        b.compute(["nutrition", "tax"])
    elif task_id == 50:
        anchor = VISUAL["right list third item on fifth page"]
        if n(GREEK, anchor, "sugar_g") < 10:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sour"), "fat_g"), 2, "sugar < 10")
        else:
            b.add(price_max(GREEK, lambda x: has_tag(GREEK, x, "low_calories")), reason="fallback low-calorie highest price")
        b.add_set(["greek classic set"], 1, "discounted items already present; add set with largest set discount")
        b.compute(["payment", "nutrition"])
    elif task_id == 51:
        anchor = VISUAL["dark grey plate with white sauce dish"]
        if has_allergen(GREEK, anchor, "dairy"):
            b.add(discount_best(GREEK, lambda x: has_taste(GREEK, x, "sweet")), reason="dairy allergen branch")
        else:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_protein"), "sodium_mg"), 2, "fallback high-protein lowest sodium")
        if not any(has_tag(GREEK, item, "high_sodium") for item in b.cart):
            for item in list(b.cart):
                if dish(GREEK, item)["price"] == min(dish(GREEK, x)["price"] for x in b.cart):
                    b.remove(item, None, "replace lowest-priced non-set with high-sodium dish")
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_sodium"), "calories_kcal"), reason="high-sodium lowest calorie")
        b.compute(["nutrition", "payment"])
    elif task_id == 52:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if n(GREEK, anchor, "calories_kcal") < 700:
            b.add(metric_max(GREEK, lambda x: not dish(GREEK, x).get("allergens"), "carbs_g"), 2, "calories < 700")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "salty") and has_taste(GREEK, x, "savory")), reason="fallback salty savory lowest price")
        if any(has_allergen(GREEK, item, "seafood") for item in b.cart):
            b.clear("seafood allergen in order")
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "protein_g"), reason="vegan highest protein")
        b.compute(["payment", "nutrition"])
    elif task_id == 53:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if has_tag(GREEK, anchor, "low_fat"):
            b.add(price_max(GREEK, lambda x: has_allergen(GREEK, x, "seafood")), reason="low-fat branch; seafood highest price")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sour"), "fiber_g"), 2, "fallback sour highest fiber")
        if any(has_allergen(GREEK, item, "nuts") for item in b.cart):
            for item in list(b.cart):
                if has_allergen(GREEK, item, "nuts"):
                    b.remove(item, None, "remove nut allergen")
        b.compute(["tax", "nutrition"])
    elif task_id == 54:
        anchor = VISUAL["dairy product in wooden bowl"]
        if n(GREEK, anchor, "sugar_g") > 20:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sweet")), 2, "sugar exceeds 20")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "mild"), "calories_kcal"), reason="fallback mild highest calories")
        if b.total_metric("sugar_g") > 50:
            b.remove_non_set_by_metric("sugar_g", True, "sugar > 50")
        b.compute(["payment", "tax"])
    elif task_id == 55:
        anchor = VISUAL["grilled vegetable skewer on wooden cutting board"]
        if n(GREEK, anchor, "protein_g") > 20:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "high_fiber")), 3, "protein > 20")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "fat_g"), reason="fallback savory highest fat")
        if b.non_set_total_price(False) > 200:
            totals = {item: dish(GREEK, item)["price"] * qty for item, qty in b.cart.items()}
            top = max(totals.values())
            for item, total in list(totals.items()):
                if total == top:
                    b.remove(item, 1, "current price > 200; reduce highest total-price non-set by one")
        b.compute(["tax", "nutrition"])
    elif task_id == 56:
        anchor = VISUAL["right list second item on fifth page"]
        if dish(GREEK, anchor)["discount"] < 0.85:
            b.add(metric_min(GREEK, lambda x: has_allergen(GREEK, x, "gluten"), "calories_kcal"), 2, "discount factor < 0.85")
        else:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "low_calories"), "sodium_mg"), reason="fallback low-calorie highest sodium")
        b.maybe_convert_exact_set("set below threshold if exact")
        b.compute(["nutrition", "payment"])
    elif task_id == 57:
        anchor = VISUAL["dark blue casserole containing seafood / seafood paella"]
        if dish(GREEK, anchor)["price"] < 88:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "sugar_g"), reason="price below 88")
        else:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "vegan")), 2, "fallback vegan lowest price")
        if b.non_set_total_price(False) > 200:
            b.clear("non-set total > 200")
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "salty") and has_taste(GREEK, x, "savory")), reason="salty savory lowest price")
        b.compute(["tax", "nutrition"])
    elif task_id == 58:
        anchor = VISUAL["dairy product in wooden bowl"]
        if has_allergen(GREEK, anchor, "dairy") and has_allergen(GREEK, anchor, "nuts"):
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sour") and not dish(GREEK, x).get("allergens")), 2, "dairy and nut allergen branch")
        else:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "carbs_g"), reason="fallback high-calorie lowest carbs")
        if b.non_set_total_price(False) < 50:
            b.add(metric_max(GREEK, lambda x: True, "protein_g"), reason="non-set total < 50")
        b.compute(["payment", "nutrition"])
    elif task_id == 59:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if dish(GREEK, anchor)["price"] < 150:
            b.add(metric_min(GREEK, lambda x: not has_allergen(GREEK, x, "seafood"), "calories_kcal"), 2, "price below 150")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "umami") and has_taste(GREEK, x, "savory")), reason="fallback fresh-savory lowest price")
        b.clear("selected individual dish is included in Mediterranean Feast Set; replace with set")
        b.add_set(["mediterranean feast set"], 1, "replace individual dishes with set meal")
        b.compute(["payment", "nutrition"])
    elif task_id == 60:
        anchor = VISUAL["dark grey plate with white sauce dish"]
        if has_taste(GREEK, anchor, "spicy"):
            b.add(metric_max(GREEK, lambda x: dish(GREEK, x)["price"] < 150, "protein_g"), 2, "spicy branch")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "umami")), reason="fallback umami lowest price")
        if b.total_metric("calories_kcal") > 800:
            b.remove_non_set_by_metric("carbs_g", True, "calories > 800; remove highest-carb/high-fat candidate")
        b.compute(["nutrition", "payment"])
    elif task_id == 61:
        anchor = VISUAL["right list first item on fifth page"]
        if n(GREEK, anchor, "sugar_g") > 10:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "sugar_g"), reason="sugar > 10")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "calories_kcal"), 2, "fallback savory highest calories")
        if not any(dish(GREEK, item)["discount"] < 1 for item in b.cart):
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "high_fiber")), reason="no discounted items")
        b.compute(["tax", "nutrition"])
    elif task_id == 62:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if n(GREEK, anchor, "sodium_mg") > 800:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "low_fat"), "protein_g"), reason="sodium > 800")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "salty")), 2, "fallback salty lowest price")
        if not any(has_allergen(GREEK, item, "dairy") for item in b.cart):
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "carbs_g"), reason="no dairy; add high-calorie lowest carbs")
        b.compute(["nutrition", "tax"])
    elif task_id == 63:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if 98 <= dish(GREEK, anchor)["price"] <= 198:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "protein_g"), 2, "price in [98,198]; savory highest protein")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "mild")), reason="fallback mild lowest price")
        if b.non_set_total_price(False) > 280:
            b.remove_non_set_by_price(True, "non-set total > 280; remove most expensive")
        b.compute(["tax", "nutrition"])
    elif task_id == 64:
        anchor = VISUAL["grilled vegetable skewer on wooden cutting board"]
        if has_taste(GREEK, anchor, "spicy"):
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "high_protein"), "calories_kcal"), 2, "spicy branch")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "salty")), reason="fallback salty lowest price")
        if b.total_metric("sodium_mg") > 2000:
            b.remove_non_set_by_metric("sodium_mg", True, "sodium > 2000")
        b.compute(["payment", "nutrition"])
    elif task_id == 65:
        anchor = VISUAL["dark blue casserole containing seafood / seafood paella"]
        if dish(GREEK, anchor)["price"] < 100:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sweet")), reason="price below 100")
        else:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sweet") and dish(GREEK, x)["price"] <= 70, "sugar_g"), 2, "fallback sweet <=70 lowest sugar")
        if b.total_metric("sugar_g") > 30:
            b.remove_non_set_by_metric("sugar_g", True, "sugar > 30")
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sour")), reason="replace with cheapest sour dish")
        b.compute(["payment", "nutrition"])
    elif task_id == 66:
        anchor = VISUAL["right list second item on fifth page"]
        if not has_allergen(GREEK, anchor, "dairy") and not has_allergen(GREEK, anchor, "eggs"):
            b.add(metric_max(GREEK, lambda x: has_allergen(GREEK, x, "gluten") and has_taste(GREEK, x, "sweet"), "protein_g"), reason="no dairy/egg; gluten sweet highest protein")
        else:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "low_fat"), "calories_kcal"), 2, "fallback low-fat lowest calories")
        if b.total_metric("calories_kcal") > 700:
            b.remove_non_set_by_metric("calories_kcal", True, "calories > 700")
        b.compute(["tax", "nutrition"])
    elif task_id == 67:
        anchor = VISUAL["right list third item on fifth page"]
        if n(GREEK, anchor, "sodium_mg") < 500:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "mild"), "fiber_g"), reason="sodium < 500")
        else:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "high_calories")), 2, "fallback high-calorie lowest price")
        if b.non_set_total_price(False) > 750:
            b.remove_non_set_by_price(True, "price > 750")
        b.compute(["payment", "nutrition"])
    elif task_id == 68:
        anchor = VISUAL["dairy product in wooden bowl"]
        if n(GREEK, anchor, "carbs_g") < 10:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "fat_g"), 2, "carbs < 10")
        else:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "savory") and dish(GREEK, x)["price"] < 100, "carbs_g"), reason="fallback savory <100 lowest carbs")
        if b.total_metric("fat_g") < 30:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "high_fat")), reason="fat < 30; cheapest high-fat")
        b.compute(["nutrition", "tax"])
    elif task_id == 69:
        anchor = VISUAL["dark grey plate with white sauce dish"]
        if n(GREEK, anchor, "protein_g") > n(GREEK, anchor, "fat_g"):
            b.add(metric_min(GREEK, lambda x: not dish(GREEK, x).get("allergens"), "calories_kcal"), 2, "protein > fat")
        else:
            b.add(price_max(GREEK, lambda x: has_taste(GREEK, x, "sweet")), reason="fallback sweet highest price")
        dairy_items = [item for item in b.cart if has_allergen(GREEK, item, "dairy")]
        for item in dairy_items:
            b.remove(item, None, "remove dairy-containing item")
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "vegan")), reason="replace dairy with cheapest vegan")
        b.compute(["nutrition", "tax"])
    elif task_id == 70:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if has_allergen(GREEK, anchor, "seafood"):
            b.add(metric_max(GREEK, lambda x: dish(GREEK, x)["price"] > 98, "protein_g"), 2, "seafood allergen branch")
        else:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sour"), "calories_kcal"), reason="fallback sour lowest calories")
        if not any(has_tag(GREEK, item, "high_omega_3") for item in b.cart):
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "low_fat")), reason="no high Omega-3 label; add low-fat lowest price")
        b.compute(["tax", "payment"])
    elif task_id == 71:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if n(GREEK, anchor, "sodium_mg") > 800:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "low_calories") and dish(GREEK, x)["price"] < 90, "sodium_mg"), reason="sodium > 800")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "protein_g"), 2, "fallback savory highest protein")
        if b.total_metric("sodium_mg") > 2000:
            b.remove_non_set_by_price(True, "sodium > 2000; remove most expensive")
        b.compute(["payment", "nutrition"])
    elif task_id == 72:
        anchor = VISUAL["grilled vegetable skewer on wooden cutting board"]
        if dish(GREEK, anchor)["price"] > 85:
            b.add(metric_max(GREEK, lambda x: dish(GREEK, x)["discount"] < 1.0, "calories_kcal"), reason="price > 85")
        else:
            b.add(price_min(GREEK, lambda x: not has_allergen(GREEK, x, "seafood")), 2, "fallback no-seafood lowest price")
        if not any(has_taste(GREEK, item, "spicy") for item in b.cart):
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sour")), reason="no spicy label; add cheapest sour")
        b.compute(["tax", "nutrition"])
    elif task_id == 73:
        anchor = VISUAL["dark blue casserole containing seafood / seafood paella"]
        if has_tag(GREEK, anchor, "vegan"):
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "calories_kcal"), reason="vegan branch")
        else:
            b.add(price_max(GREEK, lambda x: not dish(GREEK, x).get("allergens")), 2, "fallback no-allergen highest price")
        if any(has_allergen(GREEK, item, "eggs") for item in b.cart):
            b.clear("egg allergen included")
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "carbs_g"), reason="vegan highest carbs")
        b.compute(["nutrition"])
    elif task_id == 74:
        anchor = VISUAL["right list first item on fifth page"]
        if n(GREEK, anchor, "sugar_g") > 15:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "high_fiber"), "protein_g"), reason="sugar > 15")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "mild")), 2, "fallback mild lowest price")
        if b.total_metric("sugar_g") > 35:
            b.remove_non_set_by_metric("sugar_g", True, "sugar > 35")
        b.compute(["nutrition", "payment"])
    elif task_id == 75:
        anchor = VISUAL["right list second item on fifth page"]
        if dish(GREEK, anchor)["discount"] < 0.9:
            b.add(ties(GREEK, names(GREEK, lambda x: has_taste(GREEK, x, "umami")), greek_discounted_price), 2, "discount < 0.9; fresh-fragrant lowest discounted price")
        else:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "carbs_g"), reason="fallback high-calorie highest carbs")
        b.maybe_convert_exact_set("exact set match")
        b.compute(["nutrition", "tax"])
    elif task_id == 76:
        anchor = VISUAL["right list third item on fifth page"]
        if n(GREEK, anchor, "sodium_mg") > 800:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "low_fat")), reason="sodium > 800")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "calories_kcal"), 2, "fallback sweet highest calories")
        if b.total_metric("sodium_mg") > 1300:
            b.remove_non_set_by_metric("sodium_mg", True, "sodium > 1300")
        b.compute(["payment", "nutrition"])
    elif task_id == 77:
        anchor = VISUAL["dairy product in wooden bowl"]
        if dish(GREEK, anchor)["price"] * (1 + dish(GREEK, anchor)["tax_rate"]) > 88:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "calories_kcal"), 2, "tax-included price > 88")
        else:
            b.add(metric_max(GREEK, lambda x: has_allergen(GREEK, x, "seafood"), "protein_g"), reason="fallback seafood highest protein")
        while b.non_set_total_price(False) > 500:
            b.remove_non_set_by_price(True, "budget > 500")
        b.compute(["nutrition", "tax"])
    elif task_id == 78:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if n(GREEK, anchor, "carbs_g") > 20:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "low_calories"), "protein_g"), reason="carbs > 20")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sour")), 2, "fallback sour lowest price")
        if b.total_metric("carbs_g") > 20:
            b.remove_non_set_by_metric("carbs_g", True, "carbs still > 20")
        b.compute(["nutrition", "tax"])
    elif task_id == 79:
        anchor = VISUAL["bright blue plate with fried items and lemon"]
        if has_allergen(GREEK, anchor, "nuts"):
            b.add(metric_max(GREEK, lambda x: not dish(GREEK, x).get("allergens"), "protein_g"), 2, "nut allergen branch")
        else:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "sugar_g"), reason="fallback sweet lowest sugar")
        if b.total_metric("sugar_g") > 40:
            b.remove_non_set_by_metric("sugar_g", True, "sugar > 40")
        b.compute(["payment", "nutrition"])
    elif task_id == 80:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        if n(GREEK, anchor, "calories_kcal") > 250:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "umami"), "calories_kcal"), 2, "calories > 250; fresh/umami lowest calories")
        else:
            b.add(price_max(GREEK, lambda x: has_tag(GREEK, x, "high_fiber")), reason="fallback high-fiber highest price")
        if not any(has_taste(GREEK, item, "umami") for item in b.cart):
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "vegan")), reason="no fresh/umami flavor; add cheapest vegan")
        b.compute(["tax"])
    elif task_id == 81:
        anchor = VISUAL["grilled vegetable skewer on wooden cutting board"]
        if dish(GREEK, anchor)["discount"] < 1.0:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "fat_g"), reason="on sale; high-calorie highest fat")
        else:
            b.add(price_min(GREEK, lambda x: has_allergen(GREEK, x, "seafood")), 2, "fallback seafood lowest price")
        if any(has_allergen(GREEK, item, "nuts") for item in b.cart):
            b.clear("nut allergen in order")
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sour"), "calories_kcal"), 2, "replace with sour lowest calories")
        b.compute(["payment", "nutrition"])
    elif task_id == 82:
        anchor = VISUAL["dark blue casserole containing seafood / seafood paella"]
        if n(GREEK, anchor, "sugar_g") > 10:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "mild"), "fiber_g"), 2, "sugar > 10")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "sugar_g"), reason="fallback sweet highest sugar")
        if b.total_metric("sugar_g") > 40:
            for item in list(b.cart):
                if has_taste(GREEK, item, "sweet") and n(GREEK, item, "sugar_g") == max(n(GREEK, x, "sugar_g") for x in b.cart if has_taste(GREEK, x, "sweet")):
                    b.remove(item, None, "sugar > 40; remove sweetest non-set item")
        b.compute(["payment", "nutrition"])
    elif task_id == 83:
        anchor = VISUAL["right list first item on fifth page"]
        if n(GREEK, anchor, "calories_kcal") / n(GREEK, anchor, "protein_g") < 20:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_protein"), "carbs_g"), 2, "calorie/protein ratio < 20")
        else:
            b.add(price_max(GREEK, lambda x: has_taste(GREEK, x, "savory")), reason="fallback savory most expensive")
        if b.non_set_total_price(False) * 1.1 > 150:
            b.remove_non_set_by_price(True, "tax-inclusive non-set amount > 150")
        b.compute(["nutrition", "tax"])
    elif task_id == 84:
        anchor = VISUAL["right list second item on fifth page"]
        if n(GREEK, anchor, "sodium_mg") > 950:
            b.add(price_min(GREEK, lambda x: has_tag(GREEK, x, "vegan")), reason="sodium > 950")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "calories_kcal"), 2, "fallback sweet highest calories")
        if any(has_allergen(GREEK, item, "seafood") for item in b.cart):
            for item in list(b.cart):
                if has_allergen(GREEK, item, "seafood"):
                    b.remove(item, None, "remove seafood allergen")
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "savory"), "sodium_mg"), reason="replace with savory lowest sodium")
        b.compute(["payment", "nutrition"])
    elif task_id == 85:
        anchor = VISUAL["right list third item on fifth page"]
        if has_tag(GREEK, anchor, "high_omega_3"):
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "umami") and has_taste(GREEK, x, "savory"), "calories_kcal"), 2, "Omega-3 branch")
        else:
            b.add(price_max(GREEK, lambda x: has_tag(GREEK, x, "low_calories")), reason="fallback low-calorie highest price")
        b.maybe_convert_exact_set("discounted set if exact")
        b.compute(["tax", "nutrition"])
    elif task_id == 86:
        anchor = VISUAL["dairy product in wooden bowl"]
        if any(anchor in [i["dish_name"] for i in meal["included_dishes"]] for meal in SET_MEALS_BY_REST[GREEK].values()):
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sour")), reason="anchor belongs to a set; add cheapest sour")
        else:
            b.add(metric_max(GREEK, lambda x: n(GREEK, x, "carbs_g") >= 40, "protein_g"), 3, "fallback high-carb highest protein")
        if b.non_set_total_price(False) > 250:
            b.remove_non_set_by_price(True, "undiscounted total > 250")
        b.compute(["payment", "nutrition"])
    elif task_id == 87:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if has_allergen(GREEK, anchor, "dairy"):
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "calories_kcal"), 2, "dairy allergen branch")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "mild") and dish(GREEK, x)["price"] < 100, "sugar_g"), reason="fallback mild <100 highest sugar")
        if b.contains_allergen("dairy"):
            b.clear("updated order still contains dairy")
            b.add([name for name in ORDER_BY_REST[GREEK] if has_taste(GREEK, name, "sweet") and has_taste(GREEK, name, "savory")], reason="keep only sweet-and-savory dish")
        b.compute(["nutrition", "tax"])
    elif task_id == 88:
        anchor = VISUAL["dark grey plate with white sauce dish"]
        compare = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if dish(GREEK, anchor)["price"] < dish(GREEK, compare)["price"]:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_protein"), "sodium_mg"), reason="cheaper than top-right dish")
        else:
            b.add(price_max(GREEK, lambda x: has_taste(GREEK, x, "mild")), 2, "fallback mild highest price")
        if b.non_set_total_price(False) > 50:
            b.clear("mood change; total price > 50")
        b.compute(["payment", "nutrition"])
    elif task_id == 89:
        if True:
            candidates = discount_best(GREEK, lambda x: has_taste(GREEK, x, "savory") and has_taste(GREEK, x, "umami"))
            cheapest = min(dish(GREEK, x)["price"] for x in candidates)
            b.add([x for x in candidates if dish(GREEK, x)["price"] == cheapest], 1, "Seafood Lover's Set is cheaper than individual items")
        else:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "fat_g"), 2, "fallback high-calorie lowest fat")
        for item in list(b.cart):
            if has_allergen(GREEK, item, "nuts"):
                b.remove(item, None, "remove nut allergen")
        b.compute(["payment", "nutrition"])
    elif task_id == 90:
        anchor = VISUAL["red seafood in copper double-handled pot"]
        needed = -(-60 // int(n(GREEK, anchor, "protein_g")))
        if needed > 3:
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "low_fat"), "protein_g"), needed, "needs more than three servings")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "sour")), 2, "protein target does not require >3 servings")
        if any(has_taste(GREEK, item, "umami") for item in b.cart):
            for item in list(b.cart):
                if has_taste(GREEK, item, "umami"):
                    b.remove(item, None, "remove fresh/umami selected dish")
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "savory")), reason="replace with cheapest savory")
        b.compute(["nutrition", "tax"])
    elif task_id == 91:
        anchor = VISUAL["dark blue casserole containing seafood / seafood paella"]
        if n(GREEK, anchor, "protein_g") > 30:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "savory"), "carbs_g"), 2, "protein exceeds 30")
        else:
            b.add(price_max(GREEK, lambda x: has_tag(GREEK, x, "high_fiber")), reason="fallback high-fiber highest price")
        if b.total_metric("calories_kcal") < 400:
            b.add(metric_min(GREEK, lambda x: True, "sugar_g"), reason="calories below 400; lowest sugar")
        b.compute(["nutrition", "tax"])
    elif task_id == 92:
        b.clear("clear accidental previous items first")
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if dish(GREEK, anchor)["price"] * (1 + dish(GREEK, anchor)["tax_rate"]) < 88:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "sodium_mg"), reason="tax-included anchor below 88")
        else:
            b.add(metric_min(GREEK, lambda x: has_tag(GREEK, x, "vegan"), "calories_kcal"), 2, "fallback vegan lowest calorie")
        if b.non_set_total_price(False) < 350:
            b.add(price_min(GREEK, lambda x: n(GREEK, x, "carbs_g") >= 50), 8, "use remaining budget on lowest-price high-carb dish")
        b.compute(["payment", "nutrition"])
    elif task_id == 93:
        if True:
            b.add(discount_best(GREEK, lambda x: has_allergen(GREEK, x, "gluten")), reason="bundle is cheaper; gluten largest discount")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "mild")), 2, "fallback mild lowest price")
        b.maybe_convert_exact_set("match dishes to set meals if exact")
        b.compute(["payment", "nutrition"])
    elif task_id == 94:
        anchor = VISUAL["right list third item on fifth page"]
        if n(GREEK, anchor, "sugar_g") > 15:
            b.add(metric_min(GREEK, lambda x: has_taste(GREEK, x, "sweet"), "calories_kcal"), 2, "sugar exceeds 15")
        else:
            b.add(price_max(GREEK, lambda x: has_taste(GREEK, x, "sour")), reason="fallback sour highest price")
        sweet_items = [item for item in list(b.cart) if has_taste(GREEK, item, "sweet") and dish(GREEK, item)["price"] > 60]
        for item in sweet_items:
            b.remove(item, None, "remove sweet item above 60")
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "salty") and has_taste(GREEK, x, "umami")), reason="replace with salty umami lowest price")
        b.compute(["payment", "nutrition"])
    elif task_id == 95:
        anchor = VISUAL["dairy product in wooden bowl"]
        if has_tag(GREEK, anchor, "vegan"):
            b.add(metric_max(GREEK, lambda x: has_tag(GREEK, x, "high_calories"), "sodium_mg"), reason="vegan branch")
        else:
            b.add(price_min(GREEK, lambda x: has_taste(GREEK, x, "savory")), 2, "fallback savory lowest price")
        classic = {i["dish_name"] for i in SET_MEALS_BY_REST[GREEK]["greek classic set"]["included_dishes"]}
        if not any(item in classic for item in b.cart):
            b.add(price_min(GREEK, lambda x: has_allergen(GREEK, x, "seafood")), reason="no Classic Set component; add cheapest seafood-allergen dish")
        b.compute(["tax", "nutrition"])
    elif task_id == 96:
        anchor = VISUAL["dairy product in wooden bowl"]
        if has_taste(GREEK, anchor, "sweet"):
            b.add(price_min(GREEK, lambda x: n(GREEK, x, "sugar_g") > 20), 2, "sweet branch; lowest price with sugar > 20")
        else:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "mild"), "calories_kcal"), reason="fallback mild highest calories")
        if b.cart and max(dish(GREEK, item)["price"] for item in b.cart) > 150:
            b.remove_non_set_by_price(True, "most expensive original price > 150")
        b.compute(["nutrition", "tax"])
    elif task_id == 97:
        anchor = VISUAL["top right first expanded page / chicken and potatoes casserole"]
        if dish(GREEK, anchor)["price"] * 4 < 400:
            b.add(metric_max(GREEK, lambda x: has_taste(GREEK, x, "savory"), "carbs_g"), 4, "four anchor portions below 400")
        else:
            b.add(price_min(GREEK, lambda x: has_allergen(GREEK, x, "seafood")), 2, "fallback seafood-allergen lowest price")
        if b.non_set_total_price(False) > 0:
            b.clear("friends choose elsewhere; cancel cart")
        b.compute(["tax", "nutrition"])
    else:
        return None

    return b


def main() -> None:
    data = json.loads(SCENARIO.read_text())
    rows = []
    generated = 0
    total_calls = 0
    for task in data:
        task_id = int(task["task_id"])
        builder = build_task(task_id)
        if builder is None:
            task.pop("ground_truth", None)
            continue
        task["ground_truth"] = builder.calls
        generated += 1
        total_calls += len(builder.calls)
        rows.append(
            {
                "task": task_id,
                "user": builder.user_id,
                "calls": len(builder.calls),
                "notes": "; ".join(builder.notes),
                "final": ", ".join(
                    [f"{DISPLAY[builder.rest][item]} x{qty:g}" for item, qty in builder.cart.items()]
                    + [f"{DISPLAY_SET[builder.rest][item]} x{qty:g}" for item, qty in builder.sets.items()]
                )
                or "(empty)",
            }
        )

    SCENARIO.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    lines = [
        "# order2 GT v1 audit",
        "",
        "## Visual mapping used for implemented tasks",
    ]
    for label, value in VISUAL.items():
        d = dish(GREEK, value)
        lines.append(f"- {label}: `{d['name']}`; category={d['category']}; price={d['price']}; nutrition={d['nutrition']}; allergens={d.get('allergens', [])}; taste={d.get('taste', [])}; tags={d.get('nutritional_characteristics', [])}")
    lines += [
        "",
        f"Generated {generated} / {len(data)} tasks with {total_calls} GT calls. Tasks not generated by this script are left without `ground_truth`.",
        "",
        "| Task | User | Calls | Notes | Final order |",
        "|---:|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(f"| {row['task']} | {row['user']} | {row['calls']} | {row['notes']} | {row['final']} |")
    AUDIT.write_text("\n".join(lines) + "\n")
    print(f"Wrote {SCENARIO}")
    print(f"Wrote {AUDIT}")
    print(f"Generated {generated}/{len(data)} tasks, calls={total_calls}")


if __name__ == "__main__":
    main()
