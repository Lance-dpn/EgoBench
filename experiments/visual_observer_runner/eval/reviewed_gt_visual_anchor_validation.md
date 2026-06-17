# Reviewed GT visual-anchor validation

Scope:
- `scenarios/final/retail6.json`
- `scenarios/final/retail10.json`
- `scenarios/final/kitchen4.json`
- `scenarios/final/restaurant5.json`
- `scenarios/final/order2.json`

Changes:
- Added top-level `key` and `value` visual-anchor fields to every task in the five reviewed GT scenario files.
- Kept existing `ground_truth` tool chains unchanged.
- Added `add_visual_anchors_for_reviewed_gt.py` so the visual anchors can be regenerated.
- Added `verify_reviewed_gt_with_anchors.py` to validate anchors and replay GT execution.

Anchor coverage:

| Scenario | Tasks | Key distribution | Anchor values | Missing |
| --- | ---: | --- | ---: | ---: |
| retail6 | 49 | `product_name`: 49 | 60 | 0 |
| retail10 | 63 | `product_name`: 63 | 63 | 0 |
| kitchen4 | 50 | `recipe_name`: 23, `ingredient_name`: 27 | 58 | 0 |
| restaurant5 | 50 | `dish_name`: 50 | 50 | 0 |
| order2 | 97 | `dish_name`: 97 | 99 | 0 |

Validation command:

```bash
python experiments/visual_observer_runner/eval/verify_reviewed_gt_with_anchors.py
```

Validation result:

| Scenario | Anchor DB check | DB execution errors | Official joint | Micro accuracy |
| --- | --- | ---: | ---: | ---: |
| retail6 | ok | 0 | 49/49 | 1.0 |
| retail10 | ok | 0 | 63/63 | 1.0 |
| kitchen4 | ok | 0 | 50/50 | 1.0 |
| restaurant5 | ok | 0 | 50/50 | 1.0 |
| order2 | ok | 0 | 97/97 | 1.0 |

Additional check:

```bash
python -m py_compile experiments/visual_observer_runner/eval/add_visual_anchors_for_reviewed_gt.py experiments/visual_observer_runner/eval/verify_reviewed_gt_with_anchors.py
```

Result: passed.
