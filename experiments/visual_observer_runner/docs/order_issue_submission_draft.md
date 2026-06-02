# Order Scenario Issues Submission Draft

Date: 2026-06-02

Repository scope: EgoBench Track 2, `order1` scenario.

This draft consolidates locally confirmed issues found against the official
GitHub repository `https://github.com/ego-link/egolink2026.git`, main revision
`27e1a23a11d82f1d7fb13a202f6d3591d2b0b943`, by comparing
`code/track2/EgoBench/scenarios/final/order1.json`,
`code/track2/EgoBench/tools/order/order_init.py`,
`code/track2/EgoBench/tools/order/order_db.py`, and
`code/track2/EgoBench/tools/order/order_tools.json`.

## Issue 1: `order1.json` ground truth contains DB-mismatched values and invalid parameter keys

### Summary

Some ground-truth tool-call parameters in `scenarios/final/order1.json` do not
match the order DB canonical values or the `OrderDB` method signatures. These
problems can make correct service-agent calls fail tool-based evaluation, or
make official ground-truth execution silently ignore intended items.

This issue merges the previously identified `Salmone affumicato` and
`Cold Cuts & Cheese Platte` naming problems into the broader ground-truth
parameter mismatch issue.

### Affected files

- `scenarios/final/order1.json`
- `tools/order/order_init.py`
- `tools/order/order_db.py`
- `analysis_scripts/evaluate_interaction.py`

### Confirmed findings

String comparisons below were normalized with `strip().lower()`, so ordinary
capitalization differences were not counted.

```text
order1 tasks audited: 100

dish_name values not found in DB: 13 occurrences
set_meal_name values not found in DB: 1 occurrence
restaurant_name values not found in DB: 2 occurrences
user_id wrong/malformed: 2 occurrences
product_name used inside order aggregate dishes[]: 87 occurrences across 18 tasks
required restaurant_name missing from add_dish_to_order: 4 calls
category values not found in DB after strip/lower normalization: 0 occurrences
category values with trailing whitespace: 3 occurrences
```

### Concrete examples

1. `Cold Cuts & Cheese Platte` appears as a set meal name in task 1, but the DB
   canonical set meal is `Cold Cuts & Cheese Platter`.

```text
Affected tasks:
1
```

2. `Salmone affumicato` appears in ground truth, but the DB canonical dish is
   `Salmon affumicato`.

```text
Affected tasks:
1, 11, 28, 40, 44, 46, 58, 71, 80, 89, 99
```

3. `Seafood Delight Set'` has an extra trailing quote. The DB canonical set meal
   is `Seafood Delight Set`.

```text
Affected tasks:
86, 93
```

4. Task 10 has `restaurant_name` and `user_id` swapped in one
   `remove_dish_from_order` call.

```text
restaurant_name = "customer_010"
user_id = "Annie Italian Restaurant"
```

5. Task 26 has an invalid restaurant name.

```text
restaurant_name = "Annie Italian Restaurant_items"
```

6. Task 3 has a trailing newline in `user_id`.

```text
user_id = "customer_005\n"
```

7. Three category fields contain trailing newlines. They normalize to existing
   DB categories, but the raw strings are malformed.

```text
task 3: "Selected Steaks\n"
task 4: "Cheese & Olives\n"
task 5: "Sandwiches & Panini\n"
```

8. Several order aggregate calls use `product_name` inside `dishes[]`, but the
   order DB aggregate tools read `dish_name`.

```text
Affected tasks:
6, 7, 8, 10, 16, 17, 18, 19, 20, 31, 54, 55, 56, 81, 82, 83, 84, 85
```

For example, `OrderDB.compute_total_payment`, `compute_total_tax`, and
`compute_total_nutrition` read item names with:

```python
dish_name = item.get("dish_name", " ").lower()
```

So entries keyed as `product_name` are ignored during actual tool execution.

9. Four `add_dish_to_order` ground-truth calls omit the required
   `restaurant_name` parameter.

```text
Affected tasks:
26, 27, 28, 30
```

`OrderDB.add_dish_to_order` requires:

```python
def add_dish_to_order(self, restaurant_name, user_id, dish_name, quantity)
```

### Impact

- A correct service-agent call using canonical DB values can fail to match the
  ground truth when the ground truth contains misspellings, malformed values, or
  wrong nested keys.
- Official ground-truth execution can silently ignore aggregate items keyed as
  `product_name`, leading to incorrect payment, tax, or nutrition values.
- Result-based evaluation may hide these issues because aggregate calculation
  tools are non-mutating.

### Suggested fix

- Replace order aggregate `product_name` keys with `dish_name`.
- Correct `Cold Cuts & Cheese Platte` to `Cold Cuts & Cheese Platter`.
- Correct `Salmone affumicato` to `Salmon affumicato`.
- Correct `Seafood Delight Set'` to `Seafood Delight Set`.
- Fix the task 10 `restaurant_name` / `user_id` swap.
- Fix `Annie Italian Restaurant_items` in task 26.
- Strip trailing whitespace from all IDs and category fields.
- Add missing `restaurant_name` to affected `add_dish_to_order` calls, or
  document an explicit evaluation policy for missing top-level parameters.

## Issue 2: Order aggregate tools return zero because restaurant keys are looked up inconsistently

### Summary

In the official `tools/order/order_db.py`, the aggregate tools
`compute_total_payment`, `compute_total_tax`, and `compute_total_nutrition`
lowercase `restaurant_name` before looking up `self.restaurants`.

However, `init_from_json()` stores restaurant keys using the original official
restaurant names such as `Annie Italian Restaurant`, not lowercase keys. As a
result, passing the documented official restaurant name makes aggregate tools
miss the store and return all-zero results.

