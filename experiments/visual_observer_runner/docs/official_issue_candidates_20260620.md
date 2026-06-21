# Official issue candidates: retail/order data and enum wording

Date: 2026-06-20

This note records issue candidates found while auditing Track2 EgoBench
retail/order tasks. It separates likely official data/tool issues from prompt
normalization issues that can be handled locally.

## Issue 1: retail6 allergen and country field inconsistencies

### Summary

In `retail_init_data6`, allergen and country values appear inconsistent with
the task wording and tool enum semantics:

- The official retail tool enum includes both `nut` and `nuts`.
- The retail6 DB uses both forms for the same apparent allergen category.
- The instruction wording often says `nuts`, but using only
  `find_products_by_allergen("nuts")` misses products tagged `nut`.
- `Desobry Speculoos` has `country_of_origin = "danmark"`, while task
  instructions use `Denmark`. `find_products_by_country_of_origin("Denmark")`
  returns no result, but `find_products_by_country_of_origin("Danmark")`
  returns `desobry speculoos`.

### Minimal reproduction

```python
from tools.retail.retail_db import RetailDB
from tools.retail.retail_init import retail_init_data6

db = RetailDB()
db.init_from_json(retail_init_data6)

print(db.find_products_by_allergen("nut"))
print(db.find_products_by_allergen("nuts"))
print(db.find_products_by_country_of_origin("Denmark"))
print(db.find_products_by_country_of_origin("Danmark"))
```

Observed locally:

```text
nut  -> choco fit hazelnut, grisbi nocciola,
        grisbi chocolate hazelnut, nutella biscuits
nuts -> desobry speculoos

Denmark -> []
Danmark -> ["desobry speculoos"]
```

### Why this matters

Several retail6 instructions use natural language such as:

- "cookies containing the `nuts` allergen"
- "originating from Denmark, Japan, or Germany"

If the service agent follows the literal official field values, it can exclude
valid expected candidates. For example, retail6 task 26 expects
`Desobry Speculoos` for a Denmark/Japan/Germany + nuts branch, but the official
country lookup for `Denmark` returns empty because the DB field is `danmark`.

### Suggested official clarification or fix

Please confirm whether:

1. `nut` and `nuts` should be treated as the same allergen category.
2. `Desobry Speculoos.country_of_origin` should be changed from `danmark` to
   `denmark`.
3. GT should be regenerated after applying the canonicalized fields.

If both `nut` and `nuts` must remain accepted enum values, please document that
agents should query both for natural-language "nuts" inclusion/exclusion.

## Already submitted: retail10 initial cart has `switzerland switzerland swiss cheese`

### Summary

In the baseline `HEAD` version of `tools/retail/retail_init.py`,
`retail_init_data10.user_carts` contains two entries named:

```text
switzerland switzerland swiss cheese
```

The catalog product is:

```text
switzerland swiss cheese
```

Affected baseline entries:

- `user_123`, quantity `1`
- `user_456`, quantity `2`

### Current local status

This workspace currently appears to have already corrected the local working
tree to `switzerland swiss cheese`, but the baseline `HEAD` still shows the
two duplicated-name entries.

### Why this matters

The misspelled cart item does not match the catalog key. This can affect:

- `get_cart` metadata consistency,
- aggregate compute calls,
- GT product lists,
- hash/eval matching when one side uses the typo and the other uses the
  canonical product name.

### Suggested official fix

Update both initial cart entries:

```diff
- "product_name": "switzerland switzerland swiss cheese"
+ "product_name": "switzerland swiss cheese"
```

Then regenerate affected retail10 GT.

### Official issue status

This is already covered by official issue:

```text
#14 [Track2][Retail] Allergen fields are not queryable, and retail10 has a product-name typo
https://github.com/ego-link/egolink2026/issues/14
```

Do not file a duplicate issue for this item.

## Not currently proposed: order2 comparison restaurant names not present in DB

### Summary

The current `tools/order/order_init.py` contains only these restaurant names:

```text
Annie Italian Restaurant
Mediterranean Greek Restaurant
```

However, `scenarios/final/order2.json` instructions reference additional
restaurant names:

- `Butcher Restaurant`
- `Pau Hana Restaurant`
- `Butcher Shop Restaurant`

Examples:

- task 1: `Butcher Restaurant` and `Mediterranean Greek Restaurant`
- task 69: `Pau Hana Restaurant` and `Mediterranean Greek Restaurant`
- task 96: `Butcher Shop Restaurant` and `Mediterranean Greek Restaurant`

The order2 scenario has many restaurant-selection tasks where the user asks the
service agent to choose between a named restaurant and
`Mediterranean Greek Restaurant`. If the service agent uses the exact
instruction restaurant name as a DB namespace, the tool call can be unsupported.

### Task coverage observed locally

String scan over `scenarios/final/order2.json`:

```text
Butcher Restaurant: 14 tasks
Pau Hana Restaurant: 1 task
Butcher Shop Restaurant: 1 task
Annie Italian Restaurant: 30 tasks
Mediterranean Greek Restaurant: 97 tasks
```

`Greek Village Roast Chicken Leg` appears as the visual/GT dish value in 12
order2 tasks:

```text
1, 2, 14, 29, 36, 45, 49, 59, 78, 87, 92, 97
```

### Why this matters

