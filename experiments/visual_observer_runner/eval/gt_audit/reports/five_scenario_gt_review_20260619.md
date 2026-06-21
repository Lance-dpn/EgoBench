# Five-scenario GT review, 2026-06-19

Scope:
- `retail6`: 49 tasks, 156 GT calls.
- `retail10`: 63 tasks, 204 GT calls.
- `restaurant5`: 50 tasks, 169 GT calls.
- `kitchen4`: 50 tasks, 259 GT calls.
- `order2`: 97 tasks, 417 GT calls.

Reviewed scenarios: `retail6`, `retail10`, `restaurant5`, `kitchen4`, `order2`.

## Visual Anchor Check

Actual media was inspected through contact sheets generated from current videos:

- `/tmp/egobench_gt_visual_review/retail6_sheet.jpg`
- `/tmp/egobench_gt_visual_review/retail10_sheet.jpg`
- `/tmp/egobench_gt_visual_review/restaurant5_sheet.jpg`
- `/tmp/egobench_gt_visual_review/kitchen4_sheet.jpg`
- `/tmp/egobench_gt_visual_review/butcher_greek_sheet.jpg`
- `/tmp/egobench_gt_visual_review/greek_annie_1_sheet.jpg`
- `/tmp/egobench_gt_visual_review/meraki_greek_sheet.jpg`
- `/tmp/egobench_gt_visual_review/sunny_greek_sheet.jpg`
- `/tmp/egobench_gt_visual_review/pauhana_greek_sheet.jpg`
- `/tmp/egobench_gt_visual_review/afrikana_greek_sheet.jpg`

Visual findings:
- `retail6`: frames show the St Michel orange box, Bahlsen chocolate cookie box, Nutella cylindrical red-lid products, white cookie box, and yellow lower cookie box used by the reviewed anchors.
- `retail10`: frames show the cheese cabinet with the front wedge `Appenzeller Cheese`, front square cheese, rear rectangular cheese, rightmost label, and Basiron/Mystic Valley label positions used by the reviewed anchors.
- `restaurant5`: frames show the drink menu board with the six image-position anchors. The rule that text above a drink image is the drink name remains required for this scene.
- `kitchen4`: frames show dumpling wrapping, the white wrapper/flour dough, green chives, and meat filling bowl used by the reviewed anchors.
- `order2`: Greek menu videos show the readable dish names used by anchors, including `Greek Village Roast Chicken Leg`, `Greek Lamb Chops`, `Fried calamari`, `Grilled Octopus`, `Grilled Fish`, `Mediterranean Grilled Prawns`, `Feta & Tomato Spaghetti`, `Octopus Spaghetti`, `Spaghetti Bolognese`, `Greek Yogurt with Honey & Nuts`, and `Vanilla pudding`.

## Deterministic GT Reconstruction

Builder-based reconstruction was run in memory for:
- `retail6`
- `retail10`
- `kitchen4`
- `order2`

Result:

```json
{
  "retail6": {"tasks": 49, "generated": 49, "gt_diffs": [], "value_diffs": []},
  "retail10": {"tasks": 63, "generated": 63, "gt_diffs": [], "value_diffs": []},
  "kitchen4": {"tasks": 50, "generated": 50, "gt_diffs": [], "value_diffs": []},
  "order2": {"tasks": 97, "generated": 97, "gt_diffs": [], "value_diffs": []}
}
```

`restaurant5` has no equivalent builder. It is covered by `restaurant5_gt_v1_audit.md`, exact DB-field checks, official tool replay, compute checks, and reviewed anchor/joint validation.

## Validation Commands

Exact DB-field validation:

```text
retail6: exact_field_errors=0
retail10: exact_field_errors=0
kitchen4: exact_field_errors=0
restaurant5: exact_field_errors=0
order2: exact_field_errors=0
```

Official tool replay:

```text
retail6: tasks_checked=49 tasks_with_errors=0
retail10: tasks_checked=63 tasks_with_errors=0
restaurant5: tasks_checked=50 tasks_with_errors=0
kitchen4: tasks_checked=50 tasks_with_errors=0
order2: tasks_checked=97 tasks_with_errors=0
```

Compute/aggregate validation:

```text
retail6: tasks=49 aggregate_checked=50 changes=0 errors=0
retail10: tasks=63 aggregate_checked=63 changes=0 errors=0
restaurant5: tasks=50 aggregate_checked=47 changes=0 errors=0
kitchen4: tasks=50 aggregate_checked=50 changes=0 errors=0
order2: tasks=97 aggregate_checked=184 changes=0 errors=0
```

Reviewed anchor/joint validation:

```text
retail6: tasks=49 anchors=ok db_errors=0 joint=49/49 micro=1.0
retail10: tasks=63 anchors=ok db_errors=0 joint=63/63 micro=1.0
kitchen4: tasks=50 anchors=ok db_errors=0 joint=50/50 micro=1.0
restaurant5: tasks=50 anchors=ok db_errors=0 joint=50/50 micro=1.0
order2: tasks=97 anchors=ok db_errors=0 joint=97/97 micro=1.0
```

## Corrections Confirmed

- `retail10` task 18: confirmed no `remove_from_cart(Brie Cheese)` should occur. The lowest tag-price anchor is `Basiron Gouda Cheese`, which is not in `user_202`'s cart. Final compute includes `Brie Cheese`.
- `kitchen4` task 50: confirmed Apple and Banana are tied for lowest sodium among countertop ingredients, so both must be added. Current GT includes both and the builder now reproduces both.
- `order2`: exact-field verifier was updated to match the official `add_dish_to_order(restaurant_name, user_id, dish_name, quantity)` signature. It no longer expects nonexistent `category`, `price`, `tax_rate`, or `discount` parameters for order GT.
- `retail6`: replay logic was updated to ignore initial cart entries that are not present in the official retail catalog when deriving expected compute parameters. This removes false positives while preserving official-tool compute validation.

## Result

The current GT and visual anchor fields for all five scenarios pass the reviewed checks above. No remaining GT correction is indicated by this audit.
