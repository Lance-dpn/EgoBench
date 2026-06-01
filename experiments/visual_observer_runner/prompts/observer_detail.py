"""Detail-stage prompt builder for the visual observer.

The detail stage reads the localized frame sequence and identifies one visible
anchor. It should not answer database questions or promote background text into
the primary visual key/value.
"""

from __future__ import annotations

from typing import Any

from experiments.visual_observer_runner.prompts.observer_scenario import build_observer_scene_description


OBSERVER_DETAIL_PROMPT_VERSION = "observer_detail_prompts_v1"


QWEN_SEQUENCE_DETAIL_PROMPT = """You are the second-stage vision reader in a two-model visual observer.

Current user request:
{current_user_message}

Scene description:
{image_description}

The first-stage localizer has already localized the relevant video event. The attached images are
ordered from early to late and come from this event segment.

Localized event summary:
- referent: {user_referent}
- event type: {event_type}
- selected event order: {selected_event_order}
- selection rule: {selection_rule}
- time range: {time_range}
- target region: {target_region}
- sampling anchor timestamp: {anchor_timestamp}
- instruction: {downstream_instruction}

Your job:
Use the ordered image sequence to identify the single most likely visible anchor
requested by the localizer. Trust the event timing and do not reinterpret which
occurrence or spatial relation is intended unless the image sequence itself is
ambiguous.
Treat the first-stage referent and target region as localization hints, not as
the final identity. If the localizer includes a possible object name or text
value, verify it visually and ignore it if the pointing endpoint or image
evidence supports a different visible anchor.
The sampling anchor timestamp only explains how these frames were selected. It
is not a guarantee that the nearest frame contains the final target identity.
Use the entire ordered sequence inside the localized event to identify the
visible anchor. Use earlier and later frames to resolve motion, occlusion, blur,
and readable text; do not let the anchor frame override stronger evidence from
the sequence.
For pointing actions, identify the target at the pointing endpoint: fingertip,
contact point, cursor tip, tool tip, or extension of the pointing direction.
Do not choose text or objects covered by the middle/lower part of the pointer
body unless the endpoint supports that choice. If the pointer overlaps adjacent
rows or objects, choose the visible anchor nearest the endpoint and pointing
direction.
Combine evidence across all attached frames before deciding. The target text or
object may be occluded, blurred, cropped, or unreadable in a single frame; track
the same localized target through the sequence and use the clearest frame(s) for
the final identity.

Boundaries:
- Use only visible text and visual evidence in these images.
- Focus on the target region and the object/person/state involved in the
  localized event.
- Choose one best target_identity. Do not output top-k alternatives.
- visual_key_values must contain exactly one item for the primary visible anchor
  of this localized referent.
- Put other readable text in visible_text only. Do not promote neighboring or
  background anchors into visual_key_values.
- Do not output database facts, persistent state, rankings, calculations,
  recommendations, or actions as key/value pairs.
- Ignore database-only filters, rankings, calculations, state checks, and
  recommendations in the request. Identify only the visible anchor localized by
  the first stage.
- If the target cannot be identified, set target_identity to null, return an
  empty visual_key_values list, and explain the ambiguity in uncertainty.

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


def _first_keyframe_timestamp(referent: dict[str, Any]) -> float | None:
    for keyframe in referent.get("keyframes", []):
        if isinstance(keyframe, dict) and keyframe.get("timestamp") is not None:
            return float(keyframe["timestamp"])
    return None


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

    scene_description = build_observer_scene_description(scenario, image_description)
    event_range = referent.get("event_time_range") or {}
    if isinstance(event_range, dict) and (event_range.get("start") is not None or event_range.get("end") is not None):
        time_range = f"{event_range.get('start')}s-{event_range.get('end')}s"
    else:
        time_range = referent.get("time_range")
    anchor_timestamp = _first_keyframe_timestamp(referent)
    return QWEN_SEQUENCE_DETAIL_PROMPT.format(
        current_user_message=current_user_message,
        image_description=scene_description,
        user_referent=referent.get("user_referent"),
        event_type=referent.get("event_type"),
        selected_event_order=referent.get("selected_event_order") or "N/A",
        selection_rule=referent.get("selection_rule") or "N/A",
        time_range=time_range,
        target_region=referent.get("target_region"),
        anchor_timestamp=anchor_timestamp if anchor_timestamp is not None else "N/A",
        downstream_instruction=_build_downstream_instruction(referent),
    )