The official DB namespace does not include several names used in the
instructions. However, after rechecking the task flow, these names are usually
comparison options in the user's restaurant-selection request. They do not
necessarily need to be called as tool `restaurant_name` values if the selected
restaurant is the DB-supported `Mediterranean Greek Restaurant`.

The service agent should:

- infer or ask for the selected complete restaurant name from the user dialogue,
- call order tools only with a DB-supported selected restaurant name,
- avoid treating non-selected comparison names as tool namespaces.

### Current conclusion

Do not submit this broad restaurant-name coverage item as an official issue
unless a concrete task requires a tool call against `Butcher Restaurant`,
`Pau Hana Restaurant`, or `Butcher Shop Restaurant`.

The separate official data issue where `Greek Village Roast Chicken Leg`
appears as a `restaurant_name` in `user_orders` is already submitted:

```text
#15 [Track2][Order2] user_orders use dish name as restaurant_name: Greek Village Roast Chicken Leg
https://github.com/ego-link/egolink2026/issues/15
```

## Issue 2: order2 task 93 references missing `Enthusiast Set Meal`

### Summary

`scenarios/final/order2.json` task 93 asks the service agent to determine
whether the bundle price of the `"Enthusiast Set Meal"` containing the tapped
dish is lower than ordering each item individually.

The tapped dish is `Octopus Spaghetti`. The order DB contains
`Pasta Lovers Set`, which includes `octopus spaghetti`, but it does not contain
`Enthusiast Set Meal`.

Local checks:

```text
tools/order/order_init.py:
enthusiast set meal -> 0 occurrences
pasta lovers set    -> 3 occurrences
```

Runtime tool checks:

```text
get_set_meal_details(
  restaurant_name="Mediterranean Greek Restaurant",
  set_meal_name="Enthusiast Set Meal"
)
-> {"status": "error", "message": "Set meal 'Enthusiast Set Meal' not found."}

get_set_meal_details(
  restaurant_name="Mediterranean Greek Restaurant",
  set_meal_name="enthusiast set meal"
)
-> {"status": "error", "message": "Set meal 'enthusiast set meal' not found."}
```

### Why this matters

The instruction names a set meal that cannot be verified through the official
DB tools. The service agent can find the actual associated set meal
(`Pasta Lovers Set`) for `Octopus Spaghetti`, but the instruction asks for a
different exact set meal name. This makes the intended branch ambiguous:

- follow the exact instruction and fail because `Enthusiast Set Meal` is not in
  DB;
- substitute `Pasta Lovers Set`, which is supported by DB but not the user's
  exact requested set-meal name.

### Suggested official clarification or fix

Please confirm whether task 93 should say `Pasta Lovers Set` instead of
`Enthusiast Set Meal`, or whether `Enthusiast Set Meal` should be added to
`order_init.py`.

If the intended behavior is to use the associated set meal returned by the DB
instead of the literal set-meal name in the instruction, please document this
fallback rule.

## Issue 3: singular/plural nutritional tag exact matching ambiguity

Several instructions use natural-language wording while official tool enums use
snake_case pluralized tags:

- `high calorie`, `high-calorie`, `high calories` -> `high_calories`
- `low calorie`, `low-calorie`, `low calories` -> `low_calories`
- `gluten-free`, `gluten free` -> `gluten_free`
- `high oil` -> `high_fat` in retail nutritional-characteristic context

Local tool behavior is exact string matching over DB tag values, not semantic
alias matching.

Observed examples:

```text
order2 / Mediterranean Greek Restaurant:
high_calorie  -> []
high_calories -> santarini seafood rice, feta & tomato spaghetti, ...
low_calorie   -> []
low_calories  -> greek salad, tzatziki, dolmades, ...
gluten_free   -> []

restaurant5:
high_calorie  -> r, cheesecake
high_calories -> []
low_calorie   -> f
low_calories  -> espresso, americano, cold brew, white tea, ...
gluten_free   -> []
```

### Why this matters

`high_calorie` and `high_calories` are not interchangeable in tool calls.
The same applies to `low_calorie` and `low_calories`. In restaurant5, both
singular and plural forms exist in the DB and return different dish sets, so a
prompt-level alias rule would be unsafe unless the official intended enum is
explicitly documented per scenario.

This is similar to the retail `nut`/`nuts` problem: literal exact matching can
exclude candidates that the natural-language instruction may intend to include.

### Suggested official clarification or fix

Please clarify whether singular/plural nutritional tags are intended to be
distinct categories or aliases:

- `high_calorie` vs `high_calories`
- `low_calorie` vs `low_calories`

If they are aliases, the DB/tool should normalize them. If they are distinct,
the benchmark instructions should use exact enum names consistently.

## Local prompt normalization notes

The service/correction prompt can safely normalize only cases where the official
scenario semantics are clear. Current local prompt handling:

- retail `high oil` / `High Oil` -> `high_fat`
- order natural-language `high calorie(s)` -> `high_calories`
- order natural-language `low calorie(s)` -> `low_calories`
- order natural-language `gluten-free` / `gluten free` -> `gluten_free`

Restaurant singular/plural calorie tags should not be blindly merged because
restaurant5 contains both forms with different results.

Suggested local alias table:

```text
high calorie / high-calorie / high calories -> high_calories
low calorie / low-calorie / low calories    -> low_calories
gluten-free / gluten free                    -> gluten_free
high oil / High Oil, retail only             -> high_fat
```

If official evaluation expects exact enum names only, it may be useful to
document this alias table in the official prompt or tool description.
