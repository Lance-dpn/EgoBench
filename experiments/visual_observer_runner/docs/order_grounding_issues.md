# Order Grounding Issues Log

This document records suspected grounding-related inconsistencies found while
running order scenario experiments. The goal is to keep author-provided data
issues separate from model, prompt, and observer failures.

## Recording Rules

- Do not silently patch author-provided scenario, catalog, or ground-truth data.
- Record the affected scenario/task, file paths, observed value, expected
  canonical value, and evaluation impact.
- Treat this file as an experiment note first. Any data normalization or alias
  handling should be implemented separately and explicitly.

## Issue Template

```text
ID:
Date:
Scenario / task:
Issue type:
Affected files:
Observed:
Expected / canonical value:
Evidence:
Impact:
Suggested handling:
Status:
```

## Issues

### ORDER-GROUND-001: `Salmone affumicato` is not the exact catalog dish key

ID: ORDER-GROUND-001

Date: 2026-06-01

Scenario / task: `order1`, task 1

Issue type: dish key mismatch between scenario ground truth / runtime order
state and catalog.

Affected files:

- `code/track2/EgoBench/scenarios/final/order1.json`
- `code/track2/EgoBench/tools/order/order_init.py`
- `code/track2/EgoBench/tools/order/order_db.py`
- `code/track2/EgoBench/results/qwen36-offline-url-observer-order1-smoke/order1_easy.json`

Observed:

- `order1.json` task 1 ground truth passes `Salmone affumicato` to
  `compute_total_tax`.
- The canonical order catalog key in `tools/order/order_init.py` is
  `Salmon affumicato`.
- The author-provided `customer_009` initial order item was originally
  `salmone affumicato`, which is not an exact dish key in the order catalog.
- Local note: this repository copy was manually corrected to
  `salmon affumicato` for follow-up experiments, so the current
  `tools/order/order_init.py` content may already show the fixed value.

Expected / canonical value:

- Use `Salmon affumicato` / `salmon affumicato`, matching the order catalog key.

Evidence:

- `scenarios/final/order1.json` task 1:
  `{"dish_name": "Salmone affumicato", "quantity": 1}`
- `tools/order/order_init.py` catalog:
  `"name": "Salmon affumicato"`
- Original author-provided `tools/order/order_init.py` customer order for
  `customer_009` used `salmone affumicato`; this local copy may now show
  `salmon affumicato` after manual experiment correction.
- Recent run log:
  `results/qwen36-offline-url-observer-order1-smoke/order1_easy.json`
  recorded `{"dish_name": "salmone affumicato", "quantity": 1}` in the order
  summary.

Impact:

- Aggregate order tools rely on catalog lookup by dish name. A non-canonical
  dish key can be skipped or miscomputed when calculating payment, tax, or
  nutrition.
- In the recent `qwen36-offline-url-observer-order1-smoke` run, this mismatch
  contributed to an incorrect total-payment judgment, so the service agent did
  not perform the expected removal step.
- This should be counted as an author data / grounding-file issue, not as a
  pure observer recognition failure.

Suggested handling:

- Prefer correcting the author-provided scenario/ground-truth data to the
  canonical catalog key.
- If source files must remain unchanged, add an explicit experiment-side alias
  map and record that normalization in evaluation notes.

Status: open.

### ORDER-GROUND-002: `Cold Cuts & Cheese Platte` misses the canonical final `r`

ID: ORDER-GROUND-002

Date: 2026-06-01

Scenario / task: `order1`, task 1

Issue type: set-meal name mismatch in ground truth.

Affected files:

- `code/track2/EgoBench/scenarios/final/order1.json`
- `code/track2/EgoBench/tools/order/order_init.py`
- `code/track2/EgoBench/results/qwen36-offline-url-observer-order1-smoke/order1_easy.json`

Observed:

- `order1.json` task 1 ground truth calls `remove_set_meal_from_order` with
  `Cold Cuts & Cheese Platte`.
