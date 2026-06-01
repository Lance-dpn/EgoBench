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

### ORDER-GROUND-003: Set-meal payment may be undercounted when set-meal price is zero

ID: ORDER-GROUND-003

Date: 2026-06-01

Scenario / task: observed in `order1`, task 1

Issue type: related database calculation / order-state issue.

Affected files:

- `code/track2/EgoBench/tools/order/order_init.py`
- `code/track2/EgoBench/tools/order/order_db.py`
- `code/track2/EgoBench/results/qwen36-offline-url-observer-order1-smoke/order1_easy.json`

Observed:

- Annie set meals are represented as order items such as
  `italian classic set` and `cold cuts & cheese platter`.
- Some set-meal prices in the order initialization data are `0.0`.
- `compute_total_payment` sums set-meal price directly instead of deriving the
  price from included dishes.

Expected / canonical behavior:

- Either set-meal prices should be populated in the initialization data, or
  payment calculation should consistently derive set-meal totals from included
  dishes when the set-meal price is not meaningful.

Evidence:

- The recent run computed total payment as `61.6` after adding
  `turkey breast ham`, despite the existing set-meal items in the order.
- The task decision depends on whether the current order price exceeds
  `150` yuan.

Impact:

- Conditional branches based on total payment can be wrong even if the visual
  grounding and dish addition are correct.
- This can cause the service agent to skip an expected remove operation and
  then calculate final tax/nutrition over the wrong order state.

Suggested handling:

- Verify whether zero set-meal prices are intentional in the official data.
- If not intentional, correct set-meal prices or introduce a documented
  calculation policy for set meals.

Status: open.
