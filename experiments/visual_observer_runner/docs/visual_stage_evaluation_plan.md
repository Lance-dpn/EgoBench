# Visual Observer Stage Evaluation Plan

Date: 2026-06-03

This document defines the staged evaluation plan for visual observer work. The
goal is to separate observer event localization, detail recognition, and service
tool-use accuracy so that failures can be diagnosed at the correct layer.

## Motivation

End-to-end task success mixes several independent capabilities:

- The service agent must decide when a visual reference is unresolved.
- The observer event stage must localize the requested visible event or region.
- The observer detail stage must read the localized event or region.
- The service agent must verify visual clues with scenario tools and execute
  the correct workflow.

The official scenario `key/value` labels are useful for final visual identity
checks, but they are not enough to evaluate event localization because they do
not include timestamps or spatial regions. They are also incomplete for detail
analysis when the task contains multiple visual referents or when the visible
evidence needed by the service is a section/category/region rather than only
the final entity value.

## Visual Request Taxonomy

Use a small event-mode taxonomy for review and evaluation. Fine-grained
patterns are kept only as debug metadata.

Event modes:

- `temporal_sequence_event`: first/second/third/last event in a visible
  sequence, usually pointing, pick-up, put-down, or holding.
- `single_pointing_event`: one visible pointing target without ordinal
  sequencing.
- `static_spatial_region`: a target identified by absolute geometry, such as a
  menu section, shelf row, page/fold, board region, pot/pan/tray region, visible
  label area, or section title area.
- `relative_spatial_region`: a target identified relative to another visible
  anchor, such as left/right/next to/under/above another product, dish, or
  section.
- `object_action_state`: a non-ordinal visible action/state, such as
  sprinkling, cutting, boiling, stir-frying, holding, picked up, or put down.
- `composite_scene_context`: a whole-scene or multi-object context needed to
  infer a recipe/dish/ingredient from visible ingredients or cooking state.

Detail modes:

- `entity_identity`: read the localized product, dish, ingredient, or set meal.
- `section_or_category_identity`: identify a localized menu/category/section.
- `composite_identity`: infer a recipe/dish from localized scene evidence.
- `visible_text`: read visible label/title/sign/package text.
- `visible_region_description`: describe the localized region when no entity
  identity is needed.

Fine patterns currently used for debugging include
`temporal_ordinal_pointing`, `temporal_ordinal_action`, `single_pointing`,
`spatial_region`, `relative_anchor`, `visible_text_or_label`,
`object_action_state`, `composite_scene_identity`, and
`menu_section_or_category`.

## Observer Task Schema

The service layer should send the observer a structured request instead of the
original user/business question. `normalized_visual_requests.jsonl` is an
audit/review artifact. The observer-facing artifact is `observer_tasks.jsonl`,
and each row is the `observer_task` object.

```json
{
  "request_id": "order1_task3_v1",
  "event_mode": "temporal_sequence_event",
  "detail_mode": "entity_identity",
  "target_key": "dish_name",
  "target_kind": "menu_item",
  "action": "pointing",
  "ordinal": "third",
  "sequence_scope": "all distinct stable pointing events in the visible menu scope",
  "spatial_scope": {
    "surface": "menu",
    "page": null,
    "region": null,
    "relation": null
  },
  "appearance_constraints": [],
  "visible_text_constraints": [],
  "menu_scope": {
    "scope_type": "active_selected_menu",
    "menu_label": null,
    "candidate_visible_menus": ["menu_1", "menu_2"],
    "requires_service_menu_resolution": true
  },
  "forbidden": [
    "database facts",
    "ranking decisions",
    "price/nutrition/tax calculations",
    "order mutations"
  ]
}
```

The event stage should receive only localization-relevant fields. The detail
stage should receive the event output plus `target_key`, `target_kind`, and
`detail_goal`.

The original instruction snippet is kept only as
`review_source_instruction_snippet` for human review. It is not an observer
prompt. The observer-facing payload is `observer_task`, which contains only
structured visual fields.

For order tasks, `menu_scope` is explicit because videos commonly show two
menus. The service layer should resolve whether the active restaurant maps to
`menu_1` or `menu_2`; the observer should receive menu labels or active-menu
scope, not restaurant database names.

## GT Bootstrap Workflow

Because event GT is missing, we will build a first-pass GT set manually with
AI-assisted inspection, then leave it open for human correction.

1. Extract all visual requests from `scenarios/final/*.json`.
2. Normalize each visual request using the taxonomy above.
3. Group normalized requests by `visual_task_group_key`, so repeated visual
   problems such as "identify the second pointed dish" or "read the
   bottom-left menu section/category" can share GT work where appropriate.
   Keep `abstract_task_key` as finer debug trace metadata.
4. For each normalized request or grouped visual task, inspect the corresponding video with sampled
   frames, frame sequences, and existing observer traces when available.
5. Produce first-pass event GT and detail GT.
6. Mark each GT entry with confidence and whether it needs human review.
7. Let humans correct timestamps, regions, and detail identities.
8. Freeze corrected GT versions for regression evaluation.

This should be done incrementally. Start with `order1`, then add pointing-heavy
retail scenarios, then restaurant and kitchen.

## Event GT Schema

