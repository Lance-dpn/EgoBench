"""Detail-stage prompt builder for the visual observer.

The detail stage reads the localized frame sequence and identifies one visible
anchor. It should not answer database questions or promote background text into
the primary visual key/value.
"""

from __future__ import annotations

from typing import Any

from experiments.visual_observer_runner.prompts.observer_scenario import build_observer_detail_scene_description


OBSERVER_DETAIL_PROMPT_VERSION = "observer_detail_prompts_v4_scope_key_type"


QWEN_SEQUENCE_DETAIL_PROMPT = """You are a vision reader for one localized event.

Current user request:
{current_user_message}

Scene:
{image_description}

The attached frames are ordered and come from the localized event. Use the
localized time range and region only; do not trust any entity name, dish name,
product name, category title, OCR text, or label that appears in the event
summary. Identify the anchor directly from the visible endpoint/contact point in
the frames.

Localized event summary:
- referent: {user_referent}
- event type: {event_type}
- selected event order: {selected_event_order}
- time range: {time_range}
- target region: {target_region}
- instruction: {downstream_instruction}

Your job:
- Identify the single visible anchor at the localized target.
- For pointing, use the endpoint/contact point/pointing direction, not the hand body.
- Use the whole frame sequence to handle motion, blur, occlusion, and readable text.
- If localizer text conflicts with the visible endpoint, trust the visible endpoint.
- Never copy an entity name from target_region or downstream_instruction unless
  the same text is visibly anchored at the endpoint in the attached frames.

Boundaries:
- Use only visible evidence. Do not answer database facts, rankings, calculations, or actions.
- Return exactly one primary visual_key_values item, or an empty list if unclear.
- Put neighboring/background readable text in visible_text only.

Return JSON only:
{{
  "target_identity": "... or null",
  "visible_text": [],
  "visual_key_values": [
    {{
      "key": "product_name|dish_name|ingredient_name|recipe_name|category|set_meal_name|visible_region",
      "value": "... or null",
      "confidence": "high|medium|low",
      "evidence": "which frame(s), visible text, action/order cues, region, color, shape, or spatial relation"
    }}
  ],
  "spatial_evidence": "...",
  "uncertainty": null
}}"""


def _build_downstream_instruction(referent: dict[str, Any]) -> str:
    if referent.get("downstream_instruction"):
        return str(referent["downstream_instruction"])
    referent_text = referent.get("user_referent") or "the localized visual referent"
    return f"These frames show {referent_text}. Identify the specific visible anchor involved in this event."


def build_qwen_sequence_prompt(
    referent: dict[str, Any],
    current_user_message: str,
    image_description: str,
    scenario: str,
) -> str:
    """Build the frame-sequence detail-reader prompt."""

    scene_description = build_observer_detail_scene_description(scenario, image_description)
    event_range = referent.get("event_time_range") or {}
    if isinstance(event_range, dict) and (event_range.get("start") is not None or event_range.get("end") is not None):
        time_range = f"{event_range.get('start')}s-{event_range.get('end')}s"
    else:
        time_range = referent.get("time_range")
    return QWEN_SEQUENCE_DETAIL_PROMPT.format(
        current_user_message=current_user_message,
        image_description=scene_description,
        user_referent=referent.get("user_referent"),
        event_type=referent.get("event_type"),
        selected_event_order=referent.get("selected_event_order") or "N/A",
        time_range=time_range,
        target_region=referent.get("target_region"),
        downstream_instruction=_build_downstream_instruction(referent),
    )
