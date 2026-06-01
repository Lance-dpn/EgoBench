"""Scenario visual guidance for observer prompts."""

from __future__ import annotations


SCENARIO_VISUAL_GUIDANCE = {
    "order": """
- The scene often contains one or more visible menu-like artifacts. User wording
  may refer to them by order, page, fold, side, section, or a user-provided name.
- Preserve user-provided ordering cues: if the user refers to the first/second
  menu-like artifact or a named choice, resolve visual references inside that
  scoped artifact unless the current request changes scope.
- For ordinal pointing requests, use the chronological order of distinct
  pointing actions within the requested scope. A new stable target is a new
  event; do not choose a later clearer target if the requested ordinal points to
  an earlier stable target.
- For pointing, localize the endpoint target, such as the fingertip/contact
  point or pointing direction, not the area covered by the middle of the hand or
  pointer.
- For section/title requests, localize the requested visible region itself. Do
  not jump to a different larger or clearer region only because it is easier to
  read.
""",
    "retail": """
- The scene often contains shelves, packages, labels, rows, columns, adjacent
  products, and visible package regions.
- For pointing or spatial references, use shelf layout and adjacency. Preserve
  left/right/top/bottom/front/back wording and ordinal references within the
  scoped shelf or product group.
- Treat package text as visual evidence that may be partially occluded, blurred,
  or noisy. Identify only the visible anchor requested by the current visual
  reference.
""",
    "restaurant": """
- The scene may contain menus, signs, table items, counters, seating, and visible
  service areas.
- For visible menu/table/scene references, preserve spatial wording and the
  currently scoped region. Do not infer business facts from appearance.
- For pointed or selected visible items, localize the visible target involved in
  the interaction before attempting to read its identity.
""",
    "kitchen": """
- The scene may contain ingredients, utensils, containers, appliances, work
  surfaces, and visible preparation states.
- For pointing or spatial references, preserve object location and relation to
  nearby containers, tools, or appliances.
- For visible state requests, identify the visible state of the localized target
  only; do not infer recipe facts or quantities from appearance alone.
""",
}


def build_observer_scene_description(scenario: str, image_description: str) -> str:
    """Combine task scene text with scenario-level visual guidance."""

    parts = []
    if image_description and image_description.strip():
        parts.append("Scene note:\n" + image_description.strip())
    scenario_key = (scenario or "").strip().lower()
    guidance = SCENARIO_VISUAL_GUIDANCE.get(scenario_key)
    if guidance:
        parts.append("Scenario visual guidance:\n" + guidance.strip())
    return "\n\n".join(parts) if parts else "N/A"
