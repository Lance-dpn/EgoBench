"""Event-stage prompt builders for the visual observer.

The event stage localizes the visible event or region that grounds the user's
current visual reference. It should not identify final entity names or answer
database questions.
"""

from __future__ import annotations

from typing import Any

from experiments.visual_observer_runner.prompts.observer_scenario import (
    build_observer_event_scene_description,
    format_normalized_visual_context,
)


OBSERVER_EVENT_PROMPT_VERSION = "observer_event_prompts_v14_visual_query"


EVENT_LOCALIZER_COMMON_RULES = """
- Use only the visual input.
- Localize one requested visible event/region; do not identify final dish/product names.
- The event stage must output only timing and coarse spatial regions. Do not
  put visible dish names, product names, menu item text, category titles, OCR
  labels, or guessed entity names in selected_event, candidates, target_region,
  selection_rule, keyframes, or uncertainties.
- For menu or shelf targets, describe the location with neutral geometry such
  as page/fold/side/row/column/box/relative position, not the printed item text.
- Keep the user's menu/page/region/sequence scope.
- Treat the Visual query as hard constraints when provided. Use `scenario` and
  `surface` to understand the scene, `target.kind` only to know what kind of
  visible value detail will later read, and `referent`/`scope` to localize the
  requested event or region. If natural language and Visual query conflict,
  follow the Visual query and mark uncertainty.
- For visual_query_v1, interpret fields as follows:
  `referent.type=pointing_sequence` means segment matching stable actions and
  select `referent.ordinal`; `static_region` means localize the absolute
  `referent.region`; `relative_region` means locate `referent.relation.anchor`
  then apply the relation; `object_action_state` means localize the object
  involved in `referent.action`; `composite_scene` means localize the full
  scene/region needed to identify the requested target.
- Preserve `scope.menu_instance`, `scope.menu_label`,
  `referent.ordinal`, `referent.action`, `referent.region`,
  `referent.relation`, and visible-only
  `referent.appearance` constraints. Do not use target.kind to infer a name.
- If legacy normalized slots include anchor_region and target_region_constraints,
  localize the target region by applying those constraints geometrically. For
  relative-anchor tasks, locate the anchor region first, then apply relation,
  same_fold/same_column, adjacency, and do_not_return_anchor. For small or
  supplementary regions, target the small title/card region itself, not a
  neighboring large section.
- For first/second/third/last pointing requests, first segment all distinct
  stable pointing events in the requested scope into candidates in visible time
  order. Then set selected_event to the candidate matching the requested ordinal.
- A stable pointing event starts when the endpoint settles on one target and
  ends when the endpoint leaves it or switches to another target.
- For temporal pointing events, event_time_range must be a duration covering the
  full stable pointing interval. Do not collapse it to a single keyframe or set
  start == end unless the event is truly instantaneous. keyframes are only
  sampling anchors and must not replace event_time_range.
- Every selected event/region must include 1-3 keyframes. The first keyframe is
  the primary frame that the detail reader should inspect.
  For pointing, choose the clearest contact/endpoint frame.
- For static menu/shelf/region tasks, first find when the requested
  page/fold/side/region is fully visible in context. Prefer a complete menu or
  shelf overview frame where the target region, its neighboring regions, and the
  relevant fold/page boundaries are visible together. Do not choose an earlier
  partial close-up just because the target region is partly visible there.
- For multi-fold menus, prefer a frame that shows the whole opened menu or at
  least the complete relevant fold with clear boundaries. The requested region
  must not be cropped out, clipped at the image edge, or isolated without enough
  surrounding menu context to judge relative position.
- For static menu/shelf/region keyframes, the first keyframe should be the best
  overview frame for detail reading: complete target context, least occlusion,
  least blur, stable camera, and readable target-region text. Do not prefer a
  wider overview if the requested small title/card/item becomes less readable
  than in a tighter frame. Use a local close-up when it best shows the requested
  small/supplementary target while still preserving enough neighboring context.
- For static menu/shelf/region tasks, event_time_range should be a concise
  inspection window of at most 2 seconds around the best complete overview
  frame. Use keyframes for the clearest inspection frames. Do not return a long
  stable visibility interval if only a shorter window should be sent to the
  detail reader.
- Do not select the clearest or latest event before completing this candidate
  sequence count.
- For pointing, localize the endpoint target: fingertip/contact point/tool tip/pointing direction.
- Only report events you can visually ground. Do not invent timestamps, regions, or targets from the request text.
- If the requested event is unclear, use a wider visible time range and set uncertainty; if it is not visible, set selected_event to null.
- Return seconds from the original video.
""".strip()


QWEN_EVENT_RESPONSE_SCHEMA = """
{{
  "selection_rule": "...",
  "selected_event": {{
    "event_order": 1,
    "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
    "ordinal": "first|second|third|last|null",
    "event_time_range": {{"start": 5.37, "end": 6.42}},
    "target_region": "coarse visual region without printed item text or entity names",
    "keyframes": [
      {{
        "timestamp": 6.0,
        "target_region": "same coarse visual region, without printed item text or entity names"
      }}
    ],
    "uncertainty": null
  }},
  "candidates": [
    {{
      "event_order": 1,
      "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
      "event_time_range": {{"start": 5.37, "end": 6.42}},
      "target_region": "coarse visual region without printed item text or entity names",
      "keyframes": [
        {{
          "timestamp": 6.0,
          "target_region": "coarse visual region without printed item text or entity names"
        }}
      ]
    }}
  ],
  "uncertainties": null
}}
""".strip()


QWEN_FRAME_EVENT_LOCALIZER_PROMPT = """You are a visual event localizer.

Input: sampled video frames in time order, each with frame id and timestamp.

Rules:
{common_rules}

Current user message:
{current_user_message}

Visual query:
{normalized_context}

Scene:
{image_description}

Return JSON only:
{response_schema}"""


QWEN_VIDEO_EVENT_LOCALIZER_PROMPT = """You are a visual event localizer.

Input: original video. Locate the event/region grounding the user request.

Rules:
{common_rules}

Current user message:
{current_user_message}

Visual query:
{normalized_context}

Scene:
{image_description}

Return JSON only:
{response_schema}"""


def build_qwen_event_prompt(
    current_user_message: str,
    image_description: str,
    scenario: str,
    normalized_request: dict[str, Any] | None = None,
) -> str:
    """Build the frame-sequence event-localizer prompt."""

    scene_description = build_observer_event_scene_description(scenario, image_description)
    return QWEN_FRAME_EVENT_LOCALIZER_PROMPT.format(
        common_rules=EVENT_LOCALIZER_COMMON_RULES,
        current_user_message=current_user_message,
        normalized_context=format_normalized_visual_context(normalized_request),
        image_description=scene_description,
        response_schema=QWEN_EVENT_RESPONSE_SCHEMA,
    )


def build_qwen_video_event_prompt(
    current_user_message: str,
    image_description: str,
    scenario: str,
    normalized_request: dict[str, Any] | None = None,
) -> str:
    """Build the direct-video event-localizer prompt."""

    scene_description = build_observer_event_scene_description(scenario, image_description)
    return QWEN_VIDEO_EVENT_LOCALIZER_PROMPT.format(
        common_rules=EVENT_LOCALIZER_COMMON_RULES,
        current_user_message=current_user_message,
        normalized_context=format_normalized_visual_context(normalized_request),
        image_description=scene_description,
        response_schema=QWEN_EVENT_RESPONSE_SCHEMA,
    )