- The canonical set-meal name in the order data is
  `Cold Cuts & Cheese Platter`.
- The recent run order summary contained the lowercase canonical value
  `cold cuts & cheese platter`.

Expected / canonical value:

- `Cold Cuts & Cheese Platter`

Evidence:

- `scenarios/final/order1.json` task 1:
  `"set_meal_name": "Cold Cuts & Cheese Platte"`
- `tools/order/order_init.py` set meal:
  `"name": "Cold Cuts & Cheese Platter"`
- `tools/order/order_init.py` customer order:
  `"dish_name": "cold cuts & cheese platter"`

Impact:

- Tool-call evaluation expects a removal call using the misspelled ground-truth
  parameter, while exact database execution may treat that parameter as not
  matching the canonical set meal.
- Result-based evaluation can become misleading: if the ground-truth removal is
  effectively a no-op because of the typo, a model that fails to remove the set
  meal may still match the final database state.

Suggested handling:

- Correct the ground-truth parameter to `Cold Cuts & Cheese Platter`.
- If preserving author files, add a documented alias normalization rule for
  this set-meal name before evaluation.

Status: open.

### ORDER-GROUND-003: `compute_total_payment` returns `0.0` for every top-level set meal

ID: ORDER-GROUND-003

Date: 2026-06-02

Official re-check note:

- Re-checked against `https://github.com/ego-link/egolink2026.git` main
  revision `27e1a23a11d82f1d7fb13a202f6d3591d2b0b943`.
- The official issue is broader than this local-fork title: official
  `compute_total_payment`, `compute_total_tax`, and `compute_total_nutrition`
  lowercase `restaurant_name` before `self.restaurants.get(...)`, while
  initialization stores restaurant keys with original capitalization. Passing
  official restaurant names such as `Annie Italian Restaurant` therefore makes
  all three aggregate tools return zero.
- The missing `set_meal_price` problem still exists as a secondary
  payment-specific issue after the restaurant-key lookup is fixed.

Scenario / task: observed in `order1`, tasks 1 and 4; likely affects all
order tasks that pass set meals directly to `compute_total_payment`.

Issue type: tool data / grounding semantic mismatch.

Affected files:

- `code/track2/EgoBench/tools/order/order_init.py`
- `code/track2/EgoBench/tools/order/order_db.py`
- `code/track2/EgoBench/results/qwen36-offline-url-observer-order1-smoke/order1_easy.json`

Observed:

- All 10 set meals in `tools/order/order_init.py` omit `set_meal_price`.
- `OrderDB.init_from_json()` defaults a missing set-meal price to `0.0`.
- `OrderDB.compute_total_payment()` recognizes top-level set meal names, but
  calculates payment as `set_meal_price * set_meal_discount * quantity`.
- Therefore every top-level set meal passed directly to
  `compute_total_payment` contributes `0.0`, even though the included dishes
  have normal prices and discounts.
- In `order1` task 4, the official ground truth calls `compute_total_payment`
  with `Seafood Delight Set` as a top-level item. The official tool returns
  `0.0` for that set meal, while expanding its included dishes returns `201.2`.

Expected / canonical behavior:

- Either set-meal prices should be populated in the initialization data, or
  payment calculation should consistently derive set-meal totals from included
  dishes when the set-meal price is missing or `0.0`.
- Ground-truth calls should be consistent with the chosen behavior. If the tool
  is intended to price top-level set meals, the data needs `set_meal_price`. If
  set meals are intended to be priced by their included dishes, ground truth and
  tool descriptions should reflect that expansion policy.

Evidence:

- `tools/order/order_db.py`: `set_meal_price=set_meal_info.get("set_meal_price", 0.0)`
- `tools/order/order_db.py`: `compute_total_payment()` uses
  `set_meal.set_meal_price * set_meal.set_meal_discount * quantity`.
- Static check on `order_init_data`: `set_meals_total=10`,
  `with_set_meal_price=0`, `missing_set_meal_price=10`.