There is also a second payment-specific issue: all set meals in
`tools/order/order_init.py` omit `set_meal_price`, so even after fixing the
restaurant lookup, top-level set meals would still contribute `0.0` to
`compute_total_payment` unless prices are populated or set meals are expanded.

### Affected files

- `tools/order/order_init.py`
- `tools/order/order_db.py`
- `scenarios/final/order1.json`

### Evidence

Official `OrderDB` stores restaurant keys with original capitalization:

```text
self.restaurants keys:
Annie Italian Restaurant
Mediterranean Greek Restaurant
Greek Village Roast Chicken Leg
```

But aggregate tools use:

```python
restaurant_key = (restaurant_name or "").lower()
store = self.restaurants.get(restaurant_key)
```

Runtime check against the official files:

```text
compute_total_payment("Annie Italian Restaurant", "customer_test", [{"dish_name": "Lasagne", "quantity": 1}])
=> {"total_payment": 0.0}

compute_total_tax("Annie Italian Restaurant", "customer_test", [{"dish_name": "Lasagne", "quantity": 1}])
=> {"total_tax": 0.0}

compute_total_nutrition("Annie Italian Restaurant", "customer_test", [{"dish_name": "Lasagne", "quantity": 1}])
=> all nutrition fields 0.0
```

All 10 set meals are missing `set_meal_price`:

```text
set_meals_total = 10
with_set_meal_price = 0
missing_set_meal_price = 10
```

Payment-specific set meal check after official initialization:

```text
Italian Classic Set              direct_payment=0.0
Steak Lovers Set                 direct_payment=0.0
Seafood Delight Set              direct_payment=0.0
Cold Cuts & Cheese Platter       direct_payment=0.0
Annie's Special Set              direct_payment=0.0
Seafood Lover's Set              direct_payment=0.0
Pasta Lovers Set                 direct_payment=0.0
Greek Classic Set                direct_payment=0.0
Dessert Pairing Set              direct_payment=0.0
Mediterranean Feast Set          direct_payment=0.0
```

### Impact

- Any condition based on payment, tax, or nutrition can take the wrong branch
  because aggregate tools return zero for valid official restaurant names.
- Final payment, tax, and nutrition answers can be numerically wrong.
- Result-based evaluation may hide this because aggregate calls do not mutate
  final order state.
- Even if the restaurant lookup is fixed, `compute_total_payment` still needs a
  clear set-meal pricing policy.

### Suggested fix

- Use the same restaurant key policy across initialization and aggregate tools.
  For example, either store restaurants with lowercase keys everywhere or use a
  case-insensitive lookup helper in aggregate tools.
- Confirm intended set-meal payment semantics.
- If set meals have fixed prices, populate `set_meal_price` for all set meals.
- If set meals should be priced from included dishes, update
  `compute_total_payment` and the tool description to expand set meals when
  `set_meal_price` is missing or zero.

## Issue 3: Order category enums include a non-canonical alias and restaurant-specific near-duplicate categories

### Summary

The category enums in the official `tools/order/order_tools.json` cover the
real catalog categories, but they also include at least one non-canonical alias:
`Steaks`. The order DB category lookup uses strict lowercase equality, so
querying `Steaks` returns no Annie dishes even though the real Annie category is
`Selected Steaks`.

The schema also contains restaurant-specific near-duplicate categories such as
`Pasta` and `Italian Pasta`. Both are real categories, but they apply to
different restaurants. This is not a direct schema/DB mismatch, but it can make
restaurant recommendation and category selection ambiguous when user wording or
visual text says only "pasta".

### Affected files

- `tools/order/order_tools.json`
- `tools/order/order_init.py`
- `tools/order/order_db.py`

### Evidence

Real catalog categories in the official data:

```text
Annie Italian Restaurant:
  Annie's top dishes
  Antipasti & Snacks
  Cheese & Olives
  Cold Cuts
  Handmade Bread
  Italian Pasta
  Pizza
  Salads
  Sandwiches & Panini
  Selected Steaks

Mediterranean Greek Restaurant:
  Appetizers
  Desserts
  Main Courses
  Pasta
  Seafood
  Sides
  Soups
```

Official `find_dishes_by_category` enum contains:

```text
Pizza, Pasta, Salads, Sandwiches & Panini, Antipasti & Snacks,
Cheese & Olives, Cold Cuts, Steaks, Handmade Bread, Annie's top dishes,
Appetizers, Desserts, Italian Pasta, Main Courses, Seafood, Selected Steaks,
Sides, Soups
```

Non-canonical enum value:

```text
Steaks
```

Runtime examples:

```text
Annie Italian Restaurant | Steaks => []
Annie Italian Restaurant | Selected Steaks => 3 dishes
Annie Italian Restaurant | Pasta => []
Annie Italian Restaurant | Italian Pasta => 10 dishes
Mediterranean Greek Restaurant | Pasta => 3 dishes
```

### Impact

- Agents can be guided by the schema enum into valid-looking but empty category
  queries such as `Steaks`.
- Restaurant recommendation and branch selection can be biased by false empty
  results when a semantically close category is selected for the wrong
  restaurant.
- The issue is especially harmful for `Steaks` vs `Selected Steaks`, and for
  generic user wording such as "pasta" when one restaurant uses `Pasta` and
  another uses `Italian Pasta`.

### Suggested fix

- Remove `Steaks` from the enum or map it explicitly to `Selected Steaks`.
- If semantically generic categories are intended, document restaurant-specific
  category usage or add alias handling in `find_dishes_by_category`.
