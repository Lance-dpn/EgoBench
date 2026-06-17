# Visual Observer Evaluation Assets

This directory stores reusable observer-evaluation assets: normalized visual
requests, problem sets, and GT files.

Runtime logs, observer traces, sampled evaluation results, extracted frames, and
model outputs belong under:

```text
experiments/visual_observer_runner/cache/visual_stage_eval/
```

## Layout

```text
eval/
  observer_problem_set_order1/
    observer_grounding_order1_bootstrap.json
    observer_visual_problem_summary.md
    _work/
  observer_problem_set_retail/
    observer_grounding_retail_bootstrap.json
    _work/
      retail1_rebuild/
  observer_problem_set_{scenario}/
    observer_grounding_{scenario}_bootstrap.json
    observer_visual_problem_summary.md
    _work/
```

The evaluator reads only:

```text
observer_problem_set_{scenario_key}/observer_grounding_{scenario_key}_bootstrap.json
```

Generated drafts, normalized request JSONL files, skipped-candidate reports,
and older review notes should live under each scenario directory's `_work/`
folder. Large cross-scenario review/pre-GT packages are intentionally not kept
in this directory because they can be regenerated and make the reviewed GT hard
to inspect.

## Current GT Status

- `order1`: bootstrap exists and is the primary reviewed order observer GT.
- `retail`: currently partial. Only `retail1` has been rebuilt through the
  full process: instruction extraction, visual-problem clustering, video
  inspection, EVENT GT filling, DETAIL GT filling, and review notes.
- `retail2`, `retail3`, `retail4`, `retail5`, `retail7`, `retail8`, and
  `retail9`: pending rebuild. Do not treat them as completed GT.
- `restaurant` and `kitchen`: existing bootstrap files are retained, but should
  be considered pending spot-check unless explicitly reviewed.

## Build Assets

```text
python experiments/visual_observer_runner/build_observer_eval_assets.py --scenario_key retail1
python experiments/visual_observer_runner/build_observer_eval_assets.py --scenario retail
python experiments/visual_observer_runner/build_observer_eval_assets.py --all_scenarios
```

`order1` has a hand-corrected specialized GT file. The generic builder skips it
by default unless `--include_order1` is passed.

For retail scenarios, do not use a generic script to mark GT as complete. Follow
the retail1 process: extract visual requests per instruction, cluster them into
normalized observer problems, inspect the corresponding video frames, fill event
and detail GT, and write review notes for under-specified cases.

## Evaluate

```text
python experiments/visual_observer_runner/evaluate_observer_grounding_sample.py \
  --scenario_key order1 \
  --sample_size 20 \
  --experiment_id observer-grounding-order1-sample

python experiments/visual_observer_runner/evaluate_observer_grounding_sample.py \
  --scenario_key retail1 \
  --all \
  --include_high_review \
  --experiment_id observer-grounding-retail1-all
```

## Runtime Outputs

Sampled observer evaluation runs should be written to cache, not this directory:

```text
cache/visual_stage_eval/observer_problem_set_{scenario_key}/eval_runs/
```

Observer HTTP traces remain under:

```text
cache/visual_observer/runs/
```
