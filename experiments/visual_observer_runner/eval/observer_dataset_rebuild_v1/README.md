# Observer Dataset Rebuild v1

This directory is independent from the older `observer_problem_set_*` folders.
It follows `../eval-process.md` and stores GT inline in each eval case.

## Layout

Each scenario subdirectory contains:

- `01_scenario_tasks.jsonl`: final scenario tasks used as extraction source.
- `02_visual_questions_raw.jsonl`: un-deduped extracted visual problems.
- `03_visual_queries_raw.jsonl`: visual_query_v1 per raw problem.
- `04_visual_query_clusters.json`: deduped observer problems.
- `05_observer_dataset_with_gt.json`: source-of-truth eval cases with inline event/detail GT.
- `excluded_cases.json`: cases kept out of strict eval.
- `review_required_cases.json`: validation or GT gaps that need manual review.
- `summary.md`: readable counts and coverage.

## Current Build

- `order`: 159 cases, 293 raw visual problems, 0 excluded, 0 review-required, 0 validation issues
- `retail`: 63 cases, 570 raw visual problems, 12 excluded, 0 review-required, 0 validation issues
- `restaurant`: 28 cases, 169 raw visual problems, 1 excluded, 0 review-required, 0 validation issues
- `kitchen`: 12 cases, 126 raw visual problems, 0 excluded, 0 review-required, 0 validation issues

## Notes

- `visual_query_v1` is the normalized observer-call interface and cluster key.
- GT is bootstrapped from existing video-inspected files and marked for human review where needed.
- Do not edit indexed exports by hand; generate them from `05_observer_dataset_with_gt.json`.