- Runtime check with `OrderDB.init_from_json(order_init_data)`:

```text
Italian Classic Set              direct_payment=0.0 expanded_payment=109.9
Steak Lovers Set                 direct_payment=0.0 expanded_payment=227.8
Seafood Delight Set              direct_payment=0.0 expanded_payment=201.2
Cold Cuts & Cheese Platter       direct_payment=0.0 expanded_payment=283.6
Annie's Special Set              direct_payment=0.0 expanded_payment=106.4
Seafood Lover's Set              direct_payment=0.0 expanded_payment=497.4
Pasta Lovers Set                 direct_payment=0.0 expanded_payment=212.8
Greek Classic Set                direct_payment=0.0 expanded_payment=201.6
Dessert Pairing Set              direct_payment=0.0 expanded_payment=92.8
Mediterranean Feast Set          direct_payment=0.0 expanded_payment=315.8
```

Impact:

- Conditional branches based on total payment can be wrong even if the visual
  grounding and dish addition are correct.
- Final payable answers can be semantically wrong when the final order contains
  a top-level set meal.
- Tool-call evaluation can favor a ground-truth call that is trace-compatible
  but numerically inconsistent with the official tool's current behavior.
- Result-based evaluation may hide this because payment calls do not mutate the
  final database state.

Suggested handling:

- Ask the benchmark organizers to confirm the intended set-meal payment
  semantics.
- If set meals have fixed prices, add `set_meal_price` values to all official
  set meal records.
- If set meals should be derived from included dishes, update
  `compute_total_payment` and the tool description accordingly.
- For local agent behavior, keep the final top-level set-meal
  `compute_total_payment` call for trace compatibility, then use an expanded
  secondary calculation when a user-facing numeric answer needs the real value.

Status: confirmed locally; pending organizer clarification.

### ORDER-GROUND-005: Order ground truth contains invalid keys, missing required fields, and DB-mismatched values

ID: ORDER-GROUND-005

Date: 2026-06-02

Scenario / task: `order1`, full 100-task ground-truth audit.

Issue type: ground-truth tool-call parameter mismatch.

Affected files:

- `code/track2/EgoBench/scenarios/final/order1.json`
- `code/track2/EgoBench/tools/order/order_init.py`
- `code/track2/EgoBench/tools/order/order_db.py`
- `code/track2/EgoBench/analysis_scripts/evaluate_interaction.py`

Observed:

- A full audit of `scenarios/final/order1.json` ground-truth calls against the
  initialized order DB found multiple key fields that are not executable or do
  not match DB canonical values.
- The audit normalized string values with `strip().lower()` before comparison,
  so ordinary capitalization differences were not counted as problems.
- The affected fields are important for tool execution and tool-based
  evaluation: `restaurant_name`, `user_id`, `dish_name`, and the item key inside
  aggregate `dishes[]` lists.

Summary:

```text
order1 tasks audited: 100

dish_name values not found in DB: 12 occurrences
restaurant_name values not found in DB: 2 occurrences
user_id wrong/malformed: 2 occurrences
product_name used inside order aggregate dishes[]: 87 occurrences across 18 tasks
required restaurant_name missing from add_dish_to_order: 4 calls
set_meal_name values not found in DB: 0 occurrences
category values not found in DB after strip/lower normalization: 0 occurrences
```

Detailed findings:

1. `Salmone affumicato` is still present in 10 ground-truth `dish_name`
   positions even though the catalog canonical value is `Salmon affumicato`.

```text
tasks: 11, 28, 40, 44, 46, 58, 71, 80, 89, 99
```

2. `Seafood Delight Set'` has an extra trailing single quote in 2 ground-truth
   `dish_name` positions. The DB set-meal name is `Seafood Delight Set`.

```text
tasks: 86, 93
```

3. Task 10 has `restaurant_name` and `user_id` swapped in one
   `remove_dish_from_order` ground-truth call.

