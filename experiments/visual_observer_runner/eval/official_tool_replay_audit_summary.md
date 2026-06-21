# Official Tool Replay Audit Summary

Generated with:

```bash
python experiments/visual_observer_runner/eval/replay_gt_with_official_tools.py \
  --scenarios retail6 retail10 restaurant5 kitchen4 order2 \
  --report experiments/visual_observer_runner/eval/official_tool_replay_audit.json
```

## Scope

This audit replays the current `ground_truth` calls in:

- `scenarios/final/retail6.json`
- `scenarios/final/retail10.json`
- `scenarios/final/restaurant5.json`
- `scenarios/final/kitchen4.json`
- `scenarios/final/order2.json`

For each task, the script:

1. Initializes the official scenario DB from the matching `*_init.py` seed.
2. Checks `value` and `secondary_value` against official lookup tools where possible.
3. Executes each current GT tool call through the official DB method.
4. Before each compute/tally call, calls the official current-state tool (`get_cart`, `get_user_order_summary`, `get_current_menu`, or `get_current_shopping_list`) and derives the expected compute/tally parameters from that tool result.
5. Calls the same official compute/tally tool with those state-derived parameters and compares both parameters and returned result.

The script does not modify scenario files.

## Current Result

| Scenario | Tasks checked | Tasks with replay issues |
| --- | ---: | ---: |
| retail6 | 49 | 5 |
| retail10 | 63 | 0 |
| restaurant5 | 50 | 0 |
| kitchen4 | 50 | 0 |
| order2 | 97 | 0 |

Full machine-readable evidence is in:

```text
experiments/visual_observer_runner/eval/official_tool_replay_audit.json
```

## Remaining Issues

All remaining replay issues are in `retail6`, and all involve `user_456`.

The official `get_cart` tool reports an initial cart item:

```text
highland speciality shortbread teddy bear*2"
```

That item is returned by the cart state, but compute tools cannot find it in the catalog. When the audit derives compute parameters from the official cart state, compute returns `partial_success`; the current GT omits that non-catalog item and compute returns `success` with the same numeric totals for the valid products.

Affected tasks:

| Task | Tool | Current GT behavior | State-derived official-tool behavior |
| ---: | --- | --- | --- |
| 10 | `compute_total_tax` | Omits non-catalog cart item. Numeric total `8.07`, status `success`. | Includes non-catalog cart item from `get_cart`. Numeric total `8.07`, status `partial_success`. |
| 14 | `compute_total_nutrition` | Omits non-catalog cart item. Numeric totals match valid items, status `success`. | Includes non-catalog cart item from `get_cart`. Numeric totals match valid items, status `partial_success`. |
| 24 | `compute_total_tax` | Omits non-catalog cart item. Numeric total `3.85`, status `success`. | Includes non-catalog cart item from `get_cart`. Numeric total `3.85`, status `partial_success`. |
| 32 | `compute_total_payment` | Omits non-catalog cart item. Numeric total `145.64`, status `success`. | Includes non-catalog cart item from `get_cart`. Numeric total `145.64`, status `partial_success`. |
| 42 | `compute_total_payment` | Omits non-catalog cart item. Numeric total `177.14`, status `success`. | Includes non-catalog cart item from `get_cart`. Numeric total `177.14`, status `partial_success`. |

## Interpretation

This is not currently evidence of a visual-anchor error. It is a DB/state consistency issue: the official cart state contains an item that the official compute tools cannot resolve against the catalog.

There are two policy choices before editing GT:

1. Keep the current GT compute params that omit the non-catalog item, because compute can only calculate valid catalog products and returns clean `success`.
2. Include the cart item returned by `get_cart`, accepting `partial_success` from the official compute tool.

The existing GT follows option 1. The audit flags these tasks because the requested stricter rule says compute inputs should come from current official tool state rather than from manual filtering.

## Instruction-Driven Spot Check

The new instruction-driven executor was also tested on `restaurant5` task 1 and `retail6` task 10.

Command shape:

```bash
python experiments/visual_observer_runner/eval/generate_gt_from_instruction_with_tools.py \
  --scenarios <scenario> \
  --task_ids <task_id> \
  --max_steps 12 \
  --report /tmp/instruction_gt_<scenario>_<task_id>.json \
  --jsonl_report /tmp/instruction_gt_<scenario>_<task_id>.jsonl
```

Results:

- `restaurant5` task 1: generated GT matches the existing GT after case-insensitive parameter normalization.
- `retail6` task 10: generated GT does not match the existing GT on `compute_total_tax` parameters. The executor first called `get_cart`, received the non-catalog item `highland speciality shortbread teddy bear*2"`, then passed it into `compute_total_tax`. The official compute tool returned the same numeric tax total `8.07` but with `status=partial_success`.

This independently confirms that the remaining retail6 discrepancy is caused by the official current cart state containing a non-catalog item, not by the visual anchor for task 10.