```json
{
  "request_id": "order1_task3_v1",
  "gt_version": "ai_bootstrap_v1",
  "video_path": "greek_annie_1.mp4",
  "pattern": "temporal_ordinal_pointing",
  "event_type": "pointing",
  "ordinal": "third",
  "expected_time_range": {
    "start": 13.4,
    "end": 14.7,
    "center": 14.05
  },
  "primary_content_range": {
    "start": 13.65,
    "end": 14.4,
    "center": 14.025
  },
  "allowed_transition_range": {
    "start": 13.2,
    "end": 14.9
  },
  "expected_region": {
    "coarse": "right menu page, pizza list area",
    "target_relation": "finger endpoint on one menu item line"
  },
  "candidate_sequence": [
    {"event_order": 1, "time_range": {"start": 9.45, "end": 10.5}},
    {"event_order": 2, "time_range": {"start": 12.6, "end": 13.65}},
    {"event_order": 3, "time_range": {"start": 13.65, "end": 14.7}}
  ],
  "confidence": "medium",
  "needs_human_review": true,
  "notes": "AI bootstrap; verify by frame inspection before freezing."
}
```

`primary_content_range` is the range where the requested visual evidence is
clearest. `allowed_transition_range` captures a wider boundary where selecting
the target may still be acceptable but should receive lower score if it mostly
covers transition time.

## Detail GT Schema

```json
{
  "request_id": "order1_task3_v1",
  "gt_version": "ai_bootstrap_v1",
  "target_key": "dish_name",
  "target_value": "Margherita",
  "acceptable_aliases": ["margherita"],
  "visible_text_expected": ["Margherita"],
  "negative_neighbors": ["Pepperoni", "Calzone", "Black truffle"],
  "region_dependency": "use event GT region; do not read neighboring menu lines",
  "confidence": "medium",
  "needs_human_review": true,
  "notes": "Detail GT may differ from final scenario value when the task needs a section, category, or multiple visible anchors."
}
```

Detail GT should not be limited to official `value`. When the task asks for a
visible section/category/region, the detail target may be `category` or
`visible_region`. When the service needs several visible anchors, each anchor
should get a separate detail GT entry.

## Event Evaluation Metrics

Event localization is a time-range problem. The primary metric should be based
on center matching rather than strict IoU alone because a predicted range may
be wider or narrower while still capturing the decisive content.

Let:

- `gt_center` be `primary_content_range.center` when available, otherwise
  `expected_time_range.center`.
- `pred_center` be the center of the predicted selected event range.
- `gt_duration` be the duration of `primary_content_range` when available,
  otherwise `expected_time_range`.
- `center_error = abs(pred_center - gt_center)`.
- `normalized_center_error = center_error / max(gt_duration, 0.5)`.

Recommended scoring:

```text
center_score = max(0, 1 - normalized_center_error)
```

Then apply penalties:

- `transition_penalty`: predicted center outside `allowed_transition_range`.
- `overcoverage_penalty`: predicted range contains too much transition or
  irrelevant time.
- `undercapture_penalty`: predicted range misses the primary content center.
- `ordinal_penalty`: wrong event_order for ordinal pointing requests.
- `entity_leak_penalty`: event output includes dish/product/category names
  when it should output only time and coarse region.

Suggested event success threshold:

```text
success if:
  center_score >= 0.7
  and predicted center is inside allowed_transition_range
  and ordinal is correct when ordinal is required
  and no severe entity leakage occurred
```

IoU should remain a secondary metric:

- useful for detecting overly broad ranges,
- insufficient alone because long ranges can get good recall while covering too
  much transition time.

## Detail Evaluation Metrics

Detail should be evaluated in two modes:

1. `detail_oracle_event`: feed detail with GT event range/region.
2. `detail_predicted_event`: feed detail with the event stage output.

Metrics:

- exact/fuzzy match for `target_key` and `target_value`,
- hit@k when multiple candidates are allowed,
- neighbor confusion rate using `negative_neighbors`,
- confidence-weighted error rate,
- background leakage rate,
- missing/empty output rate.

`detail_oracle_event` isolates recognition quality. `detail_predicted_event`
measures robustness under event errors.

## Combined Observer Metrics

The full observer pipeline should report:

- event center score,
- event ordinal accuracy,
- event entity leakage rate,
- detail oracle-event accuracy,
- detail predicted-event accuracy,
- final visual anchor recall against official `key/value`.

This makes failures attributable:

- event good + detail bad => recognition/detail prompt issue,
- event bad + detail plausible => localization issue,
- both good + service wrong => service/tool workflow issue.

## Implementation Plan

1. Add a `visual_request_normalizer.py` module that converts task instruction
   snippets and runtime observer queries into the normalized schema.
2. Add a `generate_visual_gt_bootstrap.py` script that lists normalized visual
   requests and writes empty GT templates.
3. For the first batch, manually inspect videos and fill AI-bootstrap event and
   detail GT for `order1`.
4. Add `evaluate_event_stage.py` using center-based scoring and leakage checks.
5. Add `evaluate_detail_stage.py` with oracle-event and predicted-event modes.
6. Add a small regression report that groups failures by taxonomy pattern.

Initial focus should be `order1` because it has repeated ordinal pointing,
menu regions, section/category reading, and known observer instability.

## Current Pre-GT Review Artifacts

Implemented on 2026-06-03:

- `experiments/visual_observer_runner/visual_request_normalizer.py`
- `experiments/visual_observer_runner/generate_visual_gt_bootstrap.py`

Generated pre-video-inspection review packages:

- `experiments/visual_observer_runner/eval/review_pre_gt_all`
- `experiments/visual_observer_runner/eval/review_pre_gt_order1`

These packages contain:

- `normalized_visual_requests.jsonl`
- `event_gt_templates.json`
- `detail_gt_templates.json`
- `abstract_visual_task_groups.json`
- `summary.md`

All GT fields remain empty and are marked `pending_video_inspection`. The
final scenario `key/value` fields are not included as GT hints because they may
represent only one branch or one final entity, while a task can require
section/category or catalog-level visual grounding.
