#!/usr/bin/env python3
"""Build generic observer-evaluation assets for EgoBench scenarios.

The generic builder creates the same evaluation-facing shape used by the
order1 observer GT file. For non-order scenarios this is an instruction-level
bootstrap: visual problems are grouped by the normalized visual referent inside
the same video. Scenario-level values are used only as weak detail candidates,
never as grouping keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CURRENT_FILE = Path(__file__).resolve()
PROJECT_ROOT = CURRENT_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.visual_observer_runner.visual_request_normalizer import (  # noqa: E402
    normalize_space,
    normalize_visual_requests,
)


SCENARIOS_DIR = PROJECT_ROOT / "scenarios" / "final"
DEFAULT_OUTPUT_ROOT = CURRENT_FILE.parent / "eval"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def scenario_paths(args: argparse.Namespace) -> list[Path]:
    if args.scenario_key:
        return [SCENARIOS_DIR / f"{args.scenario_key}.json"]
    if args.scenario:
        return sorted(SCENARIOS_DIR.glob(f"{args.scenario}*.json"))
    return sorted(SCENARIOS_DIR.glob("*.json"))


def scenario_prefix(scenario_key: str) -> str:
    return re.sub(r"\d+$", "", scenario_key)


def stable_id(prefix: str, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]}"


def norm_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "unknown"


def readable_id(*parts: Any, max_len: int = 120) -> str:
    base = "_".join(part for part in (norm_id(part) for part in parts) if part)
    if len(base) <= max_len:
        return base
    suffix = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return f"{base[: max_len - len(suffix) - 1].rstrip('_')}_{suffix}"


def video_stem(request: dict[str, Any]) -> str:
    return Path(str(request.get("image_path") or "video")).stem


def compact_constraint_terms(request: dict[str, Any]) -> list[str]:
    spatial = request.get("spatial_scope") or {}
    terms: list[str] = []
    terms.extend(spatial.get("region_terms") or [])
    terms.extend(spatial.get("relative_terms") or [])
    terms.extend(request.get("appearance_constraints") or [])
    text_constraints = request.get("visible_text_constraints") or []
    terms.extend(f"text_{item}" for item in text_constraints)
    return terms


BUSINESS_QUERY_PATTERN = re.compile(
    r"\b("
    r"price|unit price|tax rate|tax|discount|protein|calor(?:y|ies)|nutrition(?:al)?"
    r"|nutrition facts table|allergen(?:s| list)?|dietary fiber|sodium|fat|carbohydrates?"
    r"|flavo(?:u)?r(?: description)?|iron|calcium|inventory|stock|expiration date"
    r"|shelf life|storage|serving size|cooking steps?|total number"
    r")\b",
    re.IGNORECASE,
)

VISUAL_FRAGMENT_PATTERNS = [
    re.compile(
        r"\b(?:dish|item|menu item|food)\s+"
        r"(?:located|positioned|on|at|in|among|that|which|you|being|containing|with)"
        r"[^.;]{0,180}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:category|section|card|area|region)\s+"
        r"(?:located|directly|immediately|on|at|in|with|where|containing|that|which|you|this)"
        r"[^.;]{0,200}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ingredient|powder|meat|vegetable|recipe|dish)\s+"
        r"(?:being|you are|that|which|composed|consists|corresponds|placed|located|on|at|in|from|remaining)"
        r"[^.;]{0,200}",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:two|three|all|chunky|green|yellow|baked|cooked|fried|stir-fried)"
        r"[^.;]{0,160}\b(?:ingredient|ingredients|vegetable|vegetables|powder|dish|recipe|pot|tray|cutting board|wok)\b"
        r"[^.;]{0,120}",
        re.IGNORECASE,
    ),
]

VISUAL_FRAGMENT_STOP_PATTERN = re.compile(
    r"\b("
    r"ask|have|instruct|then|next|subsequently|otherwise|if|whether|determine|check|query"
    r"|select|filter|find|add|remove|calculate|compute|priced|price|with the highest"
    r"|with the lowest|among those|from those|for this|of this|and add|and have"
    r")\b",
    re.IGNORECASE,
)


def normalize_visual_fragment(value: str) -> str:
    text = value.lower()
    text = re.sub(r"\b(ai|service|agent|please|ask|have|instruct|to)\b", " ", text)
    text = BUSINESS_QUERY_PATTERN.sub(" ", text)
    text = re.sub(r"\b(user id|today is|customer_\d+|cook_\d+)\b", " ", text)
    replacements = [
        (r"\b(furthest|farthest|far)\s+to\s+the\s+right\s+and\s+highest(?:\s+up|\s+position)?\b", "top right"),
        (r"\bfar\s+right\s+and\s+highest(?:\s+position)?\b", "top right"),
        (r"\b(topmost|highest)\b", "top"),
        (r"\b(furthest|farthest|far)\s+left\b", "leftmost"),
        (r"\b(furthest|farthest|far)\s+right\b", "rightmost"),
        (r"\bleft\s*-\s*hand\b", "left"),
        (r"\bright\s*-\s*hand\b", "right"),
        (r"\bpointed\s+at\b", "pointed"),
        (r"\byou\s+are\s+pointing\s+at\b", "pointed"),
        (r"\byou\s+pointed\s+at\b", "pointed"),
        (r"\byou\s+pointed\b", "pointed"),
        (r"\bcontains?\s+fresh\s+fruit(?:\s+ingredients)?\b", "contains fresh fruit"),
        (r"\bsmall\s+hand\s+illustration\b", "small hand illustration"),
        (r"\bdark\s+background\s+with\s+white\s+text\b", "dark background white text"),
        (r"\bwhite\s+rounded(?:-corner)?\s+(?:small\s+)?card\b", "white rounded card"),
        (r"\bblue\s+cutting\s+board\b", "blue cutting board"),
        (r"\bbaking\s+tray\b", "baking tray"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[^a-z0-9&'+/ -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_visual_fragment(text: str) -> str:
    normalized = normalize_space(text)
    matches: list[str] = []
    for pattern in VISUAL_FRAGMENT_PATTERNS:
        for match in pattern.finditer(normalized):
            fragment = normalize_space(match.group(0))
            stop = VISUAL_FRAGMENT_STOP_PATTERN.search(fragment, 1)
            if stop:
                fragment = fragment[: stop.start()]
            fragment = normalize_visual_fragment(fragment)
            if fragment and fragment not in matches:
                matches.append(fragment)
    if matches:
        return " + ".join(matches[:3])
    return normalize_visual_fragment(normalized[:220])


def visual_referent_signature(request: dict[str, Any]) -> str:
    """Instruction-derived visual referent used for same-video clustering."""

    fragment = extract_visual_fragment(request.get("review_source_instruction_snippet") or "")
    parts = [
        request.get("event_mode"),
        request.get("detail_mode"),
        f"target={request.get('target_key')}",
    ]
    if request.get("action"):
        parts.append(f"action={request['action']}")
    if request.get("ordinal"):
        parts.append(f"ordinal={request['ordinal']}")
    if fragment:
        parts.append(f"referent={fragment}")
    return "|".join(str(part) for part in parts if part)


def event_gt_id_for_request(request: dict[str, Any], canonical_value: str | None) -> str:
    video = video_stem(request)
    event_mode = request["event_mode"]
    action = request.get("action")
    ordinal = request.get("ordinal")
    target_key = request.get("target_key")
    constraints = compact_constraint_terms(request)

    if event_mode == "temporal_sequence_event":
        return readable_id(video, action or "event", ordinal or "unspecified")
    if event_mode == "single_pointing_event":
        return readable_id(video, action or "pointing", *(constraints or [target_key]))
    if event_mode == "static_spatial_region":
        if constraints:
            return readable_id(video, "static", *constraints, target_key)
        if canonical_value:
            return readable_id(video, "static", canonical_value)
        return readable_id(video, "static", target_key)
    if event_mode == "relative_spatial_region":
        return readable_id(video, "relative", *(constraints or [target_key]))
    if event_mode == "object_action_state":
        return readable_id(video, action or "action", *(constraints or [target_key]))
    if event_mode == "composite_scene_context":
        return readable_id(video, "scene", *(constraints or [target_key]))
    return readable_id(video, event_mode, *(constraints or [target_key]))


DETAIL_ID_PREFIX_BY_KIND = {
    "product": "product",
    "menu_item": "dish",
    "dish_name": "dish",
    "category_or_section": "category",
    "menu_catalog_or_category": "category",
    "ingredient": "ingredient",
    "recipe": "recipe",
    "set_meal": "set_meal",
    "visible_anchor": "visible",
}


def detail_gt_id_for_request(
    request: dict[str, Any],
    canonical_value: str | None,
    alternatives: list[str],
    label: str,
) -> str:
    prefix = DETAIL_ID_PREFIX_BY_KIND.get(str(request.get("target_kind")), norm_id(request.get("target_kind")))
    if canonical_value and canonical_value != "UNKNOWN":
        return readable_id(prefix, canonical_value)
    if len(alternatives) == 1:
        return readable_id(prefix, alternatives[0])
    return readable_id(video_stem(request), "detail", request.get("target_key"), label)


def normalized_problem_payload(request: dict[str, Any]) -> dict[str, Any]:
    observer_task = dict(request["observer_task"])
    observer_task.pop("request_id", None)
    return {
        "video_path": request.get("image_path"),
        "event_mode": request["event_mode"],
        "detail_mode": request["detail_mode"],
        "target_key": request["target_key"],
        "target_kind": request["target_kind"],
        "action": request.get("action"),
        "ordinal": request.get("ordinal"),
        "sequence_scope": request.get("sequence_scope"),
        "spatial_scope": request.get("spatial_scope") or {},
        "appearance_constraints": request.get("appearance_constraints") or [],
        "visible_text_constraints": request.get("visible_text_constraints") or [],
        "visual_referent_signature": visual_referent_signature(request),
        "observer_task": observer_task,
    }


def visual_problem_key(request: dict[str, Any]) -> str:
    return stable_id("visual_problem", normalized_problem_payload(request))


def task_lookup_key(request: dict[str, Any]) -> tuple[str, int]:
    return (request["scenario_key"], int(request["task_id"]))


def target_values_for_requests(
    requests: list[dict[str, Any]],
    tasks_by_id: dict[tuple[str, int], dict[str, Any]],
) -> tuple[str | None, list[str], str]:
    values: list[str] = []
    for request in requests:
        task_value = tasks_by_id[task_lookup_key(request)].get("value")
        if isinstance(task_value, list):
            values.extend(str(item) for item in task_value if item not in (None, ""))
        elif task_value not in (None, ""):
            values.append(str(task_value))
    values = list(dict.fromkeys(values))
    if len(values) == 1:
        return values[0], [], "medium"
    if values:
        return None, values, "low"
    return None, [], "low"


def label_for_request(request: dict[str, Any]) -> str:
    pieces: list[str] = []
    if request.get("ordinal"):
        pieces.append(str(request["ordinal"]))
    if request.get("action"):
        pieces.append(str(request["action"]))
    pieces.append(str(request["target_key"]))
    spatial = request.get("spatial_scope") or {}
    region_terms = spatial.get("region_terms") or []
    if region_terms:
        pieces.append("region=" + "+".join(region_terms))
    relative_terms = spatial.get("relative_terms") or []
    if relative_terms:
        pieces.append("relative=" + "+".join(relative_terms))
    appearance = request.get("appearance_constraints") or []
    if appearance:
        pieces.append("appearance=" + "+".join(appearance))
    referent = extract_visual_fragment(request.get("review_source_instruction_snippet") or "")
    if referent:
        pieces.append("referent=" + referent)
    return " | ".join(pieces)


def observer_input_for_case(case_id: str, request: dict[str, Any], label: str) -> dict[str, Any]:
    return {
        "schema_version": "observer_input_v1",
        "problem_id": case_id,
        "video_path": request.get("image_path"),
        "menu_label": None,
        "task_type": request["event_mode"],
        "target_kind": request["target_kind"],
        "slots": {
            "visual_problem_label": label,
            "visual_referent_signature": visual_referent_signature(request),
            "action": request.get("action"),
            "ordinal": request.get("ordinal"),
            "sequence_scope": request.get("sequence_scope"),
            "spatial_scope": request.get("spatial_scope") or {},
            "appearance_constraints": request.get("appearance_constraints") or [],
            "visible_text_constraints": request.get("visible_text_constraints") or [],
            "target_key": request["target_key"],
            "detail_goal": request.get("detail_goal"),
        },
    }


def visual_problem_key_for_observer_input(observer_input: dict[str, Any]) -> str:
    payload = dict(observer_input)
    payload.pop("schema_version", None)
    payload.pop("problem_id", None)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_case(
    *,
    output_key: str,
    index: int,
    requests: list[dict[str, Any]],
    tasks_by_id: dict[tuple[str, int], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    first = requests[0]
    case_id = f"{output_key}_problem_{index:04d}"
    label = label_for_request(first)
    canonical_value, alternatives, confidence = target_values_for_requests(requests, tasks_by_id)
    observer_input = observer_input_for_case(case_id, first, label)
    event_gt_id = event_gt_id_for_request(first, canonical_value)
    detail_gt_id = detail_gt_id_for_request(first, canonical_value, alternatives, label)

    event_gt = {
        "event_gt_id": event_gt_id,
        "event_type": first["event_mode"],
        "action": first.get("action"),
        "ordinal": first.get("ordinal"),
        "expected_time_range": None,
        "primary_content_range": None,
        "allowed_transition_range": None,
        "evidence_time_range": None,
        "expected_region": {
            "surface": (first.get("spatial_scope") or {}).get("surface"),
            "region_terms": (first.get("spatial_scope") or {}).get("region_terms") or [],
            "relative_terms": (first.get("spatial_scope") or {}).get("relative_terms") or [],
            "appearance_constraints": first.get("appearance_constraints") or [],
            "visible_text_constraints": first.get("visible_text_constraints") or [],
        },
        "center_time": None,
        "confidence": "low",
        "evidence": [
            "Generic weak bootstrap. Event timestamp GT is pending video inspection."
        ],
    }
    detail_gt = {
        "detail_gt_id": detail_gt_id,
        "target_kind": first["target_kind"],
        "canonical_value": canonical_value or "UNKNOWN",
        "acceptable_aliases": [],
        "negative_neighbors": [],
        "confidence": confidence,
        "alternative_values_due_to_ambiguous_source_grouping": alternatives,
        "notes": [
            "Weak bootstrap from scenario-level value when consistent; verify against video before freezing GT."
        ],
    }
    case = {
        "case_id": case_id,
        "problem_type": first["event_mode"],
        "video_path": first.get("image_path"),
        "menu_label": None,
        "observer_input": observer_input,
        "event_gt_id": event_gt_id,
        "detail_gt_id": detail_gt_id,
        "evaluation_modes": ["event_only", "detail_with_gt_event", "detail_with_predicted_event", "end_to_end"],
        "gt_status": "weak_bootstrap_needs_video_review",
        "case_gt_confidence": confidence,
        "alternative_values_due_to_ambiguous_source_grouping": alternatives,
        "human_review_priority": "medium" if canonical_value else "high",
        "source_task_ids": sorted({request["task_id"] for request in requests}),
        "source_request_ids": [request["request_id"] for request in requests],
        "source_consistency_notes": [
            "Generated by generic builder from normalized instruction-derived visual requests; verify against video before freezing GT."
        ],
        "visual_problem_key": visual_problem_key_for_observer_input(observer_input),
        "visual_problem_label": f"{first.get('image_path')}: {label}",
    }
    return case, event_gt, detail_gt


def load_existing_gt(output_dir: Path, output_key: str) -> dict[str, Any] | None:
    path = output_dir / f"observer_grounding_{output_key}_bootstrap.json"
    if not path.exists():
        return None
    try:
        gt = load_json(path)
    except json.JSONDecodeError:
        return None
    return {
        "cases_by_key": {case.get("visual_problem_key"): case for case in gt.get("eval_cases", [])},
        "cases_by_label": {case.get("visual_problem_label"): case for case in gt.get("eval_cases", [])},
        "events_by_id": {item.get("event_gt_id"): item for item in gt.get("event_ground_truths", [])},
        "details_by_id": {item.get("detail_gt_id"): item for item in gt.get("detail_ground_truths", [])},
    }


def existing_case_for(case: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any] | None:
    if not existing:
        return None
    return (
        existing["cases_by_key"].get(case.get("visual_problem_key"))
        or existing["cases_by_label"].get(case.get("visual_problem_label"))
    )


def copy_existing_event_gt(
    case: dict[str, Any],
    event_gt: dict[str, Any],
    existing: dict[str, Any] | None,
) -> None:
    old_case = existing_case_for(case, existing)
    if not old_case or not existing:
        return
    old_event = existing["events_by_id"].get(old_case.get("event_gt_id"))
    if not old_event:
        return
    for key in (
        "expected_time_range",
        "primary_content_range",
        "allowed_transition_range",
        "evidence_time_range",
        "center_time",
        "confidence",
        "evidence",
    ):
        if old_event.get(key) is not None:
            event_gt[key] = old_event[key]
    old_region = old_event.get("expected_region")
    if isinstance(event_gt.get("expected_region"), dict) and isinstance(old_region, dict):
        for key, value in old_region.items():
            if key not in event_gt["expected_region"] and value not in (None, [], ""):
                event_gt["expected_region"][key] = value
    elif old_region not in (None, "", [], {}):
        event_gt["expected_region"] = old_region
    if old_case.get("gt_status", "").startswith("video_event"):
        case["gt_status"] = old_case["gt_status"]


def merge_event_gt(target: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    target_has_time = target.get("primary_content_range") is not None
    incoming_has_time = incoming.get("primary_content_range") is not None
    if incoming_has_time and not target_has_time:
        return incoming
    if incoming_has_time and target_has_time:
        target_evidence = target.get("evidence") or []
        for item in incoming.get("evidence") or []:
            if item not in target_evidence:
                target_evidence.append(item)
        target["evidence"] = target_evidence
    return target


def merge_detail_gt(target: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    aliases = list(dict.fromkeys([*(target.get("acceptable_aliases") or []), *(incoming.get("acceptable_aliases") or [])]))
    alternatives = list(
        dict.fromkeys(
            [
                *(target.get("alternative_values_due_to_ambiguous_source_grouping") or []),
                *(incoming.get("alternative_values_due_to_ambiguous_source_grouping") or []),
            ]
        )
    )
    notes = list(dict.fromkeys([*(target.get("notes") or []), *(incoming.get("notes") or [])]))
    target["acceptable_aliases"] = aliases
    target["alternative_values_due_to_ambiguous_source_grouping"] = alternatives
    target["notes"] = notes
    return target


def source_values_for_requests(
    requests: list[dict[str, Any]],
    tasks_by_id: dict[tuple[str, int], dict[str, Any]],
) -> list[str]:
    values: list[str] = []
    for request in requests:
        value = tasks_by_id[task_lookup_key(request)].get("value")
        if isinstance(value, list):
            values.extend(str(item) for item in value if item not in (None, ""))
        elif value not in (None, ""):
            values.append(str(value))
    return list(dict.fromkeys(values))


def cluster_review_record(
    *,
    case: dict[str, Any],
    event_gt: dict[str, Any],
    detail_gt: dict[str, Any],
    requests: list[dict[str, Any]],
    tasks_by_id: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    first = requests[0]
    return {
        "case_id": case["case_id"],
        "visual_problem_label": case["visual_problem_label"],
        "problem_type": case["problem_type"],
        "video_path": case["video_path"],
        "event_gt_id": event_gt["event_gt_id"],
        "detail_gt_id": detail_gt["detail_gt_id"],
        "detail_canonical_value": detail_gt["canonical_value"],
        "detail_confidence": detail_gt["confidence"],
        "human_review_priority": case["human_review_priority"],
        "source_scenario_keys": sorted({request["scenario_key"] for request in requests}),
        "source_task_ids": case["source_task_ids"],
        "source_request_ids": case["source_request_ids"],
        "source_values": source_values_for_requests(requests, tasks_by_id),
        "normalized_slots": case["observer_input"]["slots"],
        "extraction_confidence_counts": dict(Counter(request.get("extraction_confidence") for request in requests)),
        "source_instruction_snippets": [
            {
                "request_id": request["request_id"],
                "scenario_key": request["scenario_key"],
                "task_id": request["task_id"],
                "snippet": request.get("review_source_instruction_snippet"),
            }
            for request in requests[:10]
        ],
        "grouping_key": visual_problem_key(first),
    }


def write_instruction_audit(
    work_dir: Path,
    requests: list[dict[str, Any]],
    tasks_by_id: dict[tuple[str, int], dict[str, Any]],
) -> None:
    rows = []
    for request in requests:
        rows.append(
            {
                "request_id": request["request_id"],
                "scenario_key": request["scenario_key"],
                "task_id": request["task_id"],
                "video_path": request.get("image_path"),
                "event_mode": request["event_mode"],
                "detail_mode": request["detail_mode"],
                "target_key": request["target_key"],
                "target_kind": request["target_kind"],
                "action": request.get("action"),
                "ordinal": request.get("ordinal"),
                "spatial_scope": request.get("spatial_scope") or {},
                "appearance_constraints": request.get("appearance_constraints") or [],
                "visible_text_constraints": request.get("visible_text_constraints") or [],
                "visual_task_group_key": request.get("visual_task_group_key"),
                "abstract_task_key": request.get("abstract_task_key"),
                "visual_referent_signature": visual_referent_signature(request),
                "scenario_value": tasks_by_id[task_lookup_key(request)].get("value"),
                "instruction_snippet": request.get("review_source_instruction_snippet"),
                "image_description": request.get("image_description"),
                "extraction_confidence": request.get("extraction_confidence"),
                "needs_review": request.get("needs_review"),
            }
        )
    write_jsonl(work_dir / "instruction_extraction_audit.jsonl", rows)
    lines = [
        "# Instruction Extraction Audit",
        "",
        f"- Visual requests: {len(rows)}",
        f"- Event modes: `{dict(Counter(row['event_mode'] for row in rows).most_common())}`",
        f"- Target keys: `{dict(Counter(row['target_key'] for row in rows).most_common())}`",
        "",
        "Review `instruction_extraction_audit.jsonl` for the full per-request extraction trace.",
        "",
    ]
    (work_dir / "instruction_extraction_audit_summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_cluster_review(work_dir: Path, records: list[dict[str, Any]]) -> None:
    write_json(work_dir / "visual_problem_cluster_review.json", records)
    lines = [
        "# Visual Problem Cluster Review",
        "",
        f"- Visual problem clusters: {len(records)}",
        f"- Problem types: `{dict(Counter(record['problem_type'] for record in records).most_common())}`",
        "",
        "## Clusters",
        "",
    ]
    for record in records:
        snippets = "; ".join(
            str(item.get("snippet") or "")[:160] for item in record["source_instruction_snippets"][:2]
        )
        lines.append(
            f"- `{record['case_id']}` `{record['visual_problem_label']}` "
            f"event=`{record['event_gt_id']}` detail=`{record['detail_gt_id']}` "
            f"expected=`{record['detail_canonical_value']}` sources={record['source_request_ids']} "
            f"snippets={snippets}"
        )
    (work_dir / "visual_problem_cluster_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_assets_for_paths(output_key: str, paths: list[Path], output_root: Path, max_tasks: int | None = None) -> dict[str, Any]:
    tasks_by_id: dict[tuple[str, int], dict[str, Any]] = {}
    requests: list[dict[str, Any]] = []
    source_scenario_keys: list[str] = []
    output_dir = output_root / f"observer_problem_set_{output_key}"
    existing = load_existing_gt(output_dir, output_key)
    for path in paths:
        scenario_key = path.stem
        source_scenario_keys.append(scenario_key)
        tasks = load_json(path)
        if max_tasks is not None:
            tasks = tasks[:max_tasks]
        for task_id, task in enumerate(tasks, start=1):
            tasks_by_id[(scenario_key, task_id)] = task
            requests.extend(normalize_visual_requests(scenario_key=scenario_key, task_id=task_id, task=task))

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for request in requests:
        grouped[visual_problem_key(request)].append(request)

    eval_cases: list[dict[str, Any]] = []
    excluded_cases: list[dict[str, Any]] = []
    event_gt_by_id: dict[str, dict[str, Any]] = {}
    detail_gt_by_id: dict[str, dict[str, Any]] = {}
    cluster_review_records: list[dict[str, Any]] = []
    for index, group_requests in enumerate(
        sorted(grouped.values(), key=lambda items: (str(items[0].get("image_path")), label_for_request(items[0]))),
        start=1,
    ):
        case, event_gt, detail_gt = build_case(
            output_key=output_key,
            index=index,
            requests=group_requests,
            tasks_by_id=tasks_by_id,
        )
        copy_existing_event_gt(case, event_gt, existing)
        if detail_gt.get("alternative_values_due_to_ambiguous_source_grouping"):
            case["gt_status"] = "excluded_under_specified_pending_human_review"
            case["human_review_priority"] = "high"
            case.setdefault("source_consistency_notes", []).append(
                "Excluded from strict eval because one normalized visual referent maps to multiple scenario values."
            )
            excluded_cases.append(case)
        else:
            eval_cases.append(case)
        if event_gt["event_gt_id"] in event_gt_by_id:
            event_gt_by_id[event_gt["event_gt_id"]] = merge_event_gt(event_gt_by_id[event_gt["event_gt_id"]], event_gt)
        else:
            event_gt_by_id[event_gt["event_gt_id"]] = event_gt
        if detail_gt["detail_gt_id"] in detail_gt_by_id:
            detail_gt_by_id[detail_gt["detail_gt_id"]] = merge_detail_gt(detail_gt_by_id[detail_gt["detail_gt_id"]], detail_gt)
        else:
            detail_gt_by_id[detail_gt["detail_gt_id"]] = detail_gt
        cluster_review_records.append(
            cluster_review_record(
                case=case,
                event_gt=event_gt,
                detail_gt=detail_gt,
                requests=group_requests,
                tasks_by_id=tasks_by_id,
            )
        )

    work_dir = output_dir / "_work"
    write_jsonl(work_dir / "normalized_visual_requests.jsonl", requests)
    write_instruction_audit(work_dir, requests, tasks_by_id)
    write_jsonl(work_dir / "observer_inputs.jsonl", [case["observer_input"] for case in eval_cases])
    write_json(work_dir / "observer_problem_set_draft.json", eval_cases)
    write_cluster_review(work_dir, cluster_review_records)
    write_json(
        work_dir / "observer_problem_type_summary.json",
        [
            {"problem_type": key, "count": value}
            for key, value in Counter(case["problem_type"] for case in eval_cases).most_common()
        ],
    )

    coverage = {
        "eval_case_count": len(eval_cases),
        "included_for_strict_eval": len(eval_cases),
        "excluded_under_specified_or_ambiguous": len(excluded_cases),
        "event_gt_count": len(event_gt_by_id),
        "detail_gt_count": len(detail_gt_by_id),
        "human_review_priority_counts": dict(Counter(case["human_review_priority"] for case in eval_cases)),
        "excluded_review_priority_counts": dict(Counter(case["human_review_priority"] for case in excluded_cases)),
        "detail_confidence_counts": dict(Counter(item["confidence"] for item in detail_gt_by_id.values())),
    }
    result = {
        "schema_version": "observer_grounding_eval_v1",
        "scenario_key": output_key,
        "status": "weak_bootstrap_needs_video_review",
        "purpose": (
            "Generic bootstrap GT for observer evaluation. Detail values are weak scenario-value "
            "anchors when consistent; event ranges require video inspection."
        ),
        "scoring_defaults": {
            "temporal_sequence_event": {
                "event_metric": "gt_primary_range_coverage_ratio",
                "pass_threshold": 0.8,
                "gt_range_status": "pending_video_inspection",
            },
            "static_spatial_region": {
                "event_metric": "gt_primary_range_coverage_ratio",
                "pass_threshold": 0.8,
                "gt_range_status": "pending_video_inspection",
            },
            "detail": {
                "metric": "canonical_or_alias_exact_match",
                "case_sensitive": False,
                "normalize_whitespace": True,
                "target_value_source": "weak scenario-value bootstrap when available",
            },
        },
        "coverage": coverage,
        "eval_cases": eval_cases,
        "excluded_cases": excluded_cases,
        "event_ground_truths": sorted(event_gt_by_id.values(), key=lambda item: item["event_gt_id"]),
        "detail_ground_truths": sorted(detail_gt_by_id.values(), key=lambda item: item["detail_gt_id"]),
    }
    gt_path = output_dir / f"observer_grounding_{output_key}_bootstrap.json"
    write_json(gt_path, result)
    write_visual_problem_summary(output_dir, result)
    write_summary(output_dir, result)
    return {"scenario_key": output_key, "source_scenario_keys": source_scenario_keys, "output_dir": str(output_dir), "coverage": coverage}


def build_assets_for_scenario(scenario_key: str, output_root: Path, max_tasks: int | None = None) -> dict[str, Any]:
    return build_assets_for_paths(scenario_key, [SCENARIOS_DIR / f"{scenario_key}.json"], output_root, max_tasks)


def write_visual_problem_summary(output_dir: Path, gt: dict[str, Any]) -> None:
    detail_by_id = {item["detail_gt_id"]: item for item in gt["detail_ground_truths"]}
    rows = []
    for case in gt["eval_cases"]:
        rows.append(
            {
                "visual_problem_key": case["visual_problem_key"],
                "visual_problem_label": case["visual_problem_label"],
                "problem_type": case["problem_type"],
                "case_count": 1,
                "case_ids": [case["case_id"]],
                "expected_values": [detail_by_id[case["detail_gt_id"]]["canonical_value"]],
                "source_task_ids": case.get("source_task_ids") or [],
            }
        )
    summary = {
        "schema_version": "observer_visual_problem_summary_v1",
        "scenario_key": gt["scenario_key"],
        "definition": "One visual problem is the same normalized visual referent within the same scenario video.",
        "eval_case_count": len(gt["eval_cases"]),
        "visual_problem_count": len(rows),
        "by_problem_type": dict(Counter(row["problem_type"] for row in rows).most_common()),
        "visual_problems": rows,
    }
    write_json(output_dir / "observer_visual_problem_summary.json", summary)
    lines = [
        "# Observer Visual Problem Summary",
        "",
        summary["definition"],
        "",
        f"- Eval cases: {summary['eval_case_count']}",
        f"- Visual problems: {summary['visual_problem_count']}",
        "",
        "## By Problem Type",
        "",
    ]
    for key, count in summary["by_problem_type"].items():
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Visual Problems", ""])
    for row in rows:
        lines.append(
            f"- `{row['problem_type']}` `{row['visual_problem_label']}` -> "
            f"expected={row['expected_values']}, cases={row['case_ids']}"
        )
    (output_dir / "observer_visual_problem_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(output_dir: Path, gt: dict[str, Any]) -> None:
    coverage = gt["coverage"]
    lines = [
        "# Observer Problem Set Summary",
        "",
        f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Scenario: `{gt['scenario_key']}`",
        f"Status: `{gt['status']}`",
        "",
        "## Files",
        "",
        f"- `observer_grounding_{gt['scenario_key']}_bootstrap.json`: evaluator input",
        "- `observer_visual_problem_summary.md`: visual problem browser",
        "- `_work/`: generated intermediate files",
        "",
        "## Coverage",
        "",
        f"- Eval cases: {coverage['eval_case_count']}",
        f"- Excluded/review-only cases: {coverage.get('excluded_under_specified_or_ambiguous', 0)}",
        f"- Event GT entries: {coverage['event_gt_count']}",
        f"- Detail GT entries: {coverage['detail_gt_count']}",
        f"- Review priorities: `{coverage['human_review_priority_counts']}`",
        f"- Excluded priorities: `{coverage.get('excluded_review_priority_counts', {})}`",
        "",
        "## Notes",
        "",
        "- This generic bootstrap is not a frozen human-reviewed GT set.",
        "- Event time ranges are pending video inspection.",
        "- Detail values are weak anchors from scenario `value` only when grouped requests agree.",
        "",
    ]
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["order", "retail", "restaurant", "kitchen"])
    parser.add_argument("--scenario_key", help="Exact scenario key, e.g. retail1.")
    parser.add_argument("--all_scenarios", action="store_true", help="Build every final scenario except order1 by default.")
    parser.add_argument("--include_order1", action="store_true", help="Allow rebuilding order1 with the generic builder.")
    parser.add_argument("--max_tasks", type=int)
    parser.add_argument("--output_root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = scenario_paths(args)
    if args.all_scenarios:
        paths = sorted(SCENARIOS_DIR.glob("*.json"))
    if not args.include_order1:
        paths = [path for path in paths if path.stem != "order1"]
    if not paths:
        raise SystemExit("No scenario files matched.")

    outputs = []
    if args.scenario and not args.scenario_key:
        outputs.append(build_assets_for_paths(args.scenario, paths, args.output_root, args.max_tasks))
    elif args.all_scenarios:
        by_family: dict[str, list[Path]] = defaultdict(list)
        for path in paths:
            by_family[scenario_prefix(path.stem)].append(path)
        for family, family_paths in sorted(by_family.items()):
            if family == "order" and not args.include_order1:
                continue
            outputs.append(build_assets_for_paths(family, sorted(family_paths), args.output_root, args.max_tasks))
    else:
        for path in paths:
            outputs.append(build_assets_for_scenario(path.stem, args.output_root, args.max_tasks))
    print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
