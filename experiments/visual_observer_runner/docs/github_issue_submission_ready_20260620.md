# GitHub Issue Draft Ready To Submit

Date: 2026-06-20

## Title

`[Track2] minor DB/instruction field consistency issues in retail6, restaurant5, and order2`

## Body

Hi EgoLink organizers,

While auditing several Track2 tasks, we found a few small DB/instruction field
consistency issues. They are minor individually, so I am grouping them into one
issue for easier tracking.

## 1. retail6 country spelling: `danmark` vs `Denmark`

### Problem

Some retail6 instructions use the standard English country name `Denmark`, for
example branches that ask for products originating from `Denmark, Japan, or
Germany`.

However, the retail6 DB stores `Desobry Speculoos` as:

```text
country_of_origin = "danmark"
```

Minimal reproduction:

```python
from tools.retail.retail_db import RetailDB
from tools.retail.retail_init import retail_init_data6

db = RetailDB()
db.init_from_json(retail_init_data6)

print(db.find_products_by_country_of_origin("Denmark"))
print(db.find_products_by_country_of_origin("Danmark"))
```

Observed:

```text
Denmark -> []
Danmark -> ["desobry speculoos"]
```

### Impact

An agent following the instruction literally may query `Denmark` and incorrectly
get no candidates. This can affect branch decisions, candidate ranking, and GT
matching.

### Suggested clarification/fix

Please confirm whether `Desobry Speculoos.country_of_origin` should be changed:

```diff
- "country_of_origin": "danmark"
+ "country_of_origin": "denmark"
```

If `danmark` is intentional, please document that agents should normalize
`Denmark` to `Danmark` for retail country lookup.

## 2. Singular/plural field ambiguity where both variants return non-empty results: `nut`/`nuts`, `low_calorie`/`low_calories`

### Problem A: retail6 `nut` vs `nuts`

In retail6, both `nut` and `nuts` appear as allergen values and return different
products.

Minimal reproduction:

```python
from tools.retail.retail_db import RetailDB
from tools.retail.retail_init import retail_init_data6

db = RetailDB()
db.init_from_json(retail_init_data6)

print(db.find_products_by_allergen("nut"))
print(db.find_products_by_allergen("nuts"))
```

Observed:

```text
nut  -> choco fit hazelnut, grisbi nocciola,
        grisbi chocolate hazelnut, nutella biscuits
nuts -> desobry speculoos
```

If a task says products containing `nuts`, querying only `nuts` excludes products
tagged `nut`, although these appear to refer to the same natural-language
allergen category.

### Problem B: restaurant5 `low_calorie` vs `low_calories`

In restaurant5, both `low_calorie` and `low_calories` return non-empty but
different candidate sets.

Minimal reproduction:

```python
from tools.restaurant.restaurant_db import RestaurantDB
from tools.restaurant.restaurant_init import restaurant_init_data5

db = RestaurantDB()
db.init_from_json(restaurant_init_data5)

print(db.find_dishes_by_nutritional_tag("low_calorie"))
print(db.find_dishes_by_nutritional_tag("low_calories"))
```

Observed:

```text
low_calorie  -> ["f"]
low_calories -> ["espresso", "americano", "cold brew", "white tea",
                 "green tea", "black tea", "oolong tea", "jasmine tea",
                 "earl grey", "matcha"]
```

We also checked similar singular/plural pairs where one side is empty and the
other side has results, for example `high_calorie/high_calories` in restaurant5
and order/retail calorie tags. Those are not included here because only one
variant returns a non-empty set.

### Impact

The tools exact-match these strings. In the cases above, both singular and
plural variants return non-empty but different candidate sets. That makes it
unclear whether these should be distinct official categories or aliases.

### Suggested clarification/fix

Please clarify whether the following pairs are intended to be distinct or
aliases:

```text
nut vs nuts
low_calorie vs low_calories
```

If they are aliases, it would help to normalize them in the DB/tool layer or
document the expected alias mapping. If they are distinct, it would help if task
instructions consistently used the exact official enum values.

## 3. order2 task 93 references missing `Enthusiast Set Meal`

### Problem

`scenarios/final/order2.json` task 93 asks the service agent to compare the
bundle price of the `"Enthusiast Set Meal"` containing the tapped dish.

The tapped dish is:

```text
Octopus Spaghetti
```

However, `tools/order/order_init.py` does not contain `Enthusiast Set Meal`.
The DB set meal associated with `Octopus Spaghetti` appears to be
`Pasta Lovers Set`.

Local string check:

```text
tools/order/order_init.py:
enthusiast set meal -> 0 occurrences
pasta lovers set    -> 3 occurrences
```

Runtime tool behavior:

```python
db.get_set_meal_details(
    restaurant_name="Mediterranean Greek Restaurant",
    set_meal_name="Enthusiast Set Meal"
)
```

Observed:

```text
{"status": "error", "message": "Set meal 'Enthusiast Set Meal' not found."}
```

The lowercase variant also fails:

```text
get_set_meal_details(..., set_meal_name="enthusiast set meal")
-> {"status": "error", "message": "Set meal 'enthusiast set meal' not found."}
```

### Impact

The agent cannot verify the exact requested set meal through official tools.
This creates ambiguity:

- following the exact instruction fails because `Enthusiast Set Meal` is not in
  DB;
- substituting `Pasta Lovers Set` is tool-supported, but no longer follows the
  exact set-meal name in the instruction.

This can cause branch ambiguity, unnecessary correction rejection, tool-limit
failures, and GT mismatch.

### Suggested clarification/fix

Please confirm whether task 93 should say `Pasta Lovers Set`, whether
`Enthusiast Set Meal` should be added to `order_init.py`, or whether agents are
expected to ignore the literal set-meal name and use the DB-associated set meal
for the tapped dish.

Thanks!
