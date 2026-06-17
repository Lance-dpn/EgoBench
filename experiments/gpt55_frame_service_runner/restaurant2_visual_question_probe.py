"""Extract and probe restaurant2 visual referents with the frame service prompt."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experiments.gpt55_frame_service_runner.openai_responses_client import OpenAIResponsesServiceClient
from experiments.gpt55_frame_service_runner.prompts.service import SERVICE_PROMPT_VERSION, build_service_agent_prompt
from experiments.gpt55_frame_service_runner.run_frame_agent import parse_task_ids, prepare_frames, response_input_items


VISUAL_WORD_RE = re.compile(
    r"\b("
    r"point|pointed|pointing|last|first|second|third|initial|initially|"
    r"category|section|area|panel|card|fold|foldout|fold-out|flap|leaflet|brochure|menu|"
    r"left|right|top|bottom|middle|center|below|above|border|background|font|text|"
    r"hand|illustration|dark|white|small|smaller|supplementary"
    r")\b",
    re.IGNORECASE,
)

ACTION_WORD_RE = re.compile(
    r"\b("
    r"determine|contains?|find|filter|select|add|calculate|compute|tax|price|protein|"
    r"calories|kcal|sodium|fat|carb|fiber|discount|allergen|gluten|dairy|vegan|sale"
    r")\b",
    re.IGNORECASE,
)

SPLIT_RE = re.compile(
    r"(?<=[.!?])\s+|"
    r"(?=\bIf so\b)|(?=\bOtherwise\b)|(?=\bNext\b)|(?=\bThen\b)|"
    r"(?=\bAfter that\b)|(?=\bSubsequently\b)|(?=\bFinally\b)",
    re.IGNORECASE,
)


CURATED_RESTAURANT2_ANCHORS: list[dict[str, Any]] = [
    {
        "visual_question_id": "restaurant2_curated_001_left_top_section",
        "referent_type": "category",
        "visual_clause": "Identify the category/section in the top white rounded box on the leftmost foldout.",
        "normalized_anchor": "left foldout top section",
        "source_question_ids": [
            "restaurant2_task01_visual01",
            "restaurant2_task14_visual01",
            "restaurant2_task17_visual05",
            "restaurant2_task20_visual04",
            "restaurant2_task25_visual01",
            "restaurant2_task28_visual02",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_002_left_middle_card",
        "referent_type": "category",
        "visual_clause": "Identify the independent small card or white rounded box in the middle of the left foldout.",
        "normalized_anchor": "left foldout middle card",
        "source_question_ids": [
            "restaurant2_task02_visual01",
            "restaurant2_task05_visual02",
            "restaurant2_task12_visual04",
            "restaurant2_task19_visual05",
            "restaurant2_task10_visual03",
            "restaurant2_task21_visual05",
            "restaurant2_task22_visual04",
            "restaurant2_task15_visual01",
            "restaurant2_task30_visual01",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_003_left_bottom_card",
        "referent_type": "category",
        "visual_clause": "Identify the independent small card or white rounded box at the bottom of the left foldout.",
        "normalized_anchor": "left foldout bottom card",
        "source_question_ids": [
            "restaurant2_task04_visual04",
            "restaurant2_task08_visual01",
            "restaurant2_task18_visual01",
            "restaurant2_task23_visual05",
            "restaurant2_task26_visual01",
            "restaurant2_task06_visual05",
            "restaurant2_task11_visual05",
            "restaurant2_task27_visual04",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_004_middle_top_section",
        "referent_type": "category",
        "visual_clause": "Identify the top section of the middle foldout or middle panel.",
        "normalized_anchor": "middle foldout top section",
        "source_question_ids": [
            "restaurant2_task01_visual03",
            "restaurant2_task04_visual01",
            "restaurant2_task11_visual03",
            "restaurant2_task13_visual01",
            "restaurant2_task14_visual05",
            "restaurant2_task19_visual01",
            "restaurant2_task21_visual03",
            "restaurant2_task26_visual05",
            "restaurant2_task27_visual05",
            "restaurant2_task17_visual01",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_005_middle_right_border_hand",
        "referent_type": "category",
        "visual_clause": "Identify the category on the middle foldout whose right border has a small hand illustration.",
        "normalized_anchor": "middle foldout right-border hand illustration",
        "source_question_ids": [
            "restaurant2_task03_visual04",
            "restaurant2_task06_visual04",
            "restaurant2_task10_visual05",
            "restaurant2_task15_visual05",
            "restaurant2_task20_visual05",
            "restaurant2_task07_visual05",
            "restaurant2_task12_visual03",
            "restaurant2_task16_visual04",
            "restaurant2_task25_visual05",
            "restaurant2_task28_visual03",
            "restaurant2_task30_visual05",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_006_middle_lower_left_title_hand",
        "referent_type": "category",
        "visual_clause": "Identify the lower-middle section of the middle foldout whose title has a small hand illustration on the left.",
        "normalized_anchor": "middle foldout lower-middle title-left hand illustration",
        "source_question_ids": [
            "restaurant2_task02_visual02",
            "restaurant2_task09_visual01",
            "restaurant2_task15_visual03",
            "restaurant2_task18_visual04",
            "restaurant2_task23_visual01",
            "restaurant2_task24_visual01",
            "restaurant2_task29_visual01",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_007_right_top_section",
        "referent_type": "category",
        "visual_clause": "Identify the top section of the right foldout or right panel.",
        "normalized_anchor": "right foldout top section",
        "source_question_ids": [
            "restaurant2_task04_visual02",
            "restaurant2_task07_visual01",
            "restaurant2_task12_visual01",
            "restaurant2_task21_visual01",
            "restaurant2_task28_visual01",
            "restaurant2_task30_visual04",
            "restaurant2_task01_visual05",
            "restaurant2_task18_visual05",
            "restaurant2_task22_visual05",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_008_right_left_border_hand",
        "referent_type": "category",
        "visual_clause": "Identify the section on the right foldout whose left border has a small hand illustration.",
        "normalized_anchor": "right foldout left-border hand illustration",
        "source_question_ids": [
            "restaurant2_task08_visual03",
            "restaurant2_task09_visual05",
            "restaurant2_task10_visual01",
            "restaurant2_task17_visual03",
            "restaurant2_task20_visual01",
            "restaurant2_task14_visual03",
            "restaurant2_task25_visual04",
            "restaurant2_task26_visual04",
            "restaurant2_task27_visual01",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_009_right_dark_background",
        "referent_type": "category",
        "visual_clause": "Identify the exclusive dark-background section with white text on the right foldout.",
        "normalized_anchor": "right foldout dark-background section",
        "source_question_ids": [
            "restaurant2_task03_visual03",
            "restaurant2_task06_visual01",
            "restaurant2_task07_visual04",
            "restaurant2_task09_visual03",
            "restaurant2_task13_visual02",
            "restaurant2_task16_visual01",
            "restaurant2_task19_visual03",
            "restaurant2_task23_visual04",
            "restaurant2_task24_visual04",
            "restaurant2_task29_visual04",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_010_bottom_right_bread_section",
        "referent_type": "category",
        "visual_clause": "Identify the smaller homemade bread or supplementary section in the bottom-right corner of the menu.",
        "normalized_anchor": "bottom-right handmade bread section",
        "source_question_ids": [
            "restaurant2_task02_visual03",
            "restaurant2_task05_visual03",
            "restaurant2_task11_visual01",
            "restaurant2_task13_visual04",
            "restaurant2_task16_visual05",
            "restaurant2_task22_visual01",
            "restaurant2_task24_visual03",
            "restaurant2_task29_visual03",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_011_first_pointed_category",
        "referent_type": "sequence",
        "visual_clause": "Identify the first category or section that the user points at chronologically in the video.",
        "normalized_anchor": "first pointed category sequence",
        "source_question_ids": [
            "restaurant2_task03_visual01",
            "restaurant2_task06_visual03",
            "restaurant2_task08_visual04",
            "restaurant2_task09_visual04",
            "restaurant2_task13_visual03",
            "restaurant2_task18_visual03",
            "restaurant2_task26_visual03",
            "restaurant2_task27_visual03",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_012_second_pointed_category",
        "referent_type": "sequence",
        "visual_clause": "Identify the second category or section that the user points at chronologically in the video.",
        "normalized_anchor": "second pointed category sequence",
        "source_question_ids": ["restaurant2_task02_visual04", "restaurant2_task03_visual05", "restaurant2_task10_visual04", "restaurant2_task12_visual05", "restaurant2_task20_visual03", "restaurant2_task23_visual03", "restaurant2_task25_visual03", "restaurant2_task29_visual05"],
    },
    {
        "visual_question_id": "restaurant2_curated_013_third_pointed_category",
        "referent_type": "sequence",
        "visual_clause": "Identify the third category or section that the user points at chronologically in the video.",
        "normalized_anchor": "third pointed category sequence",
        "source_question_ids": ["restaurant2_task14_visual04", "restaurant2_task30_visual03"],
    },
    {
        "visual_question_id": "restaurant2_curated_014_last_pointed_category",
        "referent_type": "sequence",
        "visual_clause": "Identify the last category or section that the user points at chronologically in the video.",
        "normalized_anchor": "last pointed category sequence",
        "source_question_ids": [
            "restaurant2_task04_visual03",
            "restaurant2_task05_visual04",
            "restaurant2_task08_visual02",
            "restaurant2_task11_visual04",
            "restaurant2_task17_visual04",
            "restaurant2_task19_visual04",
            "restaurant2_task21_visual04",
            "restaurant2_task22_visual03",
            "restaurant2_task24_visual02",
            "restaurant2_task28_visual04",
        ],
    },
    {
        "visual_question_id": "restaurant2_curated_015_below_second_pointed_hand_panel",
        "referent_type": "category",
        "visual_clause": "Identify the panel below the second pointed category that has a small hand illustration on its left border.",
        "normalized_anchor": "below second pointed category with left-border hand",
        "source_question_ids": ["restaurant2_task05_visual01", "restaurant2_task02_visual04"],
    },
    {
        "visual_question_id": "restaurant2_curated_016_below_initially_pointed_section",
        "referent_type": "category",
        "visual_clause": "Identify the category located below the section the user initially pointed to.",
        "normalized_anchor": "below initially pointed section",
        "source_question_ids": ["restaurant2_task16_visual03"],
    },
    {
        "visual_question_id": "restaurant2_curated_017_right_of_initially_pointed_category",
        "referent_type": "category",
        "visual_clause": "Identify the section to the right of the category the user initially points at.",
        "normalized_anchor": "right of initially pointed category",
        "source_question_ids": ["restaurant2_task07_visual03"],
    },
]


def clean_text(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = re.sub(r"^Results:\s*", "", value, flags=re.IGNORECASE)
    return value


def split_instruction(instruction: str) -> list[str]:
    text = clean_text(instruction)
    parts = [part.strip(" .") for part in SPLIT_RE.split(text) if part and part.strip(" .")]
    merged: list[str] = []
    for part in parts:
        if len(part) < 18:
            continue
        merged.append(part)
    return merged


def is_visual_clause(clause: str) -> bool:
    if not VISUAL_WORD_RE.search(clause):
        return False
    # Keep clauses that describe a visual anchor even if they also contain business logic.
    strong_anchor = re.search(
        r"\b(category|section|area|panel|card|fold|foldout|fold-out|flap|leaflet|brochure|point|pointed|pointing)\b",
        clause,
        re.IGNORECASE,
    )
    menu_spatial_anchor = re.search(
        r"\b(menu)\b.*\b(left|right|top|bottom|middle|center|below|above|border|background|hand|illustration)\b|"
        r"\b(left|right|top|bottom|middle|center|below|above|border|background|hand|illustration)\b.*\b(menu)\b",
        clause,
        re.IGNORECASE,
    )
    return bool(strong_anchor or menu_spatial_anchor)


def classify_clause(clause: str) -> str:
    text = clause.lower()
    if any(word in text for word in ["dish", "dishes", "meal", "bread", "item"]):
        if any(word in text for word in ["category", "section", "area", "panel", "card"]):
            return "dish_within_visual_boundary"
        return "dish_pointing_or_visible_item"
    if any(word in text for word in ["category", "section", "area", "panel", "card", "fold", "flap", "leaflet"]):
        return "category_or_section_localization"
    return "visual_reference"


def build_probe_question(case: dict[str, Any]) -> str:
    instruction = case.get("instruction") or (
        "Curated restaurant2 visual-grounding question. Resolve only the visible menu anchor or pointing sequence."
    )
    return (
        "Diagnostic visual grounding probe for restaurant2. Do not call tools. "
        "Use only the attached timestamped frames and the instruction context. "
        "Resolve the visual referent in the clause below. If the clause contains business facts "
        "such as price, nutrition, allergens, tax, discount, sale status, or ranking, do not solve "
        "those facts; only identify the visual category/section/dish/boundary needed before tools. "
        "Return exactly one JSON object and no prose with this schema: "
        '{"visual_question_id":"...","referent_type":"category|section|dish|region|sequence|unknown",'
        '"answer":"...","confidence":"high|medium|low","evidence_frames":["F000"],'
        '"visual_reason":"brief"}\n\n'
        f"visual_question_id: {case['visual_question_id']}\n"
        f"task_id: {case['task_id']}\n"
        f"full_instruction: {instruction}\n"
        f"visual_clause: {case['visual_clause']}\n"
        f"expected_output_focus: {case['expected_output_focus']}\n"
    )


def extract_cases(scenario_path: Path, task_ids: list[int] | None = None) -> list[dict[str, Any]]:
    tasks = json.loads(scenario_path.read_text(encoding="utf-8"))
    selected_ids = set(task_ids or [])
    cases: list[dict[str, Any]] = []
    for task in tasks:
        task_id = int(task["task_id"])
        if selected_ids and task_id not in selected_ids:
            continue
        instruction = clean_text(task["Instruction"])
        visual_idx = 0
        for clause in split_instruction(instruction):
            if not is_visual_clause(clause):
                continue
            visual_idx += 1
            focus = classify_clause(clause)
            case_id = f"restaurant2_task{task_id:02d}_visual{visual_idx:02d}"
            cases.append(
                {
                    "visual_question_id": case_id,
                    "scenario": "restaurant",
                    "scenario_number": 2,
                    "task_id": task_id,
                    "expected_output_focus": focus,
                    "visual_clause": clause,
                    "instruction": instruction,
                    "probe_question": "",
                }
            )
    for case in cases:
        case["probe_question"] = build_probe_question(case)
    return cases


def build_curated_cases(raw_cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_by_id = {case["visual_question_id"]: case for case in raw_cases}
    used_source_ids: set[str] = set()
    curated_cases: list[dict[str, Any]] = []

    for idx, anchor in enumerate(CURATED_RESTAURANT2_ANCHORS, start=1):
        source_cases = [raw_by_id[source_id] for source_id in anchor["source_question_ids"] if source_id in raw_by_id]
        used_source_ids.update(case["visual_question_id"] for case in source_cases)
        case = {
            "visual_question_id": anchor["visual_question_id"],
            "scenario": "restaurant",
            "scenario_number": 2,
            "task_id": f"curated_{idx:03d}",
            "expected_output_focus": anchor["referent_type"],
            "referent_type": anchor["referent_type"],
            "normalized_anchor": anchor["normalized_anchor"],
            "visual_clause": anchor["visual_clause"],
            "instruction": (
                "Curated restaurant2 visual-grounding probe. The source instructions use different wording "
                "for the same visual referent; answer this normalized visual question only."
            ),
            "source_question_ids": anchor["source_question_ids"],
            "source_examples": [
                {
                    "visual_question_id": case["visual_question_id"],
                    "task_id": case["task_id"],
                    "visual_clause": case["visual_clause"],
                }
                for case in source_cases[:8]
            ],
            "probe_question": "",
        }
        case["probe_question"] = build_probe_question(case)
        curated_cases.append(case)

    removed_cases: list[dict[str, Any]] = []
    for case in raw_cases:
        if case["visual_question_id"] in used_source_ids:
            continue
        reason = "business_or_context_continuation_without_independent_visual_anchor"
        clause = case["visual_clause"].lower()
        if any(token in clause for token in ["this category", "that section", "that area", "this section", "if it", "if they"]):
            reason = "context_dependent_business_clause"
        if "category containing the last dish" in clause:
            reason = "ambiguous_dish_to_category_reference"
        removed_cases.append(
            {
                "visual_question_id": case["visual_question_id"],
                "task_id": case["task_id"],
                "visual_clause": case["visual_clause"],
                "reason": reason,
            }
        )

    return curated_cases, removed_cases


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_video(path_text: str) -> Path:
    path = Path(path_text)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([PROJECT_ROOT / path, PROJECT_ROOT / "videos" / path.name])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Video not found: {path_text}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract and probe restaurant2 visual grounding questions.")
    parser.add_argument("--scenario_path", default=str(PROJECT_ROOT / "scenarios" / "final" / "restaurant2.json"))
    parser.add_argument("--video", default=str(PROJECT_ROOT / "videos" / "restaurant2.mp4"))
    parser.add_argument("--scenario", default="restaurant")
    parser.add_argument("--scenario_number", type=int, default=2)
    parser.add_argument("--task_ids", default="", help="Comma/range list, e.g. 2,5,8,16 or 1-30.")
    parser.add_argument("--max_questions", type=int, default=0, help="Limit questions after extraction. 0 means all.")
    parser.add_argument("--curated", action="store_true", help="Use the manually reviewed deduplicated restaurant2 visual question set.")
    parser.add_argument("--run", action="store_true", help="Call the service model. Without this, only writes questions.")
    parser.add_argument("--output_dir", default=str(PROJECT_ROOT / "experiments" / "gpt55_frame_service_runner" / "cache" / "restaurant2_visual_probe"))
    parser.add_argument("--frame_cache_dir", default=str(PROJECT_ROOT / "experiments" / "gpt55_frame_service_runner" / "cache" / "restaurant2_visual_probe" / "frames"))
    parser.add_argument("--frame_fps", type=float, default=2.0)
    parser.add_argument("--frame_max_side", type=int, default=1920)
    parser.add_argument("--frame_rotation", choices=["none", "clockwise", "counterclockwise", "180"], default="none")
    parser.add_argument("--jpeg_quality", type=int, default=3)
    parser.add_argument("--max_frames", type=int, default=0)
    parser.add_argument("--refresh_frames", action="store_true")
    parser.add_argument("--image_detail", choices=["low", "auto", "high"], default="high")
    parser.add_argument("--reasoning_effort", choices=["none", "low", "medium", "high"], default=os.environ.get("SERVICE_REASONING_EFFORT", "low"))
    parser.add_argument("--temperature", type=float, default=float(os.environ.get("SERVICE_TEMPERATURE", "0") or 0))
    parser.add_argument("--service_model_name", default=os.environ.get("LANCE_SERVICE_MODEL_NAME") or os.environ.get("SERVICE_MODEL_NAME") or "gpt-5.5")
    parser.add_argument("--service_api_key", default=os.environ.get("LANCE_SERVICE_API_KEY") or os.environ.get("SERVICE_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--service_api_base_url", default=os.environ.get("LANCE_SERVICE_API_BASE_URL") or os.environ.get("SERVICE_API_BASE_URL") or os.environ.get("OPENAI_BASE_URL"))
    parser.add_argument("--max_output_tokens", type=int, default=1200)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max_retries", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task_ids = parse_task_ids(args.task_ids) if args.task_ids.strip() else None
    output_dir = Path(args.output_dir)
    scenario_path = Path(args.scenario_path)
    video_path = resolve_video(args.video)

    raw_cases = extract_cases(scenario_path, task_ids=task_ids)
    raw_questions_path = output_dir / "restaurant2_visual_questions.json"
    write_json(
        raw_questions_path,
        {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "count": len(raw_cases), "cases": raw_cases},
    )
    print(f"🧩 [Questions] extracted={len(raw_cases)} path={raw_questions_path}", flush=True)

    removed_cases: list[dict[str, Any]] = []
    if args.curated:
        cases, removed_cases = build_curated_cases(raw_cases)
        questions_path = output_dir / "restaurant2_visual_questions_curated.json"
        write_json(
            questions_path,
            {
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "source_count": len(raw_cases),
                "count": len(cases),
                "removed_count": len(removed_cases),
                "curation_policy": [
                    "Merge visual questions that resolve to the same menu anchor or pointing-sequence anchor.",
                    "Remove clauses that only ask business/database facts about an already resolved visual anchor.",
                    "Remove clauses whose visual referent is underspecified without previous business context.",
                    "Keep source_question_ids so every curated case can be traced back to raw task clauses.",
                ],
                "cases": cases,
                "removed_cases": removed_cases,
            },
        )
        print(f"🧹 [Curated] kept={len(cases)} removed={len(removed_cases)} path={questions_path}", flush=True)
    else:
        cases = raw_cases
        questions_path = raw_questions_path

    if args.max_questions and len(cases) > args.max_questions:
        cases = cases[: args.max_questions]

    tool_descriptions = "No tools are available for this diagnostic visual-grounding probe."
    prompt = build_service_agent_prompt(tool_descriptions=tool_descriptions, scenario="restaurant", scenario_number=2)
    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run": bool(args.run),
        "model": args.service_model_name,
        "prompt_version": SERVICE_PROMPT_VERSION,
        "scenario": "restaurant",
        "scenario_number": 2,
        "video": str(video_path),
        "frame_fps": args.frame_fps,
        "frame_max_side": args.frame_max_side,
        "frame_rotation": args.frame_rotation,
        "image_detail": args.image_detail,
        "reasoning_effort": args.reasoning_effort,
        "temperature": args.temperature,
        "cases": [],
    }
    report_path = output_dir / (
        "restaurant2_visual_probe_results_curated.json" if args.curated else "restaurant2_visual_probe_results.json"
    )
    write_json(report_path, report)

    if not args.run:
        print(f"📝 [Dry] wrote report stub={report_path}", flush=True)
        return

    frames = prepare_frames(args, video_path)
    print(f"🖼️ [Frames] {len(frames)} frames from {video_path}", flush=True)
    client = OpenAIResponsesServiceClient(
        model=args.service_model_name,
        api_key=args.service_api_key,
        base_url=args.service_api_base_url,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.max_output_tokens,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )

    frame_header = (
        "The following images are uniformly sampled frames from restaurant2.mp4. "
        "They are chronological; each image is preceded by frame id and timestamp. "
        "Use stable adjacent frames for pointing order and menu-section localization."
    )
    for idx, case in enumerate(cases, start=1):
        print(f"🔎 [Probe] {idx}/{len(cases)} {case['visual_question_id']}", flush=True)
        input_items = response_input_items(
            [{"role": "user", "content": case["probe_question"]}],
            frames=frames,
            attach_frames=True,
            image_detail=args.image_detail,
            frame_header=frame_header,
        )
        start = time.time()
        row = {key: case[key] for key in ("visual_question_id", "task_id", "expected_output_focus", "visual_clause")}
        try:
            result = client.create(instructions=prompt, input_items=input_items)
        except Exception as exc:
            row.update({"status": "error", "error": str(exc), "elapsed_seconds": round(time.time() - start, 3)})
            print(f"❌ [Probe] {case['visual_question_id']} error={exc}", flush=True)
        else:
            row.update(
                {
                    "status": "ok",
                    "model_text": result.text,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "elapsed_seconds": round(time.time() - start, 3),
                }
            )
            print(f"🤖 [Probe Answer] {result.text}", flush=True)
        report["cases"].append(row)
        write_json(report_path, report)

    print(f"✅ [Done] results={report_path}", flush=True)


if __name__ == "__main__":
    main()
