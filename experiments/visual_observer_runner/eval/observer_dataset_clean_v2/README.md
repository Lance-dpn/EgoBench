# Observer Dataset Clean v2

This is a clean rebuild from `scenarios/final/*.json` instructions only.
It deliberately does not use older bootstrap/problem-set files or final values.

GT is pending and must be filled by actual video inspection before strict observer evaluation.

## Build Results

- `order`: 260 cases from 268 raw visual problems over 100 tasks
- `retail`: 254 cases from 324 raw visual problems over 334 tasks
- `restaurant`: 348 cases from 418 raw visual problems over 169 tasks
- `kitchen`: 69 cases from 108 raw visual problems over 125 tasks

## Files Per Scenario

- `01_scenario_tasks.jsonl`
- `02_visual_questions_raw.jsonl`
- `03_visual_queries_raw.jsonl`
- `04_visual_query_clusters.json`
- `05_observer_dataset_with_gt.json`
- `excluded_cases.json`
- `review_required_cases.json`
- `summary.md`