```text
task 10:
  restaurant_name = "customer_010"
  user_id = "Annie Italian Restaurant"
```

4. Task 26 has a polluted restaurant name in a `compute_total_nutrition`
   ground-truth call.

```text
task 26:
  restaurant_name = "Annie Italian Restaurant_items"
```

5. Task 3 has a trailing newline in one `user_id`.

```text
task 3:
  user_id = "customer_005\n"
```

6. Order aggregate tools use the wrong item key `product_name` in 87
   `dishes[]` entries across 18 tasks. Order DB calculation tools read
   `dish_name`, not `product_name`, so these entries are ignored by official
   tool execution unless normalized elsewhere.

```text
affected tasks:
6, 7, 8, 10, 16, 17, 18, 19, 20, 31, 54, 55, 56, 81, 82, 83, 84, 85
```

7. Four `add_dish_to_order` ground-truth calls omit the required
   `restaurant_name` parameter.

```text
affected tasks:
26, 27, 28, 30
```

Evidence:

- `tools/order/order_db.py` requires `restaurant_name` for order mutation and
  aggregate methods, for example:

```python
def add_dish_to_order(self, restaurant_name: str, user_id: str, dish_name: str, quantity: float)
def compute_total_payment(self, restaurant_name: str, user_id: str, dishes: List[Dict[str, Any]])
def compute_total_tax(self, restaurant_name: str, user_id: str, dishes: List[Dict[str, Any]])
def compute_total_nutrition(self, restaurant_name: str, user_id: str, dishes: List[Dict[str, Any]])
```

- The aggregate tools read item names with `item.get("dish_name", " ")`; they
  do not read `product_name`.
- `analysis_scripts/evaluate_interaction.py` filters top-level parameters by
  DB method signature, but nested `dishes[]` key names are still compared
  recursively. A model that uses the correct `dish_name` key can fail to match a
  ground-truth call that uses `product_name`.
- The same evaluator's fuzzy fields for order are `dish_name` and
  `restaurant_name`; `set_meal_name`, `user_id`, and nested wrong keys are not
  covered by the DB fuzzy matcher.

Impact:

- Correct service-agent tool calls may fail tool-based evaluation when the
  ground truth uses `product_name` instead of `dish_name`, omits
  `restaurant_name`, or contains malformed field values.
- Official ground-truth execution can silently ignore aggregate items keyed as
  `product_name`, producing incorrect final payment/tax/nutrition values while
  still preserving a trace shape that the evaluator expects.
- Result-based evaluation can hide these issues because aggregate calculation
  calls are non-mutating.
- Some failures should be attributed to author-provided grounding/tool-schema
  inconsistencies rather than agent reasoning, visual grounding, or prompt
  quality.

Suggested handling:

- Replace all order aggregate `product_name` keys with `dish_name`.
- Correct `Salmone affumicato` to `Salmon affumicato`.
- Correct `Seafood Delight Set'` to `Seafood Delight Set`.
- Fix swapped `restaurant_name` / `user_id` in task 10.
- Fix `Annie Italian Restaurant_items` in task 26.
- Strip trailing whitespace from all IDs and category fields.
- Add missing `restaurant_name` to the four affected `add_dish_to_order`
  ground-truth calls, or document why omitted top-level parameters should be
  ignored during tool-call matching.

Status: confirmed locally; pending organizer clarification.

### ORDER-GROUND-004: Order category enums are incomplete and include non-canonical aliases

ID: ORDER-GROUND-004

Date: 2026-06-02

Official re-check note:

- Re-checked against `https://github.com/ego-link/egolink2026.git` main
  revision `27e1a23a11d82f1d7fb13a202f6d3591d2b0b943`.
- The official `tools/order/order_tools.json` category enum now includes all
  real catalog categories found in official `tools/order/order_init.py`.
- The official issue is narrower than the local fork finding: `Steaks` remains
  a non-canonical enum value while `Selected Steaks` is the real Annie catalog
  category. `Pasta` and `Italian Pasta` are both real categories, but are
  restaurant-specific and can still create semantic ambiguity.
