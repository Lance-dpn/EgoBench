"""Event-stage prompt builders for the visual observer.

The event stage localizes the visible event or region that grounds the user's
current visual reference. It should not identify final entity names or answer
database questions.
"""

from __future__ import annotations

from experiments.visual_observer_runner.prompts.observer_scenario import build_observer_event_scene_description


OBSERVER_EVENT_PROMPT_VERSION = "observer_event_prompts_v3_compact"


EVENT_LOCALIZER_COMMON_RULES = """
- Use only the visual input.
- Localize one requested visible event/region; do not identify final dish/product names.
- Keep the user's menu/page/region/sequence scope.
- For ordinal requests, list distinct candidate events in visible time order and select the requested one.
- For pointing, localize the endpoint target: fingertip/contact point/tool tip/pointing direction.
- Return seconds from the original video.
""".strip()


QWEN_EVENT_RESPONSE_SCHEMA = """
{{
  "current_visual_request": "...",
  "visual_reference_type": "temporal_ordinal_event|spatial_region|visible_text_region|object_state|single_visible_object|other",
  "selection_rule": "...",
  "candidate_events": [
    {{
      "event_order": 1,
      "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
      "time_range": "5.37-6.42s",
      "event_time_range": {{"start": 5.37, "end": 6.42}},
      "anchor_timestamp": 6.0,
      "target_region": "coarse visual region"
    }}
  ],
  "selected_event_order": 1,
  "referents": [
    {{
      "referent": "user's requested visible target",
      "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
      "ordinal": "first|second|third|last|null",
      "event_time_range": {{"start": 5.37, "end": 6.42}},
      "time_range": "5.37-6.42s",
      "target_region": "coarse visual region",
      "detail_needed": ["identify anchor"],
      "downstream_instruction": "Identify the visible anchor at this localized target.",
      "best_keyframes": [
        {{
          "frame_id": "F012",
          "timestamp": 6.0
        }}
      ],
      "uncertainty": null
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
