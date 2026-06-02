"""Event-stage prompt builders for the visual observer.

The event stage localizes the visible event or region that grounds the user's
current visual reference. It should not identify final entity names or answer
database questions.
"""

from __future__ import annotations

from experiments.visual_observer_runner.prompts.observer_scenario import build_observer_event_scene_description


OBSERVER_EVENT_PROMPT_VERSION = "observer_event_prompts_v8_menu_scope"


EVENT_LOCALIZER_COMMON_RULES = """
- Use only the visual input.
- Localize one requested visible event/region; do not identify final dish/product names.
- The event stage must output only timing and coarse spatial regions. Do not
  put visible dish names, product names, menu item text, category titles, OCR
  labels, or guessed entity names in selected_event, candidates, target_region,
  selection_rule, downstream_instruction, or uncertainties.
- For menu or shelf targets, describe the location with neutral geometry such
  as page/fold/side/row/column/box/relative position, not the printed item text.
- Keep the user's menu/page/region/sequence scope.
- For first/second/third/last pointing requests, first segment all distinct
  stable pointing events in the requested scope into candidates in visible time
  order. Then set selected_event to the candidate matching the requested ordinal.
- A stable pointing event starts when the endpoint settles on one target and
  ends when the endpoint leaves it or switches to another target.
- Do not select the clearest or latest event before completing this candidate
  sequence count.
- For pointing, localize the endpoint target: fingertip/contact point/tool tip/pointing direction.
- Only report events you can visually ground. Do not invent timestamps, regions, or targets from the request text.
- If the requested event is unclear, use a wider visible time range and set uncertainty; if it is not visible, set selected_event to null.
- Return seconds from the original video.
""".strip()


QWEN_EVENT_RESPONSE_SCHEMA = """
{{
  "current_visual_request": "...",
  "visual_reference_type": "temporal_ordinal_event|spatial_region|visible_text_region|object_state|single_visible_object|other",
  "selection_rule": "...",
  "selected_event": {{
    "event_order": 1,
    "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
    "ordinal": "first|second|third|last|null",
    "event_time_range": {{"start": 5.37, "end": 6.42}},
    "time_range": "5.37-6.42s",
    "anchor_timestamp": 6.0,
    "target_region": "coarse visual region without printed item text or entity names",
    "downstream_instruction": "Read the visible anchor from this localized region in the detail stage.",
    "uncertainty": null
  }},
  "candidates": [
    {{
      "event_order": 1,
      "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
      "event_time_range": {{"start": 5.37, "end": 6.42}},
      "target_region": "coarse visual region without printed item text or entity names"
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

Scene:
{image_description}

Return JSON only:
{response_schema}"""


def build_qwen_event_prompt(current_user_message: str, image_description: str, scenario: str) -> str:
    """Build the frame-sequence event-localizer prompt."""

    scene_description = build_observer_event_scene_description(scenario, image_description)
    return QWEN_FRAME_EVENT_LOCALIZER_PROMPT.format(
        common_rules=EVENT_LOCALIZER_COMMON_RULES,
        current_user_message=current_user_message,
        image_description=scene_description,
        response_schema=QWEN_EVENT_RESPONSE_SCHEMA,
    )


def build_qwen_video_event_prompt(current_user_message: str, image_description: str, scenario: str) -> str:
    """Build the direct-video event-localizer prompt."""

    scene_description = build_observer_event_scene_description(scenario, image_description)
    return QWEN_VIDEO_EVENT_LOCALIZER_PROMPT.format(
        common_rules=EVENT_LOCALIZER_COMMON_RULES,
        current_user_message=current_user_message,
        image_description=scene_description,
        response_schema=QWEN_EVENT_RESPONSE_SCHEMA,
    )
