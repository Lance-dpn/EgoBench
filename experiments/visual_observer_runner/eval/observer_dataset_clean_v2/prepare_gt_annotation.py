#!/usr/bin/env python3
"""Prepare manual/video GT annotation assets for clean v2.

Inputs are limited to observer_dataset_clean_v2 and videos/. This script does
not read older bootstrap/problem-set files, DB files, eval_result, or scenario
final values.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = ROOT / "experiments/visual_observer_runner/eval/observer_dataset_clean_v2"
VIDEO_ROOT = ROOT / "videos"
ANNOTATION_ROOT = DATA_ROOT / "_annotation"
SCENARIOS = ("order", "retail", "restaurant", "kitchen")

BUSINESS_TERMS = (
    "price",
    "discount",
    "tax",
    "protein",
    "calorie",
    "kcal",
    "allergen",
    "sodium",
    "sugar",
    "fat",
    "fiber",
    "stock",
    "expired",
    "origin",
    "country",
    "nutrition",
    "nutritional",
    "low-fat",
    "low sugar",
    "high protein",
    "gluten-free",
    "set meal",
    "combo meal",
    "order",
    "cart",
)

INCOMPLETE_ENDINGS = (
    "of the",
    "for the",
    "with the",
    "to the",
    "from the",
    "above the",
    "left of the",
    "right of the",
    "and",
    "or",
    "that",
    "which",
    "does not",
    "do not",
    "are",
    "is",
)

GENERIC_HINTS = {
    "category",
    "section",
    "area",
    "dish",
    "item",
    "product",
    "recipe",
    "ingredient",
    "dishes you ordered",
    "dish does not",
    "dish with them",
    "wines that",
    "category for item",
    "category for items",
    "category for dishes",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def video_duration(video_path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        output = subprocess.check_output(cmd, text=True)
        return float(json.loads(output)["format"]["duration"])
    except Exception:
        return None


def ffmpeg_available() -> bool:
    try:
        subprocess.check_call(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def safe_video_name(video_id: str) -> str:
    return Path(video_id).stem.replace(" ", "_")


def extract_frames(video_id: str, fps: float = 1.0) -> dict[str, Any]:
    video_path = VIDEO_ROOT / video_id
    out_dir = ANNOTATION_ROOT / "frames" / safe_video_name(video_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = video_duration(video_path)
    if not video_path.exists():
        return {"video_id": video_id, "status": "missing_video", "duration": None, "frames": [], "contact_sheet": None}
    if duration is None:
        return {"video_id": video_id, "status": "duration_failed", "duration": None, "frames": [], "contact_sheet": None}
    if not ffmpeg_available():
        return {"video_id": video_id, "status": "ffmpeg_unavailable", "duration": duration, "frames": [], "contact_sheet": None}

    frame_paths = []
    # Keep deterministic integer-second frames. The +0.1 avoids requesting a
    # frame exactly past EOF due to rounded durations.
    for sec in range(0, max(1, math.ceil(duration))):
        out = out_dir / f"t{sec:02d}.jpg"
        if not out.exists():
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                f"{sec:.2f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=640:-1,drawtext=text='%{pts\\:hms}':x=12:y=12:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.55",
                str(out),
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if out.exists():
            frame_paths.append(str(out.relative_to(ROOT)))

    sheet = out_dir / "contact_sheet.jpg"
    if frame_paths and not sheet.exists():
        tile_cols = 5
        tile_rows = math.ceil(len(frame_paths) / tile_cols)
        cmd = [
            "ffmpeg",
            "-y",
            "-pattern_type",
            "glob",
            "-i",
            str(out_dir / "t*.jpg"),
            "-vf",
            f"scale=360:-1,tile={tile_cols}x{tile_rows}:padding=8:margin=8",
            str(sheet),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    labeled_sheet = create_labeled_contact_sheet(out_dir)
    return {
        "video_id": video_id,
        "status": "ready",
        "duration": duration,
        "frames": frame_paths,
        "contact_sheet": str(sheet.relative_to(ROOT)) if sheet.exists() else None,
        "labeled_contact_sheet": str(labeled_sheet.relative_to(ROOT)) if labeled_sheet else None,
    }


def create_labeled_contact_sheet(frame_dir: Path) -> Path | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    frames = sorted(frame_dir.glob("t*.jpg"))
    if not frames:
        return None
    thumbs = []
    for frame in frames:
        img = Image.open(frame).convert("RGB")
        img.thumbnail((360, 220))
        tile = Image.new("RGB", (360, 250), "white")
        tile.paste(img, ((360 - img.width) // 2, 28))
        draw = ImageDraw.Draw(tile)
        label = frame.stem.replace("t", "t=") + "s"
        draw.rectangle((0, 0, 360, 26), fill=(20, 20, 20))
        draw.text((10, 5), label, fill="white")
        thumbs.append(tile)
    cols = 5
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * 360, rows * 250), "white")
    for i, tile in enumerate(thumbs):
        x = (i % cols) * 360
        y = (i // cols) * 250
        sheet.paste(tile, (x, y))
    out = frame_dir / "contact_sheet_labeled.jpg"
    sheet.save(out, quality=92)
    return out


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        data = load_json(DATA_ROOT / scenario / "05_observer_dataset_with_gt.json")
        for case in data["cases"]:
            cases.append(case)
    return cases


def hint(case: dict[str, Any]) -> str:
    return str(case["visual_query_v1"]["referent"]["appearance"].get("content_hint") or "").strip()


def quality_reasons(case: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    h = hint(case)
    low = h.lower()
    vq = case["visual_query_v1"]
    ref = vq["referent"]
    target = vq["target"]["kind"]
    snippets = " ".join(case.get("source_instruction_snippets") or []).lower()

    if not h:
        reasons.append("missing_content_hint")
    if len(h) < 10:
        reasons.append("content_hint_too_short")
    if low in GENERIC_HINTS:
        reasons.append("generic_visual_reference")
    if low.endswith(INCOMPLETE_ENDINGS):
        reasons.append("incomplete_reference_tail")
    if "user id" in low or "enthusiast" in low or "suitable for pairing" in low:
        reasons.append("context_not_visual_referent")
    if any(term in low for term in BUSINESS_TERMS):
        reasons.append("business_fact_leak_in_visual_hint")
    if target in {"dish_name", "product_name", "ingredient_name", "recipe_name"} and ref["type"] == "static_region":
        if not any([ref.get("ordinal"), ref.get("action"), ref.get("region", {}).get("side"), ref.get("region", {}).get("vertical"), ref["appearance"].get("color"), ref["appearance"].get("style")]):
            reasons.append("underspecified_identity_without_visual_anchor")
    if re.search(r"\b(this|that|it|them)\b", low) and not any(word in low for word in ("point", "left", "right", "top", "bottom", "color", "label", "tray", "board", "pot", "wok")):
        reasons.append("unresolved_pronoun_reference")
    if "category as " in low or "category for " in low:
        reasons.append("db_or_textual_category_not_visual_region")
    if " in the order" in snippets or "current order" in snippets:
        reasons.append("source_clause_may_be_business_order_state")

    severe = {
        "missing_content_hint",
        "content_hint_too_short",
        "generic_visual_reference",
        "incomplete_reference_tail",
        "context_not_visual_referent",
        "unresolved_pronoun_reference",
        "db_or_textual_category_not_visual_region",
    }
    if any(reason in severe for reason in reasons):
        status = "exclude_suggested"
    elif reasons:
        status = "review_required"
    else:
        status = "annotation_ready"
    return status, reasons


def build_worklists(cases: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for case in cases:
        status, reasons = quality_reasons(case)
        rows.append(
            {
                "case_id": case["case_id"],
                "scenario": case["scenario"],
                "video_id": case["video_id"],
                "quality_status": status,
                "quality_reasons": reasons,
                "visual_query_v1": case["visual_query_v1"],
                "source_task_ids": case.get("source_task_ids") or [],
                "source_instruction_snippets": case.get("source_instruction_snippets") or [],
            }
        )

    by_video: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_video[row["video_id"]].append(row)

    video_summary = {}
    for video_id, video_rows in sorted(by_video.items()):
        video_summary[video_id] = {
            "total_cases": len(video_rows),
            "annotation_ready": sum(row["quality_status"] == "annotation_ready" for row in video_rows),
            "review_required": sum(row["quality_status"] == "review_required" for row in video_rows),
            "exclude_suggested": sum(row["quality_status"] == "exclude_suggested" for row in video_rows),
        }
    return {
        "schema_version": "gt_annotation_worklist_v1",
        "source_dataset": "observer_dataset_clean_v2",
        "policy": {
            "gt_source": "actual video inspection only",
            "excluded_from_input": ["old bootstrap", "observer_problem_set_*", "final key/value", "DB/tool data"],
        },
        "summary": {
            "total_cases": len(rows),
            "annotation_ready": sum(row["quality_status"] == "annotation_ready" for row in rows),
            "review_required": sum(row["quality_status"] == "review_required" for row in rows),
            "exclude_suggested": sum(row["quality_status"] == "exclude_suggested" for row in rows),
            "by_video": video_summary,
            "reason_counts": dict(Counter(reason for row in rows for reason in row["quality_reasons"]).most_common()),
        },
        "cases": rows,
    }


def write_markdown(worklist: dict[str, Any], frame_manifest: dict[str, Any]) -> None:
    lines = [
        "# GT Annotation Review",
        "",
        "This worklist is generated from clean v2 only. GT must be filled by inspecting video frames.",
        "",
        "## Summary",
        "",
    ]
    for key, value in worklist["summary"].items():
        if key != "by_video":
            lines.append(f"- {key}: {value}")
    lines.extend(["", "## Videos"])
    for video_id, summary in worklist["summary"]["by_video"].items():
        frames = frame_manifest.get(video_id, {})
        sheet = frames.get("labeled_contact_sheet") or frames.get("contact_sheet")
        lines.append(
            f"- `{video_id}`: total={summary['total_cases']}, ready={summary['annotation_ready']}, "
            f"review={summary['review_required']}, exclude_suggested={summary['exclude_suggested']}, "
            f"sheet=`{sheet}`"
        )
    lines.extend(["", "## Suggested Exclusions"])
    for row in worklist["cases"]:
        if row["quality_status"] != "exclude_suggested":
            continue
        q = row["visual_query_v1"]
        lines.append(
            f"- `{row['case_id']}` `{row['video_id']}` reasons={row['quality_reasons']} "
            f"hint={q['referent']['appearance'].get('content_hint')!r}"
        )
    write_text(ANNOTATION_ROOT / "annotation_review.md", "\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-frames", action="store_true")
    args = parser.parse_args()

    cases = load_cases()
    worklist = build_worklists(cases)

    frame_manifest = {}
    if not args.skip_frames:
        for video_id in sorted(worklist["summary"]["by_video"]):
            frame_manifest[video_id] = extract_frames(video_id)
    else:
        frame_manifest = {video_id: {"video_id": video_id, "status": "skipped"} for video_id in worklist["summary"]["by_video"]}

    write_json(ANNOTATION_ROOT / "gt_annotation_worklist.json", worklist)
    write_json(
        ANNOTATION_ROOT / "low_quality_candidates.json",
        {
            "schema_version": "low_quality_candidates_v1",
            "summary": worklist["summary"],
            "cases": [row for row in worklist["cases"] if row["quality_status"] != "annotation_ready"],
        },
    )
    write_json(
        ANNOTATION_ROOT / "annotation_ready_cases.json",
        {
            "schema_version": "annotation_ready_cases_v1",
            "cases": [row for row in worklist["cases"] if row["quality_status"] == "annotation_ready"],
        },
    )
    write_json(
        ANNOTATION_ROOT / "quality_decisions_draft.json",
        {
            "schema_version": "quality_decisions_draft_v1",
            "notes": [
                "Edit decision to keep/exclude/review after manual inspection.",
                "Suggested exclusions are not applied to 05_observer_dataset_with_gt.json until explicitly reviewed.",
            ],
            "decisions": [
                {
                    "case_id": row["case_id"],
                    "video_id": row["video_id"],
                    "suggested_status": row["quality_status"],
                    "decision": "exclude" if row["quality_status"] == "exclude_suggested" else "keep" if row["quality_status"] == "annotation_ready" else "review",
                    "reasons": row["quality_reasons"],
                    "comment": "",
                }
                for row in worklist["cases"]
            ],
        },
    )
    write_json(ANNOTATION_ROOT / "frame_manifest.json", frame_manifest)
    write_markdown(worklist, frame_manifest)
    print(json.dumps(worklist["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
