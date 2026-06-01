"""Event-stage prompt builders for the visual observer.

The event stage localizes the visible event or region that grounds the user's
current visual reference. It should not identify final entity names or answer
database questions.
"""

from __future__ import annotations

from experiments.visual_observer_runner.prompts.observer_scenario import build_observer_scene_description


OBSERVER_EVENT_PROMPT_VERSION = "observer_event_prompts_v2"


EVENT_LOCALIZER_COMMON_RULES = """
- Use only the provided visual input and timestamps, not outside knowledge.
- Resolve visual grounding only: timing, action order, selected target, spatial
  relation, visible region, object state, or text region to inspect.
- Keep the current user request as the scope. If the request names a page,
  region, sequence, selected option, or ordered reference, localize only inside
  that scope.
- For ordinal or temporal references, enumerate distinct candidate events in
  visible order, then select the requested one. A new stable target or state is
  a new candidate event.
- For pointing or interaction, localize the endpoint target: fingertip, contact
  point, cursor/tool tip, or pointing direction.
- For spatial or text-region references, select the region matching the user's
  spatial wording, not merely the largest or clearest region.
- Do not output final entity names, database facts, persistent state, ranked or
  conditional decisions, recommendations, or actions to take.
- Use coarse target_region wording. The detail-stage reader will identify the
  final visible anchor.
- Return exactly one selected referent for the current observer request.
- Timestamps must be seconds from the start of the original video and may be
  decimal values.
""".strip()


QWEN_EVENT_RESPONSE_SCHEMA = """
{{
  "current_visual_request": "...",
  "visual_reference_type": "temporal_ordinal_event|spatial_region|visible_text_region|object_state|single_visible_object|other",
  "selection_rule": "How the single selected target was chosen from the user request.",
  "candidate_events": [
    {{
      "event_order": 1,
      "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
      "time_range": "5.37-6.42s",
      "event_time_range": {{"start": 5.37, "end": 6.42}},
      "anchor_timestamp": 6.0,
      "target_region": "coarse region in the frame",
      "boundary_reason": "why this is one distinct candidate event or region"
    }}
  ],
  "selected_event_order": 1,
  "referents": [
    {{
      "referent": "...",
      "request_order": 1,
      "event_type": "pointing|holding|menu_region|object_state|spatial_region|other",
      "ordinal": "first|second|third|last|null",
      "event_time_range": {{"start": 5.37, "end": 6.42}},
      "time_range": "5.37-6.42s",
      "target_region": "coarse region in the frame",
      "detail_needed": ["identify anchor"],
      "downstream_instruction": "Identify the visible anchor for this localized referent.",
      "best_keyframes": [
        {{
          "frame_id": "F012",
          "timestamp": 6.0,
          "target_region": "coarse region in the frame",
          "reason": "short visual reason"
        }}
      ],
      "uncertainty": null
    }}
  ],
  "uncertainties": null
}}
""".strip()


QWEN_FRAME_EVENT_LOCALIZER_PROMPT = """You are the first-stage event localizer in a two-model visual observer.

Task:
Given the current user message and a sequence of sampled video frames, locate
the visual event that grounds the user's request. The attached images are
ordered from early to late. Each image is preceded by a frame id and timestamp.

Rules:
{common_rules}

Current user message:
{current_user_message}

Scene description:
{image_description}

Return JSON only:
{response_schema}"""


QWEN_VIDEO_EVENT_LOCALIZER_PROMPT = """You are the first-stage event localizer in a two-model visual observer.

Task:
Given the current user message and the original video, locate the visual event
that grounds the user's request. The video is provided directly; do not assume
any externally controlled frame rate.

Rules:
{common_rules}

Current user message:
{current_user_message}

Scene description:
{image_description}

Return JSON only:
{response_schema}"""


def build_qwen_event_prompt(current_user_message: str, image_description: str, scenario: str) -> str:
    """Build the frame-sequence event-localizer prompt."""

    scene_description = build_observer_scene_description(scenario, image_description)
    return QWEN_FRAME_EVENT_LOCALIZER_PROMPT.format(
        common_rules=EVENT_LOCALIZER_COMMON_RULES,
        current_user_message=current_user_message,
        image_description=scene_description,
        response_schema=QWEN_EVENT_RESPONSE_SCHEMA,
    )


def build_qwen_video_event_prompt(current_user_message: str, image_description: str, scenario: str) -> str:
    """Build the direct-video event-localizer prompt."""

    scene_description = build_observer_scene_description(scenario, image_description)
    return QWEN_VIDEO_EVENT_LOCALIZER_PROMPT.format(
        common_rules=EVENT_LOCALIZER_COMMON_RULES,
        current_user_message=current_user_message,
        image_description=scene_description,
        response_schema=QWEN_EVENT_RESPONSE_SCHEMA,
    )
