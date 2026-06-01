"""Compact scenario visual guidance for observer prompts."""

from __future__ import annotations


EVENT_SCENARIO_VISUAL_GUIDANCE = {
    "order": """
- Menus may be referenced as Menu 1/Menu 2, page, fold, side, or section.
- For ordinal pointing, count distinct stable pointing targets in time order
  within the requested menu/region.
- Localize the fingertip/contact point or pointing direction, not the hand body.
""",
    "retail": """
- Use shelf layout, rows/columns, adjacency, and package regions.
- Preserve left/right/top/bottom/front/back and ordinal wording within scope.
""",
    "restaurant": """
- Preserve spatial wording for menus, signs, table items, counters, or seating.
- For selected items, localize the visible interaction target first.
""",
    "kitchen": """
- Preserve object location and relation to containers, tools, or appliances.
- For visible state requests, localize the target state only.
""",
}


DETAIL_SCENARIO_VISUAL_GUIDANCE = {
    "order": """
- Read the localized menu target only; use visible text near that target.
- Do not use restaurant logos or headers as dish/category identity unless they
  are the localized target.
""",
    "retail": """
- Read the localized product/package/label only.
- Treat nearby shelf text as context, not the primary product, unless localized.
""",
    "restaurant": """
- Read only the localized menu/table/sign/item target.
- Do not infer service or business facts from appearance.
""",
    "kitchen": """
- Identify only the localized ingredient, tool, container, appliance, or state.
- Do not infer recipe facts or quantities from appearance.
""",
}


def build_observer_scene_description(
    scenario: str,
    image_description: str,
    *,
    stage: str = "event",
) -> str:
    """Combine task scene text with compact stage-specific visual guidance."""

    parts = []
    if image_description and image_description.strip():
        parts.append("Scene note:\n" + image_description.strip())
    scenario_key = (scenario or "").strip().lower()
    if stage == "detail":
        guidance = DETAIL_SCENARIO_VISUAL_GUIDANCE.get(scenario_key)
    else:
        guidance = EVENT_SCENARIO_VISUAL_GUIDANCE.get(scenario_key)
    if guidance:
        parts.append("Scenario guidance:\n" + guidance.strip())
    return "\n\n".join(parts) if parts else "N/A"


def build_observer_event_scene_description(scenario: str, image_description: str) -> str:
    return build_observer_scene_description(scenario, image_description, stage="event")


def build_observer_detail_scene_description(scenario: str, image_description: str) -> str:
    return build_observer_scene_description(scenario, image_description, stage="detail")


# Backward-compatible name for older imports.
SCENARIO_VISUAL_GUIDANCE = EVENT_SCENARIO_VISUAL_GUIDANCE
