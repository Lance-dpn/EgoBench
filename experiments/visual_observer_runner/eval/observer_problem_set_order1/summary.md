# Observer Problem Set Summary

Scenario: `order1`

This directory contains the evaluation-ready observer grounding set for order1.

## Active Files

- `observer_grounding_order1_bootstrap.json`: evaluator input.
- `observer_visual_problem_summary.md`: human-readable visual problem index.
- `observer_visual_problem_summary.json`: structured visual problem index.
- `_work/`: generation drafts, old review notes, observer inputs, and skipped candidates.

## Current Status

- Eval cases: 160
- Visual problems under same-video/same-menu grouping: 159
- GT status: AI bootstrap with human corrections for known order1 menu-category issues.

Event ranges are represented by `primary_content_range` and related time
fields in the GT file. The current schema does not store a separate GT keyframe;
keyframe quality is evaluated by checking the observer-predicted keyframe
against the GT primary range.
