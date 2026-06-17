"""Detail-stage prompt builder for the visual observer.

The detail stage reads the localized frame sequence and identifies one visible
anchor. It should not answer database questions or promote background text into
the primary visual key/value.
"""

from __future__ import annotations

from typing import Any

from experiments.visual_observer_runner.prompts.observer_scenario import (
    build_observer_detail_scene_description,
    format_normalized_visual_context,
)


OBSERVER_DETAIL_PROMPT_VERSION = "observer_detail_prompts_v7_visual_query"


QWEN_SEQUENCE_DETAIL_PROMPT = """You are a vision reader for one localized event.

Current user request:
{current_user_message}

Scene:
{image_description}

Visual query:
{normalized_context}

The attached frames are ordered and are sampled around the event key frame.
Use the localized time range and region only; do not trust any entity name,
dish name, product name, category title, OCR text, or label that appears in the
event summary. Identify the anchor directly from the visible endpoint/contact
point or localized region in the frames.

Localized event summary:
- referent: {user_referent}
- event type: {event_type}
- selected event: {selected_event_summary}
- event_time_range: {time_range}
- target region: {target_region}

Your job:
- First identify the target region from the Visual query and localized
  event summary, then identify the single visible anchor inside that region.
- Treat the Visual query as hard constraints when provided. Use `target.kind`
  as the key to return, `target.selection_unit` as the visual unit to read, and
  `referent`/`scope` to reject text or objects from the wrong region, action,
  relation, menu, shelf, table, or kitchen container.
- For visual_query_v1, read exactly one value matching `target.kind` from the
  region/event selected by event. Do not answer price, tax, nutrition, allergen,
  stock, ranking, recipe quantity, or other database/business facts.
- For pointing_sequence, event has already selected the intended event. Do not
  use `referent.ordinal` as a row-counting instruction in the attached frames;
  inspect the selected fingertip/contact point only.
- If legacy normalized slots include target_region_constraints, use them as the
  primary spatial contract. Enforce relation, same_fold, same_column,
  adjacency, region_size, region_role, and avoid_region_role before reading
  text.
- If legacy normalized slots include anchor_region, locate that anchor geometrically
  first, then apply the requested relation from anchor to target. Do not return
  the anchor itself when do_not_return_anchor is true.
- If slots specify a small/supplementary/bottommost/positioned-card region, do not
  choose a larger or more prominent neighboring section.
- If target_region_constraints specify region_size=small_supplementary or
  region_role=small_supplementary_title, return the title inside that small
  supplementary region. Do not return the larger main category directly above
  it, even when that larger title is clearer or more visually prominent.
- If slots specify a fold/page/side/relative relation, reject visible text from
  a different fold/page/side/relation even if it is clearer.
- For relative-anchor requests, locate the anchor region first, apply the
  relation geometrically, and do not return the anchor itself unless the
  relation explicitly asks for it.
- For relative-anchor requests with adjacency=direct, choose the first distinct
  titled region immediately adjacent to the anchor in the requested direction.
  Do not skip over that region to a farther title.
- For pointing, use the endpoint/contact point/pointing direction, not the hand
  body. Prefer the frame where the endpoint is most settled on one row/item;
  use adjacent frames only to disambiguate motion and occlusion.
- For pointing, the event stage has already selected the intended event. Do not
  treat upstream event-selection wording as a menu row number, item position,
  or counting instruction inside the attached frames.
- If legacy normalized slots include pointing_resolution, follow it exactly: locate
  the fingertip/contact point, project it to the nearest menu text row, compare
  adjacent candidate rows by distance to the endpoint, and do not choose by row
  count guess, hand-body overlap, or most salient/readable text.
- Use the short frame sequence to handle motion, blur, occlusion, and readable text.
- If localizer text conflicts with the visible endpoint, trust the visible endpoint.
- Never copy an entity name from the localized event summary unless the same
  text is visibly anchored at the endpoint in the attached frames.

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


def _is_pointing_referent(referent: dict[str, Any], normalized_request: dict[str, Any] | None) -> bool:
    event_type = str(referent.get("event_type") or "").lower()
    if "point" in event_type:
        return True
    query_referent = (normalized_request or {}).get("referent")
    if isinstance(query_referent, dict):
        referent_type = str(query_referent.get("type") or "").lower()
        action = str(query_referent.get("action") or "").lower()
        if "point" in referent_type or action == "pointing":
            return True
    task_type = str((normalized_request or {}).get("task_type") or "").lower()
    if "point" in task_type:
        return True
    slots = (normalized_request or {}).get("slots")
    return isinstance(slots, dict) and str(slots.get("action") or "").lower() == "pointing"


def _detail_current_user_message(
    referent: dict[str, Any],
    current_user_message: str,
    normalized_request: dict[str, Any] | None,
) -> str:
    if _is_pointing_referent(referent, normalized_request):
        return (
            "Read the visible target at the fingertip/contact point in the selected "
            "pointing event. The event order was resolved upstream."
        )
    return current_user_message


def _detail_normalized_request(
    referent: dict[str, Any],
    normalized_request: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not _is_pointing_referent(referent, normalized_request) or not isinstance(normalized_request, dict):
        return normalized_request
    cleaned = dict(normalized_request)
    query_referent = cleaned.get("referent")
    if isinstance(query_referent, dict):
        next_referent = dict(query_referent)
        next_referent["type"] = "selected_pointing_event"
        next_referent.pop("ordinal", None)
        cleaned["referent"] = next_referent
    slots = dict(cleaned.get("slots") or {})
    for key in ("ordinal", "sequence_scope"):
        slots.pop(key, None)
    slots["event_selection"] = "already_selected_upstream"
    cleaned["slots"] = slots
    if "task_type" in cleaned:
        cleaned["task_type"] = "selected_pointing_event"
    return cleaned


def _selected_event_summary(referent: dict[str, Any], normalized_request: dict[str, Any] | None) -> str:
    if _is_pointing_referent(referent, normalized_request):
        return "already selected upstream; inspect the fingertip/contact point only"
    return str(referent.get("selected_event_order") or "N/A")


def build_qwen_sequence_prompt(
    referent: dict[str, Any],
    current_user_message: str,
    image_description: str,
    scenario: str,
    normalized_request: dict[str, Any] | None = None,
) -> str:
    """Build the frame-sequence detail-reader prompt."""

    scene_description = build_observer_detail_scene_description(scenario, image_description)
    event_range = referent.get("event_time_range") or {}
    if isinstance(event_range, dict) and (event_range.get("start") is not None or event_range.get("end") is not None):
        time_range = f"{event_range.get('start')}s-{event_range.get('end')}s"
    else:
        time_range = None
    detail_normalized_request = _detail_normalized_request(referent, normalized_request)
    return QWEN_SEQUENCE_DETAIL_PROMPT.format(
        current_user_message=_detail_current_user_message(referent, current_user_message, normalized_request),
        image_description=scene_description,
        normalized_context=format_normalized_visual_context(detail_normalized_request),
        user_referent=referent.get("user_referent"),
        event_type=referent.get("event_type"),
        selected_event_summary=_selected_event_summary(referent, normalized_request),
        time_range=time_range,
        target_region=referent.get("target_region"),
    )