- The missing-category evidence below applies to the local fork/worktree state,
  not to the official repository at the revision above.

Scenario / task: observed in `order1`, especially tasks that select a
restaurant or category from preferences such as pasta, beef, or steak.

Issue type: tool schema / catalog mismatch.

Affected files:

- `code/track2/EgoBench/tools/order/order_tools.json`
- `code/track2/EgoBench/tools/order/order_init.py`
- `code/track2/EgoBench/tools/order/order_db.py`

Observed:

- `find_dishes_by_category` and `add_dish_to_catalog` expose category enums in
  `tools/order/order_tools.json`.
- These enums are not the complete set of real catalog categories in
  `tools/order/order_init.py`.
- Some enum values are near aliases but not canonical catalog values. For
  example, the schema exposes `Steaks`, while Annie's real category is
  `Selected Steaks`.
- `Pasta` is a real category for `Mediterranean Greek Restaurant`, but Annie's
  pasta items are under `Italian Pasta`. A model following the enum or a
  coarse visual/category phrase can easily query `Pasta` for Annie and receive
  an empty result even though the relevant dishes exist.
- `find_dishes_by_category` performs strict lowercase equality on the category
  string, so these near aliases do not recover automatically.

Expected / canonical behavior:

- Tool category enums should either list all real category values present in
  the catalog, or the category parameter should be free-form with clear
  documentation.
- If aliases such as `Steaks` are exposed, the tool should map them to canonical
  categories such as `Selected Steaks`, or the schema should use the exact
  canonical category instead.

Evidence:

- Real order catalog categories:

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

- `find_dishes_by_category` enum contains:

```text
Pizza, Pasta, Salads, Sandwiches & Panini, Antipasti & Snacks,
Cheese & Olives, Cold Cuts, Steaks, Handmade Bread, Italian Pasta
```

- Missing from `find_dishes_by_category` enum:

```text
Annie's top dishes, Appetizers, Desserts, Main Courses, Seafood,
Selected Steaks, Sides, Soups
```

- Enum value not present as a real catalog category:

```text
Steaks
```

- Runtime checks:

```text
Annie Italian Restaurant | Pasta => {'dishes': []}
Annie Italian Restaurant | Italian Pasta => 10 dishes
Annie Italian Restaurant | Steaks => {'dishes': []}
Annie Italian Restaurant | Selected Steaks => 3 dishes
Mediterranean Greek Restaurant | Pasta => 3 dishes
Mediterranean Greek Restaurant | Main Courses => 7 dishes
Mediterranean Greek Restaurant | Seafood => 6 dishes
Mediterranean Greek Restaurant | Sides => 2 dishes
```

- `tools/order/order_db.py` implements category lookup as exact lowercase
  equality:

```python
matching_dishes = [dish.name for dish in store['catalog'].values() if dish.category == cat_lower]
```

Impact:

- The service agent can be misled into choosing a valid enum value that returns
  no results for the intended restaurant.
- Restaurant recommendation can be biased by false empty results. For example,
  querying Annie with `Steaks` or `Pasta` can make it appear less suitable than
  it actually is.
- This contributes to wrong-restaurant failures and wrong branch selection in
  visual order tasks.
- The ambiguity is especially harmful when visual category text, user wording,
  and database category names are semantically close but not exact.

Suggested handling:

- Ask the benchmark organizers to align category enums with the actual catalog.
- Either add all canonical categories to the schema or remove the enum and make
  the parameter explicitly free-form.
- Add documented alias handling for near categories such as `Steaks` ->
  `Selected Steaks` and generic `Pasta` -> restaurant-specific `Italian Pasta`
  where appropriate.
- For local agent behavior, treat category enums as hints and retry with
  catalog-style aliases when a category query unexpectedly returns empty.

Status: confirmed locally; pending organizer clarification.
