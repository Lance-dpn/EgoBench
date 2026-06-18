# Reviewed GT visual-anchor validation

Scope:
- `scenarios/final/retail6.json`
- `scenarios/final/retail10.json`
- `scenarios/final/kitchen4.json`
- `scenarios/final/restaurant5.json`
- `scenarios/final/order2.json`

Changes:
- Added top-level `key` and `value` visual-anchor fields to every task in the five reviewed GT scenario files.
- Added `secondary_key` and `secondary_value` fields for the next DB-mappable visual anchor in each reviewed task.
- Rechecked `restaurant5`, `kitchen4`, and `order2` task-by-task against the visual anchor sequence and the instruction branch logic.
- Corrected `order2` task 12 GT after visual review: the wooden-board roasted vegetable skewer is `Grilled Fish`, which enters the umami branch and adds `Greek Yogurt with Honey & Nuts` x2.
- Corrected stored primary visual anchors for `order2` task 89 and task 93; their reviewed GT branch results remain valid.
- Added `add_visual_anchors_for_reviewed_gt.py` so the visual anchors can be regenerated.
- Added `verify_reviewed_gt_with_anchors.py` to validate anchors and replay GT execution.
- Added `verify_gt_exact_db_fields.py` to reject GT fields that only pass by fuzzy/inclusion matching.

Primary anchor coverage:

| Scenario | Tasks | Key distribution | Anchor values | Missing |
| --- | ---: | --- | ---: | ---: |
| retail6 | 49 | `product_name`: 49 | 60 | 0 |
| retail10 | 63 | `product_name`: 63 | 63 | 0 |
| kitchen4 | 50 | `recipe_name`: 23, `ingredient_name`: 27 | 58 | 0 |
| restaurant5 | 50 | `dish_name`: 50 | 50 | 0 |
| order2 | 97 | `dish_name`: 97 | 97 | 0 |

Secondary anchor coverage:

| Scenario | Tasks | Secondary key distribution | Secondary values | Empty secondary |
| --- | ---: | --- | ---: | ---: |
| retail6 | 49 | `product_name`: 49 | 44 | 5 |
| retail10 | 63 | `product_name`: 63 | 25 | 38 |
| kitchen4 | 50 | `recipe_name`: 13, `ingredient_name`: 37 | 12 | 38 |
| restaurant5 | 50 | `dish_name`: 50 | 50 | 0 |
| order2 | 97 | `dish_name`: 97 | 13 | 84 |

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
python experiments/visual_observer_runner/eval/verify_gt_exact_db_fields.py
```

Exact DB field result:

| Scenario | Exact field errors |
| --- | ---: |
| retail6 | 0 |
| retail10 | 0 |
| kitchen4 | 0 |
| restaurant5 | 0 |
| order2 | 0 |

Secondary DB field result:

| Scenario | Secondary exact field errors |
| --- | ---: |
| kitchen4 | 0 |
| restaurant5 | 0 |
| order2 | 0 |

Builder/branch replay check:

| Scenario | Recomputed GT mismatches |
| --- | ---: |
| kitchen4 | 0 |
| order2 | 0 |

`restaurant5` has no builder script; its branch replay is recorded in `restaurant5_gt_v1_audit.md`, and the official evaluator result remains 50/50.

Compile check:

```bash
python -m py_compile experiments/visual_observer_runner/eval/add_visual_anchors_for_reviewed_gt.py experiments/visual_observer_runner/eval/build_order2_gt.py experiments/visual_observer_runner/eval/verify_reviewed_gt_with_anchors.py experiments/visual_observer_runner/eval/verify_gt_exact_db_fields.py
```

Result: passed.
